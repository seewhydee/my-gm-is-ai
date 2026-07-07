# Hard Game State Schema

Hard game state records the mutable aspects of the adventure.  It is
**only** mutated by the engine.  The LLM never writes directly to hard
state; it only submits actions for the engine to validate and resolve.

When the game starts, the engine initializes the hard state from
`hard-state.json`, and performs validatation of its contents against
the `corpus.md`.  Between turns, hard state is held in memory. On each
turn, the engine applies changes based on the player's actions and its
side-effects.  When the game is saved, the full hard state is
serialised to disk.  Between turns, a copy is also saved, along with
soft state (except during chained actions where control does not
return to the player).

## Top-Level Structure

```json
{
  "flags":         { "<flag_id>": true | false, ... },
  "player":        { /* player state */ },
  "room_states":   { "<room_id>": { "<field>": <value>, ... } },
  "entity_states": { "<entity_id>": { "<field>": <value>, ... } },
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

## Global Boolean Flags

```json
{
  "<flag_id>": true | false
}
```

The `flags` field represent binary world state: conditions discovered,
events triggered, doors opened, NPCs met, etc.  They can be read by
Condition objects, and set/cleared by Result resolutions and NPC
revelations; setting/clearing flags can also act as Event triggers for
reactions.

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
  counts (default `{}`).

  Each key must match an item entity ID defined in the corpus.  Items
  with the `stackable` tag may have counts >= 1, up to their
  corpus-defined `max_stack` field (if any).  Items without
  `stackable` are unique, and must have count 1 (engine-enforced).
  Removing an item decrements the count, and the key is deleted when
  the count reaches 0.

  Note that items in `equipped` are NOT in `inventory`.  The act of
  equipping decrements the inventory count by 1.

- `equipped` lists the entity IDs for all items the player is wearing
  or wielding (default `[]`).  Upon equipping an item, the engine
  decrements the count in `inventory` by 1 and appends the ID to
  `equipped`, and vice versa for unequipping.  When equipping, the
  engine also enforces any constraints specified in the item's
  `equip_block`; see the [Corpus schema](corpus.md#equipment).

  Equipped items can modify the player's stats.  This is computed
  on-the-fly by starting from the `hard.player.stats` baseline (which
  is never modified by equipment) and layering on the `stat_effects`
  in the item's `equip_block`.

### 5e system fields

When `corpus.stats.system` is `"5e"`, the following additional fields
are accepted in the player state. Other systems may define their own
set of system-specific fields.

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
| `proficiency_bonus` (*) | integer | Proficiency bonus                 |
| `save_proficiencies` | string[] | Stat IDs for saving throw proficiencies |

When `ac` is `null`, AC is computed from base (10 + DEX mod) plus
equipment bonuses. Set an explicit value to override the computation.

When `proficiency_bonus` is `null`, it defaults to the standard 5e
progression for the player's `level`.

---

## Per-Room and Per-Entity Mutable States

```json
{
  "room_states": {
	"<room_id>": { "<field_name>": <value> }
  },
  "entity_states": {
	"<entity_id>": { "<field_name>": <value> }
  }
}
```

The `room_states` and `entity_states` fields track per-room and
per-entity mutable properties.  They map room/entity IDs to objects
mapping state fields (strings) to their present values (each matching
the type declared in the Corpus – boolean, number, or string).  If an
initial value is not specified by the Corpus, it defaults to `false`
(boolean), `0` (number), or `""` (string).

Every room/entity defined in the Corpus must be present in these
blocks.  Every Corpus-defined state field must be present.  In
addition, each room entry must include the reserved state field
`visited` (boolean), which the engine sets to `true` the first time
the player enters a room.

---

## Containment Lists

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

These maps track the mutable location of every entity in the world:
`room_contains` records entities placed directly in rooms, while
`entity_contains` records entities nested inside other entities.  The
initial values are determined by the `contains` fields of the Room and
Entity objects in the Corpus.

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

When non-null, the game has ended. No further player input is
processed. The engine includes the game-over state in EngineResult,
and the GM narrates the ending without soliciting further input.

| Field     | Type   | Description |
|-----------|--------|-------------|
| `type`    | string | Type of outcome: `"win"`, `"lose"`, or something else |
| `trigger` | string | The `trigger_id` of the game-over that fired — from an inline `Result.game_over` or a top-level `game_over_conditions` entry in Corpus. |

--

## `combat` — Combat state

When non-null, the game is in combat mode. The field holds a
`CombatState` object managing initiative, turn order, and a combat
log. When `null`, standard exploration/resolution is active.

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

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
