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
  "game_over_conditions": [ { /* global game-over condition */ } ],
  "stats":        { /* stat definitions (optional) */ },
  "flags_declared": [ "<flag_id>", { "<flag_id>": <boolean> }, ... ]
}
```

Top-level `flags_declared` entries are either plain strings (starting
`false`) or single-key objects mapping a flag id to its initial boolean
value.

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

A Condition object describes a predicate gating availability: whether
an exit is shown, a mechanic can be triggered, etc.  They are formed
from condition strings and, optionally, other Conditions (allowing for
nested logic).  There are several forms:

**`require`** — availability requires condition string to be true.

```json
{ "require": "flag:volcano_erupting == true" }
```

**`unless`** — availability requires condition string to not be true.

```json
{ "unless": "flag:volcano_erupting == true" }
```

**`any`** — availability requires at least one sub-condition to be
true; each sub-condition is a condition string or nested Condition.

```json
{ "any": [ "flag:volcano_erupting == true",
		   { "all": [ "entity:frodo.alive",
					  "entity:frodo.attitude >= 4" ] } ] }
```

**`all`** — availability requires all sub-conditions to be true; each
sub-condition is a condition string or nested Condition.

```json
{ "all": [ "flag:volcano_erupting == true",
		   { "unless": "inventory:one_ring" } ] }
```

#### Condition String

Condition strings have one of two forms:

- `<domain>:<key>` — presence-only check (allowed for `equipped`,
  `tag`, `topic`, and `inventory` domains).

- `<domain>:<key> <op> <value>` — compare to `<value>`. Supported:
  `== true`, `== false`, `== <string>`, `>= <number>`, `> <number>`,
  `<= <number>`, `< <number>`.
  
| Domain      | Key                                                 |
|-------------|-----------------------------------------------------|
| `flag`      | Global flag ID                                      |
| `inventory` | Item entity ID in inventory; operators compare quantity |
| `equipped`  | Item entity ID in player's equipped gear.           |
| `tag`       | Item with this tag in inventory/equipment           |
| `entity`    | Entity with named state field (e.g. `spider.alive`) |
| `room`      | Room with named state field (e.g. `parlor.visited`) |
| `topic`     | Topic ID of a topic discussed in current dialogue   |
| `stat`      | Stat name; value is the value of that player stat   |
| `event`     | Value in current event dispatch context (see below).|

Notes:

- For `inventory`, omitting the operator checks that the count is
  greater than 0; operators for quantity comparisons.

- The `equipped` domain also accepts tag names: `equipped:weapon`
  holds if any equipped item has tag `"weapon"`.

- An NPC's attitude is stored in `entity_states[<npc_id>].attitude` and
  accessed via `entity:<npc_id>.attitude` conditions, e.g.
  `entity:frodo.attitude >= 4`.  If the NPC has dialogue,
  `attitude_limits.initial` provides the default at game start; the
  corpus author should initialize all dialogue-NPC attitudes to this
  value in the hard-state JSON.

- The `event` domain is used in [Reaction dispatch](#reaction).
  It evaluates to `false` outside event dispatch.

**Examples**:
- `flag:daytime == true` holds iff the `daytime` flag is true.
- `inventory:rusty_key` holds iff item with entity ID `rusty_key` is
  in inventory (count > 0); not satisfied if the item exists outside inventory.
- `inventory:gold_coins >= 30` holds iff the player has at least 30 of the
  stackable item `gold_coins`.
- `topic:abandonment` holds iff the topic has been discussed in the
  current dialogue (`soft_state.dialogue_state.topics_discussed`)
- `stat:STR >= 5` holds iff player's current STR stat is >= 5.

---

### Check

A Check object resolves the success or failure of an event or action:
interaction, traversal, encounter, etc.  There are two types: `roll`
(flat probability) and `stat_check` (stat-based resolution).

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
| `note` (*)   | string  | Author note (not shown to player) |
> (*) optional

Note: `repeatable` is required; if `true`, the Check can be retried,
and if `false`, the engine tracks attempts and rejects repeats.

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
| `note` (*)     | string  | Author note (not shown to player) |
> (*) optional

Aside from the above, different RPG systems can define extra fields as
needed.  `5e` uses roll(1d20) + (stat-10)//2 + modifier >= target as
its success formula, and supports these additional optional fields:

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `advantage`    | boolean | Roll 2d20 and keep the higher die |
| `disadvantage` | boolean | Roll 2d20 and keep the lower die  |

If both fields are `true`, they cancel out and a single d20 is rolled.

---

### Result

A Result describes the consequences of an action: narrative, state
mutations, stat adjustments, inventory changes, and optional follow-up
checks. Results can appear deterministically, or in non-deterministic
`success` and `failure` branches.

```json
{
  "narrative": "Looting the troll, you find a helmet and a dagger, probably taken from some hapless adventurer",
  "add_item": [ "helmet", "enchanted_dagger" ],
  "add_item_count": { "gold_coins": 50 },
  "set_flag": { "old_gear_found" : true },
  "set_entity_state": { "troll": { "looted" : true } },
  "reveals": "Found gear belonging to another adventurer on a troll.",
}
```

ALL fields in a Result object are optional.

| Field               | Type     | Description                         |
|---------------------|----------|-------------------------------------|
| `narrative`         | string   | Narrative description of the result |
| `add_item`          | string[] | Item IDs to add to inventory (each +1) |
| `add_item_count`    | object   | Item IDs → integer counts to add    |
| `remove_item`       | string[] | Item IDs to remove from inventory (each -1) |
| `remove_item_count` | object   | Item IDs → integer counts to remove |
| `set_flag`          | object   | Flag IDs → values to set            |
| `set_room_state`    | object   | Room IDs → { fields → values }      |
| `set_entity_state`  | object   | Entity IDs → { fields → values }    |
| `alter_stat`        | object   | Stat IDs → `{ "mode": "delta"\|"set", "value": <int> }` |
| `set_player_location`| string  | Room ID to relocate the player to   |
| `player_damage`     | string   | Damage dealt to player, e.g. `"1d4"`|
| `adjust_attitude`   | object   | NPC IDs → attitude deltas           |
| `reveals`           | string   | Player knowledge update (see below) |
| `then_check`        | FollowUpCheck | See [Follow-Up](#follow-up)    |
| `trigger_combat`    | boolean  | Enter combat mode (default `false`) |
| `game_over`         | GameOver | End the game (see below)            |

Notes:

- `narrative` briefs the GM but might not be used verbatim.

- All supplied fields are applied together; thus, a single Result can
  deal damage, set multiple flags, alter multiple state fields across
  several entities and rooms, add/drop items, etc.  Action-result
  changes and immediate-reaction changes are merged and applied
  atomically.  Deferred reactions (`room.entered`, `turn.end`, etc.)
  fire after and see the new state.

- During a check, `check.passed`/`check.failed` events (and their
  immediate reactions) fire before applying success/failure results.
  The effects are accumulated into a batch, and processed before any
  [FollowUpCheck](#follow-up) resolves.  See [Reaction](#reaction).

- `set_flag` sets global boolean flags.  A `false` value clears the
  flag; any truthy value sets it.

- `set_room_state` sets [Room](#room) state fields, and similarly
  `set_entity_state` sets [Entity](#entity) state fields.  Each value
  must match the type declared in the corresponding `state_field`.

- `alter_stat` keys are stat labels (e.g. `"STR"`); the mode, if
  omitted, defaults to `"delta"`.  Examples:
  - `{ "STR": { "value": -4 } }` decreases strength by 4
  - `{ "INT": { "mode": "set", "value": 3 } }` sets intelligence to 3

- `add_item` adds one of each listed item, while `add_item_count` adds
  specific amounts, e.g. `{ "coins": 50 }`.  For stackable items (see
  [Entity](#entity)), repeats are allowed and the total count is
  added.  Adding any non-stackable (i.e., unique) item automatically
  removes it from its previous location, if any.

- Similarly, `remove_item` removes one of each listed item, with
  repeats removing multiple counts, and `remove_item_count` removes
  specific quantities.  The engine prevents removing more than exist.

- `adjust_attitude` is capped by the affected NPCs' `step_per_turn`
  for attitude changes.  See [NPC attitude](#npc-attitude).

- `reveals` appends to `soft_state.revealed_hints` (deduplicated) to
  guide the GM; see the [Soft State schema](soft-state.md).

- `game_over`, if present, [ends the game](#game-over).

---

### Follow-Up

A FollowUpCheck object can be put in a Result's `then_check` field,
and implements multi-stage resolutions for actions and effects, firing
right after the parent.

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
| `check`           | Check     | Follow-up check to resolve       |
| `skip_check_if`(*)| Condition | If present and true, skip check  |
| `success`         | Result    | Result if follow-up succeeds     |
| `failure` (*)     | Result    | Result if follow-up fails        |
> (*) optional

Nested follow-ups are supported: a follow-up check's success/failure
results may contain other follow-ups, to a maximum depth of 3.

---

### Resolvable

A Resolvable object describes a player-initiated action that leads to
custom effects: e.g., special interactions with [Rooms](#room) and
[Entities](#entity), [examination actions](#examination), and engaging
in [dialogue paths with NPCs](#dialogue-path).  It is modeled as a
Condition-gated action resolving to a Result.

```json
{
  "id": "string (optional unless subclass requires it)",
  "description": "string (optional unless subclass requires it)",
  "condition": { /* Condition (optional) */ },
  "skip_check_if": { /* Condition (optional) */ },
  "check": { /* roll or stat_check (optional) */ },
  "success": { /* Result (required if check is present) */ },
  "failure": { /* Result (optional) */ },
  "result": { /* Result (optional, mutually exclusive with check) */ },
  "using_results": { /* item ID -> override (optional) */ }
}
```

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `id` (*)          | string    | ID (depends on context)              |
| `description` (*) | string    | Human-readable description of action |
| `condition` (*)   | Condition | Availability gate for the action     |
| `skip_check_if`(*)| Condition | Whether to bypass check and succeed  |
| `result` (*)      | Result    | Fixed result (excl. with `check`)    |
| `check` (*)       | Check     | Resolving check (excl. with `result`)|
| `success` (*)     | Result    | Result when check succeeds/bypassed  |
| `failure` (*)     | Result    | Result when check fails              |
| `using_results`(*)| UsageOverride | See [Usage Override](#usage-override)|
> (*) optional by default (may be required in some contexts)

Notes:

- The meaning of `id` depends on where the Resolvable is used.  For
  room and entity interactions, it must be a room-unique or
  entity-unique ID.  In other contexts, it need not be specified.

- `description` is used to brief the GM on the semantic meaning of the
  action.  It may be omitted for Examination Effects.

- `condition`, if supplied, gates availability.  For example, for an
  interaction with a room/entity, `condition` being `false` typically
  means the interaction is nonsensical in the game's current context,
  and should not even be offered as a possible player action.

- The action itself is specified by one of:
  - a deterministic `result` (which directly fires), OR
  - a probabilistic `check`, with optional `skip_check_if` to bypass
    (evaluating to `true` means auto-success), branching into either
    `success` or `failure` (optional, no-op if omitted).
  The `result` and `check` fields are mutually exclusive.

- `using_results`, if present, describes alternative resolutions when
  doing the action using items: see [Usage Override](#usage-override).

---

### Gated Check

A **gated check** describes situations where a player action meets an
obstacle: specifically, `take_check` for items and `traversal_check`
for room exits.  It is modeled as a [Check](#check) wrapped with a
[Condition](#condition) that determines whether the check is active,
an optional bypass condition, and success/failure [Results](#result).

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
| `using_results`(*)| UsageOverride | See [Usage Override](#usage-override)|
> (*) optional

Notes:

- If `gating` is supplied and evaluates to false, the check is ignored
  (including `success`/`failure`), and the action proceeds normally.

- If the check is active and `skip_check_if` evaluates to true, the
  check automatically succeeds without rolling; in this case `success`
  (if present) *is* applied.

- If the check succeeds or fails, the original action automatically
  proceeds (e.g., a sword is taken from the stone), or fails (e.g.,
  the sword remains stuck), *in addition* to the effects of `success`
  and `failure`.

- `using_results`, if present, describes alternative resolutions when
  doing the action using items: see [Usage Override](#usage-override).

---

### Usage Override

A UsageOverride object, if placed in the optional `using_results`
field of a GatedCheck or Resolvable, handles player commands of the
form "[ACTION] using [ITEM]" for special items.  It maps each special
item's [entity ID](#entity) to a resolution that overrides the usual
GatedCheck or Resolvable.  Each resolution comprises either:

- an object with `"result"` keyed to a fixed [Result](#result); OR

- an object with `check`, `success`, and `failure` (optional),
  defining an alternative [Check](#check).

---

### Encounter Rule

**Encounters** are game events that can unfold in different ways,
depending on an ordered list of conditions.  Encounters occur when
NPCs [attack or are attacked](#aggro), or when triggered by global
[Mechanics](#mechanic).  An encounter is defined by an ordered array
of EncounterRule objects, each having the following form:

```json
  {
    "condition": { "require": "tag:weapon" },
    "check": { "type": "stat_check", "stat": "STR",
			   "target": 10, "repeatable": true },
    "skip_check_if": { "require": "stat:CHA >= 14" },
    "success": { "narrative": "Brandishing your weapon, you hold the orc at bay." },
    "failure": { "narrative": "The orc overpowers you.",
                 "game_over": { "type": "lose", "trigger_id": "orc" } }
  }
```

| Field             | Type      | Description                          |
|-------------------|-----------|--------------------------------------|
| `condition`       | Condition | Condition for the rule to fire       |
| `result` (*)      | Result    | Direct result (excl. with `check`)   |
| `check` (*)       | Check     | Resolving check (excl. with `result`)|
| `skip_check_if`(*)| Condition | Whether to bypass `check` and succeed|
| `success` (*)     | Result    | Result when Check succeeds           |
| `failure` (*)     | Result    | Result when Check fails              |
> (*) optional

When an encounter is triggered, its rules are evaluated in order. The
first rule whose `condition` holds (if any) is applied; the rest are
ignored.  The applied EncounterRule is resolved via its `result`,
`check`, `success`, and/or `failure` fields, which have the same
meanings as in [Resolvable](#resolvable).  Each Result may trigger
combat via `trigger_combat`, or game-over via `game_over`.

---

### Game-Over

A GameOver object specifies a win or loss outcome.

```json
{ "type": "lose", "trigger_id": "" }
```

| Field        | Type   | Description                          |
|--------------|--------|--------------------------------------|
| `type`       | string | `"win"` or `"lose"`                  |
| `trigger_id` | string | Descriptor for the game-over outcome |

In the final copy of the hard game state, the `trigger_id` is saved to
`game_over.trigger` for debugging and player review.

---

## Room

A room is a location in the adventure module, modeled as a node in a
world graph keyed by a globally-unique `room_id`.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when player enters or examines room)",
    "contains": ["<entity_id>", {"<entity_id>": <count>}, ...],
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

| Field               | Type         | Description                     |
|---------------------|--------------|---------------------------------|
| `name`              | string       | Short display name              |
| `description`       | string       | Prose description (for GM)      |
| `contains`(*) | string/object[] | IDs/counts of entities in room at start |
| `exits` (*)         | Exit[]       | All exits out of the room       |
| `state_fields` (*)  | object       | `{ "<field>": <spec>, ...  }`   |
| `interactions` (*)  | Resolvable[] | Special interactions (see below)|
| `on_examine` (*)    | array        | See [Examination](#examination) |
| `reactions` (*)     | Reaction[]   | See [Reaction](#reaction)       |
| `soft_items` (*)    | string[]     | Plausible generic items in room |
| `is_start_room` (*) | boolean      |`true` for starting room only    |
> (*) optional

Notes:

- The `name` string is used as the room's in-game UI label, whereas
  `description` briefs the GM on the characteristics of the room (but
  is not necessarily used verbatim in narration).

- The `contains` field lists the entities *directly* present in the
  room initially.  "Directly" means that if room R contains entity A,
  and A contains another entity B (see [Entity](#entity)), R's
  `contains` should list A but not B.  As an exception, the player
  entity must be omitted, even if this is the starting room.

  Each list entry is either an object `{ "<entity_id>": <count> }`, or
  an entity ID (count = 1).  Each count must be positive, and a
  non-item entity or non-stackable item must have total count 1.

  When the game loads, the engine uses this to initialize the
  containment maps used for subsequent game state mutations.

- The `exits` field stores an array of [Exit](#exit) objects, one for
  every possible exit regardless of initial availability / visibility.
  Each exit can be individually gated and/or hidden.

- State fields describe various mutable aspects of the room's state.
  They are labeled by room-unique IDs.  There are two reserved state
  fields, which are managed by the engine and need not be declared:

  - `visited` is set to `true` when the player enters a room.

  - `is_current` is true only for the player's current room.  This is
    auto-computed, so do not move the player by trying to change it;
    use `set_player_location` in a [Result](#result) instead.

  Any other state field needed by the adventure should be declared in
  `state_fields`, keyed by its ID and with values of the form

    `{ "type": TYPE, "description": DESC, "initial": INIT }`

  where

  - TYPE is one of `"boolean"`, `"number"`, or `"string"`
  - DESC is a string describing the nature of the state field
  - INIT is optional and, when present, is the value at game start. It
    must match the declared type. (Note that `boolean` and `number` are
    distinct: `true` is not accepted as the number `1`.)

  If `initial` is omitted, the engine fills in a default based on the
  field name and type:

  - Reserved fields use their documented default initial value (see
    below).
  - Author-defined fields fall back to the type default: `false` for
    booleans, `0` for numbers, `""` for strings.

  Because omitted `initial` values silently fall back to a safe default,
  authors are encouraged to set them explicitly.

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

| Field               | Type       | Description                      |
|---------------------|------------|----------------------------------|
| `id`                | string     | Exit ID (room-unique)            |
| `direction`         | string     | Human-readable exit label        |
| `target_room`       | string     | Room ID of destination           |
| `condition` (*)     | Condition  | Gating condition (see below)     |
| `traversal_check`(*)| GatedCheck | See [Gated Check](#gated-check)  |
| `one_way` (*)       | boolean    | Indicates if exit is one-way     |
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
array of [Resolvables](#resolvable) describing possible examination
outcomes.  When the player performs an examination, all eligible
Resolvables run in array order.

The player can opt between ordinary (cursory) examination, which does
not consume a turn, and rigorous examination, which costs a turn.  To
support this, the Resolvables in `on_examine` allow an extra field,
`rigorous_only` (boolean, default `false`).  Resolvables with
`rigorous_only` *only* activate under rigorous examination, whereas
rigorous examinations *can* activate cursory-examination Resolvables.

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

| Field         | Type         | Description                           |
|---------------|--------------|---------------------------------------|
| `id`          | string       | Reaction ID, unique in scope          |
| `on`          | string       | The [reaction trigger](#event)        |
| `condition`(*)| Condition    | Activation condition for reaction     |
| `effect`      | ReactionEffect | What it does when triggered         |
| `once` (*)    | boolean      | Whether it is one-off; default false  |
| `phase`(*)    | string       | `"deferred"` (default) / `"immediate"`|
| `priority`(*) | integer      | Lower = fires earlier; default `0`    |
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

- The **Event Context** – a flat map of details about the event.  For
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
| `traversal.[attempted\|succeeded]`| `exit_id`, `from_room`, `to_room`|
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
| `turn.[start\|end]`    | `turn_number`                               |

For the full list, and full documentation of the context keys, see the
[Events schema doc](events.md).

### Reaction Effect

A Reaction Effect object is stored in a reaction's `effect` field, and
describes what the reaction does if successfully triggered:

```json
{
  "result": { /* Result object (same as interaction results) */ },
  "trigger_encounter": "<mechanic_id or entity_id>",
  "trigger_dialogue": "<npc_entity_id>"
}
```

The Reaction Effect must contain at least one of the following fields
(if more than one is supplied, they all apply):

| Field               | Type      | Description                        |
|---------------------|-----------|------------------------------------|
| `result`            | Result    | A [Result](#result) to run         |
| `trigger_encounter` | string    | Mechanic or entity ID              |
| `trigger_dialogue`  | string    | NPC entity ID to start dialogue    |

Note: For `trigger_[encounter|dialogue]`, the `"self"` value resolves
to the owning entity's ID (for entity-scoped reactions).

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

Entities are objects that appear in rooms or inventory.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | item",
    "name": "string (required for item, optional otherwise)",
    "description": "string",
    "soft_items": ["string", ...],
    "contains": ["<entity_id>", {"<entity_id>": <count>}, ...],
    "tags": ["<tag>", ...],
    "take_check": { /* Gated Check (optional) */ },
    "equip_block": { /* equip_block */ },
    "max_stack": 99,
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
| `contains`(*) | string/object[] | IDs/counts of entities in this entity at start |
| `interactions` (*) | Resolvable[] | Special interactions (see below) |
| `on_examine` (*)   | array    | See [Examination](#examination)      |
| `reactions` (*)    | array    | See [Reaction](#reaction)            |
| `state_fields` (*) | object   | `{ "<field>": <spec>, ...  }`        |
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

  The special `"stackable"` tag may be placed on item entities to let
  their inventory count exceed 1.  See [Item](#item).

- The `contains` field lists the entities *directly* contained in this
  entity at game start.  "Directly" means that if A contains B and B
  contains C, the `contains` field for A should list B but not C.  An
  entity cannot contain itself.

  Each list entry must be an object `{ "<entity_id>": <count> }`, or
  an entity ID string (count = 1).  Each count must be positive, and a
  non-item entity or non-stackable item must have total count 1.

- State fields describe various mutable aspects of the entity's state.
  They are labeled by entity-unique IDs.  There are several reserved
  state fields, which need not be declared in `state_fields`:

  | Reserved Field | Type    | Initial value | Purpose                                 |
  |----------------|---------|---------------|-----------------------------------------|
  | `alive`        | boolean | `true`        | NPC active? (false => reactions off)    |
  | `fled`         | boolean | `false`       | NPC fled? (false => reactions off)      |
  | `attitude`     | integer | `dialogue.attitude_limits.initial` | NPC disposition (higher == friendlier)  |
  | `hidden`       | boolean | `false`       | Explicit concealment (see below)        |
  | `following`    | boolean | `false`       | NPC follows player between rooms        |
  | `current_hp`   | number  | `combat.hp`   | Current hit points (for combat)         |
  | `open`         | boolean | `true`        | Container open/closed state             |

  Authors may override any reserved-field initial value by supplying an
  explicit `initial` in the field declaration.

  The `hidden` state field declares explicit concealment (e.g., a
  lurking enemy, or a sword buried in rubble). When `true`, the engine
  omits the entity (even from the GM, to avoid leakage).  DO NOT use
  `hidden` for entities that are merely inside a closed
  [container](#container); that kind of concealment is controlled by
  the container's `open` state.

  Any other state field needed by the adventure (`looted`, `cursed`,
  etc.) should be declared in `state_fields`, keyed by its ID and
  having values of the form

    `{ "type": TYPE, "description": DESC, "initial": INIT }`

  where

  - TYPE is one of `"boolean"`, `"number"`, or `"string"`
  - DESC is a string describing the nature of the state field
  - INIT is optional and, when present, is the value at game start.
    It must match the declared type.

  If `initial` is omitted, the engine uses the reserved-field default
  above when applicable; otherwise it falls back to the type default
  (`false`, `0`, or `""`).

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

A container's initial contents are declared in its `contains` and
`soft_items` fields.  (These fields can also be used for non-container
entities, like a rubbish pile, which is not a container in the present
sense as it lacks open/close functionality.)

When the container is open, the engine automatically surfaces its
contents to the GM and player; when closed, the contents are
inaccessible.  This is distinct from the `hidden` state.

### Item

Items are entities that can potentially be picked up by the player.
The player cannot talk to or attack items.

Items with the `"stackable"` tag can have multiple instances tied to
the same entity ID.  These instances are indistinguishable and can
occur, individually or in multiple copies, within the player's
inventory, rooms, or other entities.  Stackable items support
multi-copy transfers in [Results](#result) and player actions, and
quantity comparisons in conditions (e.g. `inventory:coins >= 30`).

| Field            | Type       | Description                  |
|------------------|------------|------------------------------|
| `name`           | string     | Display name (required!)     |
| `take_check` (*) | GatedCheck | Obstacle to taking the item  |
| `equip_block` (*)| object     | For equipment (see below)    |
| `max_stack` (*)  | interger   | Stack cap for stackable item |

> (*) optional

Notes:

- `name` is required for items; it's shown in the inventory UI.

- `take_check`, if present, is a [gated check](#gated-check) for
  taking the item (e.g., pulling a sword from a stone).  Success and
  failure have the side-effects of adding the item to the player's
  inventory, and preventing the item from being taken, respectively;
  no need to specify `add_item` explicitly in `success`/`failure`.

  The gated check is *not* automatically disabled after a successful
  take.  For a one-time success gate (pass once, then freely take
  thereafter), use `gating` with a flag on `success`.

- For a stackable item, `max_stack`, if supplied, should be >= 1 and
  sets the inventory count; if omitted, there is no cap.

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

| Field           | Type   | Description                          |
|-----------------|--------|--------------------------------------|
| `dialogue`(*)   | object | NPC's [dialogue settings](#dialogue) |
| `aggro` (*)     | array  | NPC's [aggro rules](#aggro)          |
| `follower` (*)  | object | NPC's [follower rules](#follower)    |
| `combat` (*)    | object | Combat stats (hp, ac, atk, etc.)     |
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
can share with the player.  It should be an object keyed by topic IDs
(entity-unique), with value objects having following fields:

| Field          | Type     | Description                              |
|----------------|----------|------------------------------------------|
| `description`  | string   | What the topic reveals; surfaced to GM   |
| `conditions`   | string[] | Revelation conditions (all must be true) |
| `set_flag` (*) | object   | `{ "<flag_id>": <value>, ... } `         |
| `set_entity_state` (*) | object| `{ "<entity_id>": { "<field>": <value>, ...}, ...}` |
> (*) optional

When a topic's conditions are met, the engine marks it as available
and surfaces it to the GM, which can decide to narrate the revelation
(or not, depending on the flow of conversation).

Once the revelation occurs and is validated, the engine applies any
side effects specified by `set_flag` and `set_entity_state`, which use
the same formats as the fields in [Result](#result).  The engine also
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

The `aggro` field on an NPC entity stores an ordered list of
[encounter rules](#encounter-rule) defining how an NPC reacts in
hostile encounters (player attack, or combat triggered by a reaction).

```json
"aggro": [
  {
    "condition": { "require": "tag:weapon" },
    "result": { "narrative": "Brandishing your weapon, you fight the orc.",
				"trigger_combat": true },
  },
  {
    "condition": { "require": "true" },
    "check": { "type": "stat_check",
               "stat": "STR", "target": 10, "repeatable": true },
    "success": { "narrative": "Putting up your fists, you start to fight!",
				 "trigger_combat": true },
    "failure": { "narrative": "Without a weapon, the orc overpowers you.",
                 "game_over": { "type": "lose", "trigger_id": "orc" } }
  }
]
```

If no rule matches, the encounter silently does nothing (no narrative,
no effects, no combat, no game-over).  To avoid this, put a rule with
`"require": "true"` as the last entry.

#### Follower

An NPC entity can be declared as a **follower** — a companion that
moves with the player between rooms. To enable this, set the NPC's
`following` state field to `true`.  (The default is `false`.)

An NPC can carry an optional `follower` object to tweak its behavior
as a follower:

```json
"follower": {
  "blacklist": ["<room_id>", ...]
}
```

| Field       | Type     | Description                          |
|-------------|----------|--------------------------------------|
| `blacklist` | string[] | Room IDs the follow refuses to enter |

If the player enters one of these listed rooms while the NPC is
following, the engine clears the `following` state field.

---

## Mechanic

Mechanics are named bundles of game logic not tied to a specific room
or entity.  They live in an object in the Corpus' top-level
`"mechanics"` field (see [Top-Level Structure](#top-level-structure):

```json
{
  "mechanics": {
    "curse_effects": {
      "reactions": [
        {
          "id": "guardians_awaken",
          "on": "flag.set",
          "condition": { "require": "event:flag_id == curse_active" },
          "effect": {
            "result" : {
              "narrative" : "The guardians awaken!",
              "set_entity_state" : {
				"guardian_1": { "alive": true },
				"guardian_2": { "alive": true }
			  }
			}
		  }
		},
        {
          "id": "curse_debuff",
          "on": "flag.set",
          "condition": {
			"all": [ "event:flag_id == curse_active",
					 { "unless": "inventory:amulet_of_protection" } ]
		  },
          "effect": {
			"result": {
              "narrative": "The curse saps your vitality",
			  "alter_stat": { "CON": { "mode": "delta", "value": -5 } }
			}
          }
		}
      ]
    }
  }
}
```

All fields supported by Mechanic objects are listed here:

| Field           | Type            | Description                   |
|-----------------|-----------------|-------------------------------|
| `condition` (*) | Condition       | An encounter-gating condition |
| `rules` (*)     | EncounterRule[] | A triggerable encounter       |
| `reactions` (*) | Reaction[]      | A set of global reactions     |
> (*) optional (subject to constraints below)

Conceptually, there are two kinds of mechanic, distinguished by which
field is present:

- An **Encounter Mechanic** must have `rules`, and describes an
  Encounter (a set of possibilities that can unfold in various ways).
  When the mechanic is triggered (usually via `trigger_encounter`),
  the ordered list of [Encounter Rules](#encounter-rule) stored in
  `rules` is evaluated top-to-bottom .  The first valid Encounter Rule
  is run; if no rule matches, the encounter silently does nothing.

  `condition`, if supplied, is a gating condition: when the mechanic
  is triggered, `condition` is evaluated first, and if it is `false`
  the encounter is cancelled (without checking `rules`).

  An Encounter Mechanic can only resolve once per turn.  If a reaction
  triggers an Encounter Mechanic that has already been triggered this
  turn, the second trigger is ignored.  However, reactions can trigger
  *other* encounters, etc., up to a depth-5 limit.

  An Encounter Mechanic is also allowed to carry `reactions`; this is
  handled in the same way as a Reaction-Only Mechanic, below.

- A **Reaction-Only Mechanic** carries only `reactions`: a list of
  [Reactions](#reaction) that are always active, reacting to
  adventure-wide triggers not tied to a specific room or entity.

--

## Global Game-Over Conditions

The top-level `game_over_conditions` field of the Module Corpus can
store game-over conditions accessible from any point in the game.

This field is meant for *globally significant* game-overs, usually
those that can be reached via several routes and aren't tied to
specific parts of the game.  For "local" game-overs (e.g., falling
into a specific pit), set `game_over` in a [Result](#result).

If `game_over_conditions` is supplied, it should be an array of
objects with these fields:

| Field            | Type      | Description                       |
|------------------|-----------|-----------------------------------|
| `condition`      | Condition | Predicate polled each turn        |
| `type`           | string    | `"win"` or `"lose"`               |
| `trigger_id`     | string    | Copied into `game_over.trigger`   |
| `narrative` (*)  | string    | Canonical ending narration        |
| `note` (*)       | string    | Author note (not shown to player) |
> (*) optional

The engine polls `condition` once per turn, after all reactions have
settled.  The first entry with `condition` evaluating to `true` ends
the game using `type` and `trigger_id` as the [GameOver](#game-over)
parameters, and with `narrative` (optional) as the ending narration.

Example:

```json
"game_over_conditions": [
  {
    "type": "win",
    "condition": { "require": "entity:dragon.alive == false" },
    "trigger_id": "killed_dragon",
    "narrative": "The dragon is dead. You have defeated the boss!"
  }
]
```

---

## Player Stats

RPG systems often track a large set of player data (level, armor
class, etc.).  We store this data in `hard_state.player` in the game's
[Hard State](hard-state.md), and use it during combat.

In the Corpus, we focus on a core subset of player data that directly
affects out-of-combat game mechanics, referred to as **Player Stats**.
These numerical fields perform the following roles:

- They are used in [Stat Checks](#stat-checks).

- They can be queried via [Condition Strings](#condition-string) like
  `"stat:CHA >= 14"`.

- They can be altered by [Results](#result) via the `alter_stat`
  field, triggering `stat.changed` [Events](#event).  They can also be
  modified by wearing/wielding [Equipment](#equipment).

The schema aims to be agnostic about the choice of RPG system.  The
system, along with the set of supported player stats, is declared in
each Corpus' `stats` field at [top-level](top-level-structure).

```json
{
  "system": "5e",
  "definitions": {
    "STR": { "name": "Strength" },
    "DEX": { "name": "Dexterity" },
    "CON": { "name": "Constitution" },
    "INT": { "name": "Intelligence" },
    "WIS": { "name": "Wisdom" },
    "CHA": { "name": "Charisma" }
  },
}
```

| Field         | Type   | Description                    |
|---------------|--------|--------------------------------|
| `system`      | string | RPG system ID, e.g. `"5e"`     |
| `definitions` | object | Map of stat key → `{ name }`   |

`system` specifies how to perform [Stat Checks](#stat-checks).  If the
value is not a supported RPG system, the adventure will not load.

`definitions` is keyed by stat IDs.  These are the same stat IDs used
in Stat Checks, Condition Strings, and other parts of the corpus.  For
each stat, `name` is used to print the stat in the character sheet;
other fields may be added later.

The engine uses the `stats` field to validate that the corpus and hard
state are consistent in their use of stats (e.g., every stat key in
the player state has a matching definition in the corpus).

---

## `flags_declared` — Flag name registry (optional)

```json
"flags_declared": [
  "spider_fled",
  { "injured": false },
  { "handkerchief_moved": true }
]
```

An optional top-level array of all flag names used in the adventure's
conditions and `set_flag` results.  Each entry is either a plain string
(meaning the flag starts `false`) or a single-key object mapping the
flag id to its initial boolean value.

The engine uses this field to verify that every flag referenced in the
corpus has been declared and to seed the initial `hard_state.flags`
when the world state is generated from the corpus.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `flags_declared` | (string \| object)[] | no | List of all flag names used in the adventure. Each name must appear as a key in `hard_state.flags` or in `flags_declared`. |

This field is typically generated during cross-validation, after all
corpus sections are complete. It is optional at the schema level — the
engine treats it as `Optional[List[str]]` and skips validation when
absent.

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
