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
  "player_knowledge":  [ { "topic_id": "...", "description": "...", "source_type": "...", "source_id": "...", "turn_learned": 0 } ],
  "turn_history":      [ { /* turn log entry */ } ],
  "soft_items_taken":  { "<room_or_entity_id>": { "<item_name>": <count> } },
  "soft_contents":     { "<room_or_entity_id>": { "<item_name>": <count> } },
  "checks_attempted":  { "<check_id>": ["<room_id>", ...] },
  "revealed_hints":    ["string", ...],
  "dialogue_state":    { /* active NPC conversation state */ },
  "appearance_notes":  ["string", ...],
  "improvised_weapon": { /* ImprovisedWeapon or null */ }
}
```

---

## `soft_inventory` — Generic carried items

```json
["rock", "loose stone", "dusty rag"]
```

An array of soft item names the player is carrying. These items come from
accepted soft-item takes and are identified by their general name only — no
unique IDs. They can be:

- Used in `transfer` actions (given to targets)
- Referenced in LLM narration

### Validation rules

1. Adding a soft item: the engine creates a `SoftItemProposal`; LLM Call 2
   adjudicates whether the item exists in the scene. Accepted takes are appended
   to `soft_inventory`.
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

## NPC Attitude Tracking

NPC attitude is now tracked as a `state_fields` entry per NPC in
`hard_state.entity_states` (see `corpus.md` § `dialogue.attitude_limits`
and the `entity_states` section of `hard-state.md`). Attitude changes are proposed
by LLM Call 2 via the `attitude_changes` block, post-validated by the engine, and
applied to `hard_state.entity_states[<npc_id>].attitude` via
`StateManager.apply_hard_changes()`.

The Context Assembler includes attitude values for visible NPCs through the
`BriefingEntity.state` field, which contains all declared entity state fields.

### Transition rules (enforced by engine)

Attitude changes are proposed by LLM Call 2 via the `attitude_changes` block
and post-validated by the engine in step 4.5:

1. Attitude changes are validated against the NPC's `attitude_limits` in the
   corpus (`min`, `max`, `step_per_turn`). The absolute change from `old_value`
   to `new_value` must not exceed `step_per_turn`. The `new_value` must be within
   `[min, max]`.
2. Attitude changes must be accompanied by a **non-empty reason**.
3. If an NPC's hard state says `alive == false`, all attitude changes for that
   NPC are rejected.
4. The engine initialises each NPC's attitude from the corpus
   `state_fields.attitude.initial` (default 0).

### Relationship to `dialogue`

The module corpus may gate certain dialogue topics behind attitude thresholds
via the `will_reveal` block. The engine evaluates the `conditions` on each
`will_reveal` entry (e.g., `entity:korbar.attitude >= 2`) against the current game
state. If the LLM narrates a reveal that the conditions do not permit, the
engine flags it in `warnings`.

Revelations are recorded in `npc_revelations` (see below), which feeds into
future GMBriefings and is surfaced in `dialogue_context.revealed_topics` when
that NPC is the active speaker.

---

## `player_knowledge` — Topics the player has learned

```json
[
  {
    "topic_id": "padlock_mechanism",
    "description": "How the exterior padlock can be opened from inside",
    "source_type": "npc_dialogue",
    "source_id": "korbar",
    "turn_learned": 4
  },
  {
    "topic_id": "secret_compartment",
    "description": "A hidden cache inside the axe head",
    "source_type": "npc_dialogue",
    "source_id": "korbar",
    "turn_learned": 6
  }
]
```

Records which topics the player has learned during play. Each entry is a
`KnowledgeEntry` object containing the topic ID, its description, how it was
learned (`source_type` and optional `source_id`), and the turn number when it
was recorded. Populated exclusively by the engine during post-validation of LLM
Call 2's `knowledge_tags`.

### Population rules

| Trigger                                             | Engine action |
|-----------------------------------------------------|---------------|
| LLM Call 2 emits `knowledge_tags.npc_revealed`      | For each topic ID, the engine checks against the active NPC's `will_reveal` entries. If the topic exists and all its `conditions` are met, the engine applies the topic's `set_flag` and `set_entity_state` side effects, then appends a `KnowledgeEntry` to `player_knowledge`. |
| Tag references unknown topic                        | Silently rejected. |
| Tag references topic with unmet conditions          | Silently rejected. |
| Duplicate topic ID (already in `player_knowledge`)  | Skipped (no duplicate entries). |

### Usage in GMBriefing

- The Context Assembler produces `player_knowledge_topics` — a list of
  `{ "topic_id": "...", "description": "..." }` objects for each topic the
  player has learned — and includes it in the GMBriefing so LLM Call 1 knows
  what the player has learned and what each topic means.
- When `dialogue_state.active_npc` is set, the `dialogue_context` block
  includes `revealed_topics` (just the topic IDs for the current NPC) for quick
  reference.

---

## `soft_items_taken` — Soft-item extraction ledger

```json
{
  "axe_head": { "loose stone": 1 },
  "rubbish_pile": { "cork": 2 }
}
```

A dictionary mapping room IDs and entity IDs to dictionaries of soft item
names and the number of times the player has successfully taken them from
that source. This is a pure extraction ledger:
`soft_items_taken[source][name] = N` means exactly "the player has extracted
N of *name* from *source*". Entries are created only by accepted takes of
ambient soft items, so every count is ≥ 1 — examines and gives never write
here, and retrieving a placed item (see `soft_contents` below) is not
extraction.

### Population rules

| Trigger | Action |
|---------|--------|
| `transfer` takes a soft item from a source and LLM Call 2 accepts | The engine increments the item's count under the source room or entity — but only for the portion not covered by `soft_contents` on that source (retrieval is not extraction). |
| `examine` targets a soft item and LLM Call 2 accepts the proposal | No state effect; the adjudication affects narration only. Durable examine facts should be recorded via `room_note`/`entity_note`. |
| `transfer` gives a soft item to a target and LLM Call 2 accepts | No effect on this field; the placement is recorded in `soft_contents`. |

### Usage in GMBriefing

The Context Assembler populates `BriefingRoom.soft_items_taken` and
`BriefingEntity.soft_items_taken` from this field, formatted as
`"name (taken N)"`. LLM Call 2 reads these counts as a depletion signal when
adjudicating further takes from the same source. Carried soft items are
surfaced separately via `soft_inventory` in the player state block.

---

## `soft_contents` — Placed soft items

```json
{
  "korbar": { "cork": 1 },
  "bag_floor": { "rock": 2 }
}
```

A dictionary mapping room IDs and entity IDs to the soft items the player
has given, placed, or dropped there, with current counts. Unlike
`soft_items_taken` (a monotonic history), this is *current state*: entries
are incremented on accepted gives and decremented when the placed items are
retrieved. Counts are always ≥ 1 — zero-count entries (and emptied parent
entries) are pruned.

Items in `soft_contents` have mechanically verified existence — they came
out of the player's own `soft_inventory` via an accepted give — so
retrieving them from a room or non-NPC entity needs no adjudication; from
an NPC, LLM Call 2 adjudicates consent. Lookups normalize names (via
`_normalize_item_name`), so "the Stone" matches a stored "stone".

### Population rules

| Trigger | Action |
|---------|--------|
| `transfer` gives a soft item to an entity and LLM Call 2 accepts | The engine removes the item from `soft_inventory` and increments its count under the target entity. |
| `transfer` gives a soft item to a room (a drop) and LLM Call 2 accepts | The engine removes the item from `soft_inventory` and increments its count under the room ID. |
| Player retrieves a placed item | The engine decrements the count; entries reaching zero (and emptied parent entries) are pruned. |

### Usage in GMBriefing

The Context Assembler populates `BriefingRoom.soft_items_present` and
`BriefingEntity.soft_items_present` from this field, formatted as
`"name xN"`. Placed items can be taken back like ordinary contents.

---

## `checks_attempted` — Non-repeatable check tracking

```json
{
  "rummage_rubbish": ["bag_floor"],
  "study_canvas_glow": ["axe_head"]
}
```

A dict mapping interaction or on-examine event IDs to lists of room IDs
where the check has been attempted. The engine uses this to enforce
non-repeatable checks (`repeatable: false`): if the current room
appears in the list for a given check ID, the engine rejects the
attempt.

### Population rules

| Trigger | Action |
|---------|--------|
| A non-repeatable check is resolved (pass or fail) | The engine records the interaction/event ID and the current room ID. |
| A repeatable check is resolved | No entry is created. |
| Check already recorded for this room | No duplicate entry. |

### Usage

The engine consults `checks_attempted` during interaction and on-examine
resolution. If an interaction has `repeatable: false` in its check and
the interaction ID + current room appears in this dict, the engine
returns a "already attempted" response. This field is not surfaced in
the GMBriefing.

---

## `revealed_hints` — Accumulated reveal strings

```json
[
  "The handkerchief conceals a flap leading to a secret compartment.",
  "The rubbish is actually someone's adventuring supplies, shrunk by the Bag's magic."
]
```

An array of `reveals` strings from successful interactions, on-examine
events, and dialogue path results. When a result object carries a
`reveals` field, the engine appends the string here (deduplicating).
The Context Assembler includes these in the GMBriefing as the
player's accumulated knowledge from discoveries.

### Population rules

| Trigger | Action |
|---------|--------|
| A result with `reveals` is applied | The engine appends the string if not already present. |
| Duplicate string | Skipped (no duplicate entries). |

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
| `flags_changed`         | string[] | Names of hard-state flags that were set or cleared this turn. Empty array for `ooc_discussion` entries. |
| `location_after`        | string   | Room ID the player was in after resolution. For `ooc_discussion`, unchanged from the previous turn. |

`ooc_discussion` entries are logged with `ruled_action.action_type` set to
`"ooc_discussion"`. The Context Assembler skips these entries when building the
`recent_history` block for the GMBriefing.

### Size management

1. The engine appends one entry per completed turn. `ooc_discussion` turns are
   also logged (for debugging and save files) but are **not** counted toward
   the 5-entry cap in the GMBriefing — the `recent_history` block is unchanged
   over the course of `ooc_discussion` actions.
2. The Context Assembler includes the last **5 entries** from non-`ooc_discussion`
   turns in GMBriefing (`recent_history`). This cap prevents context bloat.
3. The full history (including `ooc_discussion` entries) is retained in soft
   state for potential future use (save files, debugging, post-game analysis).

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
| `room.entered` reaction with `trigger_dialogue` | Set `active_npc` to the named NPC, init `conversation_log` with an empty first entry (the NPC "speaks first" via the reaction's `narrative`), set `entered_turn`, reset `stall_counter`. |
| `talk` action to the same NPC            | Append player utterance to `conversation_log`. After LLM Call 2 runs, extract and append the NPC response. Reset `stall_counter` to 0. |
| `talk` action to a different NPC         | Archive conversation (see §Archival), emit `dialogue.ended` event for the previous NPC, switch `active_npc`, start fresh. |
| Any non-`talk` action while in dialogue  | Increment `stall_counter`. If `stall_counter >= 3`, archive conversation (see §Archival), emit `dialogue.ended`, clear dialogue state. |
| `move` action (player leaves room)       | Archive conversation (see §Archival), emit `dialogue.ended`, clear dialogue state. |
| NPC dies or flees                        | Archive conversation (see §Archival), clear dialogue state. Reject future `talk` to that NPC. |
| `talk` with `ends_dialogue: true`        | Archive conversation (see §Archival), emit `dialogue.ended`, clear dialogue state. |
| `ooc_discussion` while in dialogue       | Does not increment `stall_counter`; does not affect dialogue state. |

When dialogue mode exits for any reason, the engine emits a `dialogue.ended`
event for the NPC. Any entity-scoped `dialogue.ended` reaction on that NPC
(e.g. one that sets `alive: false` or applies a flag) will fire during the
deferred reaction dispatch. This allows NPCs to die, flee, transform, or
trigger events when conversation ends.

### NPC response extraction

LLM Call 2 generates the full prose narration including the NPC's spoken response.
After Call 2 completes, the engine extracts the NPC's response from the output
and appends it to `conversation_log`. The extraction can be heuristic (e.g.,
text within quotes attributed to the NPC) or the LLM may include a structured
`npc_response` field alongside its prose to make extraction deterministic.

### Relationship to GMBriefing

When `active_npc != null`, the Context Assembler includes a `dialogue_context`
block in the GMBriefing with the last 5 entries from `conversation_log`, the
NPC's `dialogue`, current attitude, and `topics_discussed`. This
gives LLM Call 1 enough conversational awareness to parse player inputs that
mix action narration with in-character speech, without exposing the full
verbatim chat log.

If `active_npc` is null, `dialogue_context` is omitted from the GMBriefing.

### Archival

When dialogue mode exits, the engine appends a conversation memory note to
`entity_notes[<npc_id>]`. This note persists across turns and is surfaced in
the GMBriefing whenever that NPC is present in the room (last 5 notes per
entity).

**LLM-authored (preferred):** If LLM Call 2 (Prose) includes a
`conversation_note` field in its output, that note is used. The LLM should
write a self-contained narrative summary covering what was discussed, what
information was exchanged, any promises or conflicts, and the NPC's disposition.

```
"Player spoke with Korbar about her origin and abandonment. Korbar revealed
the padlock mechanism secret and became cautiously friendly. Player promised
to look for her old party."
```

**Engine fallback:** If the LLM does not provide a `conversation_note`, the
engine writes a minimal fallback recording only the topic names and exchange
count:

```
"[Turn 4-6] Conversation summary: Discussed origin, abandonment over 6 exchanges."
```

The LLM's note replaces the fallback entirely — the two are never both written.
This preserves the narrative for future GMBriefings without retaining the
verbatim exchange indefinitely in the active dialogue state.

---

---

## `appearance_notes` — Player visual appearance

```json
["tattered cloak pulled from a goblin corpse", "ornamental circlet of woven grass"]
```

Freeform narrative notes about the player's visual appearance from improvised /
narrative-only equipment. Displayed in the GMBriefing's player-state section so
both LLMs can reference them. Carries no mechanical effect — for that, use
hard-state equipment.

### Patch format

```json
{
  "field": "appearance_note_add",
  "new_value": "tattered cloak pulled from a goblin corpse",
  "reason": "Player described wearing the goblin cloak as a trophy."
}
```

### Validation rules

1. `new_value` must be a non-empty string.
2. Notes accumulate in order; the Context Assembler may cap them at the
   briefing stage to avoid context bloat.

---

## `improvised_weapon` — Temporary weapon

```json
{
  "damage_expr": "1d4",
  "hit_bonus": 0,
  "description": "broken bottle",
  "clears_after_turn": true
}
```

An `ImprovisedWeapon` object set by the LLM when the player grabs a non-standard
object and uses it as a weapon (chair leg, broken bottle, heavy rock). It takes
lower priority than a properly equipped weapon but higher than unarmed combat.

| Field               | Type    | Default  | Description |
|---------------------|---------|----------|-------------|
| `damage_expr`       | string  | `"1d6"`  | Damage dice expression. |
| `hit_bonus`         | int     | `0`      | Flat bonus to hit rolls. |
| `description`       | string  | `""`     | Narrative description. |
| `clears_after_turn` | bool    | `false`  | If true, automatically cleared at the start of the next player turn (one-shot use). |

### Patch format

Set an improvised weapon:

```json
{
  "field": "set_improvised_weapon",
  "new_value": {
    "damage_expr": "1d4",
    "hit_bonus": 0,
    "description": "broken bottle",
    "clears_after_turn": true
  },
  "reason": "Player picked up a broken bottle as a weapon."
}
```

Clear an improvised weapon (set to `null`):

```json
{
  "field": "set_improvised_weapon",
  "new_value": null,
  "reason": "The bottle shatters after the blow."
}
```

### Validation rules

1. `new_value` must be either a valid `ImprovisedWeapon` object or `null`.
2. The combat engine consults this field in `get_player_damage_expr()`:
   equipped weapon → improvised weapon → inventory weapon tag (legacy) → unarmed.

---

## SoftStatePatch reference

The general soft-state patch format that LLM Call 1 outputs in
`PlayerAction.proposed_soft_state_patches`:

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

| Field       | Type           | Description |
|-------------|----------------|-------------|
| `entity_id` | string\|null   | Target entity ID for `entity_note`. Null for `room_note`. |
| `field`     | string         | One of `room_note`, `entity_note`, `soft_inventory_remove`, `appearance_note_add`, `set_improvised_weapon`. Attitude changes are proposed separately by LLM Call 2 — see below. |
| `target_id` | string\|null   | For `room_note`, the room ID. Null for entity-level patches. |
| `old_value` | any\|null      | Expected current value (for validation). Null for add-only patches. |
| `new_value` | any            | Proposed new value. |
| `reason`    | string         | Narrative justification. Must be non-empty. |

### Supported soft state fields (LLM Call 1)

| Field                     | Type     | Allowed values              | Notes |
|---------------------------|----------|-----------------------------|-------|
| `room_note`               | string   | Non-empty, non-contradictory | Appended to `room_notes[target_id]`. |
| `entity_note`             | string   | Non-empty, non-contradictory | Appended to `entity_notes[entity_id]`. |
| `soft_inventory_remove`   | string   | Must exist in `soft_inventory` | Removed from `soft_inventory[]`. |
| `appearance_note_add`     | string   | Non-empty string               | Appended to `appearance_notes[]`. |
| `set_improvised_weapon`   | dict\|null | Valid `ImprovisedWeapon` dict or `null` | Sets or clears `improvised_weapon`. |

### Full validation rules (LLM Call 1 patches)

| Rule | Description |
|------|-------------|
| Entity/room must exist | `entity_id` or `target_id` must be defined in the module corpus. |
| Field must be registered | `field` must be one of the supported types above. |
| Alive check | Patches for entities with `alive == false` are rejected. |
| Reason required | `reason` must be non-empty. |
| No hard-state contradiction | Notes cannot assert facts that contradict hard-state flags or entity states. |
| Soft inventory removal | `soft_inventory_remove` must reference an item currently in `soft_inventory`. |
| Appearance note value | `appearance_note_add.new_value` must be a non-empty string. |
| Improvised weapon shape | `set_improvised_weapon.new_value` must be a valid `ImprovisedWeapon` object or `null`. |

### Attitude changes (LLM Call 2)

Attitude changes are proposed by LLM Call 2 via the `attitude_changes` block
(see `actions.md` §5), not by LLM Call 1 via `SoftStatePatch`. The engine
post-validates them against the NPC's `attitude_limits` using the same rules:

| Rule | Description |
|------|-------------|
| Entity must exist | NPC entity ID must be defined in the corpus. |
| Attitude step limit | Absolute delta must not exceed corpus `attitude_limits.step_per_turn`. |
| Attitude bounds | `new_value` must be within corpus `attitude_limits.[min, max]`. |
| Alive check | Changes for entities with `alive == false` are rejected. |
| Reason required | `reason` must be non-empty. |

---

## Example (initial state for test adventure)

```json
{
  "soft_inventory": [],
  "room_notes": {},
  "entity_notes": {},
  "player_knowledge": [],
  "soft_items_taken": {},
  "soft_contents": {},
  "checks_attempted": {},
  "revealed_hints": [],
  "turn_history": [],
  "dialogue_state": {
    "active_npc": null,
    "conversation_log": [],
    "topics_discussed": [],
    "entered_turn": 0,
    "stall_counter": 0
  },
  "appearance_notes": [],
  "improvised_weapon": null
}
```


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
