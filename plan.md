# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Combat phase**: the attack interaction will be revised to support iterative rounds, HP tracking, damage rolls, and opposed checks. The current flag-based branching is a phase-1 placeholder.
- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.
- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

## Custom Player Character Sheets

### Goal

Allow players to supply a custom character sheet JSON file when starting a new adventure, overriding the default values in `hard-state.json`. The custom sheet can only be specified at new-game time, not when loading a save. If omitted, behaviour is unchanged.

### Design constraints

1. **New-game only**: The `--char-sheet` flag is mutually exclusive with `--load`. Passing both is an error.
2. **Backward-compatible default**: No custom sheet — use defaults from `hard-state.json.player.stats`, as now.
3. **Generic player-state override**: The mechanism applies any known `PlayerState` field (currently `stats`, `location`, `inventory`), and is open to future fields (skills, HP, resources, etc.) without architectural changes.
4. **Validation**: Custom sheet values must pass the same cross-references that the defaults do — every stat key must exist in `corpus.stats.definitions`, and `location`/`inventory` values must be valid.

### Schema: custom char sheet JSON

A simple JSON file:

```json
{
  "system": "d20",
  "player": {
    "stats": {
      "STR": 15,
      "DEX": 14,
      "CON": 13,
      "INT": 10,
      "WIS": 8,
      "CHA": 12
    }
  }
}
```

The top-level `"system"` field declares the RPG system the sheet assumes and must match `corpus.stats.system` when the adventure has a stats block.

The top-level key `"player"` mirrors the structure of `HardGameState.player`. For future fields, add more keys under `player` — e.g. `"hit_points": 30`, `"level": 1`, `"skills": {...}`. Known `PlayerState` fields are replaced outright; unknown fields are ignored for forward compatibility.

### Files to change

#### 1. `mgmai/cli.py` — `main()`

- Add `--char-sheet` CLI argument (`argparse`): path to a JSON char sheet file.
- In the `--load` branch, reject `--char-sheet` with an error message.
- After `state_manager.load_all()` on the new-game path, apply the custom sheet if provided.
- Pass the resolved char-sheet data through to `StateManager` — either as a method call or as a field on `StateManager`.

**Detail:** The new-game flow in `main()` currently:

```python
state_manager.load_all(adventure_path)
```

Change to:

```python
state_manager.load_all(adventure_path)
if args.char_sheet:
    state_manager.apply_char_sheet(args.char_sheet)
```

#### 2. `mgmai/state/manager.py` — `StateManager`

Add `apply_char_sheet(path: str | Path) -> None` method:

1. Load the JSON file.
2. Validate it contains `"system"` (when the adventure has a stats block) and a `"player"` object.
3. If `corpus.stats` is `None` but the sheet contains `player.stats` or a `system`, raise an error (adventure has no stat system).
4. If `corpus.stats` is present, validate the sheet's `system` against `corpus.stats.system` and each stat key in the sheet against `corpus.stats.definitions`.
5. Merge known `PlayerState` fields from `sheet["player"]` into `self.hard_state.player` (full replacement for each field).
6. Call `_validate_cross_references()` and `_validate_player_stats()` again to confirm consistency after the merge.

**Validation rules (future-proofing):**

- The sheet must declare `"system"` when the adventure has a stats block, and it must match `corpus.stats.system`.
- Any key in `sheet["player"]` that corresponds to a known field on `PlayerState` is merged.
- Unknown top-level keys under `"player"` are silently ignored (allows forward-compatible sheets).
- For known keys that are dicts or lists (like `stats` and `inventory`), the merge is a full replacement, not a per-key patch — the sheet must supply all values for that field.
- Validation errors produce user-friendly messages (not stack traces): missing `system`, system mismatch, unknown stat keys, invalid `location`/`inventory` references, and type errors.

#### 3. `mgmai/cli.py` — error messages

Add user-facing error handling:

- `--char-sheet` file not found → `display.render_error("Character sheet file not found: ...")`
- `--char-sheet` + `--load` → `display.render_error("Cannot specify both --char-sheet and --load")`
- Invalid sheet JSON / missing keys → `display.render_error` with description

### Data flow: custom stats through the system

```
CLI --char-sheet flag
  → StateManager.apply_char_sheet()
    → merges into hard_state.player.stats
      → subsequent GMBriefing includes custom stats via _build_player_stats()
      → engine resolves stat_check using custom values
      → display shows custom values in character sheet panel
      → save files include custom values (no special handling needed)
      → load_save() restores custom values from save (no special handling)
```

No changes needed to the briefing model, engine resolver, stat checks module, conditions evaluator, or display — they all read `hard_state.player.stats` dynamically.

### Future-proofing pattern

The generic approach:

```python
def apply_char_sheet(self, sheet: dict) -> None:
    player_overrides = sheet.get("player", {})
    for field, value in player_overrides.items():
        if field not in PlayerState.model_fields:
            continue  # forward-compat: skip unknown fields
        setattr(self.hard_state.player, field, value)
```

This means adding a new field to the `PlayerState` Pydantic model automatically makes it overridable via the char sheet, with no changes to the merge logic.

### Future extensions (not in scope for initial implementation)

- LLM-aided prompt for character sheet generation
- Save character sheets in .config/mgmai
- Per-stat range validation (requires adding min/max to `StatDefinition`).
