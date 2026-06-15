# Hard Game State Schema

Hard game state is the authoritative, engine-managed runtime state. It is
directly mutated **only** by the engine during action resolution. The LLM
never writes to hard state; it may only read it via the GMBriefing.

Hard state is initialised from a file (e.g., `hard-state.json`) at game start,
persisted between turns, and queried by the engine to validate actions and
resolve mechanics.

## Top-Level Structure

```json
{
  "player":       { /* player state */ },
  "flags":        { "<flag_name>": true | false, ... },
  "room_states":  { "<room_id>": { "<field>": <value>, ... } },
  "entity_states":{ "<entity_id>": { "<field>": <value>, ... } },
  "turn_count":   0,
  "game_over":    null
}
```

---

## `player` — Player state

```json
{
  "location": "<room_id>",
  "inventory": ["<item_entity_id>", ...],
  "stats": {
    "STR": 14,
    "DEX": 12,
    "CON": 13,
    "INT": 10,
    "WIS": 8,
    "CHA": 16
  }
}
```

| Field      | Type     | Description |
|------------|----------|-------------|
| `location` | string   | Current room ID. Must match a key in the module corpus `rooms`. |
| `inventory`| string[] | List of item entity IDs the player is carrying (hard inventory). |
| `equipped` | string[] | List of item entity IDs the player currently has equipped. Items in `equipped` are NOT in `inventory` — equipping moves the ID from one list to the other. Defaults to `[]`. |
| `stats`    | object   | Player ability scores. Optional dict of stat key → integer value. Keys must match `stats.definitions` in the corpus. When stats are present in the corpus, this field should also be present (and vice versa). The engine validates key consistency on startup. |

### Inventory rules

1. Items in inventory are referenced by their entity ID as defined in the
   module corpus `entities` block.
2. Adding an item: the engine pushes the ID onto the `inventory` array. Duplicates
   are allowed only if the module explicitly supports it (tag: `stackable`).
3. Removing an item: the engine removes the first occurrence from the array.
4. Draggable items (entity `draggable == true`): the engine sets an implicit
   flag `dragging_<item_id>` to `true` when the item is in inventory. The player
   cannot perform manual actions (interact, examine) while dragging.
   Movement is still allowed.
5. The engine checks `tag:weapon` by scanning items in inventory
   for the `"weapon"` tag in the entity definition, not by specific item ID.
   This allows future modules to have multiple weapon types.

### Equipment rules

Parallel to `inventory`, `equipped` tracks items the player is actively wearing
or wielding:

1. Items in `equipped` are referenced by entity ID, matching `inventory`.
2. Equipping an item: the engine removes the ID from `inventory` and appends it
   to `equipped`. The tag conflict resolver runs first (see `corpus.md` § `equip_block`).
3. Unequipping an item: the engine removes the ID from `equipped` and appends it
   to `inventory`.
4. Equipment stat modifiers are computed on-the-fly — `hard.player.stats` remains
   the permanent baseline and is never modified by equipment.
5. `equipped` defaults to `[]` for backward compatibility with old save files
   that do not contain the field.

---

## `flags` — Global boolean flags

```json
{
  "<flag_name>": true | false
}
```

Flags represent binary world state: conditions discovered, events triggered,
doors opened, NPCs met, etc. The engine uses flags to evaluate conditions on
exits, interactions, encounters, and game-over mechanics.

### Flag lifecycle

1. **Initialised** from `hard-state.json` at game start.
2. **Set/cleared** by the engine during:
   - Exit traversal (`on_traverse.set_flag`)
   - Interaction resolution (`result.set_flag`, `success.set_flag`)
   - On-enter events (`set_flag`)
   - Encounter outcomes (`set_flags`)
3. **Read** by the engine to evaluate:
   - Exit conditions
   - Interaction conditions
   - On-enter event conditions
   - Encounter rule conditions
   - Game-over conditions

### Special flags

Module authors may define flags that have special meanings for game state.
For instance, the sample adventure "Trapped In A Bag of Holding" uses these flags:

| Flag               | Meaning |
|--------------------|---------|
| `spider_fled`      | Set when the spider flees after being wounded. Prevents re-triggering the spider encounter. |
| `injured`          | Player is injured. Affects encounter outcomes and blocks certain interactions. |
| `stunned`          | Player is briefly stunned. Transient narrative flag. |
| `dragging_<item>`  | Implicitly managed when a draggable item is in inventory. |

---

## `room_states` — Per-room mutable state

```json
{
  "<room_id>": {
    "<field_name>": <value>
  }
}
```

Tracks per-room mutable properties. The primary initial field is `visited`
(boolean), which the engine sets to `true` the first time the player enters
a room. Additional per-room fields can be declared by module authors and
evaluated in condition strings as `room:<room_id>.<field> <op> <value>`.

### State field types

| Type      | Default | Description |
|-----------|---------|-------------|
| `boolean` | `false` | Used for `visited`, room-specific toggles. |
| `number`  | `0`     | Used for counters (future). |
| `string`  | `""`    | Used for short text state (future). |

### Initialisation

Room state entries are initialised from `hard-state.json`. The engine validates
at startup that every `room_id` in `room_states` exists in the module corpus.

---

## `entity_states` — Per-entity mutable state

```json
{
  "<entity_id>": {
    "<field_name>": <value>
  }
}
```

Tracks per-entity mutable properties (e.g., `alive`, `told_secret`, `fled`).
Each key is an entity ID from the module corpus. The value is an object
containing the current values for that entity's declared `state_fields`.

Only entities that have declared `state_fields` in the corpus need an entry here.

### State field types

| Type      | Default | Description |
|-----------|---------|-------------|
| `boolean` | `false` | Used for alive/dead, discovered, activated, etc. |
| `number`  | `0`     | Used for HP, counter variables (future). |
| `string`  | `""`    | Used for short text state (future). |

### Initialisation

The entity state block in `hard-state.json` must include an entry for every
entity with non-empty `state_fields`, with an initial value for each field.
The engine validates at startup that:
- Every entity_id in `entity_states` exists in the module corpus.
- Every field name matches a declared `state_field` for that entity.
- Values are of the correct type.

### State filtering for GMBriefing

When the Context Assembler builds the GMBriefing, it:
1. Lists entities in `entities_present` for the current room.
2. Filters to entities where `state.alive == true` (or the entity has no
   `alive` field — static features are always visible).
3. Includes a brief description and current state summary for each visible entity.

---

## `turn_count` — Turn counter

An integer starting at `0`. Incremented by the engine after successful action
resolution (except for `ooc_discussion`, which does not advance the counter).
Used for display and for capping `turn_history` entries in soft state.

---

## `game_over` — Terminal state

```json
null
```

or

```json
{ "type": "win", "trigger": "escape_bag" }
```

or

```json
{ "type": "lose", "trigger": "death_spider" }
```

When non-null, the game has ended. No further player input is processed. The
engine includes the game-over state in EngineResult, and LLM Call 2 narrates
the ending without soliciting further input.

| Field     | Type   | Description |
|-----------|--------|-------------|
| `type`    | string | Describes the outcome (typically `"win"` or `"lose"`). Unrestricted to accommodate tabletop games with non-binary endings. |
| `trigger` | string | The `trigger_id` of the game-over mechanic that fired (matches module corpus). |

---

## Engine write operations

The engine mutates hard state through these operations:

| Operation              | Affects                        |
|------------------------|--------------------------------|
| `set_player_location`  | `player.location`              |
| `add_item`             | `player.inventory`             |
| `remove_item`          | `player.inventory`             |
| `set_flag`             | `flags.<name>`                 |
| `clear_flag`           | `flags.<name>`                 |
| `set_room_state`       | `room_states.<id>.<field>`     |
| `set_entity_state`     | `entity_states.<id>.<field>`   |
| `equip_item`           | `player.equipped`              |
| `unequip_item`         | `player.equipped`              |
| `increment_turn`       | `turn_count`                   |
| `set_game_over`        | `game_over`                    |

All of these are reflected in the `hard_state_changes` block of EngineResult.

---

## Startup and persistence

1. **Startup**: The engine loads `hard-state.json` and the module corpus. It
   validates that entity_states match declared state_fields and that room_states
   reference valid room IDs.
2. **Between turns**: Hard state is held in memory. On each turn, the engine
   applies changes and produces `hard_state_changes` for the EngineResult.
3. **Save/load**: The full hard state is serialised to disk for save files.
   Between turns, a copy is saved along with soft state (except during chained
   actions where control does not return to the player).

---

## Example (initial state for test adventure)

```json
{
  "player": {
    "location": "axe_head",
    "inventory": []
    // "stats": { "STR": 14, "DEX": 12, ... } — optional ability scores
  },
  "flags": {
    "injured": false,
    "stunned": false,
    "handkerchief_noticed": false,
    "handkerchief_moved": false,
    "padlock_unlocked": false
  },
  "room_states": {
    "axe_head": { "visited": false },
    "axe_handle_upper": { "visited": false },
    "axe_handle_lower": { "visited": false },
    "bag_floor": { "visited": false }
  },
  "entity_states": {
    "stuck_fly": { "alive": true },
    "spider": { "alive": true, "fled": false },
    "korbar": { "alive": true, "told_secret": false }
  },
  "turn_count": 0,
  "game_over": null
}
```


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
