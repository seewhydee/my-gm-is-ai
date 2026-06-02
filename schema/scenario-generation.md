# Scenario-to-JSON Generation Instructions

This document is a prompt/checklist for an LLM agent to convert a natural-language adventure scenario (e.g., `scenario.md`) into the three structured JSON files the engine requires:

- `corpus.json` — read-only adventure content (rooms, entities, mechanics)
- `hard-state.json` — initial authoritative runtime state
- `soft-state.json` — initial narrative-oriented mutable state

The agent must follow the schemas defined in:
- [`corpus.md`](corpus.md) for the Module Corpus
- [`hard-state.md`](hard-state.md) for Hard Game State
- [`soft-state.md`](soft-state.md) for Soft Game State
- [`actions.md`](actions.md) for actions (which describe what the engine validates)

---

## 1. Input Assumptions

The input is a Markdown file containing:

- An adventure title and optional credits/license note.
- An introduction paragraph (shown to the player at game start).
- A list of rooms with prose descriptions, connected exits, entities present,
  special interactions, and per-room mechanics (e.g. secret compartments).
- A section on NPCs (dialogue, knowledge, attitude gating, combat rules).
- A section on overall mechanics (dropping rules, combat rules, win/loss conditions).

The agent must extract all structured information from this prose and encode it
into the JSON schemas below — never inventing entities, rooms, or mechanics not
present in the scenario.

---

## 2. General Naming and ID Conventions

- All IDs (rooms, entities, exits, interactions, mechanics) must be
  **snake_case, lowercase ASCII**.
- Room IDs: descriptive, e.g. `axe_head`, `bag_floor`, `secret_compartment`.
- Entity IDs: descriptive, e.g. `spider`, `korbar`, `rusty_key`, `toenail_sword`.
- Exit IDs: prefixed `exit_` followed by a short description of the traversal,
  e.g. `exit_climb_down_handle`, `exit_drop_into_darkness`,
  `exit_leave_secret_compartment`.
- Interaction IDs: descriptive snake_case.
- Mechanic IDs: descriptive, e.g. `fall_damage`, `win_escape_bag`.
- Flag names: descriptive snake_case, e.g. `spider_fled`, `injured`,
  `handkerchief_noticed`, `padlock_unlocked`.
- Soft item names: lowercase generic name, e.g. `rock`, `cork`, `sandwich`.
- Topic IDs in `will_reveal`: descriptive snake_case, e.g.
  `padlock_mechanism`, `secret_compartment`, `abandonment`.

---

## 3. Generating `corpus.json`

The Module Corpus has three top-level keys: `"adventure"`, `"rooms"`,
`"entities"`, `"mechanics"`.

### 3.1 `adventure`

```json
{
  "title": "string — scenario title",
  "credits": {
    "author": "string — from scenario preamble",
    "source": "string — e.g. competition name and year",
    "license": "string — e.g. CC BY-SA 4.0"
  },
  "introduction": "string — opening narration verbatim from scenario",
  "atmosphere": {
    "setting": "string — 1-2 brief sentences about the world",
    "tone": "string — desired narrative style"
  }
}
```

- `introduction`: use the intro paragraph verbatim (or very close to it).
- `atmosphere`: synthesize from the scenario's overall feel. Do not reveal
  secrets or spoilers — describe only the initial dramatic situation.

### 3.2 `rooms`

For each room in the scenario, produce a single entry under its room ID.

```json
{
  "<room_id>": {
    "name": "string — short display name",
    "description": "string — full prose shown on entry and on examine room",
    "entities_present": ["<entity_id>", ...],
    "soft_items": ["string", ...],
    "exits": [ { /* exit object */ } ],
    "interactions": [ { /* interaction object */ } ],
    "on_enter": [ { /* on_enter event object */ } ],
    "is_start_room": false
  }
}
```

#### Room description

- Write full second-person prose describing what the player sees, hears, smells,
  and any notable features. Include hints of interactable entities.
- The description should be sufficient for both room entry and re-examination.
- Do not include clues gated behind a rigorous search or NPC reveal — those are
  returned by the *engine* as examine outcomes, not as the base description.

#### `entities_present`

- List the entity IDs of every entity physically in this room at game start.
- Do not include the player entity or soft items here.
- Features that span multiple rooms (e.g. a giant battleaxe sticking through
  several rooms) should be listed in every room they span, and carry a
  `spans_rooms` array in the entity definition.
- Hidden entities (e.g. a key inside a secret compartment) are listed only in
  the rooms that contain them, but the exit/condition guarding access ensures
  the player cannot interact with them until revealed.

#### `soft_items`

- List plausible generic items a player might pick up in this room.
- These should be nondescript, environmentally-appropriate items (rocks in a
  cavern, cork on rubbish heap, loose change on a table).
- Never list items that carry plot significance — those must be proper
  entities with unique IDs.
- Each entity present may also carry its own `soft_items` list (see §3.3).

#### Exits

Each exit is:

```json
{
  "id": "string — unique exit ID",
  "direction": "string — natural-language label for LLM context",
  "target_room": "<room_id>",
  "conditions": [ { /* condition */ } ],
  "on_traverse": { /* traversal effect or null */ },
  "hidden": false,
  "one_way": false
}
```

- **`direction`**: natural language (e.g. "Climb carefully down the axe handle",
  "Drop down into the darkness below").
- **`conditions`**: if exit availability depends on flags, inventory, or entity
  state. Each condition is an object with `require`, `unless`, `any`, or `all`.
  See the Condition syntax section below (§6).
- **`on_traverse`**: effects applied when the player uses this exit:
  - `set_flag` / `value` — boolean flag to set
  - `set_flag` / `narrative` — prose for the traversal
  - `trigger_encounter` — encounter mechanic to trigger
  - `skip_if` — condition to skip (optional)
  - `narrative_skip` — prose when skipped (optional)
- **`hidden`**: set `true` for exits that are secret/unrevealed at game start
  (e.g. a hidden flap under a handkerchief). The engine omits these from
  GMBriefing until the reveal condition is met. The reveal condition is a
  separate mechanic — model this by having an interaction on the concealing
  entity that sets a flag, and making the exit's `conditions` require that flag.
- **`one_way`**: set `true` if the exit cannot be traversed in reverse. For
  dropping-down exits that don't permit climbing back up, set `one_way: true`.

#### Interactions (room-level)

Interactions specific to a room (not to a particular entity) go here:

```json
{
  "id": "string — unique per room, referenced in interact actions",
  "label": "string — short label for debug",
  "description": "string — what the player is attempting",
  "parameter_signature": {
    "target": ["entity", "soft_item"],
    "using": ["entity", "soft_item"]
  },
  "condition": { /* condition or null */ },
  "check": { /* roll check or null */ },
  "success": { /* result */ },
  "failure": { /* result or null */ },
  "result": { /* result (when no check present) */ }
}
```

- If no check is needed (deterministic outcome), omit `check`, `success`, and
  `failure`; use only `result`.
- If a probabilistic check is needed, define `check` + `success` + `failure`.
- `parameter_signature` constrains what `interact` action `target` and `using`
  can reference. When absent, there are no type restrictions beyond existence.
- Generic interactions like `attack` or `take` do NOT need to be defined in the
  corpus — they are available everywhere. Only define non-standard interactions.

**Check object:**
```json
{
  "type": "roll",
  "threshold": 0.50,
  "repeatable": false,
  "note": "Optional designer note"
}
```

- `threshold` is 0.0–1.0. Roll succeeds if `random() < threshold`.
- `repeatable`: if `false`, the engine tracks attempts and rejects retries.

**Result object:**
```json
{
  "narrative": "string — pre-written outcome prose",
  "add_item": "<item_id>",
  "remove_item": "<item_id>",
  "set_flag": { "<flag_name>": true | false },
  "reveals": "string — hint for player's future reference"
}
```

- All fields are optional; an empty `{}` result means "nothing notable happens."
- `narrative` goes to LLM Call 2 as `triggered_narration` — it should be
  canonical prose for the event.

#### On-enter events

```json
{
  "id": "string — unique within the room",
  "condition": "string or null (fires exactly once if null)",
  "action": "narrative_and_flag",
  "narrative": "string — canonical narration",
  "set_flag": { "<flag_name>": true | false }
}
```

- If `condition` is null, the event fires on the first entry only.
- A condition string like `"flag:fly_alive == true"` gates the event on a flag.
- Use on-enter events for: introductory room flavour, NPC auto-dialogue, trap
  triggering, revealing information the player would immediately notice.

### 3.3 `entities`

Each entity is keyed by a unique entity ID:

```json
{
  "<entity_id>": {
    "type": "player | feature | npc | trap | item",
    "description": "string — canonical description for examine action",
    "spans_rooms": ["<room_id>", ...],
    "soft_items": ["string", ...],
    "tags": ["<tag>", ...],
    "draggable": false,
    "dragging_note": "string",
    "interactions": [ { /* interaction */ } ],
    "dialogue_guidelines": { /* npc only */ },
    "behavior": { /* npc (monster) only */ },
    "state_fields": { "<field_name>": { "type": "...", "description": "..." } }
  }
}
```

#### Required for all entity types

- `type`: one of `player`, `feature`, `npc`, `trap`, `item`.
- `description`: the prose returned when the player examines this entity.
  Write in the style of a GM describing the thing. For NPCs, include visual
  description including posture, attire, visible emotional state.
- `state_fields`: declare every hard-state field the engine tracks for this
  entity. Common fields:
  - `alive` (boolean) — for NPCs and creatures that can die
  - `fled` (boolean) — for creatures that can flee
  - `told_secret` (boolean) — for NPCs with secret knowledge
  - `activated`, `revealed`, `opened` — for features and traps
  - `visited_once` — for special interactions
  Each field entry is `{ "type": "boolean|number|string", "description": "..." }`.

#### `player` type

- Exactly one entity must have `type: "player"`.
- `description`: a general description of the player character (from their
  perspective, used when examining oneself).
- `state_fields`: standard fields like `alive` if death is possible.
- Usually has no `dialogue_guidelines`, `behavior`, or `interactions`.

#### `feature` type

- Inanimate or environmental objects: webs, walls, piles of rubbish, a
  handkerchief, a giant battleaxe.
- Features that span multiple rooms (like a battleaxe visible from several
  rooms) use `spans_rooms` to list all rooms where they are present.
- Interactions attached to features go in the `interactions` array (e.g.
  `search_handkerchief` on the handkerchief entity, `rummage_for_weapon` on the
  rubbish pile).

#### `npc` type

- Characters the player can talk to, fight, or interact with.
- Required: `dialogue_guidelines` block (see below).
- For combat-capable NPCs: `behavior` block (see below).

##### `dialogue_guidelines`

```json
{
  "personality": "string — tone, demeanor, motivations",
  "on_encounter": "string — auto-event on first meeting",
  "can": ["string — things the NPC can/will do"],
  "cannot": ["string — things the NPC will never do or say"],
  "knows": ["string — facts the NPC possesses"],
  "attitude_limits": {
    "min": -5,
    "max": 10,
    "step_per_turn": 3,
    "initial": 0
  },
  "will_reveal": {
    "<topic_id>": {
      "description": "string — what the NPC reveals",
      "conditions": ["attitude:korbar >= 2", "topic:abandonment", "item:rusty_key"]
    }
  }
}
```

- `personality`: 2-4 sentence summary. Include manner of speaking, emotional
  state, core motivation, fears.
- `can` / `cannot`: hard constraints the LLM must obey when narrating NPC speech
  and behaviour. The engine flags violations in `warnings`. Be specific — these
  are the "firewall" against LLM confabulation.
- `knows`: all facts the NPC possesses, even if gated. Helps the LLM improvise
  dialogue without inventing knowledge.
- `attitude_limits`: integer caps. `step_per_turn` limits single-turn attitude
  shifts. A troll who never turns friendly might have `min: -5, max: -1`.
- `will_reveal`: each topic has a conditions array. Conditions are strings using
  the format described in §6. Common gates:
  - `"attitude:<npc_id> >= <N>"` — attitude threshold
  - `"item:<item_id>"` — player must have the item
  - `"topic:<topic_name>"` — a prior topic must have been discussed
  - `"flag:<flag_name> == true"` — a hard-state flag must be set

##### `behavior` (combat NPCs)

```json
{
  "triggers_on": "<exit_id or interaction_id>",
  "encounter_rules": [
    {
      "condition": "string",
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
    "effect": "string — description of subsequent behaviour"
  }
}
```

- Rules are evaluated top-to-bottom; the first matching condition applies.
- For phase 1 (kill-or-be-killed resolution), outcomes are `death` (player
  dies → game over), `flee` (creature flees), or `roll` (check-based).
- `condition` is a string evaluated against flags, inventory, entity state.
  Typical patterns:
  - `"tag:weapon"` — player has a weapon (checks for any item with `"weapon"` tag)
  - `"flag:injured == true"` — player is injured
  - `"inventory:toenail_sword"` — player has a specific item
- When `outcome: roll`, `threshold` and `on_success`/`on_failure` are used.
- `on_flee`: applied when a flee outcome triggers. Sets flags (e.g.
  `spider_fled`) and records behavioural effects for the narrating LLM.

#### `item` type

- Objects that can be picked up, carried, given, used as weapons, etc.
- `tags`: semantic tags for mechanical matching. Common tags:
  - `"weapon"` — can be used to attack; checked via `tag:weapon`
  - `"key_item"` — plot-significant item
  - `"stackable"` — duplicates allowed in inventory
- `draggable`: if `true`, the player is encumbered while carrying it (no manual
  actions except movement).
- `dragging_note`: narrative description of the encumbrance.
- Items placed in a specific room at game start should appear in that room's
  `entities_present` list.
- Items the player starts with should appear in `hard-state.json`
  `player.inventory`.

#### `trap` type

- For hazards with mechanical consequences. Currently similar to features but
  with explicit danger semantics.

### 3.4 `mechanics`

Two categories: **encounters** and **game-over conditions**.

#### Encounters

```json
{
  "<mechanic_id>": {
    "id": "string — unique mechanic identifier",
    "description": "string — human-readable summary",
    "rules": [
      {
        "condition": "string — evaluated against player state",
        "outcome": "death | flee | roll",
        "threshold": 0.50,
        "narrative": "string — canonical narration of the outcome",
        "set_flags": { "<flag>": true },
        "on_success": { "outcome": "...", "set_flags": {}, "narrative": "..." },
        "on_failure": { "outcome": "...", "narrative": "..." }
      }
    ]
  }
}
```

- Encounters are referenced by exits (`trigger_encounter`) or interactions.
- Rules use the same format as entity `behavior.encounter_rules`.

#### Game-over conditions

```json
{
  "<mechanic_id>": {
    "id": "string — unique identifier",
    "type": "win | lose",
    "description": "string — what must happen",
    "condition": "string — evaluated each turn or on trigger",
    "narrative": "string — canonical ending narration",
    "trigger_id": "string — matches game_over.trigger in hard state"
  }
}
```

- `condition` uses the standard condition string format. For a win condition
  gated on multiple flags:
  `"all: flag:padlock_unlocked == true , flag:player_escaped == true"`
  (The exact `all`/`any` syntax is object-based, not string-based — use the
  `all`/`any` condition objects, not string shorthand.)
- `narrative`: the closing prose. Should be satisfying; this is shown to the
  player when the game ends.
- `trigger_id`: short snake_case string matching what will appear in
  `hard_state.game_over.trigger`.

---

## 4. Generating `hard-state.json`

Initial hard state. See `hard-state.md` for the full schema.

```json
{
  "player": {
    "location": "<room_id of start room>",
    "inventory": ["<entity_id>", ...]
  },
  "flags": {
    "<flag_name>": true | false
  },
  "room_states": {
    "<room_id>": { "<field>": <value> }
  },
  "entity_states": {
    "<entity_id>": { "<field>": <value> }
  },
  "turn_count": 0,
  "game_over": null
}
```

### Step by step

1. **`player.location`**: set to the ID of the room with `is_start_room: true`.
2. **`player.inventory`**: list any entity IDs the player starts with. Usually
   empty (no starting items).
3. **`flags`**: enumerate every flag name used anywhere in the corpus
   (conditions, `set_flag` results, encounter outcomes, etc.). Set each to its
   initial value (almost always `false`).
4. **`room_states`**: for every room in the corpus, add an entry with `visited:
   false`. If a room has additional `state_fields`, add them with initial values
   (boolean → `false`, number → `0`, string → `""`).
5. **`entity_states`**: for every entity that declared `state_fields` in the
   corpus, add an entry with initial values for each declared field. **Do not
   skip any entity that has state_fields.** Boolean fields default to `false`;
   `alive` for creatures that start alive should be `true`.
6. **`turn_count`**: always `0`.
7. **`game_over`**: always `null`.

### Validation checklist for hard-state.json

- [ ] Every room in the corpus has a `room_states` entry with `visited: false`.
- [ ] Every entity with `state_fields` in the corpus has an `entity_states`
  entry with all fields initialised.
- [ ] Every flag name used in condition strings or `set_flag` results appears
  in `flags` with an initial value.
- [ ] `player.location` references a valid room ID with `is_start_room: true`.
- [ ] No entity IDs in `player.inventory` duplicate room `entities_present`
  (an item should not be both in inventory and in a room at start).

---

## 5. Generating `soft-state.json`

Initial soft state. See `soft-state.md` for the full schema.

```json
{
  "soft_inventory": [],
  "room_notes": {},
  "entity_notes": {},
  "npc_attitudes": { "<npc_entity_id>": <integer> },
  "turn_history": [],
  "dialogue_state": {
    "active_npc": null,
    "conversation_log": [],
    "topics_discussed": [],
    "entered_turn": 0,
    "stall_counter": 0
  }
}
```

### Step by step

1. **`soft_inventory`**: always `[]` at start. The player begins with no soft
   items.
2. **`room_notes`**: initialise as an empty object `{}`. The engine will
   populate it dynamically. (Alternatively, pre-populate with an empty array for
   each room: `{ "axe_head": [], ... }`. Either is acceptable.)
3. **`entity_notes`**: empty object `{}` (or pre-filled with empty arrays per
   entity).
4. **`npc_attitudes`**: for every NPC entity (type `npc`), add an entry with
   the initial attitude value from that NPC's
   `dialogue_guidelines.attitude_limits.initial`. If `initial` is not specified,
   use `0`.
5. **`turn_history`**: always `[]`.
6. **`dialogue_state`**: always the null-state structure shown above.

### Validation checklist for soft-state.json

- [ ] Every NPC in the corpus has an entry in `npc_attitudes`.
- [ ] Attitude values are within the NPC's `[min, max]` range.
- [ ] `dialogue_state` has the null structure (all fields present with empty/null
  initial values).

---

## 6. Condition Syntax Reference

Conditions appear on exits, interactions, on-enter events, and mechanics. They
use the following formats:

### Simple condition (object-based)

```json
{ "require": "flag:spider_fled == true" }
{ "unless": "flag:injured == true" }
```

### Compound condition

```json
{ "any": [
  "flag:handkerchief_noticed == true",
  "flag:korbar_told_secret == true"
] }
```

```json
{ "all": [
  "flag:spider_fled == true",
  "flag:handkerchief_moved == true"
] }
```

### Condition string format

```
<domain>:<key> <op> <value>
```

| Domain       | Example                          | Meaning |
|--------------|----------------------------------|---------|
| `flag`       | `flag:door_opened == true`       | Hard-state flag |
| `inventory`  | `inventory:rusty_key`            | Item entity ID in player inventory |
| `tag`        | `tag:weapon`                     | Any item with this tag in player inventory |
| `entity`     | `entity:spider.alive == true`    | Entity hard-state field |
| `room`       | `room:axe_head.visited == true`  | Room state field |
| `attitude`   | `attitude:korbar >= 2`           | NPC soft-state attitude |

Supported ops: `== true`, `== false`, `== <string>`, `>= <number>`,
`> <number>`, `<= <number>`, `< <number>`.

### Usage notes

- For `unless`, the condition is true (and thus blocks) when the string evaluates
  to true. For example, `{ "unless": "flag:injured == true" }` means "this exit
  is unavailable if the player is injured."
- `inventory` and `tag` conditions test presence, not equality.
- `tag:weapon` succeeds if *any* item in inventory has the `"weapon"` tag.

---

## 7. Complete Step-by-Step Workflow

Follow these steps in order:

### Step A: Parse the scenario

Read the entire scenario and identify:
- The adventure title, credits, introduction.
- Every room (name, description, contents, exits, special rules).
- Every entity mentioned (NPCs, items, features, traps).
- Every encounter and mechanic (combat, dropping, searching, win/loss).
- The start room.
- NPC dialogue information (personality, knows, secrets, attitude gating).
- All flags mentioned in conditions (injury, spider fled, handkerchief moved,
  etc.).

### Step B: Create the entity list

For every entity in the scenario, decide its `type` and declare its
`state_fields`.

- Start with the player entity (type `player`).
- NPCs → type `npc` with `dialogue_guidelines`.
- Combat NPCs → also add `behavior`.
- Static dressing → type `feature`.
- Pickup-able objects → type `item`, with appropriate `tags`.
- Hazards → type `trap`.

### Step C: Create rooms

For each room, fill in:
- `name`, `description` (prose)
- `entities_present` (list of entity IDs)
- `soft_items` (plausible nondescript items)
- `exits` (every way out)
- `interactions` (special room-level actions)
- `on_enter` events (first-entry narration or conditional triggers)
- `is_start_room` (exactly one)

### Step D: Add entity-level interactions and details

- Attach interactions to entities (e.g. `search_handkerchief` on the
  handkerchief feature).
- Fill in `dialogue_guidelines` for every NPC.
- Fill in `behavior` for combat NPCs.
- Assign `tags` to items.

### Step E: Create mechanics

- Model encounters as mechanic entries (e.g. spider encounter, dropping damage).
- Model win and loss conditions as mechanic entries with `type: "win"` or
  `"lose"`.

### Step F: Generate `hard-state.json`

Follow §4. Ensure every flag, room, and entity state field is initialised.

### Step G: Generate `soft-state.json`

Follow §5. Ensure every NPC gets an attitude entry.

### Step H: Cross-file validation

- [ ] Every entity ID appearing in `rooms.*.entities_present` exists in the
  `entities` block.
- [ ] Every exit `target_room` references a valid room ID.
- [ ] Every condition string references flags that are declared in
  `hard_state.flags`.
- [ ] Every `set_flag` flag name is declared in `hard_state.flags`.
- [ ] Every `add_item` / `remove_item` references a valid entity ID.
- [ ] Every `trigger_encounter` references a valid `mechanics` entry.
- [ ] Every `entity_id` in `soft_state.npc_attitudes` has
  `dialogue_guidelines` in its corpus entity definition.
- [ ] Every `entity_id` in `soft_state.npc_attitudes` has `type: "npc"`.
- [ ] `hard_state.player.location` is the room with `is_start_room: true`.
- [ ] `soft_state.dialogue_state` has the standard null structure.

---

## 8. Common Pitfalls and Edge Cases

1. **Confusing soft items with entities**: If the scenario says "there are rocks
   on the ground", those are soft items. If it says "the key of rusty iron is
   in the secret compartment", the key is an entity (it has plot significance).
   The litmus test: *will a condition, mechanic, or specific interaction
   reference this thing by name?* If yes → entity. If no → soft item.

2. **Forgetting to declare flags**: Every flag referenced in any `set_flag`,
   condition string, or `require`/`unless` block must appear in
   `hard_state.flags` with an initial value. Forgetting one causes engine
   startup failure.

3. **Missing `state_fields` declarations**: Every mutable property of an entity
   that changes during play (alive, fled, told_secret, opened, activated) must
   be declared in `state_fields`. The engine validates at startup that
   `hard_state.entity_states` and `corpus.entities.<id>.state_fields` match.

4. **Hidden exits without reveal conditions**: A `hidden: true` exit needs a
   companion mechanic (usually an interaction on the concealing entity) that
   sets a flag; the exit's `conditions` should require that flag. Otherwise the
   exit is permanently invisible.

5. **One-way exits without constraints**: A `one_way: true` exit (e.g. dropping
   down) should have a separate exit back up (perhaps one-way in the opposite
   direction, or requiring a climb check).

6. **Duplicate IDs**: Ensure every ID (room, entity, exit, interaction, mechanic,
   flag, topic) is unique across the entire corpus.

7. **NPCs with no `dialogue_guidelines`**: Every `npc` entity must have a
   `dialogue_guidelines` block, even if the NPC has nothing to say — provide
   minimal guidelines (`personality`, empty `can`/`cannot`/`knows` arrays).

8. **Missing `on_encounter` narrative for NPCs**: If the scenario describes what
   happens when the player first meets an NPC, encode it in
   `dialogue_guidelines.on_encounter` and/or as a room `on_enter` event.

9. **Ambiguous condition syntax**: Use the object-based form
   (`{ "require": "..." }`, `{ "any": [...] }`) for conditions attached to
   exits, interactions, and on-enter events. Use the plain string form
   (`"flag:injured == true"`) for the `condition` field in encounter rules and
   game-over mechanics (check the corpus schema for which form each field
   expects).

10. **Attitude initialisation**: The `npc_attitudes` in soft-state.json must
    use the NPC's `attitude_limits.initial` value. If a scenario says "Korbar
    is initially neutral", that's `0`. If she's described as friendly, set
    higher (e.g. `1` or `2`).

11. **Item placement**: Items that start in a specific location should appear
    in that room's `entities_present`. Items the player starts carrying should
    be in `hard_state.player.inventory`. Never put the same item ID in both.

12. **Prose style**: All descriptions (`description` fields, `narrative` fields,
    `introduction`) should be in second-person present tense ("You see... You
    are...") matching the interactive fiction convention.
