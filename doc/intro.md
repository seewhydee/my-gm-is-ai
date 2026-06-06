# My GM is AI — Architecture Guide

## Project Goals

An AI-driven Game Master (GM) for single-player RPGs. The objective: replicate the tabletop RPG experience without needing friends.

Unlike freeform AI roleplay chatbots, this AI GM is **not** optimised for crafting naturalistic interlocutors with emotional depth, nor can it create open-ended adventures. Instead, the AI GM runs a **pre-generated adventure module faithfully**. You, the player, can attempt anything, and the GM decides (a) if it's possible, (b) what rules apply, and (c) how to describe what happens. Like a human GM, the AI GM aims to strike a balance between creativity and rules adherence.

### Phase 1 scope

- OpenAI-compatible API calls (Deepseek, etc.)
- Console-based input/output, no graphics
- Kill-or-be-killed combat with no special mechanics (HP, rounds, etc.)
- No player stats

## Overall Approach

The system is built around a **single, invariant design principle**: the LLM drives narration and interpretation, but a deterministic engine has final authority over game mechanics.

The core insight is that LLMs are excellent at natural-language understanding and prose generation, but unreliable for rule enforcement and state tracking. By splitting these responsibilities, we get the best of both worlds:

- The **LLM** interprets player intent, constructs structured actions, and weaves outcomes into compelling prose.
- The **engine** validates actions against the rules, resolves mechanics deterministically (dice rolls, condition checks, state mutations), and constrains the LLM's narrative output to prevent contradictions and hallucinations.

This architecture is analogous to a human GM who knows the rules intimately: the engine is the rulebook, the LLM is the voice.

## Architecture

The system runs a per-turn loop of **two LLM calls sandwiching a deterministic engine**, with three data stores feeding a Context Assembler that builds the LLM's input each turn.

### Per-turn data flow

```
Player Input
      │
      ▼
┌─────────────────┐
│ Context Assembler│ ◄── Corpus + Hard State + Soft State
└────────┬────────┘
         │ GMBriefing (structured JSON)
         ▼
┌─────────────────┐
│   LLM Call 1    │  (low temperature — ruling)
│   "What does    │
│    the player   │  Output: PlayerAction (machine-readable)
│    attempt?"    │         + optional SoftStatePatch[]
└────────┬────────┘
         │ PlayerAction
         ▼
┌─────────────────┐
│  Engine (rule-  │  Reads: Corpus + Hard State + Soft State
│  book, dice,    │  Writes: Hard State only
│  state machine) │  Validates & applies SoftStatePatch[]
└────────┬────────┘
         │ EngineResult (outcome, state diffs, narration)
         ▼
┌─────────────────┐
│   LLM Call 2    │  (moderate temperature — prose)
│   "How does the │
│    world react?"│  Output: natural-language narration
│                  │       + optional knowledge_tags (NPC revelations)
└────────┬────────┘  │       + optional attitude_changes
         │           ▼
         │   ┌─────────────────┐
         │   │ Post-validation  │  Engine validates knowledge_tags
         │   │      (step 4.5)  │  and attitude_changes from Call 2
         │   └────────┬────────┘
         ▼            ▼
   Game state saved   Player receives narration
```

### The three data stores

**Module Corpus** (read-only). The digital equivalent of a printed adventure module — a JSON file loaded at startup, never modified during play. Contains rooms (as graph nodes), entities (player, NPCs, features, traps, items), interactions (named actions gated by conditions), and mechanics (win/lose rules, dice checks).

**Hard Game State** (engine-authoritative). Mutable runtime state written exclusively by the engine. Tracks player location, inventory, flags, room/entity states, turn count, and game-over conditions. The LLM reads it via the GMBriefing but cannot propose changes directly.

**Soft Game State** (LLM-proposed, engine-validated). Narrative state that the LLM can propose changes to — soft inventory (non-unique items like "a rock"), room notes, entity notes, NPC attitudes, dialogue state, turn history, and NPC revelations. All proposals go through a strict patch schema; the engine validates and applies.

### The Context Assembler and GMBriefing

Each turn, the Context Assembler builds a **GMBriefing** — a JSON document that compresses the current world into a compact prompt block for the ruling LLM. It contains:

- **Global setting**: one or two brief sentences about the adventure.
- **Current room**: ID, name, prose description, visible entities with state, available exits, available interactions.
- **Player state**: location, hard inventory, soft inventory, active flags, entity notes.
- **Recent history**: the last 5 turns, summarised.
- **NPC revelations**: topics NPCs have revealed to the player so far.
- **Dialogue context** (when in conversation): active NPC identity, attitude, dialogue guidelines, recent exchanges, topics discussed — all omitted when not in dialogue.
- **Player input**: the verbatim input for this turn.

No vector database — lookups are deterministic by ID.

### Player action types

LLM Call 1 maps the player's natural-language input into exactly one of seven structured action types:

| Type | Purpose | Key fields |
|------|---------|------------|
| `move` | Travel to an adjacent room via an exit | `target` (exit ID), optional `style` (crawl, etc.) |
| `examine` | Look at a room, entity, or soft item | `target`, optional `rigorous` (deep search), optional `using` |
| `interact` | Perform a named interaction on an entity | `target`, `interaction_id`, optional `using` |
| `talk` | Start or continue dialogue with an NPC | `target` (NPC ID), optional `utterance`, optional `ends_dialogue` |
| `transfer` | Give/take items between player and entity/room | `target`, `given_items`[], `taken_items`[] |
| `wait` | Pass time, catch-all for below-threshold actions | `detail` describing intent |
| `ooc_discussion` | Out-of-character question to the GM | `detail` with the question |

Every action includes a `detail` field (natural-language description), optional `proposed_soft_state_patches`, and optional `follow_up` (for chained actions — see below).

Only one action per turn. For multi-step inputs ("I pick up the key and unlock the door"), the LLM constructs the first action and stores the remainder in the `follow_up` field; the engine re-injects the follow-up as a new turn automatically.

### LLM Call 1: Ruling (low temperature)

Receives the GMBriefing + verbatim player input. Produces a structured PlayerAction in JSON. Cannot propose hard-state changes (those are the engine's domain). If the LLM encounters an impossible or out-of-scope player request, it should produce a `wait` action and use the `detail` field to explain why.

### Engine resolution

The engine is the system's source of truth. It receives the PlayerAction and:

1. **Validates** the action against the hard state and corpus (does the exit exist? is the entity alive? are conditions met?).
2. **Resolves mechanics**: evaluates conditions, rolls dice for checks, dispatches encounters, applies traversal effects and on-enter events.
3. **Applies hard-state changes**: flags, inventory, location, entity states.
4. **Validates soft-state patches**: accepts/rejects with reasons.
5. **Checks for game-over** conditions.
6. **Produces an EngineResult** containing the full outcome: success/failure, the room after resolution, a diff of all changes, triggered narrations (canonical prose for key events), encounter outcomes, roll details, warnings, and chain-action handling info.

### LLM Call 2: Prose narration (moderate temperature)

Receives the GMBriefing, PlayerAction, EngineResult, and a verbatim chat log. Weaves the outcome into natural prose. Key constraints:

1. **Do not contradict the engine result** — if the engine says the spider fled, do not narrate it attacking.
2. **Do not invent game state** — no adding items, changing rooms, or killing entities.
3. **Incorporate triggered narrations** — weave canonical prose blocks into the narrative, don't replace them.
4. **Respect hidden information** — secret exits, gated NPC knowledge, and unrevealed mechanics must not be divulged.
5. **Respect game-over** — if `game_over` is set, narrate the ending and stop.

Optionally, the LLM may also propose `knowledge_tags` (which topic IDs an NPC revealed) and `attitude_changes` (NPC attitude shifts from this turn's events). Both are engine-validated in step 4.5 before being applied.

### Chained actions

When a player's input describes multiple steps, the LLM produces the first action and stores the remainder as `follow_up`. The engine then re-injects the follow-up as an automatic next turn without waiting for the player. The chain terminates if any step fails validation. Max chain depth is a defined constant to prevent infloops.

### Dialogue mode

When the player starts talking to an NPC (`talk` action), the system enters dialogue mode. The GMBriefing is enriched with a `dialogue_context` block containing the NPC's personality guidelines, recent exchanges, and discussed topics — giving the ruling LLM enough context to parse inputs that mix action narration with in-character speech.

Dialogue ends when: the player moves rooms, the NPC dies/flees, the player sends `talk` with `ends_dialogue: true`, or 3+ turns pass without a `talk` action.

### Dialogue vs. structured history

A deliberate design choice: LLM Call 1 (ruling) receives **structured, non-verbatim** turn history to prevent it from reinforcing hallucinations. The one exception is Dialogue Mode, where a scoped, engine-validated block of verbatim conversation with the active NPC is injected. LLM Call 2 (prose) receives the **verbatim chat log** for conversational continuity, but is instructed to defer to the engine when contradictions arise.

### Error handling

- **Malformed LLM output** (invalid JSON, unknown action): retry once with error in prompt, then fall back to generic narration.
- **Impossible action** (valid JSON but engine rejects): `success: false` with a reason; narration describes the failure.
- **Rejected soft patches** and **rejected attitude changes**: listed in the EngineResult; narrator must not narrate the rejected change.

### Serialization

After each non-chain turn, the system saves hard state + soft state as a JSON file. The GMBriefing is reconstructed from scratch on load — no LLM context is persisted.

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

## Human Validation

The project includes two validation tools in `scripts/`:
- **`validate_adventure.py`** — static structural checks on adventure corpus files (no LLM required).
- **`validate.py`** — runtime validation with full LLM pipeline, logging all intermediate artifacts (GMBriefing, raw LLM outputs, engine results, narration).

See [validation.md](validation.md) for the full validation plan covering sequence files, log review procedures, and defect tracking.

## Planned Extensions

The following are on the roadmap for future phases. Detailed design documents are linked below.

- **Player stats** (player-stats.md): Add ability scores (STR/DEX/CON/INT/WIS/CHA), stat-gated conditions and checks, and a resolution-system abstraction to decouple adventures from specific RPG editions.
- **Combat phase**: Replace the current flag-based kill-or-be-killed placeholder with iterative rounds, HP tracking, damage rolls, and opposed checks.
- **Semantic search / RAG**: Augment the deterministic ID lookup with vector embeddings for larger adventure modules.
- **Multi-NPC conversations**: Extend dialogue mode to handle simultaneous conversations with multiple NPCs.
