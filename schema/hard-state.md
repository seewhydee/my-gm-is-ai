# Hard Game State Schema

Hard game state records the mutable aspects of the adventure.  It is
initialised from a file (e.g., `hard-state.json`) at game start, and
**only** mutated by the engine.  The LLM never writes directly to hard
state; it only submits actions for the engine to validate and resolve.

## Top-Level Structure

```json
{
  "player":       { /* player state */ },
  "flags":        { "<flag_id>": true | false, ... },
  "room_states":  { "<room_id>": { "<field>": <value>, ... } },
  "entity_states":{ "<entity_id>": { "<field>": <value>, ... } },
  "room_contains": { "<room_id>": { "<entity_id>": <count>, ... } },
  "entity_contains": { "<container_id>": { "<entity_id>": <count>, ... } },
  "turn_count":   0,
  "game_over":    null,
  "combat":       null
}
```

These fields are documented below.  See the [Corpus](corpus.md) schema
for the (immutable) definitions of rooms, entities, mechanics, etc.

---

## Player State

The `player` block describes the player's state.

### Core fields

The following fields form the system-agnostic core of the player state.
Additional fields may be required by the declared RPG system; see
[5e system fields](#5e-system-fields) below.

```json
{
  "location": "<room_id>",
  "stats": { "STR": 14, "DEX": 12, "CON": 13,
			 "INT": 10, "WIS": 8, "CHA": 16 },
  "inventory": { "<item_entity_id>": <count>, ... },
  "equipped": ["<item_entity_id>", ...]
}
```

| Field      | Type     | Description                         |
|------------|----------|-------------------------------------|
| `location` | string   | Room ID of room the player is in    |
| `stats`    | object   | Player stats (stat key → integer)   |
| `inventory`| object   | Item entity IDs → integer counts    |
| `equipped` | string[] | Entity IDs for equipped items       |

Notes:

- `location` must match the room ID of a room in the corpus.

- `stats` should be null if the corpus does not define stats.
  Otherwise, it should be an object mapping each player stat ID (a
  string) to its current valu (an integer).  All stats defined in the
  corpus (see [corpus.md](corpus.md#player-stats)) must be present.

- `inventory` is an object mapping item entity IDs to their integer
  counts, such that:
  - Each key must match an item entity ID defined in the corpus.
  - Items without the `stackable` tag are unique: their count is always
    1, and adding another raises an error.
  - Items with the `stackable` tag may have counts ≥ 1. If the item
    defines `max_stack`, the count may never exceed it.
  - Removing an item decrements the count; the key is deleted when the
    count reaches 0.
  Note that items in `equipped` are NOT in `inventory`.  Equipping
  decrements the inventory count by 1 (and may delete the key). Defaults
  to `{}`.

### Equipment rules

Parallel to `inventory`, `equipped` tracks items the player is actively wearing
or wielding:

1. Items in `equipped` are referenced by entity ID, matching `inventory`.
2. Equipping an item: the engine decrements the item's count in `inventory`
   by 1 and appends the ID to `equipped`. The tag conflict resolver runs first
   (see `corpus.md` § `equip_block`).
3. Unequipping an item: the engine removes the ID from `equipped` and
   increments the item's count in `inventory` by 1.
4. Equipment stat modifiers are computed on-the-fly — `hard.player.stats` remains
   the permanent baseline and is never modified by equipment.
5. `equipped` defaults to `[]` for backward compatibility with old save files
   that do not contain the field.

### 5e system fields

When `corpus.stats.system` is `"5e"`, the following additional fields are
accepted in the player state. Other systems may define their own set of
system-specific fields.

```json
{
  "level": 1,
  "current_hp": 10,
  "max_hp": 10,
  "ac": null,
  "proficiency_bonus": 2,
  "save_proficiencies": ["STR", "CON"]
}
```

| Field                | Type     | Description                         |
|----------------------|----------|-------------------------------------|
| `level`              | integer  | Player level (default 1)            |
| `current_hp` (*)     | integer  | Current hit points                  |
| `max_hp` (*)         | integer  | Maximum hit points                  |
| `ac`                 | integer  | Explicit AC, if not computed        |
| `proficiency_bonus` (*) | integer| Proficiency bonus (5e standard)   |
| `save_proficiencies` | string[] | Stat IDs for saving throw proficiencies |

When `ac` is `null`, AC is computed from base (10 + DEX mod) plus
equipment bonuses. Set an explicit value to override the computation.

When `proficiency_bonus` is `null`, it defaults to the standard 5e
progression for the player's `level`.

---

## `flags` — Global boolean flags

```json
{
  "<flag_id>": true | false
}
```

Flags represent binary world state: conditions discovered, events triggered,
doors opened, NPCs met, etc. The engine uses flags to evaluate conditions on
exits, interactions, encounters, and game-over conditions.

### Flag lifecycle

1. **Initialised** from `hard-state.json` at game start.
2. **Set/cleared** by the engine during:
   - Interaction resolution (`result.set_flag`, `success.set_flag`)
   - Reaction `result.set_flag` effects
   - Encounter outcomes (`set_flag`)
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
a room. Additional per-room fields must be declared in the room's
`state_fields` in the corpus and evaluated in condition strings as
`room:<room_id>.<field> <op> <value>`.

### State field types

| Type      | Default | Description |
|-----------|---------|-------------|
| `boolean` | `false` | Used for `visited`, room-specific toggles. |
| `number`  | `0`     | Used for counters (future). |
| `string`  | `""`    | Used for short text state (future). |

### Initialisation

Room state entries are initialised from `hard-state.json`. The engine validates
at startup that every `room_id` in `room_states` exists in the module corpus,
and that every field (except `visited` and `is_current`) matches a declared `state_fields` entry
in that room's corpus definition.

If a field's `state_fields` declaration in the corpus includes an `initial`
value and no explicit value is supplied in `hard-state.json`, the engine uses
the corpus `initial` as the default.  A value supplied in `hard-state.json`
always overrides the corpus default.

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

If a field's `state_fields` declaration in the corpus includes an `initial`
value and no explicit value is supplied in `hard-state.json`, the engine
uses the corpus `initial` as the default.  A value supplied in
`hard-state.json` always overrides the corpus default.

### State filtering for GMBriefing

When the Context Assembler builds the GMBriefing, it:
1. Lists entities in `hard.room_contains` for the current room.
2. Filters to entities where `state.alive == true` (or the entity has no
   `alive` field — static features are always visible).
3. Includes a brief description and current state summary for each visible entity.

---

## Runtime containment (`room_contains`, `entity_contains`)

```json
{
  "room_contains": {
    "<room_id>": { "<entity_id>": <count> }
  },
  "entity_contains": {
    "<container_id>": { "<entity_id>": <count> }
  }
}
```

These maps track the mutable location of every entity in the world.
`room_contains` holds entities placed directly in rooms;
`entity_contains` holds entities nested inside container entities.

### Initialisation

- On `load_all`, the engine always rebuilds both maps from the corpus
  `Room.contains_map` / `Entity.contains_map`.
- On `load_save`, if the save already contains `room_contains`, the saved
  maps are used as-is.  Legacy saves that lack the keys are backfilled
  from the corpus once.

### Mutation rules

- Player `take` actions decrement the source container/room and add to
  `player.inventory`.
- Player `give` actions decrement `player.inventory` and increment the
  target room or entity container.
- `Result.add_item` for a non-stackable item that exists in a world
  container in the current room removes it from that container (prevents
  duplication of unique items).  Stackable `add_item`/`add_item_count`
  does not touch world containers (the grant is a materialization, not a
  transfer from a specific location).
- `Result.remove_item` removes from `player.inventory` only; the item
  vanishes (no world-side deposit).
- Counts are summed on add; keys are deleted when the count reaches `0`.
- Non-stackable items may never exceed count `1` in a location.
- Stackable items respect `max_stack`.

### Persistence

Both maps are serialised as part of the hard state in save files.

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
| `trigger` | string | The `trigger_id` of the game-over that fired — from an inline `Result.game_over` or a top-level `game_over_conditions` entry (matches module corpus). |

--

## `combat` — Combat state

When non-null, the game is in combat mode. The field holds a `CombatState` object
managing initiative, turn order, and a combat log. When `null`, standard
exploration/resolution is active.

```json
{
  "active": true,
  "combatants": ["player", "spider"],
  "initiative_order": ["player", "spider"],
  "current_index": 0,
  "round_number": 1,
  "log": []
}
```

| Field               | Type     | Description |
|---------------------|----------|-------------|
| `active`            | bool     | Whether combat is currently in progress. |
| `combatants`        | string[] | List of participant IDs — `"player"` plus NPC entity IDs. |
| `initiative_order`  | string[] | Sorted turn order of combatants. |
| `current_index`     | int      | Index into `initiative_order` for the actor whose turn it is. |
| `round_number`      | int      | Current combat round (starts at 1). |
| `log`               | object[] | List of `CombatLogEntry` objects recording each action taken. |

### Combat log entry

```json
{
  "round": 1,
  "actor": "player",
  "action": "attack",
  "target": "spider",
  "attack_roll": 15,
  "attack_total": 18,
  "ac": 13,
  "hit": true,
  "critical": false,
  "damage_roll": "1d8+2",
  "damage": 7,
  "remaining_hp": 5,
  "on_hit_effects": []
}
```

| Field            | Type     | Description |
|------------------|----------|-------------|
| `round`          | int      | The round number this entry belongs to. |
| `actor`          | string   | Who took the action (`"player"` or an NPC entity ID). |
| `action`         | string   | Action type: `"attack"`, `"flee"`, `"death"`, etc. |
| `target`         | string?  | Target of the action (if applicable). |
| `attack_roll`    | int?     | Raw d20 roll. |
| `attack_total`   | int?     | Total after modifiers. |
| `ac`             | int?     | Target's AC at time of attack. |
| `hit`            | bool?    | Whether the attack landed. |
| `critical`       | bool?    | Whether the attack was a critical hit. |
| `damage_roll`    | string?  | Damage dice expression rolled. |
| `damage`         | int?     | Final damage dealt. |
| `remaining_hp`   | int?     | Target's HP after damage. |
| `on_hit_effects` | object[] | On-hit save effects that triggered (see `combat` in corpus.md). |

## NPC attitude

NPC attitude is tracked as an integer in `hard_state.entity_states[<npc_id>].attitude`. Positive values indicate friendly disposition; negative values indicate hostility.

---

## Engine write operations

The engine mutates hard state through these operations:

| Operation              | Affects                        |
|------------------------|--------------------------------|
| `set_player_location`  | `player.location`              |
| `add_item`             | `player.inventory`             |
| `remove_item`          | `player.inventory`             |
| `add_room_contains`    | `room_contains.<room_id>`      |
| `remove_room_contains` | `room_contains.<room_id>`      |
| `add_entity_contains`  | `entity_contains.<entity_id>`  |
| `remove_entity_contains`| `entity_contains.<entity_id>` |
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
    "inventory": {}
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
  "game_over": null,
  "combat": null
}
```


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
