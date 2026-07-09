# Plan: Multi-combatant encounters (`combatants` + `combat_group`)

## Background and motivation

The combat engine is fully multi-combatant, but nothing can *populate*
more than one enemy. `enter_combat(enemy_ids, ...)` accepts a list and
threads it through initiative (`combat.py:167`), pre-player NPC turns
(`combat.py:232`), the victory check (`combat.py:324-331`), and the flee
DC (`combat.py:336-345`). Yet every call site passes a **single-element**
list:

- `resolver.py:897` — direct attack: `enter_combat([target_id])`
- `engine.py:273` — encounter outcome: `enter_combat([encounter_source_id])`
- `event_bus.py:431` — reaction-fired encounter: `enter_combat([source_id])`

Three problems follow:

1. **"Three goblins attack" is inexpressible.** Combat is always 1-v-1;
   there is no channel from a `Result` to the combatant set.
2. **Mechanic-sourced combat is broken.** For a `mechanics` encounter,
   `source_id` is the *mechanic id*, which is not an entity.
   `enter_combat` leaves it in `combatants` (`combat.py:217`) but
   `roll_initiative` drops it (`combat.py:169`) — a phantom combatant not
   in the initiative order, i.e. a degenerate fight the player can only
   leave by fleeing.
3. **`trigger_combat` is a no-op off the encounter path.** The generic
   Result-application path `_apply_result` (`resolver.py:1270`) handles
   every field *including* `game_over` (`resolver.py:1404`) **but not
   `trigger_combat`**. The field is only consumed by encounter resolution
   (`encounters.py:122` → `engine.py:271` / `event_bus.py:429`). So
   `trigger_combat: true` on an interaction result, a reaction
   `effect.result`, an `on_examine` result, or a `then_check` branch does
   nothing. This contradicts the docs (`scenario-generation.md:1489-1490`,
   `corpus.md:276`), which state it generally. (The runtime no-op is in
   fact already locked in by `test_event_bus.py:1311-1313`; the fix below
   makes the corpus validation and docs match that intended scope rather
   than changing runtime behaviour.)

This plan closes all three with two composable, declarative features and
a validation/documentation fix. It does **not** change the combat loop,
the GM briefing, or targeting — those already handle N enemies (verified:
`assembler.py:375-393`, `ruling.j2` combat-targeting rule, `combat.py:294`).

## Design overview

Two ways to seed a multi-enemy fight, both funnelled through one resolver
helper that filters for presence and combat-capability:

- **`Result.combatants`** — an explicit list on an encounter-rule result,
  for scripted / heterogeneous set-pieces ("the captain and two
  archers"). Only meaningful alongside `trigger_combat: true`.
- **`Entity.combat_group`** — a tag on NPC entities. Attacking (or
  aggroing) *any* member pulls in every present, living member of the
  same group. Ideal for homogeneous bands ("a band of identical
  goblins") and, crucially, it works on the **direct-attack** path that
  bypasses aggro/encounter rules entirely (`resolver.py:895-905`).

Both are expanded and filtered by a single function so the three
`enter_combat` call sites behave identically.

The `trigger_combat` no-op is closed by **locking the field (and
`combatants`) to encounter results** (load-time validation error if they
appear elsewhere) and fixing the docs, rather than spreading combat-entry
side effects into the generic Result-application layer.

### Combatant resolution helper (single source of truth)

New `mgmai/engine/combat.py::resolve_combat_enemies`:

```python
def resolve_combat_enemies(
    seed_ids: list[str],          # encounter source(s): [source_id] or [target_id]
    explicit: list[str] | None,   # Result.combatants (encounter path only)
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[str]:
    room_id = hard.player.location
    room_present = set(hard.room_contains.get(room_id, {}))
    follower_ids = set(get_following_npc_ids(hard, corpus))
    seed_set = set(seed_ids) | set(explicit or [])

    # 1. Expand combat_group membership for every seed/explicit id.
    #    Followers are allies: they are never pulled in via group
    #    expansion. A follower can only become a combatant by being a
    #    seed itself (i.e. the player attacked it directly).
    expanded: list[str] = []
    seen_groups: set[str] = set()
    for cid in list(seed_ids) + list(explicit or []):
        ent = corpus.entities.get(cid)
        grp = ent.combat_group if ent else None
        if grp and grp not in seen_groups:
            seen_groups.add(grp)
            for eid, e in corpus.entities.items():
                if e.combat_group == grp and (eid == cid or eid not in follower_ids):
                    expanded.append(eid)
        else:
            expanded.append(cid)

    # 2. Dedup (preserve order), then filter to eligible enemies.
    out: list[str] = []
    for cid in dict.fromkeys(expanded):
        ent = corpus.entities.get(cid)
        if ent is None or ent.combat is None:        # must be a stat-blocked entity
            continue
        # Presence: a seed is eligible if it is in the room or a follower
        # (you may attack a follower). Group-expanded members must be in
        # the current room; followers are excluded by the expansion step.
        if cid in seed_set:
            if cid not in room_present and cid not in follower_ids:
                continue
        else:
            if cid not in room_present:
                continue
        st = hard.entity_states.get(cid, {})
        if st.get("alive") is False or st.get("fled") is True:
            continue
        out.append(cid)
    return out
```

Properties this gives us:

- A **mechanic** source id (not an entity) is filtered out at the
  `ent is None` gate, so mechanic encounters draw enemies purely from
  `combatants`/`combat_group` — fixing the phantom-combatant bug.
- **Absent, dead, or fled** listed members are silently dropped, so
  authoring `[goblin_1, goblin_2, goblin_3]` degrades gracefully when one
  goblin is already dead or in another room.
- The **aggressor is auto-included** because it is always a seed.
- **Followers are not auto-pulled** into combat against the player. A
  follower is only a combatant if it is the directly-attacked seed. (See
  "Design decisions" below.)

If `resolve_combat_enemies` returns an empty list, the caller **does not
enter combat**: it logs a warning, leaves the encounter's narrative/state
changes intact, and — importantly — does *not* report the encounter as
having started combat (see B3 for the `EncounterOutcome.combat` /
move-block reconciliation).

---

## Design decisions (resolved)

- **Followers are allies, not auto-enemies.** `combat_group` expansion
  excludes following NPCs. The only way a follower enters combat is by
  being the directly-attacked seed. Rationale: a following NPC is
  conventionally an ally; auto-pulling it into a fight against the player
  would be surprising. (Note: `get_following_npc_ids` only returns NPCs
  that have a `dialogue` block — `utils.py:69` — so "follower" already
  carries that unstated precondition; the docs should state it.)
- **`combat_group` implies mutual hostility.** Authors must not place an
  allied follower in an enemy band. This is enforced structurally by the
  expansion-exclusion above (presence can't be checked statically because
  `following` is runtime state).
- **Empty post-filter set ⇒ no combat, and no "combat started" signal.**
  Every call site guards on a non-empty result and refrains from setting
  `combat_triggered`, emitting `combat.started`, or blocking movement.
- **Encounter state changes are applied *before* enemy resolution** on the
  engine path, so a firing result that mutates presence/alive (e.g.
  reviving or relocating a combatant via `set_entity_state`) is visible to
  the filter.
- **Hard error for scope violations.** `trigger_combat`/`combatants`
  outside encounter results is a load-time error (fail fast). No in-repo
  corpus relies on the (non-functional) field; the only in-repo use of
  `trigger_combat` is on an aggro encounter result
  (`adventures/bag-of-holding/corpus.json:179`).

---

## Implementation phases

### Phase A: Model changes (`mgmai/models/corpus.py`)

**A1. `Result.combatants`**

Add `combatants: Optional[List[str]] = None` (`corpus.py:168`). Leave
`has_any_effect` unchanged — `combatants` is inert without
`trigger_combat`, which already counts as an effect (`corpus.py:196`). Do
**not** add a validator on `Result` itself (it is shared by interactions,
reactions, and encounters; a field-level validator would wrongly reject
the legitimate encounter case and break existing unit tests that
construct `Result(trigger_combat=True)` directly — `test_resolver.py:803`,
`test_event_bus.py:1315`). Scope enforcement lives in cross-validation
(B4), not on the model.

**A2. `Entity.combat_group`**

Add `combat_group: Optional[str] = None` to `Entity` (`corpus.py:493`).
Extend the entity `@model_validator` (`corpus.py:533-548`, where `aggro`
and `combat` are already gated) so a non-`npc` entity carrying
`combat_group` raises, mirroring the `aggro`/`combat` restrictions.

### Phase B: Engine wiring

**B1. `combat.py::resolve_combat_enemies`** — new helper as specified
above (imports `get_following_npc_ids` from `mgmai/engine/utils.py`; no
circular-import risk — `utils` does not import `combat`).

**B2. Encounter result → combatants (`encounters.py`)**

In `_apply_encounter_rule` (`encounters.py:119-126`), add
`"combatants": firing_result.combatants if firing_result else None` to the
returned dict, and default it to `None` in `_empty_result`
(`encounters.py:57-65`). `firing_result` is already the local for both
the result-bearing and check-bearing branches (`encounters.py:95,108`),
mirroring the existing `trigger_combat` threading (`encounters.py:122`).

**B3. Route all three entry points through the helper**

- **`engine.py` (encounter outcome).** Restructure the encounter block
  (`engine.py:235-284`) so that:

  1. `encounter_changes` are applied **before** combat resolution (move
     the `_apply_and_merge(encounter_changes)` call ahead of the combat
     block; drop the later duplicate application at `engine.py:284`).
  2. Combat enemies are resolved and `enter_combat` is called only when
     non-empty.
  3. `EncounterOutcome.combat` reflects **actual combat entry**, not
     `trigger_combat`.

  ```python
  _apply_and_merge(encounter_changes)          # presence/alive mutations visible

  combat_started = False
  if enc_result["trigger_combat"]:
      enemies = resolve_combat_enemies(
          [encounter_source_id], enc_result.get("combatants"), hard, corpus)
      if enemies:
          combat_entry = enter_combat(enemies, hard, corpus)
          combat_started = True
          combat_triggered = True
          combat_log = combat_entry["combat_log"]
          if combat_entry.get("hard_changes"):
              _apply_and_merge(combat_entry["hard_changes"])
          if combat_entry.get("game_over"):
              hard.game_over = GameOverState(type="lose", trigger="player_death")
              game_over = GameOverResult(type="lose", trigger="player_death")
          if soft.dialogue_state.active_npc is not None:
              resolution.dialogue_exited = exit_dialogue(soft, corpus, hard)
      else:
          log.warning("trigger_combat produced no eligible combatants for %s",
                      encounter_source_id)

  encounter_outcome = EncounterOutcome(
      encounter_id=encounter_source_id,
      combat=combat_started,                   # actual entry, not trigger_combat
      narrative_brief=enc_result.get("narrative"),
      branch_taken=enc_result.get("branch_taken"),
  )
  ```

  Construct `encounter_outcome` after the combat block (it currently
  precedes it at `engine.py:253`). The room-transition block at
  `engine.py:332-340` keys off `encounter_outcome.combat`, so with
  `combat=combat_started` a `trigger_combat` that resolves to no enemies
  no longer strands the player in the old room — the move proceeds and
  `EngineResult.encounter_outcome.combat` is `False`.

- **`event_bus.py` (reaction-fired encounter, `_resolve_reaction_encounter`
  `event_bus.py:429-450`).** `enc_result`'s state changes are already
  applied before the combat block (`event_bus.py:417-422`), so only the
  guard is needed:

  ```python
  if enc_result["trigger_combat"]:
      enemies = resolve_combat_enemies(
          [source_id], enc_result.get("combatants"), hard, corpus)
      if enemies:
          combat_entry = enter_combat(enemies, hard, corpus)
          # ... existing hard_changes / game_over / combat_log / dialogue-exit
          #     / "combat.started" event handling, all inside this branch ...
      else:
          log.warning("trigger_combat produced no eligible combatants for %s",
                      source_id)
  ```

  Because the `combat.started` event and dialogue-exit are emitted inside
  the same branch, an empty result emits neither.

- **`resolver.py` (direct attack on a stat-blocked NPC, `resolver.py:884-905`).**
  Two changes:

  1. **Fix the dead-NPC guard.** The alive check at `resolver.py:885` is
     currently gated on `target_entity.aggro`, so a stat-blocked NPC
     *without* aggro that is already dead still reaches the attack branch.
     Broaden it to all NPCs:
     ```python
     if target_entity.type == "npc":
         entity_state = hard.entity_states.get(target_id, {})
         if entity_state.get("alive") is False:
             return ResolutionResult(success=False,
                 error=f"NPC '{target_id}' is dead")
     ```
  2. **Resolve enemies and guard on non-empty.**
     ```python
     if interaction_id == "attack" and target_entity.combat is not None:
         from mgmai.engine.combat import enter_combat, resolve_combat_enemies
         enemies = resolve_combat_enemies([target_id], None, hard, corpus)
         if not enemies:
             return ResolutionResult(success=False,
                 error=f"Cannot start combat with '{target_id}' "
                       f"(not present or not a valid combatant)",
                 room_after_id=room_id)
         entry = enter_combat(enemies, hard, corpus)
         return ResolutionResult(success=True, ...)
     ```
     In the normal case `target_id` is present (found via
     `_find_entity_in_room_followers`, `resolver.py:874`) and stat-blocked,
     so the result is non-empty and `combat_group` expansion pulls in the
     rest of the band. The guard is a safety net for the degenerate case
     rather than a reliance on "never empty".

**B4. Lock `trigger_combat`/`combatants` to encounter results**

Add `_validate_trigger_combat_scope()` to the load-time pipeline in
`state/manager.py` (call it in `load_all` and `_apply_char_sheet_data`,
alongside `validate_cross_references`). Mirror the per-carrier walker
structure already used by `_collect_corpus_flag_references`
(`manager.py:392-553`), recursing into `then_check` with carrier context.

Raise `ValueError` if any of the following hold:

- **Scope:** `trigger_combat` or `combatants` is set on a `Result`
  outside an encounter rule.
  - **Allowed carriers:** `entity.aggro[*].result` / `.success` /
    `.failure`; `mechanic.rules[*].result` / `.success` / `.failure`; and
    any `then_check` reachable from those.
  - **Forbidden carriers:** `interaction.result` / `.success` /
    `.failure` (entity, room, and dialogue-path `Resolvable`s);
    `on_examine[*].result` / `.success` / `.failure`; `reaction.effect.result`
    (entity, room, mechanic scopes); `using_results[*].result` / `.success`
    / `.failure` (traversal and take overrides); and any `then_check`
    reachable from those.
- **`combatants` requires `trigger_combat`:** a `Result` carrying
  `combatants` must also have `trigger_combat: true` (otherwise it is
  silently inert).
- **`combatants` referential integrity:** every id in a `combatants` list
  references a known entity.
- **`combat_group` membership:** every entity sharing a `combat_group`
  value is an `npc` with a `combat` block. (All members must be
  stat-blocked — not just ≥1 — so a group reliably denotes a fightable
  band. Members without a `combat` block would be silently dropped by the
  runtime filter; fail fast instead.)

Presence (in-room / follower / alive) cannot be checked statically — that
is the runtime filter's job.

### Phase C: Documentation

**C1. `schema/corpus.md`**

- Result field table (`corpus.md:276`): clarify `trigger_combat` is
  **only** honoured in encounter-rule results; add the `combatants` row
  (list of entity ids; requires `trigger_combat`; filtered for presence).
- Aggro / encounter-rule section (around `corpus.md:1338-1355`): document
  `combatants` and the presence/alive/combat-capable filtering, and that
  an empty post-filter set means no combat.
- Entity field table / NPC section (`corpus.md:1204-1210`): add
  `combat_group`, npc-only, with the "attack one → the band joins"
  semantics, the direct-attack note, and the statement that followers are
  allies (not auto-pulled) and that "follower" requires a `dialogue` block.
- State the phantom-fix: a mechanic encounter with `trigger_combat` must
  supply `combatants` (or the members must share a `combat_group`),
  because the mechanic id is not itself a combatant.

**C2. `doc/combat.md`**

- "Entering Combat" (`combat.md:162-182`): document that the enemy set is
  the filtered union of the source, its `combat_group`, and any
  `combatants` list; enemies must be present and living; an empty set
  means no combat is entered.
- Fix the framing at `combat.md:166-172` to match the new resolution
  (note that a direct attack on a stat-blocked NPC enters combat
  immediately via the helper, pulling its band).

**C3. `schema/scenario-generation.md`**

- Fix the overclaim at `scenario-generation.md:1489-1490` ("When a firing
  `Result` has `trigger_combat: true`, the engine starts multi-round
  combat") → scope it to encounter-rule results.
- Document the "band of goblins" idiom (`combat_group`) and the scripted
  idiom (`combatants`) in Step 4 (Build Mechanics) and the NPC/aggro
  guidance. Note that listing one band member in `combatants` expands the
  whole present band — to select a subset, omit `combat_group`.
- Validation checklist additions: `trigger_combat`/`combatants` only in
  encounter results; `combatants` requires `trigger_combat`; `combatants`
  ids reference stat-blocked entities; `combat_group` members are all
  stat-blocked npcs.

### Phase D: Tests

**D1. `tests/test_combat.py` — `resolve_combat_enemies`**

- Present + alive + stat-blocked members are kept; absent / dead / fled /
  non-combat / unknown ids are dropped.
- `combat_group` expansion from a single seed (attack `goblin_1` →
  `{goblin_1, goblin_2, goblin_3}` when all present; a fourth goblin in
  another room is excluded).
- **Followers are not auto-pulled:** a following NPC sharing a group with
  an attacked enemy is excluded; but attacking a follower seed directly
  still starts combat with that follower (plus any in-room group members).
- Empty result → caller enters no combat (assert `hard.combat is None`
  and a warning is logged).

**D2. `tests/test_encounters.py` / `tests/test_event_bus.py` / `tests/test_resolver.py`**

- Encounter rule with explicit `combatants` → multi-enemy `CombatState`.
- Mechanic encounter with `trigger_combat` + `combatants` (previously
  broken) → correct combatants, no phantom mechanic id.
- Mechanic encounter with `trigger_combat` and **no** combatants/group →
  no combat, warning, encounter narrative/state still applied.
- **`engine.py` empty-reconciliation:** a `trigger_combat` encounter that
  resolves to no enemies sets `encounter_outcome.combat=False`,
  `combat_triggered=False`, and does **not** block a pending room
  transition (`action_changes.player_location` survives).
- **`engine.py` encounter-change timing:** an encounter result that
  `set_entity_state` revives an otherwise-dead listed combatant before
  `trigger_combat` includes that combatant (state change applied before
  enemy resolution).
- **Direct-attack guard:** attacking a dead stat-blocked NPC with no
  aggro returns an error (not a degenerate player-only combat); attacking
  a `combat_group` member pulls the whole present band (via
  `resolver.py:895`).
- **`event_bus.py` empty:** a reaction-fired `trigger_combat` that
  resolves to no enemies emits no `combat.started` event and leaves
  `hard.combat` unset.

**D3. Validation (`tests/test_corpus.py` / `tests/test_state_manager.py`)**

- `combat_group` on a non-npc entity → model error.
- `trigger_combat` / `combatants` on an interaction, reaction,
  `on_examine` (`.result`, `.success`, `.failure`), or `using_results`
  result → load-time `ValueError` from `_validate_trigger_combat_scope`.
- `combatants` without `trigger_combat` on an encounter result → error.
- `combatants` referencing an unknown / non-stat-blocked entity → error.
- A `combat_group` where any member lacks a `combat` block (or is not an
  npc) → error.
- The existing engine-level unit tests that call `_apply_result` /
  reaction dispatch with `Result(trigger_combat=True)` directly
  (`test_resolver.py:803-866`, `test_event_bus.py:1315-1377`) still pass
  (they bypass corpus validation); update their docstrings to reference
  the new "encounter-only" rule.

**D4. Briefing coverage (`tests/` for `context/assembler.py`)**

- A multi-enemy `CombatState` yields one briefing entry per living enemy
  with correct name/hp (guards `assembler.py:375-393`).

### Phase E: Example content (optional, illustrative)

Add a small `combat_group` band and/or a `combatants` set-piece to
`tests/fixtures/corpus.json` (and optionally `bag-of-holding`) so the new
idioms have a worked reference and an integration surface.

---

## Files touched

| File | Phase | Nature of change |
|------|-------|------------------|
| `mgmai/models/corpus.py` | A1-A2 | Add `Result.combatants`; add `Entity.combat_group` + npc-only guard |
| `mgmai/engine/combat.py` | B1 | New `resolve_combat_enemies` helper |
| `mgmai/engine/encounters.py` | B2 | Return `combatants` from encounter results |
| `mgmai/engine/engine.py` | B3 | Apply encounter changes before enemy resolution; resolve enemy set; guard combat entry on non-empty; `EncounterOutcome.combat` = actual entry |
| `mgmai/engine/event_bus.py` | B3 | Same guard for reaction-fired encounters |
| `mgmai/engine/resolver.py` | B3 | Broaden dead-NPC guard to all npcs; direct-attack path uses the helper (`combat_group` expansion) + empty-guard |
| `mgmai/state/manager.py` | B4 | `_validate_trigger_combat_scope` (scope, `combatants⇒trigger_combat`, referential, `combat_group` membership) |
| `schema/corpus.md` | C1 | Document `combatants`, `combat_group`, encounter-only `trigger_combat`, mechanic-source rule, follower semantics |
| `doc/combat.md` | C2 | Multi-combatant entry + filtering + empty-set behaviour |
| `schema/scenario-generation.md` | C3 | Fix overclaim; document both idioms; checklist items |
| `tests/test_combat.py` | D1/D4 | Helper + briefing tests |
| `tests/test_encounters.py` | D2 | `combatants` threading, mechanic-source cases, empty-reconciliation, change-timing |
| `tests/test_event_bus.py` | D2/D3 | Reaction-fired multi-enemy; empty → no `combat.started`; validation docstrings |
| `tests/test_resolver.py` | D2/D3 | Direct-attack band; dead-NPC guard; validation docstrings |
| `tests/test_corpus.py` | D3 | Model + scope validation errors |
| `tests/test_state_manager.py` | D3 | Load-time scope/cross-validation |
| `tests/fixtures/corpus.json` | E | Example band / set-piece (optional) |
| `plan.md` | — | This document |

## Open questions / deferred

- **`"self"` in a `combatants` list.** For entity-scoped encounter
  results one could allow `"self"` to mean the owning entity, consistent
  with reaction `self` semantics. Deferred — not needed for the band or
  set-piece idioms, and encounters don't currently carry an owner id
  through to result resolution.
- **Heterogeneous bands via a single tag.** `combat_group` is a flat
  string; multi-group membership (a goblin in both "camp" and "raiders")
  is out of scope. A list-valued `combat_group` is a possible future
  extension.
- **Per-encounter `combat_group` opt-out.** Today `combat_group` expands
  on all three call sites uniformly. If an author later wants a single
  member's aggro/encounter to fight alone, an opt-out flag on the
  encounter result could be added.
