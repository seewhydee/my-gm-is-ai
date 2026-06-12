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
    "on_enter": [ { /* on_enter event */ } ],
    "on_examine": [ { /* on_examine event */ } ],
    "is_start_room": false
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
| `on_enter`           | array     | no       | Events that fire when the player first enters the room. May be one-shot or conditional. |
| `on_examine`         | array     | no       | Events that fire when the player examines this room. Each is an `OnExamineEvent` (see below). |
| `is_start_room`      | boolean   | no       | Exactly one room should have this set to `true`. Player starts here. |

### Exit object

```json
{
  "id": "string (unique across all exits)",
  "direction": "string (natural-language label, e.g. 'Climb carefully down the axe handle')",
  "target_room": "<room_id>",
  "conditions": [ { /* condition */ } ],
  "on_traverse": { /* traversal effect */ },
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
| `on_traverse`     | object  | no       | Effects applied when the player successfully traverses the exit: `set_flag`, `trigger_encounter`, etc. |
| `traversal_check` | object  | no       | **Optional.** A check (roll or stat_check) that must be passed to succeed at traversing this exit. On failure, the player stays in the current room. See Traversal check below. |
| `hidden`          | boolean | no       | If `true`, the exit is omitted from `exits_available` in GMBriefing until its reveal condition is met (e.g., `flag:handkerchief_moved == true`). The reveal condition is evaluated by the engine based on hard-state flags. |
| `one_way`         | boolean | no       | If `true`, the exit cannot be traversed in reverse. |

#### Exit `on_traverse` effects

The `on_traverse` object supports these fields; all are optional:

| Field               | Type             | Description |
|---------------------|------------------|-------------|
| `set_flag`          | object           | Sets hard-state flags: `{ "<flag_name>": true\|false, ... }`. |
| `narrative`         | string           | Pre-written prose for the traverse event. |
| `trigger_encounter` | string           | Triggers a named encounter from `mechanics`. |
| `skip_if`           | condition object | Condition under which the effect is skipped. |
| `narrative_skip`    | string           | Short narrative for when the effect is skipped. |

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

Conditions can appear on exits, interactions, on_enter events, encounter rules,
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
| `tag`        | `tag:weapon`                     | Checks if the player's inventory contains any item with this tag. |
| `entity`     | `entity:spider.alive == true`    | Checks an entity's hard state field. |
| `room`       | `room:axe_head.visited == true`  | Checks a room state field. |
| `attitude`   | `attitude:korbar >= 2`           | Checks an NPC's soft-state attitude value. Defaults to the corpus `attitude_limits.initial` if absent from soft state. |
| `topic`      | `topic:abandonment`              | Checks if a topic ID has been discussed in the current dialogue (present in `soft_state.dialogue_state.topics_discussed`). |
| `stat`       | `stat:STR >= 12`                 | Checks the player's stat value against a threshold. Stat must be declared in `corpus.stats.definitions`; the player's value comes from `hard_state.player.stats`. |

Supported ops: `== true`, `== false`, `== <string>`, `>= <number>`, `> <number>`, `<= <number>`, `< <number>`.

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
| `resolution_params`| object  | no       | System-specific options. For `d20`: `{ "advantage": true }` or `{ "disadvantage": true }`. |
| `repeatable`       | boolean | yes      | Whether the check can be retried. |
| `opposed_by`       | string  | no       | Reserved for future NPC opposed checks. |
| `skill`            | string  | no       | Reserved for future skill checks. |
| `note`             | string  | no       | Optional designer note. |

The engine dispatches `stat_check` to the active resolution system (declared in
`stats.resolution_system`), which computes the dice formula and produces a
success/failure outcome.

**Resolution systems:**

| System | Formula                              | Use case |
|--------|--------------------------------------|----------|
| `d20`  | roll(1d20) + (stat-10)//2 + modifier >= DC | D&D-style (3–18 stats, DC 5–25) |

The schema reserves space for additional systems (e.g., `3d6` for GURPS-style,
`flat` for diceless).


#### Result object

```json
{
  "narrative": "string (pre-written description of outcome)",
  "add_item": "<item_id> (optional, adds to player inventory)",
  "remove_item": "<item_id> (optional)",
  "set_flag": { "<flag_name>": true | false },
  "set_stat": { "<stat_key>": <delta> },
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
| `set_stat`        | object | **Optional.** Stat deltas to apply to the player. Keys are stat abbreviations (must be declared in `corpus.stats.definitions`); values are integer changes (positive or negative). E.g., `{ "STR": -4, "DEX": -4, "CON": -4 }` for fall damage. |
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

### On-enter event object

```json
{
  "id": "string (unique within the room)",
  "condition": { "require": "flag:fly_alive == true" },
  "narrative": "string",
  "set_flag": { "<flag_name>": true | false },
  "set_entity_state": { "<entity_id>": { "<field>": <value> } },
  "trigger_dialogue": "<npc_entity_id>"
}
```

| Field              | Type            | Description |
|--------------------|-----------------|-------------|
| `id`                | string          | Unique event identifier within the room. |
| `condition`         | object\|null    | Condition object. If null, fires exactly once on first entry (engine tracks internally). |
| `narrative`         | string          | Canonical narration text. |
| `set_flag`          | object          | Hard-state flags to set or clear. |
| `set_entity_state`  | object          | Entity state changes to apply. Keys are entity IDs; values are `{ "field": value }` maps. The engine validates that the entity exists and the field is declared in the entity's `state_fields`. |
| `trigger_dialogue`  | string          | If set, the engine automatically initiates dialogue mode with the named NPC entity. The NPC must be of type `npc` and present in the current room. The on_enter narrative (if any) fires first, then dialogue is activated. |

The engine detects which effects to apply from the presence of the effect
fields and applies all that are present. Fields can be combined — for example,
an on_enter event can simultaneously set a flag, modify entity state, and
initiate dialogue with an NPC.

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
`set_flag`, `set_stat`, `add_item`, and `chain_check` like any other result.
Multiple on-examine events on the same target all fire (in array order) if
their conditions are met.

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
| `interactions`         | array  | all           | Interactions available on this entity specifically. Follows the same Interaction object schema. |
| `on_examine`           | array  | all           | Events that fire when the player examines this entity. Each is an `OnExamineEvent` (see above). |
| `dialogue_guidelines`  | object | npc           | See below. |
| `behavior`             | object | npc (monster) | Encounter rules for combat-capable NPCs. See below. |
| `state_fields`         | object | all           | Declaration of mutable state fields for this entity. The engine initialises these from `hard_state.json` and tracks changes. |
| `follower_blacklist`   | array  | npc           | **Optional.** List of room IDs this NPC refuses to enter when following the player. If the player moves into a blacklisted room, the NPC's `following` state is cleared and a narrative note is generated. |

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
  "on_dialogue_exit": {
    "set_entity_state": { "<entity_id>": { "<field>": <value> } },
    "set_flag": { "<flag_name>": true | false },
    "narrative": "string (canonical narration when dialogue ends)"
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
| `on_dialogue_exit`| object | Effects applied by the engine when dialogue mode exits for this NPC. Contains optional `set_entity_state`, `set_flag`, and `narrative` fields. This is the mechanism for NPCs that die, flee, transform, or otherwise change state when conversation ends — whether the player leaves, uses `ends_dialogue`, or a stall is detected. |
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

Path results support the same fields as interaction `Result` objects: `narrative`, `set_flag`, `set_stat`, `adjust_attitude`, `reveals`, `chain_check`.

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
  "triggers_on": ["<exit_id>", "<interaction_id>", ...],
    "encounter_rules": [
    {
      "condition": { /* condition object */ },
      "outcome": "death | flee | roll | stat_check",
      "threshold": 0.50,
      "check": { "type": "stat_check", "stat": "STR", "dc": 12, "repeatable": true },
      "narrative": "string",
      "set_flags": { "<flag>": true },
      "on_success": { "outcome": "...", "set_flags": {}, "narrative": "..." },
      "on_failure": { "outcome": "...", "narrative": "..." }
    }
  ],
  "on_flee": {
    "set_flags": { "<flag>": true },
    "effect": "string describing subsequent behavior change"
  }
}
```

- `triggers_on` is an array of exit and/or interaction IDs. When the player
  uses any trigger in the list, the behavior's encounter rules fire. An empty
  array means the behavior only fires when the NPC is directly targeted (e.g.,
  via an `attack` interaction).
- Rules are evaluated top-to-bottom. The first rule whose `condition` matches
  is applied. Conditions are condition objects (see Condition object section)
  evaluated against hard state (flags, inventory, entity states) and soft state
  (attitudes).
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
rooms or entities. They are referenced by exits, interactions, and on_enter events.
Game-over conditions live here too.

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
        "on_success": { "outcome": "...", "set_flags": {}, "narrative": "..." },
        "on_failure": { "outcome": "...", "narrative": "..." },
        "narrative": "string",
        "set_flags": {}
      }
    ]
  }
}
```

Rules are evaluated top-to-bottom. The first rule whose `condition` matches is applied. Conditions are condition objects (see Condition object section).

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
  "resolution_system": "d20"
}
```

| Field               | Type   | Required | Description |
|---------------------|--------|----------|-------------|
| `definitions`       | object | yes      | Dict of stat key → `{ name, description }`. Keys are short uppercase identifiers (e.g. `"STR"`). |
| `resolution_system` | string | yes      | Named resolution system. Currently supported: `"d20"`. |

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
(e.g., `(stat - 10) // 2` for d20) and includes the full `player_stats` block
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
