# My GM is AI — Architecture Guide

The objective of this software is to implement an AI-driven Game Master (GM) that can replicate key aspects of the tabletop RPG experience.  It attempts to function like a human GM running a pre-written adventure module: the GM knows and follows the rules, but also accommodates the player's intentions and provides customized narrative flavor.

The system uses a large language model (LLM) to drive interpretation and narration, and a deterministic engine to impose game mechanics.  LLMs are excellent at natural-language understanding and prose generation, but unreliable for rule enforcement and state tracking.  By splitting these responsibilities, we hope to get the best of both worlds: the LLM interprets player intent, constructs structured actions, and weaves outcomes into compelling prose; the engine validates actions against the rules, resolves mechanics, and constrains the narrative output to the actual game state.

## Architecture

Each turn, we run two LLM calls sandwiching a coded engine.  The LLM calls and engine are informed by three data stores that track the game state.

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

**Module Corpus** (read-only).  This is loaded at startup and never modified during play, serving as the equivalent of a printed adventure module.  It specifies rooms (as graph nodes), entities (player, NPCs, features, items), interactions (named actions gated by conditions), and mechanics (win/lose rules, dice checks).

**Hard Game State** (engine-authoritative).  This contains mutable runtime state and is managed exclusively by the engine.  It tracks player location, inventory, flags, room/entity states (including per-NPC attitude values), turn count, and game-over conditions.  The LLM reads part of it via the GMBriefing, but cannot alter it directly.

**Soft Game State** (LLM-proposed, engine-validated).  This contains narrative elements that the LLM can propose changes to: soft inventory (non-unique items like "a rock"), room notes, entity notes, dialogue state, turn history, and player knowledge (topics learned through NPC dialogue, interactions, examination, etc.).  All proposals go through a patch schema, which the engine validates and applies.

### The Context Assembler and GMBriefing

Each turn, the Context Assembler builds a **GMBriefing** — a JSON document describing the current world state to the ruling LLM, containing:

- **Global setting**: a few introductory sentences about the adventure.
- **Current room**: ID, name, prose description, visible entities, available exits, available interactions.
- **Player state**: location, hard inventory, soft inventory, active flags.
- **Recent history**: summary of the last 5 turns.
- **Player knowledge topics**: topic IDs the player has learned about (through dialogue, interactions, examination, etc.).
- **Dialogue context** (when in conversation): active NPC identity, attitude, dialogue guidelines, recent exchanges, topics discussed.
- **Player input**: the verbatim input for this turn.

In the future, we might turn to a vector database, but for now lookups are deterministic by ID.

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

Only one action occurs per turn.  Multi-step inputs ("I pick up the key and unlock the door") are handled by constructing **chained actions**.  The LLM extracts the first action ("I pick up the key") and stores the rest in the `follow_up` field ("unlock the door").  After the first action is processed, the engine injects the follow-up as a new turn, *without waiting for further player input*.  This follow-up can itself be broken up, thereby extending the chain.  The chain terminates if any step fails validation, or if the length exceeds a maximum value.

### Engine resolution

The engine is the system's source of truth.  It receives the PlayerAction and:

1. **Validates** the action (e.g., is the entity alive? does the item exist?).
2. **Resolves mechanics**: evaluates conditions, rolls dice for checks, dispatches encounters, etc.
3. **Applies hard-state changes**: flags, inventory, location, entity states.
4. **Validates soft-state patches**: accepts/rejects with reasons.
5. **Checks for game-over**.
6. **Produces an EngineResult** containing the full outcome: stat check success/failure, a diff of state changes, etc.

### LLM Call 2: Prose narration (moderate temperature)

LLM Call 2 runs at a moderately high temperature.  It receives the GMBriefing, PlayerAction, EngineResult, and a verbatim chat log.  Its task is to weave the outcome into natural prose, subject to these constraints:

1. **Do not contradict the engine result** — if the engine says the spider fled, do not narrate it attacking.
2. **Do not invent game state** — no adding items, changing rooms, or killing entities.
3. **Incorporate triggered narrations** — weave canonical prose blocks into the narrative, don't replace them.
4. **Respect hidden information** — secret exits, gated NPC knowledge, and unrevealed mechanics must not be divulged.
5. **Respect game-over** — if `game_over` is set, narrate the ending and stop.

Optionally, the LLM may also propose `knowledge_tags` (which topic IDs an NPC revealed) and `attitude_changes` (NPC attitude shifts from this turn's events).  Both are checked against corpus-defined constraints in the post-validation step.  See [npcs.md](npcs.md) for details.

### Dialogue mode

When the player starts talking to an NPC (`talk` action), the system enters dialogue mode.  The GMBriefing is then enriched with a `dialogue_context` block specifying the NPC's personality guidelines, current attitude, recent exchanges, discussed topics, and topics already revealed to the player.

Dialogue ends when the player moves rooms (away from the NPC), the NPC dies/flees, the player terminates the conversation (a `talk` action with `ends_dialogue: true`), or 3+ turns pass without a `talk` action.  An exception is made for **follower NPCs** (NPCs with `entity_states[].following == true`), who travel with the player between rooms and remain in active dialogue regardless of room changes.  On exit, the conversation is archived as an `entity_note` on the NPC — LLM Call 2 may provide a rich `conversation_note`, otherwise the engine writes a minimal fallback.  Any `on_dialogue_exit` side effects (set_flag, set_entity_state) from the NPC's dialogue guidelines are applied.

### Error handling

- **Malformed LLM output** (invalid JSON, unknown action): retry once with error in prompt, then fall back to generic narration.
- **Impossible action** (valid JSON but engine rejects): `success: false` with a reason; narration describes the failure.
- **Rejected soft patches** and **rejected attitude changes**: listed in the EngineResult; narration should not discuss the rejected change.

### Serialization

After each non-chain turn, the system saves hard state + soft state as a JSON file.  The GMBriefing is reconstructed from scratch on load; no LLM context is persisted.

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

- **Combat phase**: Replace the placeholder stat check-based combat resolutions with iterative rounds, HP tracking, damage rolls, etc.
- **Semantic search**: Explore augmenting the deterministic ID lookup with vector embeddings for larger adventure modules.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
