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
  "flags":        { "<flag_id>": true | false, ... },
  "room_states":  { "<room_id>": { "<field>": <value>, ... } },
  "entity_states":{ "<entity_id>": { "<field>": <value>, ... } },
  "turn_count":   0,
  "game_over":    null,
  "combat":       null
}
```

---

## `player` — Player state

```json
{
  "location": "<room_id>",
  "inventory": ["<item_entity_id>", ...],
  "equipped": ["<item_entity_id>", ...],
  "stats": {
    "STR": 14,
    "DEX": 12,
    "CON": 13,
    "INT": 10,
    "WIS": 8,
    "CHA": 16
  },
  "level": 1,
  "current_hp": 10,
  "max_hp": 10,
  "ac": null,
  "proficiency_bonus": 2,
  "save_proficiencies": ["STR", "CON"]
}
```

| Field                   | Type     | Description |
|-------------------------|----------|-------------|
| `location`              | string   | Current room ID. Must match a key in the module corpus `rooms`. |
| `inventory`             | string[] | List of item entity IDs the player is carrying (hard inventory). |
| `equipped`              | string[] | List of item entity IDs the player currently has equipped. Items in `equipped` are NOT in `inventory` — equipping moves the ID from one list to the other. Defaults to `[]`. |
| `stats`                 | object   | Player ability scores. Optional dict of stat key → integer value. Keys must match `stats.definitions` in the corpus. When stats are present in the corpus, this field should also be present (and vice versa). The engine validates key consistency on startup. |
| `level`                 | int      | Player level (default 1). |
| `current_hp`            | int|null| Current hit points, or `null` if HP tracking is not used. |
| `max_hp`                | int|null| Maximum hit points, or `null` if HP tracking is not used. |
| `ac`                    | int|null| Explicit armour class value. When `null`, AC is computed from base (10 + DEX mod) plus equipment bonuses. Set an explicit value to override the computation. |
| `proficiency_bonus`     | int|null| Proficiency bonus for attack rolls and proficient saving throws. When `null`, defaults to the 5e standard based on `level`. |
| `save_proficiencies`    | string[] | List of stat keys (e.g. `"STR"`, `"DEX"`) the player is proficient in for saving throws. |

### Inventory rules

1. Items in inventory are referenced by their entity ID as defined in the
   module corpus `entities` block.
2. Adding an item: the engine pushes the ID onto the `inventory` array. Duplicates
   are allowed only if the module explicitly supports it (tag: `stackable`).
3. Removing an item: the engine removes the first occurrence from the array.
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
1. Lists entities in `contains` for the current room.
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
  "game_over": null,
  "combat": null
}
```


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
