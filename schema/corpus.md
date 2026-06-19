# Module Corpus Schema

The Module Corpus is the read-only canonical adventure content — the equivalent
of a printed D&D adventure module. It is never modified during play. All game
logic, descriptions, entities, encounters, and win/loss conditions live here.

The Context Assembler reads from it to build the GMBriefing. The Engine reads
from it to validate actions, resolve encounters, and apply mechanics.

## Top-Level Structure

```json
{
  "adventure":    { /* metadata */ },
  "rooms":        { "<room_id>": { /* room */ } },
  "entities":     { "<entity_id>": { /* entity */ } },
  "mechanics":    { "<mechanic_id>": { /* mechanic */ } },
  "stats":        { /* stat definitions (optional) */ }
}
```

### `adventure` — Metadata block

| Field          | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `title`        | string | yes      | Display title of the adventure. |
| `credits`      | object | no       | `{ author, source, license }`. |
| `introduction` | string | yes      | Opening narration read to the player at game start. |
| `atmosphere`   | object | no       | `{ setting, tone }` — 1-2 sentence narrative guidance for both LLM calls. Setting describes the world; tone describes the desired style (e.g., grim, whimsical). |

---

## `rooms` — Room definitions

Each room is keyed by a unique `room_id`. A room is a node in the world graph.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when entering and when player examines room)",
    "entities_present": ["<entity_id>", ...],
    "soft_items": ["string", ...],
    "exits": [ { /* exit */ } ],
    "interactions": [ { /* interaction */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "is_start_room": false,
    "reactions": [ { /* reaction */ } ]
  }
}
```

| Field               | Type      | Required | Description |
|----------------------|-----------|----------|-------------|
| `name`               | string    | yes      | Short display name (e.g., "Axe Head"). |
| `description`        | string    | yes      | Full prose description shown on entry and on `examine` room. |
| `entities_present`   | string[]  | no       | Entity IDs of non-player entities present in this room. The Context Assembler uses this to populate `entities_visible` in GMBriefing, filtered by `state.alive`. |
| `soft_items`         | string[]  | no       | Plausible generic items that can be found in this room (e.g., `["rock", "loose stone", "dust"]`). These are identified by their general name only — they carry no unique item ID. The engine tracks them in `soft_inventory` when picked up. |
| `exits`              | array     | no       | Available exits from this room. |
| `interactions`       | array     | no       | Defined interactions the player can perform in this room. |
| `on_examine`         | array     | no       | Events that fire when the player examines this room. Each is an `OnExamineEvent` (see below). |
| `is_start_room`      | boolean   | no       | Exactly one room should have this set to `true`. Player starts here. |
| `reactions`          | array     | no       | Reactions that fire when the player is in this room (see Reactions below). |

### Exit object

```json
{
  "id": "string (unique across all exits)",
  "direction": "string (natural-language label, e.g. 'Climb carefully down the axe handle')",
  "target_room": "<room_id>",
  "conditions": [ { /* condition */ } ],
  "traversal_check": { /* traversal check (optional) */ },
  "hidden": false,
  "one_way": false
}
```

| Field             | Type    | Required | Description |
|-------------------|---------|----------|-------------|
| `id`              | string  | yes      | Unique exit identifier, referenced by `move` action `target`. |
| `direction`       | string  | yes      | Human-readable direction label for LLM context. |
| `target_room`     | string  | yes      | Room ID the player ends up in after traversing. |
| `conditions`      | array   | no       | Conditions that must be satisfied for the exit to be available. |
| `traversal_check` | object  | no       | **Optional.** A check (roll or stat_check) that must be passed to succeed at traversing this exit. On failure, the player stays in the current room. See Traversal check below. |
| `hidden`          | boolean | no       | If `true`, the exit is omitted from `exits_available` in GMBriefing until its reveal condition is met (e.g., `flag:handkerchief_moved == true`). The reveal condition is evaluated by the engine based on hard-state flags. |
| `one_way`         | boolean | no       | If `true`, the exit cannot be traversed in reverse. |

#### Traversal check (`traversal_check`)

An optional check that gates successful room traversal. Unlike `conditions` (which
determine whether the exit is shown/available at all), a `traversal_check` makes the
exit available but risky — the player may fail the check and remain in the current
room, able to retry next turn.

```json
{
  "traversal_check": {
    "check": {
      "type": "stat_check",
      "stat": "STR",
      "dc": 13,
      "repeatable": true
    },
    "condition": { "require": "inventory:rusty_key" },
    "skip_check_if": { "require": "flag:korbar_helps_key == true" },
    "failure_narrative": "You strain to haul the key but can't make progress."
  }
}
```

| Field               | Type                | Description |
|---------------------|---------------------|-------------|
| `check`             | CheckType           | The check to roll: a `roll` or `stat_check`. |
| `condition`         | condition object    | **Optional.** When present, the check only fires if this condition is met. When absent (or the condition is not met), traversal proceeds normally without a check. |
| `skip_check_if`     | condition object    | **Optional.** When present and evaluated to true, the check is skipped entirely (bypasses `condition`). Inverse of `condition` — use this for "don't check when NPC helps" patterns. |
| `failure_narrative` | string              | **Optional.** Narration text shown when the traversal check fails. |

### Condition object

Conditions can appear on exits, interactions, reactions, encounter rules,
and mechanics. They are predicate clauses evaluated against hard game state and
the module corpus. A standalone condition is expressed as an **object**; the
`any` and `all` forms may contain bare condition strings as array elements
(in addition to nested condition objects).

**`require`** — condition must be true for the thing to be available:

```json
{ "require": "flag:handkerchief_moved == true" }
```

**`unless`** — condition blocks availability if true:

```json
{ "unless": "flag:injured == true" }
```

**`any`** — at least one sub-condition must be true. Each element may be a
condition string *or* a nested condition object:

```json
{ "any": [
  "flag:handkerchief_noticed == true",
  { "all": [
    "attitude:korbar >= 4",
    "topic:abandonment"
  ] }
] }
```

**`all`** — all sub-conditions must be true. Each element may be a condition
string *or* a nested condition object:

```json
{ "all": [
  "flag:spider_fled == true",
  { "unless": "flag:injured == true" }
] }
```

A condition object can stand alone (`{ "require": "..." }`) or serve as an
element inside `any`/`all` arrays, allowing arbitrarily deep nesting of AND/OR
logic.

Condition strings use the format `<domain>:<key> <op> <value>`:

| Domain       | Example                          | Meaning |
|--------------|----------------------------------|---------|
| `flag`       | `flag:door_opened == true`       | Refers to a key in `hard_state.flags`. |
| `inventory`  | `inventory:rusty_key`            | Checks if an item entity ID is in the player's hard inventory. |
| `item`       | `item:rusty_key`                 | Alias for `inventory`. |
| `tag`        | `tag:weapon`                     | Checks if the player's inventory **or equipped items** contain any item with this tag. Scans both lists for backward compatibility. |
| `entity`     | `entity:spider.alive == true`    | Checks an entity's hard state field. |
| `room`       | `room:axe_head.visited == true`  | Checks a room state field. |
| `attitude`   | `attitude:korbar >= 2`           | Checks an NPC's soft-state attitude value. Defaults to the corpus `attitude_limits.initial` if absent from soft state. |
| `topic`      | `topic:abandonment`              | Checks if a topic ID has been discussed in the current dialogue (present in `soft_state.dialogue_state.topics_discussed`). |
| `stat`       | `stat:STR >= 12`                 | Checks the player's stat value against a threshold. Stat must be declared in `corpus.stats.definitions`; the player's value comes from `hard_state.player.stats`. |
| `equipped`   | `equipped:toenail_sword`         | Checks if an item entity ID is in the player's `equipped` list. Also accepts tag names — `equipped:weapon` is true if any equipped item has the tag `"weapon"`. |
| `event`      | `event:exit_id == exit_climb`    | Checks a value in the current event context. Only valid during reaction dispatch (see Reactions below). Outside dispatch, evaluates to `false`. |

Supported ops: `== true`, `== false`, `== <string>`, `>= <number>`, `> <number>`, `<= <number>`, `< <number>`.

The `event:` domain is only valid during reaction dispatch. Outside dispatch
(e.g., in interaction conditions or game-over mechanics), it evaluates to `false`.
Common context keys: `exit_id`, `interaction_id`, `npc_id`, `flag_name`,
`source_id`, `check_type`, `stat`, `amount`, `new_hp`.

---

### Interaction object

Interactions are named operations that can be performed by or on entities or rooms.
They can be defined at the room level or on individual entities.

```json
{
  "id": "string (unique within the defining context)",
  "label": "string (short label for UI/debug)",
  "description": "string (what the player is attempting)",
  "parameter_signature": { "target": ["entity", "soft_item"], "using": ["entity", "soft_item"] },
  "condition": { /* condition object or null */ },
  "check": { /* roll check or null */ },
  "success": { /* result */ },
  "failure": { /* result or null */ },
  "result": { /* result (used when no check is present) */ },
  "using_results": { /* item-specific overrides (optional) */ }
}
```

| Field                  | Type         | Required | Description |
|------------------------|--------------|----------|-------------|
| `id`                   | string       | yes      | Unique within the defining context (room or entity). Referenced by `interact` action `interaction_id`. |
| `label`                | string       | yes      | Human-readable action label. |
| `description`          | string       | no       | Extended description of the action. |
| `parameter_signature`  | object       | no       | Constrains what the `target` and `using` fields of the `interact` action can reference. `target` lists accepted types (`entity`, `soft_item`, `room`); `using` lists accepted types. If absent, no parameter restrictions beyond target existence. |
| `condition`            | object\|null | no       | Condition that must be met for the interaction to be available. |
| `check`                | object       | no       | A probabilistic check (roll). If absent, `result` is used directly. |
| `success`              | object       | no       | Result when the check succeeds. |
| `failure`              | object       | no       | Result when the check fails (optional; if absent, engine returns a generic "nothing happens"). |
| `result`               | object       | no       | Deterministic result (used when no `check` is present). |
| `using_results`        | object       | no       | **Optional.** Dict mapping item entity IDs (or `"*"` wildcard) to `UsingResultOverride` objects. When the `interact` action's `using` field matches a key, the override replaces the interaction's own `check`/`success`/`failure`/`result`. Each override may optionally carry its own `check` (allowing different DCs per item, e.g. STR DC 14 bare-handed vs. DC 10 with a weapon), or a plain `result`. Overrides are leaf-level — the override's check+success+failure (or result) fully replaces the interaction's defaults. |

Interactions include generic types available everywhere (e.g., `attack`) and special corpus-defined ones (e.g., `recharge`). Generic interactions are not automatically applied — the LLM must explicitly propose them via `interact`, and the engine validates the target and any `using` item. Picking up items should use the `transfer` action instead.

#### Check objects

Interactions use one of two check types: `roll` (flat probability) or `stat_check` (ability-score-based resolution).

**Roll check:**

```json
{
  "type": "roll",
  "threshold": 0.50,
  "repeatable": false,
  "note": "Optional designer note."
}
```

| Field        | Type    | Required | Description |
|--------------|---------|----------|-------------|
| `type`       | string  | yes      | `"roll"` — flat probability check. |
| `threshold`  | number  | yes      | Probability threshold (0.0–1.0). Roll succeeds if `random() < threshold`. |
| `repeatable` | boolean | yes      | Whether the check can be retried. If `false`, the engine tracks attempts and rejects repeats. |
| `note`       | string  | no       | Optional designer note. |

**Stat check:**

```json
{
  "type": "stat_check",
  "stat": "STR",
  "dc": 12,
  "modifier": 0,
  "resolution_params": { "advantage": true },
  "repeatable": false,
  "note": "Bend the iron bars."
}
```

| Field              | Type    | Required | Description |
|--------------------|---------|----------|-------------|
| `type`             | string  | yes      | `"stat_check"` — ability-score-based check. |
| `stat`             | string  | yes      | Stat key (e.g. `"STR"`, `"DEX"`). Must be declared in `stats.definitions`. |
| `dc`               | integer | yes      | Difficulty class (target number). Typical range: 5 (trivial) to 25 (nearly impossible). |
| `modifier`         | integer | no       | Flat situational modifier (default 0). E.g. `-2` for a slippery surface. |
| `resolution_params`| object  | no       | System-specific options. For `5e`: `{ "advantage": true }` or `{ "disadvantage": true }`. |
| `repeatable`       | boolean | yes      | Whether the check can be retried. |
| `opposed_by`       | string  | no       | Reserved for future NPC opposed checks. |
| `skill`            | string  | no       | Reserved for future skill checks. |
| `note`             | string  | no       | Optional designer note. |

The engine dispatches `stat_check` to the active resolution system (declared in
`stats.system`), which computes the dice formula and produces a
success/failure outcome.

**Resolution systems:**

| System | Formula                              | Use case |
|--------|--------------------------------------|----------|
| `5e`  | roll(1d20) + (stat-10)//2 + modifier >= DC | D&D 5e ability checks with advantage/disadvantage |

The schema reserves space for additional systems (e.g., `3d6` for GURPS-style,
`flat` for diceless).


#### Result object

```json
{
  "narrative": "string (pre-written description of outcome)",
  "add_item": "<item_id> (optional, adds to player inventory)",
  "remove_item": "<item_id> (optional)",
  "set_flag": { "<flag_name>": true | false },
  "alter_stat": { "<stat_key>": { "mode": "delta"|"set", "value": <int> } },
  "adjust_attitude": { "<npc_id>": <delta> },
  "reveals": "string (hint text for the player's future reference)",
  "chain_check": { /* chained check (optional) */ }
}
```

| Field         | Type   | Description |
|---------------|--------|-------------|
| `narrative`   | string | Canonical narration of the result. Engine passes this to LLM Call 2 via `triggered_narration`. |
| `add_item`    | string | Item entity ID to add to hard inventory. |
| `remove_item` | string | Item entity ID to remove from hard inventory. |
| `set_flag`        | object | Hard-state flags to set or clear. |
| `set_room_state`  | object | **Optional.** Per-room state changes: `{ "<room_id>": { "<field>": <value>, ... } }`. Useful for recording entry direction or other room-specific state that conditions can read via `room:<room_id>.<field>`. |
| `alter_stat`        | object | **Optional.** Stat modifiers to apply to the player. Keys are stat abbreviations (must be declared in `corpus.stats.definitions`); values are `{ "mode": "delta"\|"set", "value": <int> }` (mode defaults to `"delta"`). Use `"delta"` for damage/buffs (e.g., fall damage: `{ "STR": { "value": -4 } }`); use `"set"` for absolute assignment (e.g., a curse: `{ "INT": { "mode": "set", "value": 3 } }`). |
| `adjust_attitude` | object | **Optional.** Relative attitude changes applied by the engine when an interaction succeeds. Keys are NPC entity IDs; values are integer deltas (positive or negative). The engine clamps the new value to the NPC's `attitude_limits.[min, max]` and respects `step_per_turn`. LLM Call 2 cannot propose additional attitude changes for the same NPC on the same turn. |
| `reveals`         | string | Hint text; added to the player's known information for future GMBriefings. |
| `chain_check`     | object | **Optional.** A follow-up check to resolve immediately after this result. Enables nested "fail → check" patterns (e.g., fail a STR check → immediately resolve a DEX check). See Chained check below. |

#### Chained check (`chain_check`)

A chained check allows a result to trigger an immediate follow-up check (roll or stat
check) with its own success/failure outcomes. This supports nested resolution within a
single turn — for example, a key insertion that requires a STR check, and on failure
triggers a DEX check to catch the slipping key.

```json
{
  "chain_check": {
    "check": {
      "type": "stat_check",
      "stat": "DEX",
      "dc": 8,
      "repeatable": true
    },
    "success": {
      "narrative": "You catch it just in time.",
      "set_flag": { "key_caught": true }
    },
    "failure": {
      "narrative": "The key slips through your fingers and falls into the Astral Plane.",
      "set_flag": { "key_lost_to_astral": true }
    }
  }
}
```

| Field     | Type                | Description |
|-----------|---------------------|-------------|
| `check`   | CheckType           | The chained check to resolve (roll or stat_check). |
| `success` | Result              | Result to apply if the chained check succeeds. |
| `failure` | Result (optional)   | Result to apply if the chained check fails. |

Nested chaining is supported — a chained check's result may itself contain another
`chain_check`, up to a maximum depth of 3.

---

### On-examine event object

On-examine events fire when the player performs an `examine` action on the
entity or room that carries them. They support stat checks, conditional
gating, and rigorous-search-only gating — enabling patterns like "examining
the canvas walls triggers an INT check to deduce the glow is magical."

```json
{
  "id": "string (unique within the entity or room)",
  "condition": { "require": "flag:glow_noticed == false" },
  "rigorous_only": false,
  "check": {
    "type": "stat_check",
    "stat": "INT",
    "dc": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You deduce that the faint luminescence is magical in nature — a side effect of the Bag's magic.",
    "set_flag": { "glow_noticed": true },
    "reveals": "The glow is magical."
  },
  "failure": null
}
```

| Field            | Type            | Description |
|------------------|-----------------|-------------|
| `id`             | string          | Unique event identifier within the parent entity or room. |
| `condition`      | object\|null    | Condition object. If null, fires every time the entity/room is examined. |
| `rigorous_only`  | boolean         | If `true`, the event only fires when the examine action has `rigorous: true`. Default `false`. |
| `check`          | CheckType       | **Optional.** A roll or stat_check that gates the outcome. If absent, `result` fires deterministically when `condition` is met. |
| `success`        | Result          | Result applied when the check passes. Required if `check` is present. |
| `failure`        | Result\|null    | Result applied when the check fails. Optional; if absent, nothing happens on failure. |
| `result`         | Result\|null    | Deterministic result applied when no `check` is present. Mutually exclusive with `check`. |

The base `description` of the entity/room is returned first in the narration;
on-examine event narratives are appended after it. Results may carry
`set_flag`, `alter_stat`, `add_item`, and `chain_check` like any other result.
Multiple on-examine events on the same target all fire (in array order) if
their conditions are met.

### Reaction object

Reactions are the preferred mechanism for state-based and event-driven triggers.
A reaction fires when a matching game event occurs and its condition is met.

```json
{
  "id": "string (unique within the defining context)",
  "on": "event type string",
  "condition": { /* condition object or null */ },
  "effects": { /* reaction effects */ },
  "once": false,
  "priority": 0,
  "phase": "deferred"
}
```

| Field     | Type            | Required | Description |
|-----------|-----------------|----------|-------------|
| `id`      | string          | yes      | Unique identifier within the defining context (room, entity, or mechanic). Used for debugging and `once` tracking. Because `once` tracking is global, reaction IDs should be unique across the whole adventure when any reaction uses `once: true`. |
| `on`      | string          | yes      | Event type to match (see Event types below). |
| `condition` | object\|null  | no       | Condition evaluated against game state + event context. If null, fires unconditionally when the event occurs. |
| `effects` | object          | yes      | The effects to apply (see Reaction effects below). |
| `once`    | boolean         | no       | If `true`, fires at most once per adventure load. Default `false`. For persistent one-shot behavior, prefer flag-gated conditions instead. |
| `priority` | integer        | no       | Lower values fire earlier. Default `0`. |
| `phase`   | string          | no       | `"deferred"` (default) or `"immediate"`. Immediate reactions fire before the current action continues; only allowed for `interaction.used`, `traversal.attempted`, `traversal.succeeded`, and `room.entered`. |

#### Scoping rules

| Reaction defined on... | Active when... |
|------------------------|----------------|
| `Room` | Player is currently in that room |
| `Entity` | Entity is in `entities_present` of the current room AND `alive` is not `false` and `fled` is not `true` |
| `Mechanic` | Always (mechanics are adventure-wide) |

#### Event types

> **Full reference:** See [`events.md`](events.md) for the complete event
catalog, context-key descriptions, immediate/deferred rules, and known
implementation gaps.

The summary below lists the most commonly used events. The `on` field of a
reaction must be one of these event type strings.

**Action-level events:**

| Event | Context keys | Emitted when |
|-------|-------------|-------------|
| `room.entered` | `room_id` | Player arrives in a room |
| `room.exited` | `room_id` | Player leaves a room |
| `traversal.attempted` | `exit_id`, `from_room`, `to_room` | Player attempts to traverse an exit |
| `traversal.succeeded` | `exit_id`, `from_room`, `to_room` | Exit traversal succeeds |
| `traversal.failed` | `exit_id`, `from_room`, `fail_reason` | Traversal check fails |
| `check.passed` | `check_type`, `stat?`, `dc?`, `threshold?`, `source_id`, `source_type` | Any check succeeds |
| `check.failed` | same as `check.passed` | Any check fails |
| `interaction.used` | `interaction_id`, `target_id`, `using_item?` | An interaction is attempted |
| `dialogue.started` | `npc_id` | Dialogue mode begins |
| `dialogue.ended` | `npc_id`, `reason` | Dialogue mode ends |
| `combat.started` | `combatant_ids` | Combat begins |
| `combat.ended` | `reason` | Combat ends |
| `encounter.branched` | `encounter_id`, `branch` (`success`\|`failure`), `outcome` | A `stat_check`/`roll` encounter rule selects its `on_success`/`on_failure` branch |
| `item.acquired` | `item_id`, `source` | Item enters inventory |
| `item.lost` | `item_id`, `reason` | Item leaves inventory |

**State-change events (derived from the turn's state diff):**

| Event | Context keys | Emitted when |
|-------|-------------|-------------|
| `flag.set` | `flag_name` | A flag transitions to `true` |
| `flag.cleared` | `flag_name` | A flag transitions to `false` |
| `entity_state.changed` | `entity_id`, `field`, `new_value` | Any entity state field changes |
| `attitude.changed` | `npc_id`, `old_value`, `new_value`, `delta` | NPC attitude changes |
| `stat.changed` | `stat_name`, `old_value`, `new_value`, `delta` | Player stat changes |
| `equipment.changed` | `added?`, `removed?` | Equipped gear changes |
| `player.damaged` | `amount`, `new_hp` | Player HP decreases |
| `player.healed` | `amount`, `new_hp` | Player HP increases |

**Lifecycle events:**

| Event | Context | Emitted when |
|-------|---------|-------------|
| `turn.start` | `turn_number` | Beginning of each turn |
| `turn.end` | `turn_number` | End of each turn |

#### Event context in conditions

During reaction dispatch, event context values are available via the `event:`
condition domain. This allows reactions to match on specific event details:

```json
{ "require": "event:exit_id == exit_climb_down" }
{ "require": "event:interaction_id == attack" }
{ "require": "event:npc_id == spider" }
{ "require": "event:flag_name == spider_fled" }
```

The `event:` domain is only valid during reaction dispatch. Outside dispatch
(e.g., in interaction conditions or game-over mechanics), it evaluates to `false`.

#### `check.passed` / `check.failed` context keys

| Key | Description |
|-----|-------------|
| `check_type` | `"stat_check"` or `"roll"` |
| `stat` | The stat key (for stat checks) |
| `dc` | The difficulty class (for stat checks) |
| `threshold` | The probability threshold (for rolls) |
| `source_id` | The interaction, exit, dialogue path, or reaction ID that originated the check |
| `source_type` | `"interaction"`, `"examine"`, `"traversal"`, `"dialogue_path"`, `"take"`, or `"reaction"` |

See [`events.md`](events.md) for additional detail on each event's context.

#### Reaction effects

```json
{
  "result": { /* Result object (same as interaction results) */ },
  "trigger_encounter": "<mechanic_id or entity_id>",
  "trigger_dialogue": "<npc_entity_id>",
  "game_over": { "type": "win|lose", "trigger_id": "string" }
}
```

| Field               | Type   | Description |
|---------------------|--------|-------------|
| `result`            | object | A `Result` object — same fields as interaction results: `narrative`, `set_flag`, `set_entity_state`, `set_room_state`, `alter_stat`, `adjust_attitude`, `add_item`, `remove_item`, `reveals`, `chain_check`. |
| `trigger_encounter` | string | Mechanic ID or entity ID to trigger an encounter. If `"self"`, resolves to the owning entity's ID (for entity-scoped reactions). |
| `trigger_dialogue`  | string | NPC entity ID to initiate dialogue with. If `"self"`, resolves to the owning entity's ID. |
| `game_over`         | object | `{ "type": "win"|"lose", "trigger_id": "..." }` — ends the game. |

At least one of `result` or the reaction-specific fields (`trigger_encounter`,
`trigger_dialogue`, `game_over`) must be set.

#### Self-reference for entity-scoped reactions

When a reaction is defined on an entity, the special string `"self"` in effect
fields resolves to the entity's own ID. This makes reactions portable — copying
a reaction to a different entity doesn't require editing effect references.

| Effect field | `"self"` resolves to |
|---|---|
| `trigger_encounter` | The entity's ID |
| `trigger_dialogue` | The entity's ID (must be type `npc`) |
| `result.set_entity_state` key | The entity's ID |
| `result.adjust_attitude` key | The entity's ID |

#### Ordering and loop prevention

1. Reactions are sorted by `priority` (lower first), then by scope (entity before room before mechanic), then by definition order.
2. State-change events are derived once at the end of the turn from the complete state diff, after all action and reaction effects have been applied. They are dispatched in a single final pass; reactions triggered by that pass may mutate state, but no further state-change events are derived from those mutations.
3. Maximum reaction dispatch recursion depth is 5. Exceeding this stops dispatch with a warning.
4. Only one encounter can fire per turn (from the resolver or from reactions). Subsequent `trigger_encounter` effects are silently ignored.

#### Encounter-once-per-turn guard

Only one encounter can resolve per turn. If a reaction triggers an encounter and
that encounter has already been triggered (from the resolver or from another
reaction), the second `trigger_encounter` is silently ignored with a warning log.

#### Nested encounters

A reaction that fires during an encounter can trigger another encounter via
`trigger_encounter`. The depth-5 recursion limit prevents infinite loops, but
design reaction conditions carefully to avoid unintended chains.

#### Examples

**State-based trigger (flag change):**
```json
{
  "id": "spider_fled_reaction",
  "on": "flag.set",
  "condition": { "require": "event:flag_name == spider_fled" },
  "effects": {
    "result": {
      "narrative": "With the spider gone, the room feels safer.",
      "set_flag": { "room_cleared": true }
    }
  }
}
```

**Room-entry encounter:**
```json
{
  "id": "spider_ambush",
  "on": "room.entered",
  "condition": { "require": "entity:spider.alive == true" },
  "effects": { "trigger_encounter": "spider_attack" }
}
```

**Chained encounter (reaction → encounter → reaction → encounter):**
```json
{
  "id": "guardian_awakens",
  "on": "room.entered",
  "condition": { "require": "event:room_id == cave_depths" },
  "effects": { "trigger_encounter": "guardian_attack" }
}
```

The `guardian_attack` encounter has a rule whose success branch sets `guardian_defeated: true`. A second reaction then fires on that flag:

```json
{
  "id": "wraith_appears",
  "on": "flag.set",
  "condition": { "require": "event:flag_name == guardian_defeated" },
  "effects": { "trigger_encounter": "wraith_ambush" }
}
```

**Failed-check trigger:**
```json
{
  "id": "web_fail_damage",
  "on": "check.failed",
  "condition": {
    "all": [
      { "require": "event:source_id == force_through_web" },
      { "require": "event:check_type == stat_check" }
    ]
  },
  "effects": {
    "result": {
      "narrative": "The webs constrict around you.",
      "alter_stat": { "STR": { "value": -2 } }
    }
  }
}
```

**Entity-scoped behavior trigger (replaces `behavior.triggers_on`):**
```json
{
  "id": "spider_attack_on_sight",
  "on": "interaction.used",
  "condition": { "require": "event:interaction_id == attack" },
  "effects": { "trigger_encounter": "self" }
}
```

**Reaction-only mechanic (adventure-wide trigger):**
```json
"global_reactions": {
  "id": "global_reactions",
  "description": "Adventure-wide state-based reactions.",
  "reactions": [
    {
      "id": "injury_warning",
      "on": "player.damaged",
      "condition": { "require": "event:new_hp <= 3" },
      "effects": {
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

## `entities` — Entity definitions

Entities are typed objects that appear in rooms or inventory. Keyed by unique `entity_id`.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | item",
    "description": "string",
    "spans_rooms": ["<room_id>", ...],
    "soft_items": ["string", ...],
    "tags": ["<tag>", ...],
    "draggable": false,
    "dragging_note": "string",
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

| Field                  | Type   | Applies to    | Description |
|------------------------|--------|---------------|-------------|
| `type`                 | enum   | all           | `player`, `feature`, `npc`, `item`. The `player` type is reserved for the player character entity. |
| `description`          | string | all           | Canonical description returned for `examine` action. |
| `spans_rooms`          | array  | feature       | List of room IDs this entity is visible in (e.g., a battleaxe spanning multiple rooms). |
| `soft_items`           | array  | all           | Plausible generic items found on/in this entity (e.g., a corpse might have `["loose change", "torn parchment"]`). Same semantics as room soft_items. |
| `tags`                 | array  | item          | Semantic tags for mechanical matching (e.g., `"weapon"`, `"key_item"`, `"draggable"`). |
| `draggable`            | bool   | item          | If true, the item can be dragged but occupies the player (no other manual actions while dragging). |
| `dragging_note`        | string | item          | Narrative note describing the encumbrance. |
| `take_check`           | object | item          | **Optional.** A check (with `success` / `failure` results) that must be passed when the player attempts to pick up this item via a `transfer` action. |
| `interactions`         | array  | all           | Interactions available on this entity specifically. Follows the same Interaction object schema. |
| `on_examine`           | array  | all           | Events that fire when the player examines this entity. Each is an `OnExamineEvent` (see above). |
| `reactions`            | array  | all           | Reactions scoped to when this entity is present and alive/not-fled (see Reactions below). |
| `dialogue_guidelines`  | object | npc           | See below. |
| `behavior`             | object | npc (monster) | Encounter rules for combat-capable NPCs. See below. |
| `state_fields`         | object | all           | Declaration of mutable state fields for this entity. The engine initialises these from `hard_state.json` and tracks changes. |
| `follower_blacklist`   | array  | npc           | **Optional.** List of room IDs this NPC refuses to enter when following the player. If the player moves into a blacklisted room, the NPC's `following` state is cleared and a narrative note is generated. |
| `equip_block`          | object | item          | **Optional.** `EquipBlock` describing how the item interacts with the equipment system (see below). Items without this block cannot be equipped. |

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

The engine recognises two reserved boolean state fields for reaction scoping:

- `alive` — entity reactions are active only when `alive` is not `false`. This
  is conventionally declared for any creature or destructible feature.
- `fled` — entity reactions are active only when `fled` is not `true`. Declare
  this for creatures that can flee or be driven off. Adventures that do not use
  fleeing simply omit the field; it defaults to unset, so the check passes.

Both fields are optional at the schema level, but if an entity has reactions
and can die or flee, declare the corresponding field so the engine scopes the
reactions correctly.

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
      "conditions": ["attitude:korbar >= 2", "topic:abandonment", "item:rusty_key"],
      "set_flag": { "<flag_name>": true | false },
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
    "check": { "type": "stat_check", "stat": "CHA", "dc": 12, "repeatable": true },
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
| `condition` | object | Optional. If present, all conditions must be met for the path to be usable. |
| `check`     | object | Optional. A `roll` or `stat_check`. If present, `success` is required. |
| `success`   | object | Result applied when the check succeeds. |
| `failure`   | object | Result applied when the check fails. |
| `result`    | object | Deterministic result when no `check` is present. Mutually exclusive with `check`. |

Path results support the same fields as interaction `Result` objects: `narrative`, `set_flag`, `alter_stat`, `adjust_attitude`, `reveals`, `chain_check`.

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

#### `attitude_limits`

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
      "check": { "type": "stat_check", "stat": "STR", "dc": 12, "repeatable": true },
      "narrative": "string",
      "set_flags": { "<flag>": true },
      "alter_stat": { "<stat_key>": { "mode": "delta"|"set", "value": <int> } },
      "on_success": { "outcome": "...", "set_flags": {}, "alter_stat": {}, "narrative": "..." },
      "on_failure": { "outcome": "...", "set_flags": {}, "alter_stat": {}, "narrative": "..." }
    }
  ],
  "on_flee": {
    "set_flags": { "<flag>": true },
    "effect": "string describing subsequent behavior change"
  }
}
```

- Rules are evaluated top-to-bottom. The first rule whose `condition` matches
  is applied. Conditions are condition objects (see Condition object section)
  evaluated against hard state (flags, inventory, entity states) and soft state
  (attitudes).
- `alter_stat` (optional) applies stat modifiers to the player when the rule fires. Each value is `{ "mode": "delta"|"set", "value": <int> }` (mode defaults to `"delta"`). When a branch (`on_success`/`on_failure`) also carries `alter_stat`, the branch values override rule-level values for the same stat key.
- For phase 1 (kill-or-be-killed resolution), outcomes are:
  - `death` — player dies, game over.
  - `flee` — creature flees, applying `on_flee` effects.
  - `roll` — flat probability check using `threshold`; branches on `on_success`/`on_failure`.
  - `stat_check` — ability-score-based check using a `StatCheck` definition; branches on `on_success`/`on_failure`. The `check` field (a `StatCheck` object) is required when outcome is `stat_check`. Example:
    ```json
    {
      "condition": { "require": "tag:weapon" },
      "outcome": "stat_check",
      "check": { "type": "stat_check", "stat": "STR", "dc": 17, "repeatable": true },
      "on_success": { "outcome": "flee", "narrative": "You overpower Korbar." },
      "on_failure": { "outcome": "death", "narrative": "Korbar overpowers you." }
    }
    ```

---

## `mechanics` — Encounter and system rules

Named mechanics are rules involving aspects of game state not tied to specific
rooms or entities. They are referenced by exits, interactions, and reactions.
Game-over conditions live here too.

A mechanic can be one of three things:
- An **encounter** (has `rules`)
- A **game-over condition** (has `type`, `condition`, `trigger_id`)
- A **reaction-only mechanic** (has `reactions` only — for adventure-wide state-based triggers)

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
        "outcome": "death | flee | roll | stat_check",
        "threshold": 0.50,
        "check": { "type": "stat_check", "stat": "STR", "dc": 12, "repeatable": true },
        "on_success": { "outcome": "...", "set_flags": {}, "alter_stat": {}, "narrative": "..." },
        "on_failure": { "outcome": "...", "set_flags": {}, "alter_stat": {}, "narrative": "..." },
        "narrative": "string",
        "set_flags": {},
        "alter_stat": {}
      }
    ],
    "reactions": [ { /* reaction (optional) */ } ]
  }
}
```

Rules are evaluated top-to-bottom. The first rule whose `condition` matches is applied. Conditions are condition objects (see Condition object section). Rule and branch `alter_stat` objects follow the same modifier semantics as interaction `Result.alter_stat`.

### Game-over conditions

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
| `condition`   | object | Evaluated each turn (or when specific triggers fire). When true, `game_over` is set. Follows the condition object format. |
| `narrative`   | string | Canonical ending prose passed to LLM Call 2 via `triggered_narration`. |
| `trigger_id`  | string | Set as `game_over.trigger` in hard state; for debugging and save analysis. |

### Reaction-only mechanic

A mechanic with only `reactions` (no `type`, `rules`, or `trigger_id`) is valid.
Use this for adventure-wide state-based reactions that don't need encounter rules
and aren't tied to a specific room or entity.

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
mechanics. Reaction-only mechanics use per-reaction `condition` fields instead.

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

### Resolution system abstraction

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

## Example Module

In the reference implementation, the module corpus is loaded once at
startup from a JSON file. The engine holds it in memory as a read-only
data structure. No vector database or semantic search is needed — all
lookups are by deterministic ID.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
