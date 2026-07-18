# Hard Game State Schema

Hard game state records the mutable aspects of the adventure.  It is
*only* mutated by the engine.  The LLM never writes directly to hard
state; it only submits actions for the engine to validate and resolve.

When the game starts, the engine generates the initial world state
(`flags`, `room_states`, `entity_states`, containment, etc.) from the
corpus.  An optional file `hard-state.json`, if present, overrides the
starting world state.  The player block is initialized from (in order
of increasing priority) the adventure default `default-player.json`,
any player block override in `hard-state.json`, and any `--char-sheet`
supplied by the player.

Between turns, hard state is held in memory. On each turn, the engine
applies changes based on the player's actions and its side-effects.
When the game is saved, the full hard state is serialised to disk.
Between turns, a copy is also saved, along with soft state (except
during chained actions where control does not return to the player).

## Top-Level Structure

```json
{
  "flags":         { "<flag_id>": true | false, ... },
  "turn_count":    0,
  "game_over":     null,
  "player":        { /* player state — optional in hard-state.json override */ },
  "room_states":   { "<room_id>": { "<field>": <value>, ... } },
  "entity_states": { "<entity_id>": { "<field>": <value>, ... } },
  "room_contains": { "<room_id>": { "<entity_id>": <count>, ... } },
  "entity_contains": { "<container_id>": { "<entity_id>": <count>, ... } },
  "combat":        null
}
```

`player` is required in the in-memory runtime model, but it may be
omitted from `hard-state.json` when that file is used only as a
world-state override; the engine injects the cascaded player block
before validation.  These fields are documented below.  See the
[Corpus](corpus.md) schema for the (immutable) definitions of rooms,
entities, mechanics, etc.

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

## Turn Counter

The top-level `turn_count` field must be an integer, and is
initialized as '0' at the start of the game.  The turn counter is
incremented by the engine after each successful action resolution,
except for cursory examinations and OOC discussion.

---

## Game-Over State

If the top-level `game_over` field is non-null, the game has ended and
no further player input is processed.

```json
{ "type": "win", "trigger": "escaped_castle" }
```

| Field     | Type   | Description                                     |
|-----------|--------|-------------------------------------------------|
| `type`    | string | Outcome type: `"win"`, `"lose"`, etc.           |
| `trigger` | string | Descriptor for the triggering game-over outcome |

Both fields have no actual gameplay effects.  The `trigger` is
intended for debugging and player review of the final save file.

---

## Player State

The top-level `player` field is used to describe the player's state.

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

| Field                | Type     | Description                    |
|----------------------|----------|--------------------------------|
| `level`              | integer  | Player level (default 1)       |
| `current_hp`         | integer  | Current hit points             |
| `max_hp`             | integer  | Maximum hit points             |
| `ac`                 | integer  | Explicit AC, if not computed   |
| `proficiency_bonus`¹ | integer  | Proficiency bonus              |
| `save_proficiencies` | string[] | Saving throw proficiency stats |

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
the type declared in the Corpus – boolean, number, or string).  Initial
values are determined by the corpus field declaration; see
[Corpus.md](corpus.md#room) for details.

Every room/entity defined in the Corpus must be present in these
blocks.  Every Corpus-defined state field must be present.  In
addition, each room entry must include the reserved state field
`visited` (boolean), which the engine sets to `true` the first time
the player enters a room.

### NPC Attitude

Each NPC may declare a numeric `attitude` state field representing its
disposition toward the player.  Attitude is hard state: it lives in
`entity_states[<npc_id>].attitude` and is mutated exclusively by the
engine.  The LLM never writes it directly; LLM Call 2 proposes changes
via the `attitude_changes` block (see `actions.md` §5), and the engine
post-validates them in step 4.5 against the NPC's corpus-defined
`dialogue.attitude_limits` (see `corpus.md`, and `doc/npcs.md` for the
design):

| Rule | Description |
|------|-------------|
| Entity must exist | NPC entity ID must be defined in the corpus. |
| Attitude step limit | Absolute delta must not exceed corpus `attitude_limits.step_per_turn`. |
| Attitude bounds | `new_value` must be within corpus `attitude_limits.[min, max]`. |
| Alive check | Changes for entities with `alive == false` are rejected. |
| Reason required | `reason` must be non-empty. |

The engine initialises each NPC's attitude from the corpus
`state_fields.attitude.initial` (default 0).  The Context Assembler
surfaces the current attitude for visible NPCs via
`BriefingEntity.state`, and the `EngineResult.npc_attitude_limits`
block tells LLM Call 2 the bounds and `step_per_turn` for NPCs present
after resolution.

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

The special entity state field `location` is derived from these at
query time.  It reads as `"room:<room_id>`/`"entity:<container_id>"`
when the entity is in-game, or `null` when it is absent from play.

Notes:

- Counts are summed on add; keys are deleted when counts reach `0`.
  Non-stackable items may never exceed count `1` in a location;
  stackable items respect their `max_stack` field.

- Player `take` actions decrement the source container/room and add to
  `player.inventory`.  Similarly, `give` actions decrement
  `player.inventory` and increment the target room/entity container.

- A successful `Result.add_item` for a non-stackable item removes it
  any previous location, to prevent duplication of unique items.
  However, `add_item`/`add_item_count` for stackable items do not
  trigger auto-removal; the grant is a materialization not a transfer.

- `Result.remove_item` removes from `player.inventory` only; the item
  vanishes without any world-side deposit.

---

## Combat State

When the top-level `combat` field is non-null, the game is in combat
mode.  The field holds an object managing initiative, turn order, and
a combat log:

```json
{
  "active": true,
  "combatants": ["player", "korbar", "spider"],
  "allies": ["korbar"],
  "initiative_order": ["player", "korbar", "spider"],
  "current_index": 0,
  "round_number": 1,
  "log": [],
  "last_attacker": {"spider": "player"},
  "player_last_target": "spider"
}
```

| Field              | Type     | Description                        |
|--------------------|----------|------------------------------------|
| `active`           | bool     | Whether combat is in progress      |
| `combatants`       | string[] | Participants: `"player"`, NPC IDs  |
| `allies`           | string[] | Combatant IDs fighting on the player's side (followers with combat blocks) |
| `initiative_order` | string[] | Sorted turn order of combatants    |
| `current_index`    | int      | Initiative index for current actor |
| `round_number`     | int      | Current combat round (starts at 1) |
| `log`              | CombatLogEntry[] | See below                  |
| `last_attacker`    | object   | Combat-AI bookkeeping: combatant ID → ID of the combatant who last landed a hit on them |
| `player_last_target` | string?  | The enemy the player most recently attacked (drives default ally targeting) |

Enemy NPCs may also carry the engine-owned `fled` entity state
(`entity_states.<npc_id>.fled == true`) after fleeing combat via their
`ai.flee_below_hp_pct` threshold; it is set by the engine at runtime and
persists across saves.

### Combat Log Entries

The format of CombatLogEntry entries depends on the RPG system.  For
`5e` combat (the only one implemented), they have the following form:

```json
{
  "round": 1,
  "actor": "spider",
  "action": "attack",
  "target": "player",
  "attack_roll": 15,
  "attack_total": 18,
  "ac": 13,
  "hit": true,
  "critical": false,
  "damage_roll": "1d8+3",
  "damage": 7,
  "remaining_hp": 5,
  "on_hit_effects": [
    {
      "save_stat": "CON",
      "save_dc": 11,
      "save_roll": 9,
      "save_total": 10,
      "save_success": false,
      "damage_expr": "1d8",
      "damage": 5,
      "damage_type": "poison"
    }
  ]
}
```

| Field            | Type    | Description                           |
|------------------|---------|---------------------------------------|
| `round`          | int     | This entry's round number             |
| `actor`          | string  | Who acts: `"player"` or NPC ID        |
| `action`         | string  | `"attack"`, `"flee"`, `"death"`, etc. |
| `target`         | string? | Target of the action (if applicable)  |
| `attack_roll`    | int?    | Raw d20 roll                          |
| `attack_total`   | int?    | Total after modifiers                 |
| `ac`             | int?    | Target's AC at time of attack         |
| `hit`            | bool?   | Whether the attack landed             |
| `critical`       | bool?   | Whether the attack was a critical hit |
| `damage_roll`    | string? | Damage dice expression rolled         |
| `damage`         | int?    | Final damage dealt                    |
| `remaining_hp`   | int?    | Target's HP after damage              |
| `on_hit_effects` | object[]| On-hit `CheckResolution` effects triggered by the attack |

Each object in `on_hit_effects` records the resolved saving throw (or
roll) and its damage outcome:

| Field          | Type    | Description                          |
|----------------|---------|--------------------------------------|
| `save_stat`    | string? | Stat used for the save (if any)      |
| `save_dc`      | int?    | Save difficulty class (if any)       |
| `save_roll`    | int?    | Raw d20 roll (if any)                |
| `save_total`   | int?    | Total after modifiers (if any)       |
| `save_success` | bool    | Whether the save/check succeeded     |
| `damage_expr`  | string? | Damage expression that was applied   |
| `damage`       | int     | Damage actually dealt by the effect  |
| `damage_type`  | string? | Value of the effect's `tag`, if any  |

---

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
