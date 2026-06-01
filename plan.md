# My GM is AI (MGMAI) -- Project Plan

## Preamble

The goal of this project is to build an AI-driven Game Master (GM) that can run a **fixed, pre-written adventure** for a **single player**, with strict adherence to the module’s map, traps, items, and mechanics.

Since the advent of LLM chatbots, there has been an explosion of interest in using them for roleplaying (RP).  However, these RP systems have focused on generating non-player characters (NPCs) with emotional depth, open-ended narratives, and other aspects that are not core to the classic tabletop adventure module RP experience.  What we are after is natural-language interaction with a GM to run through a fun RP adventure, without human interaction.

At the same time, we don't want the system to be merely a natural language front end to an interactive fiction game, i.e. Zork with a nice parser.  The intention is for the AI to be aware of the adventure's narrative intent and adjudicate player actions against it, while maintaining mechanical fidelity. The player can attempt anything, and the GM decides (a) if it's possible here, (b) what mechanics apply, and (c) how to describe the outcome. We will aim to strike the right balance between AI creativity and fidelity -- the same struggle a human GM has to deal with, but magnified.

### Proposed high-level approach

We will set up a system that combines an LLM agent with a non-AI engine for game logic and game state.

Player Input
 -> combined with context, supplied to LLM
 -> LLM submits actions for engine validation/resolution
 -> LLM checks outcome, and generates final prose to player

The game state setup is done ahead of time, similar to a human GM preparing an adventure module before the play session.  This includes key conditions (e.g., the secret door in room 2 is opened, the lich on level 3 is killed), and the ways in which they depend on each other.

The system will also have a way to track "soft state", such as NPC attitudes. This will be handled by a combination of LLM and a memory store, with safeguards against confabulations by both the narrator and player.

For testing, we will set up one short sample adventure consisting of a hand written text adventure consisting of a 5 room dungeon with no combat. This will be written up as a single long planning document, and converted unto the appropriate schema (with validation) by LLM assistants. Much later, we will explore setting up a more general conversion pipeline, e.g. finding adventures from interactive fiction or tabletop modules with permissive licenses, and translating them.

Other scoping issues:

* We will fix on OpenAI compatible API calls. For development, we will probably use Deepseek v4 Flash for cost savings.
* The input/output will be console based, with no graphics. Much later, we will extend to allow playing via Telegram bot, website, etc.
* Combat will probably need a special mode, and will be handled in the next phase of development.

## Proposed Architecture

### Overview

The system is a loop of **two LLM calls sandwiching a deterministic engine**. Three data stores — one read-only corpus and two mutable state stores — feed into a Context Assembler that builds a structured "GM Briefing" each turn. The engine is the sole authority over game mechanics; the LLM interprets natural language and narrates outcomes but cannot alter mechanical state directly.

### Data Flow (per turn)

```
Player Input ───────────────────────────────────────────────────────┐
                                                                      │
1. Context Assembler ──────────────────────────────────────────────┐  │
   Reads: Module Corpus + Hard State + Soft State                  │  │
   Produces: GMBriefing (structured JSON context doc)              │  │
                                                                   │  │
2. LLM Call 1: Ruling ───────────────────────────────────────────┐ │  │
   Input:  GMBriefing + verbatim player input                    │ │  │
   Output: PlayerAction (action_type, target, detail)            │ │  │
           + proposed SoftStatePatch[] (optional)                │ │  │
                                                                 │ │  │
3. Engine Resolution ───────────────────────────────────────────┐│ │  │
   Input:  PlayerAction                                         ││ │  │
   Reads:  Module Corpus, current Hard State, Soft State        ││ │  │
   Writes: Hard State only (engine is exclusive writer)         ││ │  │
   Validates & applies SoftStatePatch[] (schema-gated)         ││ │  │
   Produces: EngineResult (outcome, state diffs, narration)    ││ │  │
                                                                ││ │  │
4. LLM Call 2: Prose ──────────────────────────────────────────┘│ │  │
   Input:  Verbatim chat log + GMBriefing + EngineResult        │ │  │
   Output: Natural-language narration (text to player)          │ │  │
                                                                 │ │  │
5. Player receives text output ─────────────────────────────────┘ │  │
   (loop repeats)                                                   │
```

If LLM Call 1 produces a malformed or impossible action, the system retries once with an error message injected into the prompt, then falls back to a generic failure narration (see Error Handling below).

### The Three Data Stores

**Module Corpus** (read-only). The digital equivalent of a printed adventure module. JSON loaded at startup, never modified during play. Contains:

- *Rooms* as graph nodes: each has a prose description, a list of entities present, available exits (with conditions, traversal effects, and hidden/reveal logic), defined interactions (with deterministic or probabilistic results), and on-enter events (one-shot or conditional).
- *Entities* of typed categories — `feature`, `npc`, `trap`, `item` — each with descriptive prose, tags for mechanical matching, and declarations of mutable state fields. NPCs carry `dialogue_guidelines` (personality, knowledge constraints, attitude-gated secrets) that are surfaced to the LLM. Monster-type NPCs carry `behavior` blocks defining encounter rules and outcomes.
- *Mechanics*: named encounters (rules evaluated top-to-bottom against player state; outcomes include death, flee, or probabilistic rolls) and win conditions (item–target combinations gated by location and inventory checks).
- *Game-over conditions*: terminal triggers with success/failure classification.

**Hard Game State** (engine-write, engine-read, LLM-read). Authoritative runtime state mutated exclusively by the engine during action resolution:

- `player`: current room ID, inventory (item IDs), hit points (nullable until combat is added).
- `flags`: global boolean toggles (doors opened, NPCs met, conditions triggered). Evaluated by the engine to gate exits, interactions, encounters.
- `entity_states`: per-entity mutable fields (e.g., `alive`, `fled`, `told_secret`), initialised from a startup file and validated against the entity's declared `state_fields` in the corpus.
- `turn_count`: monotonic counter incremented each turn.
- `game_over`: null during play; set to `{ type, trigger }` when a terminal condition fires.

**Soft Game State** (LLM-proposed, engine-validated, LLM-read). Narrative-oriented mutable state that the LLM can propose changes to, but only through a fixed patch schema that the engine validates before applying:

- `npc_attitudes`: a `hostile | neutral | friendly` triple per NPC. The engine enforces a one-step-per-turn transition limit and rejects attitude patches for dead NPCs.
- `environmental_notes`: freeform strings describing minor narrative changes (cleared webs, rearranged debris). The engine accepts any note that does not contradict a hard-state flag.
- `turn_history`: a structured log of completed turns (player input, resolved action, engine summary, flags changed, location after). The Context Assembler includes the last 5 entries in the GMBriefing; the full log is retained for future save/load and debugging.

### The Context Assembler and the GMBriefing

Each turn begins with the Context Assembler building a **GMBriefing** — a JSON document that distills the current world state into a compact, deterministic prompt block for LLM Call 1. It contains:

- The current room: ID, name, prose description, visible entities (filtered to those whose `alive` state is true), available exits (filtered by condition satisfaction; hidden exits omitted unless their reveal flag is set), and available interactions (filtered by condition).
- Player state: location, inventory (with entity descriptions and tags), active flags, a natural-language summary.
- NPC attitudes: current disposition of all NPCs encountered.
- Recent history: the last 5 entries from the structured `turn_history`, summarised.
- A win-condition hint (if the player has discovered relevant clues).
- The verbatim player input for this turn.

No vector database is required for the reference implementation. Lookups are deterministic by ID: the engine knows the player's room, so the Assembler fetches that room's data and enumerates present entities from the corpus.

### LLM Call 1: The Ruling

The first LLM call interprets the player's natural-language input and produces a **structured PlayerAction** in JSON. The LLM is prompted to classify the intent into one of eight action types:

| Action type | Target | Key validation |
|-------------|--------|----------------|
| `move` | exit ID | Exit exists in current room, conditions met |
| `examine` | entity ID (or room ID) | Entity present in current room |
| `interact` | interaction ID | Interaction defined in current room, conditions met |
| `talk` | NPC entity ID | NPC present and alive; dialogue is freeform |
| `use` | item ID + target ID | Item in inventory, target in room |
| `search` | (none) | Triggers all repeatable search interactions in room |
| `attack` | entity ID | Entity present with combat behavior defined |
| `wait` | (none) | Advances turn counter, no state change |

The PlayerAction includes a `detail` field (natural-language description of what the player attempts) and may include `proposed_soft_state_patches` — structured requests to update NPC attitudes or append environmental notes. The LLM cannot propose hard-state changes (inventory, flags, location); those are engine domain.

### The Engine

The engine is the system's deterministic backbone. It receives the PlayerAction and:

1. **Validates** the action against the current hard state and module corpus. Checks include: does the exit exist? is the entity present and alive? are conditions met? is the item in inventory?
2. **Resolves mechanics**: evaluates any conditions on exits/interactions, rolls dice for probabilistic checks, dispatches encounters (evaluating rules top-to-bottom against inventory and flags), applies `on_traverse` effects and `on_enter` events.
3. **Applies hard-state changes**: sets/clears flags, adds/removes inventory items, moves the player, updates entity states, increments the turn counter.
4. **Validates soft-state patches**: checks each proposed patch against the soft-state schema (entity exists, attitude step limit, no dead-NPC patches, reason is non-empty, no contradiction with hard state). Accepted patches are applied; rejected patches are returned with reasons.
5. **Checks for game-over**: if a death outcome or win condition fired, sets `hard_state.game_over`.
6. **Appends a turn log entry** to `soft_state.turn_history`.
7. **Produces an EngineResult** containing: success/failure, the room after resolution, a diff of all hard-state changes, applied/rejected soft patches, triggered narrations (canonical prose for key events), encounter outcomes, game-over state (if any), and warnings to LLM Call 2 about narrative constraints.

Combat in phase 1 is resolved as flag-based branching (no hit points, no iterative rounds): the spider encounter checks whether the player has a weapon tag and whether they are injured, then branches to flee/roll/death. Iterative combat will be added in a subsequent phase.

### LLM Call 2: Prose Narration

The second LLM call weaves the engine's mechanical outcome into natural prose for the player. It receives three inputs:

- The **verbatim chat log** (raw player–GM exchange, recent messages) for conversational continuity.
- The **GMBriefing** (same as LLM Call 1 received) for current world context.
- The **EngineResult** — the authoritative outcome.

Key constraints on LLM Call 2:

1. **Do not contradict the engine result.** If the engine says the spider fled, do not narrate it attacking. If `success: false`, narrate the action failing.
2. **Do not alter hard state.** Narration cannot add items, change rooms, set flags, or kill entities.
3. **Incorporate triggered narrations** where provided. These are canonical prose blocks for key events; the LLM's job is to weave them into natural conversation, not replace them.
4. **Respect hidden information.** Secret exits, NPC secrets gated behind attitude thresholds, and unrevealed mechanics must not be divulged.
5. **Respect game-over.** If the engine sets `game_over`, the LLM narrates the ending and stops.

### Chat History: Structured vs. Verbatim

A deliberate architectural choice: LLM Call 1 (the ruling) receives a **structured, non-verbatim** turn history — distilled summaries vetted by the engine — to prevent the ruling LLM from reinforcing its own or the player's hallucinations. LLM Call 2 (the prose) receives the **verbatim chat log** for conversational flavour, but is explicitly instructed to defer to the EngineResult when contradictions arise. This split is designed to balance narrative continuity against mechanical integrity.

### Error Handling

- **Malformed LLM output** (invalid JSON, unknown action type): the engine returns an error; the system re-invokes LLM Call 1 once with the error appended, then falls back to generic "you can't do that" narration.
- **Impossible action** (valid JSON, but target not present or conditions not met): the engine returns `success: false` with a reason; LLM Call 2 narrates the failure naturally.
- **Rejected soft-state patches**: appear in `EngineResult.soft_state_patches_rejected` with reasons; LLM Call 2 must not narrate the rejected change.

### Extensibility

- **New adventures**: authored as a Module Corpus JSON file and paired hard/soft state files. No code changes needed for adventures that use the existing set of entity types, action types, and mechanics.
- **New action types**: register in the engine's action parser and add the prompt instruction to LLM Call 1. New soft-state fields can be added to the patch schema with engine-side validation rules.
- **Combat phase**: the `attack` action will be revised to support iterative rounds, HP tracking, damage rolls, and opposed checks. The current flag-based branching is a phase-1 placeholder.
- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

### World Model

The internal world model is built from first principles around tabletop concepts, not interactive-fiction parsers:

* Rooms are nodes in a graph.
* Entities (items, NPCs, features, traps, exits) are typed objects with state, linked to room nodes.
* Actions are natural-language inputs parsed by the LLM into structured intent, then resolved by the engine against the graph and rules.

Incidentally, there are precedents for AI interaction with interactive fiction through the TextWorld and Jericho projects. However, these are treated as references for natural-language action parsing only; we will not adopt their structured action grammars.
