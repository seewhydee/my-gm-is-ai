# Theater-of-the-Mind Positioning for Combat

## Goal

Add abstract positioning to the combat engine — no grid, no distances. The
single concept is **engagement**: a symmetric "within melee reach" relation
between two combatants. The ruling LLM may assert engagement changes for any
pair of combatants (full-scene adjudication, validated by the engine), and
leaving engagement without Disengaging provokes a lite Opportunity Attack
(OA). This unlocks the SRD 5.2.1 rules that are currently stubbed for lack
of a positioning model:

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
  `_set_engagement(combat, a, b, on: bool)`, `_is_engaged(combat, a, b) -> bool`.

### Engagement lifecycle (deterministic defaults)

- A **melee attack** (player with non-`ranged` equipped weapon/unarmed; NPC
  attack not flagged `ranged`) engages attacker ↔ target, and **automatically
  disengages** the attacker from all previous targets, *unless* the same
  ruling contains an explicit `positioning` assertion preserving other
  engagements. This prevents silent graph rot while still allowing the LLM
  to narrate complex multi-engagement scenes (e.g. "you spin between the
  two goblins, keeping both at sword's length").
- Combat entry via the player's direct `interact`/`attack`: player ↔ source
  NPC start engaged if the player's equipped weapon is not ranged.
  Encounter/ambush starts: no initial pairs; enemies engage by attacking.
- Engagement breaks only via: explicit Disengage maneuver, validated LLM
  assertion, death, flee, or combat end.
- **Fleeing is unchanged** (the DEX check abstracts the getaway; no OA on
  flee — documented simplification).

> **Play-feel note:** Engagement accumulates across target switches, so after
> a few rounds a melee combatant may be engaged with every foe they've
> touched. The 4-pair-change cap and LLM assertions are the pressure-release
> valves. See "Engagement accumulation and deterministic hygiene" in the
> Design Decisions section below.

### LLM assertion channel (full-scene adjudication)

- New optional field on `_BaseAction` (`mgmai/models/actions.py:27`):
  `positioning: Optional[PositioningAssertion]` where
  `PositioningAssertion = {engage: list[list[str]], disengage: list[list[str]]}`.
  Keeps the Call-1 contract (one JSON object with `action_type`) — no wrapper
  type, no parser change beyond the model.
  - **`engage` entries:** symmetric pairs `[a, b]` — these two combatants
    are now within melee reach of each other.
  - **`disengage` entries:** directional pairs `[mover, stationary]` — the
    first element is the combatant leaving, the second stays put. This
    determines OA direction: the stationary party gets the free attack on
    the mover. If both parties are moving away from each other (narrative
    retreat), the LLM should issue two `disengage` entries, one in each
    direction, or use a `maneuver` action.
- Valid in combat only, on `combat` and `wait` actions (rejected on
  `move`/`examine`/out-of-combat). Validation in
  `mgmai/llm/ruling_validation.py` (paired with the existing corrective-retry
  loop in `game/loop.py:_call_ruling`): ids must be living combatants in the
  briefing; a pair may not appear in both lists; at most 4 pair-changes per
  turn. Engine re-validates at apply time (containment: worst case is a few
  adjacency flips whose mechanical impact is bounded to adv/disadv/OAs).
- **Graceful degradation:** If `positioning` fails validation (even after the
  corrective retry), the invalid `positioning` block is **stripped** and the
  core `combat`/`wait` action proceeds normally. A failed positioning
  assertion must never raise `LLMOutputError` or cost the player their turn.
  The engine logs a warning (`result.warnings`) so the LLM can learn from the
  mistake next turn, but play continues. (`loop.py:420-433` must branch on
  whether the error is in required fields vs. optional embellishments.)
  - If a `disengage` entry is malformed (e.g. IDs not in combat, or the
    pair is not currently engaged), that specific entry is dropped but the
    rest of the positioning block and the core action proceed.
- Engine applies assertions at the top of `resolve_combat_turn`
  (`mgmai/engine/combat.py:1542`), before the declared action: apply
  engage/disengage → resolve provoked OAs → resolve the action. (OAs first,
  since a lethal OA cancels the action — mirrors SRD "occurs right before it
  leaves your reach".)

### OA-lite

- Breaking engagement with a living enemy other than via Disengage provokes
  **one basic melee attack** from the stationary party against the mover.
  The mover is determined by the `disengage` directional convention
  (`[mover, stationary]`) for LLM assertions, or by the attack direction for
  auto-disengage on melee attack (the previous target is stationary, the
  attacker is the mover).
  - Enemy OAs on player movement: resolved via `system.resolve_npc_attack`
    (block-level `atk`/`dmg`, or its first attack def; no multiattack, no
    abilities, no on-hit effects beyond the basic attack's own).
  - Player OAs on enemy movement: resolved via `resolve_player_attack` with
    the equipped weapon when an LLM assertion moves an enemy away from the
    player. Logged as `CombatLogEntry(action="opportunity_attack")`.
- **Ally OAs are in scope:** Followers engaged with enemies can provoke and
  receive OAs on the same terms. The engine resolves OAs for any pair break
  where the stationary party is capable of making one.
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

> **Play-feel note:** Disengage's value is highest when managing multiple
> engagements (break 3 enemy pairs in one action) or when protecting allies
> (break engagement to intercept a threat headed for a wounded follower). In
> solo 1v1 combat with no spatial semantics, it is often weaker than simply
> attacking — the enemy will likely re-engage next turn. The LLM should
> narrate its value contextually rather than presenting it as a universally
> strong option.

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
  (`mgmai/models/corpus.py`). **Ability `attack` effects do NOT count as
  ranged for close-combat Disadvantage by default**; a per-ability opt-in
  `ranged: true` flag can be added later for abilities that genuinely are
  (e.g. Eldritch Blast, Ray of Frost). This avoids penalizing melee-touch
  abilities like Shocking Grasp or Inflict Wounds from day one.
- Auto-crit: new key `auto_crit_against_engaged` on the `unconscious`,
  `paralyzed`, and `stunned` conditions (SRD-fidelity fix: all three grant
  melee auto-crit within reach). On a hit, if the target has it and attacker
  is engaged with the target → `critical = True` (double dice).

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
- **Headless display** (`mgmai/game/headless.py:194-235`) builds its own
  combatants view and must also show engagement markers (used by integration
  tests).
- No new event-bus event type in v1 (engagement is visible in the combat
  log; corpus reactions on positioning are speculative).

## Work plan

1. **Models**: `CombatState.engagement`; `PositioningAssertion` +
   `positioning` on `_BaseAction`; `maneuver` on `CombatAction` (target →
   Optional + validator); `ranged` on `CombatBlock`/`NPCAttackDef`.
2. **Engine** (`mgmai/engine/combat.py`): engagement helpers; auto-engage on
   melee attacks (player :1630 area, NPC :1171 area, combat entry :1354);
   apply+re-validate `positioning` assertions at top of `resolve_combat_turn`
   with graceful degradation (strip invalid, warn, proceed); OA resolution
   helper (shared for player/NPC movers); Disengage maneuver branch; prune
   pairs on death/flee.
3. **System** (`five_e.py`, `conditions.json`): engaged-aware
   `attack_roll_mods`, close-combat Disadvantage (ability attacks exempt
   by default), `auto_crit_against_engaged` on unconscious/paralyzed/stunned,
   prone condition update; delete the stale "no positioning" comments.
4. **LLM surface**: ruling_validation for `positioning` (soft-fail, not hard
   fail); ruling.j2 rewrite of the combat action rules; briefing
   `engaged_with`; prose_combat.j2 + indicators/prefix formatting for
   `reposition`/`maneuver`/`opportunity_attack` entries.
5. **Display**: engagement markers in the combat panel and headless display.
6. **Docs**: `doc/combat.md` (new Positioning section; update Player Actions
   table, CombatBlock table, Limitations), `schema/actions.md` (maneuver,
   positioning field), `plan.md` (move Positioning out of "Not implemented";
   note Disengage/OA-lite under Action economy).
7. **Tests**:
   - `tests/test_combat.py` — new `TestPositioning` class (fixtures built
    inline via `ModuleCorpus.model_validate`, dice steered by monkeypatched
    `random.randint`): engagement formation, last-target auto-disengage with
    LLM override, close-combat Disadvantage (player + NPC `ranged`), OA on
    disengage (directional `[mover, stationary]`), Disengage avoids OA, prone
    engaged/unengaged split, unconscious auto-crit, pair pruning on death/flee,
    skip_turn suppresses OA, graceful degradation of invalid positioning.
   - `tests/test_systems.py` — new `attack_roll_mods` keys; ability attacks
     not flagged ranged exempt from close-combat Disadvantage.
   - `tests/test_ruling_validation.py` — positioning assertion validation
     (bad ids, both-lists conflict, cap, wrong phase/action, soft-fail path).
   - `tests/test_briefing.py`, `tests/test_display.py` — exposure.
   - Update `TestConditions` expectations for the prone split and
     paralyzed/stunned auto-crit.
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
- No per-ability ranged flag in v1 (melee-touch abilities are exempt from
  close-combat Disadvantage; a future flag will opt in genuinely ranged
  abilities like Eldritch Blast).

## Play-feel analysis

The following observations are not plan flaws — they are honest
consequences of the chosen scope that should be documented so the LLM can
narrate around them.

### Asymmetry: rules bite the player more than enemies

Enemies auto-engage by attacking (free) and never pay OAs because they
never move. The player pays OAs to leave engagement, or burns a full
action on Disengage. Enemy ranged attackers, once engaged, just eat
disadvantage forever — they never Disengage to kite. (This part *helps*
the player, but makes enemies tactically inert.)

Net: positioning is mostly a **tax on the player** unless the LLM actively
uses positioning assertions to move enemies and create dynamic scenes.
Without LLM-initiated enemy movement, the "creative play" upside is
lopsided. Document this in `doc/combat.md` so authors know the LLM needs
to be proactive for positioning to feel alive.

### Disengage value in solo vs. group combat

Without movement positioning being mechanically meaningful (no blocking
paths, no zones, no cover to reach), Disengage's value is contextual:

- **Solo 1v1:** Usually weak. Costs your action, enemy re-engages next turn.
  Only worth it if you have a critical ranged attack to make.
- **Multi-enemy:** Strong. Breaking 3 engagements in one action is
  action-economy efficient.
- **Ally combat:** Strong. Disengaging from threats to protect a wounded
  follower is narratively and mechanically meaningful.

The LLM should present Disengage as situational, not a default.

### Fleeing vs. Disengage: why fleeing is "better"

Fleeing (DEX check, change rooms) avoids OAs entirely. Disengage (costs
your action, stay in combat) avoids OAs but leaves you in the fight where
enemies will re-engage. A player might reasonably ask: "Why does fleeing
cost less than repositioning?"

Answer: fleeing is a **narrative exit** (you're giving up the fight and
trusting the dice to escape). Disengage is a **tactical reposition**
within the fight. The asymmetry is deliberate: fleeing has failure stakes
(DEX check may fail, you may be chased), while Disengage is reliable but
costly. The LLM should narrate fleeing as desperate and Disengage as
controlled.

### Movement vocabulary

The only way to reposition without eating an OA is Disengage — a full
action, no attack. There's no 5-foot-step / shift / partial movement.
That's faithful to 5e, but in TotM it constrains creative flow. A future
"Step" maneuver (move to a new engagement without an OA, no attack) would
materially change the feel. Note as a v2 enhancement in `plan.md`.

## Implementation notes

- **Prone inversion:** Flat Advantage → engaged/unengaged split is correct
  SRD but flips the current "prone = easier to hit" intuition for ranged
  attackers. Playtesters may need adjustment.
- **Ranged override plumbing:** `resolve_npc_attack` does per-attack
  overrides-block for `atk`/`dmg`/`dmg_type` (`five_e.py:581-587`); the new
  `ranged` must follow the same pattern or block-level `ranged` is silently
  ignored whenever an `attacks` list is present. Explicitly call this out in
  the implementation.
- **No "engage through obstacles":** If there's a chasm or wall of fire
  between two combatants, the LLM simply doesn't assert engagement. There's
  no mechanical enforcement — the LLM must remember narrative obstacles.
  OK for v1.
- **AoE positioning tension:** Burning Hands ("15-foot cone") doesn't have
  a mechanical way to determine which NPCs are in the cone, since engagement
  only tracks pairwise reach, not relative NPC-to-NPC positions. The LLM
  will narrate and the engine will trust it. This is a known future tension
  if/when AoE spellcasting arrives.
