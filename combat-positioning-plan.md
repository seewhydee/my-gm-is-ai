# Theater-of-the-Mind Positioning for Combat

## Goal

Add abstract positioning to the combat engine — no grid, no distances. The
single concept is **engagement**: a symmetric "within melee reach" relation
between two combatants. The ruling LLM may assert engagement changes for any
pair of combatants (full-scene adjudication, validated by the engine), and
leaving engagement without Disengaging provokes a lite Opportunity Attack
(OA). This unlocks the SRD 5.2.1 rules that are currently stubbed for lack of
a positioning model:

- **Ranged attacks in close combat** — Disadvantage on a ranged attack roll
  while within reach of a living, non-incapacitated enemy (SRD: "Ranged
  Attacks in Close Combat").
- **Prone** — attack rolls against a prone combatant have Advantage if the
  attacker is within reach, Disadvantage otherwise (currently flat Advantage;
  `mgmai/data/srd_5e/conditions.json` prone entry carries the "no positioning
  model" caveat; `mgmai/engine/systems/five_e.py:301-303` notes the same).
- **Unconscious** — a hit from within reach is an automatic critical (SRD).
- **Opportunity Attacks / Disengage** (lite) — leaving an enemy's reach
  provokes one free basic attack from that enemy; a `maneuver` (Disengage)
  combat action leaves safely at the cost of the turn's action.

Confirmed scope decisions (from user): **OA-lite + Disengage**; **full-scene
LLM adjudication** of engagement.

## Model

- `CombatState.engagement: list[list[str]]` — sorted symmetric pairs of
  combatant ids (`[["goblin", "player"]]`), on
  `mgmai/models/combat.py:52-74`. Same pattern as `last_attacker`. Discarded
  when combat ends (state is dropped); pairs involving dead/fled combatants
  are pruned immediately.
- Helpers in `mgmai/engine/combat.py`: `_engaged_with(combat, cid) -> set[str]`,
  `_set_engagement(combat, a, b, on: bool)`.

### Engagement lifecycle (deterministic defaults)

- A **melee attack** (player with non-`ranged` equipped weapon/unarmed; NPC
  attack not flagged `ranged`) engages attacker ↔ target, if not already.
  Attacking a new target *adds* engagement; it never breaks existing pairs
  (TotM simplification: "within reach of both" is plausible; the LLM can
  assert otherwise).
- Combat entry via the player's direct `interact`/`attack`: player ↔ source
  NPC start engaged if the player's equipped weapon is not ranged.
  Encounter/ambush starts: no initial pairs; enemies engage by attacking.
- Engagement breaks only via: explicit Disengage maneuver, validated LLM
  assertion, death, flee, or combat end.
- **Fleeing is unchanged** (the DEX check abstracts the getaway; no OA on
  flee — documented simplification).

### LLM assertion channel (full-scene adjudication)

- New optional field on `_BaseAction` (`mgmai/models/actions.py:27`):
  `positioning: Optional[PositioningAssertion]` where
  `PositioningAssertion = {engage: list[list[str]], disengage: list[list[str]]}`.
  Keeps the Call-1 contract (one JSON object with `action_type`) — no wrapper
  type, no parser change beyond the model.
- Valid in combat only, on `combat` and `wait` actions (rejected on
  `move`/`examine`/out-of-combat). Validation in
  `mgmai/llm/ruling_validation.py` (paired with the existing corrective-retry
  loop in `game/loop.py:_call_ruling`): ids must be living combatants in the
  briefing; a pair may not appear in both lists; at most 4 pair-changes per
  turn. Engine re-validates at apply time (containment: worst case is a few
  adjacency flips whose mechanical impact is bounded to adv/disadv/OAs).
- Engine applies assertions at the top of `resolve_combat_turn`
  (`mgmai/engine/combat.py:1542`), before the declared action: apply
  engage/disengage → resolve provoked OAs → resolve the action. (OAs first,
  since a lethal OA cancels the action — mirrors SRD "occurs right before it
  leaves your reach".)

### OA-lite

- Breaking engagement with a living enemy other than via Disengage provokes
  **one basic melee attack** from that enemy (block-level `atk`/`dmg`, or its
  first attack def; no multiattack, no abilities, no on-hit effects beyond
  the basic attack's own) via the existing `system.resolve_npc_attack`.
  Symmetric: an enemy leaving the player's reach (via LLM assertion) provokes
  one automatic player OA via `resolve_player_attack` with the equipped
  weapon. Logged as `CombatLogEntry(action="opportunity_attack")`.
- An enemy with a `skip_turn` status effect (stunned, incapacitated, …)
  cannot make OAs and does not impose close-combat Disadvantage (stands in
  for SRD's "can see you and doesn't have Incapacitated").

### New combat action: Disengage

- `CombatAction.combat_action` gains `"maneuver"` with
  `maneuver: Optional[Literal["disengage"]]`; `target` becomes
  `Optional[str] = None` with a model validator requiring it for
  `attack`/`use_item`/`use_ability` and ignoring it for `maneuver`
  (`mgmai/models/actions.py:98-103`).
- Disengage consumes the player's action: breaks all of the player's
  engagement pairs, provokes no OAs, logged as `action="maneuver"`. NPC turns
  then proceed as usual.
- The stale guidance that repositioning is flavor-only
  (`mgmai/llm/ruling_validation.py:134-146`, `mgmai/templates/ruling.j2`
  action rules ~:221-232 and :248-259) is replaced with maneuver/positioning
  documentation.

### Rules hooks in FiveESystem (`mgmai/engine/systems/five_e.py`)

`resolve_player_attack` (:475) and `resolve_npc_attack` (:558) both receive
`hard`, so engagement is read from `hard.combat.engagement` directly — no
interface change to `ResolutionSystem` call sites beyond an optional param:

- `attack_roll_mods(...)` (:351) gains `engaged: bool = False`; two new
  `system_effects` keys: `advantage_against_engaged` and
  `disadvantage_against_unengaged` (prone). `conditions.json` prone entry
  drops flat `advantage_against` for these; its description loses the
  "no positioning model" caveat.
- Close-combat Disadvantage: in both resolve fns, if the attack is ranged
  and the attacker is engaged with ≥1 living enemy without a `skip_turn`
  effect → `disadvantage = True`. Player ranged-ness from equipped weapon
  `equip_tags` (existing `_weapon_attack_stat` logic); NPC ranged-ness from a
  new `ranged: bool = False` on `CombatBlock` and `NPCAttackDef`
  (`mgmai/models/corpus.py`). Ability `attack` effects are treated as ranged
  for this rule (documented; can be refined with a flag later).
- Auto-crit: new key `auto_crit_against_engaged` on the `unconscious`
  condition; on a hit, if the target has it and attacker is engaged with the
  target → `critical = True` (double dice).

### Exposure surfaces

- **Briefing**: `CombatBriefing.combatants` entries gain
  `engaged_with: list[str]` (`mgmai/context/assembler.py:402-481`), so the
  ruling LLM sees the current map. `templates/ruling.j2` documents the
  `positioning` field, the maneuver action, and the OA/close-combat rules.
- **Narration**: engagement changes are logged as
  `CombatLogEntry(action="reposition", actor, target)` so Call 2 can weave
  them; update `mgmai/engine/narrative_indicators.py`
  (`_format_single_combat_entry`), `mgmai/engine/stat_checks.py`
  (`format_combat_prefix`), and `templates/prose_combat.j2` in lockstep.
- **Display**: combat status panel rows show engagement (e.g. `⚔ goblin`)
  via `_row_data`/`_rich_row`/`_plain_row` in `mgmai/game/display.py`.
- No new event-bus event type in v1 (engagement is visible in the combat
  log; corpus reactions on positioning are speculative).

## Work plan

1. **Models**: `CombatState.engagement`; `PositioningAssertion` +
   `positioning` on `_BaseAction`; `maneuver` on `CombatAction` (target →
   Optional + validator); `ranged` on `CombatBlock`/`NPCAttackDef`.
2. **Engine** (`mgmai/engine/combat.py`): engagement helpers; auto-engage on
   melee attacks (player :1630 area, NPC :1171 area, combat entry :1354);
   apply+re-validate `positioning` assertions at top of `resolve_combat_turn`;
   OA resolution helper (shared for player/NPC movers); Disengage maneuver
   branch; prune pairs on death/flee.
3. **System** (`five_e.py`, `conditions.json`): engaged-aware
   `attack_roll_mods`, close-combat Disadvantage, `auto_crit_against_engaged`,
   prone/unconscious condition updates; delete the stale "no positioning"
   comments.
4. **LLM surface**: ruling_validation for `positioning`; ruling.j2 rewrite of
   the combat action rules; briefing `engaged_with`; prose_combat.j2 +
   indicators/prefix formatting for `reposition`/`maneuver`/
   `opportunity_attack` entries.
5. **Display**: engagement markers in the combat panel.
6. **Docs**: `doc/combat.md` (new Positioning section; update Player Actions
   table, CombatBlock table, Limitations), `schema/actions.md` (maneuver,
   positioning field), `plan.md` (move Positioning out of "Not implemented";
   note Disengage/OA-lite under Action economy).
7. **Tests**:
   - `tests/test_combat.py` — new `TestPositioning` class (fixtures built
     inline via `ModuleCorpus.model_validate`, dice steered by monkeypatched
     `random.randint`): engagement formation, close-combat Disadvantage
     (player + NPC `ranged`), OA on LLM disengage assertion (incl. player OA
     when an enemy is moved away), Disengage avoids OA, prone engaged/
     unengaged split, unconscious auto-crit, pair pruning on death/flee,
     skip_turn suppresses OA.
   - `tests/test_systems.py` — new `attack_roll_mods` keys.
   - `tests/test_ruling_validation.py` — positioning assertion validation
     (bad ids, both-lists conflict, cap, wrong phase/action).
   - `tests/test_briefing.py`, `tests/test_display.py` — exposure.
   - Update `TestConditions` expectations for the prone split.
   - Run full `pytest` (non-LLM); integration fixtures
     (`tests/integration/combat_arena` etc.) stay green since defaults are
     behavior-preserving when no `positioning` is asserted and no `ranged`
     flags are set... except prone: verify existing fixture combat flows
     don't rely on flat prone Advantage.

## Deliberate non-goals (documented in doc/combat.md Limitations)

- No distance bands, ranges, zones, cover, flanking, or facing.
- No full reaction economy; OA-lite is automatic, one basic attack, no
  player opt-out.
- No OA on fleeing; NPC AI never voluntarily repositions (future `ai`
  maneuvers).
- Ability attacks treated as ranged for close-combat Disadvantage (no
  per-ability flag yet).

## Issues

The following concerns were surfaced during a review of the above plan:

### 1. OA directionality is underspecified

The assertion is a symmetric pair: `disengage: [["goblin", "player"]]`
(`:57`). It says "these two are no longer engaged" but carries **no mover**.
Yet the OA rule is directional:

- `:75-78` — breaking engagement provokes an OA *from the other party* (the
  enemy gets a free attack on whoever left).
- `:79-81` — "an enemy leaving the player's reach … provokes one automatic
  player OA."

Since assertions ride on the player's `combat`/`wait` action (`:60-61`), the
turn's actor is the player. So "player moves away from goblin" → goblin OA's
player is inferrable. But "goblin moves away from player" → player OA's goblin
is **not inferrable from a symmetric pair**, and it's happening on the
*player's* turn, which is strange timing for enemy movement.

As written, the engine cannot distinguish the two cases the plan promises.
Either:

- the assertion must carry a mover (e.g. directional `[mover, stationary]`,
  or a separate `mover` field), or
- player-side OAs effectively never fire in v1 (contradicting `:79-81`).

This needs a decision before implementation. It's the one place the design is
internally inconsistent rather than merely opinionated.

### 2. The feature is asymmetric in a player-unfavorable way

"NPC AI never voluntarily repositions" is a stated non-goal (`:186-187`), and
assertions only happen on the player's turn. Consequences:

- Enemies auto-engage by attacking (free) and **never pay OAs**, because they
  never move.
- The player pays OAs to leave engagement, or burns a full action on
  Disengage.
- Enemy ranged attackers, once engaged, just eat disadvantage forever — they
  never Disengage to kite. (This part *helps* the player, but makes enemies
  tactically inert.)

Net: the close-combat-disadvantage and OA rules bite the **player** far more
than enemies. A ranged player wading into a scrum will be disadvantaged and
will pay OAs to get out; enemies pay nothing. That's SRD-faithful in letter
but produces a play feel where positioning is mostly a tax on the player.
Without at least *some* NPC repositioning (or LLM-adjudicated enemy movement
on enemy turns), the "creative play" upside is lopsided.

### 3. Engagement is sticky and accumulative — fine, but only if the LLM actively manages it

"Attacking a new target *adds* engagement; it never breaks existing pairs"
(`:41-44`). Pairs are only shed by death/flee/Disengage/explicit LLM
assertion. So after a round or two of switching targets, a melee player is
engaged with everyone they've touched, and ranged-in-melee disadvantage
becomes near-universal *for the player* until they actively extract.

This is internally consistent (the OA-on-leave rule is the pressure release,
and "you're in the thick of it" is a legitimate TotM model), but it
**delegates graph hygiene to the LLM**. LLMs are not reliably proactive about
maintaining auxiliary state. If the LLM passively lets pairs accumulate,
ranged characters suffer silently. The 4-pair-changes/turn cap (`:64`) is a
double-edged guard: enough to churn, possibly not enough to clean up a
snarled graph in a big fight. There's no deterministic decay (e.g. "only
engaged with last melee target") as a fallback. Worth at least deciding
whether you trust the LLM here, or adding a minimal deterministic rule so the
state can't silently rot.

### 4. A bad positioning assertion could tank the whole turn

The corrective-retry loop gives **one** retry, then a semantically-still-
invalid ruling raises `LLMOutputError` and the turn falls back to
`FALLBACK_NARRATION` (`loop.py:420-433`). For a required field that's
acceptable; for an *optional* embellishment like `positioning`, it's
disproportionate. A malformed `positioning` shouldn't cost the player their
turn.

The plan should specify **graceful degradation**: if `positioning` fails
validation (even after retry), drop the positioning and proceed with the core
`combat`/`wait` action. Right now the plan folds positioning validation into
the same fail-the-turn loop (`:62-63`), which is the wrong severity.

### 5. Movement vocabulary is narrow and costly

The only way to reposition without eating an OA is Disengage — a full action,
no attack (and it breaks *all* the player's pairs at once, `:93`). There's no
5-foot-step / shift / partial movement. That's faithful to 5e, but in TotM —
where the whole pitch is fluid spatial imagination — "I want to slide over to
guard the wizard" costing your entire action (or an OA) is a real constraint
on creative flow. The plan is honest about this in non-goals, but if
"flexible creative play" is the goal, this is the place it's most constrained.
A lite "reposition to an adjacent engagement (no OA, no attack)" maneuver
would materially change the feel — worth at least considering as a future
add, not necessarily v1.

### 6. Disengage has weak value in solo combat

Without movement positioning being mechanically meaningful (no blocking
paths, no zone-to-zone movement, no cover to reach, no ally to protect),
the benefit of Disengage reduces to: avoid OAs and clear close-combat
Disadvantage for *one* future ranged attack. But the enemies will almost
certainly re-engage on their next turns. In 5e tabletop, Disengage +
move gets you *somewhere* (behind cover, farther from threats, closer to
an objective). Here, there is no "somewhere." The primary value
proposition — tactical repositioning — is toothless without spatial
semantics.

This becomes more worthwhile once there's multi-enemy management
(breaking engagement with 3 enemies in one action) and once ally combat
(disengaging from threats to protect a wounded follower) is in play. The
plan should explicitly discuss when Disengage is worth using vs. when it
is a trap option.

### 7. "Ability attacks treated as ranged" may be the wrong default

The plan says all ability `attack` effects get close-combat Disadvantage
when engaged, with a note that this can be refined later with a
per-ability flag. But melee-range abilities (Shocking Grasp, Inflict
Wounds, vampire's drain touch) are explicitly melee in 5e and should not
suffer this penalty. The current default will feel wrong immediately if
anyone adds such an ability. I'd recommend defaulting to *not* applying
close-combat Disadvantage to ability attacks, with an opt-in
`ranged: true` flag on the ability definition for the ones that actually
are ranged. That's a smaller change and avoids a known-wrong behavior
from day one.

### 8. No error-handling path for invalid positioning assertions

The plan mentions validation in `ruling_validation.py` (with the
corrective-retry loop) and re-validation at the engine level, but
doesn't specify what happens when an assertion *fails* engine validation.
Presumably the invalid `positioning` block is stripped and the turn
proceeds without it, but this should be explicit: does the player's
action still resolve? Does the LLM get informed? An invalid positioning
block is a minor error, not a reason to reject the entire action — but
the LLM should know so it doesn't repeat the mistake next turn.

### 9. No ally↔enemy OA handling spelled out

The plan covers player↔enemy OAs both ways, and the general rule
("Breaking engagement with a living enemy other than via Disengage
provokes one basic melee attack from that enemy") covers ally↔enemy
cases. But the implementation section only calls out "an enemy leaving
the player's reach provokes one automatic player OA." Party combat is
implemented, so followers can be engaged with enemies and the LLM could
disengage them. The plan should explicitly note that ally OAs (both
dealt and received) are in scope.

### 10. Fleeing vs. Disengage asymmetry could confuse players

Fleeing (DEX check, change rooms) avoids OAs entirely. Disengage
(costs your action, stay in combat) avoids OAs but leaves you in the
fight. A player might reasonably ask: "If I want to break engagement
but stay in the fight, why does it cost more (my action + enemies will
re-engage) than fleeing (one check, escape cleanly)?" The plan
documents this as a simplification, which is fine, but it'll feel
arbitrary in play unless the LLM can narratively justify it.  It's
worth checking what the SRD says about this, and maybe updating the
fleeing rules accordingly.

## Minor notes

- **SRD-fidelity gap:** `auto_crit_against_engaged` is scoped to
  `unconscious` only (`:119-121`), but SRD grants melee auto-crit to
  `paralyzed` and `stunned` too (`conditions.json:49-58, 102-111`
  descriptions both reference it). Either intentional (document it) or an
  omission.
- **Headless display** (`mgmai/game/headless.py:194-235`) builds its own
  combatants view and isn't in the plan's exposure list (`:124-137`).
  Integration tests run through headless, so engagement markers won't show
  there unless updated.
- **`ranged` override plumbing:** `resolve_npc_attack` does per-attack-
  overrides-block for `atk`/`dmg`/`dmg_type` (`five_e.py:581-587`); the new
  `ranged` must follow the same pattern or block-level `ranged` is silently
  ignored whenever an `attacks` list is present. Implementation detail, but
  the plan doesn't call it out.
- **Prone inversion:** flat Advantage → engaged/unengaged split (`:108-111`)
  is correct SRD but flips the current "prone = easier to hit" intuition for
  any ranged/non-engaged attacker. Real play-experience shift, not just a
  fixture concern.
- **No concept of "you can't engage through obstacles."** If there's a
  chasm or a wall of fire between two combatants, the LLM can simply not
  assert engagement between them, but there's no mechanical or
  briefing-level enforcement. The LLM has to remember the narrative
  obstacle. This is probably OK for v1 but might cause issues in complex
  encounter spaces.
- **No consideration of AoE positioning.** What if the player uses
  Burning Hands ("a 15-foot cone") and the LLM narrates it catching
  multiple enemies? The engagement model doesn't capture relative
  positions among NPCs, so the LLM can't mechanically reason about which
  NPCs are in the cone. It'll have to guess based on narrative
  consistency. This isn't a plan flaw (AoE is a spellcasting feature
  that doesn't exist yet) but it's a future tension to note.
