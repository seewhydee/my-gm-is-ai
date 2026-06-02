# Soft Game State Schema

Soft game state stores fuzzier, narrative-oriented information that the LLM may
propose changes to. Unlike hard state, which is the engine's exclusive domain,
soft state acts as a structured memory buffer between the LLM and the engine:

- The LLM may propose **SoftStatePatch** entries in its `PlayerAction` output.
- The engine validates each patch against a fixed schema and either applies or
  rejects it.
- Applied soft state feeds back into future GMBriefings via the Context
  Assembler.

This split prevents the LLM from confabulating hard mechanical changes (inventory,
room transitions, flag toggles) while still allowing it to maintain narrative
continuity (NPC moods, environmental details, conversation memory).

## Top-Level Structure

```json
{
  "soft_inventory":    ["string", ...],
  "room_notes":        { "<room_id>": ["string", ...] },
  "entity_notes":      { "<entity_id>": ["string", ...] },
  "npc_attitudes":     { "<npc_entity_id>": <integer> },
  "turn_history":      [ { /* turn log entry */ } ],
  "dialogue_state":    { /* active NPC conversation state */ }
}
```

---

## `soft_inventory` — Generic carried items

```json
["rock", "loose stone", "dusty rag"]
```

An array of soft item names the player is carrying. These items come from
room or entity `soft_items` lists in the module corpus. They are identified
by their general name only — no unique IDs. They can be:

- Used in `interact` actions (as target or `using` field)
- Transferred via the `transfer` action
- Referenced in LLM narration

### Validation rules

1. Adding a soft item: the engine checks that the item name appears in the
   current room's `soft_items` or a present entity's `soft_items`.
2. Removing a soft item: the engine removes the first occurrence from the array.
3. Duplicate entries are allowed (e.g., multiple "rock" entries).
4. When a soft item is consumed or destroyed, the engine removes it.

---

## `room_notes` — Per-room narrative state

```json
{
  "axe_handle_lower": [
    "The webs here are partially cleared from the spider's flight.",
    "A faint trail of ichor leads downward."
  ],
  "bag_floor": []
}
```

Freeform strings describing non-plot-relevant changes to rooms (e.g., cleared
webs, rearranged debris, campfire remains). The Context Assembler includes the
most recent notes (up to 5 per room) in the GMBriefing room description.

### Patch format

```json
{
  "entity_id": null,
  "field": "room_note",
  "target_id": "axe_handle_lower",
  "old_value": null,
  "new_value": "The webs here are partially cleared.",
  "reason": "Player hacked through the webs with the toenail sword."
}
```

### Validation rules

1. `target_id` must be a valid room ID in the module corpus.
2. `new_value` must be a non-empty string.
3. The note must not contradict any hard state flag or entity state (e.g., the
   engine rejects a note saying "the spider is dead" if
   `entity_states.spider.alive == true`).
4. No duplicate detection — identical notes may accumulate; the Context
   Assembler can deduplicate at briefing time.

---

## `entity_notes` — Per-entity narrative state

```json
{
  "spider": [
    "The spider's left legs are now covered in ichor from the wound."
  ],
  "korbar": [
    "[Turn 4-6] Conversation summary: player asked about Korbar's origin and party. Korbar revealed she was abandoned by her adventuring company three years ago. Topics: origin, abandonment."
  ]
}
```

Freeform strings describing non-plot-relevant changes to entities (e.g., door
marked with chalk, scratch marks on a table). When dialogue mode exits, the
conversation summary is appended here as an `entity_note` on the NPC.

### Patch format

```json
{
  "entity_id": "spider",
  "field": "entity_note",
  "target_id": null,
  "old_value": null,
  "new_value": "The spider's left legs are covered in ichor.",
  "reason": "Player wounded the spider with the toenail sword."
}
```

### Validation rules

1. `entity_id` must be a valid entity ID in the module corpus.
2. `new_value` must be a non-empty string.
3. The note must not contradict hard state (same rules as room notes).
4. Dialogue archival summaries appended by the engine are exempt from the
   `reason` length check (the reason is the engine's own archival trigger).

---

## `npc_attitudes` — NPC disposition tracking

```json
{
  "korbar": 2,
  "angry_troll": -3
}
```

Tracks NPC disposition as an integer. Positive values indicate friendly
disposition; negative values indicate hostility. Zero (0) is neutral.

### Attitude semantics

| Range      | Typical NPC behaviour |
|------------|-----------------------|
| < 0        | Hostile / antagonistic. May attack, obstruct, or refuse cooperation. |
| 0          | Neutral. Default starting attitude. Indifferent or cautious. |
| 1–3        | Mildly friendly. Willing to talk, may help with small requests. |
| 4+         | Very friendly. Offers help, reveals secrets, becomes an ally. |

### Transition rules (enforced by engine)

1. Attitude patches are validated against the NPC's `attitude_limits` in the
   corpus (`min`, `max`, `step_per_turn`). The absolute change from `old_value`
   to `new_value` must not exceed `step_per_turn`. The `new_value` must be within
   `[min, max]`.
2. Attitude changes must be accompanied by a **non-empty reason** in the
   SoftStatePatch.
3. If an NPC's hard state says `alive == false`, all attitude patches for that
   NPC are rejected.
4. The engine initialises each NPC's attitude from the corpus
   `dialogue_guidelines.attitude_limits.initial` (default 0) if no explicit value
   is provided in the soft state startup file.

### Relationship to `dialogue_guidelines`

The module corpus may gate certain dialogue topics behind attitude thresholds
via the `will_reveal` block. The engine evaluates the `conditions` on each
`will_reveal` entry (e.g., `attitude:korbar >= 2`) against the current game
state. If the LLM narrates a reveal that the conditions do not permit, the
engine flags it in `warnings`.

---

## `turn_history` — Structured turn log

```json
[
  {
    "turn": 3,
    "player_input": "I push through the webs.",
    "ruled_action": {
      "action_type": "move",
      "target": "exit_through_webs",
      "detail": "The player steels themselves and pushes through the sticky webs."
    },
    "engine_result_summary": "Player pushed through webs. Spider attacked. Player wounded it with toenail sword. Spider fled. Arrived at Bag Floor. Korbar the Dwarf is present.",
    "flags_changed": ["spider_fled"],
    "location_after": "bag_floor"
  }
]
```

### Entry fields

| Field                   | Type     | Description |
|-------------------------|----------|-------------|
| `turn`                  | number   | Turn number at the time of this action. |
| `player_input`          | string   | Verbatim player input for this turn. |
| `ruled_action`          | object   | The validated `PlayerAction` (as resolved by engine, not as originally proposed). |
| `engine_result_summary` | string   | Condensed summary of what happened — key outcomes only. Written by the engine. |
| `flags_changed`         | string[] | Names of hard-state flags that were set or cleared this turn. |
| `location_after`        | string   | Room ID the player was in after resolution. |

### Size management

1. The engine appends one entry per completed turn (not for `ooc_discussion`).
2. The Context Assembler includes the last **5 entries** in GMBriefing
   (`recent_history`). This cap prevents context bloat.
3. The full history is retained in soft state for potential future use (save
   files, debugging, post-game analysis).

### Relationship to raw chat log

`turn_history` is a **structured, canonical** summary of what happened. It is
used by LLM Call 1 (Ruling). LLM Call 2 (Prose) also receives the raw verbatim
chat log for conversational flavour, but is instructed to trust the structured
history over any hallucinations in the chat log.

---

## `dialogue_state` — Active NPC conversation tracking

When the player is in conversation with an NPC, `dialogue_state` tracks the
ongoing exchange. It gates whether the Context Assembler injects a scoped,
verbatim `dialogue_context` block into the GMBriefing for LLM Call 1.

```json
{
  "active_npc": "korbar",
  "conversation_log": [
    {
      "turn": 4,
      "speaker": "player",
      "text": "Who are you, and how did you get stuck in this bag?"
    },
    {
      "turn": 4,
      "speaker": "korbar",
      "text": "Arr, name's Korbar. Me party left me here three years ago — said they'd be back. Liars, every one of 'em."
    },
    {
      "turn": 5,
      "speaker": "player",
      "text": "Three years? That's awful. Tell me more about this party of yours."
    }
  ],
  "topics_discussed": ["origin", "abandonment"],
  "entered_turn": 4,
  "stall_counter": 0
}
```

### Fields

| Field              | Type            | Description |
|--------------------|-----------------|-------------|
| `active_npc`       | string\|null    | Entity ID of the NPC the player is speaking to. `null` means no active dialogue. |
| `conversation_log` | array           | Verbatim dialogue exchanges. Capped at **10** entries (FIFO eviction). Each entry records the turn number, speaker identifier (either `"player"` or the NPC's `entity_id`), and the verbatim text exchanged. |
| `topics_discussed` | string[]        | Named topics that have come up in conversation. LLM Call 1 may propose new topics; the engine deduplicates and stores them. Used by the Context Assembler to inform the ruling LLM what has already been covered. |
| `entered_turn`     | number          | The turn number when dialogue mode was activated. Used by the engine for stall detection. |
| `stall_counter`    | number          | Tracks consecutive non-`talk` turns while in dialogue mode. Reset to 0 on each `talk` action. If it reaches 3, the engine auto-clears dialogue mode. |

### Lifecycle rules

| Trigger                                  | Engine action |
|------------------------------------------|---------------|
| `talk` action succeeds (no active dialogue) | Set `active_npc`, init `conversation_log` with player utterance, set `entered_turn`, reset `stall_counter`. |
| `talk` action to the same NPC            | Append player utterance to `conversation_log`. After LLM Call 2 runs, extract and append the NPC response. Reset `stall_counter` to 0. |
| `talk` action to a different NPC         | Archive current `conversation_log` as a summary in the previous NPC's `entity_notes`, switch `active_npc`, start fresh. |
| Any non-`talk` action while in dialogue  | Increment `stall_counter`. If `stall_counter >= 3`, archive conversation, clear dialogue state. |
| `move` action (player leaves room)       | Archive conversation summary to NPC's `entity_notes`, clear dialogue state. |
| NPC dies or flees                        | Archive conversation summary, clear dialogue state. Reject future `talk` to that NPC. |
| `talk` with `ends_dialogue: true`        | Archive conversation summary to NPC's `entity_notes`, clear dialogue state. |
| `ooc_discussion` while in dialogue       | Does not increment `stall_counter`; does not affect dialogue state. |

### NPC response extraction

LLM Call 2 generates the full prose narration including the NPC's spoken response.
After Call 2 completes, the engine extracts the NPC's response from the output
and appends it to `conversation_log`. The extraction can be heuristic (e.g.,
text within quotes attributed to the NPC) or the LLM may include a structured
`npc_response` field alongside its prose to make extraction deterministic.

### Relationship to GMBriefing

When `active_npc != null`, the Context Assembler includes a `dialogue_context`
block in the GMBriefing with the last 5 entries from `conversation_log`, the
NPC's `dialogue_guidelines`, current attitude, and `topics_discussed`. This
gives LLM Call 1 enough conversational awareness to parse player inputs that
mix action narration with in-character speech, without exposing the full
verbatim chat log.

If `active_npc` is null, `dialogue_context` is omitted from the GMBriefing.

### Archival

When dialogue mode exits, the full `conversation_log` is summarised and appended
as an `entity_note` on the NPC:

```
"[Turn 4-6] Conversation with Korbar: player asked about her origin and
party; Korbar revealed she was abandoned by her adventuring company three
years ago. Topics: origin, abandonment."
```

This preserves the narrative for future GMBriefings without retaining the
verbatim exchange indefinitely in the active dialogue state.

---

## SoftStatePatch reference

The general soft-state patch format that the LLM outputs in
`PlayerAction.proposed_soft_state_patches`:

```json
{
  "entity_id": "korbar",
  "field": "attitude",
  "target_id": null,
  "old_value": 0,
  "new_value": 2,
  "reason": "The player shared their food with Korbar and listened sympathetically to her story."
}
```

| Field       | Type           | Description |
|-------------|----------------|-------------|
| `entity_id` | string\|null   | Target entity ID (e.g., the NPC whose attitude changes, or the entity being noted). Null for `room_note`. |
| `field`     | string         | One of `attitude`, `room_note`, `entity_note`, `soft_inventory_add`, `soft_inventory_remove`. |
| `target_id` | string\|null   | For `room_note`, the room ID. Null for entity-level patches. |
| `old_value` | any\|null      | Expected current value (for validation). Null for add-only patches. |
| `new_value` | any            | Proposed new value. |
| `reason`    | string         | Narrative justification. Must be non-empty. |

### Supported soft state fields

| Field                     | Type     | Allowed values              | Notes |
|---------------------------|----------|-----------------------------|-------|
| `attitude`                | integer  | Within `[min, max]` per corpus | Step limit from `attitude_limits.step_per_turn`. |
| `room_note`               | string   | Non-empty, non-contradictory | Appended to `room_notes[target_id]`. |
| `entity_note`             | string   | Non-empty, non-contradictory | Appended to `entity_notes[entity_id]`. |
| `soft_inventory_add`      | string   | Must match a soft item in the current room or a present entity | Appended to `soft_inventory[]`. |
| `soft_inventory_remove`   | string   | Must exist in `soft_inventory` | Removed from `soft_inventory[]`. |

### Full validation rules

| Rule | Description |
|------|-------------|
| Entity/room must exist | `entity_id` or `target_id` must be defined in the module corpus. |
| Field must be registered | `field` must be one of the supported types above. |
| Attitude step limit | Absolute delta must not exceed corpus `attitude_limits.step_per_turn`. |
| Attitude bounds | `new_value` must be within corpus `attitude_limits.[min, max]`. |
| Alive check | Patches for entities with `alive == false` are rejected. |
| Reason required | `reason` must be non-empty. |
| No hard-state contradiction | Notes cannot assert facts that contradict hard-state flags or entity states. |
| Soft inventory source | `soft_inventory_add` must reference a soft item present in the current room or a present entity. |

---

## Example (initial state for test adventure)

```json
{
  "soft_inventory": [],
  "room_notes": {},
  "entity_notes": {},
  "npc_attitudes": {
    "korbar": 0
  },
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
