# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

- **Character sheet improvements**: LLM-aided prompt for character sheet generation; save character sheets in .config/mgmai.

---

## Inventory Subsystem Overhaul

### Current State (problems)

1.  **`i` / `inv` goes through the full LLM pipeline.**  
    `input_normalizer.py:36-37` maps `"i"` and `"inv"` → `"check my inventory"`.  
    This enters `_run_turn()` → `normalize + assemble briefing + LLM ruling call + engine resolve + LLM prose call`.  
    Two LLM round-trips just to list what you're carrying.  It also consumes a turn (and, in combat, a round).

2.  **Inventory is rendered in the compact status bar every turn.**  
    `display.py:148-161` (`render_status`): hard inventory IDs and soft inventory strings are crammed into a one-line status bar alongside turn count, location, and flags.  
    This doesn't scale — a dozen items would make the status line unreadable.  Equipped items are *not* shown in the status bar at all.

3.  **Equipped items disappear from inventory.**  
    `resolver.py:1707` (`resolve_equip`): on success, the target is moved from `hard.player.inventory` → `hard.player.equipped`.  
    `resolver.py:1748-1749` (`resolve_unequip`): reverse move.  
    The data model is clean (carried vs. worn/wielded), but the *presentation* is misleading: the player equips a sword and it vanishes from any "inventory" view.  The player never sees equipped gear unless they introspect deeply or remember what's on their character sheet.

4.  **Room entity filtering only checks `inventory`, not `equipped`.**  
    `assembler.py:94`: `if entity.type == "item" and eid in hard.player.inventory: continue` — this hides items the player has picked up from the room's visible entity list.  But equipped items are NOT in `inventory`, so they remain visible in the room description as if they were still on the floor.  This is a bug.

5.  **No `/inv` slash command exists.**  
    `commands.py:68-78` dispatch table has no inventory entry.  Only the IF shortcut expansion path exists.

### Design Goals

*   **Engine-level inventory display** — typing `i`, `inv`, or `/inv` prints inventory immediately with zero LLM involvement.  
*   **No turn/round consumption** — inventory display is a free player-convenience action that doesn't advance time.  
*   **Unified inventory view** — the `/inv` output shows *everything* the player is carrying: equipped gear (annotated with tags/effects), other hard items, and soft/misc items, all in one panel.  
*   **Status bar stays compact** — remove inventory from `render_status`.  Keep only turn count, location, and active flags.  
*   **Room visibility fix** — equipped items must also be hidden from room visible entities.  The player is carrying/wearing them.

### Detailed Plan

#### 1.  Add engine-level inventory command

**File: `mgmai/game/commands.py`**

*   Add a `_cmd_inv` method that:
    1.  Reads `hard.player.inventory`, `hard.player.equipped`, and `soft.soft_inventory`.
    2.  Looks up item names and descriptions from `corpus.entities` (corpus-validated names beat raw IDs).
    3.  Formats output as a Rich panel with three sections:
        *   **Equipped** — each equipped item shows `name`, `equip_tags`, and a one-line effects summary (damage expression, AC impact, stat modifiers).  Rendered in a dimmed/cyan style to distinguish from carried.
        *   **Carried** — remaining hard inventory items (IDs NOT in `equipped`).  Plain list with item descriptions.
        *   **Pockets / Misc** — soft inventory strings, if any.
    4.  Renders the panel via `self._render`.
*   Add `"inv"`, `"inventory"` to the dispatch table.

**File: `mgmai/game/input_normalizer.py`**

*   Remove the `"i"` and `"inv"` entries from `_SINGLE_TOKEN_SHORTCUTS` (lines 36–37).  
    If the user types `"i"` or `"inv"` with no arguments, these should now be handled before normalization, not expanded to `"check my inventory"`.

**File: `mgmai/game/loop.py`** — `_repl()` method

*   Before calling `self._commands.handle(line)`, insert a check for bare `i` / `inv` / `inventory` (case-insensitive, exact match) and route them to the same `_cmd_inv` handler in `Commands`.  
    Two options:
    *   **A**: Make `Commands.handle()` also accept a non-slash list of engine-only words.  
    *   **B**: Check in `_repl()` and call a new public method on `Commands`: `commands.handle_bare("inv")` → renders + returns `True`.

    Option A is simpler and keeps all command detection in one class.  Add a second dispatch dict `_BARE_COMMANDS` for exact-match engine-level words (`"i"`, `"inv"`, `"inventory"`).  `handle()` checks it after the slash check.

#### 2.  Remove inventory from the status bar

**File: `mgmai/game/display.py`** — `render_status()` (lines 136–171)

*   Remove the `inv` and `soft_inv` lines from both the Rich and plain-text branches.
    *   Rich: remove lines 156–159.
    *   Plain: remove lines 165–168.
*   Keep turn count, location, and active flags only.
*   When combat is active, `_render_combat_status()` already takes priority (line 143–144) and doesn't show inventory — no changes needed there.

#### 3.  Fix room entity visibility for equipped items

**File: `mgmai/context/assembler.py`** — `_build_room()` (line 94)

*   Change:
    ```python
    if entity.type == "item" and eid in hard.player.inventory:
    ```
    to:
    ```python
    if entity.type == "item" and (eid in hard.player.inventory or eid in hard.player.equipped):
    ```
*   This ensures equipped items are also hidden from visible room entities.  The player is carrying/wearing them.

#### 4.  Context Assembler — LLM still sees inventory + equipped items separately

**File: `mgmai/context/assembler.py`** — `_build_player_state()` (lines 255–265)

*   No change needed.  The LLM already receives `hard_inventory`, `soft_inventory`, and `equipped_items` as separate fields in the `PlayerStateBriefing`.  This is appropriate — the LLM needs to know what the player is wearing vs. what's in their pack.  The new engine-level `/inv` command handles the player-facing unified view.

#### 5.  Ensure inventory display does not consume a turn

*   Because the inventory command is handled entirely within `Commands` (or the pre-`_run_turn` check in `_repl`), control returns to the REPL prompt immediately.  Neither `assemble()`, `resolve()`, nor the LLM client are invoked.  Consequently:
    *   `hard.turn_count` is never incremented (`engine.py:520`).
    *   `combat.round_number` is never incremented (`combat.py:401`).
    *   No `turn.end` / `turn.start` events fire.
    *   No autosave happens for the inventory peek.

#### 6.  Update help text

**File: `mgmai/game/commands.py`** — `_cmd_help` (lines 88–113)

*   In the Shortcuts section, update:
    ```
    i, inv               Check inventory
    ```
    to clarify that `i` and `inv` now display inventory directly (engine-level), while `check my inventory` is the natural-language phrase that passes to the LLM if the player wants narration about their items.

### Side Effects & Interactions

*   **Soft inventory** remains unchanged.  Soft items can still be added/removed via `soft_inventory_add`/`soft_inventory_remove` patches by the LLM.  They appear in the `/inv` output and in the LLM's `soft_inventory` briefing field.  
*   **Equipment conditions** (`equipped:weapon`, `equipped:toenail_sword`) are unaffected — the `conditions.py:169-180` check reads `hard.player.equipped` directly.  
*   **Tag conditions** (`tag:weapon`) already check both `inventory` and `equipped` (`conditions.py:82-95`).  No change needed.  
*   **Save/load** is unaffected — the data model (`hard_state.PlayerState.inventory` and `equipped`) remains identical.  Saved games are forward-compatible.  
*   **Tests** — existing `test_input_normalizer.py:75-80` tests for `i`/`inv` shortcut expansion will need to be updated (expansion removed).  New tests should be added for the `/inv` command handler.  `test_equip_gear.py` tests are unaffected.

### Implementation Order

1.  Add `_cmd_inv` and routing in `commands.py`.  
2.  Remove `"i"` / `"inv"` shortcuts from `input_normalizer.py`.  
3.  Add bare-word handling in `loop.py` (or `commands.py` dispatch).  
4.  Strip inventory from `render_status()` in `display.py`.  
5.  Fix `_build_room()` filtering in `assembler.py` (add `equipped` check).  
6.  Update `_cmd_help` text.  
7.  Update tests; run full suite.

