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
  "game_over_conditions": [ { /* condition */ } ]
}
```

### `adventure` — Metadata block

| Field          | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `title`        | string | yes      | Display title of the adventure. |
| `credits`      | object | no       | `{ author, source, license }`. |
| `introduction` | string | yes      | Opening narration read to the player at game start. |
| `atmosphere`   | object | no       | `{ setting, lighting, tone }` — narrative guidance for the LLM's tone and description style. |

---

## `rooms` — Room definitions

Each room is keyed by a unique `room_id`. A room is a node in the world graph.

```json
{
  "<room_id>": {
    "name": "string",
    "description": "string (shown when entering and when player examines room)",
    "entities_present": ["<entity_id>", ...],
    "exits": [ { /* exit */ } ],
    "interactions": [ { /* interaction */ } ],
    "on_enter": [ { /* on_enter event */ } ],
    "is_start_room": false
  }
}
```

| Field               | Type    | Required | Description |
|----------------------|---------|----------|-------------|
| `name`               | string  | yes      | Short display name (e.g., "Axe Head"). |
| `description`        | string  | yes      | Full prose description shown on entry and on `examine` room. |
| `entities_present`   | string[] | no     | Entity IDs of non-inventory entities present in this room. The Context Assembler uses this to populate `entities_visible` in GMBriefing, filtered by `state.alive`. |
| `exits`              | array   | no       | Available exits from this room. |
| `interactions`       | array   | no       | Defined interactions the player can perform in this room. |
| `on_enter`           | array   | no       | Events that fire when the player first enters the room (conditional). |
| `is_start_room`      | boolean | no       | Exactly one room should have this set to `true`. Player starts here. |

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
| `hidden`       | boolean | no       | If `true`, the exit is omitted from `exits_available` in GMBriefing until its reveal condition is met (e.g., `flag:handkerchief_moved == true`). |
| `one_way`      | boolean | no       | If `true`, the exit cannot be traversed in reverse. |

#### Exit `on_traverse` effects

| Effect               | Description |
|----------------------|-------------|
| `set_flag` / `value` | Sets a hard-state flag to the given value. |
| `set_flag` / `narrative` | Pre-written prose for the traverse event. |
| `trigger_encounter`  | Triggers a named encounter from `mechanics`. |
| `skip_if`            | Condition under which the encounter/effect is skipped. |
| `narrative_skip`     | Short narrative for when the effect is skipped. |

### Condition object

Conditions can appear on exits, interactions, on_enter events, and mechanics.
They are simple predicate objects evaluated against hard game state.

**`require`** — condition must be true for the thing to be available:

```json
{ "require": "flag:handkerchief_moved == true" }
```

**`unless`** — condition blocks availability if true:

```json
{ "unless": "flag:injured == true" }
```

**`any`** — at least one sub-condition must be true:

```json
{ "any": [
  "flag:handkerchief_noticed == true",
  "flag:korbar_told_secret == true"
] }
```

**`all`** — all sub-conditions must be true:

```json
{ "all": [
  "flag:spider_fled == true",
  "flag:handkerchief_moved == true"
] }
```

Condition strings use the format `<domain>:<key> <op> <value>`:
- `flag:<name>` — refers to a key in `hard_state.flags`.
- `inventory:<item_id>` — checks if an item is in the player's inventory.
- Supported ops: `== true`, `== false`, `>= <number>`.

---

### Interaction object

```json
{
  "id": "string (unique within the room)",
  "label": "string (short label for UI/debug)",
  "description": "string (what the player is attempting)",
  "condition": { /* condition object or null */ },
  "check": { /* roll check or null */ },
  "success": { /* result */ },
  "failure": { /* result or null */ },
  "result": { /* result (used when no check is present) */ }
}
```

| Field         | Type         | Required | Description |
|---------------|-------------|----------|-------------|
| `id`           | string      | yes      | Unique within the room. Referenced by `interact` action `target`. |
| `label`        | string      | yes      | Human-readable action label. |
| `description`  | string      | no       | Extended description of the action. |
| `condition`    | object|null | no       | Condition that must be met for the interaction to be available. |
| `check`        | object      | no       | A probabilistic check (roll). If absent, `result` is used directly. |
| `success`      | object      | no       | Result when the check succeeds. |
| `failure`      | object      | no       | Result when the check fails (optional; if absent, engine returns a generic "nothing happens"). |
| `result`       | object      | no       | Deterministic result (used when no `check` is present). |

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
| `add_item`    | string | Item entity ID to add to inventory. |
| `remove_item` | string | Item entity ID to remove from inventory. |
| `set_flag`    | object | Hard-state flags to set or clear. |
| `reveals`     | string | Hint text; added to the player's known information for future GMBriefings. |

---

### On-enter event object

```json
{
  "id": "string (unique within the room)",
  "condition": "string (e.g. 'flag:fly_alive == true') or null (fires exactly once)",
  "action": "narrative_and_flag",
  "narrative": "string",
  "set_flag": { "<flag_name>": true | false }
}
```

| Field       | Type         | Description |
|-------------|-------------|-------------|
| `id`         | string      | Unique event identifier within the room. |
| `condition`  | string|null | Condition string. If null, fires exactly once on first entry (engine tracks internally). |
| `action`     | string      | Currently `"narrative_and_flag"`. |
| `narrative`  | string      | Canonical narration text. |
| `set_flag`   | object      | Flags to set or clear. |

---

## `entities` — Entity definitions

Entities are typed objects that appear in rooms or inventory. Keyed by unique `entity_id`.

```json
{
  "<entity_id>": {
    "type": "feature | npc | trap | item",
    "subtype": "monster (optional, for npc)",
    "description": "string",
    "spans_rooms": ["<room_id>", ...],
    "tags": ["<tag>", ...],
    "draggable": false,
    "dragging_note": "string",
    "dialogue_guidelines": { /* only for npc type */ },
    "behavior": { /* only for npc (monster) type */ },
    "state_fields": { "<field_name>": { "type": "boolean | number | string", "description": "string" } }
  }
}
```

| Field                | Type   | Applies to    | Description |
|----------------------|--------|---------------|-------------|
| `type`               | enum   | all           | `feature`, `npc`, `trap`, `item`. |
| `subtype`            | string | npc           | Optional qualifier; currently `"monster"`. |
| `description`        | string | all           | Canonical description returned for `examine` action. |
| `spans_rooms`        | array  | feature       | List of room IDs this entity is visible in (e.g., the battleaxe spans multiple rooms). |
| `tags`               | array  | item          | Semantic tags for mechanical matching (e.g., `"weapon"`, `"key_item"`, `"draggable"`). |
| `draggable`          | bool   | item          | If true, the item can be dragged but occupies the player (no other manual actions while dragging). |
| `dragging_note`      | string | item          | Narrative note describing the encumbrance. |
| `dialogue_guidelines`| object | npc           | See below. |
| `behavior`           | object | npc (monster) | Encounter rules for combat. See below. |
| `state_fields`       | object | all           | Declaration of mutable state fields for this entity. The engine initialises these from hard-state.json and tracks changes. |

### `dialogue_guidelines` (for NPC type)

```json
{
  "personality": "string (tone, demeanor, motivations)",
  "on_encounter": "string (what happens when first met, e.g. auto-event)",
  "can": ["list of things the NPC can/will do"],
  "cannot": ["list of things the NPC will never do or say"],
  "knows": ["list of facts the NPC possesses"],
  "will_reveal": {
    "<topic>": "string describing under what conditions the NPC shares this information"
  }
}
```

These are supplied to LLM Call 1 and Call 2 to constrain NPC dialogue improvisation. The engine enforces the `cannot` constraints via the `warnings` field in EngineResult.

### `behavior` (for NPC with combat)

```json
{
  "triggers_on": "<exit_id | interaction_id>",
  "encounter_rules": {
    "<outcome_key>": {
      "outcome": "death | flee | roll_50_percent | spider_flees",
      "threshold": 0.50,
      "narrative": "string",
      "set_flags": { "<flag>": true },
      "on_success": { /* nested outcome */ },
      "on_failure": { /* nested outcome */ }
    }
  },
  "on_flee": {
    "set_flags": { "<flag>": true },
    "effect": "string describing subsequent behavior change"
  }
}
```

Outcomes are selected by matching the player's current state (inventory, flags) against the outcome keys. The engine evaluates conditions in the `encounter_rules` (inside the `mechanics` top-level block, which contains the authoritative encounter definitions) and applies the matched outcome.

---

## `mechanics` — Encounter and system rules

Named mechanics referenced by exits and interactions.

### Encounter

```json
{
  "<mechanic_id>": {
    "id": "string",
    "description": "string",
    "rules": [
      {
        "condition": "string (evaluated against player state)",
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

Rules are evaluated top-to-bottom. The first rule whose `condition` matches is applied. Conditions are evaluated against:
- `inventory does not contain any item with tag 'weapon'`
- `inventory contains weapon AND flag:injured == true`
- `inventory contains weapon AND flag:injured == false`

### Win condition

```json
{
  "win_condition": {
    "description": "string",
    "check": "string (human-readable description of what must happen)",
    "on_win": {
      "narrative": "string",
      "outcome": "game_over_win"
    }
  }
}
```

The win condition is not evaluated automatically each turn. It is checked when a `use` action matches a special item–target combination (e.g., using the `key` on the exterior padlock from room `axe_head`). The engine checks if all criteria are met and returns `game_over: { type: "win", narrative: "..." }` in EngineResult.

**Item–target mechanics** for the `use` action should be defined as a first-class mechanic in future versions. For the test adventure, the win condition is special-cased: the engine checks `player location == axe_head`, `inventory contains key`, `action_type == use`, `target == padlock`.

---

## `game_over_conditions` — Terminal states

```json
[
  {
    "id": "string",
    "trigger": "string (human-readable)",
    "type": "success | failure"
  }
]
```

This is largely documentation. The actual game-over triggers are the spider death encounter and the win condition, both resolved by the engine during action resolution.

---

## Example Module Loading

In the reference implementation, the module corpus is loaded once at startup from a JSON file (e.g., `adventures/bag-of-holding/corpus.json`). The engine holds it in memory as a read-only data structure. No vector database or semantic search is needed — all lookups are by deterministic ID.
