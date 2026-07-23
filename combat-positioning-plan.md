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
