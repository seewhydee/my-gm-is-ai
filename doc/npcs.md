# NPC Interaction Model

NPCs are characters the player can interact with. This document covers how NPCs are defined in the corpus, how their state is tracked, and how the system manages dialogue, attitude, and knowledge revelation.

## NPC Definition in the Corpus

An NPC is an entity with `type: "npc"` in the module corpus.  NPCs carry two optional blocks not available to other entity types: `dialogue_guidelines` and `behavior`.

```json
{
  "entities": {
    "korbar": {
      "type": "npc",
      "description": "A grizzled dwarf sitting on a wooden crate, whittling a piece of bone.",
      "state_fields": {
        "alive":    { "type": "boolean", "description": "Whether the NPC is alive" },
        "attitude": { "type": "number",  "description": "Disposition toward the player" },
        "hidden":   { "type": "boolean", "description": "Whether the NPC is hidden from view" }
      },
      "dialogue_guidelines": { ... },
      "behavior": { ... }
    }
  }
}
```

### State Fields

NPCs declare their mutable hard-state fields in `state_fields`.  Two fields are treated specially by the system:

- **`alive`** (`boolean`): If `false`, the NPC is dead.  Dead NPCs cannot participate in dialogue, have their attitude changed, or reveal knowledge.
- **`attitude`** (`number`): The NPC's disposition toward the player.  Stored in hard game state (`entity_states.<npc_id>.attitude`).  Validated and mutated exclusively by the engine.

Additional fields like `hidden`, `injured`, `following`, etc. can be declared as needed by adventure authors.


## Dialogue Guidelines

The `dialogue_guidelines` block defines an NPC's conversational personality, attitude dynamics, knowledge gating, and exit behaviour.

```json
{
  "dialogue_guidelines": {
    "personality": "Gruff, miserable, but secretly lonely. Speaks in short, clipped sentences.",
    "on_encounter": "Korbar looks up from her bottle. 'Another one, eh? How'd you get here?'",
    "can": [
      "Talk about the bag's interior and its dangers",
      "Discuss the spider"
    ],
    "cannot": [
      "Reveal personal history before trust is earned",
      "Discuss escape methods before the spider is dealt with"
    ],
    "knows": [
		"The player and Korbor are trapped in a bag of holding, a magical item that is bigger on the inside than the outside",
		"Jumping out through a hole in the bag walls is a bad idea, since you'll end up in the Astral Plane"
    ],
    "attitude_limits": {
      "min": -5,
      "max": 10,
      "step_per_turn": 3,
      "initial": 0
    },
    "will_reveal": {
      "spider_habits": {
        "description": "The spider lurks where the web is densest. Korbor is afraid of it.",
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
| `dialogue_paths` | Special conversation paths with mechanical effects (see below). |

## Special Dialogue Paths (`dialogue_paths`)

`dialogue_paths` defines special conversation routes that have engine-resolved mechanical consequences.  They are useful for:
- Social approaches tied to stat checks (`flatter`, `intimidate`, `persuade`).
- Delivering plot-critical information (`inform_spider_dead`).
- Any dialogue moment where the engine needs to apply results directly (`adjust_attitude`, `set_flag`, `alter_stat`, etc.).

### Path ID vs. description

Each path has two parts:
- **Path ID** — the machine key used in the `talk` action's `dialogue_path` field and looked up by the engine.
- **Description** — a required human-readable string that explains what the path represents.

The description is **essential** because it is the only context LLM Call 1 has for deciding whether a player's input matches a defined path.  LLM Call 1 receives the paths in `current_room.entities_visible[*].dialogue_paths` as a map of `{path_id: description}`.  It reads the description, decides if the player's intent fits, and outputs the matching path ID in the `talk` action.

Write descriptions as clear player-intent phrases:
- Good: `"Praise the spider's hunting prowess to improve its attitude."`
- Good: `"Tell Korbar that the spider has been dealt with."`
- Bad: `"Flattery path"` (too vague — the LLM cannot map player input to this)

### Example

```json
{
  "dialogue_guidelines": {
    "dialogue_paths": {
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
          "narrative": "Korbar's eyes widen with disbelief, then relief.",
          "adjust_attitude": { "korbar": 3 }
        }
      }
    }
  }
}
```

### Engine resolution flow

1. LLM Call 1 receives `dialogue_paths` as `{path_id: description}` on visible NPCs.
2. If the player's input matches a path description, LLM Call 1 emits a `talk` action with `dialogue_path` set to the matching path ID.
3. The engine validates that the path exists, that its `condition` (if any) is met, and resolves any `check`.
4. The engine applies the `success`, `failure`, or `result` outcome, including any `adjust_attitude`, `set_flag`, or other effects.
5. If no path matches, LLM Call 1 omits `dialogue_path` and the conversation proceeds as freeform dialogue.

## Attitude System

Each NPC has a numeric **attitude** value representing their disposition toward the player:
- Positive: friendly, helpful, trusting
- Zero: neutral
- Negative: hostile, suspicious, unfriendly

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

1. Unlike most other aspects of hard state, attitude can be altered by **LLM Call 2** (the prose narrator).  When LLM Call 2 emits its narration, it may optionally include an `attitude_changes` block in the JSON response:
   ```json
   "attitude_changes": {
     "korbar": {
       "old_value": 2,
       "new_value": 3,
       "reason": "Player gave Korbar a gift"
     }
   }
   ```

2. The post-validation engine step then checks each proposal against a set of conditions:
   - NPC exists and is alive
   - NPC has `dialogue_guidelines`
   - `old_value` matches the current hard-state attitude
   - `|new_value - old_value|` does not exceed `step_per_turn`
   - `new_value` is within `[min, max]`
   - `reason` is non-empty
   - If `step_per_turn == 0`, all changes are rejected

3. Accepted changes are written to hard state.  Rejected changes are returned with explanations.
   Currently, rejection does not alter the narration received by the player.  This could change in future versions.

### Attitude in the GMBriefing

NPC attitude appears in two places in the GMBriefing:

- **Entity state**: `current_room.entities_visible[].state.attitude` — the raw numeric value, visible to both LLM calls.
- **Dialogue context**: When in active dialogue, `dialogue_context.active_npc.attitude` carries the current value for the active NPC.

Additionally, the `EngineResult` sent to LLM Call 2 includes `npc_attitude_limits` (per-NPC `{min, max, step_per_turn, current}`) so the LLM knows the mechanical constraints when proposing changes.

### Magnitude Conventions

The prose template provides guidance to LLM Call 2 on appropriate attitude change magnitudes:

| Change | When to use |
|--------|-------------|
| ±1 | Minor unrepeated interactions: polite greeting, small compliment, mild insult |
| ±2 | Significant interactions: genuine gift, meaningful help, serious threat |
| ±3 | Exceptional moments: saving the NPC's life, deep betrayal |


## Knowledge Revelation (`will_reveal`)

Certain pieces of knowledge that are plot/mechanics relevant are tracked with unique topic IDs.  For example, a secret door may appear in a room only if the player has learned of its existence (from an NPC, reading a note, etc.).

NPCs have a `will_reveal` field specifying what topics they can potentially inform the player about.  Each topic ID is accompanied by:

| Field | Description |
|-------|-------------|
| `description` | Human-readable description of what the NPC reveals (sent to both LLM calls) |
| `conditions` | List of condition strings that must ALL be met for the topic to be revealable |
| `set_flag` | Optional flags to set when the topic is revealed |
| `set_entity_state` | Optional entity state changes when the topic is revealed |

Conditions use the usual condition syntax and can reference NPC attitude, flags, inventory, and other state.

### Flow: How Knowledge Is Revealed

1. The engine evaluates all `will_reveal` entries for NPCs in the current room and produces `will_reveal_readiness` on the `EngineResult`:
   ```json
   "will_reveal_readiness": {
     "korbar": {
       "spider_habits": {
         "conditions_met": true,
         "description": "The spider only hunts at the top of the hour...",
         "conditions": [
           { "condition": "attitude:korbar >= 1", "met": true, "detail": "attitude korbar = 3" }
         ]
       },
       "secret_compartment": {
         "conditions_met": false,
         "description": "There is a hidden flap...",
         "conditions": [
           { "condition": "attitude:korbar >= 2", "met": true, "detail": "attitude korbar = 3" },
           { "condition": "flag:spider_fled == true", "met": false, "detail": "flag spider_fled = False" }
         ]
       }
     }
   }
   ```

  This is sent to LLM Call 2 *only*.  Each condition includes its original string, whether it's met, and a `detail` showing the current state value.  This aids the LLM in roleplaying why a topic is unavailable (e.g., "I'd tell you more, but not while that spider's still loose").

2. LLM Call 2 decides whether the NPC actually reveals a topic during narration. If so, it generates a `knowledge_tags` block that helps tracks what topics the player has uncovered:
   ```json
   "knowledge_tags": {"npc_id": ["topic_id", ...]}
   ```
   The LLM is instructed to only reveal topics whose `conditions_met` is `true`.

3. The post-validation step re-checks the conditions and, if met, records the revelation in `soft.player_knowledge`.  It also applies any `set_flag` / `set_entity_state` side effects in hard state arising from the revealed knowledge.

### Player Knowledge Tracking

Revealed topics are stored in `SoftGameState.player_knowledge`, a flat list of `KnowledgeEntry` records indexed by topic (not by source):

```python
class KnowledgeEntry(BaseModel):
    topic_id: str          # e.g. "spider_habits"
    description: str       # e.g. "The spider only hunts at the top of the hour..."
    source_type: Literal["npc_dialogue", "interaction", "examination", "book", "puzzle"]
    source_id: Optional[str] = None   # entity_id, interaction_id, etc.
    turn_learned: int
```

For the GMBriefing, the Context Assembler produces `player_knowledge_topics` — a list of `{ "topic_id": "...", "description": "..." }` objects for each topic the player has learned.  Including the description (recorded when the topic was first revealed) lets LLM Call 1 understand what the player already knows without cross-referencing the corpus.

The system deduplicates by `topic_id` across **all** sources.  If the player already knows topic X (from an interaction, a previous NPC, or any source), a later NPC who meets the conditions for the same topic will not re-reveal it.  The post-validation silently skips duplicate entries.

### Interaction with Dialogue Context

When dialogue mode is active, the `DialogueContext.revealed_topics` field shows which topics the *current* NPC has revealed.  This is computed by filtering `player_knowledge` for entries with `source_id == active_npc_id`.


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

LLM Call 2 can produce an `npc_response` — the verbatim NPC speech.  This response is appended to the conversation log by the game loop.  Topics from `knowledge_tags` are tracked in `dialogue_state.topics_discussed`.

The conversation log is capped at **10 entries** (scrolls, keeping the most recent).

### Stall Detection

If the player takes actions other than `talk` while in dialogue mode, the **stall counter** increments. After **3 non-talk turns** (not counting `ooc_discussion`), the dialogue exits automatically.  This prevents dialogue mode from lingering when the player has moved on.

### Exiting Dialogue

Dialogue exits through any of these triggers:

| Trigger | Description |
|---------|-------------|
| `talk` with `ends_dialogue: true` | Player explicitly ends the conversation |
| Room change (away from NPC) | Player moves to a room where the NPC is not present |
| NPC death | NPC's `alive` state becomes `false` |
| Stall (3+ non-talk turns) | Player stops engaging with the NPC |

On exit:
1. The engine generates a fallback summary from topics discussed and log length
2. **LLM Call 2** may provide a richer `conversation_note` in its prose output
3. The note written to `soft.entity_notes.<npc_id>` is the LLM's `conversation_note` (if provided) or the engine fallback — whichever is available, not both
4. A `dialogue.ended` event is emitted for the NPC; any entity-scoped
   `dialogue.ended` reaction on that NPC (e.g. setting `alive: false` or a
   flag) fires during deferred reaction dispatch
5. Dialogue state is cleared (`active_npc = null`, log and topics reset)

The `DialogueExitedResult` is surfaced for LLM Call 2 to potentially weave
into narration.  The `conversation_note` field in the prose template instructs
the LLM on the expected format: a self-contained paragraph covering what was
discussed, information exchanged, promises made, and the NPC's disposition.
See `schema/soft-state.md §Archival` for details.

### Dialogue Context in the GMBriefing

When dialogue is active, the Context Assembler injects a `dialogue_context` block into the GMBriefing:

| Field | Content |
|-------|---------|
| `active_npc` | NPC ID, name, current attitude, and full `dialogue_guidelines` |
| `recent_exchanges` | Last 5 player/NPC exchange pairs from the conversation log |
| `topics_discussed` | List of topic strings discussed so far |
| `revealed_topics` | Topic IDs this NPC has already revealed to the player |

This context is available to **both LLM calls** via the GMBriefing.  LLM Call 1 uses it to correctly classify inputs that mix action narration with in-character speech.  LLM Call 2 uses it for conversational continuity and character-consistent responses.

When dialogue is inactive, `dialogue_context` is `null`.


## NPC Behavior & Encounters

NPCs with a `behavior` block can trigger **encounters** — combat or other structured conflict resolution.

```json
{
  "behavior": {
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

Encounters are triggered by entity-scoped reactions (e.g. an `interaction.used`
reaction on the NPC that uses `effects.trigger_encounter: "self"`) or by a
`trigger_encounter` result from another reaction or interaction. For example,
an NPC with the reaction below will trigger its encounter rules when the player
attacks it:

```json
"reactions": [
  {
    "id": "spider_attack_on_sight",
    "on": "interaction.used",
    "condition": { "require": "event:interaction_id == attack" },
    "effects": { "trigger_encounter": "self" }
  }
]
```

Encounters can result in player death, NPC death, NPC fleeing, or dice rolls
with success/failure branches — all resolved by the deterministic engine, not
the LLM.

Encounter outcomes (death, flee, etc.) update hard state, which in turn gates dialogue, attitude changes, and knowledge revelation for that NPC.


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


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
