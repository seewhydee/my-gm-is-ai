# Module Corpus Schema

The Module Corpus is the read-only canonical adventure content — the
equivalent of a printed D&D adventure module, containing descriptions
of game logic, rooms, entities, encounters, win/loss conditions, etc.

The Context Assembler reads from it to build the GMBriefing. The
Engine reads from it to validate actions, resolve encounters, and
apply mechanics.

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
(*) optional

---

## Common Primitives

This section defines types used in multiple parts of the corpus
schema: conditions, checks, and results.

### Condition object

A condition object describes a predicate clause gating availability:
whether an exit is shown, a mechanic can be triggered, etc.  They are
formed from condition strings and, optionally, condition objects
(allowing for nested logic).  There are several different forms:

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
		   { "all": [ "entity:frodo.alive", "attitude:frodo >= 4" ] } ] }
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
- `<domain>:<key> <op> <value>` — compare key's value against
	`<value>`. Supported ops: `== true`, `== false`, `== <string>`, `>=
  <number>`, `> <number>`, `<= <number>`, `< <number>`.

| Domain       | Key                                                 |
|--------------|-----------------------------------------------------|
| `flag`       | Global flag ID                                      |
| `inventory`  | Item entity ID in player's inventory                |
| `equipped`   | Item entity ID in player's equipped gear.           |
| `tag`        | Item with this tag in inventory/equipment           |
| `entity`     | Entity with named state field (e.g. `spider.alive`) |
| `room`       | Room with named state field (e.g. `parlor.visited`) |
| `attitude`   | Entity ID of an NPC; value is the NPC's attitude    |
| `topic`      | Topic ID of a topic discussed in current dialogue   |
| `stat`       | Stat name; value is the value of that player stat   |
| `event`      | Value in current event dispatch context (see below).|

Notes:

- The `equipped` domain also accepts tag names: `equipped:weapon`
  holds if any equipped item has the tag `"weapon"`.
- The `attitude` domain uses the NPC's runtime attitude if one has
  been set; otherwise it falls back to `attitude_limits.initial` for
  the NPC.  See [NPC attitude](#npc-attitude)
- The `event` domain is used in [Reaction dispatch](#reaction-object);
  see that section for details.  It evaluates to `false` outside event
  dispatch.

Examples:
- `flag:daytime == true` holds iff the `daytime` flag is true.
- `inventory:rusty_key` holds iff the item with entity ID `rusty_key`
  is in player's inventory; it is not satisfied if the item exists
  outside inventory.
- `topic:abandonment` holds iff the topic has been discussed in the
  current dialogue (`soft_state.dialogue_state.topics_discussed`)
- `stat:STR >= 5` holds iff player's current STR stat is >= 5.

---

### Check

A Check resolves the success or failure of an event or action:
interaction, traversal, encounter, etc.  There are two Check types:
`roll` (flat probability) and `stat_check` (stat-based resolution).

Either type of Check can be set to be repeatable or non-repeatable.
If the `repeatable` field is `false`, the engine automatically tracks
attempts and rejects repeats.

#### Roll Check

A roll Check succeeds if `random() < threshold`.

```json
{
  "type": "roll",
  "threshold": 0.50,
  "repeatable": false,
  "note": "Optional designer note."
}
```

| Field        | Type    | Description                       |
|--------------|---------|-----------------------------------|
| `type`       | string  | `"roll"` — flat probability check |
| `threshold`  | number  | Probability threshold (0.0–1.0)   |
| `repeatable` | boolean | Whether the check can be retried  |
| `note` (*)   | string  | Optional designer note            |
(*) optional

#### Stat Check

Stat Checks are [resolution system](#resolution-system) dependent.

```json
{
  "type": "stat_check",
  "stat": "STR",
  "target": 12,
  "advantage": true,
  "repeatable": false,
  "note": "Bend the iron bars."
}
```

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `type`         | string  | `"stat_check"` — stat-based check |
| `stat`         | string  | Stat key (e.g. `"STR"`, `"DEX"`)  |
| `target`       | integer | Target number / difficulty class  |
| `modifier` (*) | integer | Situational modifier (default 0)  |
| `repeatable`   | boolean | Whether check can be retried      |
| `note` (*)     | string  | Optional designer note            |
(*) optional

Aside from the above fields, system-specific fields are accepted as
extra top-level keys.  Various systems can implement their own checks
and define their own extra fields.

The `5e` system uses roll(1d20) + (stat-10)//2 + modifier >= target as
the success formula.  It also uses the following additional fields:

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `advantage`    | boolean | Roll 2d20 and keep the higher die |
| `disadvantage` | boolean | Roll 2d20 and keep the lower die  |

Both of these fields are optional.  If both are `true`, they cancel
out and a single d20 is rolled.

---

### Result object

A Result describes the consequences of an action — the canonical
narrative, state mutations, stat adjustments, inventory changes, and
optional follow-up checks. Result objects are used in deterministic
game mechanics, but are also used in `success` and `failure` branches
for interactions, traversal checks, dialogue paths, etc.

```json
{
  "narrative": "string (description of outcome)",
  "add_item": ["<item_id>", "..."],
  "remove_item": ["<item_id>", "..."],
  "set_flag": { "<flag_id>": true | false, "..." },
  "set_entity_state": { "<entity_id>": { "<field>": <value>, ... } },
  "set_room_state": { "<room_id>": { "<field>": <value>, ... } },
  "player_damage": "1d6",
  "set_player_location": "<room_id>",
  "alter_stat": { "<stat_key>": { "mode": "delta"|"set", "value": <int> }, "..." },
  "adjust_attitude": { "<npc_id>": <delta>, "..." },
  "reveals": "string (hint text for the player's future reference)",
  "then_check": { /* follow-up check (see below) */ }
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

- All present fields in the Result object are applied.  The fields are
  *not* mutually exclusive; one Result can deal damage, set multiple
  flags, alter multiple state fields, add/drop multiple items, etc.

- The `narrative` field informs the GM narrator what happened, but may
  not be used verbatim.

- During a check, `check.passed`/`check.failed` events (and their
  immediate reactions) fire before the success/failure branch result
  is applied.  The result's effects are then accumulated into a batch,
  and processed as a unit before any follow-up `then_check` resolves.
  See [Reaction](#reaction).

- At the engine level, action-result changes and immediate-reaction
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

- `reveals` is a player-knowledge hint.  If this string is present,
  the engine appends it to `soft_state.revealed_hints` (with
  deduplication), whose contents help guide the GM narrator.
  See the [Soft State schema doc](soft-state.md) for details.

#### Follow-up check

A follow-up check can be embedded in a Result's `then_check` field.
It implements multi-stage resolutions for actions and effects: e.g., a
STR check to jump across a pit, and on failure a DEX check to grab the
ledge before falling.  The follow-up check fires immediately after its
parent result, using its own success/failure branches.

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
(*) optional

Nested follow-ups are supported — a follow-up check's success/failure
results may contain other follow-ups, up to a maximum depth of 3.

---

## Room

A room is a location in the adventure module, modeled as a node in a
world graph keyed by a globally-unique `room_id`.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when player enters or examines room)",
    "entities_present": ["<entity_id>", ...],
    "soft_items": ["string", ...],
    "exits": [ { /* exit */ } ],
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "is_start_room": false,
    "reactions": [ { /* reaction */ } ],
    "state_fields": { "<field_name>": { "type": "boolean|number|string", "description": "string" } }
  }
}
```

| Field                | Type     | Description                        |
|----------------------|----------|------------------------------------|
| `name`               | string   | Short display name                 |
| `description`        | string   | Prose description of room          |
| `entities_present`(*)| string[] | IDs of non-player entities directly present at game start |
| `exits` (*)          | array    | All exits out of the room          |
| `state_fields` (*)   | object   | State fields for room (see below)  |
| `interactions` (*)   | array    | See [Interaction](#interaction)    |
| `on_examine` (*)     | array    | See [On-Examine](#on-examine)      |
| `reactions` (*)      | array    | See [Reaction](#reaction)          |
| `soft_items` (*)     | string[] | Plausible generic items in the room|
| `is_start_room` (*)  | boolean  | `true` for starting room (only one)|
(*) optional

Notes:

- The `name` string is used to indicate the player's location in UI
  during gameplay, whereas `description` guides the GM regarding the
  characteristics of the room, including when the player enters or
  looks around (NOT necessarily used verbatim in narration).

- The `entities_present` field lists entities DIRECTLY present in the
  room (at game start).  If entity A is in room R, and entity B is in
  entity A (see `contained_entities`, [Entity](#entity)), only A is
  directly present; room R's `entities_present` lists A but not B.

- The `exits` field contains an array of [Exit](#exit) objects, one
  for EVERY possible exit, regardless of its initial availability and
  visibility.  Each exit can be individually gated and/or hidden.

- State fields have room-unique IDs (dict keys) chosen by the corpus
  author.  Two reserved state fields are engine-managed: `visited` is
  set to `true` when the player enters a room, and `is_current` is
  computed (true only for the player's current room).  Neither field
  has to be declared in `state_fields`.  Do not use `is_current` to
  relocate the player; use `set_player_location` in a Result.

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

| Field               | Type      | Description                      |
|---------------------|-----------|----------------------------------|
| `id`                | string    | Exit ID (room-unique)            |
| `direction`         | string    | Human-readable exit label        |
| `target_room`       | string    | Room ID of destination           |
| `condition` (*)     | Condition | Gating condition (see below)     |
| `traversal_check`(*)| object    | Check to use the exit (see below)|
| `one_way` (*)       | boolean   | Indicates if exit is one-way     |
(*) optional

Notes:

- `direction` is used when listing the available exits after a room
  description.  Inserted verbatim by the engine.  Style convention:
  one phrase, capitalize, no full stop.  Should be clear enough to
  distinguish different exits.

- `condition` is a gating Condition that must be met for the exit to
  be shown at all.  If an Exit is unavailable, it does not appear to
  the player (or GM) as an available exit from the room.  The distinct
  `traversal_check` field, documented below, describes the conditions
  and gating for non-automatic (e.g., risky) traversal.

- The `one_way` field is only used to indicate to the player that an
  exit *seems* one-way (e.g., a trapdoor).  No gameplay effects.

#### Traversal Check

A Traversal Check object type, on the optional `traversal_check`
field, describes the process of traversing a risky and/or difficult
exit.  (This is different from `condition`, which determines whether
the exit is shown as an available exit.)  Failure on such a check
typically means the player remains in the current room.

```json
{
  "traversal_check": {
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
}
```

| Field               | Type      | Description                 |
|---------------------|-----------|-----------------------------|
| `gating` (*)        | Condition | Whether check is active     |
| `check`             | Check     | Success/failure check       |
| `skip_check_if` (*) | Condition | Whether check auto-succeeds |
| `success` (*)       | Result    | Result when traversal works |
| `failure` (*)       | Result    | Result when traversal fails |
| `using_results` (*) | dict      | Alt check when using tool   |
(*) optional

Notes:

- The `gating` condition controls whether the traversal check is
  active.  True means proceed to do the check (with `skip_check_if`).
  False means traversal proceeds (normal movement).

- The `skip_check_if` controls whether the check auto-succeeds.  When
  present and evaluated to true, the check is skipped entirely, and
  traversal proceeds (normal movement).

- Success also has the side-effect of moving to the destination Room;
  no need to specify that in `success`.

- Failure also has the side-effect of canceling the traversal; no need
  to specify that in `failure`.

- The `using_results` field accommodates player commands of the form
  "[USE EXIT] using [ITEM]".  It is keyed by item entity IDs (or the
  `"*"` wildcard); when the player uses an item matching a key, the
  value replaces the traversal check entirely.  The mapped value can
  be one of these two:
  - a dict with `result` keyed to a [Result](#result)
  - a dict with `check` (a [Check](#check)), `success` (a Result)
    and optionally `failure` (a Result), with the same semantics as
    [Interaction](#interaction).

---

## Interaction

Interactions objects describe are discrete, non-generic operations
that can be performed on (or with) entities or rooms.  Each room and
entity maintains a separate list of available interactions, and each
interaction can have its own availability gating, success/failure
gating, and sucess/failure results.

```json
{
  "id": "string (unique within the defining context)",
  "description": "string (what the player is attempting)",
  "condition": { /* condition object or null */ },
  "skip_check_if": { /* condition object (optional) */ },
  "check": { /* roll check or null */ },
  "success": { /* result */ },
  "failure": { /* result or null */ },
  "result": { /* result (used when no check is present) */ },
  "using_results": { /* item-specific overrides (optional) */ }
}
```

| Field             | Type      |  Description                      |
|-------------------|-----------|-----------------------------------|
| `id`              | string    | ID, unique in room or entity      |
| `description`     | string    | Clear description of interaction  |
| `condition` (*)   | Condition | Whether interaction is available  |
| `check` (*)       | Check     | Success/failure check             |
| `skip_check_if`(*)| Condition | Whether interaction auto-succeeds |
| `success` (*)     | Result    | Result when check succeeds        |
| `failure` (*)     | Result    | Result when check fails           |
| `result` (*)      | Result    | Fixed result (when no check)      |
| `using_results`(*)| object    | Alt check when using tool         |
(*) optional

Notes:

- `id` should be unique within the room or entity.  The reserved
  interaction ID `attack` should not be used.  Interaction IDs should
  also not duplicate the generic actions `move`, `examine`, `talk`,
  `transfer`, or `wait`, nor similar generic verbs (e.g., `take`), as
  this risks confusing the GM on how to categorize player actions.

- The role of `description` is to brief the GM on the semantic meaning
  of the interaction.

- If present, `condition` gates the availability of the interaction;
  if it evaluates to false, the interaction is not presented as an
  available option, even to the GM.

- If `check` is omitted, the interaction triggers `result`, which must
  be defined.  Otherwise, the [Check](#check) is run and triggers
  either `success` (which must be defined) or `failure` (optional);
  but `skip_check_if`, if present and evaluating to true, bypasses the
  check and triggers `success`.

- If `failure` is not specified, a failed check sends a generic
  "nothing happens" message to the GM narrator.

- The `using_results` field, if provided, accommodates player commands
  of the form "[INTERACTION] using [ITEM]", allowing for alternative
  resolution paths.  It should be a dict mapping item entity IDs to
  one of the following objects, which overrides the usual result/check
  for interactions using the matching item:
  - a dict with `"result"` keyed to a [Result](#result), describing an
    alternative unchecked interaction result; OR
  - a dict with `check`, `success`, and `failure` (optional), which
    define an alternative [Check](#check),

---

## On-Examine

Each room and entity object has an optional `on_examine` field for an
**array** of On-Examine objects.  Each On-Examine object describes a
possible effect of examination, which can include conditional gating,
success checks, direct or success/failure results, and optional
rigorous-search-only gating.

During gameplay, ordinary (cursory) examination does not consume a
turn, while rigorous examination does.  When the player performs an
examine action, all eligible On-Examine effects run in array order.

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

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `id`              | string    | ID, unique within parent entity/room |
| `condition` (*)   | Condition | Gating condition (see below)         |
| `skip_check_if`(*)| Condition | Whether examination auto-succeeds    |
| `rigorous_only`   | boolean   | Whether rigorous search is needed    |
| `check` (*)       | Check     | Success check gating outcome         |
| `success` (*)     | Result    | Result applied when the check passes |
| `failure` (*)     | Result    | Result applied when check fails      |
| `result` (*)      | Result    | Result applied if no check           |
(*) optional

Notes:

- The base `description` of the entity/room is returned first in the
  narration; on-examine event narratives are appended after
  it. Results may carry `set_flag`, `alter_stat`, `add_item`, and
  `then_check` like any other result.

- The `condition`, `skip_check_if`, `check`, `success`, `failure`, and
  `result` fields are the same as in [Interaction](#interaction).
  Note that `result` is mutually exclusive with `success` (and
  optional `failure`).  Typically, these fields are used to describe
  whether the player is able to extract a given piece of information.

- Rigorous examinations can also trigger cursory On-Examine effects
  (but not vice versa).

## Reaction

Reactions are a flexible mechanism to make changes in game state in
response to pre-specified events.  They can be placed in the
`reactions` array of a [Room](#room), [Entity](#entity), or
[Mechanic](#mechanic) – called the *scope* of the reaction.

The scope determines when the reaction is active (i.e., can be
triggered).  Room-scoped reactions are active when the player is
present in the room; entity-scoped reactions are active when the
entity is in the present room *and* (for NPCs) alive and not fled;
mechanic-scope reactions are always active.

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
(*) optional

Notes:

- `id` is used for debugging and tracking one-off reactions (those
  with `once` true).  As the tracking is global, one-off reactions
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
  example, a `"room.entered"` trigger provides one context key,
  `room_id`, which is the ID of the room entered.

  The Event Context can be accessed by Condition blocks inside the
  Reaction.  Thus, a `condition` block can narrow the reaction to a
  specific event: e.g., `{"require" : "event:room_id == camp"}`.
  The `event` condition domain is only valid during reaction dispatch.

**Example**: a goblin NPC that attacks on sight, but only if in a
specific room:

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
| `room.[entered|exited]`| `room_id`                                   |
| `traversal.[attempted|succeeded]` | `exit_id`, `from_room`, `to_room`|
| `traversal.failed`     | `exit_id`, `from_room`, `fail_reason`       |
| `interaction.used`     | `interaction_id`, `target_id`, `using_item?`|
| `flag.[set|cleared]`   | `flag_id`                                   |
| `entity_state.changed` | `entity_id`, `field`, `new_value`           |
| `room_state.changed`   | `room_id`, `field`, `new_value`             |
| `dialogue.[started|ended]` | `npc_id`, `reason?`                     |
| `combat.started`       | `combatant_ids`                             |
| `combat.ended`         | `reason` (`victory|defeat|fled`)            |
| `item.acquired`        | `item_id`, `source`                         |
| `item.lost`            | `item_id`, `reason`                         |
| `equipment.changed`    | `added?`, `removed?`                        |
| `attitude.changed`     | `npc_id`, `old_value`, `new_value`, `delta` |
| `stat.changed`         | `stat_name`,`old_value`,`new_value`,`delta` |
| `player.[damaged|healed]` | `amount`, `new_hp`                       |
| `encounter.branched`   | `encounter_id`, `branch`, `outcome`         |
| `turn.[start|end]`     | `turn_number`                               |

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

Example:

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
      "reveals": "The dart trap in the antechamber has been triggered"
    }
  }
}
```

---

## Entity

Entities are typed objects that appear in rooms or inventory. Keyed by
unique `entity_id`.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | item",
    "name": "string (required for item, optional otherwise)",
    "description": "string",
    "spans_rooms": ["<room_id>", ...],
    "soft_items": ["string", ...],
    "contained_entities": ["<entity_id>", ...],
    "tags": ["<tag>", ...],
    "take_check": { /* take_check */
      "check": { "type": "stat_check", ... },
      "success": { "narrative": "..." },
      "failure": { "narrative": "..." }
    },
    "equip_block": { /* equip_block */ },
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "reactions": [ { /* reaction */ } ],
    "dialogue_guidelines": { /* only for npc type */ },
    "behavior": { /* only for npc (monster) type */ },
    "state_fields": { "<field_name>": { "type": "boolean | number | string", "description": "string" } },
    "follower_blacklist": ["<room_id>", ...]
  }
}
```

The following fields are meaningful for all entity types:

| Field                 | Type   | Description                         |
|-----------------------|--------|-------------------------------------|
| `type`                | enum   | `player|feature|npc|item`           |
| `description`         | string | Canonical prose description         |
| `tags` (*)            |string[]| Array of semantic tags              |
| `contained_entities`(*) | string[] | Entities nested inside this entity |
| `interactions` (*)    | array  | See [Interaction](#interaction)     |
| `on_examine` (*)      | array  | See [On-Examine](#on-examine)       |
| `reactions` (*)       | array  | See [Reaction](#reaction)           |
| `state_fields` (*)    | object | State fields for entity (see below) |
| `soft_items` (*)      | array  | Plausible soft items on/in entity   |
(*) optional

Notes:

- `tags` are for mechanical matching (e.g., `"weapon"`, `"key_item"`,
  `"container"`). Available on all entity types.
  These are distinct from `equip_block.equip_tags`;
  `tag:<value>` conditions scan this list, not `equip_tags`.
  The `"container"` tag enables the container open/close mechanic
  (see [Reserved state fields](#reserved-state-fields)).

- State fields ...

Feature-specific fields:

| Field           | Type   | Description                             |
|-----------------|--------|-----------------------------------------|
| `spans_rooms`(*)| array  | List of room IDs the entity spans       |


Item-specific fields:

| Field                  | Type   | Description |
|------------------------|--------|-------------|
| `name`                 | string | Display name for the item (required). |
| `take_check` (*)       | Check  | Success check for taking the item |
| `equip_block` (*)      | object | How the item interacts with the equipment system (see below). Items without this block cannot be equipped. |

Notes:

- `name` is required for item entities; it is what the player sees in
  the `/inv` panel and what both LLM calls receive in briefings,
  rather than the raw snake_case entity ID.

- The Check in `take_check` is **not** automatically disabled after a
  successful take; use `check.repeatable: false` for a one-time gate,
  or remove/hide the item after success. Supports optional `gating`
  (check only fires if met, otherwise item taken freely),
  `skip_check_if` (skip check if met, apply `success` Result), and
  `success`/`failure` Result objects.

NPC-specific fields:

| Field                  | Type   | Description |
|------------------------|--------|-------------|
| `dialogue_guidelines`(*)| object | See [Dialogue Guidelines](#dialogue-guidelines-for-npc-type). |
| `behavior` (*)         | object | Encounter rules for combat-capable NPCs (see [Behavior](#behavior-for-npc-with-combat)). |
| `combat` (*)           | object | HP-based combat stats (hp, ac, atk, dmg, etc.). Only for NPCs. |
| `follower_blacklist`(*)| array of room IDs | Rooms this NPC refuses to enter when following the player. |


### `equip_block` — Equipment block (`EquipBlock`)

Optional. Only present on item-type entities. Describes how an item interacts
with the equipment system. Items without this block cannot be equipped.

```json
{
  "equip_tags": ["weapon"],
  "incompatible_with": ["shield"],
  "equip_effects": { "STR": { "mode": "delta", "value": 1 } },
  "ac_override": null,
  "ac_bonus": 0,
  "two_handed": false,
  "max_equipped": 1,
  "damage_expr": "1d8",
  "attack_bonus": 0
}
```

| Field               | Type       | Required | Description |
|---------------------|------------|----------|-------------|
| `equip_tags`        | `[string]` | yes      | Category tags — e.g. `["headwear"]`, `["weapon"]`, `["armor","heavy"]`, `["shield"]`, `["ring"]`. |
| `incompatible_with` | `[string]` | no       | Tags that conflict with this item. The engine checks all already-equipped items: if any of *their* `equip_tags` intersects this list, the equip is rejected. Default empty means items conflict with anything sharing their own primary `equip_tag` (first element). |
| `equip_effects`     | `{string: {mode, value}}` | no | Stat changes applied while equipped. Keys are stat names (e.g. `"STR"`); values follow `StatModifier`: `{"mode": "delta"|"set", "value": int}`. Set modifiers apply first, then delta. |
| `ac_override`       | `int|null` | no       | If set, player AC becomes this value (e.g. heavy plate: 18). Mutually exclusive in spirit with `ac_bonus` — the highest override among equipped items takes effect. |
| `ac_bonus`          | `int`      | no       | Added to player's base AC. Stacks across equipped items. Used for shields, light/medium armour, rings of protection. |
| `two_handed`        | `bool`     | no       | If true, equipping this weapon is incompatible with any other item tagged `"handwear"`, `"weapon"`, or `"shield"`. |
| `max_equipped`      | `int|null` | no       | How many items of this primary tag may be equipped simultaneously. `1` = standard (one helmet). `2` = rings. `null` = unlimited. Default `1`. The engine uses the *highest* value among items sharing the same primary `equip_tag`. |
| `damage_expr`       | `string`   | no       | Damage dice expression when wielded (e.g. `"1d6"`, `"2d4"`). Only meaningful when `"weapon"` is in `equip_tags`. Default `"1d8"`. |
| `attack_bonus`      | `int`      | no       | Flat bonus added to attack rolls. A "+1 sword" has `attack_bonus: 1`. Stacks across equipped weapons. Default `0`. |

#### NPC follower convention (`following` state field)

An NPC entity can be declared as a **follower** — a companion that moves with the
player between rooms. To enable this, include a boolean `following` field in the
NPC's `state_fields`:

```json
"state_fields": {
  "alive": { "type": "boolean", "description": "..." },
  "attitude": { "type": "number", "description": "..." },
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

#### Reserved state fields

The engine recognises several reserved state fields:

- `alive` — entity reactions are active only when `alive` is not `false`. This
  is conventionally declared for any creature or destructible feature.
- `fled` — entity reactions are active only when `fled` is not `true`. Declare
  this for creatures that can flee or be driven off. Adventures that do not use
  fleeing simply omit the field; it defaults to unset, so the check passes.
- `attitude` (NPC only) — tracks NPC disposition as an integer. Required for
  all NPCs that have `dialogue_guidelines`, since `attitude_limits` constrains
  how attitude can change. The engine initializes attitude from
  `attitude_limits.initial` (default 0). Conditions can check attitude via
  `attitude:<npc_id> <op> <value>`.
- `hidden` — declares explicit concealment (e.g., a lurking enemy, or a sword
  buried in rubble). When `hidden` is `true`, the engine omits the entity from
  `entities_visible` in **all** contexts — the GMBriefing, the EngineResult,
  and the follower injection pass — so neither the LLM nor the player receive
  any mention of it. When `hidden` is absent from `state_fields` (or present
  but unset in `entity_states`), the entity is treated as visible.

  **Do not** use `hidden` for items that are merely inside a closed container;
  that is governed by the container's `open` state (see below).  `hidden` is
  for entities that are present in the room but not apparent even to the GM
  until some condition or action reveals them.

  **Timing:** when a result directly sets `hidden: false` via
  `set_entity_state` (e.g., in an `on_examine` event or an interaction
  result), the entity becomes visible to the narrator in the **same turn** —
  the EngineResult built after the action will include it.  If the reveal is
  gated through a separate reaction on `flag.set` that then sets `hidden:
  false`, the entity does not appear until the **next turn's** GMBriefing,
  because state-change events fire during deferred end-of-turn dispatch.
  Prefer the direct approach for dramatic immediacy, unless the scenario
  requires the reveal to be deferred.

- `open` — for entities with `tags: ["container"]`: when declared in
  `state_fields` and set to `true` in hard state, the entity's
  `contained_entities` and `soft_items` are visible and accessible. When
  `open` is `false` (or absent from hard state), the container is treated as
  closed — its contents are hidden from briefings and cannot be transferred.
  The default when declared but missing from state is closed (`false`).
  Entities without the `container` tag are unaffected by `open`.

`alive` and `fled` are optional at the schema level, but if an entity has reactions
and can die or flee, declare the corresponding field so the engine scopes the
reactions correctly.
`hidden` is optional at the schema level, but an entity with `hidden: true` in
initial hard state must have a planned reveal mechanism — an `on_examine` event
or interaction that sets `hidden: false` — otherwise it is permanently invisible.

### `dialogue_guidelines` (for NPC type)

```json
{
  "personality": "string (tone, demeanor, motivations)",
  "on_encounter": "string (what happens when first met — may reference an auto-event)",
  "can": ["list of things the NPC can/will do"],
  "cannot": ["list of things the NPC will never do or say"],
  "knows": ["list of facts the NPC possesses"],
  "attitude_limits": {
    "min": -5,
    "max": 10,
    "step_per_turn": 3,
    "initial": 0
  },
  "will_reveal": {
    "<topic_id>": {
      "description": "string",
      "conditions": ["attitude:korbar >= 2", "topic:abandonment", "inventory:rusty_key"],
      "set_flag": { "<flag_id>": true | false },
      "set_entity_state": { "<entity_id>": { "<field>": <value> } }
    }
  },
  "dialogue_paths": {
    "<path_id>": {
      "description": "What this dialogue path represents — surfaced to LLM Call 1 as a map of path_id → description.",
      "condition": { /* condition object */ },
      "check": { /* roll or stat_check */ },
      "success": { /* result */ },
      "failure": { /* result */ },
      "result": { /* deterministic result */ }
    }
  }
}
```

| Field             | Type   | Description |
|-------------------|--------|-------------|
| `personality`     | string | Tone, demeanor, motivations. Surfaced to both LLM calls. |
| `on_encounter`    | string | Description of auto-events on first meeting. |
| `can`             | array  | Things the NPC can/will do. |
| `cannot`          | array  | Things the NPC will never do or say. The engine flags violations in `warnings`. |
| `knows`           | array  | Facts the NPC possesses, for LLM dialogue improvisation. |
| `attitude_limits` | object | Integer attitude bounds (see below). |
| `will_reveal`     | object | Gated dialogue topics. Each topic has a `description`, a `conditions` array (all must be true for the topic to be revealable), and optional `set_flag` / `set_entity_state` side effects. When LLM Call 2 tags a topic as revealed via `knowledge_tags`, the engine validates conditions and applies the side effects. |
| `dialogue_paths`  | object | **Optional.** Named special dialogue paths that trigger mechanical effects when the player uses them via a `talk` action with `dialogue_path` set. Each path has a required `description` and may have a `condition`, a probabilistic `check` (+`success`/`failure`), or a deterministic `result`. The path ID is the machine key used in the `talk` action; the `description` is surfaced to LLM Call 1 in `entities_visible` as `{path_id: description}` so it can match player intent to the right path. |

#### `dialogue_paths` object

```json
{
  "flatter": {
    "description": "Praise the spider's hunting prowess to improve its attitude toward the player.",
    "condition": { "require": "attitude:spider < 0" },
    "check": { "type": "stat_check", "stat": "CHA", "target": 12, "repeatable": true },
    "success": {
      "narrative": "The spider preens at your praise.",
      "adjust_attitude": { "spider": 1 }
    },
    "failure": {
      "narrative": "The spider hisses indifferently."
    }
  },
  "inform_spider_dead": {
    "description": "Tell Korbar that the spider has been dealt with.",
    "condition": { "require": "flag:spider_fled == true" },
    "result": {
      "adjust_attitude": { "korbar": 3 }
    }
  }
}
```

| Field       | Type   | Description |
|-------------|--------|-------------|
| `description` | string | **Required.** Human-readable description of what this path represents. This text is surfaced to LLM Call 1 as the value in `entities_visible[*].dialogue_paths[path_id]`, so the LLM can match player input to the right path. Phrase it as a player intent (e.g., "Compliment the spider's hunting prowess" or "Tell Korbar the spider is dead"). |
| `condition` | Condition | Optional. If present, all conditions must be met for the path to be usable. |
| `skip_check_if` | Condition | **Optional.** When present and evaluated to true, the check is skipped entirely (bypasses `condition`). |
| `check`     | Check | Optional. A `roll` or `stat_check`. If present, `success` is required. |
| `success`   | Result | Result applied when the check succeeds. |
| `failure`   | Result | Result applied when the check fails. |
| `result`    | Result | Deterministic result when no `check` is present. Mutually exclusive with `check`. |

Path results support the same fields as interaction `Result` objects: `narrative`, `set_flag`, `alter_stat`, `adjust_attitude`, `reveals`, `then_check`.

#### Knowledge tag validation (`will_reveal` flow)

NPC dialogue revelations follow a post-validation pattern that preserves engine
authority while letting the creative LLM control dialogue timing:

1. The engine includes each NPC's `will_reveal` readiness in the EngineResult
   passed to LLM Call 2 (which topics are conditions-met and thus available to
   be revealed this turn).
2. LLM Call 2 generates dialogue prose and may emit `knowledge_tags` —
   structured tags indicating which `will_reveal` topic IDs the NPC actually
   revealed in its spoken dialogue.
3. The engine post-validates each tag: is it a declared `will_reveal` topic
   for this NPC? Are all conditions met? If so, the engine applies the topic's
   `set_flag` and `set_entity_state` side effects, and records a
   `KnowledgeEntry` in `soft_state.player_knowledge`.
4. On subsequent turns, the Context Assembler includes revealed topics (with
   descriptions) in the GMBriefing, so LLM Call 1 knows what the player has
   learned.

Invalid or conditions-not-met tags are silently rejected. LLM Call 2 is
prompted to respect the `will_reveal` readiness signals; if it narrates a
reveal that the engine rejects, the prose and the mechanical state may
diverge (same risk as rejected soft-state patches).

#### NPC attitude

NPC attitude is tracked as an integer in `hard_state.entity_states[<npc_id>].attitude`. Positive values indicate friendly disposition; negative values indicate hostility. The `attitude_limits` block constrains how attitude can change:

| Field          | Type   | Description |
|----------------|--------|-------------|
| `min`          | number | Minimum allowed attitude value. The engine rejects any patch that would go below this floor. |
| `max`          | number | Maximum allowed attitude value. The engine rejects any patch that would go above this ceiling. |
| `step_per_turn`| number | Maximum change (absolute delta) per turn. Default: 1. |
| `initial`      | number | Starting attitude value at game start. Default: 0. |

For example, a troll might have `min: -5, max: -1` — it can never become friendly. A guard might have `step_per_turn: 1` — attitude shifts only gradually.

### `behavior` (for NPC with combat)

```json
{
  "encounter_rules": [
    {
      "condition": { /* condition object */ },
      "outcome": "death | flee | roll | stat_check",
      "threshold": 0.50,
      "check": { "type": "stat_check", "stat": "STR", "target": 12, "repeatable": true },
      "narrative": "string",
      "set_flag": { "<flag>": true },
      "alter_stat": { "<stat_key>": { "mode": "delta"|"set", "value": <int> } },
      "success": { "outcome": "...", "set_flag": {}, "alter_stat": {}, "narrative": "..." },
      "failure": { "outcome": "...", "set_flag": {}, "alter_stat": {}, "narrative": "..." }
    }
  ],
  "on_flee": {
    "set_flag": { "<flag>": true },
    "effect": "string describing subsequent behavior change"
  }
}
```

- Rules are evaluated top-to-bottom. The first rule whose `condition` matches
  is applied. Conditions are condition objects (see Condition object section)
  evaluated against hard state (flags, inventory, entity states) and soft state
  (attitudes).
- `alter_stat` (optional) applies stat modifiers to the player when the rule fires. Each value is `{ "mode": "delta"|"set", "value": <int> }` (mode defaults to `"delta"`). When a branch (`success`/`failure`) also carries `alter_stat`, the branch values override rule-level values for the same stat key.
- For phase 1 (kill-or-be-killed resolution), outcomes are:
  - `death` — player dies, game over.
  - `flee` — creature flees, applying `on_flee` effects.
  - `roll` — flat probability check using `threshold`; branches on `success`/`failure`.
  - `stat_check` — ability-score-based check using a `StatCheck` definition; branches on `success`/`failure`. The `check` field (a `StatCheck` object) is required when outcome is `stat_check`. Example:
    ```json
    {
      "condition": { "require": "tag:weapon" },
      "outcome": "stat_check",
      "check": { "type": "stat_check", "stat": "STR", "target": 17, "repeatable": true },
      "success": { "outcome": "flee", "narrative": "You overpower Korbar." },
      "failure": { "outcome": "death", "narrative": "Korbar overpowers you." }
    }
    ```

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
        "outcome": "death | flee | roll | stat_check | combat",
        "threshold": 0.50,
        "check": { "type": "stat_check", "stat": "STR", "target": 12, "repeatable": true },
        "success": { "outcome": "...", "set_flag": {}, "alter_stat": {}, "player_damage": "3d6", "narrative": "..." },
        "failure": { "outcome": "...", "set_flag": {}, "alter_stat": {}, "player_damage": "3d6", "narrative": "..." },
        "narrative": "string",
        "set_flag": {},
        "alter_stat": {},
        "player_damage": "3d6"
      }
    ],
    "reactions": [ { /* reaction (optional) */ } ]
  }
}
```

Rules are evaluated top-to-bottom. The first rule whose `condition` matches is
applied. Conditions are condition objects (see Condition object section).

Rule and branch `alter_stat` objects follow the same modifier semantics as
interaction `Result.alter_stat`. `player_damage` accepts a dice expression
(e.g. `"3d6"`, `"2d4+1"`) that the engine rolls as HP damage against the
player. Set at the rule level to apply unconditionally when the rule fires;
set at the branch level (`success`/`failure`) to override the
rule-level value. `outcome: "combat"` starts the multi-round combat system.

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
