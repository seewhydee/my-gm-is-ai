# Module Corpus Schema

The Module Corpus is the read-only canonical adventure content — the
equivalent of a printed D&D adventure module, containing descriptions
of game logic, rooms, entities, encounters, win/loss conditions, etc.

The Context Assembler reads from it to build the GMBriefing. The
Engine reads from it to validate actions and apply game mechanics.

## Top-Level Structure

```json
{
  "adventure":    { /* metadata */ },
  "rooms":        { "<room_id>": { /* room */ } },
  "entities":     { "<entity_id>": { /* entity */ } },
  "mechanics":    { "<mechanic_id>": { /* mechanic */ } },
  "stats":        { /* stat definitions (optional) */ },
  "flags_declared": [ "<flag_id>", ... ]
}
```

### `adventure` — Metadata block

| Field            | Type   | Description                        |
|------------------|--------|------------------------------------|
| `id` (*)         | string | snake_case id for save/load check. |
| `title`          | string | Display title of the adventure.    |
| `credits` (*)    | object | `{ author, source, license }`.     |
| `introduction`   | string | Opening narration read to player.  |
| `atmosphere` (*) | object | `{ setting, tone }` of adventure.  |
> (*) optional

---

## Common Primitives

Here we define types used in multiple parts of the corpus schema.

### Condition

A condition object describes a predicate clause gating availability:
whether an exit is shown, a mechanic can be triggered, etc.  They are
formed from condition strings and, optionally, condition objects
(allowing for nested logic).  There are several forms:

**`require`** — availability requires condition string to be true.

```json
{ "require": "flag:volcano_erupting == true" }
```

**`unless`** — availability requires condition string to not be true.

```json
{ "unless": "flag:volcano_erupting == true" }
```

**`any`** — availability requires at least one sub-condition to be
true; each sub-condition is a condition string or nested condition.

```json
{ "any": [ "flag:volcano_erupting == true",
		   { "all": [ "entity:frodo.alive",
					  "entity:frodo.attitude >= 4" ] } ] }
```

**`all`** — availability requires all sub-conditions to be true; each
sub-condition is a condition string or nested condition.

```json
{ "all": [ "flag:volcano_erupting == true",
		   { "unless": "inventory:one_ring" } ] }
```

#### Condition string

Condition strings have one of two forms:

- `<domain>:<key>` — presence-only check (allowed for `inventory`,
  `equipped`, `tag`, and `topic` domains).

- `<domain>:<key> <op> <value>` — compare to `<value>`. Supported:
  `== true`, `== false`, `== <string>`, `>= <number>`, `> <number>`,
  `<= <number>`, `< <number>`.

| Domain       | Key                                                 |
|--------------|-----------------------------------------------------|
| `flag`       | Global flag ID                                      |
| `inventory`  | Item entity ID in player's inventory                |
| `equipped`   | Item entity ID in player's equipped gear.           |
| `tag`        | Item with this tag in inventory/equipment           |
| `entity`     | Entity with named state field (e.g. `spider.alive`) |
| `room`       | Room with named state field (e.g. `parlor.visited`) |
| `topic`      | Topic ID of a topic discussed in current dialogue   |
| `stat`       | Stat name; value is the value of that player stat   |
| `event`      | Value in current event dispatch context (see below).|

Notes:

- The `equipped` domain also accepts tag names: `equipped:weapon`
  holds if any equipped item has tag `"weapon"`.
- An NPC's attitude is stored in `entity_states[<npc_id>].attitude` and
  accessed via `entity:<npc_id>.attitude` conditions, e.g.
  `entity:frodo.attitude >= 4`.  If the NPC has dialogue,
  `attitude_limits.initial` provides the default at game start; the
  corpus author should initialize all dialogue-NPC attitudes to this
  value in the hard-state JSON.
- The `event` domain is used in [Reaction dispatch](#reaction-object).
  It evaluates to `false` outside event dispatch.

**Examples**:
- `flag:daytime == true` holds iff the `daytime` flag is true.
- `inventory:rusty_key` holds iff item with entity ID `rusty_key` is
  in inventory; not satisfied if the item exists outside inventory.
- `topic:abandonment` holds iff the topic has been discussed in the
  current dialogue (`soft_state.dialogue_state.topics_discussed`)
- `stat:STR >= 5` holds iff player's current STR stat is >= 5.

---

### Check

A Check resolves the success or failure of an event or action:
interaction, traversal, encounter, etc.  There are two Check types:
`roll` (flat probability) and `stat_check` (stat-based resolution).
Either type of Check can be repeatable or not; if `repeatable` is
`false`, the engine tracks attempts and rejects repeats.

#### Roll Check

A roll Check succeeds if `random() < threshold`.

```json
{
  "type": "roll",
  "threshold": 0.50,
  "repeatable": false,
}
```

| Field        | Type    | Description                       |
|--------------|---------|-----------------------------------|
| `type`       | string  | `"roll"` — flat probability check |
| `threshold`  | number  | Probability threshold (0.0–1.0)   |
| `repeatable` | boolean | Whether check can be retried      |
| `note` (*)   | string  | Explanatory designer note         |
> (*) optional

#### Stat Check

Stat Checks are [resolution system](#resolution-system) dependent.

```json
{
  "type": "stat_check",
  "stat": "STR",
  "target": 12,
  "advantage": true,
  "repeatable": false,
}
```

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `type`         | string  | `"stat_check"` — stat-based check |
| `stat`         | string  | Stat key (e.g. `"STR"`, `"DEX"`)  |
| `target`       | integer | Check target or difficulty class  |
| `modifier` (*) | integer | Situational modifier (default 0)  |
| `repeatable`   | boolean | Whether check can be retried      |
| `note` (*)     | string  | Explanatory designer note         |
> (*) optional

Aside from the above fields, system-specific fields are accepted as
extra top-level keys.  Various systems can implement their own checks
and define their own extra fields.

The `5e` system uses roll(1d20) + (stat-10)//2 + modifier >= target as
the success formula, and supports these additional optional fields:

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `advantage`    | boolean | Roll 2d20 and keep the higher die |
| `disadvantage` | boolean | Roll 2d20 and keep the lower die  |

If both fields are `true`, they cancel out and a single d20 is rolled.

---

### Result

A Result describes the consequences of an action — narrative, state
mutations, stat adjustments, inventory changes, and optional follow-up
checks. Results can appear either deterministically, or in `success`
and `failure` branches of non-deterministic game mechanics.

```json
{
  "narrative": "Looting the troll, you find a helmet and a dagger, probably taken from some hapless adventurer",
  "add_item": [ "helmet", "enchanted_dagger" ],
  "set_flag": { "old_gear_found" : true },
  "set_entity_state": { "troll": { "looted" : true } },
  "reveals": "Found gear belonging to another adventurer on a troll.",
}
```

ALL fields in a Result object are optional.

| Field             | Type     | Description                           |
|-------------------|----------|---------------------------------------|
| `narrative`       | string   | Narrative description of the result   |
| `add_item`        | string[] | Item entity IDs to add to inventory   |
| `remove_item`     | string[] | Item entity IDs to drop from inventory|
| `set_flag`        | object   | Hard-state flags to set or clear      |
| `set_entity_state`| object   | Entity state changes                  |
| `set_room_state`  | object   | Room state changes                    |
| `player_damage`   | string   | Damage dealt to player, e.g. `"1d4+1"`|
| `set_player_location`| string| Room ID to relocate the player to     |
| `alter_stat`      | object   | Player stat changes (see below)       |
| `adjust_attitude` | object   | NPC attitude changes (see below)      |
| `reveals`         | string   | Player's knowledge update (see below) |
| `then_check`      | object   | A follow-up check (see below)         |

Notes:

- All supplied fields in the Result object are applied.  They are
  *not* mutually exclusive; one Result can deal damage, set multiple
  flags, alter multiple state fields, add/drop multiple items, etc.

- `narrative` helps brief the GM, but might not be used verbatim.

- During a check, `check.passed`/`check.failed` events (and their
  immediate reactions) fire before applying success/failure results.
  The effects are accumulated into a batch, and processed before any
  follow-up `then_check` resolves.  See [Reaction](#reaction).

- At engine level, action-result changes and immediate-reaction
  changes are merged and applied atomically.  Deferred reactions
  (`room.entered`, `turn.end`, etc.) fire after and see the new state.

- For `alter_stat`, the keys are stat abbreviations; values are
  `{ "mode": "delta"\|"set", "value": <int> }`, with mode defaulting
  to `"delta"` (i.e., the amount by which to change).  Examples:
  - `{ "STR": { "value": -4 } }` decreases strength by 4
  - `{ "INT": { "mode": "set", "value": 3 } }` sets intelligence to 3

- For `adjust_attitude`, keys are NPC entity IDs; values are integer
  deltas (positive or negative).  The engine clamps the new value to
  the NPC's `attitude_limits.[min, max]` and respects `step_per_turn`.
  See [NPC attitude](#npc-attitude).

- `reveals` is a player-knowledge hint.  If present, the engine
  appends it to `soft_state.revealed_hints` (with deduplication) to
  guide the GM; see the [Soft State schema](soft-state.md).

#### Follow-up check

A follow-up check can be embedded in a Result's `then_check` field.
It implements multi-stage resolutions for actions and effects, firing
right after its parent result with its own success/failure branches.

**Example**: player makes a STR check to jump across a pit, and on
failure makes a DEX check to grab the ledge.

```json
{
  "then_check": {
    "check": {
      "type": "stat_check",
      "stat": "DEX",
      "target": 8,
      "repeatable": true
    },
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
```

| Field             | Type      | Description                      |
|-------------------|-----------|----------------------------------|
| `check`           | Check     | Follow-up Check to resolve       |
| `skip_check_if`(*)| Condition | If present and true, skip check  |
| `success`         | Result    | Result if follow-up succeeds     |
| `failure` (*)     | Result    | Result if follow-up fails        |
> (*) optional

Nested follow-ups are supported — a follow-up check's success/failure
results may contain other follow-ups, to a maximum depth of 3.

---

### Gated Check

A Gated Check wraps a [Check](#check) with a condition determining
whether the check is active, an optional bypass condition, and
success/failure [Results](#result).  It is meant for situations where
a player action meets a special obstacle (specifically, `take_check`
for items and `traversal_check` for room exits).

```json
{
  "gating": { "require": "flag:ladder_missing == true" },
  "check": {
    "type": "stat_check",
    "stat": "STR",
    "target": 13,
    "repeatable": true
  },
  "skip_check_if": { "require": "inventory:spring_boots" },
  "failure": {
    "narrative": "You try to climb up the wall, but can't make progress."
  },
  "success": {
    "narrative": "You manage to move up the wall."
  },
  "using_results": {
    "grappling_hook": {
      "check": { "type": "stat_check", "stat": "STR", "target": 8,
                 "repeatable": true }
    }
  }
}
```

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `gating` (*)      | Condition | Whether the check is active          |
| `check`           | Check     | The Check to resolve (required)      |
| `skip_check_if`(*)| Condition | If present and true, bypass check    |
| `success` (*)     | Result    | Result if check succeeds or bypassed |
| `failure` (*)     | Result    | Result if check fails                |
| `using_results`(*)| object    | See [Usage Override](#usage-override)|
> (*) optional

Note: if `gating` evaluates to false, the check is inactive and the
action proceeds as default; neither the `success` nor `failure` Result
is applied.  If `gating` evaluates to true (or is absent) and
`skip_check_if` evaluates to true, the check is bypassed and `success`
is applied.  Otherwise the check is rolled normally.

`using_results`, if present, is a set of [Usage Overrides](#usage-override).

---

### Resolvable

A Resolvable is a condition-gated action that resolves to a Result.
It is used to describe special interactions with [Rooms](#room) and
[Entities](#entity), [Examination Effects](#examination), and NPC
[Dialogue Paths](#dialogue-path).

```json
{
  "id": "string (optional unless subclass requires it)",
  "description": "string (optional unless subclass requires it)",
  "condition": { /* condition object (optional) */ },
  "skip_check_if": { /* condition object (optional) */ },
  "check": { /* roll or stat_check (optional) */ },
  "success": { /* result (required if check is present) */ },
  "failure": { /* result (optional) */ },
  "result": { /* deterministic result (optional, mutually exclusive with check) */ },
  "using_results": { /* item ID -> override (optional) */ }
}
```

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `id` (*)          | string    | ID (depends on context)              |
| `description` (*) | string    | Human-readable description of action |
| `condition` (*)   | Condition | Availability gate for the action     |
| `skip_check_if`(*)| Condition | Whether to bypass check and succeed  |
| `check` (*)       | Check     | Check to resolve result              |
| `success` (*)     | Result    | Result when check succeeds/bypassed  |
| `failure` (*)     | Result    | Result when check fails              |
| `result` (*)      | Result    | Deterministic result                 |
| `using_results`(*)| object    | See [Usage Override](#usage-override)|
> (*) optional by default (may be required in some contexts)

Notes:

- The meaning of `id` depends on where the Resolvable is used.  For
  room and entity interactions, it must be a room-unique or
  entity-unique ID.  In other contexts, it need not be specified.

- `description` is used to brief the GM on the semantic meaning of the
  action.  It may be omitted for Examination Effects.

- `condition`, if supplied, gates availability; if it evaluates to
  `false`, the action is unavailable (e.g., a room/entity interaction
  will not be offered as a player action).

- The action itself should be specified by one of:
  - a deterministic `result`, OR
  - a probabilistic `check`, with optional `skip_check_if` to bypass
    (evaluating to `true` means auto-success), along with `success`
    (required) and `failure` (optional) Results.

- `using_results`, if present, is a set of [Usage Overrides](#usage-override).

---

### Usage Override

A Usage Override object can be placed in the optional `using_results`
field of a Gated Check or Resolvable.  It accommodates player commands
of the form "[ACTION] using [ITEM]".  It should be a dict mapping item
[entity IDs](#entity) to one of the following resolution paths:

- a dict with `"result"` keyed to a fixed [Result](#result); OR

- a dict with `check`, `success`, and `failure` (optional), defining
  an alternative [Check](#check),

This overrides the usual resolution when using the specified item.

---

## Room

A room is a location in the adventure module, modeled as a node in a
world graph keyed by a globally-unique `room_id`.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when player enters or examines room)",
    "contains": ["<entity_id>", ...],
    "soft_items": ["string", ...],
    "exits": [ { /* exit */ } ],
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "is_start_room": false,
    "reactions": [ { /* reaction */ } ],
    "state_fields": { "<field_name>": { "type": "boolean|number|string", "description": "string", "initial": <value> } }
  }
}
```

| Field               | Type     | Description                         |
|---------------------|----------|-------------------------------------|
| `name`              | string   | Short display name                  |
| `description`       | string   | Prose description of room           |
| `contains`(*)       | string[] | Entities directly present at start  |
| `exits` (*)         | array    | All exits out of the room           |
| `state_fields` (*)  | object   | State fields for room (see below)   |
| `interactions` (*)  | Resolvable[] | Special interactions (see below)|
| `on_examine` (*)    | array    | See [Examination](#examination)     |
| `reactions` (*)     | array    | See [Reaction](#reaction)           |
| `soft_items` (*)    | string[] | Plausible generic items in the room |
| `is_start_room` (*) | boolean  | `true` for starting room (only one) |
> (*) optional

Notes:

- The `name` string is used as the in-game UI label for the room,
  whereas `description` briefs the GM on the characteristics of the
  room (NOT necessarily used verbatim in narration).

- The `contains` field lists the IDs of entities DIRECTLY present in
  the room at game start.  Note: if entity A is in room R, and entity
  B is in entity A (see `contains`, [Entity](#entity)), only A is
  directly present; room R's `contains` lists A but not B.

  The player must not be included (even for the starting room).

- The `exits` field stores an array of [Exit](#exit) objects, one for
  EVERY possible exit regardless of initial availability / visibility.
  Each exit can be individually gated and/or hidden.

- State fields have room-unique IDs (dict keys).  They can be freely
  chosen by the corpus author, except for two reserved engine-managed
  state fields (neither of which has to be declared):

  - `visited` is set to `true` when the player enters a room.

  - `is_current` is true only for the player's current room.
    This is auto-computed.  Do not move the player by changing this;
    use `set_player_location` in a Result instead.

- Each author-defined state field may include an optional `initial`
  value (matching the field's `type`), specifying the value at game
  start.  If omitted, the type default applies (`false`, `0`, `""`).

- `interactions` is an array of [Resolvables](#resolvable) describing
  operations performable on the room.  For each Resolvable,

  - `id` must be room-unique, and should not be the reserved ID
    `attack`, or the generic actions `move`, `examine`, `talk`,
    `transfer`, or `wait`, or similar generic verbs (e.g., `take`).

  - `description` is required, and should describe the semantic
    meaning of the interaction; it is used to brief the GM on the
    semantic meaning of the interaction.

  - If `failure` is unspecified, a failed check sends a generic
    "nothing happens" message to the GM narrator.

- Soft objects examples: `["rock", "loose stone", "dust"]`). These are
  identified by their general name only — they carry no unique item
  ID. The engine tracks them in `soft_inventory` when picked up.

### Exit

```json
{
  "id": "string (unique across all exits in the room)",
  "direction": "string (natural-language label, e.g. 'Climb carefully down the axe handle')",
  "target_room": "<room_id>",
  "condition": { /* condition (optional) */ },
  "traversal_check": { /* traversal check (optional) */ },
  "one_way": false
}
```

| Field               | Type        | Description                      |
|---------------------|-------------|----------------------------------|
| `id`                | string      | Exit ID (room-unique)            |
| `direction`         | string      | Human-readable exit label        |
| `target_room`       | string      | Room ID of destination           |
| `condition` (*)     | Condition   | Gating condition (see below)     |
| `traversal_check`(*)| Gated Check | See [Gated Check](#gated-check)  |
| `one_way` (*)       | boolean     | Indicates if exit is one-way     |
> (*) optional

Notes:

- `direction` is used verbatim when the engine lists available exits
  after a room description.  Style convention: one phrase, capitalize,
  no full stop.  Different exits should be sufficiently distinctive.

- `condition`, if present, is a gating Condition for the availability
  of the exit.  An unavailable Exit is not shown to the player or GM.

- `traversal_check`, if present, gates traversal.  Success and failure
  have the automatic side-effects of moving to the destination Room,
  and canceling the traversal, respectively.  The `using_results`
  field accommodates commands of the form "[USE EXIT] using [ITEM]".

- The `one_way` field is only used to indicate to the player that an
  exit *seems* one-way (e.g., a trapdoor).  No gameplay effects.

---

## Examination

Each Room and Entity has an optional `on_examine` field that takes an
**array** of [Resolvables](#resolvable), describing possible
examination outcomes.  When the player performs an examine action, all
eligible Resolvables run in array order.

The player can opt between ordinary (cursory) examination, which does
not consume a turn, and rigorous examination, which costs a turn.  To
account for this, the Resolvables in `on_examine` add an extra field,
`rigorous_only` (boolean, default `false`).  Resolvables with
`rigorous_only` *only* activate under rigorous examination; rigorous
examinations *can* activate cursory-examination Resolvables.

```json
{
  "id": "string (unique within the entity or room)",
  "condition": { "require": "inventory:magic_lens" },
  "skip_check_if": { "require": "flag:lore_master" },
  "rigorous_only": true,
  "check": {
    "type": "stat_check",
    "stat": "INT",
    "target": 10,
    "repeatable": true
  },
  "success": {
    "narrative": "You deduce that the runes warn of a demon",
    "set_flag": { "demon_warning_found": true },
    "reveals": "A demon is present in the dungeon"
  },
  "failure": {
	"narrative": "You can't decipher the runes"
  }
}
```

Extra field for Resolvables in `on_examine`:

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `rigorous_only`   | boolean   | Whether rigorous search is needed    |

Notes:

- To form the narration for what the examination reveals, the GM looks
  at the `narrative` in the [Result](#result) delivered by the
  Resolvable.  The Result can also impose other side-effects, such as
  setting flags to track the player's information.

- `id`, `description`, and `using_results` need not be supplied, and
  their effects on examination actions are undefined.

## Reaction

Reactions are a flexible mechanism to change game state in response to
specified events.  They can be placed in the `reactions` array of a
[Room](#room), [Entity](#entity), or [Mechanic](#mechanic) – the
**scope** of the reaction.

The scope determines when the reaction is active (i.e., can be
triggered).  Room-scoped reactions are active when the player is in
the room; entity-scoped reactions are active when the entity is in the
present room *and* (for NPCs) alive and not fled; mechanic-scope
reactions are always active.

```json
{
  "id": "string (unique within the defining context)",
  "on": "event type string",
  "condition": { /* condition object or null */ },
  "effect": { /* reaction effect */ },
  "once": false,
  "priority": 0,
  "phase": "deferred"
}
```

| Field       | Type     | Description                                |
|-------------|----------|--------------------------------------------|
| `id`        | string   | ID, unique in scope (room/entity/mechanic) |
| `on`        | string   | Reaction trigger; see [Event](#event)      |
| `condition` (*) | Condition | Gating condition (see below)          |
| `effect`    | object   | See [Reaction Effect](#reaction-effect)    |
| `once` (*)  | boolean  | Whether reaction is one-off; default false |
| `phase`(*)  | string   | `"deferred"` (default) or `"immediate"`    |
| `priority`(*)| integer | Lower values fire earlier; default `0`     |
> (*) optional

Notes:

- `id` is used for debugging and tracking one-off reactions (those
  with `once` true).  As this tracking is global, one-off reactions
  MUST have globally-unique IDs.  Other reactions need only be unique
  within their scope (room, entity, or mechanics).

- `condition`, if provided, determines whether the reaction fires when
  triggered.  If it evaluates to false, the reaction is canceled; this
  does not count toward a one-off reaction's single charge.  If it is
  omitted (`null`), the reaction always fires when triggered.

- The `phase` and `priority` fields determine when a reaction fires.
  Typically, reactions have `phase:"deferred"` (the default), meaning
  they fire after the current action finishes.  But reactions with
  `phase:"immediate"` fire before the action continues; this is only
  allowed for four types of trigger events:
  - `interaction.used`
  - `traversal.attempted`
  - `traversal.succeeded`
  - `room.entered`.
  Within each phase, the `priority` field sets the firing sequence
  (lower numbers go first).

### Event

The event that fires a reaction is determined by two objects:

- The **Trigger String** (the `on` field) – this, together with the
  Reaction's scope (room/entity/mechanic) sets the initial trigger.

  For example, suppose a Reaction K has `"on": "room.entered"`.  If K
  is in a room R, the trigger is the player entering R.  If K is in an
  entity E, the trigger is the player entering any room where E is
  directly present (see [Room](#room)).

- The **Event Context** – a flat dict of details about the event.  For
  example, a `"room.entered"` trigger provides the context key
  `room_id`: the ID of the room entered.

  The Event Context can be accessed by Condition blocks in the
  Reaction using the `event` [Condition String](#condition-string)
  domain (this domain is only valid during reaction dispatch).  This
  allows (say) a `condition` to narrow down when the reaction fires.

**Example**: a goblin NPC attacks on sight, but only in a given room.

```json
{
  "id": "goblin_attack_on_sight",
  "on": "room.entered",
  "condition": { "require": "event:room_id == camp" },
  "phase": "immediate",
  "effect": { "trigger_encounter": "self" }
}
```

Below is an abridged list of commonly-used Trigger Strings, and their
associated Event Context keys.  Keys marked with `?` are optional (may
be omitted if the event lacks that particular detail).

| Trigger                | Context                                     |
|------------------------|---------------------------------------------|
| `room.[entered\|exited]`| `room_id`                                  |
| `traversal.[attempted\|succeeded]` | `exit_id`, `from_room`, `to_room`|
| `traversal.failed`     | `exit_id`, `from_room`, `fail_reason`       |
| `interaction.used`     | `interaction_id`, `target_id`, `using_item?`|
| `flag.[set\|cleared]`  | `flag_id`                                   |
| `entity_state.changed` | `entity_id`, `field`, `new_value`           |
| `room_state.changed`   | `room_id`, `field`, `new_value`             |
| `dialogue.[started\|ended]` | `npc_id`, `reason?`                    |
| `combat.started`       | `combatant_ids`                             |
| `combat.ended`         | `reason` (`victory\|defeat\|fled`)          |
| `item.acquired`        | `item_id`, `source`                         |
| `item.lost`            | `item_id`, `reason`                         |
| `equipment.changed`    | `added?`, `removed?`                        |
| `attitude.changed`     | `npc_id`, `old_value`, `new_value`, `delta` |
| `stat.changed`         | `stat_name`,`old_value`,`new_value`,`delta` |
| `player.[damaged\|healed]` | `amount`, `new_hp`                      |
| `encounter.branched`   | `encounter_id`, `branch`                    |
| `turn.[start\|end]`     | `turn_number`                              |

For the full list, and full documentation of the context keys, see the
[Events schema doc](events.md).

### Reaction Effect

A Reaction Effect object is stored in a reaction's `effect` field, and
describes what the reaction does if successfully triggered:

```json
{
  "result": { /* Result object (same as interaction results) */ },
  "trigger_encounter": "<mechanic_id or entity_id>",
  "trigger_dialogue": "<npc_entity_id>",
  "game_over": { "type": "win|lose", "trigger_id": "string" }
}
```

The Reaction Effect must contain at least one of the following fields
(if more than one is supplied, they all apply):

| Field               | Type     | Description                         |
|---------------------|----------|-------------------------------------|
| `result`            | Result   | A [Result](#result) to run          |
| `trigger_encounter` | string   | Mechanic or entity ID               |
| `trigger_dialogue`  | string   | NPC entity ID to start dialogue     |
| `game_over`         | Game-Over| A [Game-Over](#game-over) condition |

Notes:

- For `trigger_[encounter|dialogue]`, the `"self"` value resolves to
  the owning entity's ID (for entity-scoped reactions).

**Example**: trap fires if it's armed when the player enters the room.

```json
{
  "id": "entrance_trap_fires",
  "on": "room.entered",
  "condition": { "require": "flag:trap_armed == true" },
  "phase": "immediate",
  "priority": 10,
  "once": true,
  "effect": {
    "result": {
	  "narrative": "A pressure plate clicks underfoot; darts fly from the walls!",
      "player_damage": "2d4",
      "set_flag": { "trap_sprung": true },
      "set_room_state": { "antechamber": { "dart_trap_triggered": true } },
      "reveals": "The dart trap in the antechamber was triggered"
    }
  }
}
```

---

## Entity

Entities are unique objects that appear in rooms or inventory.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | item",
    "name": "string (required for item, optional otherwise)",
    "description": "string",
    "soft_items": ["string", ...],
    "contains": ["<entity_id>", ...],
    "tags": ["<tag>", ...],
    "take_check": { /* Gated Check (optional) */ },
    "equip_block": { /* equip_block */ },
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "reactions": [ { /* reaction */ } ],
    "dialogue": { /* only for npc type */ },
    "aggro": { /* only for npc (monster) type */ },
    "state_fields": { "<field_name>": { "type": "boolean | number | string", "description": "string", "initial": <value> } },
    "follower": { /* only for npc type */ }
  }
}
```

The following fields are meaningful for all entity types:

| Field              | Type     | Description                          |
|--------------------|----------|--------------------------------------|
| `type`             | enum     | `player|feature|npc|item`            |
| `description`      | string   | Canonical prose description          |
| `tags` (*)         | string[] | Array of semantic tags               |
| `contains`(*)      | string[] | IDs of entities inside this entity   |
| `interactions` (*) | Resolvable[] | Special interactions (see below) |
| `on_examine` (*)   | array    | See [Examination](#examination)      |
| `reactions` (*)    | array    | See [Reaction](#reaction)            |
| `state_fields` (*) | object   | State fields for entity (see below)  |
| `soft_items` (*)   | array    | Plausible soft items on/in entity    |
> (*) optional

Notes:

- NPCs, features, and items each support additional fields, documented
  in the following subsections.

- `tags`, if provided, contains semantic tags that can be accessed via
  `tag:<value>` in [Condition strings](#condition-string).  They are
  distinct from [Equipment Tags](#equipment).

  The special `"container"` tag should be placed on entities that act
  as [containers](#container) with open/close functionality.

- State fields have entity-unique IDs.  There are two types:

  **Reserved state fields** are managed by the engine and never need
  to be declared in `state_fields`:

  | Field        | Type    | Purpose                                   |
  |--------------|---------|-------------------------------------------|
  | `alive`      | boolean | NPC active? (false => reactions inactive) |
  | `fled`       | boolean | NPC fled? (false => reactions inactive)   |
  | `attitude`   | integer | NPC disposition (higher == friendlier)    |
  | `hidden`     | boolean | Explicit concealment (see below)          |
  | `following`  | boolean | NPC follows player between rooms          |
  | `current_hp` | number  | Current hit points (for combat)           |
  | `open`       | boolean | Container open/closed state               |

  **Author-defined state fields** must be declared in `state_fields`.
  Examples: `looted`, `activated`, `cursed`.  Each must have a `type`
  (`"boolean"`, `"number"`, or `"string"`), a `description` string,
  and an optional `initial` value at game start.

  The reserved state field `hidden` declares explicit concealment
  (e.g., a lurking enemy, or a sword buried in rubble). When `true`,
  the engine omits the entity (even from the GM, to avoid leakage).
  DO NOT use `hidden` for entities that are merely inside a closed
  [container](#container); that kind of concealment is controlled by
  the container's `open` state.

- `interactions` is an array of [Resolvables](#resolvable) listing
  non-generic operations performable on the entity.  Each must have an
  entity-unique `id`.  The rest of the spec is the same as for
  [Room](#room) interactions.

### Feature

Features describe immovable environmental objects.  The player cannot
pick up, talk to, or attack features.

Features, unlike NPC and item entities, may span multiple rooms: e.g.,
the sky can be a single feature visible from different locations.
Just list the feature's entity ID in the `contains` field of each room
where it appears.

#### Container

**Containers** are entities such as chests or wardrobes, which store
other entities and can be opened and/or closed.  We document
containers here since they are commonly implemented as features, but
items (or even NPCs) are also allowed to be containers.

Containers should be assigned the following properties:

- `container` tag — A container must have `"container"` in its `tag`
  array.  This informs the engine to handle them specially.

- `open` state field — A container must have `open` as a boolean state
  field, initialized to `true` (open) or `false` (closed).  For
  entities without the `container` tag, `open` has no special meaning.

- `open` and `close` interactions (optional) — should be defined if
  the player can perform direct open/close actions (as opposed to
  indirect methods, like pressing a button elsewhere).

A container's contents are listed in its `contains` and `soft_items`
fields.  (These fields can also be used for non-container entities,
like a rubbish pile, which is not a container in the present sense
since it lacks open/close functionality.)

When the container is open, the engine automatically surfaces its
contents to the GM and player; when the container is closed, the
contents are inaccessible.  This is distinct from the `hidden` state.

### Item

Items are entities that can potentially be picked up by the player.
The player cannot talk to or attack items.  The following fields have
special meanings for items:

| Field              | Type        | Description                     |
|--------------------|-------------|---------------------------------|
| `name`             | string      | Display name (required!)        |
| `take_check` (*)   | Gated Check | See [Gated Check](#gated-check) |
| `equip_block` (*)  | object      | For equipment (see below)       |
> (*) optional

Notes:

- `name` is required for items; it's shown in the inventory UI.

- `take_check`, if present, is a [Gated Check](#gated-check) for
  taking the item (e.g., pulling a sword from a stone).  Success and
  failure have the side-effects of adding the item to the player's
  inventory, and preventing the item from being taken, respectively;
  no need to specify `add_item` explicitly in `success`/`failure`.

  The check is *not* automatically disabled after a successful take.
  For a one-time success gate (pass once, then freely take
  thereafter), use `gating` with a flag on `success`.

#### Equipment

**Equipment** refers to item that can be equipped – worn, wielded,
etc.  An item is equipment if its `equip_block` contains an Equip
Block object, which specifies the parameters of the equipment:

```json
{
  "equip_tags": ["weapon"],
  "incompatible_with": ["shield"],
  "stat_effects": { "STR": { "mode": "delta", "value": 1 } },
  "max_equipped": 1,
  "damage_expr": "1d8",
  "hit_bonus": 0
}
```

| Field                 | Type     | Description                       |
|-----------------------|----------|-----------------------------------|
| `equip_tags`          | string[] | Category tags (see below)         |
| `incompatible_with`(*)| string[] | Conflicting tags (see below)      |
| `stat_effects` (*)    | object   | Stat modifiers while equipped     |
| `max_equipped` (*)    | integer  | How many such items can stack     |
| `damage_expr` (*)     | string   | Weapon damage, e.g. `"1d8+1"`     |
| `hit_bonus` (*)       | integer  | Weapon attack bonus               |

Notes:

- Aside from the above fields, extra top-level keys are accepted.
  Systems can attach their own mechanics through these extra fields;
  the extra fields for `5e` are listed below.

- `equip_tags` implements a tag-based equipment system.  The first
  element defines the **slot**, which controls compatibility (items in
  the same slot can conflict).  The remaining tags provide more
  context: e.g. `["armor", "heavy"]`.

  Common equipment tags include: `"weapon"`, `"shield"`, `"armor"`,
  `"ring"`, `"headwear"`, `"handwear"`, `"boots"`, `"two_handed"`.

  Unlike the semantic `tags` in the [Entity](#entity) block, equipment
  tags only describe the item's features **as equipment**.  Only items
  with the `"weapon"` equipment tag can be wielded as weapons.

- `incompatible_with`, if supplied, lists equipment tags conflicting
  with the item.  When equipping, the engine checks already-equipped
  items: if any of their tags intersects this list, the equip is
  rejected.  The default (empty) means the item conflicts with
  anything in the same slot (e.g., can't wear two helmets).

  For two-handed weapons, `"equip_tags": ["two_handed"]` can be paired
  with (say) `"incompatible_with": ["shield", "handwear"]`.

- `stat_effects` stores stat changes applied while the item is
  equipped, in the form `{stat_key: {mode, value}}`.  Any `"set"`
  modifiers apply first, then `"delta"`.

- `max_equipped` defaults to 1; other values can be chosen for, say,
  rings.  The engine uses the highest value among items in the same slot.

The `5e` system uses these additional fields, both optional:

| Field         | Type    | Description                                |
|---------------|---------|--------------------------------------------|
| `ac_override` | integer | Sets AC to this value; highest takes effect|
| `ac_bonus`    | integer | Added to base AC (default 0); stacks       |

### NPC

NPCs are entities the player can fight or socialize with.  NPC entity
blocks support the following additional fields:

| Field           | Type   | Description                      |
|-----------------|--------|----------------------------------|
| `dialogue`(*)   | object | See [Dialogue](#dialogue)        |
| `aggro` (*)     | object | See [Aggro](#aggro)              |
| `follower` (*)  | object | See [Follower](#follower)        |
| `combat` (*)    | object | Combat stats (hp, ac, atk, etc.) |
> (*) optional

#### Dialogue

The Dialogue object specifies how the NPC engages in conversation.

```json
{
  "guidelines": "The Jester speaks in riddles, puns, and jibes. He gamely offers himself as the butt of jokes. Yet he's smarter than he looks, and knows much about the goings-on at court. He is fundamentally loyal to the King and will never agree to betray him.",
  "on_encounter": "The Jester hoots when he sees the player, waving and laughing hysterically",
  "attitude_limits": {
    "min": -5,
    "max": 10,
    "step_per_turn": 2,
    "initial": 0
  },
  "will_reveal": {
    "vizier_is_lich": {
      "description": "The jester shares that the vizier is a lich",
      "conditions": [ "entity:jester.attitude >= 5" ],
      "set_flag": { "vizier_secret_revealed": true }
    }
  },
}
```

| Field              | Type     | Description                          |
|--------------------|----------|--------------------------------------|
| `guidelines`       | string   | Tone, demeanor, constraints, etc.    |
| `attitude_limits`(*)| object  | NPC's attitude bounds (see below)    |
| `on_encounter`(*)  | string   | Describes behavior on first meeting  |
| `will_reveal` (*)  | object   | See [NPC Knowledge](#npc-knowledge)  |
| `dialogue_paths`(*)| Resolvable[] | See [Dialogue Path](#dialogue-path) |
> (*) optional

Notes:

- `guidelines` is a freeform prose string used to inform the GM on how
  the NPC should act in conversation: tone, demeanor, what they know,
  what they will and will not agree to, what bits of knowledge they do
  and do not know, etc.

- `on_encounter`, if present, describes the NPC's canonical reaction
  when first encountered.  The GM should not contradict this, but
  might not use it verbatim.

- `attitude_limits`, if present, sets the NPC's engine-enforced
  attitude limits.  All fields are optional.  Defaults: `min: 0`,
  `max: 0`, `initial: 0`, `step_per_turn: 1`.

  Example: a troll whose hostility can vary, but never turns friendly:
  `"attitude_limits": { "min": -10, "max": -1 }`.

#### Dialogue Path

A Dialogue Path is any special line of conversation that can trigger
mechanical effects.  It is modeled as a [Resolvable](#resolvable) with
a required `description` field.  The `id` should be entity-unique.

```json
{
  "convince_orc_dead": {
    "description": "convince the King the orc has been dealt with",
    "condition": { "require": "entity:orc.alive == false" },
    "check": {
      "type": "stat_check",
      "stat": "CHA",
      "target": 12,
      "repeatable": false
    },
    "skip_check_if": { "require": "inventory:orc_head" },
    "result": {
	  "narrative" : "The King is overjoyed and gives the player a magic shield",
	  "add_item": [ "magic_shield" ],
	  "adjust_attitude": { "king": 3 }
    }
  }
}
```

When the player converses with the NPC, the GM uses the Resolvable's
`description` to decide if the player's dialogue should trigger the
Dialogue Path.  The other fields specify the mechanics: gating
condition, check, and/or branching outcomes.

#### NPC Knowledge

The `will_reveal` field describes discrete pieces of knowledge an NPC
can share with the player.  It should be a dict keyed by topic IDs
(entity-unique), with value objects having following fields:

| Field          | Type     | Description                              |
|----------------|----------|------------------------------------------|
| `description`  | string   | What the topic reveals; surfaced to GM   |
| `conditions`   | string[] | Revelation conditions (all must be true) |
| `set_flag` (*) | object   | Flag mutations when topic revealed       |
| `set_entity_state` (*) | object| State mutations when topic revealed |
> (*) optional

When a topic's conditions are met, the engine marks it as available
and surfaces it to the GM, which can decide to narrate the revelation
(or not, depending on the flow of conversation).

Once the revelation occurs and is validated, the engine applies any
side effects specified by `set_flag` and `set_entity_state`, which use
the same format as in [Result](#result) objects.  The engine also
records the topic as already revealed, so it doesn't get repeated.

```json
"will_reveal": {
  "vizier_is_lich": {
    "description": "The jester shares that the vizier is a lich",
    "conditions": [ "entity:jester.attitude >= 5" ],
    "set_flag": { "vizier_secret_revealed": true }
  }
}
```

### Aggro

The `aggro` field is an ordered list of Encounter Rules defining how
an NPC reacts in hostile encounters (player attack, or combat
triggered by a reaction).

```json
"aggro": [
  {
    "condition": { "require": "tag:weapon" },
    "check": { "type": "stat_check",
               "stat": "STR", "target": 17, "repeatable": true },
    "success": { "narrative": "You drove it off." },
    "failure": { "narrative": "It overpowers you.",
                 "game_over": { "type": "lose", "trigger_id": "creature" } }
  },
  {
    "condition": { "require": "true" },
    "result": {
      "narrative": "Without a weapon, you are helpless against the creature.",
      "game_over": { "type": "lose", "trigger_id": "creature" }
    }
  }
]
```

Each Encounter Rule supports the following fields:

| Field           | Type          | Description                        |
|-----------------|---------------|------------------------------------|
| `condition`     | object        | Condition for the rule to fire     |
| `result` (*)    | Result        | Direct result (use exactly one of `result` or `check`) |
| `check` (*)     | CheckType     | `RollCheck` or `StatCheck` (use exactly one of `result` or `check`) |
| `success` (*)   | Result        | Result when check succeeds         |
| `failure` (*)   | Result        | Result when check fails            |
| `skip_check_if` (*)| object      | Condition to bypass the check and apply `success` directly |
> (*) optional

Notes:

- Rules are evaluated top-to-bottom. The first rule whose `condition`
  matches is applied.
- If no rule matches, the encounter silently does nothing (no narrative,
  no effects, no combat, no game-over).  To avoid this, include a
  catch-all rule with `"require": "true"` as the last entry.
- Each rule must have exactly one of `result` (direct) or `check`
  (probabilistic with `success`/`failure` branches).
- `Result` may contain `trigger_combat: true` to enter combat mode
  or `game_over` to end the game.

#### Follower

An NPC can carry an optional `follower` object to configure
follower-specific behavior:

```json
"follower": {
  "blacklist": ["<room_id>", ...]
}
```

| Field         | Type     | Description |
|---------------|----------|-------------|
| `blacklist`   | string[] | Room IDs this NPC refuses to enter when following the player. |

When `entity_states[<npc_id>].following` is `true` and the player moves
to a room in the blacklist, the engine clears `following` to `false`
and appends a note that the NPC stays behind.

#### NPC follower convention (`following` state field)

An NPC entity can be declared as a **follower** — a companion that moves with the
player between rooms. To enable this, include a boolean `following` field in the
NPC's `state_fields`:

```json
"state_fields": {
  "alive": { "type": "boolean", "initial": true, "description": "Whether this NPC is alive." },
  "attitude": { "type": "number", "initial": 0, "description": "Attitude toward the player, -10 to 10." },
  "following": { "type": "boolean", "description": "Whether this NPC follows the player between rooms." }
}
```

When `entity_states[<npc_id>].following` is `true`, the engine:

- Injects the NPC into the visible entity list for whatever room the player is in
  (both the GMBriefing and the EngineResult), so the LLM is always aware of them.
- Makes the NPC targetable for `examine`, `interact`, `talk`, and `transfer`
  actions regardless of room.
- Does not terminate dialogue when the player moves rooms — the follower remains
  in active conversation.
- Includes the follower in `will_reveal_readiness` and `npc_attitude_limits`
  blocks sent to LLM Call 2.

`following` defaults to `false` (not present in `entity_states`). Any interaction
result can set it to `true` via `set_entity_state` (e.g., after convincing the
NPC to join), and to `false` to dismiss the follower.

This convention is engine-level, not corpus-level — no new top-level fields or
schema changes are needed; any NPC that declares `following` in its
`state_fields` and has it set to `true` in `entity_states` will be treated as a
follower.

---

## Mechanic

Named mechanics are rules involving aspects of game state not tied to specific
rooms or entities. They are referenced by exits, interactions, and reactions.
Game-over conditions live here too.

A mechanic can be:
- A **game-over condition** (has `type`, `condition`, `trigger_id`)
- A **mechanic containing rules and/or reactions** — a named bundle
  of global rules that can contain encounter rules (`rules`),
  reactions (`reactions`), or both.  A mechanic with only reactions is
  simply a mechanic without encounter rules, not a distinct type.

At least one of `rules`, `type`+`condition`+`trigger_id`, or `reactions` must be present.

### Encounter

```json
{
  "<mechanic_id>": {
    "id": "string",
    "description": "string",
    "rules": [
      {
        "condition": { /* condition object */ },
        "result": { "narrative": "...", "set_flag": {}, "game_over": {} },
        "check": { "type": "stat_check", "stat": "STR", "target": 12, "repeatable": true },
        "success": { "narrative": "...", "set_flag": {}, "alter_stat": {}, "player_damage": "3d6" },
        "failure": { "narrative": "...", "set_flag": {}, "alter_stat": {}, "player_damage": "3d6", "game_over": {} }
      }
    ],
    "reactions": [ { /* reaction (optional) */ } ]
  }
}
```

Rules are evaluated top-to-bottom. The first rule whose `condition` matches is
applied.  If no rule matches, the encounter silently does nothing.
Each rule must have exactly one of `result` (direct) or `check`
(probabilistic with `success`/`failure` branches).

`alter_stat` and `player_damage` on a branch `Result` follow the same
modifier semantics as interaction results.  `trigger_combat: true` on a
firing `Result` starts the multi-round combat system.

Notes on encounters and reactions:

- Only one encounter can resolve per turn. If a reaction triggers an
  encounter and that encounter has already been triggered (from the
  resolver or from another reaction), the second `trigger_encounter`
  is silently ignored with a warning log.

- A reaction that fires during an encounter can trigger another
  encounter via `trigger_encounter`. The depth-5 recursion limit
  prevents infinite loops, but design reaction conditions carefully to
  avoid unintended chains.

### Game-Over

```json
{
  "<mechanic_id>": {
    "id": "string",
    "type": "win | lose",
    "description": "string",
    "condition": { /* condition object */ },
    "narrative": "string (canonical ending narration)",
    "trigger_id": "string (matches game_over.trigger in hard state)"
  }
}
```

| Field         | Type   | Description |
|---------------|--------|-------------|
| `id`          | string | Unique mechanic identifier. |
| `type`        | string | `"win"` or `"lose"`. |
| `description` | string | Human-readable description of what must happen. |
| `condition`   | Condition | Evaluated each turn (or when specific triggers fire). When true, `game_over` is set. Follows the condition object format. |
| `narrative`   | string | Canonical ending prose passed to LLM Call 2 via `triggered_narration`. |
| `trigger_id`  | string | Set as `game_over.trigger` in hard state; for debugging and save analysis. |

### Mechanic with reactions only

A mechanic that carries only `reactions` (no `type`, `rules`, or `trigger_id`)
is valid.  This is not a distinct structural type — it is simply a mechanic
without encounter rules.  Use this for adventure-wide state-based reactions
that don't need encounter rules and aren't tied to a specific room or entity.

```json
{
  "<mechanic_id>": {
    "id": "string",
    "description": "string",
    "reactions": [ { /* reaction */ } ]
  }
}
```

The mechanic's `condition` field is only used for game-over and encounter
mechanics.  Mechanics with only reactions use per-reaction `condition` fields
instead.

#### Examples

**Chained encounter (reaction → encounter → reaction → encounter):**
```json
{
  "id": "guardian_awakens",
  "on": "room.entered",
  "condition": { "require": "event:room_id == cave_depths" },
  "effect": { "trigger_encounter": "guardian_attack" }
}
```

The `guardian_attack` encounter has a rule whose success branch sets `guardian_defeated: true`. A second reaction then fires on that flag:

```json
{
  "id": "wraith_appears",
  "on": "flag.set",
  "condition": { "require": "event:flag_id == guardian_defeated" },
  "effect": { "trigger_encounter": "wraith_ambush" }
}
```


**Mechanic with reactions (adventure-wide trigger):**
```json
"global_reactions": {
  "id": "global_reactions",
  "description": "Adventure-wide state-based reactions.",
  "reactions": [
    {
      "id": "injury_warning",
      "on": "player.damaged",
      "condition": { "require": "event:new_hp <= 3" },
      "effect": {
        "result": {
          "narrative": "You are gravely wounded. One more hit could be your last.",
          "set_flag": { "near_death": true }
        }
      }
    }
  ]
}
```

---

## `stats` — Player ability scores (optional)

When present, the `stats` block declares which ability scores the adventure uses
and which resolution system applies to stat checks. If absent, the adventure has
no stat system — existing adventures work unchanged.

```json
{
  "definitions": {
    "STR": { "name": "Strength", "description": "Physical power" },
    "DEX": { "name": "Dexterity", "description": "Agility and reflexes" },
    "CON": { "name": "Constitution", "description": "Endurance" },
    "INT": { "name": "Intelligence", "description": "Reasoning" },
    "WIS": { "name": "Wisdom", "description": "Perception" },
    "CHA": { "name": "Charisma", "description": "Force of personality" }
  },
  "system": "5e"
}
```

| Field               | Type   | Required | Description |
|---------------------|--------|----------|-------------|
| `definitions`       | object | yes      | Dict of stat key → `{ name, description }`. Keys are short uppercase identifiers (e.g. `"STR"`). |
| `system` | string | yes      | Named resolution system. Currently supported: `"5e"`. |

### Resolution system

The resolution system defines how stat checks translate to probability, decoupling
adventures from specific RPG mechanics. The engine scoreboards stat check details
in `EngineResult.rolls`, including the stat name, DC, modifier breakdown, raw
roll, total, margin (total − DC), and advantage/disadvantage status.

### Player character stats

Player stat values live in `hard_state.player.stats` as a dict of stat key →
integer value. On startup, the engine validates that:
- Every stat key in the player state has a matching definition in `stats.definitions`.
- Stats are consistently present or absent in both corpus and hard state.
- If `stats` is present in the corpus, `player.stats` should be present in
  hard state (and vice versa).

The Context Assembler computes each stat's modifier from the resolution system
(e.g., `(stat - 10) // 2` for 5e) and includes the full `player_stats` block
in the GMBriefing so the LLM knows the player's capabilities without doing math.

### Stat condition domain

Stats can be used in condition strings via the `stat` domain (see Condition
object section). Example: `stat:INT >= 14` gates an interaction on the player's
Intelligence score.

---

## `flags_declared` — Flag name registry (optional)

```json
"flags_declared": ["spider_fled", "injured", "handkerchief_moved"]
```

An optional top-level array of all flag names used in the adventure's
conditions, `set_flag` results, and encounter `set_flag`. This is a
convenience field for validation and debugging — the engine uses it to
verify that every flag referenced in the corpus has a corresponding
entry in `hard_state.flags`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `flags_declared` | string[] | no | List of all flag names used in the adventure. Each name must appear as a key in `hard_state.flags`. |

This field is typically generated during cross-validation, after all
corpus sections are complete. It is optional at the schema level — the
engine treats it as `Optional[List[str]]` and skips validation when
absent.

---

## Example Module

In the reference implementation, the module corpus is loaded once at
startup from a JSON file. The engine holds it in memory as a read-only
data structure. No vector database or semantic search is needed — all
lookups are by deterministic ID.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
