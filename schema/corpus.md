# Module Corpus Schema

The Module Corpus is the read-only canonical adventure content — the
equivalent of a printed D&D adventure module, containing descriptions
of game logic, rooms, entities, encounters, win/loss conditions, etc.
Its contents are used to brief the GM, and by the engine to validate
actions and apply game mechanics.

## Top-Level Structure

```json
{
  "adventure":    { /* metadata */ },
  "flags_declared": [ "<flag_id>", { "<flag_id>": <boolean> }, ... ]
  "rooms":        { "<room_id>": { /* room */ } },
  "entities":     { "<entity_id>": { /* entity */ } },
  "mechanics":    { "<mechanic_id>": { /* mechanic */ } },
  "game_over_conditions": [ { /* global game-over condition */ } ],
  "stats":        { /* stat definitions (optional) */ },
  "abilities":    { "<ability_id>": { /* combat ability (optional) */ } },
  "status_effects": { "<status_effect_id>": { /* status effect definition (optional) */ } },
}
```

Certain parts of the game (rooms, items, NPCs, named mechanics, etc.)
are denoted by ID strings, often used in object keys (as in the above
example).  By convention, IDs are in snake_case.  Different ID types
have different uniqueness requirements, as explained in the following
documentation.

All objects in the schema permit undocumented fields with no
rejection.  By convention, a `note` field may be added to any object
to record author notes that have no gameplay effects.

## Adventure Metadata

```json
{
  "id": "dungeon_of_despair",
  "title": "Descent into the Dungeon of Despair!",
  "credits": {
    "author": "Foo Bar",
    "source": "Adapted from a story at http://www.example.com",
    "license": "CC-BY-SA 4.0"
  },
  "introduction": "After weeks of trekking through an uninhabited wilderness, you stand before a stone door carved into a cliff wall: the entrance to the fabled Dungeon of Despair.  What treasures lie in its depths?",
  "atmosphere": {
    "setting": "A dungeon crawling adventure, set in a medieval low fantasy world. <More setting details here>",
    "tone": "Serious, with a sense of threat around every corner"
  }
}
```

| Field          | Type   | Description                               |
|----------------|--------|-------------------------------------------|
| `id`¹          | string | The adventure's id, for save/load check   |
| `title`        | string | Display title of the adventure            |
| `credits`¹     | object | `{ author, source, license }`             |
| `introduction` | string | Opening narration read to player at start |
| `atmosphere`¹  | object | `{ setting, tone }` (to guide GM)         |
> ¹ optional

---

## Global Flags

The top-level `flags_declared` field specifies a set of boolean flags.

```json
"flags_declared": [
  "knows_vizier_secret",
  { "fairy_blessing": false },
  { "daytime": true }
]
```

Each flag must have a unique ID (i.e., unique among all flag IDs),
and, optionally, a boolean value (defaulting `false`) specifying the
initial value at game start.

If `flags_declared` is omitted, the engine assumes all global flags
are initially `false`.

---

## Common Primitives

In this section, we define several common types which are used
throughout subsequent parts of the schema.

### Condition

A **Condition** describes a predicate gating availability: whether an
exit is shown, a mechanic can be triggered, etc.  They are formed from
condition strings and, optionally, other Conditions (allowing for
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
  `== true`, `== false`, `!= true`, `!= false`, `== <string>`,
  `!= <string>`, `>= <number>`, `> <number>`, `<= <number>`,
  `< <number>`.

| Domain      | Key                                                   |
|-------------|-------------------------------------------------------|
| `flag`      | Global flag ID                                        |
| `inventory` | Item entity ID in inventory; operators compare qty    |
| `equipped`  | Item entity ID in player's equipped gear              |
| `tag`       | Item with this tag in inventory/equipment             |
| `entity`    | Entity state field, e.g. `king.alive`, `bob.location` |
| `room`      | Room state field, e.g. `parlor.visited`               |
| `topic`     | Topic ID of a topic discussed in current dialogue     |
| `stat`      | Stat name; value is the value of that player stat     |
| `event`     | Value in current event dispatch context (see below)   |
| `status_effect` | Status effect ID, with optional entity/rounds segment |

Notes:

- For `inventory`, omitting the operator checks that the count is
  greater than 0; operators perform quantity comparisons.

- The `equipped` domain also accepts tag names: `equipped:weapon`
  holds if any equipped item has tag `"weapon"`.

- The `event` domain is used in [Reaction dispatch](#reaction).
  It evaluates to `false` outside event dispatch.

- The `status_effect` domain queries active status effects (see
  [Status Effects](#status-effects)).  `status_effect:poisoned` holds iff the
  player has the status effect; `status_effect:rat.poisoned` holds iff the
  entity `rat` has it (`status_effect:player.poisoned` is equivalent to the
  bare form).  Both presence forms are operator-free.  The reserved
  second segment `rounds` compares the player's remaining rounds:
  `status_effect:poisoned.rounds >= 2` (operator required).

Examples:
- `flag:daytime == true` holds iff the `daytime` flag is true.
- `inventory:rusty_key` holds iff `rusty_key` is in inventory; not
  satisfied if that item exists outside inventory.
- `inventory:gold_piece >= 30` holds iff the player has at least 30 of
  the stackable item `gold_piece`.
- `entity:frodo.attitude >= 4` holds iff `frodo` has attitude >= 4.
- `entity:shimrod.location == room:parlor` holds iff the `shimrod`
  entity is in the room `parlor`.  Note that the `location` field only
  holds for singleton (non-stackable) entities.
- `entity:spider.location == null` holds iff `spider` is not located
  anywhere (i.e., has left the scene).
- `room:cellar.is_current == true` holds iff the player is currently
  in the room `cellar`.  This works in any condition — not only in
  encounter rules — and is the standard way to give a multi-room
  feature room-dependent behavior.
- `topic:abandonment` holds iff `abandonment` has been discussed in
  the current dialogue.
- `stat:STR >= 5` holds iff player's current STR stat is >= 5.
- `status_effect:poisoned` holds iff the player is poisoned.
- `status_effect:poisoned.rounds >= 2` holds iff the player has at least 2
  rounds of poison remaining.
- `status_effect:spider.stunned` holds iff the `spider` entity is stunned.

---

### Check

A **Check** resolves success or failure for an event or action:
interaction, traversal, encounter, etc.  There are two types: `roll`
(flat probability) and `stat_check` (stat-based resolution).

#### Roll Check

A Roll Check succeeds if `random() < threshold`.

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

| Field        | Type    | Description                       |
|--------------|---------|-----------------------------------|
| `type`       | string  | `"stat_check"` — stat-based check |
| `stat`       | string  | Stat key (e.g. `"STR"`, `"DEX"`) or a skill known to the active system (5e: e.g. `"acrobatics"`) |
| `target`     | integer | Check target or difficulty class  |
| `modifier`¹  | integer | Situational modifier (default 0)  |
| `repeatable` | boolean | Whether check can be retried      |
> ¹ optional

Aside from the above, different RPG systems can define extra fields.
`5e` uses roll(1d20) + (stat-10)//2 + modifier >= target as its
success formula, and supports these additional optional fields:

| Field          | Type    | Description                       |
|----------------|---------|-----------------------------------|
| `advantage`    | boolean | Roll 2d20 and keep the higher die |
| `disadvantage` | boolean | Roll 2d20 and keep the lower die  |
| `save`         | boolean | This check is a saving throw      |

If both `advantage` and `disadvantage` are `true`, they cancel out and
a single d20 is rolled.

If `save` is true, the check is a saving throw: the player's save
proficiency bonus for `stat` is added to the check; this is the
character's proficiency bonus when `stat` is listed in their
`save_proficiencies`, as defined in the
[hard state schema](hard-state.md).

Advantage and disadvantage may also come from the player's active
[status effects](#status-effects) (e.g. `poisoned` imposes disadvantage
on ability checks); these combine with the authored fields above.
Status-effect modifiers apply to ability checks — including skill
checks — but never to saving throws (`save: true`).

#### Skill Checks (5e)

For the `5e` system, `stat` may also name one of the 18 SRD skills
(matched case-insensitively). A skill check rolls against the player's
score in the skill's governing ability, adding the player's
proficiency bonus when the skill is listed in their
[`skill_proficiencies`](hard-state.md) — proficiency is a property of
the player, so no field on the check itself is needed:

```json
{
  "type": "stat_check",
  "stat": "acrobatics",
  "target": 13,
  "repeatable": true
}
```

| Skill | Ability | Skill | Ability |
|-------|---------|-------|---------|
| Acrobatics | DEX | Medicine | WIS |
| Animal Handling | WIS | Nature | INT |
| Arcana | INT | Perception | WIS |
| Athletics | STR | Performance | CHA |
| Deception | CHA | Persuasion | CHA |
| History | INT | Religion | INT |
| Insight | WIS | Sleight of Hand | DEX |
| Intimidation | CHA | Stealth | DEX |
| Investigation | INT | Survival | WIS |

---

### Result

A **Result** describes the consequences of an action: narrative, state
mutations, stat adjustments, inventory changes, and follow-ups.
Results can appear deterministically, or in non-deterministic
`success` and `failure` branches.

```json
{
  "narrative": "Looting the troll, you find a helmet and a dagger, probably taken from some hapless adventurer",
  "add_item": [ "helmet", "enchanted_dagger" ],
  "add_item_count": { "gold_coin": 50 },
  "set_flag": { "old_gear_found" : true },
  "set_entity_state": { "troll": { "looted" : true } },
  "reveals": "Found gear belonging to another adventurer on a troll.",
}
```

ALL fields in a Result object are optional.

| Field               | Type     | Description                         |
|---------------------|----------|-------------------------------------|
| `narrative`         | string   | Narrative description of the result |
| `add_item`          | string[] | Add 1 of each item ID to inventory  |
| `add_item_count`    | object   | Item IDs → no. to add to inventory  |
| `remove_item`       | string[] | Remove 1 of each item ID from inv   |
| `remove_item_count` | object   | Item IDs → no. to remove from inv   |
| `set_flag`          | object   | Set flag IDs → values               |
| `set_room_state`    | object   | Room IDs → { fields → values }      |
| `set_entity_state`  | object   | Entity IDs → { fields → values }    |
| `alter_stat`        | object   | Stat IDs → `{ "mode": "delta"\|"set", "value": <int> }` |
| `set_player_location`| string  | Relocate player to given Room ID    |
| `player_damage`     | string   | Deal damage to player, e.g. `"1d4"` |
| `player_heal`       | string   | Heal player (clamped to max HP), e.g. `"2d4+2"` |
| `apply_status_effect`   | object   | Apply status effect: `{ "id": "poisoned", "rounds": 3, "target": "player" }` |
| `adjust_attitude`   | object   | NPC IDs → attitude deltas           |
| `reveals`           | string   | Update player knowledge (see below) |
| `then_check` | CheckResolution | Follow-up check (see below)         |
| `start_combat`      | string[] | Enter combat (see below)            |
| `game_over`         | GameOver | End the game (see below)            |

Notes:

- `narrative` briefs the GM but might not be used verbatim.

- All supplied fields are applied together; thus, a single Result can
  deal damage, set multiple flags, alter multiple state fields across
  several entities and rooms, add/drop items, etc.  Action-result
  changes and immediate-reaction changes are merged and applied
  atomically.  Deferred reactions (`room.entered`, `turn.end`, etc.)
  fire afterward and see the new state.

- During a check, `check.passed`/`check.failed` events and their
  immediate [Reactions](#reaction) fire before success/failure results
  are run.  These effects are then batched and processed before
  resolving any [follow-up checks](#check-resolution).

- `set_flag` sets global boolean flags.  A `false` value clears the
  flag; any truthy value sets it.

- `set_room_state` sets [Room](#room) state fields; `set_entity_state`
  sets [Entity](#entity) state fields.  Values must match the types
  declared in the room or entity's `state_field`.

- In `set_entity_state`, the special state field `location` denotes
  the locations of NPCs, features, and non-stackable items; values can
  be `"room:<room_id>"`, `"entity:<container_id>"`, or `null`.  See
  [Entity](#entity).  To move the player, use `set_player_location`.

- `alter_stat` keys are stat labels (e.g. `"STR"`); the mode, if
  omitted, defaults to `"delta"`.  Examples:
  - `{ "STR": { "value": -4 } }` decreases strength by 4
  - `{ "INT": { "mode": "set", "value": 3 } }` sets intelligence to 3

- `add_item` adds one of each listed item, while `add_item_count` adds
  specified amounts, e.g. `{ "coin": 50 }`.  For stackable items (see
  [Entity](#entity)), repeats are allowed and the total count is
  added.  Adding a non-stackable (i.e., singleton) item automatically
  removes it from any previous location.

- `remove_item` removes one of each listed item, with repeats removing
  multiple counts; `remove_item_count` removes specified quantities.
  The engine prevents removing more than exist.

- `player_damage` supports the normal damage syntax, plus `half(expr)`
  to deal half of `expr` rounded down (minimum 1), like `"half(1d8)"`.

- `apply_status_effect` applies a status effect to the `target` (`"player"` by
  default, or an entity ID): `{ "id": "poisoned", "rounds": 3 }`.  The
  status effect's behavior — duration, scope, and effects — comes from its
  definition in the [Status Effects](#status-effects) block (or the built-in
  defaults `poisoned`, `stunned`, `prone`).  Reapplication keeps the
  maximum of the existing and new remaining rounds.

```json
"success": { "narrative": "You resist the poison", "player_damage": "half(1d8)" },
"failure": { "narrative": "The poison burns", "player_damage": "1d8" }
```

- `adjust_attitude` is capped by the affected NPCs' `step_per_turn`
  for attitude changes.  See [NPC attitude](#npc-attitude).

- `reveals` appends to `soft_state.revealed_hints` (deduplicated) to
  guide the GM; see the [Soft State schema](soft-state.md).

- `start_combat` is only allowed on a Result inside an
  [EncounterRule](#encounter-rule).  If present, it triggers combat;
  the value specifies a list of entity IDs for additional combatants.
  For details, see [Aggro](#aggro) and [Mechanic](#mechanic).

- `game_over`, if present, [ends the game](#game-over).

---

### Check Resolution

A CheckResolution object implements multi-stage resolutions.  It can
be put in the `then_check` field of a [Result](#result), firing right
after the parent's other effects are applied.  It can also be used in
an NPC's combat block to describe the side-effects of hitting the
player; see [Combat](#combat).

Example: player makes a STR check to jump across a pit, and on failure
must make a DEX check to grab the ledge.  The `failure` Result in the
STR check contains the following `then_check`:

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

| Field            | Type      | Description                     |
|------------------|-----------|---------------------------------|
| `check`          | Check     | The check to resolve            |
| `skip_check_if`¹ | Condition | If present and true, skip check |
| `success`        | Result    | Result if follow-up succeeds    |
| `failure`¹       | Result    | Result if follow-up fails       |
| `tag`¹           | string    | Optional label (e.g. for logs)  |
> ¹ optional

Notes:

- Nested follow-ups are supported: a follow-up check's success/failure
  results may contain other follow-ups, to a maximum depth of 3.

- In combat, certain fields in the `success` and `failure` Results are
  prohibited; see [Combat](#combat) for details.

- `tag` is an optional descriptive label used in combat logs and
  narration; it has no mechanical effect.  It is surfaced as the
  `damage_type` of the on-hit log entry.

---

### Resolvable

A **Resolvable** describes a player-initiated action that can yield
custom effects: a special interaction with [Rooms](#room) and
[Entities](#entity), [examination](#examination), or engaging in an
[NPC dialogue path](#dialogue-path).  It is modeled as a
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

| Field            | Type      | Description                          |
|------------------|-----------|--------------------------------------|
| `id`¹            | string    | ID (depends on context)              |
| `description`¹   | string    | Human-readable description of action |
| `condition`¹     | Condition | Availability gate for the action     |
| `skip_check_if`¹ | Condition | Whether to bypass check and succeed  |
| `result`¹        | Result    | Fixed result (excl. with `check`)    |
| `check`¹         | Check     | Resolving check (excl. with `result`)|
| `success`¹       | Result    | Result when check succeeds/bypassed  |
| `failure`¹       | Result    | Result when check fails              |
| `using_results`¹ | UsageOverride | See [Usage Override](#usage-override)|
> ¹ optional by default (may be required in some contexts)

Notes:

- The meaning of `id` depends on where the Resolvable is used.  For
  room and entity interactions, the ID must be room-unique or
  entity-unique.  In other contexts, it need not be specified.

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

A GatedCheck object describes a player action meeting an obstacle: a
`take_check` for an item, or `traversal_check` for a room exit.  It is
modeled as a [Check](#check) along with a [Condition](#condition)
determining whether the check is active, an optional bypass condition,
and success/failure [Results](#result).

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

| Field            | Type      | Description                          |
|------------------|-----------|--------------------------------------|
| `gating`¹        | Condition | Whether the check is active          |
| `check`          | Check     | The Check to resolve (required)      |
| `skip_check_if`¹ | Condition | If present and true, bypass check    |
| `success`¹       | Result    | Result if check succeeds or bypassed |
| `failure`¹       | Result    | Result if check fails                |
| `using_results`¹ | UsageOverride | See [Usage Override](#usage-override)|
> ¹ optional

Notes:

- If `gating` is supplied and evaluates to false, the check is ignored
  (including `success`/`failure`), and the action proceeds normally.

- If the check is active and `skip_check_if` evaluates to true, the
  check automatically succeeds without rolling; in this case `success`
  (if present) *is* applied.

- If the check succeeds or fails, the original action automatically
  proceeds (e.g., sword taken from the stone), or fails (e.g., sword
  remains stuck), *in addition* to `success` and `failure`.

- `using_results`, if present, describes alternative resolutions when
  doing the action using items: see [Usage Override](#usage-override).

---

### Usage Override

A UsageOverride object, if placed in the optional `using_results`
field of a GatedCheck or Resolvable, handles player commands of the
form "[ACTION] using [ITEM]" for special items.  It maps each special
item's [entity ID](#entity) — or the `"*"` wildcard, matching any item
— to a resolution that overrides the usual GatedCheck or Resolvable.
An exact item-ID match takes precedence over the wildcard.  Each
resolution comprises either:

- an object with `"result"` keyed to a fixed [Result](#result); OR

- an object with `check`, and optional `success` and `failure`,
  defining an alternative [Check](#check).

An override replaces what it specifies and inherits what it omits:

- A check-bearing override resolves its own `check`.  Its `success`
  and `failure` branches, when present, replace the parent GatedCheck
  or Resolvable's branches; when absent, the parent's branches apply.

- A result-only override applies its `result` outright.  On a
  `traversal_check`, this counts as a success: the traversal proceeds
  and the result is applied.  On a Resolvable, the result replaces the
  usual resolution.

A Resolvable's `skip_check_if`, when present and true, takes
precedence over `using_results`: the obstacle is gone, so tools are
irrelevant.

---

### Encounter Rule

**Encounters** are set-piece game events like action sequences or
confrontations, which can unfold in different ways and possibly
culminate in combat or game-over.  They are triggered when an NPC
[aggros](#aggro), or as a [Mechanic](#mechanic).  An encounter
consists of an ordered array of EncounterRule objects of this form:

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

| Field            | Type      | Description                           |
|------------------|-----------|---------------------------------------|
| `condition`¹     | Condition | Condition for the rule to fire        |
| `result`¹        | Result    | Direct result (excl. with `check`)    |
| `check`¹         | Check     | Resolving check (excl. with `result`) |
| `skip_check_if`¹ | Condition | Whether to bypass `check` and succeed |
| `success`¹       | Result    | Result when Check succeeds            |
| `failure`¹       | Result    | Result when Check fails               |
> ¹ optional

When an encounter is triggered, its rules are evaluated in order. The
first rule with matching `condition` (if any) runs, with the rest
ignored.  This EncounterRule is resolved via its `result`, `check`,
`skip_check_if`, `success`, and/or `failure` fields, just like a
[Resolvable](#resolvable).  The resolved [Result](#result) may trigger
combat via `start_combat`, or game-over via `game_over`.

---

### Game-Over

A GameOver object specifies a win or loss outcome.

```json
{ "type": "lose", "trigger_id": "fell_into_pit" }
```

| Field        | Type   | Description                     |
|--------------|--------|---------------------------------|
| `type`       | string | `"win"` or `"lose"`             |
| `trigger_id` | string | Descriptor of game-over trigger |

In the final copy of the hard game state, `trigger_id` is saved to
`game_over.trigger` for debugging and player review.

---

## Room

A **Room** is a location in the adventure module, modeled as a node in
a world graph keyed by a globally-unique `room_id`.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when player enters or examines room)",
    "contains": ["<entity_id>", {"<entity_id>": <count>}, ...],
    "soft_item_guidance": "freeform description of generic items in room",
    "exits": [ { /* exit */ } ],
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "is_start_room": false,
    "reactions": [ { /* reaction */ } ],
    "state_fields": { "<field_name>": { "type": "boolean|number|string", "description": "string", "initial": <value> } }
  }
}
```

| Field            | Type         | Description                     |
|------------------|--------------|---------------------------------|
| `name`           | string       | Short display name              |
| `description`    | string       | Prose description (for GM)      |
| `contains`¹ | string/object[] | IDs/counts of entities in room at start |
| `exits`¹         | Exit[]       | All exits out of the room       |
| `state_fields`¹  | object       | `{ "<field>": <spec>, ...  }`   |
| `interactions`¹  | Resolvable[] | Special interactions (see below)|
| `on_examine`¹    | array        | See [Examination](#examination) |
| `reactions`¹     | Reaction[]   | See [Reaction](#reaction)       |
| `soft_item_guidance`¹ | string  | Plausible generic items in room |
| `is_start_room`¹ | boolean      |`true` for starting room only    |
> ¹ optional

Notes:

- The `name` string is used as the room's in-game UI label, whereas
  `description` briefs the GM on the characteristics of the room (but
  is not necessarily used verbatim in narration).

- The `contains` field lists the entities *directly* present in the
  room at game start.  "Directly" means that if room R contains entity
  A, and A contains another entity B (see [Entity](#entity)), R's
  `contains` should list A but not B.  As an exception, the player
  entity must be omitted, even if this is the starting room.

  Each list entry is either an object `{ "<entity_id>": <count> }`, or
  an entity ID (count = 1).  Each count must be positive, and a
  non-item entity or non-stackable item must have total count 1.

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
  - INIT (optional) is the value at game start, which must match the
    declared type.  If omitted, the default is `false` (boolean), `0`
    (number), or `""` (string).

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

- `soft_item_guidance`, if specified, should be a freeform string
  describing the nondescript ("soft") items within this room,
  e.g. `"pebbles, leaves, and branches lie scattered on the floor"`.
  This guides the GM as to what plausible soft items can be surfaced
  in the room.  It is advisory only: depending on the gameplay
  context, the GM may accept or reject this guidance.  For more
  details, see the [Soft State schema](soft-state.md).

### Exit

**Exit** objects are modelled as follows:

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

| Field              | Type       | Description                      |
|--------------------|------------|----------------------------------|
| `id`               | string     | Exit ID (room-unique)            |
| `direction`        | string     | Human-readable exit label        |
| `target_room`      | string     | Room ID of destination           |
| `condition`¹       | Condition  | Gating condition (see below)     |
| `traversal_check`¹ | GatedCheck | See [Gated Check](#gated-check)  |
| `one_way`¹         | boolean    | Indicates if exit is one-way     |
> ¹ optional

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

| Field           | Type      | Description                       |
|-----------------|-----------|-----------------------------------|
| `rigorous_only` | boolean   | Whether rigorous search is needed |

Notes:

- To form the narration for what the examination reveals, the GM looks
  at the `narrative` in the [Result](#result) delivered by the
  Resolvable.  The Result can also impose other side-effects, such as
  setting flags to track the player's information.

- `id`, `description`, and `using_results` need not be supplied, and
  their effects on examination actions are undefined.

- When multiple `on_examine` events fire during a single examination,
  each event's `condition` is evaluated against the state as it was
  *before* the examination began: the effects of an earlier event in
  the same examination (e.g., setting a flag) do not unlock a later
  event.  Chained discoveries that are supposed to require a second
  look therefore work naturally — gate the deeper discovery on the
  flag or state set by the first one, and the player must examine
  again to get it.

## Reaction

**Reactions** are a flexible mechanism to change game state in
response to specified events.  They can be placed in the `reactions`
array of a [Room](#room), [Entity](#entity), or [Mechanic](#mechanic)
– the **scope** of the reaction.

The scope determines when the reaction is active (i.e., can be
triggered).  Room-scoped reactions are active when the player is in
the room; entity-scoped reactions are active when the entity is in the
present room *and* (for NPCs) alive; mechanic-scope
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

| Field        | Type          | Description                           |
|--------------|---------------|---------------------------------------|
| `id`         | string        | Reaction ID, unique in scope          |
| `on`         | string        | The [reaction trigger](#event)        |
| `condition`¹ | Condition     | Activation condition for reaction     |
| `effect`     | ReactionEffect|  What it does when triggered          |
| `once`¹      | boolean       | Whether it is one-off; default false  |
| `phase`¹     | string        | `"deferred"` (default) / `"immediate"`|
| `priority`¹  | integer       | Lower = fires earlier; default `0`    |
> ¹ optional

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

- The **trigger string** (the `on` field) – this, together with the
  Reaction's scope (room/entity/mechanic) sets the initial trigger.

  For example, suppose a Reaction K has `"on": "room.entered"`.  If K
  is in a room R, the trigger is the player entering R.  If K is in an
  entity E, the trigger is the player entering any room where E is
  directly present (see [Room](#room)).

- The **event context** – a flat map of details about the event.  For
  example, a `"room.entered"` trigger provides the context key
  `room_id`: the ID of the room entered.

  The Event Context can be accessed by Condition blocks in the
  Reaction using the `event` [Condition String](#condition-string)
  domain (this domain is only valid during reaction dispatch).  This
  allows (say) a `condition` to narrow down when the reaction fires.

Example: a goblin NPC attacks on sight, but only in a given room.

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

| Trigger                 | Context                                    |
|-------------------------|--------------------------------------------|
| `room.[entered\|exited]`| `room_id`                                  |
| `traversal.[attempted\|succeeded]`| `exit_id`, `from_room`, `to_room`|
| `traversal.failed`      | `exit_id`, `from_room`                     |
| `interaction.used`      | `interaction_id`,`target_id`, `using_item?`|
| `flag.[set\|cleared]`   | `flag_id`                                  |
| `entity_state.changed`  | `entity_id`, `field`, `new_value`          |
| `room_state.changed`    | `room_id`, `field`, `new_value`            |
| `dialogue.[started\|ended]` | `npc_id`, `reason?`                    |
| `combat.started`        | `combatant_ids`                            |
| `combat.ended`          | `reason` (`victory\|defeat\|fled`)          |
| `item.acquired`         | `item_id`, `source`                        |
| `item.lost`             | `item_id`, `reason`                        |
| `equipment.changed`     | `added?`, `removed?`                       |
| `attitude.changed`      | `npc_id`, `old_value`, `new_value`, `delta`|
| `stat.changed`          | `stat_name`,`old_value`,`new_value`,`delta`|
| `player.[damaged\|healed]` | `amount`, `new_hp`                      |
| `encounter.branched`    | `encounter_id`, `branch`                   |
| `turn.[start\|end]`     | `turn_number`                              |

For the full list, and full documentation of the context keys, see the
[Events schema doc](events.md).

### Reaction Effect

A ReactionEffect object is stored in a reaction's `effect` field, and
describes what the reaction does if successfully triggered:

```json
{
  "result": { /* Result object (same as interaction results) */ },
  "trigger_encounter": "<mechanic_id or entity_id>",
  "trigger_dialogue": "<npc_entity_id>"
}
```

It must contain at least one of the following fields (if more than one
is supplied, they all apply):

| Field               | Type   | Description                     |
|---------------------|--------|---------------------------------|
| `result`            | Result | A [Result](#result) to run      |
| `trigger_encounter` | string | Mechanic or entity ID           |
| `trigger_dialogue`  | string | NPC entity ID to start dialogue |

Note: For `trigger_[encounter|dialogue]`, the `"self"` value resolves
to the owning entity's ID (for entity-scoped reactions).

Example: trap fires if it's armed when the player enters the room.

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

**Entities** are objects that appear in rooms or inventory.

The entity ID `"player"` is **reserved** for the player character.
No other entity may use this ID.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | item",
    "name": "string (required for item, optional otherwise)",
    "description": "string",
    "soft_item_guidance": "freeform description of generic contents",
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

| Field           | Type     | Description                          |
|-----------------|----------|--------------------------------------|
| `type`          | enum     | `player|feature|npc|item`            |
| `description`   | string   | Canonical prose description          |
| `tags`¹         | string[] | Array of semantic tags               |
| `contains`¹ | string/object[] | IDs/counts of entities in this entity at start |
| `interactions`¹ | Resolvable[] | Special interactions (see below) |
| `on_examine`¹   | array    | See [Examination](#examination)      |
| `reactions`¹    | array    | See [Reaction](#reaction)            |
| `state_fields`¹ | object   | `{ "<field>": <spec>, ...  }`        |
| `soft_item_guidance`¹ | string | Guidance on soft items in entity |
> ¹ optional

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

- `interactions` is an array of [Resolvables](#resolvable) listing
  non-generic actions on the entity.  Each must have an entity-unique
  `id`.  The spec is the same as for [Room](#room) interactions.

- `state_fields` lists various mutable aspects of the entity's state.
  They are labeled by entity-unique IDs.  There are several reserved
  state fields, which need NOT be declared here, unless the author
  wants to override the default initial value with something else:

|Res. Field  |Type        | Init Value | Description                        |
|------------|------------|------------|------------------------------------|
|`alive`     |boolean     | `true`     | Entity active? false => reactions off for NPCs |
|`location`  |string\|null| derived    | `room:x`, `entity:y`, or `null`    |
|`attitude`  |integer     | `0`        | NPC disposition; higher=friendlier |
|`hidden`    |boolean     | `false`    | Explicit concealment (see below)   |
|`following` |boolean     | `false`    | NPC follows player between rooms   |
|`current_hp`|number      | `combat.hp`| Current hit points (for combat)    |
|`open`      |boolean     | `false`    | Container open/closed state        |

  The `location` state field is special: it is only valid for NPCs,
  features, and non-stackable items, and is managed by the engine via
  the containment relationships in the game state.  It should NOT be
  declared in `state_fields`; initial values are derived from the
  `contains` fields on rooms and entities.  Like other state fields,
  `location` can be queried (e.g., `entity:bob.location == room:parlor`
  in a [condition string](#condition-string)) and mutated
  (e.g., `"set_entity_state": { "gem": {"location": "entity:chest"}}`
  in a [Result](#result)).  The special location `null` means the
  entity is currently inaccessible (e.g., an NPC that's fled).

  The `hidden` state field declares concealment (e.g., a lurking
  enemy, or a sword buried in rubble).  When `true`, the engine omits
  the entity from the scene.  DO NOT apply `hidden` to an entity just
  because it is inside a closed [container](#container); that should
  be controlled by the container's `open` state.

  Any other state field needed by the adventure (`cursed`, etc.)
  should be listed in `state_fields`, keyed by an ID and with value

    `{ "type": TYPE, "description": DESC, "initial": INIT }`

  where

  - TYPE is one of `"boolean"`, `"number"`, or `"string"`
  - DESC is a string describing the nature of the state field
  - INIT (optional) is the value at game start, which must match TYPE.
    If omitted, a reserved field uses its aforementioned default,
    while a custom field defaults to `false` (boolean), `0` (number),
    or `""` (string).

- `soft_item_guidance`, if specified, should be a freeform string
  describing the nondescript ("soft") items contained within this
  entity.  Like the identically-named field in Room objects, its role
  is advisory and not binding on the GM.

### Feature

**Features** are immovable environmental objects.  The player cannot
pick up, talk to, or attack features.

Features, unlike NPC and item entities, may span multiple rooms: e.g.,
the sky can be a single feature visible from different locations.
Just list the feature's entity ID in the `contains` field of each room
where it appears.

#### Container

**Containers** are entities such as chests or wardrobes, which store
other entities and can be opened and/or closed.  We document
containers here since they are commonly implemented as features, but
items or even NPCs are also allowed to be containers.

Containers should be assigned the following properties:

- `container` tag — A container must have `"container"` in its `tag`
  array.  This informs the engine to handle them specially.

- `open` state field — A container must have the boolean state field
  `open`, initialized to `true` (open) or `false` (closed, default).
  For entities without the `container` tag, `open` has no special
  meaning.

- `open` and `close` interactions (optional) — should be defined if
  the player can perform direct open/close actions (as opposed to
  indirect methods, like pressing a button elsewhere).

A container's initial contents are declared in its `contains` field.
Note that this field can also be used for non-container entities, like
a rubbish pile, which is not a container in the present sense as it
lacks open/close functionality.

When the container is open, the engine automatically surfaces its
contents to the GM and player; when closed, the contents are
inaccessible.  This is distinct from the `hidden` state.

### Item

**Items** are entities that can potentially be picked up by the
player.  The player cannot talk to or attack items.

Items with the `"stackable"` tag are non-singleton entities; they can
have multiple indistinguishable instances tied to the same entity ID,
which may exist (either individually or in multiples) in the player's
inventory, rooms, or other entities.  Such items support multi-copy
transfers in [Results](#result) and player actions, and quantity
comparisons in conditions (e.g. `inventory:coin >= 30`).

| Field          | Type       | Description                  |
|----------------|------------|------------------------------|
| `name`         | string     | Display name (required!)     |
| `take_check`¹  | GatedCheck | Obstacle to taking the item  |
| `equip_block`¹ | object     | For equipment (see below)    |
| `consumable`¹  | object     | For consumables (see below)  |
| `max_stack`¹   | interger   | Stack cap for stackable item |

> ¹ optional

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

- `consumable`, if present, marks the item as usable (potion, scroll,
  food).  It holds `{ "heal": "2d4+2", "cure_status_effects": ["poisoned"],
  "destroy": true }`: `heal` is a dice expression of HP restored
  (clamped to max HP), `cure_status_effects` lists combat status effects removed
  on use, and `destroy` (default `true`) consumes one count per use.
  In combat the player uses consumables via the `use_item` combat
  action.

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

| Field                | Type     | Description                   |
|----------------------|----------|-------------------------------|
| `equip_tags`         | string[] | Category tags (see below)     |
| `incompatible_with`¹ | string[] | Conflicting tags (see below)  |
| `stat_effects`¹      | object   | Stat modifiers while equipped |
| `max_equipped`¹      | integer  | How many such items can stack |
| `damage_expr`¹       | string   | Weapon damage, e.g. `"1d8+1"` |
| `hit_bonus`¹         | integer  | Weapon attack bonus           |

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
| `ac_override` | integer | Set AC to this value; highest takes effect |
| `ac_bonus`    | integer | Added to base AC (default 0); stacks       |

### NPC

**NPCs** (non-player characters) are entities the player can fight or
socialize with.  NPC entity blocks support these additional fields:

| Field           | Type   | Description                              |
|-----------------|--------|------------------------------------------|
| `dialogue`¹     | object | NPC's [dialogue settings](#dialogue)     |
| `aggro`¹        | array  | NPC's [aggro rules](#aggro)              |
| `follower`¹     | object | NPC's [follower rules](#follower)        |
| `combat`¹       | object | NPC's [combat stat block](#combat)       |
| `combat_group`¹ | string | See [combat groups](#combat-groups)      |
> ¹ optional

#### Dialogue

The `dialogue` field on an NPC entity specifies how the NPC converses.

```json
{
  "guidelines": "The Jester speaks in riddles, puns, and jibes. He gamely offers himself as the butt of jokes. Yet he's smarter than he looks, and knows much about the goings-on at court. He is fundamentally loyal to the King and will never agree to betray him.",
  "on_meeting": "The Jester hoots when he sees the player, waving and laughing hysterically",
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

| Field             | Type   | Description                         |
|-------------------|--------|-------------------------------------|
| `guidelines`      | string | Tone, demeanor, constraints, etc.   |
| `attitude_limits`¹| object | NPC's attitude bounds (see below)   |
| `on_meeting`¹     | string | Describes behavior on first meeting |
| `will_reveal`¹    | object | See [NPC Knowledge](#npc-knowledge) |
| `dialogue_paths`¹ | Resolvable[] | See [Dialogue Path](#dialogue-path) |
> ¹ optional

Notes:

- `guidelines` is a static freeform prose string that briefs the GM on
  how the NPC should act in conversation throughout the adventure:
  tone, demeanor, what they know, what they will and will not agree
  to, what bits of knowledge they do and do not know, etc.

- `on_meeting`, if present, describes the NPC's canonical reaction
  when first encountered.  The GM may not use this verbatim, but will
  not contradict it.

- `attitude_limits`, if present, sets the NPC's engine-enforced
  numerical attitude limits.  This should be an object with supported
  fields `min` (default 0), `max` (default 0), `initial` (default 0),
  and `step_per_turn` (default 1).  All fields are optional.

  Warning: the defaults freeze the NPC's attitude — with `min` and
  `max` both 0, no attitude change is possible.  Declare explicit
  bounds for any NPC whose attitude can shift.  `step_per_turn` caps
  the magnitude of each single attitude change (each GM proposal and
  each `adjust_attitude` effect), not the number of changes per turn.

  Example: a troll whose hostility can vary, but never turns friendly:
  `"attitude_limits": { "min": -10, "max": -1 }`.

#### Dialogue Path

A **dialogue path** is a special line of conversation that may trigger
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
dialogue path.  The other fields specify the mechanics: gating
condition, check, and/or branching outcomes.

#### NPC Knowledge

The `will_reveal` field describes discrete pieces of knowledge an NPC
can share with the player.  It should be an object keyed by topic IDs
(entity-unique), with value objects having following fields:

| Field          | Type     | Description                              |
|----------------|----------|------------------------------------------|
| `description`  | string   | What the topic reveals; surfaced to GM   |
| `conditions`   | string[] | Revelation conditions (all must be true) |
| `set_flag`¹    | object   | `{ "<flag_id>": <value>, ... } `         |
| `set_entity_state`¹ | object| `{ "<entity_id>": { "<field>": <value>, ...}, ...}` |
> ¹ optional

`conditions` may be an empty list, in which case the topic is always
available for the GM to narrate when the conversation allows.

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

### Combat

The `combat` field on an NPC entity holds a stat block for multi-round
combat.  Without this block, an NPC can only participate in encounters
that resolve directly.  The block's contents are system-dependent;
those for `5e` (the one currently implemented) are documented here.

See the [Combat System docs](../doc/combat.md) for more details about
the turn-based combat subsystem.

```json
"combat": {
  "hp": 18,
  "ac": 13,
  "atk": 5,
  "dmg": "1d8+3",
  "initiative_mod": 3,
  "flee_dc": 12,
  "on_hit_effects": [
    {
      "check": {
        "type": "stat_check",
        "stat": "CON",
        "target": 11,
        "save": true,
        "repeatable": false
      },
      "tag": "poison",
      "success": {
        "narrative": "You resist the poison.",
        "player_damage": "half(1d8)"
      },
      "failure": {
        "narrative": "The poison burns in your veins.",
        "player_damage": "1d8"
      }
    }
  ]
}
```

| Field            | Type       | Description                          |
|------------------|------------|--------------------------------------|
| `hp`             | integer    | Maximum hit points (must be >= 1)    |
| `ac`             | integer    | Armor class (must be >= 0)           |
| `initiative_mod`¹| integer    | Initiative modifier; default `0`     |
| `flee_dc`¹       | integer    | DC for player flee; default `10`     |
| `atk`            | integer    | Attack bonus for the NPC's attack    |
| `dmg`¹           | string     | Damage expression; default `"1d6"`   |
| `dmg_type`¹      | string     | E.g. `"piercing"`; default untyped   |
| `resistances`¹   | string[]   | Damage types the NPC resists         |
| `vulnerabilities`¹| string[]  | Damage types the NPC is weak to      |
| `immunities`¹    | string[]   | Damage types the NPC is immune to    |
| `on_hit_effects`¹| CheckResolution[] | On-hit effects; default `[]`  |
| `attacks`¹       | AttackDef[]| Named attack options (see below)     |
| `multiattack`¹   | string[]   | Ordered attack ids used each turn    |
| `abilities`¹     | string[]   | IDs of NPC's [Abilities](#abilities) |
| `save_bonus`¹    | integer    | Flat save modifier; default `0`      |
| `ai`¹            | CombatAI   | Rule-of-thumb combat AI; see below   |
> ¹ optional

Damage types are identified by name; 5e by default uses acid,
bludgeoning, cold, fire, force, lightning, necrotic, piercing, poison,
radiant, slashing, and thunder.  Damage type resistance halves damgage
(rounded down); vulnerability doubles damage; and immunity reduces all
damage to 0.  These modifiers apply to typed damage from player
weapons (`EquipBlock.damage_type`) and from NPC attackers alike;
untyped damage is never mitigated.

#### Attack definitions and multiattack

An NPC's per-turn attacks come in two forms:

- **Basic attack** (default): one attack per turn built from the
  block-level `atk` / `dmg` / `on_hit_effects`.
- **Attack definitions**: an `attacks` list of named options, plus an
  optional `multiattack` sequence (ids may repeat) performed each turn:

```json
"combat": {
  "hp": 20, "ac": 13,
  "attacks": [
    { "id": "bite", "name": "bites", "atk": 5, "dmg": "1d8+2",
      "dmg_type": "piercing",
      "on_hit_effects": [ /* CheckResolution, combat-safe */ ] },
    { "id": "claw", "name": "claws", "atk": 5, "dmg": "1d6+2" }
  ],
  "multiattack": ["claw", "claw", "bite"]
}
```

Each attack definition has `id`, `atk`, and optional `name` (a verb
phrase for narration, e.g. `"bites"` — defaults to `id`), `dmg`,
`dmg_type`, and `on_hit_effects`.  Without `multiattack`, the NPC makes
a single attack (the first entry of `attacks`).  If the target drops
mid-sequence, the remaining attacks are lost.

When `attacks` is present, block-level `on_hit_effects` is forbidden
(each attack carries its own) and block-level `atk` is optional.

Notes:

- For NPC, all combat stats are pre-determined in the corpus; the
  engine does not derive them dynamically.

- Any NPC with a `combat` block MUST also have a `current_hp`
  declaration in its `state_fields` (see [Entity](#entity)).  The
  engine initializes `current_hp` to the block's `hp` at game start.
  When an NPC's `current_hp` drops to 0, the engine automatically sets
  the `alive` state field to `false` and drops it out of combat.

  To override this default death behavior — e.g., an NPC that falls
  unconscious at 0 HP instead of dying — note that entity-scoped
  reactions cannot fire once `alive` is `false`.  Use a mechanic-scope
  (global) reaction on `entity_state.changed` watching
  `event:entity_id`, `event:field == current_hp`, and
  `event:new_value <= 0`, and have its result restore `alive: true`
  along with whatever custom state applies.

- When the player's HP drops to ≤ 0, combat ends immediately (no
  further hostile actions that round) and the `player.died` event
  fires (see [Events](events.md#player-death)): if no reaction
  restores HP above 0, the game ends with
  `{ "type": "lose", "trigger": "player_death" }`.  No corpus entry
  is needed for this.

- `initiative_mod` is added to the NPC's initiative roll to determine
  turn order.

- `flee_dc` is a check target for player to flee when fighting this
  NPC; the highest `flee_dc` among hostile combatants applies.

- `dmg` supports dice notation (`"1d8+3"`) or flat values (`"3"`).

- `on_hit_effects`, if supplied, should be a list of
  [CheckResolution](#check-resolution) objects.  Each effect resolves
  immediately after the NPC lands a hit on the player.  The `check` is
  typically a `stat_check` saving throw; the `success` and `failure`
  branches are [Results](#result) restricted to a combat-safe subset.

  The following fields are presently **prohibited** in on-hit results:
  - `add_item`
  - `add_item_count`
  - `remove_item`
  - `remove_item_count`
  - `set_entity_state`
  - `set_room_state`
  - `adjust_attitude`
  - `set_player_location`
  - `start_combat`

#### Combat AI

The optional `ai` block configures the engine's deterministic,
rule-of-thumb combat AI for the NPC.  NPC decisions never involve the
LLM.

```json
"ai": {
  "targeting": "last_attacker",
  "flee_below_hp_pct": 25,
  "passive": false,
  "ability_rules": {
    "breath": { "cooldown_rounds": 2, "use_below_own_hp_pct": 50 }
  }
}
```

| Field               | Type    | Description |
|---------------------|---------|-------------|
| `targeting`¹        | string  | Target selection rule: `"last_attacker"` (default), `"player"`, `"lowest_hp"`, or `"random"` |
| `flee_below_hp_pct`¹| integer | Flee when current HP% falls below this value (1–99); default: never flee |
| `passive`¹          | boolean | Take no actions in combat; default `false` |
| `ability_rules`¹    | object  | Per-ability usage rules (only for abilities listed in `CombatBlock.abilities`): `{ "ability_id": { "cooldown_rounds": 2, "use_below_own_hp_pct": 50 } }` |

Notes:

- `targeting` selects among living opponents: `"last_attacker"` attacks
  whoever landed the most recent hit on the NPC (enemies fall back to
  the player); `"player"` always attacks the player (meaningful for
  enemies only); `"lowest_hp"` attacks the weakest living opponent;
  `"random"` picks a random living opponent.
- Without an `ai` block, enemies use `last_attacker` (in solo combat
  this is always the player, preserving the original behavior), and
  allies attack the player's most recent target, then their own last
  attacker, then the weakest enemy.
- Fleeing removes the NPC from combat and sets its engine-owned `fled`
  entity state to `true`; if it was the last living enemy, combat ends.
  Only enemies flee — allies never do.
- `passive` NPCs join combat (they can be targeted and hurt) but never
  act — suitable for cowering civilians or bystanders.  A declared
  `passive` entity state overrides this default at runtime (e.g. set to
  `false` by a `set_entity_state` result when the player persuades the
  NPC to fight).
- `ability_rules`: `cooldown_rounds` makes an ability unusable for that
  many rounds after each use; `use_below_own_hp_pct` only allows it
  while the NPC is below the given HP percentage.

### Aggro

The `aggro` field on an NPC entity specifies how an NPC reacts in
hostile confrontations.  It stores an Encounter – an ordered list of
[EncounterRules](#encounter-rule) – that is triggered automatically
when the player attacks the NPC, or triggered explicitly by a
[reaction effect](#reaction-effect) with `trigger_encounter`
specifying the host NPC's entity ID.

Example: confronting an orc, if the player is unarmed and fails a STR
check (DC 10), the orc kills the player; otherwise, combat begins.

```json
"aggro": [
  {
    "condition": { "require": "tag:weapon" },
    "result": { "narrative": "Brandishing your weapon, you fight the orc.",
				"start_combat": [] },
  },
  {
    "check": { "type": "stat_check",
               "stat": "STR", "target": 10, "repeatable": true },
    "success": { "narrative": "Putting up your fists, you start to fight!",
				 "start_combat": [] },
    "failure": { "narrative": "Without a weapon, the orc overpowers you.",
                 "game_over": { "type": "lose", "trigger_id": "orc" } }
  }
]
```

If no EncounterRule matches, the encounter is a no-op (no narrative,
effects, combat, or game-over).  To avoid this, put a rule with no
`condition` (or `"condition": {"require": "true"}`) as the last entry.

If the encounter resolves to a Result with non-null `start_combat`,
that launches combat against the following NPCs:
- the host NPC of the `aggro` rule, PLUS
- any additional NPCs with entity IDs listed in `start_combat`
  (none if `start_combat` is `[]`), PLUS
- NPCs in the same `combat_group` as any of the preceding ones
The set of combatants is then filtered to living and present NPCs with
defined `combat` blocks.

### Combat groups

NPCs with the same `combat_group` value behave as a single band in
combat.  If the player attacks any present living member (or combat is
triggered with any member via an encounter), that pulls in every other
present living member of that group as a hostile combatant.

Followers (see below) are treated as allies, and excluded from
auto-inclusion as a hostile combatant even if they share the tag.
However, a follower may still enter combat by being attacked directly.
Conversely, when combat begins, every present living follower that has
a `combat` block automatically joins the player's side as an **ally**
(see [Combat AI](#combat-ai)).

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

## Abilities

The top-level `abilities` block defines named **combat abilities** —
spells, class features, and monster powers — usable by the player (via
the `use_ability` combat action when listed in the character sheet's
`abilities`) and by NPCs (via `CombatBlock.abilities` and the combat
AI).  Each ability has exactly one effect: `attack`, `save`, or
`heal`.

```json
"abilities": {
  "fire_bolt": {
    "name": "Fire Bolt",
    "description": "A mote of fire hurled at a foe.",
    "target": "enemy",
    "uses_per_combat": -1,
    "attack": { "stat": "INT", "proficient": true, "damage": "1d10", "damage_type": "fire" }
  },
  "poison_spray": {
    "name": "Poison Spray",
    "target": "enemy",
    "uses_per_combat": 1,
    "save": {
      "stat": "CON", "dc": 12, "damage": "1d12", "damage_type": "poison",
      "half_on_success": true,
      "apply_status_effect_on_failure": { "id": "poisoned", "rounds": 3 }
    }
  },
  "cure_wounds": {
    "name": "Cure Wounds",
    "target": "ally",
    "uses_per_combat": 2,
    "heal": "1d8+2"
  }
}
```

| Field             | Type    | Description |
|-------------------|---------|-------------|
| `name`            | string  | Display name |
| `description`¹    | string  | Flavor text for briefings |
| `target`          | string  | `"self"`, `"ally"` (a same-side combatant), or `"enemy"` |
| `uses_per_combat`¹| integer | Uses allowed per combat; `-1` (default) = unlimited |
| `attack`¹         | object  | Attack-roll effect (exactly one effect allowed) |
| `save`¹           | object  | Save-based effect |
| `heal`¹           | string  | Healing dice expression (only for `self`/`ally` targets) |

**Attack effects**: `{ "stat": "INT", "proficient": true, "damage":
"1d10", "damage_type": "fire" }`.  Player casters roll with the named
ability score's modifier plus proficiency bonus (when `proficient`);
NPC casters use their combat block's `atk` bonus instead.  Crits,
fumbles, and damage-type mitigation apply as for weapon attacks.

**Save effects**: `{ "stat": "CON", "dc": 12, "damage": "1d12",
"damage_type": "poison", "half_on_success": true,
"apply_status_effect_on_failure": { "id": "poisoned", "rounds": 3 } }`.
The target saves — the player with the usual stat modifier and save
proficiencies, NPCs with `d20 + save_bonus`.  On success the damage is
halved (`half_on_success`) or negated; on failure the full damage
(`""` = no damage) and any status effect apply.

## Status Effects

The top-level `status_effects` block defines **status effects** —
poison, stun, curses, and similar effects — declared per-status-effect
rather than hardcoded.  The block maps status effect IDs to definitions;
the dict key is the canonical ID used by `apply_status_effect`,
`cure_status_effects`, events, and queries (`name` is a cosmetic display
name).

```json
"status_effects": {
  "trap_poison": {
    "name": "Trap Poison",
    "description": "Weakness from a poisoned needle; ticks down per turn.",
    "scope": "persistent",
    "duration": "rounds",
    "tick_effect": { "player_damage": "1" },
    "system_effects": { "5e": { "disadvantage_on_attack": true } }
  }
}
```

| Field             | Type    | Description |
|-------------------|---------|-------------|
| `name`¹           | string  | Display name (the dict key is the canonical ID) |
| `description`¹    | string  | Flavor/mechanics text for briefings |
| `scope`¹          | string  | `"combat"` (default) or `"persistent"` |
| `duration`¹       | string  | `"rounds"` (default), `"until_cleared"`, or `"until_turn_start"` |
| `skip_turn`¹      | boolean | Afflicted combatant loses its turn (default `false`) |
| `tick_effect`¹    | Result  | Applied on each tick (player only; see below) |
| `system_effects`¹ | object  | Per-RPG-system roll modifiers (see below) |

Scope and duration combine into the status effect's lifetime:

- `scope: "combat"` — ticks at the start of the afflicted combatant's
  turn; cleared when combat ends.
- `scope: "persistent"` — ticks on `turn.end`, i.e. once per
  turn-costing player action (not during dialogue or free actions);
  survives combat end.
- `duration: "rounds"` — decrements on each tick, expires at zero.
- `duration: "until_turn_start"` — removed on the afflicted's first
  tick (legacy `prone` behavior).
- `duration: "until_cleared"` — never ticks down; removed only by
  curing (`cure_status_effects`), combat end (combat-scoped), or a manual
  Result.

Scope is per-definition: a combat poison and a trap poison are two
definitions with distinct IDs (e.g. `poisoned` vs. `trap_poison`), so
each ID has one unambiguous lifetime.

`system_effects` maps a system key (`"5e"`) to that system's roll
modifiers.  For 5e the recognized keys are `disadvantage_on_attack`
(attacker side of an attack roll), `advantage_against` (target side of
an attack roll), and `advantage_on_ability_checks` /
`disadvantage_on_ability_checks` (ability checks, including skill
checks and flee checks — but not saving throws, which are not ability
checks in 5e).

`tick_effect` is a [Result](#result) applied on each of the status
effect's ticks, but only when the afflicted target is the player
(`Result` has player-targeted damage/heal fields only); a
`tick_effect` on an entity-afflicted status effect is ignored.

Three **built-in defaults** are always present; a corpus entry with
the same ID replaces the default wholesale (no field-level merge):

| ID        | Scope  | Duration           | skip_turn | 5e system effects |
|-----------|--------|--------------------|-----------|-------------------|
| `poisoned` | combat | `rounds`          | no        | `disadvantage_on_attack`, `disadvantage_on_ability_checks` |
| `stunned`  | combat | `rounds`          | yes       | `advantage_against` |
| `prone`    | combat | `until_turn_start` | no       | `disadvantage_on_attack`, `advantage_against` |

Applying a status effect the target already has sets its remaining rounds
to the maximum of the existing and new values.  Applying an undefined
status effect ID works at runtime (adventures may forward-declare), but
the validator warns about it.  Status-effect changes emit
`status_effect.applied` / `status_effect.ticked` / `status_effect.cleared` events
(see [events.md](events.md)); `entity_state.changed` does not fire for
them.

## Mechanic

**Mechanics** are named bundles of game logic not tied to a specific
room or entity.  They live in an object in the Corpus' top-level
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

| Field        | Type            | Description                   |
|--------------|-----------------|-------------------------------|
| `condition`¹ | Condition       | An encounter-gating condition |
| `rules`¹     | EncounterRule[] | A triggerable encounter       |
| `reactions`¹ | Reaction[]      | A set of global reactions     |
> ¹ optional (subject to constraints below)

There are two kinds of mechanics:

- An **encounter mechanic** describes a set-piece confrontation or
  action sequence.  It must have `rules`, storing an ordered list of
  [EncounterRule objects](#encounter-rule).  It must be triggered by
  `trigger_encounter` in a [reaction effect](#reaction-effect).  Once
  triggered, `rules` is evaluated top-to-bottom, and the first
  matching rule is run; if no rule matches, none is run.

  `condition`, if supplied, is a gating condition: when the mechanic
  is triggered, `condition` is evaluated first, and if it is `false`
  the encounter is cancelled (i.e., `rules` is ignored).

  Each encounter can only run once per turn.  If a reaction triggers
  an encounter that already ran this turn, the second trigger is
  ignored.  However, encounters can trigger other encounters, up to a
  depth-5 limit.

  Each EncounterRule's Result can trigger combat by specifying
  `start_combat` with an array of hostile combatants (NPC entity IDs).
  Note: unlike in an NPC [aggro block](#aggro), there is no default
  combatant.  The initial list is expanded to add any other NPCs in
  the same `combat_group`(s), then filtered to living and present NPCs
  with `combat` blocks.  If the final list is empty, no combat occurs.

  An encounter mechanic may also carry `reactions`, handled in the
  same way as a Reaction-Only Mechanic (see below).  This lets an
  encounter mechanic store its own global trigger: a reaction that
  fires `trigger_encounter` with the mechanic ID.  More often,
  however, encounter mechanics omit `reactions` and are triggered by
  separately-defined room or entity reactions.

- A **reaction-only mechanic** carries only `reactions`: a list of
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

| Field         | Type      | Description                       |
|---------------|-----------|-----------------------------------|
| `condition`   | Condition | Predicate polled each turn        |
| `type`        | string    | `"win"` or `"lose"`               |
| `trigger_id`  | string    | Descriptor for game-over trigger  |
| `narrative`¹  | string    | Canonical ending narration        |
> ¹ optional

The engine polls `condition` once per turn, after all reactions have
settled.  The first entry with `condition` evaluating to `true` ends
the game using `type` and `trigger_id` as the [GameOver](#game-over)
parameters, and with `narrative` (optional) as the ending narration.

Note: player death by HP loss needs no entry here.  Whenever the
player's HP drops to 0 or below, from any source, the `player.died`
event fires (see [Events](events.md#player-death)); if no reaction
restores HP above 0, the game ends with
`{ "type": "lose", "trigger": "player_death" }`.

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

RPG systems track a large set of player data (level, AC, hit points,
etc.).  We store this in the game's [Hard State](hard-state.md), and
use it during combat.

In the Corpus, we focus on a core subset of player data that directly
affects out-of-combat game mechanics, referred to as **player stats**.
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

--

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
