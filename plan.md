# Plan: Add `set_player_location` to the Result schema

## Motivation

The `Result` object (schema/corpus.md:204-234) describes the consequences of
an action: narrative, item changes, flag changes, stat adjustments, damage,
follow-up checks, etc.  It is used in success/failure branches of
interactions, traversal checks, dialogue paths, on-examine events, and
reactions.

The canonical "jump across a pit" example (schema/corpus.md:275-292) has a
STR traversal check to jump, and on failure a DEX then_check to grab the
ledge.  If the DEX check also fails, the player falls into the pit — but the
schema has no way to express "move the player to the pit room".  The example
lamely sets `"dropped_in_pit": true` as a flag, with no follow-on mechanism
to actually relocate the player.

The engine already has a `set_player_location` mutation (hard-state.md:241,
`HardStateChanges.player_location`) and `StateManager.apply_hard_changes()`
already applies it (manager.py:498-499).  The gap is that no `Result` field
wires into it — only action resolvers (e.g. `resolve_move`) can set it.

Adding `set_player_location` to `Result` plugs this gap everywhere Results
are used: interaction outcomes, check success/failure branches, follow-up
checks, and reaction effects.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Add `set_player_location: Optional[str] = None` to the `Result` model. | Symmetrical with `set_entity_state` / `set_room_state`.  One new field, zero new concepts. |
| D2 | `_apply_result()` writes `changes.player_location` from the field. | Same pattern as `set_flag` → `changes.flags_set`, etc. |
| D3 | Validate the target room exists in the corpus at `apply_hard_changes()` time. | Matches the existing `set_room_state` validation pattern.  Catch typos before state corruption. |
| D4 | Change `engine.py` line 424 to use `hard.player.location` directly instead of `resolution.room_after_id or hard.player.location`. | After all changes are applied, `hard.player.location` is the ground truth.  The resolver's `room_after_id` hint was always set to match — the `or` was defensive and is now counterproductive: it suppresses `room.exited`/`room.entered` events when a non-move Result relocates the player.  The encounter block (lines 358-366) already nullifies the location change before apply when a move is blocked, so the hard state stays correct. |
| D5 | No special handling for "move to same room" — it's a no-op. | The engine already checks `new_room != old_room` (line 427).  If `set_player_location` matches the current room, no transition fires — zero cost. |
| D6 | If multiple Results in one turn set different locations, the last write wins. | `HardStateChanges.merge()` already handles this: `if other.player_location is not None: self.player_location = other.player_location`.  Immediate-reaction results override action results; deferred reactions fire later and would override.  This is consistent with flag-overwrite semantics. |

## End-state design

### Model (`mgmai/models/corpus.py`)

```python
class Result(BaseModel):
    narrative: Optional[str] = None
    add_item: Optional[List[str]] = None
    remove_item: Optional[List[str]] = None
    set_flag: Optional[Dict[str, bool]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    set_room_state: Optional[Dict[str, Dict[str, Any]]] = None
    adjust_attitude: Optional[Dict[str, int]] = None
    reveals: Optional[str] = None
    then_check: Optional[CheckResolution] = None
    player_damage: Optional[str] = None
    set_player_location: Optional[str] = None          # NEW

    def has_any_effect(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in (
                "narrative", "add_item", "remove_item",
                "set_flag", "alter_stat", "set_entity_state", "set_room_state",
                "adjust_attitude", "reveals", "then_check",
                "player_damage", "set_player_location",    # NEW
            )
        )
```

### JSON example — the canonical pit-jump, improved

```json
{
  "traversal_check": {
    "check": { "type": "stat_check", "stat": "STR", "target": 13, "repeatable": true },
    "failure": {
      "narrative": "You leap but fall short.",
      "then_check": {
        "check": { "type": "stat_check", "stat": "DEX", "target": 8, "repeatable": true },
        "success": {
          "narrative": "You grab the ledge in time."
        },
        "failure": {
          "narrative": "You drop into the pit.",
          "set_player_location": "pit_bottom",
          "player_damage": "2d6"
        }
      }
    }
  }
}
```

### Engine flow

**Before (pit jump, DEX save fails):**
```
Result { narrative: "You drop into the pit", set_flag: {"dropped_in_pit": true} }
  → _apply_result() → changes.flags_set["dropped_in_pit"] = true
  → apply_hard_changes() → hard.flags["dropped_in_pit"] = true
  → player stays in current room.  No room transition.
```

**After:**
```
Result { narrative: "You drop into the pit", set_player_location: "pit_bottom", player_damage: "2d6" }
  → _apply_result() → changes.player_location = "pit_bottom", changes.player_hp_delta -= 2d6
  → apply_hard_changes() → hard.player.location = "pit_bottom", hp reduced
  → engine.py:424 → new_room = hard.player.location = "pit_bottom" ≠ old_room
  → engine.py:427-455 → room.exited + room.entered events fire
```

## File-change inventory

### `mgmai/models/corpus.py`
- `Result` class (L117-139): add field `set_player_location: Optional[str] = None` between `adjust_attitude` and `reveals` (or after `player_damage` — either position is fine; after `set_room_state` is semantically clearest).
- `has_any_effect()` (L130-139): add `"set_player_location"` to the attribute tuple.

### `mgmai/engine/resolver.py`
- `_apply_result()` (L1215-1302): add new block immediately after the `set_room_state` block:
  ```python
  if result.set_player_location:
      changes.player_location = result.set_player_location
  ```
  Placed after `set_room_state` (L1262-1264) and before `adjust_attitude` (L1265) to group all location/state mutations together.

### `mgmai/state/manager.py`
- `apply_hard_changes()` (L456-548): add room-existence validation for `player_location` in the pre-validation block (L466-493), matching the existing pattern for `room_state_changes`.  New block after the room_state_changes loop (L468-478):
  ```python
  if changes.player_location is not None:
      if corpus is None or changes.player_location not in corpus.rooms:
          errors.append(f"No matching room for player_location: {changes.player_location}")
  ```

### `mgmai/engine/engine.py`
- Line 424: change
  ```python
  new_room = resolution.room_after_id or hard.player.location
  ```
  to
  ```python
  new_room = hard.player.location
  ```
  Rationale: after `_apply_and_merge(action_changes)` at line 367, the hard state is the ground truth.  The resolver's `room_after_id` hint was always set to match the hard state's eventual value; dropping the `or` is a no-op for existing code paths and enables Result-driven location changes to trigger `room.exited`/`room.entered` events.  The encounter block at lines 358-366 handles the one case where they diverge (move blocked by combat) by nullifying `action_changes.player_location` *before* apply, so `hard.player.location` remains correct.

### `schema/corpus.md`
- L204-217: add `"set_player_location": "<room_id>"` to the Result JSON shape example.
- L222-234: add row to the field table:
  ```
  | `set_player_location` | string   | Room ID to relocate the player to   |
  ```
- L287-292: rewrite the pit-jump failure example to use `set_player_location` instead of the lame flag, and add `player_damage` for falling damage:
  ```json
  "failure": {
    "narrative": "You drop into the pit.",
    "set_player_location": "pit_bottom",
    "player_damage": "2d6"
  }
  ```

### `schema/hard-state.md`
- L241: the `set_player_location` row in the engine write operations table already exists — no change needed.  Optionally add a brief note that it is now also exposed as a Result field, but not required.

## Tests

### `tests/test_corpus.py` — model validation

**Class**: Existing `TestResult` (if one exists) or new test functions.

1. **`test_result_set_player_location`** — `Result(set_player_location="bag_floor")` constructs and serializes round-trip correctly.
2. **`test_result_has_any_effect_with_location`** — `Result(set_player_location="bag_floor").has_any_effect()` returns `True`.
3. **`test_result_has_any_effect_without_location`** — `Result().has_any_effect()` returns `False` (no regression on empty results).

### `tests/test_resolver.py` — `_apply_result()`

**Class**: `TestApplyResult` (L710-753).

4. **`test_set_player_location_applied`** — `Result(set_player_location="bag_floor")` → `_apply_result()` → `changes.player_location == "bag_floor"`.  Mirror of existing `test_adjust_attitude_applies_delta`.

### `tests/test_state_manager.py` — `apply_hard_changes()`

**Class**: `TestApplyHardChanges` (L220-343).

5. **`test_player_location_unknown_room_raises`** — `HardStateChanges(player_location="void")` → `apply_hard_changes()` raises `ValueError` matching `"No matching room for player_location:"`.  This is *new* validation that didn't exist before — currently `player_location` is accepted blindly.
6. **`test_player_location_apply_from_dict`** — `apply_hard_changes({"player_location": "bag_floor"})` → `hard.player.location == "bag_floor"` (existing test already covers this — verify it still passes).

### `tests/test_engine.py` — full pipeline

7. **`test_interaction_with_set_player_location_moves_player`** — Integration test:
   - Build a minimal corpus: room A (start), room B, no exits.  Add an interaction in room A whose `success` Result includes `set_player_location: "room_b"`.
   - Resolve the `interact` action targeting that interaction.
   - Assert `hard_state.player.location == "room_b"`.
   - Assert the `EngineResult` reflects the new location.
8. **`test_move_encounter_block_still_works`** — Non-regression: verify the existing pattern where an encounter blocks a move action still correctly keeps the player in the old room.  (Should already be covered by existing traversal encounter tests — run them to confirm no breakage from the engine.py line 424 change.)

## What does NOT change
- `HardStateChanges.player_location` — already exists, already handled by `merge()` and `apply_hard_changes()`.
- `ResolutionResult.room_after_id` — kept but unused in engine.py line 424 after the change.  Still set by resolvers for informational purposes; could be removed later if unused.
- `resolve_move()` — unchanged; it already sets both `changes.player_location` and `result.room_after_id`.
- The encounter block at engine.py:358-366 — unchanged; it nullifies `action_changes.player_location` before apply, which still works.
- No changes to `ResolveInteraction`, `resolve_talk`, `resolve_equip`, `resolve_unequip`, `resolve_surface`, or any other resolver — `_apply_result()` handles `set_player_location` uniformly wherever a `Result` is consumed.

## Edge cases

| Scenario | Behavior |
|---|---|
| `set_player_location` is the current room | No-op: engine.py:427 `new_room != old_room` is False, no transition |
| `set_player_location` points to a non-existent room | `ValueError` from `apply_hard_changes()` validation |
| Multiple Results in one turn set different locations | Last write wins via `HardStateChanges.merge()` |
| A reaction relocates the player mid-turn | `room.exited` fires for the old room, `room.entered` for the new room (immediate phase), deferred reactions fire afterward. This is the same sequence as a normal `move` action. |
| `set_player_location` + `then_check` in same Result | `_apply_result_with_check` (resolver.py:1305) applies the parent Result's effects first (including the location change), then resolves `then_check` in the same room context (which is now the new room).  The follow-up check's own success/failure Results can relocate again if needed. |

## Verification

Run from the repo root:

```
pytest
```

Specific checks:
- `tests/test_corpus.py` — `Result` model accepts new field
- `tests/test_resolver.py::TestApplyResult` — `_apply_result` writes to `changes.player_location`
- `tests/test_state_manager.py::TestApplyHardChanges` — validation and application
- `tests/test_engine.py` — full-pipeline integration test + non-regression on move-encounter block
- Existing traversal and interaction tests — no regressions

## Task ordering

1. **Model** — `mgmai/models/corpus.py`: add field to `Result`, update `has_any_effect()`.
2. **Engine application** — `mgmai/engine/resolver.py`: add `set_player_location` block to `_apply_result()`.
3. **Validation** — `mgmai/state/manager.py`: add room-existence check for `player_location`.
4. **Engine transition** — `mgmai/engine/engine.py`: change line 424 to use `hard.player.location`.
5. **Schema docs** — `schema/corpus.md`: update Result table and pit-jump example.
6. **Tests** — write new tests per the inventory above.
7. `pytest` green.
