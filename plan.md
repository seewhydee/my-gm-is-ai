# Status Effects Rework: First-Class Status Effects (Option A)

> **Note on terminology.** This plan was originally written using
> "condition" for the status-effect concept (poisoned, stunned, prone,
> …).  That conflicted with the pre-existing "condition" sense in the
> codebase (the `ConditionExpression` gating object and "condition
> strings" like `flag:foo == true`).  After implementation, the
> status-effect sense was renamed throughout to **`status_effect`**:
> `ConditionDef` → `StatusEffectDef`, `apply_condition` →
> `apply_status_effect`, `cure_conditions` → `cure_status_effects`,
> the corpus `conditions` block → `status_effects`, the `condition:`
> condition-string domain → `status_effect:`, and the
> `condition.applied`/`ticked`/`cleared` events → `status_effect.*`.
> The prose below still uses "condition" in places; identifiers and
> code references have been updated.

## Problem statement

The current "combat conditions" subsystem (`apply_status_effect` Result field,
`poisoned`/`stunned`/`prone`) is narrowly tailored to combat and built on a
lightweight `Dict[str, int]` payload rather than an explicitly-documented
type.  Three concrete problems:

1. **Three hardcoded IDs.**  `FiveESystem.attack_roll_mods`
   (`mgmai/engine/systems/five_e.py:261-262`) string-matches `"poisoned"`,
   `"stunned"`, and `"prone"`; `_tick_status_effects`
   (`mgmai/engine/combat.py:462`) hardcodes `prone`'s auto-stand.  There is
   no corpus-level type definition — nothing parallel to `EquipBlock`
   (`schema/corpus.md:1224`) or `ConsumableBlock` (`schema/corpus.md:1216`)
   — so adventure authors cannot define new conditions, and the engine's
   behavior is undocumented in the corpus itself (only in `doc/combat.md`).

2. **Overlap with state fields.**  Reserved entity state fields
   (`alive`, `current_hp`, `hidden`, `open`, …) live at
   `schema/corpus.md:1090-1099`; `conditions` is a reserved sub-object on
   `entity_states` (`schema/hard-state.md:178`) and on `PlayerState`
   (`mgmai/models/hard_state.py:34-35`).  Both are engine-managed mutable
   per-entity state, but with different scoping, different event semantics
   (`entity_state.changed` fires for state fields but not for conditions;
   `schema/events.md:143`), and different queryability (no `condition:`
   domain in condition strings).  Authors cannot decide which mechanism to
   use for a debuff, and the `cursed` example at `schema/corpus.md:1117`
   shows the schema already anticipates buffs-as-state-fields.

3. **Combat-only restriction.**  Conditions "tick at the start of the
   afflicted combatant's turn and all conditions clear when combat ends"
   (`schema/corpus.md:345-346`; `doc/combat.md:190-191`).  A trap that
   poisons the player (`schema/corpus.md:990-1008`) cannot use
   `apply_status_effect`; the author must fall back to a flag plus a
   hand-rolled `turn.end` reaction.  `ConsumableBlock.cure_status_effects`
   (`schema/corpus.md:1216-1221`) inherits the same restriction: a Cure
   Poison potion drunk out of combat has nothing to clear.

A subtler obstacle: the player is not a regular entity
(`schema/corpus.md:1016-1017` reserves `"player"`; the player's state
lives on `PlayerState`, not in `entity_states`).  So even an author who
*wanted* to model `poisoned` as a state field has nowhere clean to put it
on the player today.  This rework routes around that asymmetry (one
storage helper handles both cases) rather than fixing it; promoting the
player to a real entity is a separate, larger rework explicitly out of
scope here.

Note: the project is pre-alpha.  Backward compatibility with existing
corpora, saved games, and out-of-tree `ResolutionSystem` subclasses is a
non-factor; the design below chooses the cleanest semantics without
migration shims.

## Approach: Option A

Treat conditions the way the schema already treats equipment and
consumables: a **typed, top-level corpus block** with engine behavior
declared per-condition rather than hardcoded.  Concretely:

- A new top-level `conditions` block defines each condition's display
  name, description, duration, scope (combat vs. persistent), and
  system-specific effects (`disadvantage_on_attack`, …).
- The three legacy conditions become *built-in defaults* supplied by the
  engine, overlaid by corpus entries of the same ID.
- `apply_status_effect` gains an optional `target` so NPC-on-NPC and
  ability-on-enemy debuffs work symmetrically.
- `scope: "persistent"` lets traps apply conditions that survive and tick
  outside combat.
- All condition mutations go through two helpers that emit
  `status_effect.applied` / `status_effect.ticked` / `status_effect.cleared` events.
- `FiveESystem.attack_roll_mods` reads `system_effects` from the active
  condition definitions instead of string-matching IDs.

This keeps the *concept* of a condition (durations, ticking,
combat-mediated effects on rolls) — which doesn't map cleanly onto
bag-of-data state fields — while removing the hardcoded special-casing.

## Design decisions

- **Minimal `StatusEffectDef` field matrix.**  The tick trigger is derived
  from `scope`, and decay is derived from `duration` — no separate
  `tick`/`decay`/`auto_clear` flags, so no contradictory combinations:

  ```python
  class StatusEffectDef(BaseModel):
      name: str = ""            # cosmetic display name; dict key is canonical ID
      description: str = ""
      scope: Literal["combat", "persistent"] = "combat"
      duration: Literal["rounds", "until_cleared", "until_turn_start"] = "rounds"
      skip_turn: bool = False
      tick_effect: Optional[Result] = None      # see "tick_effect" below
      system_effects: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
  ```

  - `scope: "combat"` — ticks at the start of the afflicted combatant's
    turn; cleared at combat end.
  - `scope: "persistent"` — ticks on `turn.end` (only when the resolution
    costs a turn; see Phase 3); survives combat end.
  - `duration: "rounds"` — decrements on each tick, expires at zero.
  - `duration: "until_turn_start"` — removed on the afflicted's first
    tick (legacy `prone` behavior).
  - `duration: "until_cleared"` — never ticks down; removed only by
    curing, combat end (combat-scoped), or a manual Result.

- **`skip_turn` is a first-class field, not a system effect.**  Whether a
  condition skips your turn is turn-structure behavior owned by the
  system-agnostic combat loop; `system_effects` is reserved for
  system-specific roll modifiers.  This avoids `combat.py` reaching into
  a `"5e"`-namespaced key.

- **Built-in defaults, overlaid wholesale.**  The three defaults live in
  a new module `mgmai/engine/status_effects.py` (NOT
  `mgmai/engine/conditions.py` — that module already exists and is the
  condition-*string* evaluator).  `ModuleCorpus.effective_status_effects()`
  returns defaults overlaid by the corpus block; a corpus entry
  **replaces** the default of the same ID wholesale (no field-level
  merge).

  ```python
  "poisoned":  scope combat, duration rounds,
               system_effects {"5e": {"disadvantage_on_attack": True,
                                      "disadvantage_on_ability_checks": True}}
  "stunned":   scope combat, duration rounds, skip_turn True,
               system_effects {"5e": {"advantage_against": True}}
  "prone":     scope combat, duration until_turn_start,
               system_effects {"5e": {"disadvantage_on_attack": True,
                                      "advantage_against": True}}
  ```

- **Two system-effect keys for 5e, matching real 5e semantics.**
  `disadvantage_on_attack` (attacker side of an attack roll),
  `advantage_against` (target side of an attack roll), and
  `disadvantage_on_ability_checks` (flee and future ability checks).
  Poisoned declares both disadvantage keys; the flee check
  (`five_e.py:504`) consults `disadvantage_on_ability_checks`.

- **Scope is per-definition; distinct scopes need distinct IDs.**  A
  combat poison and a trap poison are two definitions (e.g. `poisoned`
  vs. `trap_poison`).  This keeps one unambiguous lifetime per ID; the
  docs must state this pattern explicitly.

- **All mutations through two event-emitting helpers.**  New functions
  `apply_status_effect(target_id, effect_id, rounds, hard, corpus, source)` and
  `remove_status_effect(target_id, effect_id, hard, corpus, reason)` in
  `mgmai/engine/status_effects.py`.  Every mutation site routes through
  them: Result application (`resolver.py:1499-1503`), save effects
  (`combat.py:742-750`), consumable curing (`combat.py:1433-1434`), tick
  expiry, prone-style auto-clear, and combat-end clearing.  Events
  therefore cannot be forgotten by any path.

- **Reapplication takes the max.**  Applying a condition the target
  already has sets its remaining rounds to `max(existing, new)`.  (Today
  both application paths blindly overwrite.)

- **`tick_effect` applies to the player only.**  `Result` has
  `player_damage`/`player_heal` but no entity-targeted fields
  (`mgmai/models/corpus.py:254`), so a `tick_effect` on an
  entity-afflicted condition is ignored (with a debug log).  Docs state
  this limitation; entity-targeted tick effects are future work.

- **Persistent ticking is tied to turn-costing actions.**  `turn.end`
  only dispatches when `resolution.costs_turn` (`engine.py:525`), so
  persistent conditions tick once per turn-costing player action — not
  during dialogue or free actions.  This is the intended semantic and
  must be documented.

- **Event model complements state fields.**  `entity_state.changed`
  continues to *not* fire for condition changes; the `condition.*`
  family replaces it for this case.  Events:

  - `status_effect.applied` — `target_id`, `status_effect_id`, `rounds`,
    `source` (`"result"`, `"save_failure"`, `"reaction"`, …).
  - `status_effect.ticked` — `target_id`, `status_effect_id`,
    `remaining_rounds`, `expired` (bool).
  - `status_effect.cleared` — `target_id`, `status_effect_id`,
    `reason` (`"expired"`, `"combat_end"`, `"consumable"`,
    `"auto_clear"`, `"manual"`).

- **Query grammar.**  New `condition:` domain in condition strings
  (evaluated in `mgmai/engine/conditions.py`; the existing regex at
  line 33 already accepts dotted keys):

  - `status_effect:poisoned` — true iff the player has the condition.
  - `status_effect:poisoned.rounds >= 2` — numeric comparison of the
    player's remaining rounds.  `rounds` is a reserved second segment.
  - `status_effect:rat.poisoned` — true iff entity `rat` has the condition
    (two-segment form where the first segment is not a defined condition
    whose second segment is `rounds`; `status_effect:player.poisoned` is
    also valid and equivalent to the bare form).

- **`attack_roll_mods` takes the corpus.**  Signature becomes
  `attack_roll_mods(self, attacker_status_effects, target_status_effects, corpus)`,
  consistent with other `ResolutionSystem` methods that already take
  `corpus` (e.g. `compute_player_damage_expr`).  Base-class default
  keeps returning `(False, False)`.

- **Unknown condition IDs are a validator warning.**  Application of an
  undefined condition ID still works at runtime (adventures may
  forward-declare), but `scripts/validate_adventure.py` warns about
  `apply_status_effect`/`cure_status_effects` references to IDs not present in
  `effective_status_effects()`.

- **The dict key is canonical; `name` is cosmetic.**  Display surfaces
  may show `StatusEffectDef.name`; storage, events, queries, and tests use
  the key.

## Phase 1 — Corpus model

1. Add `StatusEffectDef` in `mgmai/models/corpus.py` (alongside
   `ApplyStatusEffect` at line 162), per the field matrix above.
2. Add a top-level `conditions: Dict[str, StatusEffectDef]` field on
   `ModuleCorpus` (default empty), plus
   `ModuleCorpus.effective_status_effects()` returning the built-in defaults
   (imported from `mgmai/engine/status_effects.py` — or move the
   defaults into `mgmai/models/corpus.py` if the import would be
   circular; models must not import from engine) overlaid by the corpus
   block.  Prefer defining the defaults in `mgmai/models/corpus.py` next
   to `StatusEffectDef` and having the engine import them from there.
3. Extend `ApplyStatusEffect` (`mgmai/models/corpus.py:162-170`) with
   `target: str = "player"`.  Update its docstring: conditions are no
   longer combat-only.
4. Update `schema/corpus.md`:
   - Top-level structure list (lines 11-22).
   - New "Conditions" section (after "Abilities") documenting the
     block, `StatusEffectDef` fields, the three built-in defaults, the
     two-IDs-for-two-scopes pattern, and the player-only `tick_effect`
     limitation.
   - Update the `apply_status_effect` row (line 287) for `target`; replace
     the inline behavior at lines 340-346 with a reference to the new
     section.

## Phase 2 — Mutation helpers and events

1. Create `mgmai/engine/status_effects.py` with
   `apply_status_effect(...)` / `remove_status_effect(...)` (signatures above).
   - `apply_status_effect` validates the ID against
     `effective_status_effects()` (unknown IDs pass through with a debug
     log), applies the max-on-reapplication rule, writes to
     `hard.player.status_effects` or
     `entity_states[target_id]["status_effects"]`, and emits
     `status_effect.applied`.
   - `remove_status_effect` removes the entry if present and emits
     `status_effect.cleared` with the given reason.
   - Event emission uses the existing event-dispatch machinery; check
     how combat code currently emits events (e.g. `combat.ended`) and
     thread the dispatch context through.  If threading dispatch into
     every call site is too invasive, emit via the same mechanism used
     for other engine-owned events in that file.
2. Route all mutation sites through the helpers:
   - `mgmai/engine/resolver.py:1499-1503` (Result.apply_status_effect) —
     pass `result.apply_status_effect.target`, source `"result"`.
   - `mgmai/engine/combat.py:742-750` (SaveEffect) — pass the save's
     `target_id`, source `"save_failure"`.
   - Consumable curing at `mgmai/engine/combat.py:1433-1434` — reason
     `"consumable"`.
3. Emit the events documentation update in `schema/events.md`:
   the three new events plus an explicit note (near lines 137-160)
   that `entity_state.changed` does **not** fire for condition changes.

## Phase 3 — Ticking and clearing

1. Generalize `_tick_status_effects` (`mgmai/engine/combat.py:453-466`):
   for each condition on the combatant, look up its `StatusEffectDef`:
   - `duration == "until_turn_start"` → remove (reason `"auto_clear"`).
   - `duration == "rounds"` and `scope == "combat"` → decrement; on
     reaching zero remove (reason `"expired"`).  Emit
     `status_effect.ticked` either way (with `expired` flag).
   - Otherwise (persistent, or `until_cleared`) leave alone.
2. Generalize `_clear_status_effects` (`combat.py:469-473`): remove only
   conditions whose `scope == "combat"` (reason `"combat_end"`).
3. Add `_tick_persistent_status_effects(hard, corpus)` in
   `mgmai/engine/engine.py`, invoked in the `turn.end` block
   (`engine.py:524-535`) **before** the `turn.end` dispatch:
   - For the player and every entity with a `conditions` map:
     decrement conditions whose def has `scope == "persistent"` and
     `duration == "rounds"`; remove at zero (reason `"expired"`); emit
     `status_effect.ticked`.
   - Apply `tick_effect` when the afflicted target is the player.
   - Tick-effect damage that drops the player to 0 HP must still reach
     the death check at `engine.py:543` — the existing ordering (tick
     before turn.end dispatch, death check after) already does this;
     add a regression test.
4. Replace the `stunned` turn-skip string-matches
   (`combat.py:1031-1032`, `:1492-1493`) with a `skip_turn` lookup on
   the condition definitions.

## Phase 4 — System layer

1. Change `ResolutionSystem.attack_roll_mods`
   (`mgmai/engine/systems/base.py:241-246`) to
   `(self, attacker_status_effects, target_status_effects, corpus)`.
2. Rewrite `FiveESystem.attack_roll_mods`
   (`five_e.py:253-263`) to consult
   `corpus.effective_status_effects()[id].system_effects.get("5e", {})`:
   attacker side ORs `disadvantage_on_attack`; target side ORs
   `advantage_against`.
3. Update the two callers (`five_e.py:323, 420`) to pass `corpus`.
4. Rewrite the flee disadvantage check (`five_e.py:504`) to OR
   `disadvantage_on_ability_checks` over the player's conditions.
5. The existing tests at `tests/test_combat.py:2368-2628` are the
   regression anchor: the legacy three conditions must produce
   identical advantage/disadvantage results.

## Phase 5 — Query domain

1. Add the `condition:` domain to `mgmai/engine/conditions.py`
   (add to `DOMAINS` at line 32; new branch in
   `evaluate_condition_string`), per the grammar in Design decisions.
2. Document the domain in `schema/corpus.md:126-179` (condition-string
   reference).

## Phase 6 — Display, briefing, validator, docs

1. Combat status panel (`mgmai/game/display.py:191, 201, 210, 284-285,
   341-342`) and headless snapshot (`mgmai/game/headless.py:200, 208,
   215`): show `StatusEffectDef.name` (falling back to the ID) instead of
   the raw ID.
2. GM briefing (`mgmai/context/assembler.py:402, 414`): include each
   active condition's `description` so the GM LLM knows what it does.
3. `scripts/validate_adventure.py`: warn on `apply_status_effect` /
   `cure_status_effects` references to undefined condition IDs.
4. Docs:
   - `doc/combat.md:185-209` — replace the hardcoded conditions table
     with the corpus `conditions` block, the built-in defaults,
     `scope: "persistent"`, and the turn-costing-action tick semantic.
   - `schema/hard-state.md:178` — clarify that `conditions` holds IDs
     whose definitions live in the corpus; combat-scoped entries clear
     at combat end, persistent entries survive.
   - `doc/gear.md:268, 278` — `cure_status_effects` works for any defined
     condition, in or out of combat.
   - `schema/scenario-generation.md` — add a step for declaring custom
     conditions, parallel to the `abilities` step, including the
     two-IDs-for-two-scopes pattern.

## Phase 7 — Tests and fixture

1. New unit tests in `tests/test_combat.py` (extending the
   `# 17. Conditions` block at line 2368):
   - Custom corpus condition (e.g. `frightened`) with
     `system_effects {"5e": {"disadvantage_on_attack": true}}` gives
     disadvantage on attack.
   - Corpus override of a built-in default replaces it wholesale.
   - Persistent condition applied from a non-combat Result ticks on
     `turn.end` (turn-costing actions only) and expires after N turns;
     `tick_effect` damages the player; lethal tick damage still
     triggers the death check.
   - `apply_status_effect.target` set to an NPC ID applies to that NPC
     (verified via `get_status_effects(npc_id, hard)`).
   - Reapplication takes the max of remaining rounds.
   - Combat end clears `scope: "combat"` conditions but leaves
     `scope: "persistent"` conditions intact.
   - `duration: "until_turn_start"` reproduces legacy prone behavior.
   - `skip_turn: true` on a custom condition skips the turn.
2. `condition:` query tests (player presence, `.rounds` comparison,
   entity form).
3. New tests in `tests/test_events.py` for the three event types:
   context keys, and dispatch timing relative to `turn.end` and
   `combat.ended`.
4. Keep `tests/integration/test_venom_pit.py` green end-to-end —
   regression anchor for the legacy path.  Audit after Phase 4.
5. Keep `tests/test_display.py:140-183` and
   `tests/test_headless.py:328-349, 462-481` green; update only where
   the Phase 6 display label changes require it.
6. Add a sample custom condition to `tests/fixtures/mini_adventure/`
   so the corpus loader and validator exercise the new block.

## Build order and status

- [x] Phase 1: corpus model — `StatusEffectDef`, top-level block,
      `effective_status_effects()`, built-in defaults, `ApplyStatusEffect.target`.
- [x] Phase 2: mutation helpers and events — `status_effects.py`;
      route resolver, save effects, and curing; `status_effect.applied` /
      `status_effect.cleared`; events docs.
- [x] Phase 3: ticking and clearing — generalize `_tick_status_effects` and
      `_clear_status_effects`; `_tick_persistent_status_effects` on `turn.end`;
      `status_effect.ticked`; `skip_turn`.
- [x] Phase 4: system layer — `attack_roll_mods` takes corpus; 5e
      `system_effects`; flee via `disadvantage_on_ability_checks`.
- [x] Phase 5: query domain — `condition:` condition strings.
- [x] Phase 6: display, briefing, validator, docs.
- [x] Phase 7: tests and fixture.

Each phase is independently mergeable with the regular test suite green.
Phases 1-4 are the load-bearing core; Phases 5-7 can be sequenced
afterward.
