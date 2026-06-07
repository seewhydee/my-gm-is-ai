# My GM is AI — Architecture Guide

The objective of this software is to implement an AI-driven Game Master (GM) that can replicate key aspects of the tabletop RPG experience.  It attempts to function like a human GM running a pre-written adventure module: the GM knows and follows the rules, but also accommodates the player's intentions and provide narrative flavor.

The system uses a large language model (LLM) to drive interpretation and narration, and a deterministic engine to impose game mechanics.  LLMs are excellent at natural-language understanding and prose generation, but unreliable for rule enforcement and state tracking.  By splitting these responsibilities, we (hope to) get the best of both worlds: the LLM interprets player intent, constructs structured actions, and weaves outcomes into compelling prose; the engine validates actions against the rules, resolves mechanics, and constrains the narrative output to the actual game state.

## Architecture

Each turn, we run two LLM calls sandwiching a deterministic engine. The LLM calls and engine are informed by three data stores that track the game state.

### Per-turn data flow

```
Player Input
      │
      ▼
┌──────────────────┐
│ Context Assembler│ ◄── Corpus + Hard State + Soft State
└────┬─────────────┘
     │ GMBriefing (structured JSON)
     ▼
┌─────────────────┐
│   LLM Call 1    │  (low temperature — ruling)
│ "What does      │
│  the player     │  Output: PlayerAction (machine-readable)
│  attempt?"      │         + optional soft state patch
└────┬────────────┘
     │ PlayerAction
     ▼
┌─────────────────┐
│  Engine         │  Reads: Corpus + Hard State + Soft State
│ (checks, rules, │  Writes: Hard State only
│  roll dice)     │  Validates & applies soft state patch
└────┬────────────┘
     │ EngineResult (outcome, state diffs, narration)
     ▼
┌─────────────────┐
│   LLM Call 2    │  (moderate temperature — prose)
│ "How does the   │
│  world react?"  │  Output: natural-language narration
│                 │       + optional NPC knowledge tags
└────┬─────────┬──┘         and/or attitude changes
     │         ▼
     │ ┌─────────────────┐
     │ │ Post-validation │ Validates knowledge_tags and
     │ │   (optional)    │ attitude_changes
     │ └──────┬──────────┘
     ▼        ▼
   Game state saved   Player receives narration
```

### The three data stores

**Module Corpus** (read-only). This is loaded at startup and never modified during play, serving as the equivalent of a printed adventure module.  It specifies rooms (as graph nodes), entities (player, NPCs, features, items), interactions (named actions gated by conditions), and mechanics (win/lose rules, dice checks).

**Hard Game State** (engine-authoritative). This contains mutable runtime state and is managed exclusively by the engine. It tracks player location, inventory, flags, room/entity states, turn count, and game-over conditions. The LLM reads part of it via the GMBriefing, but cannot alter it directly.

**Soft Game State** (LLM-proposed, engine-validated). This contains narrative elements that the LLM can propose changes to: soft inventory (non-unique items like "a rock"), room notes, entity notes, NPC attitudes, dialogue state, turn history, and NPC revelations. All proposals go through a patch schema, which the engine validates and applies.

### The Context Assembler and GMBriefing

Each turn, the Context Assembler builds a **GMBriefing**: a compact JSON document describing the current world state to the ruling LLM. It contains:

- **Global setting**: a few introductory sentences about the adventure.
- **Current room**: ID, name, prose description, visible entities, available exits, available interactions.
- **Player state**: location, hard inventory, soft inventory, active flags.
- **Recent history**: the last 5 turns, summarised.
- **NPC revelations**: topics NPCs have revealed to the player so far.
- **Dialogue context** (when in conversation): active NPC identity, attitude, dialogue guidelines, recent exchanges, topics discussed — all omitted when not in dialogue.
- **Player input**: the verbatim input for this turn.

No vector database — lookups are deterministic by ID.

### LLM Call 1 and player actions

LLM Call 1, which runs at a moderately low temperature, receives the GMBriefing + verbatim player input and is tasked with interpreting the player's input.  It cannot propose hard-state changes (those are the engine's domain).  Instead, it is tasked with producing a structured PlayerAction in JSON, consisting of exactly one of seven types:

| Type | Purpose | Key fields |
|------|---------|------------|
| `move` | Travel to an adjacent room via an exit | `target` (exit ID), optional `style` (crawl, etc.) |
| `examine` | Look at a room, entity, or soft item | `target`, optional `rigorous` (deep search), optional `using` |
| `interact` | Perform a named interaction on an entity | `target`, `interaction_id`, optional `using` |
| `talk` | Start or continue dialogue with an NPC | `target` (NPC ID), optional `utterance`, optional `ends_dialogue` |
| `transfer` | Give/take items between player and entity/room | `target`, `given_items`[], `taken_items`[] |
| `wait` | Pass time, catch-all for below-threshold actions | `detail` describing intent |
| `ooc_discussion` | Out-of-character question to the GM | `detail` with the question |

Every action includes a `detail` field (natural-language description), optional `proposed_soft_state_patches`, and optional `follow_up` for chained actions (see below).

Only one action occurs per turn. Multi-step inputs ("I pick up the key and unlock the door") are handled by constructing **chained actions**.  The LLM extracts the first action ("I pick up the key") and stores the rest in the `follow_up` field ("unlock the door").  After the first action is processed, the engine injects the follow-up as a new turn, *without waiting for further player input*.  This follow-up can itself be broken up, thereby extending the chain, if necessary.  The chain terminates if any step fails validation; we also define a maximum chain depth to prevent infloops.

### Engine resolution

The engine is the system's source of truth. It receives the PlayerAction and:

1. **Validates** the action (e.g., is the entity alive? does the item exist?).
2. **Resolves mechanics**: evaluates conditions, rolls dice for checks, dispatches encounters, applies traversal effects and on-enter events.
3. **Applies hard-state changes**: flags, inventory, location, entity states.
4. **Validates soft-state patches**: accepts/rejects with reasons.
5. **Checks for game-over**.
6. **Produces an EngineResult** containing the full outcome: success/failure, the room after resolution, a diff of all changes, triggered narrations (canonical prose for key events), encounter outcomes, roll details, warnings, and chain-action handling info.

### LLM Call 2: Prose narration (moderate temperature)

LLM Call 2 runs at a moderately high temperature, after the engine.  It receives the GMBriefing, PlayerAction, EngineResult, and a verbatim chat log. Its task is to weave the outcome into natural prose, subject to these constraints:

1. **Do not contradict the engine result** — if the engine says the spider fled, do not narrate it attacking.
2. **Do not invent game state** — no adding items, changing rooms, or killing entities.
3. **Incorporate triggered narrations** — weave canonical prose blocks into the narrative, don't replace them.
4. **Respect hidden information** — secret exits, gated NPC knowledge, and unrevealed mechanics must not be divulged.
5. **Respect game-over** — if `game_over` is set, narrate the ending and stop.

Optionally, the LLM may also propose `knowledge_tags` (which topic IDs an NPC revealed) and `attitude_changes` (NPC attitude shifts from this turn's events). Both are checked in the post-validation step before being applied.

### Dialogue mode

When the player starts talking to an NPC (`talk` action), the system enters dialogue mode. The GMBriefing is enriched with a `dialogue_context` block containing the NPC's personality guidelines, recent exchanges, and discussed topics.

The `dialogue_context` block is a calculated gamble: we provide LLM Call 2 with more context to improve its conversational ability, hoping that the other guardrails can ward off hallucinations (e.g., the instructions to the LLM to defer to engine results if contradictions arise).

Dialogue ends when: the player moves rooms, the NPC dies/flees, the player sends `talk` with `ends_dialogue: true`, or 3+ turns pass without a `talk` action.

### Error handling

- **Malformed LLM output** (invalid JSON, unknown action): retry once with error in prompt, then fall back to generic narration.
- **Impossible action** (valid JSON but engine rejects): `success: false` with a reason; narration describes the failure.
- **Rejected soft patches** and **rejected attitude changes**: listed in the EngineResult; narrator must not narrate the rejected change.

### Serialization

After each non-chain turn, the system saves hard state + soft state as a JSON file. The GMBriefing is reconstructed from scratch on load; no LLM context is persisted.

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Best ecosystem for LLM work; modern typing support |
| Schema / validation | Pydantic v2 | Discriminated unions, model validation, JSON serialization |
| LLM client | `openai` package | Supports `base_url` for Deepseek; `response_format` for JSON mode |
| Prompt templates | Jinja2 | Clean separation of prompt text from code |
| Console UI | `rich` | Markdown rendering, colored panels |
| Testing | pytest | Standard; parametrized tests, mock LLM |
| CLI entry | argparse | Built-in, sufficient |

## Directory Structure

```
mgmai/
├── cli.py                       # Entry point, argument parsing, game start
├── models/                      # Pydantic models — all structured data
│   ├── corpus.py                # Module Corpus
│   ├── hard_state.py            # Hard Game State
│   ├── soft_state.py            # Soft Game State
│   ├── actions.py               # PlayerAction, EngineResult
│   ├── briefing.py              # GMBriefing, dialogue_context
│   └── narration.py             # NarrationOutput, AttitudeChange, KnowledgeTags
├── engine/                      # Deterministic game engine
│   ├── conditions.py            # Condition evaluator
│   ├── resolver.py              # Action resolvers (move, examine, interact, etc.)
│   ├── encounters.py            # Encounter resolution
│   ├── dialogue.py              # Dialogue lifecycle (enter, exit, stall, archive)
│   ├── engine.py                # Main engine pipeline
│   └── post_validate.py         # Post-validation of knowledge_tags + attitude_changes
├── state/
│   └── manager.py               # Load/save corpus and game state
├── context/
│   └── assembler.py             # Build GMBriefing from corpus + state
├── llm/
│   ├── client.py                # OpenAI-compatible LLM client wrapper
│   ├── model_config.py          # Model configuration and selection
│   └── parser.py                # Parse structured JSON from LLM output
├── game/
│   ├── loop.py                  # Main turn loop
│   └── display.py               # Console UI (Rich-based)
├── templates/
│   ├── ruling.j2                # System prompt for LLM Call 1
│   └── prose.j2                 # System prompt for LLM Call 2
├── tests/                       # pytest unit tests
├── scripts/
│   ├── validate.py              # Runtime validation tool (LLM-in-the-loop)
│   └── validate_adventure.py    # Static adventure corpus validation
└── adventures/
    └── bag-of-holding/          # Sample adventure (5 rooms)
        ├── corpus.json
        ├── hard-state.json
        └── soft-state.json
```

## Planned Extensions

The following are on the roadmap for future phases:

- **Combat phase**: Replace the current flag-based kill-or-be-killed placeholder with iterative rounds, HP tracking, damage rolls, and opposed checks.
- **Semantic search / RAG**: Augment the deterministic ID lookup with vector embeddings for larger adventure modules.
