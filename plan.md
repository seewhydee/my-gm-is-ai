# My GM is AI (MGMAI) -- Project Plan

## Preamble

The goal of this project is to build an AI-driven Game Master (GM) that can run a **fixed, pre-written adventure** for a **single player**, with strict adherence to the module’s map and mechanics.

Since the advent of LLM chatbots, there has been an explosion of interest in using them for roleplaying (RP).  However, these RP systems have focused on generating non-player characters (NPCs) with emotional depth, open-ended narratives, and other aspects that are not core to the classic tabletop adventure module RP experience.  What we are after is natural-language interaction with a GM to run through a fun RP adventure, without human interaction.

At the same time, we don't want the system to be merely a natural language front end to an interactive fiction game, i.e. Zork with a nice parser.  The intention is for the AI to be aware of the adventure's narrative intent and adjudicate player actions against it, while maintaining mechanical fidelity. The player can attempt anything, and the GM decides (a) if it's possible here, (b) what mechanics apply, and (c) how to describe the outcome. We will aim to strike the right balance between AI creativity and fidelity -- the same struggle a human GM has to deal with, but magnified.

### Proposed high-level approach

We will set up a system that combines an LLM agent with a non-AI engine for game logic and game state.

Player Input
 -> combined with context, supplied to LLM
 -> LLM adjudicates player intent and submits a structured action
 -> Engine validates and resolves the action
 -> LLM checks outcome, and generates final prose to player

The game state setup is done ahead of time, similar to a human GM preparing an adventure module before the play session -- we will not try to handle freeform adventures.  The game engine rigorously tracks "hard state" conditions (e.g., the secret door in room 2 is opened, the lich on level 3 is killed).  "Soft state" like NPC attitudes is tracked through a combination of LLM and a memory store, with safeguards against confabulations by both the narrator and player.

For testing, we will set up one short sample adventure consisting of a hand written text adventure consisting of a 5 room dungeon with no combat. This will be written up as a single long planning document, and converted unto the appropriate schema (with validation) by LLM assistants. Much later, we will explore setting up a more general conversion pipeline, e.g. finding adventures from interactive fiction or tabletop modules with permissive licenses, and translating them.

During the initial phase of development, we will limit the scope as follows:

* We will fix on OpenAI compatible API calls.
* Input/output will be console based, with no graphics.
* Combat will have kill-or-be-killed resolutions with no special mechanics.
* Similarly, no player stats for now.

## Proposed Architecture

### Overview

The system is a loop of **two LLM calls sandwiching a deterministic engine**. Three data stores — one read-only corpus and two mutable state stores — feed into a Context Assembler that builds a structured "GM Briefing" each turn. The engine has authority over game mechanics; the LLM interprets natural language and narrates outcomes but cannot alter mechanical state directly.

### Data Flow (per turn)

```
Player Input

1. Context Assembler
   Reads: Module Corpus + Hard State + Soft State
   Produces: GMBriefing (structured JSON context doc)

2. LLM Call 1: Ruling
   LLM temperature setting low
   Input:  GMBriefing + verbatim player input
   Output: PlayerAction (action_type, target, detail)
            + proposed SoftStatePatch[] (optional; room notes, entity notes,
              soft inventory — see Soft Game State below)

3. Engine Resolution
   Input:  PlayerAction
   Reads:  Module Corpus, current Hard State, Soft State
   Writes: Hard State only (engine is exclusive writer)
   Validates & applies SoftStatePatch[] (schema-gated; does NOT handle
     NPC attitude changes, which are dealt with in Call 2)
   Produces: EngineResult (outcome, state diffs, narration)

4. LLM Call 2: Prose
   LLM temperature setting moderate
   Input:  Verbatim chat log + GMBriefing + EngineResult
   Output: Natural-language narration (text to player)
         +  knowledge_tags (optional; topics the NPC revealed)
         +  attitude_changes (optional; attitude shifts for NPCs affected
            by this turn's events)

4.5 (optional) Engine Post-Validation
   Triggered if: step 4 produced knowledge_tags or attitude_changes
   Input:  knowledge_tags + attitude_changes from LLM Call 2
   Reads:  Module Corpus (will_reveal entries, attitude_limits)
   Validates: each knowledge_tag against will_reveal conditions;
              each attitude change against attitude_limits
              (bounds, step limits, alive check, reason required)
   Applies: will_reveal side effects (set_flag, set_entity_state);
            validated attitude changes to soft_state.npc_attitudes
   Records: revealed topics in soft_state.npc_revelations
   Produces: a corrected EngineResult that includes the 
     changes to knowledge_tags or attitude_changes (if validated)

5. Game state saved
   Player receives text output
(loop repeats)
```

If LLM Call 1 produces a malformed or impossible action, the system retries once with an error message injected into the prompt, then falls back to a generic failure narration (see Error Handling below).

### The Three Data Stores

**Module Corpus** (read-only). The digital equivalent of a printed adventure module. JSON loaded at startup, never modified during play. Contains:

- *Rooms* as graph nodes.  Each has a prose description, a list of entities present, available exits (with conditions, traversal effects, and hidden/reveal logic), special interactions, and on-enter events (one-shot or conditional).
- *Entities* have typed categories — `player`, `feature`, `npc`, `trap`, `item`. Each has descriptive prose, special interactions, and declarations of mutable state fields. NPCs carry `dialogue_guidelines` (personality, knowledge constraints, attitude-gated secrets) that are surfaced to the LLM. Monster-type NPCs carry `behavior` blocks defining encounter rules and outcomes.
- *Interactions* are named interactions that can be performed by or on entities or rooms.
  Each has a parameter signature (target, using, etc.).
- *Mechanics* are named rules involving aspects of game state not tied to specific rooms or entities.  These includes game-over conditions (win/lose).

**Hard Game State** (engine-write, engine-read, LLM-read). This stores authoritative plot-relevant runtime state, and is mutated exclusively by the engine during action resolution. Contains:

- `player`: current room ID, hard inventory (item IDs), etc.
- `flags`: global boolean toggles not tied to specific rooms or entities (e.g., night time).
- `room_states`: per-room mutable fields (e.g. `visited`).
- `entity_states`: per-entity mutable fields (e.g., `alive`, `told_secret`), initialised from a startup file and validated against the entity's declared `state_fields` in the corpus.
- `turn_count`: monotonic counter incremented each turn.
- `game_over`: null during play; set to `{ type, trigger }` when a terminal condition fires.

**Soft Game State** (LLM-proposed, engine-validated, LLM-read). Narrative-oriented mutable state that the LLM can propose changes to, but only through a fixed patch schema that the engine validates before applying:

- `soft_inventory`: inventory items lacking item IDs (e.g., rocks picked up from the ground). Soft items are further described below.
- `room_notes`: freeform strings describing non-plot-relevant changes to rooms (e.g., cleared webs, rearranged debris).
- `entity_notes`: freeform strings describing non-plot-relevant changes to entities (e.g., door marked with chalk).
- `npc_attitudes`: an integer per NPC (positive attitude is > 0). Proposed by LLM Call 2 via `attitude_changes` and validated by the engine post-resolution against corpus-specified attitude limits (bounds, step limits, alive check). The engine rejects out-of-range or dead-NPC proposals.
- `turn_history`: a structured log of completed turns (player input, resolved action, engine summary, flags changed, location after). The Context Assembler includes the last 5 entries in the GMBriefing; the full log is retained for future save/load and debugging.  For `ooc_discussion` player actions, the player inputs are included but do not count toward the entry maximum (the GMBriefing should be unchanged over the course of such "actions").
- `dialogue_state`: tracks active NPC conversations — which NPC the player is talking to, a scrolled window of the last 10 verbatim exchanges, and a set of topics discussed. When active, the Context Assembler injects a `dialogue_context` block into the GMBriefing so that LLM Call 1 has enough conversational awareness to parse inputs that mix action narration with in-character speech (see Dialogue Mode below).
- `npc_revelations`: records which `will_reveal` topics each NPC has revealed to the player (`{ "<npc_entity_id>": ["<topic_id>", ...] }`). Populated by the engine during post-validation of LLM Call 2's `knowledge_tags`. The Context Assembler includes these in the GMBriefing so LLM Call 1 knows what the player has learned.

### The Context Assembler and GMBriefing

Each turn begins with the Context Assembler building a **GMBriefing** — a JSON document distilling the current world state into a compact prompt block for LLM Call 1. It contains:

- Global setting: one or two brief sentences about the adventure setting.

- The current room: ID, name, prose description, entities present with their state and entity notes (hidden entities omitted), available exits and their state (hidden exits omitted), and available interactions.

- Player state: hard inventory, soft inventory, active flags, entity notes.

- Recent history: the last 5 entries from the structured `turn_history`, summarised.

- NPC revelations: topics revealed by NPCs so far, drawn from `soft_state.npc_revelations`. Each revelation includes its description so LLM Call 1 knows what the player has learned.

- Dialogue context: when dialogue mode is active, the NPC's identity, current attitude, full dialogue_guidelines, recent exchanges, topics discussed, and any topics already revealed to the player. When inactive, omitted.

- The verbatim player input *for this turn only*.
  Or, for chained actions (see below), the original verbatim player input along with a clear indication of where we are in the chain.

No vector database is required for the reference implementation. Lookups are deterministic by ID: the engine knows the player's room, so the Assembler fetches that room's data and enumerates present entities from the corpus.

### LLM Call 1

The first LLM call interprets the player's natural-language input.  It cannot propose hard-state changes (inventory, flags, location); those are engine domain.  Its main responsibility is to produce a structured **PlayerAction** in JSON.  This falls into one of these types:

 `move`, `examine`, `interact`, `talk`, `transfer`, `wait`, `ooc_discussion`

Only one PlayerAction can be submitted per turn.  If the player's input is a chained action best decribed by multiple PlayerActions, the LLM is instructed to break off the first (or next) piece of the action chain, construct the PlayerAction from that, and indicate the rest of the chained action using the `follow_up` field (see below).  The different PlayerActions are described below:

- `move` must specify a room exit ID, which should be a valid (i.e., accessible and non-hidden) exit from the current room.
  It optionally includes a `style` field to specify special movement methods (e.g. crawling).

* `examine` must specify a valid entity ID, room ID, or soft item name.
  It optionally includes a `rigorous` field to flag in-depth searches (thus, a schema may specify that only a rigorous search reveals a secret).
  It optionally includes a `using` field to specify a valid entity ID or soft item with which to perform the search.

* `interact` must specify a valid entity ID or soft item (a target), plus an interaction ID (a specific plot-relevant way to interact with something).
  Interactions include generic ones like `attack`, `take`, plus special corpus-defined ones like `recharge`.
  It optionally includes a `using` field to specify a valid entity ID or soft item enabling the interaction (e.g., attack goblin using sword).

* `talk` must specify one NPC entity ID.
  It optionally includes an `utterance` field (verbatim player speech) and/or an `ends_dialogue` flag. See the Dialogue section below.

* `transfer` must specify one entity ID (usually an NPC or container), or room ID
  (e.g., for dropping items on the floor).
  It optionally includes a `given_items`: a list of item IDs or soft items.
  It optionally includes a `taken_items`: a list of item IDs or soft items.
  At least one should be non-empty.

* `wait` advances the turn counter.  This serves as a catch-all category that includes actions falling below the plot significance threshold, as well as player introspection (e.g., looking through inventory).  The `detail` field will be used to instruct the narrator how to react (e.g., reporting on the contents of inventory).

* `ooc_discussion` is a special out-of-character discussion with the GM that, during the engine phase, will not advance the turn counter and will not change the hard state or soft state.  The system will instead skip to the narrator (LLM 2).  This can be used by players to ask the GM for clarifications, etc.

Every PlayerAction, regardless of type includes the following:

- `detail` field containing a natural-language description of what the player attempts
- (optional) a `proposed_soft_state_patches` field specifying structured requests to update soft state (e.g., noting environmental changes, adding soft items to inventory). Note: attitude shifts are proposed in LLM Call 2, not here.
- (optional) a `follow_up` field specifying, in natural language, the rest of a chained action yet to be performed (e.g., for "I pick up the key and unlock the door", the follow up could be "Unlock the door with the key")

When constructing PlayerActions involving soft items, the LLM is additionally instructed to adjudicate whether the action is both physically plausible (e.g., no "I lift up a wall and smash it against the door") and consistent with the GMBriefing.  If it thinks not, it should not construct a bogus PlayerAction (which is risky -- the schema might not catch everything); it should construct some other PlayerAction, or fall back on `wait` and use the `detail` field to convey the problem to LLM Call 2.

#### Dialogue

When `soft_state.dialogue_state.active_npc` is non-null, the Context Assembler enriches the GMBriefing with a `dialogue_context` block containing:

- The active NPC's identity, current attitude, and full `dialogue_guidelines` from the corpus.
- Up to 5 of the most recent verbatim exchanges from `conversation_log` (player utterance + NPC response summary per exchange).
- The set of `topics_discussed` so far.

This scoped, purpose-built injection gives the ruling LLM enough conversational awareness to correctly classify inputs that intermix action narration with in-character speech (e.g., *"I pull up a cork to sit on and ask Korbar, 'How long have you been down here?'"*). The structured, non-verbatim turn history for all other game-state context remains unchanged; the hallucination firewall is preserved for mechanical state, and only ongoing dialogue gains verbatim context.

Dialogue mode exits automatically when the player moves rooms, the NPC dies/flees, a `talk` action carries `ends_dialogue: true`, or the engine detects a stall (3+ turns without a `talk` action, not including `ooc_disussion` actions, while in dialogue mode). On exit, a summary of the conversation log is archived in the NPC's `entity_notes`, and `dialogue_state` resets to `null`.

#### Soft items

We want to avoid the immersion-breaking "you see a rock here" trope. If a player is in a rocky cavern and wants to pick up a rock to place on a pressure plate, no human GM would object. However, we don't want to let players pick up a bogus Wand of Wishing from the floor.

For now, our patchwork solution is to pre-populate each room and entity, at corpus generation time, with an LLM-generated list of plausible nondescript items that can be found in/on the room or entity. These **soft items** will not have unique item IDs, but will be identified by their general name (e.g. rock). They can be put into player inventories, and can be used in interactions if so specified by the schema.

### The Engine

The engine is the system's source of ground truth. It receives the PlayerAction and does the following:

0. No-op if the PlayerAction is `ooc_discussion`; skip straight to narration.

1. **Validate** action against the current hard state and module corpus.
   Checks include: does the exit exist? is the entity present and alive?
   are conditions met? is the item in inventory? For chained actions, check
   if the chain has surpassed some max length (a defined constant); if so,
   terminate to protect against an LLM- or mechanics-induced infloop.
2. **Resolve mechanics**: evaluate conditions on exits/interactions,
   roll dice for probabilistic checks, dispatch encounters,
   apply `on_traverse` effects and `on_enter` events.
3. **Apply hard-state changes**: set/clear flags, move inventory items,
   move the player, update entity states.
4. **Validate soft-state patches**: check each proposed patch against
   soft-state schema (entity exists, soft item is present, patch is
   non-contradictory with hard state). Accepted patches are applied;
   rejected patches are returned with reasons.
   (Note: NPC attitude changes are validated later, not here.
5. **Check for game-over**: if a death or win condition is fired,
   set `hard_state.game_over`.
6. **Increment the turn counter** and append a turn log entry to 
   `soft_state.turn_history`.
7. **Produce an EngineResult** containing:
   - success/failure
   - the room after resolution
   - a diff of all hard-state changes
   - applied/rejected soft patches
   - triggered narrations (canonical prose for key events)
   - encounter outcomes
   - game-over state (if any)
   - warnings to LLM Call 2 about narrative constraints
   - attitude limits of any NPCs present
   - if in dialogue mode, NPC's `will_reveal_readiness` topics
   - chain action handling info (if any)

For chain actions, any validation failure, or rejection of hard-state or soft-state, will automatically terminate the chain.  The EngineResult will explicitly note the reason for the cancellation, and `follow_up` that was discarded.

### LLM Call 2: Prose Narration

The second LLM call weaves the engine's mechanical outcome into natural prose for the player. It receives the following inputs:

- A corpus-specified short (1-2 sentence) briefing about the setting, the tone of the adventure, etc.
- The **verbatim chat log** (raw player–GM exchange, recent messages) for conversational continuity.
- The **GMBriefing** (same as LLM Call 1 received) for current world context.
- The **PlayerAction** submitted by LLM Call 1.
- The **EngineResult** — the authoritative outcome (previous section)

In addition to natural-language prose narration, if the player action was anything other than `ooc_discussion`, LLM Call 2 may output two optional structured blocks for the engine to post-validate:

- `knowledge_tags`: specifies the `will_reveal` topic IDs a present NPC revealed in dialogue. The engine will validate conditions and apply any `set_flag` / `set_entity_state` side effects. Topics with unmet conditions are silently rejected.
- `attitude_changes`: proposed attitude shifts for any NPC during this turn, whether through dialogue, or other events (gift-giving, attacking, etc) based on the EngineResult and chat log.  Uses the format `{ "<npc_id>": { "old_value": N, "new_value": M, "reason": "..." } }`. The engine validates against the NPC's `attitude_limits` (bounds, step limits, alive check).

Key constraints on LLM Call 2:

1. **Do not contradict the engine result.** If the engine says the spider fled, do not narrate it attacking. If `success: false`, narrate the action failing.
2. **Do not contradict world state.** Narration cannot add items, change rooms, set flags, or kill entities. Hard-state changes come exclusively from the engine.
3. **Incorporate triggered narrations** where provided. These are canonical prose blocks for key events; the LLM's job is to weave them into natural conversation, not replace them.
4. **Respect hidden information.** Secret exits, NPC secrets gated behind attitude thresholds, and unrevealed mechanics must not be divulged. Use the `will_reveal_readiness` field — only tag topics with `conditions_met: true` as revealed.
5. **Respect game-over.** If the engine sets `game_over`, the LLM narrates the ending and stops.
6. **Propose attitude changes naturally.** After narrating the turn's events, consider which NPCs' dispositions shifted and propose `attitude_changes` accordingly. Never contradict the attitude limits listed in the EngineResult.

If in an ongoing (unterminated) chained action, LLM Call 2 will be instructed to be terse, because the system is proceeding back into the next follow-up action without player interaction.

#### Chat History: Structured vs. Verbatim

A deliberate architectural choice: LLM Call 1 (the ruling) receives a **structured, non-verbatim** turn history — distilled summaries vetted by the engine — to prevent the ruling LLM from reinforcing its own or the player's hallucinations. The one exception is Dialogue Mode: when the player is in active conversation with an NPC, a scoped, engine-validated `dialogue_context` block (verbatim exchanges with that NPC only) is injected into the GMBriefing so the ruling LLM can parse mixed action/dialogue inputs. All other game-state context — room descriptions, inventory, flags, encounter outcomes — remains structured and non-verbatim.

LLM Call 2 (the prose) receives the **verbatim chat log** for conversational flavour, but is explicitly instructed to defer to the EngineResult when contradictions arise. This split is designed to balance narrative continuity against mechanical integrity.

### Serialization

Before returning control to the player, the system saves a copy of the hard state, soft state, and the prose emitted by LLM Call 2 (latest narration). In the middle of a chained action, this step is skipped since the player does not receive control.

On load, the Context Assembler reconstructs the GMBriefing from scratch; no LLM context is persisted. The player receives a brief recap generated by LLM Call 2 from the loaded state.

### Error Handling

- **Malformed LLM output** (invalid JSON, unknown action type): the engine returns an error; the system re-invokes LLM Call 1 once with the error appended, then falls back to generic "you can't do that" narration.
- **Impossible action** (valid JSON, but target not present or conditions not met): the engine returns `success: false` with a reason; LLM Call 2 narrates the failure naturally.
- **Rejected soft-state patches**: appear in `EngineResult.soft_state_patches_rejected` with reasons; LLM Call 2 must not narrate the rejected change.
- **Rejected attitude changes or knowledge tags**: appear in `EngineResult.attitude_changes_rejected` or are silently dropped (invalid topic tags); LLM Call 2 must not narrate the rejected outcome.

### Future Extensions

- **Combat phase**: the attack interaction will be revised to support iterative rounds, HP tracking, damage rolls, and opposed checks. The current flag-based branching is a phase-1 placeholder.
- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.
- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

---

# Coding Plan

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Best ecosystem for LLM work; modern typing support |
| Schema / validation | Pydantic v2 | Discriminated unions for action types, model validation for complex nested schemas (conditions with any/all/require/unless), JSON serialization. One dependency, no transitive explosion |
| LLM client | `openai` package | Supports `base_url` for Deepseek compatibility (`base_url="https://api.deepseek.com"`). Lightweight (depends only on httpx + pydantic, which we already have). Supports `response_format` for structured JSON output |
| Prompt templates | Jinja2 | Clean separation of prompt text from code. Long system prompts with injected JSON (GMBriefing) are easier to maintain as templates |
| Console UI | `rich` | Markdown rendering, colored panels, live display. Good RPG console experience |
| Testing | pytest | Standard. Parametrized tests for condition evaluation, mock LLM for integration tests |
| CLI entry | argparse | Built-in, sufficient for console app |

**Not used:**
- **LangChain / LangGraph**: Rejected. The architecture is a simple two-LLM-calls-one-engine loop. LangChain would add dozens of transitive dependencies for abstraction layers we don't need.
- **FastAPI**: Not needed for a console app. If we later want a web UI, the core can be wrapped with FastAPI then.
- **Vector database / embeddings**: Not needed at phase-1 scale. The Context Assembler does deterministic ID lookups from a corpus small enough to fit in memory.

## Directory Structure

```
mgmai/
├── cli.py                      # Entry point, argument parsing, game start
├── models/                     # Pydantic models — all structured data
│   ├── __init__.py
│   ├── corpus.py               # Module Corpus (rooms, entities, interactions, mechanics,
│   │                           #   ConditionExpression, checks, traversal effects)
│   ├── hard_state.py           # Hard Game State (player, flags, room_states, entity_states)
│   ├── soft_state.py           # Soft Game State (inventory, notes, attitudes, dialogue,
│   │                           #   history, SoftStatePatch)
│   ├── actions.py              # PlayerAction (discriminated union of 7 types),
│   │                           # EngineResult, hard_state_changes, chain_info
│   ├── briefing.py             # GMBriefing, dialogue_context
│   └── narration.py            # NarrationOutput, AttitudeChange, KnowledgeTags
├── engine/                     # Deterministic game engine
│   ├── __init__.py
│   ├── conditions.py           # Condition evaluator — evaluates condition objects against state
│   ├── resolver.py             # Action resolvers (move, examine, interact, talk, transfer, wait, ooc)
│   ├── encounters.py           # Encounter resolution, behavior evaluation
│   ├── dialogue.py             # Dialogue state lifecycle (enter, exit, stall, archive, NPC response extraction)
│   ├── engine.py               # Main engine: validate → resolve → produce EngineResult
│   └── post_validate.py        # Post-validation of knowledge_tags + attitude_changes (step 4.5)
├── state/                      # State persistence and access
│   ├── __init__.py
│   └── manager.py              # Load corpus + hard_state.json + soft_state.json, save state between turns
├── context/                    # Context Assembler
│   ├── __init__.py
│   └── assembler.py            # Build GMBriefing from corpus + state (filters entities, exits, builds dialogue_context)
├── llm/                        # LLM integration
│   ├── __init__.py
│   ├── client.py               # OpenAI-compatible client wrapper (base_url, api_key, model selection)
│   └── parser.py               # Parse structured JSON output from LLM calls into Pydantic models
├── game/                       # Game loop and display
│   ├── __init__.py
│   ├── loop.py                 # Main turn loop: GMBriefing → Call1 → Engine → Call2 → post-validate → display → repeat
│   └── display.py              # Rich-based console output (narration rendering, room display, status bar)
├── templates/                  # Jinja2 prompt templates
│   ├── ruling.j2               # System prompt for LLM Call 1 (player action ruling)
│   └── prose.j2                # System prompt for LLM Call 2 (prose narration)
└── tests/
    ├── test_corpus.py          # Module corpus model validation tests
    ├── test_hard_state.py      # Hard state model validation tests
    ├── test_soft_state.py      # Soft state model validation tests
    ├── test_actions.py         # PlayerAction and EngineResult model tests
    ├── test_briefing.py        # GMBriefing model tests
    ├── test_narration.py       # Narration output model tests
    └── conftest.py             # Shared fixtures (sample corpus, state)
```

## Phase-by-Phase Implementation Plan

### Phase 1: Models (foundation for everything)

**Files:** `models/corpus.py`, `models/hard_state.py`, `models/soft_state.py`, `models/actions.py`, `models/briefing.py`, `models/narration.py`

All Pydantic v2 models matching the schema documents. Every JSON structure defined in `schema/` gets a corresponding Pydantic class.

Key design points:
- **`PlayerAction`** uses a discriminated union (`typing.Annotated` + `pydantic.Field(discriminator="action_type")`) to validate each action type's specific fields.
- **`ConditionExpression`** models the nested `require`/`unless`/`any`/`all` object format. Bare condition strings (e.g. `"flag:spider_fled == true"`) are validated against the `<domain>:<key> <op> <value>` grammar.
- **`Interaction`** models the optional `check` + `success`/`failure` vs. deterministic `result` branching.
- **`EngineResult`** includes all fields described in `schema/actions.md` §4.1, including `will_reveal_readiness`, `npc_attitude_limits`, `chain_info`.
- **`SoftStatePatch`** has field-specific validation: `soft_inventory_add` checks the item exists in room/entity soft_items; `room_note` validates room_id exists, etc.
- Each model includes `model_validator` where cross-field constraints exist (e.g., `Interaction` must have either `check+success+failure` or `result`, not both).

No dependencies beyond pydantic. No game logic here — pure data shapes.

### Phase 2: State Manager

**Files:** `state/manager.py`

Responsibility: load, validate, hold, and persist game state.

```
StateManager
├── corpus: ModuleCorpus          # loaded once at startup, read-only
├── hard_state: HardGameState     # mutable, engine writes
├── soft_state: SoftGameState     # mutable, engine writes
│
├── load_corpus(path)             # JSON → ModuleCorpus (pydantic validation)
├── load_hard_state(path)         # JSON → HardGameState
├── load_soft_state(path)         # JSON → SoftGameState
├── save_state(dir)               # Serializes hard + soft state to disk
├── get_hard_state()              # Returns current hard state snapshot
├── get_soft_state()              # Returns current soft state snapshot
├── apply_hard_changes(changes)   # Applies hard_state_changes dict from EngineResult
├── apply_soft_patches(patches)   # Applies accepted SoftStatePatch list
└── append_turn_history(entry)    # Appends to turn_history, caps at 5 for briefing
```

On startup, loads `corpus.json`, `hard-state.json`, `soft-state.json` from an adventure directory. Validates cross-references: every entity in `room.entities_present` exists in corpus, every flag in `hard_state.flags` is declared, every `entity_state` entry has a matching `state_fields` declaration, etc.

Between turns, saves a copy of hard + soft state (skipped during chained actions).

Design note: The state manager holds mutable `HardGameState` and `SoftGameState` objects. The engine receives references to these and mutates them directly (since the engine is the sole writer), rather than passing copies. This avoids serialization overhead inside the hot loop.

### Phase 3: Condition Evaluator

**Files:** `engine/conditions.py`

Evaluates `ConditionExpression` objects against the current game state (hard + soft).

```
evaluate(condition: ConditionExpression, hard_state: HardGameState, soft_state: SoftGameState) -> bool
```

Supports all six domains:
| Domain | Implementation |
|--------|---------------|
| `flag:name == true/false` | Lookup `hard_state.flags[name]` |
| `inventory:item_id` | Check `item_id in hard_state.player.inventory` |
| `tag:tagname` | Check if any item in inventory has tag `tagname` (via corpus entity lookup) |
| `entity:id.field op value` | Lookup `hard_state.entity_states[id][field]` |
| `room:id.field op value` | Lookup `hard_state.room_states[id][field]` |
| `attitude:id op N` | Lookup `soft_state.npc_attitudes[id]` |

For `any`/`all`, recurses into sub-conditions. Bare strings inside `any`/`all` arrays are treated as `require` conditions. The evaluator needs access to the corpus (for tag lookups on inventory items), so it receives either the StateManager or the corpus directly.

This is pure logic, no I/O. Heavily unit-testable.

### Phase 4: Engine

**Files:** `engine/engine.py`, `engine/resolver.py`, `engine/encounters.py`, `engine/dialogue.py`, `engine/post_validate.py`

The largest phase. The engine is a pure function: `PlayerAction → EngineResult`, reading state and corpus.

#### `engine/engine.py` — Main entry point

```
resolve(player_action: PlayerAction, state_manager: StateManager) -> EngineResult
```

High-level flow:
1. If `ooc_discussion`: no-op, return minimal EngineResult with `success: true`
2. **Validate** action against current state (delegates to resolver). The resolver returns a result object containing: success/error, proposed `HardStateChanges`, `triggered_narration` blocks, any triggered encounter, and warnings.
3. If invalid: return `success: false` EngineResult with error message
4. **Resolve encounters**: if the action triggered an encounter (via exit traversal's `trigger_encounter`, or an `attack` interaction on an NPC with `behavior`), evaluate encounter rules *before* committing hard-state changes. A `death` outcome sets `game_over` immediately; a `flee` outcome applies `on_flee` effects.
5. **Check game-over**: if the encounter produced `game_over`, skip to step 9 (do not apply further state changes).
6. **Apply hard-state changes**: move player, update inventory, set flags, update entity/room states.
7. **Fire on-enter events**: if the player moved to a new room, evaluate the target room's `on_enter` events (condition check, set_flag, set_entity_state, trigger_dialogue). Collect triggered narrations.
8. **Validate soft-state patches**: check each `proposed_soft_state_patches` against soft-state schema (entity/room exists, soft item is present, non-contradictory with hard state).
9. **Handle dialogue state**: enter/continue/exit dialogue mode based on action type. If the player moved rooms away from the active NPC, archive and exit dialogue. If in dialogue and a non-`talk` action was taken, increment stall counter; auto-exit at 3.
10. **Increment turn counter** (except for ooc_discussion)
11. **Build turn_history entry**
12. **Produce EngineResult** with all fields populated (room_after, hard_state_changes, soft patches, rolls, encounter outcome, triggered_narration, on_enter_events, game_over, dialogue_exited, will_reveal_readiness, npc_attitude_limits, chain_info, warnings)

Note: the ordering above is deliberate — encounters fire *before* hard-state changes are committed, so that a death outcome does not produce contradictory state (e.g., the player arriving in a room and dying there simultaneously). On-enter events fire *after* the player has moved, since they describe what happens upon arrival.

#### `engine/resolver.py` — Per-action-type validation

One function per action type, each returning a result object containing `(success: bool, error: str | None, hard_changes: HardStateChanges, triggered_narration: list[str], encounter_trigger: str | None, warnings: list[str])`. The resolver validates and *proposes* changes but does not mutate state — the orchestrator applies them after encounter resolution.

| Function | Validates |
|----------|-----------|
| `resolve_move(action, state, corpus)` | Exit exists, conditions met, not one-way blocked. Returns target room + traversal effects |
| `resolve_examine(action, state, corpus)` | Target entity/room/soft_item exists and is visible. If `rigorous`, evaluates any rigorous-search-gated interactions. If `using`, checks item in inventory |
| `resolve_interact(action, state, corpus)` | Target exists, interaction_id matches defined interaction, parameter_signature satisfied, conditions met. Resolves check if present. Tracks non-repeatable checks (corpus `check.repeatable: false`) and rejects retries |
| `resolve_talk(action, state, corpus)` | NPC exists in room, alive. Handles dialogue state transitions |
| `resolve_transfer(action, state, corpus)` | Target entity/room exists, items exist in source inventories. Hard items must be in the player's inventory; soft items must be in the player's soft inventory or available from the target (an entity's available pool = item entities in the same room + the entity's `soft_items`; a room's available pool = item entities present + the room's `soft_items`) |
| `resolve_wait(action, state, corpus)` | Always valid. Advances turn only |

#### `engine/encounters.py` — Encounter resolution

Evaluates NPC `behavior.encounter_rules` and `mechanics` encounters. Rules are evaluated top-to-bottom; first matching condition applies. Handles outcomes: `death` (set game_over), `flee` (set flags, apply on_flee effects), `roll` (random check with success/failure branches).

#### `engine/dialogue.py` — Dialogue state lifecycle

Manages `soft_state.dialogue_state` transitions:
- Enter dialogue on `talk` action or `on_enter.trigger_dialogue`
- Append utterances to `conversation_log` (capped at 10)
- Track `stall_counter`; auto-exit at 3 (excluding `ooc_discussion`)
- On exit: archive conversation summary to `entity_notes`, apply `on_dialogue_exit` effects
- NPC response extraction from LLM Call 2 output (look for structured `npc_response` field)
- Handle switching between different NPCs

#### `engine/post_validate.py` — Step 4.5

Validates LLM Call 2's `knowledge_tags` and `attitude_changes`:
- For each `knowledge_tag`: verify topic exists in NPC's `will_reveal`, all conditions met. Apply `set_flag`/`set_entity_state` side effects. Record in `npc_revelations`.
- For each `attitude_change`: verify NPC exists, alive, delta within `step_per_turn`, new value within `[min, max]`, non-empty reason.
- Returns lists of applied and rejected items.

### Phase 5: Context Assembler

**Files:** `context/assembler.py`

Pure function: reads corpus + state → produces `GMBriefing`.

```
assemble(state_manager: StateManager) -> GMBriefing
```

Assembly rules (per `schema/actions.md` §1):
1. Get current room from `hard_state.player.location`
2. Filter `entities_visible`: only entities with `alive == true` (or no `alive` field). Include each entity's state, up to 3 most recent entity_notes, and soft_items. Omit hidden entities.
3. Filter `exits_available`: conditions met, hidden exits omitted unless reveal flag set.
4. Build `player_state`: hard inventory, soft inventory, active flags (non-false), entity notes on player.
5. Build `recent_history`: last 5 non-`ooc_discussion` entries from `turn_history`, summarized.
6. Build `npc_attitudes`: all NPCs with known attitudes.
7. Build `npc_revelations`: from soft_state, with topic descriptions.
8. Build `dialogue_context` if `active_npc` is non-null: NPC identity, attitude, last 5 exchanges, dialogue_guidelines, topics_discussed, revealed_topics.
9. Include `player_input` (raw text, passed in by game loop).
10. Include global `setting` and `tone` from `corpus.adventure.atmosphere`.

No LLM calls here — just data assembly.

### Phase 6: LLM Integration

**Files:** `llm/client.py`, `llm/parser.py`, `templates/ruling.j2`, `templates/prose.j2`

#### `llm/client.py`

Thin wrapper around the `openai` package.
Supports `response_format={"type": "json_object"}` for structured outputs.

#### `templates/ruling.j2` — LLM Call 1 system prompt

Jinja2 template that receives the `GMBriefing` (as a dict, rendered to JSON in the prompt) plus instructions. The prompt instructs the LLM to:
- Interpret the player's input in context
- Produce exactly one `PlayerAction` (with action_type, target, detail, etc.)
- Propose soft-state patches if applicable
- Break chained actions into first step + follow_up
- Fall back to `wait` if action is impossible to adjudicate

The template includes the full GMBriefing JSON, the supported action types with field descriptions, and constraints (don't invent items, don't change hard state, respect hidden info).

#### `templates/prose.j2` — LLM Call 2 system prompt

Receives: adventure atmosphere, GMBriefing, PlayerAction, EngineResult, verbatim chat log.
Instructs the LLM to:
- Narrate the outcome in natural prose
- Incorporate `triggered_narration` blocks
- Do not contradict EngineResult or hard_state_changes
- Propose `knowledge_tags` and `attitude_changes` if relevant
- Be terse during chained actions
- Include structured `npc_response` field for dialogue extraction
- Respect `will_reveal_readiness` — only tag met conditions

#### `llm/parser.py`

Parses LLM output strings into Pydantic models:
- `parse_player_action(raw: str) -> PlayerAction`: Validates JSON, retries on parse error (the game loop handles the retry-with-error-message logic)
- `parse_prose_output(raw: str) -> ProseOutput`: Extracts `narration`, `npc_response`, `knowledge_tags`, `attitude_changes` from Call 2's JSON output

### Phase 7: Game Loop & CLI

**Files:** `game/loop.py`, `game/display.py`, `cli.py`

#### `game/loop.py`

The main turn loop:

```python
class GameLoop:
    def __init__(self, state_manager: StateManager, llm: LLMClient):
        ...

    def run_turn(self, player_input: str) -> str:
        """Execute one full turn. Returns narration text."""
        # 1. Context Assembler → GMBriefing
        # 2. LLM Call 1 → PlayerAction (with retry on malformed output)
        # 3. Engine → EngineResult
        # 4. LLM Call 2 → ProseOutput (narration + tags)
        # 5. Post-validate knowledge_tags + attitude_changes
        # 6. If chain_info indicates continuation: loop back to step 1
        #    with follow_up as next player_input (no user interaction)
        # 7. Save state (skip during chained actions)
        # 8. Return narration
```

Chain handling: The loop detects `chain_info` in EngineResult indicating an ongoing chain. It feeds `follow_up` back as the next "player input" without waiting for user input, with LLM Call 2 instructed to be terse. Chain terminates on validation failure, hard/soft rejection, or max chain length.

Retry logic: If LLM Call 1 produces invalid JSON, the loop retries once with the parse error appended to context. On second failure, falls back to a generic "You can't do that" narration.

#### `game/display.py`

Rich-based console output:
- `render_narration(text: str)`: Print narration with rich Markdown rendering
- `render_room(state, corpus)`: Display current room name, description, visible exits (formatted)
- `render_status(state)`: Show inventory, flags, turn count as a compact status bar
- `render_game_over(result)`: Display ending narrative with win/lose styling

#### `cli.py`

Entry point:
```bash
python -m mgmai.cli adventures/bag-of-holding          # start new game
python -m mgmai.cli adventures/bag-of-holding --load save.json  # resume
```

Uses argparse. Sets up `StateManager`, `LLMClient`, `GameLoop`. Runs the REPL: prompt for input, call `game_loop.run_turn()`, display result, repeat until `game_over`.

Environment variables: `MGMAI_API_KEY`, `MGMAI_BASE_URL` (defaults to Deepseek), `MGMAI_MODEL` (defaults to `deepseek-chat`).

### Phase 8: Testing & Adventure Validation

**Files:** `tests/conftest.py`, `tests/test_conditions.py`, `tests/test_engine.py`, `tests/test_assembler.py`, `tests/test_models.py`

#### Test strategy

1. **Model validation tests** (`test_models.py`): Load the sample `corpus.json`, `hard-state.json`, `soft-state.json` and verify Pydantic validation passes. Test invalid documents are rejected.

2. **Condition evaluator tests** (`test_conditions.py`): Parametrized tests for every condition domain:
   - Simple: `flag:X == true`, `inventory:Y`, `tag:weapon`, `entity:Z.alive == true`
   - Compound: `any`/`all` with nesting
   - Edge cases: missing flag, entity not in room, attitude out of bounds

3. **Engine tests** (`test_engine.py`): Test each action type against the sample adventure:
   - `move`: valid exit, invalid exit, one-way blocked, conditions not met
   - `examine`: existing entity, nonexistent entity, rigorous search
   - `interact`: valid interaction, wrong target, conditions not met, check resolution (mock random)
   - `talk`: valid NPC, dead NPC, ends_dialogue, attitude gating
   - `transfer`: valid give/take, item not in inventory
   - `wait`: always valid, turn advances
   - `ooc_discussion`: no state change
   - Encounter resolution: spider encounter with/without weapon, injured/not injured
   - Dialogue lifecycle: enter, continue, stall exit, move exit, NPC death exit
   - Chained actions: follow_up processing, max chain length enforcement
   - Game-over: win condition (unlock padlock), lose condition (spider death)
   - Soft-state patches: valid, invalid (contradicts hard state, nonexistent entity)

4. **Context Assembler tests** (`test_assembler.py`): Build GMBriefing from sample state, verify:
   - Correct room and visible entities
   - Hidden exits omitted
   - Dialogue context present when active_npc set
   - Recent history capped at 5, ooc_discussion excluded
   - Correct player state (inventory, flags)

5. **Integration test** (`test_integration.py`): Script a sequence of player inputs through the sample adventure and verify the engine state at each step. Mock the LLM to return predetermined PlayerActions. Verify the full loop behaves correctly.

#### Test fixtures (`conftest.py`)

- `sample_corpus`: ModuleCorpus loaded from `adventures/bag-of-holding/corpus.json`
- `sample_hard_state`: HardGameState from `adventures/bag-of-holding/hard-state.json`
- `sample_soft_state`: SoftGameState from `adventures/bag-of-holding/soft-state.json`
- `state_manager`: StateManager with sample data loaded
- `mock_llm_client`: Returns predetermined responses for testing

## Key Design Decisions

### 1. Engine mutations the state manager directly

The engine receives the StateManager and mutates hard/soft state through it. This is safe because the engine is the sole writer — no other component modifies game state. The state manager exposes `apply_hard_changes()` and `apply_soft_patches()` methods that the engine calls during resolution, building up the `hard_state_changes` diff for the EngineResult as a side effect.

Alternative considered: Immutable state with copy-on-write. Rejected for phase 1 — the state is small and the mutation model is simpler. If we later need undo/redo or speculative execution, we can introduce snapshots.

### 2. LLM output format: JSON mode for both calls

Both LLM calls use `response_format={"type": "json_object"}`:
- Call 1 outputs `PlayerAction` JSON directly.
- Call 2 outputs `{"narration": "...", "npc_response": "...?", "knowledge_tags": {...}?, "attitude_changes": {...}?}`.

This eliminates fragile regex parsing. The `openai` package (and Deepseek) support this. If a model doesn't support JSON mode, we fall back to extracting JSON from markdown code blocks.

### 3. Temperature settings per call

- LLM Call 1 (ruling): temperature ≈ 0.9. Deepseek-v4-flash expects temperatures around 1.0; we want consistent, predictable action classification.
- LLM Call 2 (prose): temperature ≈ 1.1. Deepseek-v4-flash expects temperatures around 1.0; we want creative, varied narration.

Configurable via environment variables `MGMAI_RULING_TEMPERATURE` and `MGMAI_PROSE_TEMPERATURE`.

### 4. Condition string parsing

Condition strings like `"flag:spider_fled == true"` are parsed with a simple regex:
```
^(flag|inventory|tag|entity|room|attitude):([\w.]+)(?:\s*(==|>=|>|<=|<)\s*(.+))?$
```

For `inventory` and `tag`, no operator/value — just presence check. For others, the operator and value are required.

This parsing happens in `engine/conditions.py`, not in the Pydantic models (which store these as strings). Runtime evaluation resolves the domain references against current state.

### 5. Error handling as described in the architecture

- Malformed LLM JSON → retry once with error in context → fallback narration
- Impossible action (valid JSON, engine rejects) → `success: false` in EngineResult → LLM Call 2 narrates failure naturally
- Rejected soft patches → listed in EngineResult, LLM Call 2 must not narrate
- Chain termination → `chain_info` with reason, LLM Call 2 narrates the interruption

### 6. Save/load format

Save file: a JSON file containing both `hard_state` and `soft_state` (merged into one object with `hard` and `soft` keys), plus the adventure path to reload the corpus. Saved after each non-chain turn. Load reconstructs state from scratch; no LLM context is persisted.

### 7. Soft state contradiction detection

The engine does basic contradiction checks on soft-state patches (e.g., can't say "spider is dead" if `entity_states.spider.alive == true`). This is done via simple keyword matching against entity names + state fields, not via a second LLM call. It won't catch subtle contradictions but will catch the obvious ones.

## Open Questions / Future Work

1. **Rich display of GMBriefing debug mode**: Add a `--debug` flag that renders the GMBriefing and EngineResult for each turn alongside the narration. Useful for development and troubleshooting.

2. **Streaming narration**: For better UX, LLM Call 2's narration could be streamed token-by-token via the OpenAI streaming API, with `rich` live-updating the display.

3. **Token budgeting**: Count tokens in the GMBriefing and trim `entity_notes`, `recent_history`, and `room_notes` if approaching the model's context limit. Not needed for the 5-room sample but important for larger adventures.

4. **Multi-model support**: The two LLM calls could use different models — a cheap fast model for Call 1 (ruling) and a more expressive model for Call 2 (prose). Configurable via separate environment variables.

5. **Adventure validation tool**: A script that loads a corpus + state files and runs validation checks (all entity refs resolve, all flags declared, all rooms connected, etc.) without starting the game. Useful for adventure authors.

6. **Corpus generation pipeline**: The `schema/scenario-generation.md` document describes an LLM agent workflow for converting natural-language scenarios into structured JSON. This could be implemented as a separate CLI tool (`mgmai-generate`).
