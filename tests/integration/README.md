# LLM Integration Tests

Most of these tests run a "driver" LLM as the player against the real GM
LLM, verifying the full two-call pipeline (ruling → engine → prose).  The
exception is `test_narrative_indicators.py`, which drives single fixed
turns (no driver) to test the narrator's handling of mechanical
indicators — see "The narrative-indicator scenarios" below.  An
advisory LLM judge also reviews narration quality; its verdict is
recorded in the artifact but never fails the test — deterministic
assertions are the only gate.  Unlike the regular unit suite,
these tests make live API calls and are **skipped by default**.

## Quick start

```bash
pytest tests/integration                  # run all integration scenarios
pytest tests/integration -k flee          # run a specific scenario
```

This uses the default model and API key stored in the config and
credential files.  As usual, you can use the `MGMAI_MODEL` and
`MGMAI_API_KEY` envvars to choose a different model and API key.

To use different models for the different test roles, pass
`--gm-model`, `--driver-model`, and/or `--judge-model`:

```bash
pytest tests/integration \
  --gm-model deepseek-v4-flash \
  --driver-model deepseek-reasoner \
  --judge-model mistral-small-2603
```

## What is tested

The integration suite exercises the following through end-to-end
LLM-vs-LLM runs:

| Layer | What's tested |
|-------|---------------|
| **Engine combat** | Player attacks, NPC attacks, save abilities, consumable use, healing, friendly NPC ally, NPC flee AI, resistance/vulnerability, cooldown management |
| **Status effects & on-hit effects** | NPC on-hit saves (poison, stun), status-effect application, consumable `cure_status_effects` (antidote), status effects cleared at combat end |
| **Attack variety** | NPC `multiattack` with named attacks, damage **immunity**, mid-combat weapon swap (`gear` with `equip_targets` + `unequip_targets`), player attack-roll and heal abilities |
| **Combat AI** | `player` targeting, HP-gated NPC abilities (`use_below_own_hp_pct`), passive NPCs (join combat, never act) |
| **Encounter-driven combat** | Combat started by an encounter (`trigger_encounter` → `start_combat`) instead of a direct attack; the player's `wait` action; out-of-bounds talk attempts handled gracefully |
| **Combat positioning** | Engagement auto-forms on melee attacks and is exposed in status snapshots; scripted `positioning` rulings (engage/disengage/impede) produce `reposition` / `opportunity_attack` / `maneuver` / `impeded` log entries and indicator lines; the Disengage maneuver; impede turn-consumption; graceful degradation of invalid positioning blocks |
| **Action economy** | Per-turn budget (one action / bonus action / free interaction / reaction, one slot spell): open-turn continuation across commands, over-budget rejection costing nothing, Light-weapon off-hand attacks, the opportunity-attack reaction cap, potions always costing the action, the bonus-action slot rule; `status.player_budget` exposure in headless snapshots |
| **GM rulings** | LLM Call 1 correctly classifies player commands in natural language as combat actions, ability uses, item uses, and flee attempts |
| **GM prose** | LLM Call 2 produces a coherent narration that reflects the engine outcome, without hallucinating hits/misses/KOs that didn't happen |
| **Narration quality** | No verbatim repetition, no degenerate loops, consistent HP tracking across turns (advisory judge) |
| **Error resilience** | Empty input, malformed LLM output, and edge-case state transitions don't crash the harness |
| **Follower KO** | An ally dropped to 1 HP at start is correctly handled (death logged, removed from combat) |
| **NPC conversation** | Attitude ladders with per-turn caps, frozen attitudes, tiered `will_reveal` reveals (unconditional / attitude-gated / flag-gated / cross-NPC), reveal side effects (`set_flag`, `set_entity_state`), knowledge recording into `player_knowledge` |
| **Dialogue paths** | Condition-gated paths (refusal vs. success branches), CHA-checked persuasion (repeatable), no-check narrative paths, `adjust_attitude` outcomes, authored lies (narration contradicts, hard state stays clean) |
| **Dialogue lifecycle** | NPC-initiated dialogue (`trigger_dialogue`), stall auto-exit after 3 non-talk turns, conversation-note archival into `entity_notes`, partner switching, dead-NPC talk rejection, follower dialogue mid-travel |
| **Scripted sequences** | Multi-beat `turn.end` reaction chains driven by `increment_room_state` / `increment_entity_state` (ghost-light set-piece, marsh crossing, pier approach), `topic:`-gated mid-dialogue events, scripted room transitions (`set_player_location`), take-check gating, gated exits, inline `game_over` win/loss |

The integration tests do not test puzzles or deep exploration mechanics
— those are exercised by the unit suite.

## Architecture

```
            ┌──────────┐
            │  Driver  │  LLM acting as the player
            │  LLM     │  (one call per turn)
            └────┬─────┘
                 │ command (natural language)
            ┌────▼─────┐
            │  GM LLM  │  Call 1: ruling → PlayerAction JSON
            │          │  Call 2: prose  → narration
            └────┬─────┘
                 │ narration + combat log
            ┌────▼─────┐
            │  Judge   │  Post-run LLM review (rubric-based)
            │  LLM     │  Advisory verdict, recorded in artifact
            └──────────┘
```

1. **Driver** (`driver.py`) — A "playtester" LLM that reads the rolling
   transcript and a scenario directive, then replies with exactly one
   game command per turn.  It tracks its own past commands for context.

2. **Runner** (`runner.py`) — Orchestrates the driver against a
   `HeadlessSession`.  Applies stop conditions (e.g. "stop when combat
   ends"), detects driver aborts, and writes an artifact regardless of
   pass/fail.

3. **Judge** (`judge.py`) — Feeds the full transcript to a third LLM
   with a rubric scoring mechanical fidelity, consistency, narration
   quality, coherent arc, and command appropriateness.  The judge
   receives the scenario directive so it evaluates against the correct
   objective (e.g. doesn't penalise a flee run for having no combat).
   The judge is **advisory only**: its verdict is recorded in the
   artifact, but pass/fail is decided solely by the deterministic
   assertions.  This keeps the red/green signal stable across reruns,
   which matters when an orchestrating agent uses these tests in a
   fix-and-retest loop (the orchestrator can read the artifact
   itself for anything the assertions don't cover).

### Abort mechanism

The driver can signal that the game is broken by replying with `ABORT:
<reason>`.  The runner detects this prefix before submission and stops
the run immediately, recording the abort reason in the artifact and
failing the test.  A driver that gets stuck repeating itself is simply
bounded by `max_turns`.

### Early stop

Each scenario can provide a `stop_when` predicate to `run_scenario`.
For example, the fight-to-completion scenario stops as soon as combat
has been entered and then cleared, rather than running to the
`max_turns` cap.  This saves cost and prevents post-combat wandering
from polluting the judge transcript.

### Artifacts

Every run writes a JSON file to `tests/integration/artifacts/`
(`<scenario>_<timestamp>.json`; the timestamp has microsecond
resolution, so same-second reruns never clobber each other).  The
artifact is a self-describing envelope (`schema_version: 2`):

- `scenario_name`, `directive`, `created_utc`, `turn_count`, `error`
  (plus `error_traceback` when the run died on an exception, so crash
  post-mortems don't need the pytest session's stderr)
- `metadata` — the models used for each role (gm/driver/judge),
  `max_turns`/`seed`, and the git commit + dirty flag of the working
  tree, so any two runs can be correlated with the code that produced
  them
- `summary` — the at-a-glance digest: outcome, player HP trajectory,
  combat entered/concluded/rounds, milestones (flags), knowledge
  topics, archived NPC notes, abilities/items used, enemy outcomes,
  and a compact judge digest.  Computed by
  `tests/integration/artifact.py`, which doubles as the shared query
  layer for the scripts below
- `judge` — the advisory judge's full evidence: parsed verdict, the
  exact payload it was shown, its verbatim raw output, the judge
  model, and any parse error
- `data` — the harness-specific payload.  Scenario runs: every turn's
  command, GM narration, combat log, and status snapshot (including
  the per-turn dialogue snapshot), `driver_raw_outputs` plus
  `driver_contexts` (the situation/transcript the driver was shown
  each turn), whether the driver aborted and why, final entity states
  (HP, alive/fled, attitude), derived entity locations
  (`room:<id>` / `entity:<id>` / null), final soft state
  (`entity_notes`, `player_knowledge`, `dialogue_state`).  Indicator
  runs: `player_input`, `action`, `indicators`, `raw_narration`,
  `final_narration`, `engine_result`

The artifact is written regardless of pass/fail, so you can inspect
even broken runs.  Alongside it, the runner writes a DEBUG log to
`tests/integration/artifacts/<scenario>_<ts>.log` with the full LLM
traffic — `LLMClient` logs every request/response at DEBUG, so the
log covers GM, driver, and judge calls alike, for both harnesses —
the first place to look when diagnosing a failure.

`artifacts/index.json` is maintained automatically (keyed by
scenario, newest first; judge pass/score, turn count, abort/error per
run) for "latest run per scenario" lookups without globbing.

Artifacts written before schema version 2 have a flat legacy shape;
the scripts below read both.

### Query scripts

Three prewritten, stdlib-only scripts answer the common orchestration
questions directly from the artifacts — no throwaway parse scripts
needed:

```bash
# Digest of one run: metadata, summary, judge, first N turns, log pointer
python tests/integration/inspect_artifact.py artifacts/fight_to_completion_20260804_100000_123456.json
python tests/integration/inspect_artifact.py <file> --json --turns 10

# Inventory across runs (uses index.json when present)
python tests/integration/list_runs.py artifacts/
python tests/integration/list_runs.py artifacts/ --scenario venom_pit --latest

# Side-by-side diff of two runs: models/commit, judge criteria,
# HP trajectory, milestones, abilities/items, commands
python tests/integration/compare_runs.py <fileA> <fileB>
```

### Cost expectations

Each game turn makes 2 GM LLM calls (ruling + prose) plus 1 driver
call.  With `stop_when`, a typical fight is ~10 turns ≈ 30 calls.  The
combat suites total roughly 350–450 calls, plus the scripted
single-turn scenarios (1 GM call each) and one judge call per
scenario.  The conversation suite (`test_drowned_lantern.py`) is the
largest: ~450 budgeted turns across 10 scenarios (conversation runs
are deliberately long), on the order of 1,400 calls plus judges at the
outside — most runs stop early via `stop_when`.

## Scenarios

Four scenarios use the `combat_arena` fixture:

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `fight_to_completion` | Defeat all four enemies | Combat started and concluded cleanly; on a win, all enemies have death/flee entries in the combat log; on a loss, the game-over is handled gracefully (player survival is not required — the arena fight is swingy by design) |
| `flee_scenario` | Attack once, then flee north | Combat started, at least one flee attempt logged; escape → player reached corridor alive, no game-over; death → gracefully handled loss |
| `consumable_ability` | Use flame strike on bugbear, potion when HP < 14, then fight to end | Flame strike entry in combat log, combat concluded (win or graceful loss); in any round where the player drank a potion, no player attack/ability entry that same round (potions cost the action); potion never used → warn-only |
| `ally_death` | Korbar at 1 HP / AC 1, fight to end | Combat concluded (win or gracefully handled loss); Korbar's fate consistent between combat log and entity state — death recorded on both when she falls (she almost always does) |

Four scenarios use the `venom_pit` fixture (`test_venom_pit.py`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `poisoned_and_cured` | Attack the viper; drink an antidote if poisoned (Willa made passive so the viper always targets the player) | Viper hits carry CON-save poison on-hit effects; on a failed save, a `use_item` antidote entry; no status effects linger after combat |
| `multiattack_and_stun` | Fight the carrion crawler | Some round has both `tentacles` and `bite` attack entries; on a failed tentacle save, a `stunned` player turn is logged |
| `immunity_weapon_swap` | Attack the jelly with the sword, then swap to the war hammer | A player attack with `mitigation="immune"` and 0 damage; later bludgeoning attacks; war hammer equipped at the end (no swap → jelly unkillable → turn-cap failure, the intended signal) |
| `player_abilities` | Power Strike the crawler; Healing Hands on Willa below half HP | ≥1 and ≤2 `power_strike` attack entries; a `heal` entry targeting Willa when she was hurt |

Three scenarios use the `ambush_alley` fixture (`test_ambush_alley.py`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `ambush_trigger` | Confront and grab the cutpurse (no attack), then fight | Combat entered via the encounter: `ambush_triggered` flag set and all three gang members enemy combatants on the combat-start turn; combat concluded |
| `targeting_and_frenzy` | Ambush, then fight howler-first | Every thug attack targets the player; `frenzy` entries only at/after the howler first dropped below half HP; pack mule a party combatant with zero attack entries |
| `hold_and_talk_rejected` | Ambush, hold ground first turn, then try to talk, then fight | A `wait` player entry; no exceptions or empty narrations across the talk attempt; combat concluded |

## The NPC-conversation scenarios

`test_drowned_lantern.py` is the conversation suite, run against the
`drowned_lantern` fixture (see below).  Scenarios are grouped in three
tiers: per-NPC arcs, dialogue-lifecycle micro-behaviors, and the
endgame plus an unguided playthrough.  Several scenarios start from a
**preset starting point** — a pre-built `StateManager` with knowledge
flags flipped (e.g. "you already heard the name Janis from Fen"),
using the `state_manager=` path of `run_scenario` (the venom_pit
precedent).  RNG-gated outcomes (CHA checks, GM-discretion reveals)
follow the warn-don't-fail convention.

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `fen_arc` | Talk to Fen on the dock through his whole rambling arc | `trigger_dialogue` active on dock entry; frozen attitude stays 0; reveal chain (`night_crossings` → ghost-light beats → `lights_malevolent`, `janis_blurt`) with flags and `player_knowledge` entries; ghost-light `stage` runs to completion; `dialogue.ended` departure (`departed`, location null); note archived |
| `marta_ladder` (preset: `heard_janis_name`) | Warm up Marta over a long evening | Attitude rises with per-turn steps ≤ 2; unconditional and attitude ≥ 2 reveal tiers; crate unhidden via `set_entity_state`; attitude ≥ 5 tier warn-only |
| `berrin_confront` (preset: name + link) | Cold-ask, confront with evidence, press for the crossing | Refusal precedes `berrin_confessed`; no-check confront path; `crossing_agreed` + `confided_crate`; attitude steps ≤ 2 |
| `berrin_bluff` (preset: name only) | Drop the name and bluff | `knows_janis_link` never set; on failure branches attitude drops with no state leaked; CHA-14 success branch warn-only |
| `old_wellington_and_stall` | Talk to the stuffed heron, chat with Marta, get distracted, re-engage | Dialogue never opens with the dead NPC; stall counter climbs and dialogue auto-exits; memory note archived; re-engagement warn-only |
| `npc_switching` | Marta → Berrin → Marta, warm then curt | Partner sequence M→B→M; both conversations archived; attitudes tracked independently (his drops under mockery; her ladder rises under warmth — her final value is GM discretion, since she witnesses the mockery, so the gate is her peak, warn-only on a soured final) |
| `loss_enter_water` | Jump into the marsh | Game over, type `lose` |
| `loss_violence` | Attack Fen | Fen dead; game over, type `lose` (`violence_ends_it`) |
| `crate_and_crossing` (preset: confessed + agreed) | Move the crate, ride out the crossing, moor the ferry | Win; crate ends at `entity:ferry`; follower dialogue with Berrin in `mid_marsh`; scripted beats ran (lights unhidden); Berrin `departed`/null; `janis_vanishing` warn-only |
| `free_play` | "Play the adventure" (unguided, 100 turns) | Clean run; at least one knowledge milestone; full win warn-only until pass rates are known |

## The narrative-indicator scenarios

`test_narrative_indicators.py` is a separate, smaller suite for the
marker-based inline mechanical indicators (see
`design-inline-indicators.md`).  It has **no driver LLM**: each
scenario is a single fixed turn.  A hand-written `PlayerAction` is
resolved by the real engine — Call 1 (ruling) is bypassed by design,
so the engine-generated text is controlled by the scenario — the
indicators built from the engine result are passed to the real GM
prose call (Call 2, exactly as in production), and the marker-replaced
narration is checked.  Only two LLM roles are involved: the GM
(narrator) and the judge.

Hard assertions (the gate) cover player-facing output correctness:

- the engine produced the expected indicator set for the scenario;
- the final player-facing narration contains no leftover marker
  syntax (a mangled, paraphrased, or duplicated marker would survive
  replacement and leak to the player);
- each indicator's canonical text appears exactly once (nothing
  dropped, no duplicated mechanical summaries) — and so does each
  indicator's plain description, which catches the narrator writing
  out the mechanical text itself in addition to placing the marker.

Marker *placement* (how many markers the narrator placed inline, and
where) is model-quality behaviour that varies between runs; it is
recorded in the artifact and surfaced as a warning, never a gate —
the fallback keeps the player-facing output correct regardless.  An
advisory judge (`indicator_judge.py`) scores marker placement
quality, mechanical fidelity, cleanliness, and narration quality; the
verdict is recorded in the artifact and surfaced as a warning, never
a test failure.

Four scenarios use the `indicator_hall` fixture:

| Scenario | Fixed action | Expected indicators |
|----------|--------------|---------------------|
| `indicator_single_check` | Shove the cracked pillar (STR check vs target 3, STR 16 — always succeeds) | Exactly one `check` indicator |
| `indicator_multi_check_hp` | Cross the rickety bridge (DEX then CON checks vs target 30 — both always fail, the second dealing 1d4 damage) | Two `check` indicators + one `hp` indicator in one turn |
| `indicator_combat_round` | Attack the sparring golem mid-combat (preset combat state, seeded dice) | Two `combat` indicators (player attack + golem retaliation) + one `hp` indicator |
| `indicator_attack_death` | Attack the 1-HP battered dummy mid-combat (preset combat state, seeded dice) | Two `combat` indicators (attack + death); combat ends |

Each run costs 1 GM call + 1 judge call per scenario.

## The combat-positioning scenarios

`test_combat_positioning.py` covers theater-of-the-mind positioning
(engagement, opportunity attacks, Disengage, impede — see
`combat-positioning-plan.md`) in two styles.

Five **scripted** scenarios reuse the single-turn indicator harness
(`run_indicator_turn`) against the `combat_arena` fixture with a
preset `CombatState` (player acting first against the goblin grunt and
the bugbear) and pinned dice (`seed=7`, making the combat log,
indicator texts, and post-turn engagement state deterministic — the
expectations were derived by running the engine locally with that
seed).  The hand-written actions carry `positioning` assertion blocks
exactly as the ruling LLM would emit them.  Each run costs 1 GM call +
1 judge call:

| Scenario | Fixed action | Key assertions |
|----------|--------------|----------------|
| `positioning_engagement_exposure` | Attack the grunt (no assertion) | Melee attacks auto-engage attacker ↔ target; the headless status snapshot carries `engaged_with` (sorted ids) and `impeded` on every combatant |
| `positioning_opportunity_attack` | Attack the grunt with `{"engage": [["player", "goblin_grunt"]], "disengage": [["player", "bugbear"]]}` | `reposition` entries for both changes; one `opportunity_attack` entry (bugbear → player, seeded hit for 5) resolving *before* the declared attack; the OA indicator line appears in the player-facing narration |
| `positioning_disengage_maneuver` | `{"combat_action": "maneuver", "maneuver": "disengage"}` (no target; grunt preset stunned so it cannot re-engage) | `maneuver` log entry; zero opportunity attacks; the grunt's pair stays broken while the bugbear re-engages on its own attack; "You disengage, carefully withdrawing from melee." indicator |
| `positioning_impede` | Attack the grunt with `{"impede": ["bugbear"]}` | The bugbear's turn is consumed closing in (`impeded` entry, no attack); it ends engaged with its AI target; `impede_used == ["bugbear"]` persists after the pending flag is consumed; "held up by an obstacle" indicator |
| `positioning_soft_fail` | Attack the grunt with an invalid block (unknown id, non-engaged disengage pair, impeding the player) | Every malformed entry dropped with a `positioning ... dropped: ...` warning in `result.warnings`; no reposition/OA/impede effects; the core attack still lands |

One **playtest** scenario uses the driver-vs-GM harness
(`run_scenario`, same as `test_combat_arena.py`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `positioning_playtest` | Defeat all enemies while fighting mobile: switch targets mid-fight, create an obstacle to slow an enemy, withdraw when surrounded | Hard gates: combat concludes cleanly; every in-combat status snapshot exposes `engaged_with`/`impeded` on every combatant and at least one snapshot shows a live engagement pair.  Whether the GM actually asserts positioning blocks (reposition/OA/maneuver/impeded entries) depends on its rulings, so it is surfaced as a warning, never a gate |

## The action-economy scenarios

`test_action_economy.py` covers the per-turn action economy
(`TurnBudget` on `CombatState`: one action, one bonus action, one free
object interaction, one reaction, one slot spell per turn) in two
styles.

Seven **scripted** scenarios reuse the single-turn indicator harness
(`run_indicator_turn`) against the `combat_arena` and `spell_arena`
fixtures with a preset `CombatState` and pinned dice (`seed=7`).  A
player turn that stays open (`turn_continuation`) spans several
commands, so the multi-segment scenarios chain several
`run_indicator_turn` calls on one shared `StateManager` — the harness
resolves one fixed action per call, but the budget flags,
`turn_continuation`, `reactions_spent`, and `action_weapon_id` persist
on the StateManager between calls, and each segment still gets the real
GM prose call.  The fixtures declare no bonus-action ability and no
Light weapons, so those are preset on the loaded player state: the SRD
spell pack's `healing_word` (plus level-1 slots) and the SRD gear
pack's `shortsword` + `dagger` for dual-wielding.  Each segment costs 1
GM call; the last segment of each scenario gets 1 judge call:

| Scenario | Fixed actions | Key assertions |
|----------|---------------|----------------|
| `open_turn_continuation` | `healing_word` (bonus), then attack (action) | Both log entries land in round 1; no NPC turns after the bonus segment; `turn_continuation` set then cleared; budget flags and slot consumption correct |
| `over_budget_rejection` | Attack, second attack (rejected), then `healing_word` | `success: False` with an engine error; empty log; turn still open with the budget unchanged; the legal bonus action still closes the turn |
| `off_hand_attack` | Attack (Light shortsword), off-hand attack (dagger), third attack (rejected, mid-turn budget preset) | Both attacks land in the same round; `action_weapon_id` bookkeeping; the both-spent rejection costs nothing |
| `reaction_cap` | Two enemies disengage from the player, two rounds running | Exactly one player `opportunity_attack` per round — the second provocation is blocked by `reactions_spent`; the reaction refreshes at the player's next turn start |
| `potion_costs_the_action` | Drink potion, attack (rejected), then `healing_word` | The drink logs `interact` + `heal` and spends the action; the attack is rejected; the turn stays open for the bonus action |
| `potion_never_a_free_interaction` | Potion with `interaction_cost: "free"` | Rejected ("always require an action"); potion unconsumed; budget untouched |
| `slot_rule` | `healing_word` (leveled bonus), `magic_missile` (rejected), `fire_bolt` (cantrip) | Leveled bonus spell + leveled main spell can't coexist; the rejected cast consumes no slot; the cantrip closes the turn |

One **playtest** scenario uses the driver-vs-GM harness
(`run_scenario`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `action_economy_playtest` | Defeat all enemies while combining attack + flame strike + potion every turn | Combat concludes cleanly; at most one action-costing player log entry per round; every failed turn carries an engine error; every in-combat snapshot exposes `status.player_budget`.  Whether an over-budget ruling actually occurred is a warning, never a gate |

## The combat arena fixture

Located at `tests/integration/fixtures/combat_arena/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).

- **Player** (level 2): longsword (1d8 slashing), 2 potions of healing
  (2d4+2) — both from the SRD data pack, not declared in the fixture —
  flame strike ability (2 uses/combat, 2d6 fire DEX save DC
  13), HP 24, AC 14
- **Korbar** (ally): warhammer (1d10+3 bludgeoning), HP 22, AC 16
- **Goblin grunt**: HP 11, AC 13, rusty shortsword (1d6 slashing)
- **Goblin runner**: HP 9, AC 14, javelins (1d4 piercing), flees below
  35% HP
- **Goblin shaman**: HP 16, AC 12, melee (1d6 slashing), mend wounds
  ability (2d4+2 heal, 2‑round cooldown, targets lowest-HP ally)
- **Bugbear**: HP 22, AC 11, morningstar (1d8+2 bludgeoning),
  piercing resistance, fire vulnerability
- **Rooms**: Arena (start, contains all combatants, exit north to
  corridor) → Exit Corridor

## The venom pit fixture

Located at `tests/integration/fixtures/venom_pit/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).

- **Player** (level 3): longsword (1d8 slashing) equipped, warhammer
  (1d8 bludgeoning) in inventory, 2 potions of healing, 2 antidotes
  (cure `poisoned`), power strike ability (2 uses/combat, 2d6 slashing
  attack), healing hands ability (2 uses/combat, 2d4+2 heal on ally),
  HP 28, AC 14; save proficiencies deliberately exclude CON.  The
  longsword, warhammer, and potions come from the SRD data pack; the
  antidote is a fixture-custom item
- **Willa** (ally): short blade (1d6 slashing), HP 16, AC 12
- **Pit viper**: HP 20, AC 12, bite (1d4 piercing) with a poison on-hit
  effect (CON save DC 13: 1d6 poison + `poisoned` 2 rounds on failure,
  half on success)
- **Carrion crawler**: HP 22, AC 13, multiattack — tentacles (1d4
  bludgeoning, CON save DC 13 or stunned for its next turn) + bite
  (1d6 piercing)
- **Ochre jelly**: HP 24, AC 8, pseudopod (1d6 acid), **immune to
  slashing** — unbeatable without swapping to the war hammer
- **Rooms**: Venom Pit (start, all combatants, rope exit up) → Temple
  Ruins

## The ambush alley fixture

Located at `tests/integration/fixtures/ambush_alley/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).

- **Player** (level 2): longsword (1d8 slashing), 2 potions of healing
  — both from the SRD data pack — HP 28, AC 14
- **Pack mule** (ally): `ai.passive` — joins combat on the player's
  side but never acts
- **Cutpurse**: HP 10, AC 13, knife (1d4 piercing); declares a
  `confront` interaction whose `interaction.used` reaction triggers his
  aggro encounter, which sets `ambush_triggered` and starts combat with
  the whole gang
- **Hired thug**: HP 16, AC 13, club (1d6 bludgeoning),
  `ai.targeting: "player"`
- **Frenzied howler**: HP 14, AC 12, knife (1d4 slashing), frenzy
  ability (2d4 slashing attack) gated to below 50% HP
- All three gang members share the `alley_gang` combat group
- **Rooms**: Market Alley (start, all combatants, exit east) → Dead-End
  Court

## The spell arena fixture

Located at `tests/integration/fixtures/spell_arena/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).
Built for spellcasting scenarios: the player is a caster whose spells
come from the SRD spell pack (not declared in the fixture corpus).  No
scenarios use this fixture yet — it is reserved for future
spellcasting playtests (see `spellcasting-plan.md`).

- **Player** (level 1 wizard): quarterstaff (1d6 bludgeoning), 1 potion
  of healing — both from the SRD data pack — `spellcasting_ability:
  "INT"` (INT 16), two 1st-level `spell_slots`, knows `fire_bolt`
  (cantrip, 1d10 fire attack), `mage_armor` (on-cast, base AC 13 + DEX),
  and `magic_missile` (auto-damage, 3d4+3 force); HP 8, AC 12
- **Goblin grunt**: HP 11, AC 13, rusty shortsword (1d6 slashing)
- **Hobgoblin**: HP 18, AC 13, morningstar (1d8+1 bludgeoning)
- **Rooms**: Arena (start, both enemies, exit north to corridor) → Exit
  Corridor

## The indicator hall fixture

Located at `tests/integration/fixtures/indicator_hall/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).
Built for the narrative-indicator scenarios: every check target is
authored unreachable or pass-everything, so the engine outcome (and
thus the indicator set) of each fixed action is deterministic.

- **Player** (level 2): training cudgel (1d6 bludgeoning, +5 hit),
  HP 24, AC 14, STR 16 / DEX 10 / CON 10
- **Cracked pillar** (feature): `shove` interaction — STR check vs
  target 3, always succeeds (one `check` indicator)
- **Rickety bridge** (feature): `cross` interaction — DEX check vs
  target 30, always fails, chaining into a CON check vs target 30 that
  also always fails and deals 1d4 damage (two `check` indicators + one
  `hp` indicator)
- **Sparring golem**: HP 40, AC 8, 1d4 bludgeoning — durable enough to
  guarantee a full combat round (player attack + retaliation)
- **Battered dummy**: HP 1, AC 1 — dies to any hit (attack + death
  indicators, ending combat)
- **Rooms**: Proving Hall (start, pillar + bridge, exit east) →
  Sparring Chamber (golem + dummy)

## The drowned lantern fixture

Located at `tests/integration/fixtures/drowned_lantern/`, validated by
a non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).
A conversation-centric mini-adventure (human-playable in its own
right); the design is documented in `scenario.md` and mapped to engine
mechanics in `scenario-map.md` (both in the fixture directory).  No
`hard-state.json` — all initial state derives from corpus
declarations.

- **Player** (level 3 fighter): longsword (1d8 slashing, from the SRD
  data pack), HP 24, AC 13, CHA 12 (persuasion-centric)
- **Berrin** (ferryman): attitude ±10/step 2; dialogue paths
  `ask_crossing_cold` (refusal), `bluff_janis` (CHA 14, lie on
  failure), `confront_janis` (no check, evidence-gated),
  `convince_crossing`; becomes a follower during the crossing
- **Marta** (barkeep): attitude ±10/step 2; `sympathetic_ear` (CHA 9)
  path; tiered reveals `ferryman_duty` (unconditional),
  `crate_concern` (attitude ≥ 2, unhides the crate), `janis_payout`
  (attitude ≥ 5 + `heard_janis_name` — cross-NPC gating)
- **Fen** (fisherman): frozen attitude (0/0); `trigger_dialogue`
  greeting; reveals gated on the ghost-light set-piece; departs on
  `dialogue.ended` once his dialogue is exhausted
- **Old Wellington**: a stuffed heron — an NPC with `alive: false`
  (dead-NPC talk rejection)
- **Scripted sequences** (numeric stage fields + increment effects):
  the 3-beat ghost light (`topic:`-gated), the 5-beat marsh crossing
  (ends in a scripted `set_player_location` transition), and the
  2-beat pier approach (ungates the `rope_end` take and the
  `exit_pier` win exit)
- **Losses**: the `enter_water` dummy exits (drowning in the
  `in_the_water` room) and the `violence_ends_it` reaction mechanic
  (any living NPC killed)
- **Rooms**: Common Room (start) ⇄ Dock → (one-way, gated) Mid-Marsh →
  (scripted) Far Shore → (gated) Muddy Track (win); The Black Water
  (terminal drowning room, reachable via `enter_water` from any
  waterside room)

## How to modify

### Changing the fixture

Edit the JSON files in `tests/integration/fixtures/combat_arena/`:

- `corpus.json` — Rooms, entities, abilities, stats
- `default-player.json` — Player stats, inventory, abilities
- `hard-state.json` — Initial world state (player location, entity
  states, flags)
- `soft-state.json` — Initial soft state (empty for a fresh game)

Run the smoke test after changes:

```bash
pytest tests/test_headless.py -k integration_fixture_smoke -v
```

### Adding a new scenario

1. Write a directive string describing the player's objective and
   tactics in natural language (no engine identifiers).
2. Add a `stop_when` predicate if the scenario has a natural end point
   before `max_turns`.
3. Add the test function to `test_combat_arena.py`, calling
   `run_scenario` with your directive and `stop_when`.
4. Add hard assertions appropriate to the scenario — check combat log
   entries, location, HP bounds, entity states, etc.
5. Run the test to verify it passes, then check the artifact for the
   judge verdict.

### Adding a new fixture adventure

1. Create a new directory under `tests/integration/fixtures/` with the
   JSON files (`corpus.json`, `default-player.json`, `soft-state.json`;
   `hard-state.json` only if you need to override the generated
   initial state — `drowned_lantern` does without).
2. Add a fixture in `tests/integration/conftest.py` exposing the
   directory path.
3. Add a smoke test in `test_headless.py` verifying the fixture loads.
4. Create test functions as above.

### Adding custom models

Register new models in `~/.config/mgmai/models.json` (the same file
used by the main REPL).  For each model, provide at minimum:

```json
{
  "my-model": {
    "label": "Human-readable name",
    "base_url": "https://api.provider.com/v1",
    "ruling_temperature": 0.7,
    "prose_temperature": 0.9
  }
}
```

All ModelConfig fields are supported.  See
`mgmai/llm/model_config.py` for the full `ModelConfig` schema.

### Using reasoning models

Reasoning models (chain-of-thought) are a good fit for the **driver**
and **judge** roles, where straightforward answers are less critical
than nuanced reasoning.  They are less suitable for the **GM**
(ruling) because low latency matters for each turn.

Add reasoning models to `~/.config/mgmai/models.json` with the
appropriate `extra_body` for each provider:

```json
{
  "deepseek-reasoner": {
    "label": "Deepseek Reasoner",
    "base_url": "https://api.deepseek.com",
    "ruling_temperature": null,
    "prose_temperature": null,
    "extra_body": {"thinking": {"type": "enabled"}},
    "prose_max_tokens": 4096
  },
  "openai-o3-mini": {
    "label": "OpenAI o3-mini",
    "base_url": "https://api.openai.com/v1",
    "ruling_temperature": null,
    "prose_temperature": null,
    "extra_body": {"reasoning_effort": "medium"},
    "prose_max_tokens": 4096
  }
}
```

Key points:

- Set `ruling_temperature` and `prose_temperature` to `null` (JSON
  null) — most reasoning models reject explicit temperature.
- Increase `prose_max_tokens` to accommodate chain-of-thought tokens
  alongside the final answer (4096+ is typical).
- Use `extra_body` for provider-specific reasoning parameters
  (DeepSeek → `"thinking"`, OpenAI → `"reasoning_effort"`).
- A `deepseek-reasoner` stub with placeholder values is included in
  the built-in registry; exact model names and URLs need to be filled
  in.

### Choosing models

Set `MGMAI_MODEL` to use a single model for all three roles, or pass
`--gm-model`, `--driver-model`, `--judge-model` individually.  The
driver uses the model's prose temperature by default (no hardcoded
value) and disables JSON mode to produce plain-text commands; the
judge and GM uphold JSON mode for structured outputs.
