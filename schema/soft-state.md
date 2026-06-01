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
  "npc_attitudes":     { "<npc_entity_id>": { "attitude": "..." } },
  "environmental_notes": [ "string", ... ],
  "turn_history":      [ { /* turn log entry */ } ],
  "dialogue_state":    { /* active NPC conversation state */ }
}
```

---

## `npc_attitudes` — NPC disposition tracking

```json
{
  "<npc_entity_id>": {
    "attitude": "hostile | neutral | friendly"
  }
}
```

### Attitude values

| Value      | Meaning | Typical NPC behaviour |
|------------|---------|-----------------------|
| `hostile`  | The NPC is antagonistic. Will not cooperate, may attack or obstruct. |
| `neutral`  | Default starting attitude. The NPC is indifferent or cautious. |
| `friendly` | The NPC likes the player. Will offer help, reveal secrets, cooperate. |

### Transition rules (enforced by engine)

1. Attitude may change at most **one step per turn** (e.g., `hostile → neutral`
   or `neutral → friendly`). Multi-step jumps in a single turn are rejected
   unless the LLM provides an extraordinary justification AND the engine is
   configured to allow it.
2. Attitude changes must be accompanied by a **non-empty reason** in the
   SoftStatePatch.
3. If an NPC's hard state says `alive == false`, all attitude patches for that
   NPC are rejected.

### Relationship to `dialogue_guidelines`

The module corpus may gate certain dialogue topics behind attitude thresholds.
For example, Korbar only reveals the secret compartment when `attitude == "friendly"`.
The engine checks these constraints when LLM Call 2 narrates: if the LLM
proposes narration that implies a secret reveal at `neutral` attitude, the
engine flags it in `soft_state_patches_rejected` or issues a `warning`.

---

## `environmental_notes` — Narrative environmental continuity

```json
[
  "The webs on the lower axe handle are now partially cleared from the spider's flight.",
  "Korbar has built a small lean-to from corks and sandwich wrappers."
]
```

Environmental notes are freeform strings appended by the engine when the LLM
proposes an `environmental_note` patch. They are carried forward in future
GMBriefings to give the LLM continuity about minor narrative changes that
don't rise to the level of hard-state flags.

### Patch format

```json
{
  "entity_id": null,
  "field": "environmental_note",
  "old_value": null,
  "new_value": "The webs on the lower axe handle are now partially cleared.",
  "reason": "Player hacked through the webs with the toenail sword."
}
```

### Validation rules

1. `new_value` must be a non-empty string.
2. The note must not contradict any hard state flag (e.g., the engine rejects
   a note saying "the spider is dead" if `entity_states.spider.alive == true`).
3. No duplicate detection — identical notes may accumulate; the Context
   Assembler can deduplicate them at briefing time.

### Usage in GMBriefing

The Context Assembler appends the most recent N environmental notes (up to 5)
to the room description or player state summary. This helps the LLM remember
that "the webs were already cut" or "the campfire is still smoldering."

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
| `ruled_action`          | object   | The validated `PlayerAction` (as resolved, not as originally proposed). |
| `engine_result_summary` | string   | Condensed summary of what happened — key outcomes only. Written by the engine. |
| `flags_changed`         | string[] | Names of hard-state flags that were set or cleared this turn. |
| `location_after`        | string   | Room ID the player was in after resolution. |

### Size management

1. The engine appends one entry per completed turn.
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
  "paused_turn": null
}
```

### Fields

| Field                | Type              | Description |
|----------------------|-------------------|-------------|
| `active_npc`         | string\|null      | Entity ID of the NPC the player is speaking to. `null` means no active dialogue. |
| `conversation_log`   | array             | Verbatim dialogue exchanges, capped at **10** entries (FIFO eviction). Each entry records the turn number, speaker identifier (`"player"` or the NPC's `entity_id`/name), and the verbatim text spoken. |
| `topics_discussed`   | string[]          | Named topics that have come up in conversation. LLM Call 1 may propose new topics; the engine deduplicates and stores them. Used by the Context Assembler to inform the ruling LLM what has already been covered. |
| `entered_turn`       | number            | The turn number when dialogue mode was activated. Used by the engine for stall detection. |
| `paused_turn`        | number\|null      | Set to the current turn when a non-`talk` action occurs during dialogue. If 3+ turns elapse without another `talk`, the engine auto-clears dialogue mode. `null` when conversation is active. |

### Lifecycle rules

| Trigger                              | Engine action |
|--------------------------------------|---------------|
| `talk` action succeeds (no active dialogue) | Set `active_npc`, init `conversation_log` with player utterance, set `entered_turn`. |
| `talk` action to same NPC           | Append to `conversation_log`. After LLM Call 2 runs, append the NPC response summary. |
| `talk` action to different NPC      | Archive current `conversation_log` as an `environmental_note` summary, switch `active_npc`, start fresh. |
| `move` action (player leaves room)  | Archive `conversation_log`, set `active_npc = null`, set `interrupted: true` in the archive note. |
| NPC dies or flees                   | Archive `conversation_log`, set `active_npc = null`. Reject future `talk` to that NPC. |
| `talk` with `ends_dialogue: true`   | Archive `conversation_log`, set `active_npc = null`. |
| 3 turns since last `talk` in dialogue mode | Engine auto-clears dialogue mode; archive and nullify. |

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

### Relationship to `dialogue_guidelines`

The engine cross-references `will_reveal` constraints in the NPC's
`dialogue_guidelines` with `topics_discussed` and current attitude. If the
LLM narrates a secret reveal that is gated behind a higher attitude or an
undiscovered topic, the engine flags it in `warnings`. The `will_reveal`
block in the corpus can also gate on `topic:<topic_id>` conditions — e.g.,
"the NPC only reveals the padlock mechanism if `abandonment` has been
discussed AND attitude >= friendly."

### Archival

When dialogue mode exits, the full `conversation_log` is appended as a
single `environmental_note`:

```
"[Turn 4-5] Conversation with Korbar: player asked about her origin and
party; Korbar revealed she was abandoned by her adventuring company three
years ago. Topics: origin, abandonment."
```

This preserves the narrative for future GMBriefings without retaining the
verbatim exchange indefinitely in the active dialogue state.

---

## SoftStatePatch reference (from actions.md)

For completeness, the soft-state patch format that the LLM outputs in
`PlayerAction.proposed_soft_state_patches`:

```json
{
  "entity_id": "korbar",
  "field": "attitude",
  "old_value": "neutral",
  "new_value": "friendly",
  "reason": "The player shared their food with Korbar and listened sympathetically to her story."
}
```

| Field       | Type          | Description |
|-------------|--------------|-------------|
| `entity_id` | string|null  | Target NPC entity ID. Null for `environmental_note` patches. |
| `field`     | string       | Must be `"attitude"` or `"environmental_note"`. |
| `old_value` | string|null  | Expected current value (for validation). Null for add-only fields. |
| `new_value` | string       | Proposed new value. |
| `reason`    | string       | Narrative justification. Must be non-empty. |

### Full validation rules

| Rule | Description |
|------|-------------|
| Entity must exist | `entity_id` must be defined in the module corpus `entities`. |
| Field must be registered | `field` must be one of `attitude`, `environmental_note`. |
| Attitude step limit | Attitude transitions are capped at one step per turn. |
| Alive check | Patches for entities with `alive == false` are rejected. |
| Reason required | `reason` must be non-empty. |
| No hard-state contradiction | Environmental notes cannot assert facts that contradict hard-state flags or entity states. |

---

## Example (initial state for test adventure)

```json
{
  "npc_attitudes": {
    "korbar": { "attitude": "neutral" }
  },
  "environmental_notes": [],
  "turn_history": [],
  "dialogue_state": {
    "active_npc": null,
    "conversation_log": [],
    "topics_discussed": [],
    "entered_turn": 0,
    "paused_turn": null
  }
}
```
