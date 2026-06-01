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
  "player":     { /* player state */ },
  "flags":      { "<flag_name>": true | false, ... },
  "entity_states": { "<entity_id>": { "<field>": <value>, ... } },
  "turn_count": 0,
  "game_over": null
}
```

---

## `player` — Player state

```json
{
  "location": "<room_id>",
  "inventory": ["<item_entity_id>", ...],
  "hit_points": null
}
```

| Field        | Type     | Description |
|--------------|----------|-------------|
| `location`   | string   | Current room ID. Must match a key in the module corpus `rooms`. |
| `inventory`  | string[] | List of item entity IDs the player is carrying. |
| `hit_points` | number|null | Current HP. `null` means HP is not tracked (no combat system). When the combat system is added, this becomes a number. |

### Inventory rules

1. Items in inventory are referenced by their entity ID as defined in the
   module corpus `entities` block.
2. Adding an item: the engine pushes the ID onto the `inventory` array. Duplicates
   are allowed only if the module explicitly supports it (flag: `stackable`).
3. Removing an item: the engine removes the first occurrence from the array.
4. Draggable items (entity `draggable == true`): the engine sets an implicit
   flag `dragging_<item_id>` to `true` when the item is in inventory. The player
   cannot perform manual actions (interact, search, rummage) while dragging.
   Movement is still allowed.
5. The engine checks `inventory contains weapon` by scanning items in inventory
   for the `"weapon"` tag in the entity definition, not by specific item ID.
   This allows future modules to have multiple weapon types.

---

## `flags` — Global boolean flags

```json
{
  "<flag_name>": true | false
}
```

Flags represent binary world state: conditions discovered, events triggered,
doors opened, NPCs met, etc. The engine uses flags to evaluate conditions on
exits, interactions, and encounters.

### Flag lifecycle

1. **Initialised** from `hard-state.json` at game start.
2. **Set/cleared** by the engine during:
   - Exit traversal (`on_traverse.set_flag`)
   - Interaction resolution (`result.set_flag`, `success.set_flag`)
   - On-enter events (`set_flag`)
   - Encounter outcomes (`set_flags`)
3. **Read** by the engine to evaluate:
   - Exit conditions (`conditions`)
   - Interaction conditions (`condition`)
   - On-enter event conditions (`condition`)
   - Encounter rule conditions

### Special flags

Module authors may define flags that have special meanings for the game state.  For instance, the sample adventure "Trapped In A Bag of Holding" uses these flags:

| Flag                | Meaning |
|---------------------|---------|
| `spider_fled`       | Set when the spider flees after being wounded. Prevents re-triggering the spider encounter. |
| `injured`           | Player is injured. Affects spider encounter outcome and blocks certain interactions (e.g., rummaging). |
| `stunned`           | Player is briefly stunned after a safe drop. Transient narrative flag. |
| `dragging_<item>`   | Implicitly managed when a draggable item is in inventory. |

---

## `entity_states` — Per-entity mutable state

```json
{
  "<entity_id>": {
    "<field_name>": <value>
  }
}
```

Each key is an entity ID from the module corpus. The value is an object
containing the current values for that entity's declared `state_fields`.

Only entities that have mutable state need an entry here. Entities with
empty `state_fields` (e.g., static features) do not require entries.

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
3. Includes a brief description and current state summary.

---

## `turn_count` — Turn counter

An integer starting at `0`. Incremented by the engine after successful action
resolution. Used for display and for capping `turn_history` entries in
soft state.

---

## `game_over` — Terminal state

```json
null | { "type": "success", "trigger": "win_escape" } | { "type": "failure", "trigger": "death_spider" }
```

When non-null, the game has ended. No further player input is processed. The
engine includes the game-over state in EngineResult, and LLM Call 2 narrates
the ending without soliciting further input.

| Field     | Type   | Description |
|-----------|--------|-------------|
| `type`    | string | `"success"` or `"failure"`. |
| `trigger` | string | The `id` of the `game_over_condition` that fired (matches module corpus). |

---

## Engine write operations

The engine mutates hard state through these operations:

| Operation              | Affects                      |
|------------------------|------------------------------|
| `set_player_location`  | `player.location`            |
| `add_item`             | `player.inventory`           |
| `remove_item`          | `player.inventory`           |
| `set_flag`             | `flags.<name>`               |
| `clear_flag`           | `flags.<name>`               |
| `set_entity_state`     | `entity_states.<id>.<field>` |
| `increment_turn`       | `turn_count`                 |
| `set_game_over`        | `game_over`                  |

All of these are reflected in the `hard_state_changes` block of EngineResult.

---

## Startup and persistence

1. **Startup**: The engine loads `hard-state.json` and the module corpus. It
   validates that entity_states match declared state_fields.
2. **Between turns**: Hard state is held in memory. On each turn, the engine
   applies changes and produces `hard_state_changes` for the EngineResult.
3. **Save/load**: Future — serialise the full hard state to disk for save files.

---

## Example (initial state for test adventure)

```json
{
  "player": {
    "location": "axe_head",
    "inventory": [],
    "hit_points": null
  },
  "flags": {
    "injured": false,
    "stunned": false,
    "handkerchief_noticed": false,
    "handkerchief_moved": false,
    "padlock_unlocked": false
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
