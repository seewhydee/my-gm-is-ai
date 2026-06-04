# Phase 4 Implementation Report

## Summary

Phase 4 implemented the deterministic game engine — the core of the MGMAI system. Five engine modules and five test files were created, totaling ~1,500 lines of engine code and ~950 lines of tests (109 test cases). All 476 tests in the project pass.

## Files Created

| File | Lines | Description |
|------|-------|-------------|
| `mgmai/engine/encounters.py` | 139 | Encounter/behavior rule evaluation, flee effects |
| `mgmai/engine/dialogue.py` | 158 | Dialogue state lifecycle management |
| `mgmai/engine/resolver.py` | 578 | Per-action-type validation and resolution (7 types) |
| `mgmai/engine/post_validate.py` | 219 | Step 4.5: knowledge_tag + attitude change validation |
| `mgmai/engine/engine.py` | 361 | Main orchestrator: resolve() entry point |
| `tests/test_encounters.py` | 145 | 13 tests for encounter resolution |
| `tests/test_dialogue.py` | 195 | 20 tests for dialogue lifecycle |
| `tests/test_resolver.py` | 437 | 40 tests for action resolvers |
| `tests/test_post_validate.py` | 169 | 16 tests for post-validation |
| `tests/test_engine.py` | 203 | 20 tests for engine orchestrator |

## Files Modified

| File | Change |
|------|--------|
| `mgmai/engine/__init__.py` | Added exports for all new engine modules |
| `tests/conftest.py` | Added `state_manager` fixture (function-scoped, deep-copied) |

## Implementation Notes

### What was implemented per the phase-4 plan

All five files specified in `phase-4-plan.md` were implemented:

1. **`engine/encounters.py`** — `resolve_encounter()`, `should_trigger_behavior()`, `apply_flee_effects()`
   - Evaluates encounter rules top-to-bottom; first matching condition wins
   - Handles death, flee, and roll outcomes
   - Roll outcomes use `random.random()` with success/failure branch resolution
   - Flee effects apply flags and entity state changes

2. **`engine/dialogue.py`** — Complete lifecycle management
   - `enter_dialogue()`, `append_player_turn()`, `append_npc_response()` — conversation log management (capped at 10 entries)
   - `increment_stall()` — tracks non-talk actions during dialogue; auto-exit at 3
   - `exit_dialogue()` — archives conversation summary, applies `on_dialogue_exit` effects, clears state
   - `check_room_change_exit()` — exits dialogue when player moves away from active NPC
   - `track_topic()` — accumulates discussed topics

3. **`engine/resolver.py`** — Seven action resolvers plus `resolve_action()` dispatcher
   - `resolve_wait` / `resolve_ooc` — trivial always-success
   - `resolve_examine` — validates target (entity, room, soft item), supports `using` and `rigorous` fields
   - `resolve_move` — validates exit existence, evaluates conditions, applies `on_traverse` effects (flags, narrative, encounter triggers, skip_if)
   - `resolve_talk` — validates NPC presence/alive, manages dialogue enter/continue/switch/end
   - `resolve_transfer` — validates give/take items against inventory and available pools
   - `resolve_interact` — finds interaction on entity/room, validates conditions, parameter signatures, resolves checks/rolls and direct results; handles generic `take` and `attack` interactions
   - All resolvers return `ResolutionResult` with proposed `HardStateChanges` — they do not mutate state directly (except dialogue state via `dialogue.py`)

4. **`engine/post_validate.py`** — Step 4.5 validation
   - `post_validate_knowledge_tags()` — validates will_reveal topics, checks conditions, applies set_flag/set_entity_state side effects, records in npc_revelations (deduplicated)
   - `post_validate_attitude_changes()` — validates old_value match, step_per_turn limits, min/max bounds, alive check, non-empty reason. Handles `step_per_turn: 0` correctly.
   - `apply_post_validation()` — convenience wrapper returning applied/rejected deltas

5. **`engine/engine.py`** — Main orchestrator
   - `resolve()` — the full engine pipeline: validate → apply hard changes → validate soft patches → resolve encounters → fire on_enter events → manage dialogue → check game-over → increment turn → build turn history → construct EngineResult with room_after, will_reveal_readiness, npc_attitude_limits
   - Handles OOC discussion as no-op
   - Handles chain depth limit (MAX_CHAIN_LENGTH = 10)
   - Builds `room_after` (BriefingRoom) with visible entities, available exits (conditions-filtered), interactions, room notes
   - Builds `will_reveal_readiness` for all NPCs in room
   - Builds `npc_attitude_limits` with current values from soft state (falling back to corpus initial values)

### Encounter resolution during interactions

The engine correctly routes `attack` interactions on NPCs with behavior blocks to encounter resolution. Both `resolve_move` (via `on_traverse.trigger_encounter`) and `resolve_interact` (via `attack` interaction) can trigger encounters.

## Issues and Ambiguities Encountered

### 1. Soft inventory items in transfer action (bug)

**Severity:** Medium  
**Location:** `engine/resolver.py:297-298` in `resolve_transfer`

When transferring soft items (`given_items` that are in `soft.soft_inventory`), the resolver adds them to `HardStateChanges.inventory_removed`. However, `StateManager.apply_hard_changes()` only removes items from `hard.player.inventory` (the hard inventory). Soft items in the soft inventory are never actually removed. The item appears in the EngineResult as "removed" but stays in `soft.soft_inventory`.

**Recommended fix:** Either (a) have the resolver produce `SoftStatePatch` proposals for soft inventory changes alongside `HardStateChanges`, or (b) add a `soft_inventory_removed` field to `HardStateChanges` and handle it in `apply_hard_changes`. Approach (a) is more aligned with the architecture since soft-state changes are meant to go through the patch mechanism.

### 2. `Result.reveals` field surfacing mechanism

**Severity:** Low  
**Location:** `engine/resolver.py:_apply_result()`  
**Status:** Resolved

The `Result.reveals` field (from corpus Interactions) is surfaced by appending it to `triggered_narration`. LLM Call 2 will receive it alongside other triggered narrations and can weave it into prose. This is a pragmatic solution that avoids expanding the EngineResult schema. However, `reveals` text is intended as "hint text for the player's future reference" (per schema), and including it as triggered narration means the LLM will treat it as something to narrate immediately rather than as a hint to store.

### 3. Hidden exit accessibility logic

**Severity:** Low  
**Location:** `engine/resolver.py:resolve_move()`  
**Status:** Resolved (behavior changed)

The original implementation rejected all hidden exits immediately, before condition evaluation. In the sample adventure, `exit_enter_secret_flap` is `hidden: true` with condition `flag:handkerchief_moved == true`. The condition serves double duty: it both gates access AND acts as the reveal mechanism. The engine now evaluates exit conditions even for hidden exits — if conditions are met, the exit is accessible. This is appropriate for the current phase where hidden exits use conditions as their reveal mechanism.

**Future consideration:** A more sophisticated hidden exit system might separate "visibility" (is the exit shown in the GMBriefing?) from "accessibility" (can the player traverse it?). The Context Assembler (Phase 5) will need to handle which hidden exits to surface in the briefing.

### 4. Parameter signature "entity" wildcard interpretation

**Severity:** Low  
**Location:** `engine/resolver.py:resolve_interact()`  
**Status:** Resolved

The `parameter_signature` in interactions can specify `target: ["entity"]` or `using: ["entity"]`. The original implementation compared entity types literally — "feature" ≠ "entity". The fix treats `"entity"` as a wildcard matching any entity type (`player`, `feature`, `npc`, `trap`, `item`). This is documented in the schema (`schema/corpus.md`) where "entity" in parameter signatures means "any entity regardless of type."

### 5. Non-repeatable check tracking not implemented

**Severity:** Low  
**Location:** `engine/resolver.py:_resolve_interaction_check()`  
**Plan reference:** phase-4-plan.md §"resolve_interact" mentions tracking non-repeatable checks and rejecting retries

The `Check` model has a `repeatable: bool` field. Checks with `repeatable: false` should reject retry attempts. The current resolver does not track which checks have been attempted and always allows retries. This is minimal impact for the sample adventure (which has `repeatable: true` on its only check), but should be implemented before Phase 6 to prevent LLM Call 1 from exploiting repeatable interactions.

**Recommended fix:** Add a `checks_attempted` set to `SoftGameState` (or track per-interaction in entity/room state) and check it before resolving a non-repeatable check.

### 6. Room visited flag always overwritten on move

**Severity:** Minor  
**Location:** `engine/resolver.py:resolve_move()`

The resolver always sets `visited: true` on the target room when moving, even if the target room already has existing room state values. This works correctly after the dict merge order fix (`{**existing, "visited": True}`), but it unconditionally sets visited without checking if the room has already been visited. This is harmless since setting `visited: True` when it's already true is idempotent.

### 7. Dialogue exit on room change: duplicate handling

**Severity:** Low  
**Location:** `engine/engine.py:resolve()`

The engine checks for room-change dialogue exit in two places: (a) in the `on_enter` processing block via `check_room_change_exit()`, and (b) in a separate block afterward that checks `hard_changes.player_location != old_room`. Both do essentially the same thing. The second check is redundant when the first succeeds, and acts as a safety net. However, if both fire, `exit_dialogue` can be called twice for the same conversation, producing two archive notes. The `exit_dialogue` function is idempotent in terms of state clearing (it sets `active_npc = None`), but will archive twice.

**Recommended fix:** Remove the redundant check and rely solely on the one in `check_room_change_exit`.

### 8. Encounter resolution occurs after hard state changes are applied

**Severity:** Design clarification  
**Location:** `engine/engine.py:resolve()`  
**Plan reference:** phase-4-plan.md §Step 4 ordering

Per the phase-4 plan, encounters should fire *before* hard-state changes are committed (so a death outcome doesn't produce contradictory state). However, the current implementation:
1. Applies hard changes (via `state_manager.apply_hard_changes()`) — this may move the player to a new room
2. Then resolves encounters — which may set `game_over` (death) while player has already moved

This ordering issue is partly mitigated by the game-over check after encounters: if an encounter produces a death outcome, the engine sets `hard.game_over` and returns it. But the player's location has already been updated.

**Recommended fix:** Reorder to resolve encounters before applying hard-state changes. The encounter outcome should conditionally override the proposed changes.

## Design Decisions Made

1. **`reveals` field → `triggered_narration`**: The `Result.reveals` hint text is appended to `triggered_narration` so LLM Call 2 can weave it into prose.

2. **Hidden exits accessible when conditions met**: Hidden exits are accessible if their conditions evaluate true. Conditions serve as the reveal mechanism.

3. **"entity" in parameter_signature is a wildcard**: Matches any entity type (player, feature, npc, trap, item).

4. **Transfer item availability**: Items available from a room = item-type entities present + room's soft_items. Items available from an entity = if the entity is an item, itself + its soft_items.

5. **Step 4.5 post-validation returns a delta**: `apply_post_validation()` returns a dict of applied/rejected items to merge into EngineResult, rather than producing a new EngineResult. This keeps post-validation composable.

## Test Coverage

| Module | Tests | Key scenarios covered |
|--------|-------|----------------------|
| encounters | 13 | Death, flee, roll success/failure, no-match, first-match-wins, behavior triggers by action/exit, flee effects |
| dialogue | 20 | Enter, append player/npc, stall increment/limit, exit (normal, on_dialogue_exit effects), room change exit, topic tracking, dedup |
| resolver | 40 | All 7 action types: valid/invalid, conditions, soft items, hidden exits, item transfer, NPC presence/alive, generic take/attack, interact checks and results, parameter validation |
| post_validate | 16 | Valid/invalid knowledge tags, conditions not met, unknown topics/NPCs, dead NPCs, duplicate prevention, attitude change validation (step, bounds, alive, reason, step_per_turn=0) |
| engine | 20 | Full flow per action type, OOC no-op, on_enter events, hard state changes, turn history, soft patch validation/rejection, game-over detection, dialogue integration, chain handling, room_after/will_reveal/npc_attitude_limits construction |

## Next Steps (Phase 5: Context Assembler)

The engine is ready for integration. Phase 5 should implement `context/assembler.py` which builds `GMBriefing` from corpus + state. The engine already produces `room_after` (BriefingRoom), `will_reveal_readiness`, and `npc_attitude_limits` — the Context Assembler will use these as building blocks for the full briefing.
