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
  "mechanics":    { "<mechanic_id>": { /* mechanic */ } }
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
| `is_start_room`      | boolean   | no       | Exactly one room should have this set to `true`. Player starts here. |

### Exit object

```json
{
  "id": "string (unique across all exits)",
  "direction": "string (natural-language label, e.g. 'Climb carefully down the axe handle')",
  "target_room": "<room_id>",
  "conditions": [ { /* condition */ } ],
  "on_traverse": { /* traversal effect */ },
  "hidden": false,
  "one_way": false
}
```

| Field          | Type    | Required | Description |
|----------------|---------|----------|-------------|
| `id`           | string  | yes      | Unique exit identifier, referenced by `move` action `target`. |
| `direction`    | string  | yes      | Human-readable direction label for LLM context. |
| `target_room`  | string  | yes      | Room ID the player ends up in after traversing. |
| `conditions`   | array   | no       | Conditions that must be satisfied for the exit to be available. |
| `on_traverse`  | object  | no       | Effects applied when the player uses this exit: `set_flag`, `trigger_encounter`, etc. |
| `hidden`       | boolean | no       | If `true`, the exit is omitted from `exits_available` in GMBriefing until its reveal condition is met (e.g., `flag:handkerchief_moved == true`). The reveal condition is evaluated by the engine based on hard-state flags. |
| `one_way`      | boolean | no       | If `true`, the exit cannot be traversed in reverse. |

#### Exit `on_traverse` effects

The `on_traverse` object supports these fields; all are optional:

| Field               | Type             | Description |
|---------------------|------------------|-------------|
| `set_flag`          | object           | Sets hard-state flags: `{ "<flag_name>": true\|false, ... }`. |
| `narrative`         | string           | Pre-written prose for the traverse event. |
| `trigger_encounter` | string           | Triggers a named encounter from `mechanics`. |
| `skip_if`           | condition object | Condition under which the effect is skipped. |
| `narrative_skip`    | string           | Short narrative for when the effect is skipped. |

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
  "result": { /* result (used when no check is present) */ }
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

Interactions include generic types available everywhere (e.g., `attack`) and special corpus-defined ones (e.g., `recharge`). Generic interactions are not automatically applied — the LLM must explicitly propose them via `interact`, and the engine validates the target and any `using` item. Picking up items should use the `transfer` action instead.

#### Check object

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
| `type`       | string  | yes      | Currently only `"roll"`. Future: `"skill_check"`, `"opposed"`. |
| `threshold`  | number  | yes      | Probability threshold (0.0–1.0). Roll succeeds if `random() < threshold`. |
| `repeatable` | boolean | yes      | Whether the check can be retried. If `false`, the engine tracks attempts and rejects repeats. |

#### Result object

```json
{
  "narrative": "string (pre-written description of outcome)",
  "add_item": "<item_id> (optional, adds to player inventory)",
  "remove_item": "<item_id> (optional)",
  "set_flag": { "<flag_name>": true | false },
  "reveals": "string (hint text for the player's future reference)"
}
```

| Field         | Type   | Description |
|---------------|--------|-------------|
| `narrative`   | string | Canonical narration of the result. Engine passes this to LLM Call 2 via `triggered_narration`. |
| `add_item`    | string | Item entity ID to add to hard inventory. |
| `remove_item` | string | Item entity ID to remove from hard inventory. |
| `set_flag`    | object | Hard-state flags to set or clear. |
| `reveals`     | string | Hint text; added to the player's known information for future GMBriefings. |

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

---

## `entities` — Entity definitions

Entities are typed objects that appear in rooms or inventory. Keyed by unique `entity_id`.

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | trap | item",
    "description": "string",
    "spans_rooms": ["<room_id>", ...],
    "soft_items": ["string", ...],
    "tags": ["<tag>", ...],
    "draggable": false,
    "dragging_note": "string",
    "interactions": [ { /* interaction */ } ],
    "dialogue_guidelines": { /* only for npc type */ },
    "behavior": { /* only for npc (monster) type */ },
    "state_fields": { "<field_name>": { "type": "boolean | number | string", "description": "string" } }
  }
}
```

| Field                  | Type   | Applies to    | Description |
|------------------------|--------|---------------|-------------|
| `type`                 | enum   | all           | `player`, `feature`, `npc`, `trap`, `item`. The `player` type is reserved for the player character entity. |
| `description`          | string | all           | Canonical description returned for `examine` action. |
| `spans_rooms`          | array  | feature       | List of room IDs this entity is visible in (e.g., a battleaxe spanning multiple rooms). |
| `soft_items`           | array  | all           | Plausible generic items found on/in this entity (e.g., a corpse might have `["loose change", "torn parchment"]`). Same semantics as room soft_items. |
| `tags`                 | array  | item          | Semantic tags for mechanical matching (e.g., `"weapon"`, `"key_item"`, `"draggable"`). |
| `draggable`            | bool   | item          | If true, the item can be dragged but occupies the player (no other manual actions while dragging). |
| `dragging_note`        | string | item          | Narrative note describing the encumbrance. |
| `interactions`         | array  | all           | Interactions available on this entity specifically. Follows the same Interaction object schema. |
| `dialogue_guidelines`  | object | npc           | See below. |
| `behavior`             | object | npc (monster) | Encounter rules for combat-capable NPCs. See below. |
| `state_fields`         | object | all           | Declaration of mutable state fields for this entity. The engine initialises these from `hard_state.json` and tracks changes. |

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
   `set_flag` and `set_entity_state` side effects, and records the topic ID
   and its `description` in `soft_state.npc_revelations`.
4. On subsequent turns, the Context Assembler includes revealed topics (with
   descriptions) in the GMBriefing, so LLM Call 1 knows what the player has
   learned.

Invalid or conditions-not-met tags are silently rejected. LLM Call 2 is
prompted to respect the `will_reveal` readiness signals; if it narrates a
reveal that the engine rejects, the prose and the mechanical state may
diverge (same risk as rejected soft-state patches).

#### `attitude_limits`

NPC attitude is tracked as an integer in `soft_state.npc_attitudes`. Positive values indicate friendly disposition; negative values indicate hostility. The `attitude_limits` block constrains how attitude can change:

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
      "outcome": "death | flee | roll",
      "threshold": 0.50,
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
- For phase 1 (kill-or-be-killed resolution), outcomes are `death` (player
  dies → game over), `flee` (creature flees), or `roll` (check-based).

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
        "outcome": "death | flee | roll",
        "threshold": 0.50,
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

## Example Module

In the reference implementation, the module corpus is loaded once at startup from
a JSON file (e.g., `adventures/bag-of-holding/corpus.json`). The engine holds it
in memory as a read-only data structure. No vector database or semantic search is
needed — all lookups are by deterministic ID.
