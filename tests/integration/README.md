# LLM Integration Tests

These tests run a "driver" LLM as the player against the real GM LLM,
verifying the full two-call pipeline (ruling → engine → prose).  An
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
| **Conditions & on-hit effects** | NPC on-hit saves (poison, stun), condition application, consumable `cure_conditions` (antidote), conditions cleared at combat end |
| **Attack variety** | NPC `multiattack` with named attacks, damage **immunity**, mid-combat weapon swap (`equip` + `unequip_targets`), player attack-roll and heal abilities |
| **Combat AI** | `player` targeting, HP-gated NPC abilities (`use_below_own_hp_pct`), passive NPCs (join combat, never act) |
| **Encounter-driven combat** | Combat started by an encounter (`trigger_encounter` → `start_combat`) instead of a direct attack; the player's `wait` action; out-of-bounds talk attempts handled gracefully |
| **GM rulings** | LLM Call 1 correctly classifies player commands in natural language as combat actions, ability uses, item uses, and flee attempts |
| **GM prose** | LLM Call 2 produces a coherent narration that reflects the engine outcome, without hallucinating hits/misses/KOs that didn't happen |
| **Narration quality** | No verbatim repetition, no degenerate loops, consistent HP tracking across turns (advisory judge) |
| **Error resilience** | Empty input, malformed LLM output, and edge-case state transitions don't crash the harness |
| **Follower KO** | An ally dropped to 1 HP at start is correctly handled (death logged, removed from combat) |

The integration tests **do not** test adventuring mechanics (dialogues,
puzzles, exploration) — those are exercised by the unit suite.

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
containing:

- The scenario name and directive
- Every turn's command, GM narration, combat log, and status snapshot
- Whether the driver aborted and why
- The advisory judge's verdict (pass/fail, per-criterion scores and
  notes), when it runs successfully — informational only
- Final entity states (HP, alive/fled) for post-run inspection

The artifact is written regardless of pass/fail, so you can inspect
even broken runs.

### Cost expectations

Each game turn makes 2 GM LLM calls (ruling + prose) plus 1 driver
call.  With `stop_when`, a typical fight is ~10 turns ≈ 30 calls.  A
full `pytest tests/integration` run (11 scenarios) is roughly 300–400
calls, plus 11 judge calls.

## Scenarios

Four scenarios use the `combat_arena` fixture:

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `fight_to_completion` | Defeat all four enemies | Combat started and concluded cleanly; on a win, all enemies have death/flee entries in the combat log; on a loss, the game-over is handled gracefully (player survival is not required — the arena fight is swingy by design) |
| `flee_scenario` | Attack once, then flee north | Combat started, at least one flee attempt logged; escape → player reached corridor alive, no game-over; death → gracefully handled loss |
| `consumable_ability` | Use flame strike on bugbear, potion when HP < 14, then fight to end | Flame strike entry in combat log, combat concluded (win or graceful loss) |
| `ally_death` | Korbar at 1 HP / AC 1, fight to end | Combat concluded (win or gracefully handled loss); Korbar's fate consistent between combat log and entity state — death recorded on both when she falls (she almost always does) |

Four scenarios use the `venom_pit` fixture (`test_venom_pit.py`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `poisoned_and_cured` | Attack the viper; drink an antidote if poisoned (Willa made passive so the viper always targets the player) | Viper hits carry CON-save poison on-hit effects; on a failed save, a `use_item` antidote entry; no conditions linger after combat |
| `multiattack_and_stun` | Fight the carrion crawler | Some round has both `tentacles` and `bite` attack entries; on a failed tentacle save, a `stunned` player turn is logged |
| `immunity_weapon_swap` | Attack the jelly with the sword, then swap to the war hammer | A player attack with `mitigation="immune"` and 0 damage; later bludgeoning attacks; war hammer equipped at the end (no swap → jelly unkillable → turn-cap failure, the intended signal) |
| `player_abilities` | Power Strike the crawler; Healing Hands on Willa below half HP | ≥1 and ≤2 `power_strike` attack entries; a `heal` entry targeting Willa when she was hurt |

Three scenarios use the `ambush_alley` fixture (`test_ambush_alley.py`):

| Scenario | Directive | Key assertions |
|----------|-----------|----------------|
| `ambush_trigger` | Confront and grab the cutpurse (no attack), then fight | Combat entered via the encounter: `ambush_triggered` flag set and all three gang members enemy combatants on the combat-start turn; combat concluded |
| `targeting_and_frenzy` | Ambush, then fight howler-first | Every thug attack targets the player; `frenzy` entries only at/after the howler first dropped below half HP; pack mule a party combatant with zero attack entries |
| `hold_and_talk_rejected` | Ambush, hold ground first turn, then try to talk, then fight | A `wait` player entry; no exceptions or empty narrations across the talk attempt; combat concluded |

## The combat arena fixture

Located at `tests/integration/fixtures/combat_arena/`, validated by a
non-LLM smoke test (`test_headless.py::TestIntegrationFixtureSmoke`).

- **Player** (level 2): longsword (1d8 slashing), 2 healing potions
  (2d4+2), flame strike ability (2 uses/combat, 2d6 fire DEX save DC
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

- **Player** (level 3): longsword (1d8 slashing) equipped, war hammer
  (1d6 bludgeoning) in inventory, 2 healing potions, 2 antidotes
  (cure `poisoned`), power strike ability (2 uses/combat, 2d6 slashing
  attack), healing hands ability (2 uses/combat, 2d4+2 heal on ally),
  HP 28, AC 14; save proficiencies deliberately exclude CON
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

- **Player** (level 2): longsword (1d8 slashing), 2 healing potions,
  HP 28, AC 14
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
   four JSON files.
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
