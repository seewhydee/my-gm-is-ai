# NPC Interaction Model

NPCs are the characters the player can talk to, fight, and build relationships with. This document covers how NPCs are defined in the corpus, how their state is tracked, and how the system manages dialogue, attitude, and knowledge revelation.

## NPC Definition in the Corpus

An NPC is an entity with `type: "npc"` in the module corpus. NPCs carry two optional blocks not available to other entity types: `dialogue_guidelines` and `behavior`.

```json
{
  "entities": {
    "korbar": {
      "type": "npc",
      "description": "A grizzled dwarf sitting on a wooden crate, whittling a piece of bone.",
      "state_fields": {
        "alive":    { "type": "boolean", "description": "Whether the NPC is alive" },
        "attitude": { "type": "number",  "description": "Disposition toward the player" },
        "told_secret": { "type": "boolean", "description": "Whether the NPC has shared the secret" }
      },
      "dialogue_guidelines": { ... },
      "behavior": { ... }
    }
  }
}
```

### State Fields

NPCs declare their mutable hard-state fields in `state_fields`. Two fields are treated specially by the system:

- **`alive`** (`boolean`): If `false`, the NPC is dead. Dead NPCs cannot participate in dialogue, have their attitude changed, or reveal knowledge.
- **`attitude`** (`number`): The NPC's disposition toward the player. Stored in hard game state (`entity_states.<npc_id>.attitude`). Validated and mutated exclusively by the engine.

Additional fields like `told_secret`, `fled`, etc. can be declared as needed by adventure authors.

---

## Dialogue Guidelines

The `dialogue_guidelines` block defines an NPC's conversational personality, attitude dynamics, knowledge gating, and exit behaviour.

```json
{
  "dialogue_guidelines": {
    "personality": "Gruff, cynical, but secretly lonely. Speaks in short, clipped sentences.",
    "on_encounter": "Korbar looks up from his whittling. 'Another one, eh? Fell through the rip too?'",
    "can": [
      "Talk about the bag's interior and its dangers",
      "Discuss the spider"
    ],
    "cannot": [
      "Reveal personal history before trust is earned",
      "Discuss the lich before the spider is dealt with"
    ],
    "knows": [
      "The bag's internal geography",
      "The spider's habits",
      "The lich's weakness"
    ],
    "attitude_limits": {
      "min": -5,
      "max": 10,
      "step_per_turn": 3,
      "initial": 0
    },
    "will_reveal": {
      "spider_habits": {
        "description": "The spider only hunts at the top of the hour, when the bag's ambient magic pulses.",
        "conditions": ["attitude:korbar >= 1"]
      },
      "secret_compartment": {
        "description": "There is a hidden flap under the handkerchief leading to a secret compartment.",
        "conditions": ["attitude:korbar >= 2", "flag:spider_fled == true"],
        "set_flag": { "handkerchief_noticed": true },
        "set_entity_state": {
          "korbar": { "told_secret": true }
        }
      }
    },
    "on_dialogue_exit": {
      "narrative": "Korbar returns to his whittling, muttering something under his breath."
    }
  }
}
```

### Fields

| Field | Description |
|-------|-------------|
| `personality` | Natural-language description of the NPC's personality and speech patterns. Sent to both LLM calls for character-consistent dialogue. |
| `on_encounter` | Optional text describing the NPC's initial behaviour when the player first sees them (not yet used mechanically). |
| `can` | Topics and actions the NPC is allowed to discuss or perform. Advisory for the LLM. |
| `cannot` | Topics and actions the NPC must never discuss or perform. Advisory for the LLM. |
| `knows` | Knowledge the NPC possesses (which may or may not be revealed depending on conditions). Advisory for the LLM. |
| `attitude_limits` | Mechanical bounds on the NPC's attitude (see below). |
| `will_reveal` | Topics the NPC can reveal, gated by conditions, with optional side effects (see below). |
| `on_dialogue_exit` | Optional effects applied when dialogue ends (see Dialogue Lifecycle). |

---

## Attitude System

Each NPC has a numeric **attitude** value representing their disposition toward the player:
- **Positive** (> 0): friendly, helpful, trusting
- **Zero**: neutral
- **Negative** (< 0): hostile, suspicious, unfriendly

### Storage

Attitude is stored in **hard game state** (`entity_states.<npc_id>.attitude`). This makes it engine-authoritative: the LLM can propose changes but only the engine can apply them, and only within corpus-defined limits.

### Attitude Limits

Defined per-NPC in `dialogue_guidelines.attitude_limits`:

| Field | Description |
|-------|-------------|
| `min` | Minimum possible attitude value |
| `max` | Maximum possible attitude value |
| `step_per_turn` | Maximum absolute change per turn. If 0, the NPC's attitude is frozen. |
| `initial` | Starting attitude value at game start |

### Flow: How Attitude Changes

1. **LLM Call 2** (the prose narrator) outputs an `attitude_changes` block in its JSON response:
   ```json
   "attitude_changes": {
     "korbar": {
       "old_value": 2,
       "new_value": 3,
       "reason": "Player gave Korbar a gift"
     }
   }
   ```

2. **Post-validation** (`post_validate_attitude_changes`) checks each proposal against:
   - NPC exists and is alive
   - NPC has `dialogue_guidelines`
   - `old_value` matches the current hard-state attitude
   - `|new_value - old_value|` does not exceed `step_per_turn`
   - `new_value` is within `[min, max]`
   - `reason` is non-empty
   - If `step_per_turn == 0`, all changes are rejected

3. **Accepted changes** are written to `hard.entity_states.<npc_id>.attitude`. **Rejected changes** are returned in `EngineResult.attitude_changes_rejected` with explanations; the narrator must not describe rejected changes.

### Attitude in the GMBriefing

NPC attitude appears in two places in the GMBriefing:

- **Entity state**: `current_room.entities_visible[].state.attitude` — the raw numeric value, visible to both LLM calls.
- **Dialogue context**: When in active dialogue, `dialogue_context.active_npc.attitude` carries the current value for the active NPC.

Additionally, the `EngineResult` sent to LLM Call 2 includes `npc_attitude_limits` (per-NPC `{min, max, step_per_turn, current}`) so the LLM knows the mechanical constraints when proposing changes.

### Magnitude Conventions

The prose template provides guidance to LLM Call 2 on appropriate attitude change magnitudes:

| Change | When to use |
|--------|-------------|
| ±1 | Minor interactions: polite greeting, small compliment, mild insult |
| ±2 | Significant interactions: genuine gift, meaningful help, serious threat |
| ±3 | Exceptional moments: saving the NPC's life, deep betrayal |

---

## Knowledge Revelation (`will_reveal`)

The `will_reveal` system controls what NPCs can tell the player and what mechanical side effects result.

### Topic Definition

Each topic under `will_reveal` has:

| Field | Description |
|-------|-------------|
| `description` | Human-readable description of what the NPC reveals (sent to both LLM calls) |
| `conditions` | List of condition strings that must ALL be met for the topic to be revealable |
| `set_flag` | Optional flags to set when the topic is revealed |
| `set_entity_state` | Optional entity state changes when the topic is revealed |

Conditions can reference attitude (`attitude:korbar >= 2`), flags (`flag:spider_fled == true`), inventory, and other state — the same condition syntax used throughout the engine.

### Flow: How Knowledge Is Revealed

1. **The engine** evaluates all `will_reveal` entries for NPCs in the current room and produces `will_reveal_readiness` on the `EngineResult`:
   ```json
   "will_reveal_readiness": {
     "korbar": {
       "spider_habits": {
         "conditions_met": true,
         "description": "The spider only hunts at the top of the hour..."
       },
       "secret_compartment": {
         "conditions_met": false,
         "description": "There is a hidden flap..."
       }
     }
   }
   ```
   This is sent to **LLM Call 2 only** (the prose narrator).

2. **LLM Call 2** decides whether the NPC actually reveals a topic during narration. If so, it includes a `knowledge_tags` block:
   ```json
   "knowledge_tags": { "npc_revealed": { "korbar": ["spider_habits"] } }
   ```
   The LLM is instructed to **only tag topics where `conditions_met` is `true`**.

3. **Post-validation** (`post_validate_knowledge_tags`) re-checks conditions and, if met, applies any `set_flag` / `set_entity_state` side effects directly to hard state, and records the revelation in `soft.player_knowledge`.

### Player Knowledge Tracking

Revealed topics are stored in `SoftGameState.player_knowledge`, a flat list of `KnowledgeEntry` records:

```python
class KnowledgeEntry(BaseModel):
    topic_id: str          # e.g. "spider_habits"
    description: str       # e.g. "The spider only hunts at the top of the hour..."
    source_type: Literal["npc_dialogue", "interaction", "examination", "book", "puzzle"]
    source_id: Optional[str] = None   # entity_id, interaction_id, etc.
    turn_learned: int
```

This replaces the earlier per-NPC `npc_revelations` dict. Knowledge is indexed by topic, not by source — the system tracks *what* the player knows, with source as metadata rather than the primary key.

For the GMBriefing, the Context Assembler produces `player_knowledge_topics: List[str]` — a flat list of topic IDs the player has learned. Full descriptions are available from the corpus `will_reveal` entries when needed by LLM Call 2. This avoids duplicating description text in every briefing.

### Duplicate Detection

The system deduplicates by `topic_id` across **all** sources. If the player already knows topic X (from an interaction, a previous NPC, or any source), a later NPC who meets the conditions for the same topic will not "re-reveal" it — the post-validation silently skips duplicate entries.

### Interaction with Dialogue Context

When dialogue mode is active, the `DialogueContext.revealed_topics` field shows which topics the *current* NPC has revealed. This is computed by filtering `player_knowledge` for entries with `source_id == active_npc_id`.

---

## Dialogue Lifecycle

### Entering Dialogue

Dialogue begins when the player submits a `talk` action targeting a living NPC in the current room. The engine:
1. Sets `dialogue_state.active_npc` to the target NPC ID
2. Clears the conversation log, topics discussed, and stall counter
3. Records the player's utterance (if provided) as the first log entry

If the player was already talking to a different NPC, the previous dialogue is exited first.

### During Dialogue

Each `talk` action during active dialogue:
- Records the player's utterance (or a paraphrase of the detail) to the conversation log
- Resets the stall counter to 0

LLM Call 2 can produce an `npc_response` — the verbatim NPC speech. This response is appended to the conversation log by the game loop. Topics from `knowledge_tags` are tracked in `dialogue_state.topics_discussed`.

The conversation log is capped at **10 entries** (scrolls, keeping the most recent).

### Stall Detection

If the player takes actions other than `talk` while in dialogue mode, the **stall counter** increments. After **3 non-talk turns** (not counting `ooc_discussion`), the dialogue exits automatically. This prevents dialogue mode from lingering when the player has moved on.

### Exiting Dialogue

Dialogue exits through any of these triggers:

| Trigger | Description |
|---------|-------------|
| `talk` with `ends_dialogue: true` | Player explicitly ends the conversation |
| Room change (away from NPC) | Player moves to a room where the NPC is not present |
| NPC death | NPC's `alive` state becomes `false` |
| Stall (3+ non-talk turns) | Player stops engaging with the NPC |

On exit:
1. A **conversation summary** is generated from the topics discussed and log length
2. The summary is appended to `soft.entity_notes.<npc_id>` as a record of the interaction
3. If the NPC's `dialogue_guidelines.on_dialogue_exit` defines `set_flag` or `set_entity_state` side effects, they are applied to hard state
4. Dialogue state is cleared (`active_npc = null`, log and topics reset)

The `on_dialogue_exit.narrative` field, if present, is surfaced in the `DialogueExitedResult` for LLM Call 2 to potentially weave into narration.

### Dialogue Context in the GMBriefing

When dialogue is active, the Context Assembler injects a `dialogue_context` block into the GMBriefing:

| Field | Content |
|-------|---------|
| `active_npc` | NPC ID, name, current attitude, and full `dialogue_guidelines` |
| `recent_exchanges` | Last 5 player/NPC exchange pairs from the conversation log |
| `topics_discussed` | List of topic strings discussed so far |
| `revealed_topics` | Topic IDs this NPC has already revealed to the player |

This context is available to **both LLM calls** via the GMBriefing. LLM Call 1 uses it to correctly classify inputs that mix action narration with in-character speech. LLM Call 2 uses it for conversational continuity and character-consistent responses.

When dialogue is inactive, `dialogue_context` is `null`.

---

## NPC Behavior & Encounters

NPCs with a `behavior` block can trigger **encounters** — combat or other structured conflict resolution.

```json
{
  "behavior": {
    "triggers_on": ["attack"],
    "encounter_rules": [
      {
        "condition": { "require": "flag:has_weapon == true" },
        "outcome": "roll",
        "threshold": 0.5,
        "narrative": "You swing at the spider...",
        "set_flags": {},
        "on_success": {
          "outcome": "death",
          "narrative": "The spider crumples.",
          "set_flags": { "spider_fled": true }
        },
        "on_failure": {
          "outcome": "flee",
          "narrative": "The spider knocks you back.",
          "set_flags": {}
        }
      }
    ],
    "on_flee": {
      "set_flags": { "spider_fled": true },
      "set_entity_state": { "spider": { "alive": false } },
      "effect": "remove_entity"
    }
  }
}
```

When the player uses `interact` with `interaction_id: "attack"` targeting an NPC with a `behavior` block, the engine dispatches to encounter resolution. Encounters can result in player death, NPC death, NPC fleeing, or simple dice rolls with success/failure branches — all resolved by the deterministic engine, not the LLM.

Encounter outcomes (death, flee, etc.) update hard state (`entity_states.<npc>.alive`), which in turn gates dialogue, attitude changes, and knowledge revelation for that NPC.

---

## Summary: Per-Turn NPC Data Flow

```
Corpus (dialogue_guidelines, will_reveal, attitude_limits)
    │
    ▼
Context Assembler ──► GMBriefing
    │                  ├── entity state (attitude)
    │                  ├── dialogue_context (if active)
    │                  └── player_knowledge_topics
    ▼
LLM Call 1 (ruling)
    │  Uses dialogue_context to classify mixed speech/action input
    ▼
PlayerAction
    ▼
Engine
    │  Validates talk target, manages dialogue lifecycle
    │  Produces will_reveal_readiness + npc_attitude_limits on EngineResult
    ▼
LLM Call 2 (prose)
    │  Narrates NPC response (npc_response)
    │  Proposes knowledge_tags (checking will_reveal_readiness)
    │  Proposes attitude_changes (checking npc_attitude_limits)
    ▼
Post-validation
    │  Validates knowledge_tags → applies side effects, records KnowledgeEntry
    │  Validates attitude_changes → writes to hard.entity_states.<npc>.attitude
    ▼
Hard State updated    Soft State updated
  (attitude, flags,     (player_knowledge,
   entity_states)        dialogue_state, etc.)
```
