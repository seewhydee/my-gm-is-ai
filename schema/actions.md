# Action Schema

This defines the structured data formats that flow between the core-loop
components: Context Assembler -> LLM Call 1 -> Engine -> LLM Call 2.

## Core Loop Data Flow

```
Player Input
       |
       v
+------------------------------+
| 1. Context Assembler         |
|    Reads:  Module Corpus     |
|           + Hard State       |
|           + Soft State       |
|    Produces: GMBriefing      |
+------------------------------+
       |
       v
+------------------------------+
| 2. LLM Call 1: Ruling        |
|    Input:  GMBriefing        |
|           + Player Input     |
|    Output: PlayerAction      |
|           + SoftStatePatch[] |
+------------------------------+
       |
       v
+------------------------------+
| 3. Engine Resolution         |
|    Reads:  Module Corpus     |
|           + Hard/Soft State  |
|    Validates & Resolves      |
|    Writes: Hard State        |
|    Produces: EngineResult    |
+------------------------------+
       |
       v
+------------------------------+
| 4. LLM Call 2: Prose         |
|    Input:  Chat Log          |
|           + GMBriefing       |
|           + EngineResult     |
|    Output: Narration (text)  |
|           + knowledge_tags   |
|           + attitude_changes |
+------------------------------+
       |
       v
+------------------------------+
| 4.5. Engine Post-Validation  |
|    (if knowledge_tags or     |
|     attitude_changes present)|
|    Reads:  Module Corpus     |
|    Validates & Applies       |
|    Produces: corrected       |
|    EngineResult              |
+------------------------------+
       |
       v
   Player (text output)
```

---

## 1. GMBriefing -- Input to LLM Call 1

Assembled by the Context Assembler from Module Corpus, Hard State, and
Soft State, for the ruling LLM (call 1).

```json
{
  "adventure_title": "You're Trapped in a Bag of Holding!",
  "setting": "You are a person trapped inside a magical Bag of Holding — a pocket dimension full of discarded treasures, dangers, and a dwarf who has been lost here for years.",
  "tone": "Whimsical and slightly dark. The world is absurd but coherent. Danger is real but the tone is more Pratchett than Lovecraft.",
  "turn": 3,

  "current_room": {
    "id": "axe_handle_lower",
    "name": "Axe Handle (Lower)",
    "description": "You are on the lower section of the axe handle. The webs here are denser, blocking the path downward unless you push through. If you look carefully, you see the spider — huge and hungry for blood — lurking in the webs. Below, many irregularly shaped objects are coming into view. It looks like you could drop down safely. There is some muffled clanking from the shadows below.",
    "soft_items": ["rock", "loose stone"],
    "entities_visible": [
      {
        "id": "spider",
        "name": "Huge Spider",
        "type": "npc",
        "description": "A huge, hungry spider lurking in the dense webs.",
        "state": { "alive": true, "fled": false },
        "entity_notes": [],
        "soft_items": [],
        "dialogue_paths": {
          "flatter": "Praise the spider's hunting prowess to improve its attitude toward the player."
        }
      },
      {
        "id": "webs_dense",
        "name": "Dense Webs",
        "type": "feature",
        "description": "Thick webs blocking the downward path.",
        "state": {},
        "entity_notes": [],
        "soft_items": []
      }
    ],
    "exits_available": [
      { "id": "exit_up_handle_lower", "direction": "Walk up the axe handle", "target_room": "axe_handle_upper", "hidden": false },
      { "id": "exit_through_webs", "direction": "Push through the dense webs downward", "target_room": "bag_floor", "hidden": false },
      { "id": "exit_drop_lower", "direction": "Drop safely down to the floor", "target_room": "bag_floor", "hidden": false }
    ],
    "interactions_available": [],
    "room_notes": ["The webs here are partially cleared from the spider's flight."]
  },

  "player_state": {
    "location": "axe_handle_lower",
    "hard_inventory": ["iron_sword"],
    "soft_inventory": ["rock"],
    "active_flags": { "injured": false, "stunned": false },
    "entity_notes": [],
    "player_stats": {
      "STR": { "value": 14, "modifier": 2 },
      "DEX": { "value": 12, "modifier": 1 },
      "CON": { "value": 13, "modifier": 1 },
      "INT": { "value": 10, "modifier": 0 },
      "WIS": { "value": 8, "modifier": -1 },
      "CHA": { "value": 16, "modifier": 3 }
    }
  },

  "npc_revelations": {
    "korbar": [
      {
        "topic_id": "padlock_mechanism",
        "description": "How the exterior padlock can be opened from inside"
      }
    ]
  },

  "recent_history": [
    {
      "turn": 2,
      "summary": "Player climbed down the axe handle from axe_head, passing through axe_handle_upper where a dying fly warned about the spider. Now at axe_handle_lower.",
      "location_after": "axe_handle_lower"
    },
    {
      "turn": 1,
      "summary": "Player woke up on the axe head inside the Bag of Holding. Examined surroundings. Noticed the rip in the canvas.",
      "location_after": "axe_head"
    }
  ],

  "dialogue_context": {
    "active_npc": {
      "id": "korbar",
      "name": "Korbar the Dwarf",
      "attitude": 2,
      "dialogue_guidelines": {
        "personality": "Cynical dwarven rogue, heavy drinker, lonely but proud.",
        "cannot": ["Leave the bag", "Stop drinking", "Remember which way is north"],
        "knows": ["The padlock mechanism", "The secret compartment in the axe head"],
        "will_reveal": {
          "padlock_mechanism": {
            "description": "How the exterior padlock can be opened from inside",
            "conditions": ["attitude:korbar >= 2", "topic:abandonment"]
          },
          "secret_compartment": {
            "description": "A hidden cache inside the axe head",
            "conditions": ["attitude:korbar >= 4", "item:rusty_key"]
          }
        }
      }
    },
    "recent_exchanges": [
      { "turn": 4, "speaker": "player", "text": "Who are you?" },
      { "turn": 4, "speaker": "korbar", "text": "Arr, name's Korbar. Me party left me here." },
      { "turn": 5, "speaker": "player", "text": "Tell me more about your party." }
    ],
    "topics_discussed": ["origin", "abandonment"],
    "revealed_topics": ["padlock_mechanism"]
  },

  "player_input": "I pull up a chair to sit on and ask Korbar, 'What happened to your party?'"
}
```

### GMBriefing assembly rules

1. **Global setting**: `setting` and `tone` drawn from the module corpus
   `adventure.atmosphere` block.  Some brief sentences about the world and
   narrative style.

2. **Current room**: fetched by ID from the module corpus. Includes 
   `entities_visible`, listing all non-concealed entities in the room.
   Each of these entity entries includes the entity ID, current hard
   state, and entity notes (up to 3 most recent). For NPCs with
   `dialogue_guidelines.dialogue_paths`, `entities_visible[*].dialogue_paths`
   is a map of `{path_id: description}` so LLM Call 1 can match player intent
   to the correct special dialogue path.

3. **Soft items** in the room (from `room.soft_items`) are listed directly.
   Entity-specific soft items are listed under each entity's entry.

4. **Exits** whose conditions are met are included. Hidden exits (e.g., the
   secret compartment) are omitted unless their reveal flag is set.

5. **Player state** summarises hard inventory, soft inventory, active flags,
   entity notes, and (when the corpus defines stats) a `player_stats` block
   with each stat's value and computed modifier (e.g.
   `{ "value": 14, "modifier": 2 }`). This gives LLM Call 1 direct knowledge
   of the player's capabilities without requiring it to do the math.

6. **Recent history** is drawn from soft state `turn_history`, which
   summarizes the player's recent actions.  This includes the last 5
   proper entries from non-`ooc_discussion` turns; `ooc_discussion`
   entries are included but do not count toward the cap.  NO raw chat log.

7. **NPC attitudes** includes attitudes for all known NPCs.

8. **NPC revelations** are drawn from `soft_state.npc_revelations`. Each NPC
   with revealed topics lists them with their `will_reveal` descriptions, so
   LLM Call 1 knows what the player has learned from each NPC.

9. **Dialogue context** is included when `soft_state.dialogue_state.active_npc`
   is non-null. The block contains the active NPC's identity, attitude,
   full `dialogue_guidelines`, last 5 entries from `conversation_log`,
   `topics_discussed`, and `revealed_topics` (topic IDs already revealed to
   the player). If `active_npc` is null, `dialogue_context` is omitted.

10. **Player input** is the verbatim text entered this turn. For chained
    actions (described below), this is the original input plus a clear
	indication of where the chain currently stands.

---

## 2. PlayerAction -- Output of LLM Call 1

The LLM must output a single structured action, corresponding to the player's intent, for the engine to validate and resolve.  Every PlayerAction carries these fields:

| Field                        | Type    | Required | Description |
|------------------------------|---------|----------|-------------|
| `action_type`                | string  | yes      | One of the action types below. |
| `detail`                     | string  | yes      | Natural-language description of what the player attempts. |
| `follow_up`                  | string  | no       | The remainder of a chained action yet to be performed. See Follow-up below. |
| `proposed_soft_state_patches`| array   | no       | Structured soft-state patch requests. See SoftStatePatch in soft-state.md. |

### 2.1 Supported action types

#### `move` -- Travel between rooms

```json
{
  "action_type": "move",
  "target": "<exit_id>",
  "style": "crawling",
  "detail": "The player gets down on hands and knees and crawls through the narrow tunnel.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

| Field    | Type   | Required | Description |
|----------|--------|----------|-------------|
| `target` | string | yes      | The exit ID to traverse. Must be a valid, accessible, non-hidden exit from the current room. |
| `style`  | string | no       | Optional qualifier for special movement methods (e.g., "crawling", "running", "carefully"). |

**Engine validation:**
- `target` must be a valid exit_id in the current room.
- All `conditions` on the exit must be satisfied.
- If the exit has `on_traverse`, the engine applies the specified effects
  (set flags, trigger encounters, etc.).
- If the exit is `one_way: true`, reverse traversal is rejected.
- On success, `player.location` is set to the exit's `target_room`.

---

#### `examine` -- Look at something

```json
{
  "action_type": "examine",
  "target": "<entity_id or room_id>",
  "rigorous": false,
  "using": null,
  "detail": "The player peers closely at the rusty mechanism, looking for a way to disengage it.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

| Field      | Type          | Required | Description |
|------------|---------------|----------|-------------|
| `target`   | string        | yes      | A valid entity ID present in the current room, the current room ID itself (for examining the room), or a soft item name present in the current room or on a visible entity. |
| `rigorous` | boolean       | no       | If `true`, signifies an in-depth search. A schema may specify that only a rigorous search reveals hidden details. |
| `using`    | string\|null  | no       | A valid entity ID or soft item used to assist the examination (e.g., using a torch to look at a dark corner). |

**Engine validation:**
- `target` must be a valid entity in the current room's `entities_present`, the
  current room ID, or a soft item name present in the current room or on a
  visible entity.
- If `using` is specified, the item must be in the player's hard inventory
  (entity IDs) or soft inventory (soft item names).
- If `rigorous: true`, the engine evaluates the room/entity's interactions
  that were previously scoped only to rigorous search (i.e., checks that
  require the `rigorous` flag). Hidden exits, items, or state changes may
  be revealed.
- The engine returns the entity's `description` and any applicable
  examine-only narrative.

---

#### `interact` -- Perform a defined interaction

```json
{
  "action_type": "interact",
  "target": "<entity_id or soft_item_name>",
  "interaction_id": "<interaction_id>",
  "using": "iron_sword",
  "detail": "The player slashes at the spider with the iron sword.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

| Field            | Type           | Required | Description |
|------------------|----------------|----------|-------------|
| `target`         | string         | yes      | The entity ID or soft item name being interacted with. |
| `interaction_id` | string         | yes      | The specific interaction to perform. Generic interactions include `attack`. Module authors define additional ones (e.g., `recharge`). Picking up or giving items should use the `transfer` action instead. |
| `using`          | string\|null   | no       | An entity ID or soft item enabling the interaction (e.g., "iron_sword" for attack). |

**Engine validation:**
- `target` must exist: an entity present in the room, or a soft item present
  in the room or on a present entity.
- `interaction_id` must match a defined interaction on the target entity, the
  current room, or a generic interaction (e.g., `attack`).
- The interaction's `parameter_signature` (if defined) is validated: `target`
  must be of a type listed in `parameter_signature.target`, and `using` must
  be of a type listed in `parameter_signature.using`.
- All interaction `conditions` must be met.
- If the interaction has a `check` (roll), the engine resolves it and selects
  the `success` or `failure` result.
- On success, the engine applies the result (add_item, set_flag, etc.).
- If no matching interaction exists, the engine returns `success: false` with
  a reason. The LLM may then retry with a different action or fall back to
  `wait`.

---

#### `talk` -- Speak to an NPC

```json
{
  "action_type": "talk",
  "target": "korbar",
  "utterance": "Hey there, who are you and how did you get stuck in this bag?",
  "detail": "The player approaches the dwarf with an open, friendly demeanour, hands visible to show no threat.",
  "ends_dialogue": false,
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

| Field            | Type    | Required | Description |
|------------------|---------|----------|-------------|
| `target`         | string  | yes      | NPC entity ID to speak to. |
| `utterance`      | string  | no       | Verbatim spoken words the player's character says. May be absent if the player is describing speech indirectly or the input is purely non-verbal (e.g., nodding, gesturing). |
| `detail`         | string  | yes      | Non-verbal context: tone, body language, actions accompanying the speech. |
| `ends_dialogue`  | boolean | no       | If `true`, signals that the player intends to end the conversation. The engine will archive the conversation log to the NPC's `entity_notes` and clear `dialogue_state.active_npc`. |
| `dialogue_path`  | string  | no       | If the player is attempting a specific special dialogue path (e.g., flatter, intimidate, persuade, deliver specific information), set this to the path ID declared in the NPC's `dialogue_guidelines.dialogue_paths`. LLM Call 1 receives each path's `description` in `current_room.entities_visible[*].dialogue_paths` as `{path_id: description}` and should use that description to match player intent to the correct path ID. The engine resolves the path's condition, check, and results. Omit for freeform conversation. |

**Engine validation:**
- `target` must be an NPC entity present in the current room, with `state.alive` true.
- When a `talk` action succeeds, the engine activates or extends dialogue mode:
  sets `dialogue_state.active_npc`, appends the player's `utterance` (or a
  summary of the `detail` if no `utterance`) to `conversation_log`, and records
  any new topics proposed by LLM Call 1.
- If the `talk` targets a different NPC than the current `active_npc`, the
  engine archives the current conversation log and starts a new one.
- If `ends_dialogue` is `true`, engine clears dialogue mode after resolution.
- Soft-state patches (e.g., entity notes) are validated per the soft-state
  patch schema. Attitude changes are proposed by LLM Call 2, not via
  `proposed_soft_state_patches`.

---

#### `transfer` -- Give or take items

```json
{
  "action_type": "transfer",
  "target": "korbar",
  "given_items": ["rusty_key"],
  "taken_items": ["rock"],
  "detail": "The player hands the rusty key to Korbar and takes back the rock.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

| Field          | Type            | Required | Description |
|----------------|-----------------|----------|-------------|
| `target`       | string          | yes      | Entity ID (NPC or container) or room ID (for dropping items on the floor). |
| `given_items`  | string[]\|null  | no       | List of item entity IDs and/or soft item names the player is giving to the target. |
| `taken_items`  | string[]\|null  | no       | List of item entity IDs and/or soft item names the player is taking from the target. |

**Engine validation:**
- `target` must be an entity ID present in the room, or current room ID.
- Each item in `given_items` must be in the player's hard inventory
  (entity IDs) or soft inventory (soft item names).
- Each item in `taken_items` must be obtainable from the target: entity IDs 
  must be listed in the target entity's or room's available inventory;
  soft item names must appear in the target's `soft_items` or the room's 
  `soft_items`.
- On success, items are moved accordingly between inventories.
- If the target is a room, `given_items` are removed from the player's inventory
  and added to the room's available pool; `taken_items` are removed from the
  room's available pool and added to the player's inventory.
- At least one of `given_items` or `taken_items` should be non-empty.

---

#### `wait` -- Pass time / miscellaneous

```json
{
  "action_type": "wait",
  "detail": "The player pauses, taking stock of what they're carrying. Among their belongings: an iron sword, a rock, and a torn piece of canvas.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

The `wait` action advances the turn counter and serves as a catch-all for:
- Actions falling below plot significance threshold (e.g., examining a soft
  item, looking through inventory).
- Player introspection or self-examination.
- Genuinely waiting or doing nothing.

The `detail` field instructs LLM Call 2 on how to narrate the response (e.g.,
reporting inventory contents). No hard state changes occur beyond the turn
counter increment.

**Engine validation:**
- No additional validation beyond turn advancement.
- The engine may trigger time-based events (for future modules).
- Soft-state patches in `proposed_soft_state_patches` are validated as usual.

---

#### `ooc_discussion` -- Out-of-character conversation

```json
{
  "action_type": "ooc_discussion",
  "detail": "The player wants to clarify whether the spider is still visible in the room.",
  "follow_up": null,
  "proposed_soft_state_patches": []
}
```

Allows the player to speak to the GM out-of-character for clarifications,
rule questions, or meta-discussion.

**Engine behaviour:**
- The engine performs a no-op: no hard state changes. The turn counter is 
  **not** incremented.
- The player input is logged in `turn_history` for debugging but does not count
  toward the GMBriefing entry cap.
- The engine skips directly to LLM Call 2 with the `ooc_discussion` action
  and the player's `detail` as the narrative prompt.
- LLM Call 2 should respond in a GM voice, not an in-world narration voice.
- If in active dialogue mode, `ooc_discussion` does not increment the
  `stall_counter`.

---

### 2.2 Follow-up: Chained actions

Players often describe multi-step plans in a single input (e.g., "I pick up
the key and unlock the door"). The LLM is instructed to:

1. Identify the first (or next) discrete step in the chain.
2. Construct a `PlayerAction` for that step.
3. Place the remainder of the chain in the `follow_up` field as a 
   natural-language string describing what remains to be done.

```json
{
  "action_type": "transfer",
  "target": "bag_floor",
  "taken_items": ["rusty_key"],
  "detail": "The player picks up the rusty key from the floor.",
  "follow_up": "Unlock the padlock on the outside of the bag using the rusty key.",
  "proposed_soft_state_patches": []
}
```

After LLM Call 2 narrates the result of the current step, the system checks
whether to continue the chain:

- If the engine terminated the chain due to a validation failure or hard/soft
  state rejection, control returns to the player. The `chain_info` in the
  EngineResult will note the reason for cancellation and the `follow_up` that
  was discarded.
- If the chain is still viable, the system loops back to the Context Assembler
  (now with updated state) and feeds the `follow_up` text as the "player input"
  for the next step. LLM Call 2 is instructed to be terse during ongoing chain
  steps.
- The engine enforces a maximum chain length (a defined constant) to guard
  against infinite follow-up loops. If exceeded, the chain is terminated and
  control returns to the player.

---

### 2.3 Action validation summary

| Action            | target must be                                  | other constraints                          |
|-------------------|-------------------------------------------------|--------------------------------------------|
| `move`            | exit_id in current room                         | exit conditions met, not one-way blocked   |
| `examine`         | entity_id in current room, current room_id, or soft item name present in room/on visible entity | `using` item must be in inventory |
| `interact`        | entity_id or soft item present in room          | interaction_id must match defined interaction; `using` item must be present/in-inventory |
| `talk`            | npc entity_id in current room, alive            | `utterance` optional                       |
| `transfer`        | entity_id (NPC/container) in room, or room_id   | items in given/taken must exist in source  |
| `wait`            | null (no target)                                | none; advances turn counter                |
| `ooc_discussion`  | null (no target)                                | no-op; does not advance turn counter       |

---

## 3. SoftStatePatch -- LLM-proposed, engine-validated

The LLM may propose changes to soft state in its `PlayerAction` output. The
full format and validation rules are detailed in `soft-state.md`. In summary:

```json
{
  "entity_id": null,
  "field": "room_note",
  "target_id": "axe_handle_lower",
  "old_value": null,
  "new_value": "The webs here are partially cleared.",
  "reason": "Player hacked through the webs with the iron sword."
}
```

Supported fields: `room_note`, `entity_note`, `soft_inventory_add`,
`soft_inventory_remove`. (Attitude changes are proposed by LLM Call 2 via
`attitude_changes`, not by LLM Call 1.)

---

## 4. EngineResult -- Input to LLM Call 2

The engine produces this after resolving the PlayerAction. It contains
everything LLM Call 2 needs to narrate the outcome.

```json
{
  "success": true,
  "action_type": "move",
  "target": "exit_through_webs",

  "room_after": {
    "id": "bag_floor",
    "name": "Bag Floor",
    "description": "You are on the floor of the bag. Loose piles of giant rubbish surround you...",
    "soft_items": ["cork", "loose copper", "stale sandwich"],
    "entities_visible": [
      { "id": "korbar", "name": "Korbar the Dwarf", "type": "npc", "description": "A drunk dwarf in noisy platemail.", "state": { "alive": true }, "entity_notes": [] },
      { "id": "rubbish_pile", "name": "Piles of Rubbish", "type": "feature", "description": "Giant potion bottles, corks, sandwiches, copper pieces, lint.", "state": {}, "entity_notes": [], "soft_items": ["cork", "loose copper"] }
    ],
    "exits_available": [
      { "id": "exit_climb_up_handle_floor", "direction": "Climb up the axe handle", "target_room": "axe_handle_lower" }
    ],
    "interactions_available": [],
    "room_notes": []
  },

  "hard_state_changes": {
    "player_location": "bag_floor",
    "inventory_added": [],
    "inventory_removed": [],
    "flags_set": { "spider_fled": true },
    "flags_cleared": [],
    "room_state_changes": {
      "bag_floor": { "visited": true }
    },
    "entity_state_changes": {
      "spider": { "fled": true }
    }
  },

  "soft_state_patches_applied": [],
  "soft_state_patches_rejected": [],

  "rolls": [],

  "encounter_outcome": {
    "encounter_id": "spider_encounter",
    "outcome": "flee",
    "narrative_brief": "The player wounded the spider with their iron sword. It fled into the shadows."
  },

  "triggered_narration": [
    "You push through the sticky webs, hacking at them with the iron sword. The spider lunges — you slash it across its legs. It screeches and scuttles away into the shadows, never to threaten you again.",
    "You emerge onto the floor of the bag, surrounded by giant rubbish. A drunken dwarf in noisy platemail looks up at you with bleary eyes."
  ],

  "on_enter_events": [
    {
      "event_id": null,
      "narrative": null
    }
  ],

  "game_over": null,

  "dialogue_exited": null,

  "will_reveal_readiness": {
    "korbar": {
      "padlock_mechanism": { "conditions_met": true, "description": "How the exterior padlock can be opened from inside" },
      "secret_compartment": { "conditions_met": false, "description": "A hidden cache inside the axe head" }
    }
  },

  "revelations_applied": [],

  "npc_attitude_limits": {
    "korbar": { "min": -5, "max": 10, "step_per_turn": 3, "current": 2 }
  },

  "attitude_changes_applied": [],
  "attitude_changes_rejected": [],

  "chain_info": null,

  "warnings": [
    "Korbar is present but has not been introduced yet. You may narrate her presence."
  ]
}
```

### 4.1 EngineResult field descriptions

| Field                          | Description |
|--------------------------------|-------------|
| `success`                      | Whether the action was valid and resolved. `false` means the engine rejected the action. |
| `action_type`, `target`        | Echoed from PlayerAction for context. |
| `room_after`                   | The room after resolution: the new room if the player moved, otherwise the current room. Includes `soft_items`, `room_notes`, visible `entities_visible` (with their `soft_items` and `entity_notes`), available exits, and interactions. |
| `hard_state_changes`           | All applied changes to hard state: location, inventory changes, flag changes, room state changes, entity state changes. LLM Call 2 must not contradict these. |
| `soft_state_patches_applied`   | Soft-state patches the engine accepted. |
| `soft_state_patches_rejected`  | Soft-state patches the engine rejected, each with a `reason` string. LLM Call 2 must not narrate rejected changes. |
| `rolls`                        | Any probabilistic rolls or stat checks the engine resolved. For `roll` checks: `{ outcome, roll, threshold }`. For `stat_check` checks: `{ check_type, stat, dc, raw_roll, modifier, stat_modifier, total, margin, advantage, disadvantage }`. |
| `encounter_outcome`            | If an encounter triggered, its resolution. |
| `triggered_narration`          | Pre-written narrative blocks for specific events (e.g., spider fleeing, room entry). LLM Call 2 should incorporate or paraphrase these — they represent canonical prose for key moments. |
| `on_enter_events`              | Any on_enter events that fired when entering the new room. |
| `game_over`                    | `null` or `{"type": "win"|"lose", "trigger": "string", "narrative": "string"}`. |
| `dialogue_exited`              | `null` or `{"npc_id": "string", "exit_narrative": "string"}`. Present when dialogue mode ended this turn and the NPC's `on_dialogue_exit` fired. |
| `will_reveal_readiness`        | For each NPC with `will_reveal` entries, whether each topic's conditions are currently met and its description. LLM Call 2 uses this to know which topics can be revealed in dialogue and must not narrate a reveal for topics with `conditions_met: false`. |
| `npc_attitude_limits`          | For each NPC present in the room after resolution, the `attitude_limits` bounds (`min`, `max`, `step_per_turn`) and `current` attitude value. LLM Call 2 must not propose attitude changes that violate these bounds. |
| `revelations_applied`          | Topics that LLM Call 2 tagged as revealed in `knowledge_tags` and the engine post-validated (step 4.5). Each entry records the NPC ID, topic ID, and any side effects applied. |
| `attitude_changes_applied`     | Attitude changes proposed by LLM Call 2 that the engine post-validated and accepted (step 4.5). Each entry records the NPC ID, old value, new value, and reason. |
| `attitude_changes_rejected`    | Attitude changes proposed by LLM Call 2 that the engine rejected, each with a `reason` string. LLM Call 2 must not narrate the rejected change on future turns. |
| `chain_info`                   | `null` or an object with chain status: `{ "follow_up": "<discarded text>", "termination_reason": "..." }`. Present when a chained action was terminated by the engine (validation failure, hard-state or soft-state rejection). Also present when a chain is ongoing, indicating the next follow-up step. |
| `warnings`                     | Engine hints to LLM Call 2 about narrative constraints (e.g., don't reveal secrets, respect attitude gating, NPC dialogue limits). |

---

## 5. LLM Call 2: Prose Narration

LLM Call 2 receives:
- The **adventure setting** (1-2 sentences from the module corpus).
- The **verbatim chat log** (raw player–GM exchange, recent messages) for
  conversational continuity.
- The **GMBriefing** (same as LLM Call 1 received) for current world context.
- The **PlayerAction** from LLM Call 1.
- The **EngineResult** — the authoritative outcome.

### Constraints on LLM Call 2 output

1. **Do not contradict the EngineResult.** If the engine says the spider fled,
   do not narrate it attacking. If `success: false`, narrate the failure or
   impossibility naturally.

2. **Do not alter hard state.** Narration cannot add items to inventory, change
   the player's room, set flags, or kill entities. Those are engine domain.

3. **Incorporate `triggered_narration` blocks** where provided. These are
   canonical descriptions of key events and should be used verbatim or closely
   paraphrased. The LLM's job is to weave them into natural conversation with
   the player's action and the broader scene.

4. **Do not reveal hidden information.** If a secret exit is hidden, do not
   mention it. If an NPC knows something but hasn't shared it, the LLM may
   improvise their dialogue but must respect the `dialogue_guidelines.cannot`
   constraints and `will_reveal_readiness` (only tag topics with
   `conditions_met: true` as revealed). The engine provides these constraints
   in the `warnings` field.

5. **Provide NPC response for dialogue extraction.** When a `talk` action was
   resolved, the narration must include the NPC's spoken response in a form
   the engine can extract (e.g., marked with a structured `npc_response` field).

6. **Respect game-over state.** If `game_over` is non-null, narrate the ending
   and stop. No further player input should be solicited.

7. **The raw chat log may contain hallucinations.** The LLM is instructed that
   prior narration (including its own) is non-canonical unless confirmed by the
   EngineResult. If a contradiction is detected, prefer the engine's version.

8. **Chained action handling.** If the EngineResult's `chain_info` indicates an
   ongoing chain, the LLM should be terse — the system will proceed directly
   back to the next follow-up step without player interaction. Full narration
   is reserved for the final step or when the chain is interrupted.

9. **Propose `knowledge_tags` when relevant** (non-`ooc_discussion` actions
   only). When an NPC reveals a gated topic during dialogue, the LLM includes
   a `knowledge_tags` block tagging which `will_reveal` topic IDs were revealed.
   The engine post-validates these against the NPC's corpus `will_reveal`
   conditions and applies any side effects (`set_flag`, `set_entity_state`).
   Only tag topics whose conditions are met in the `will_reveal_readiness` hint
   provided in the EngineResult. Tagging a topic with unmet conditions has no
   effect (the engine rejects it). If no revelations occur, `knowledge_tags`
   may be omitted or empty.

10. **Propose `attitude_changes` when relevant** (non-`ooc_discussion` actions
    only). After narrating the turn's events, consider which NPCs' dispositions
    shifted and propose `attitude_changes` accordingly. Never contradict the
    `npc_attitude_limits` listed in the EngineResult.

#### `attitude_changes` output format

```json
{
  "attitude_changes": {
    "<npc_entity_id>": {
      "old_value": <integer>,
      "new_value": <integer>,
      "reason": "string — narrative justification"
    }
  }
}
```

| Field        | Type    | Description |
|--------------|---------|-------------|
| `old_value`  | integer | Expected current attitude value (for validation). |
| `new_value`  | integer | Proposed new attitude. Must be within the NPC's `attitude_limits.[min, max]` and the delta must not exceed `step_per_turn`. |
| `reason`     | string  | Narrative justification. Must be non-empty. |

### Chat History: Structured vs. Verbatim

LLM Call 1 receives a **structured, non-verbatim** turn history — distilled
summaries vetted by the engine — to prevent the ruling LLM from reinforcing
hallucinations. The exception is the `dialogue_context` block in GMBriefing,
which injects scoped, verbatim dialogue exchanges when the player is in active
conversation with an NPC.

LLM Call 2 receives the **verbatim chat log** for conversational flavour, but
is explicitly instructed to defer to the EngineResult when contradictions arise.

---

## 6. Error Handling

### 6.1 LLM produces invalid action

If the LLM outputs an action the engine cannot parse (unknown `action_type`,
missing required fields, invalid JSON), the engine returns:

```json
{
  "success": false,
  "error": "invalid_action",
  "message": "Unknown action type 'cast_spell'. Supported types: move, examine, interact, talk, transfer, wait, ooc_discussion.",
  "player_input_echo": "<original player input>"
}
```

The system re-invokes LLM Call 1 once with the error message appended to the
context. If the retry also fails, the system falls back to a generic "You can't
do that" narration via LLM Call 2.

### 6.2 LLM proposes impossible action

If the action is well-formed but invalid (e.g., targeting an NPC not in the
room, using an item not in inventory), the engine returns:

```json
{
  "success": false,
  "error": "invalid_target",
  "message": "Entity 'korbar' is not present in room 'axe_handle_upper'.",
  "player_input_echo": "<original player input>"
}
```

LLM Call 2 should narrate the failure naturally (e.g., "You call out for
Korbar, but there's no response from the darkness below.").

### 6.3 LLM proposes contradictory soft state

If a soft-state patch is rejected by the engine, it appears in
`soft_state_patches_rejected` with a reason. LLM Call 2 must not narrate the
rejected change. If the rejection invalidates the LLM's intended narration
direction, the LLM should adapt.

---

## 7. Turn Lifecycle Summary

```
1. Player enters input
2. Context Assembler builds GMBriefing
3. LLM Call 1 (Ruling) produces PlayerAction + SoftStatePatch[]
4. Engine validates action
   +-- Valid:   resolve, apply hard state, validate soft patches
   +-- Invalid: return error (goto 3 with retry, or goto 6 with fail)
5. Engine adds entry to turn_history (ooc_discussion entries are logged
   but do not count toward the GMBriefing cap)
6. LLM Call 2 (Prose) narrates outcome
7. If LLM Call 2 produced knowledge_tags or attitude_changes:
   engine post-validates and produces corrected EngineResult (step 4.5)
8. If chained action is ongoing and not terminated by engine: goto 2
   Else: output text to player, save game state
```

---

## 8. Extensibility Notes

- **New action types**: Add to Section 2.1 with validation rules. Register in
  the engine's action parser and update the LLM Call 1 prompt instructions.
- **New soft state fields**: Add to `soft-state.md` Section SoftStatePatch.
  The engine must validate the field exists and values are in range.
- **New entity types**: Add to the `type` enum in the corpus schema. Update
  the engine's entity resolver.
- **Combat phase**: The current `interact`-based attack uses kill-or-be-killed
  resolution. A future combat phase will support iterative rounds, HP tracking,
  and damage rolls. The `attack` interaction ID will route to the new combat
  engine.
- **Semantic search / RAG**: Once adventures grow beyond the five-room scale,
  deterministic ID lookups can be augmented with vector embeddings for entity
  descriptions and player queries.
