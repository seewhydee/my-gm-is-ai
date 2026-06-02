# Action Schema

This defines the structured data formats that flow between the three core-loop
components: Context Assembler → LLM Call 1 (Ruling) → Engine Resolution → LLM
Call 2 (Prose).

## Core Loop Data Flow

```
Player Input ──────────────────────────────────────────────────────────────────┐
                                                                                │
┌─────────────────────────────────┐                                             │
│  Context Assembler              │                                             │
│  Produces: GMBriefing           │                                             │
└─────────────────────────────────┘                                             │
         │                                                                      │
         ▼                                                                      │
┌─────────────────────────────────┐                                             │
│  LLM Call 1: Ruling            │                                             │
│  Input:  GMBriefing            │                                             │
│  Output: PlayerAction          │  (structured JSON)                          │
│     + SoftStatePatch[]         │                                             │
└─────────────────────────────────┘                                             │
         │                                                                      │
         ▼                                                                      │
┌─────────────────────────────────┐                                             │
│  Engine Resolution              │                                             │
│  Input:  PlayerAction           │                                             │
│  Reads:  ModuleCorpus           │                                             │
│  Reads:  HardGameState          │                                             │
│  Reads:  SoftGameState          │                                             │
│  Writes: HardGameState          │                                             │
│  Validates & Applies:           │                                             │
│     SoftStatePatch[]            │                                             │
│  Produces: EngineResult         │                                             │
│     + TurnLogEntry              │                                             │
└─────────────────────────────────┘                                             │
         │                                                                      │
         ▼                                                                      │
┌─────────────────────────────────┐                                             │
│  LLM Call 2: Prose              │                                             │
│  Input:  ChatLog                │                                             │
│       + GMBriefing              │                                             │
│       + EngineResult            │                                             │
│  Output: Natural-language       │                                             │
│       narration (text)          │                                             │
└─────────────────────────────────┘                                             │
         │                                                                      │
         ▼                                                                      │
     Player (text output) ──────────────────────────────────────────────────────┘
```

---

## 1. GMBriefing — Input to LLM Call 1

Assembled by the Context Assembler from Module Corpus + Hard State + Soft State.
This is what the LLM sees when making a ruling.

```json
{
  "adventure_title": "You're Trapped in a Bag of Holding!",
  "turn": 3,

  "current_room": {
    "id": "axe_handle_lower",
    "name": "Axe Handle (Lower)",
    "description": "You are on the lower section of the axe handle. The webs here are denser, blocking the path downward unless you push through. If you look carefully, you see the spider — huge and hungry for blood — lurking in the webs. Below, many irregularly shaped objects are coming into view. It looks like you could drop down safely. There is some muffled clanking from the shadows below.",
    "entities_visible": [
      { "id": "spider", "name": "Huge Spider", "description": "A huge, hungry spider lurking in the dense webs.", "state": "alive, hostile" },
      { "id": "webs_dense", "name": "Dense Webs", "description": "Thick webs blocking the downward path." }
    ],
    "exits_available": [
      { "id": "exit_up_handle_lower", "direction": "Walk up the axe handle", "target_room": "axe_handle_upper" },
      { "id": "exit_through_webs", "direction": "Push through the dense webs downward", "target_room": "bag_floor" },
      { "id": "exit_drop_lower", "direction": "Drop safely down to the floor", "target_room": "bag_floor" }
    ],
    "interactions_available": []
  },

  "player_state": {
    "location": "axe_handle_lower",
    "inventory": ["toenail_sword"],
    "flags": {
      "injured": false,
      "stunned": false
    },
    "summary": "You are uninjured. You are carrying a toenail clipping sword."
  },

  "npc_attitudes": {
    "korbar": "neutral"
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

  "win_condition_hint": "The padlock on the outside of the bag is locked. You will need to find a way to unlock it.",

  "player_input": "I want to push through the webs."
}
```

### GMBriefing assembly rules

1. **Current room** is fetched by ID from Module Corpus. Only entities with
   `state.alive == true` (or equivalent) are included in `entities_visible`.
2. **Exits** whose conditions are met are included. Hidden exits (e.g., the
   secret compartment) are omitted unless their reveal flag is set.
3. **Recent history** is drawn from Soft Game State `turn_history` — last 5
   entries, summarized. Raw chat log is NOT included here (see Section 5).
4. **Player state summary** is a natural-language condensation of inventory
   and flags, to reduce LLM parsing burden.
5. **Win condition hint** is included only if the player has discovered clues.

---

## 2. PlayerAction — Output of LLM Call 1

The LLM must output a single structured action. This is the *ruling* — the LLM
interprets the player's intent and proposes what happens, which the engine then
validates and resolves.

```json
{
  "action_type": "move",
  "target": "exit_through_webs",
  "detail": "The player steels themselves and pushes through the sticky webs, trying to reach the bag floor.",
  "proposed_soft_state_patches": []
}
```

### 2.1 Supported action types

#### `move` — Travel between rooms

The LLM selects the exit the player is using. The engine validates the exit
exists, is available from the current room, and all conditions are met.

```json
{
  "action_type": "move",
  "target": "<exit_id>",
  "detail": "Natural-language description of how the player moves.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `target` must be a valid exit_id in the current room.
- All `conditions` on the exit must be satisfied.
- If the exit has `on_traverse`, the engine applies the specified effects
  (set flags, trigger encounters, etc.).
- If the exit is one-way, reverse traversal is rejected.

#### `examine` — Look at something

```json
{
  "action_type": "examine",
  "target": "<entity_id or feature_id>",
  "detail": "What the player is looking at or trying to inspect.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `target` must exist in the current room's `entities_present` list, or be the
  current room itself (for examining the room).
- Engine returns the entity's description and any `examine`-specific narrative
  from the module corpus.
- Does NOT trigger interactions — those require the `interact` action type.

#### `interact` — Use a defined interaction

```json
{
  "action_type": "interact",
  "target": "<interaction_id>",
  "detail": "How the player attempts the interaction.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `target` must be a valid `interaction.id` defined in the current room.
- All conditions on the interaction must be met.
- If the interaction has a `check` (roll), the engine resolves it and returns
  success or failure.
- On success, the engine applies the result (add_item, set_flag, etc.).
- Interactions are one-to-one: the LLM cannot invent new interactions. For
  freeform actions not covered by a defined interaction, the engine returns a
  generic failure and the LLM narrates the impossibility.

#### `talk` — Speak to an NPC

```json
{
  "action_type": "talk",
  "target": "<npc_entity_id>",
  "detail": "What the player says to the NPC, in natural language.",
  "utterance": "Hey there, who are you and how did you get stuck in this bag?",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `target` must be an NPC entity present in the current room, and its `state.alive`
  must be true.
- The engine returns the NPC's `dialogue_guidelines` from the module corpus.
- The engine does NOT validate dialogue content — dialogue is freeform and
  the LLM improvises based on the guidelines.
- If the LLM proposes a soft-state patch (e.g., attitude change), the engine
  validates it per the soft-state patch schema (Section 4).
- Hard knowledge constraints are checked: e.g., if `told_secret` flag is false
  and Korbar's guidelines say she only reveals at `friendly` attitude, the
  engine will reject any attempt by LLM Call 2 to have Korbar reveal the secret
  at `neutral` attitude. (This is enforced at EngineResult time, not at
  PlayerAction time — the LLM may *propose* narration that implies a secret
  reveal; the engine strips or flags it before it reaches the player.)

#### `use` — Use an item on a target

```json
{
  "action_type": "use",
  "item": "<inventory_item_id>",
  "target": "<entity_id or feature_id>",
  "detail": "How the player uses the item on the target.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `item` must be in the player's inventory.
- `target` must be a valid entity in the current room (or a special reachable
  entity, e.g., the exterior padlock).
- The engine checks for a matching item–target combination in the module
  mechanics. If found, the defined outcome applies.
- If no defined interaction exists, the engine returns a generic "nothing
  happens" and the LLM nar narrates the anticlimax.

#### `search` — Search the current room

```json
{
  "action_type": "search",
  "target": null,
  "detail": "The player searches the room thoroughly.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- The engine enumerates all `interactions` in the current room that have
  a `check.type == "roll"` and `repeatable == true` or not yet attempted.
- For each, the engine rolls and reports results.
- This is a convenience action that bundles multiple search-type interactions.
  The LLM can also use `interact` with a specific search interaction ID for
  targeted searching.

#### `attack` — Fight an entity

```json
{
  "action_type": "attack",
  "target": "<entity_id>",
  "detail": "How the player attacks.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- `target` must be an entity with a defined combat behavior in the module
  corpus.
- The engine resolves combat per the entity's `behavior.encounter_rules`.
- In phase 1 (no full combat system), combat is resolved as a special-case
  encounter with flag-based outcomes. The engine checks flags (armed, injured)
  and applies the corresponding outcome.
- Future phases will replace this with iterative combat rounds.

#### `wait` — Do nothing / pass time

```json
{
  "action_type": "wait",
  "detail": "The player waits to see if anything happens.",
  "proposed_soft_state_patches": []
}
```

**Engine validation:**
- No state changes besides advancing the turn counter.
- The engine may trigger time-based events (none in the test adventure).

### 2.2 Action validation summary

| Action    | target must be                            | other constraints                       |
|-----------|-------------------------------------------|-----------------------------------------|
| `move`    | exit_id in current room                   | exit conditions met                     |
| `examine` | entity_id in current room (or room_id)    | none                                    |
| `interact`| interaction_id in current room            | interaction conditions met              |
| `talk`    | npc entity_id in current room, alive      | none (dialogue is freeform)            |
| `use`     | item in inventory + target in room        | matching mechanic may exist             |
| `search`  | null                                      | triggers relevant search interactions   |
| `attack`  | entity_id in current room, has combat     | combat encounter rules applied          |
| `wait`    | null                                      | none                                    |

---

## 3. EngineResult — Input to LLM Call 2

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
    "entities_visible": [
      { "id": "korbar", "name": "Korbar the Dwarf", "brief": "A drunk dwarf in noisy platemail." },
      { "id": "rubbish_pile", "name": "Piles of Rubbish", "brief": "Giant potion bottles, corks, sandwiches, copper pieces, lint." }
    ],
    "exits_available": [
      { "id": "exit_climb_up_handle_floor", "direction": "Climb up the axe handle", "target_room": "axe_handle_lower" }
    ]
  },

  "hard_state_changes": {
    "player_location": "bag_floor",
    "inventory_added": [],
    "inventory_removed": [],
    "flags_set": { "spider_fled": true },
    "flags_cleared": [],
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
    "narrative_brief": "The player wounded the spider with their toenail sword. It fled into the shadows."
  },

  "triggered_narration": [
    "You push through the sticky webs, hacking at them with the toenail sword. The spider lunges — you slash it across its legs. It screeches and scuttles away into the shadows, never to threaten you again.",
    "You emerge onto the floor of the bag, surrounded by giant rubbish. A drunken dwarf in noisy platemail looks up at you with bleary eyes."
  ],

  "on_enter_events": [
    {
      "event_id": null,
      "narrative": null
    }
  ],

  "game_over": null,

  "warnings": [
    "note: Korbar is present but has not been introduced yet. You may narrate her presence."
  ]
}
```

### 3.1 EngineResult field descriptions

| Field                      | Description                                                                 |
|----------------------------|-----------------------------------------------------------------------------|
| `success`                  | Whether the action was valid and resolved. `false` means the engine rejected the action. |
| `action_type`, `target`    | Echoed back from PlayerAction for context.                                  |
| `room_after`               | If the player changed rooms, the new room data. Otherwise the current room. |
| `hard_state_changes`       | All applied changes to hard state. LLM Call 2 uses this for narration.      |
| `soft_state_patches_applied` | Soft-state patches the engine accepted (see Section 4).                   |
| `soft_state_patches_rejected`| Soft-state patches the engine rejected, with reasons.                     |
| `rolls`                    | Any probabilistic rolls the engine made, with results.                      |
| `encounter_outcome`        | If an encounter triggered, its resolution.                                  |
| `triggered_narration`      | Pre-written narrative blocks the engine supplies for specific events (e.g., spider fleeing). LLM Call 2 should incorporate or paraphrase these. |
| `on_enter_events`          | Any events that fired on entering the new room (e.g., fly warning).         |
| `game_over`                | `null` or `{"type": "win"|"loss", "narrative": "..."}`.                     |
| `warnings`                 | Engine hints to the LLM about narrative constraints (e.g., don't have Korbar reveal secrets she hasn't been asked about). |

---

## 4. SoftStatePatch — LLM-proposed, engine-validated

The LLM may propose changes to soft state in its `PlayerAction` output. The
engine validates each patch against a fixed schema and either applies or
rejects it.

### 4.1 Patch format

```json
{
  "entity_id": "korbar",
  "field": "attitude",
  "old_value": "neutral",
  "new_value": "friendly",
  "reason": "The player shared their food with Korbar and listened sympathetically to her story about being abandoned by her party."
}
```

### 4.2 Validation rules

| Rule                        | Description                                                                 |
|-----------------------------|-----------------------------------------------------------------------------|
| `entity_id` must exist      | The entity must be defined in the module corpus.                            |
| `field` must be registered  | The entity must have the field declared in its `state_fields` (hard state) or in the soft state schema. |
| Attitude transitions ≤ 1 step | Attitude can only move one step per turn (hostile → neutral, neutral → friendly). Multi-step jumps are rejected unless the reason describes extraordinary circumstances AND the engine is configured to allow it. |
| Cannot contradict hard state | If hard state says `korbar.alive == false`, a patch to change her attitude is rejected. |
| `reason` must be non-empty  | The LLM must justify the change with a narrative reason.                    |

### 4.3 Supported soft state fields

| Field      | Type   | Allowed values              | Notes                                    |
|------------|--------|-----------------------------|------------------------------------------|
| `attitude` | enum   | `hostile`, `neutral`, `friendly` | One-step transitions only. Applies to NPCs. |
| `environmental_note` | string | Any non-contradictory text | Appended to `environmental_notes[]`. Used for narrative continuity (e.g., "the webs are now partially cleared"). |

---

## 5. LLM Call 2: Prose Narration Constraints

LLM Call 2 receives:
- **Raw chat log** (verbatim player–GM exchange, last N messages) — for
  conversational continuity.
- **GMBriefing** (same as LLM Call 1 received) — for current state context.
- **EngineResult** — the authoritative outcome of the player's action.

### Constraints on LLM Call 2 output

1. **Do not contradict the EngineResult.** If the engine says the spider fled,
   do not narrate the spider attacking. If the engine says `success: false`,
   narrate the action failing or being impossible.

2. **Do not alter hard state.** The narration cannot add items to inventory,
   change room, set flags, or kill entities. Those are engine domain.

3. **Incorporate `triggered_narration` blocks** where provided. These are
   canonical descriptions of key events and should be used verbatim or closely
   paraphrased. The LLM's job is to weave them into natural prose with the
   player's action and the broader scene.

4. **Do not reveal hidden information.** If a secret exit is hidden, do not
   mention it. If an NPC knows something but hasn't shared it, the LLM may
   improvise their dialogue but must respect the `dialogue_guidelines.cannot`
   constraints from the module corpus. The engine provides these guidelines
   in the EngineResult `warnings` field.

5. **Respect game-over state.** If `game_over` is non-null, narrate the ending
   and stop. No further player input should be solicited.

6. **The raw chat log may contain hallucinations.** The LLM is instructed that
   prior narration (including its own) is non-canonical unless confirmed by the
   EngineResult. If a contradiction is detected, prefer the engine's version.

---

## 6. Error Handling

### 6.1 LLM produces invalid action

If the LLM outputs an action the engine cannot parse (unknown `action_type`,
missing required fields, invalid JSON), the engine returns:

```json
{
  "success": false,
  "error": "invalid_action",
  "message": "Unknown action type 'cast_spell'. Supported types: move, examine, interact, talk, use, search, attack, wait.",
  "player_input_echo": "<original player input>"
}
```

The system should then re-invoke LLM Call 1 with the error message appended to
the context, giving it a chance to correct. Maximum 1 retry before falling back
to a generic "You can't do that" narration.

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
`soft_state_patches_rejected` with a reason. LLM Call 2 should NOT narrate the
rejected change. If the rejection invalidates the LLM's intended narration
direction, the LLM should adapt.

---

## 7. Turn Lifecycle Summary

```
1. Player enters input ──────────────────────────────────────────────┐
2. Context Assembler builds GMBriefing                                │
3. LLM Call 1 (Ruling) produces PlayerAction + SoftStatePatch[]       │
4. Engine validates action                                            │
   ├── Valid:   resolve, apply hard state, validate soft patches      │
   └── Invalid: return error (goto 3 with retry, or goto 6 with fail) │
5. Engine adds turn to turn_history                                   │
6. LLM Call 2 (Prose) narrates outcome                                │
7. Output text to player ─────────────────────────────────────────────┘
```

## 8. Extensibility Notes

- **New action types**: Add to Section 2.1 with validation rules. Register in
  the engine's action parser.
- **New soft state fields**: Add to Section 4.3. The engine must validate the
  field exists and the value is in range.
- **New encounter types**: Add to the entity's `behavior` block. The engine
  dispatches based on `encounter_id`.
- **Combat phase**: The `attack` action will be revised to support iterative
  rounds, HP tracking, and damage rolls. The current flag-based resolution is
  a phase-1 placeholder for the test adventure only.
