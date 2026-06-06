# My GM is AI (MGMAI) -- Project Plan

For an overview of project goals, see README.md.

During the initial phase of development, we will limit the scope as follows:

* We will fix on OpenAI compatible API calls.
* Input/output are console based, with no graphics.
* Combat will have kill-or-be-killed resolutions with no special mechanics.
* Similarly, no player stats for now.

## Architecture

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
   Interactions include generic ones like `attack`, plus special corpus-defined ones like `recharge`.
  It optionally includes a `using` field to specify a valid entity ID or soft item enabling the interaction (e.g., attack goblin using sword).

* `talk` must specify one NPC entity ID.
  It optionally includes an `utterance` field (verbatim player speech) and/or an `ends_dialogue` flag. See the Dialogue section below.

* `transfer` must specify one entity ID (usually an NPC or container), or room ID, to transfer items to/from (e.g., for dropping items on the floor).
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

## Design Decisions

### 1. Engine mutations the state manager directly

The engine receives the StateManager and mutates hard/soft state through it. This is safe because the engine is the sole writer — no other component modifies game state. The state manager exposes `apply_hard_changes()` and `apply_soft_patches()` methods that the engine calls during resolution, building up the `hard_state_changes` diff for the EngineResult as a side effect.

Alternative considered: Immutable state with copy-on-write. Rejected for phase 1 — the state is small and the mutation model is simpler. If we later need undo/redo or speculative execution, we can introduce snapshots.

### 2. LLM output format: JSON mode for both calls

Both LLM calls use `response_format={"type": "json_object"}`:
- Call 1 outputs `PlayerAction` JSON directly.
- Call 2 outputs `{"narration": "...", "npc_response": "...?", "knowledge_tags": {...}?, "attitude_changes": {...}?}`.

This eliminates fragile regex parsing. The `openai` package (and Deepseek) support this. If a model doesn't support JSON mode, we fall back to extracting JSON from markdown code blocks.

### 3. Condition string parsing

Condition strings like `"flag:spider_fled == true"` are parsed with a simple regex:
```
^(flag|inventory|tag|entity|room|attitude):([\w.]+)(?:\s*(==|>=|>|<=|<)\s*(.+))?$
```

For `inventory` and `tag`, no operator/value — just presence check. For others, the operator and value are required.

This parsing happens in `engine/conditions.py`, not in the Pydantic models (which store these as strings). Runtime evaluation resolves the domain references against current state.

### 4. Error handling as described in the architecture

- Malformed LLM JSON → retry once with error in context → fallback narration
- Impossible action (valid JSON, engine rejects) → `success: false` in EngineResult → LLM Call 2 narrates failure naturally
- Rejected soft patches → listed in EngineResult, LLM Call 2 must not narrate
- Chain termination → `chain_info` with reason, LLM Call 2 narrates the interruption

### 5. Save/load format

Save file: a JSON file containing both `hard_state` and `soft_state` (merged into one object with `hard` and `soft` keys), plus the adventure path to reload the corpus. Saved after each non-chain turn. Load reconstructs state from scratch; no LLM context is persisted.

### 6. Soft state contradiction detection

The engine does basic contradiction checks on soft-state patches (e.g., can't say "spider is dead" if `entity_states.spider.alive == true`). This is done via simple keyword matching against entity names + state fields, not via a second LLM call. It won't catch subtle contradictions but will catch the obvious ones.

# To Be Done: Player Stats Extension

## Objective

Add a rudimentary player stat system that supports:

1. A basic character sheet with ability scores (STR, DEX, CON, INT, WIS, CHA).
2. Stat checks (e.g., "STR +4 vs DC 12") for gating actions and resolving uncertain outcomes.
3. Adventure module-level references to stats in conditions and interactions.
4. A **resolution system abstraction** so adventures are not coupled to a specific RPG edition (D&D 5e, Pathfinder, GURPS, etc.).
   The scenario writes checks in a general form; a translation layer maps them to concrete dice math.
   Once a scenario is translated into an adventure module (json files), it's locked into a specific resolution system.

No existing code or schema is altered — this is purely additive.

### What already exists

| Existing feature | How stats extend it |
|---|---|
| **Condition domains** (`flag`, `inventory`, `tag`, `entity`, `room`, `attitude`, `topic`) | Add a `stat` domain: `stat:STR >= 12`. This is a new branch in `evaluate_condition_string()`. |
| **Check object** (`type: "roll"`, flat `threshold`) | Add a new check type `"stat_check"` with stat, modifier, and DC fields. The engine dispatches to the resolution system. |
| **Entity `state_fields`** | Player stats are a parallel data structure living in `hard_state.player.stats`. |
| **NPC `attitude_limits`** | Stats can be added as conditions on `will_reveal` entries, encounters, and interactions — same condition-object nesting. |
| **GMBriefing** | Add a `player_stats` section. The Context Assembler already builds the briefing from hard state. |
| **Engine resolution** | Stat checks slot into the same resolve → produce EngineResult flow. `EngineResult.rolls` already exists for probabilistic outcomes. |

### What does NOT need to change

- The two-LLM-call architecture (ruling + prose) is untouched.
- The soft state system is untouched (stats are hard state — engine-authoritative).
- Existing condition domains, action types, and interaction schemas are untouched.
- The bag-of-holding adventure continues to work as-is (stats are optional per adventure).

## Proposed Design

### 1. Stat definitions in the corpus

A new optional top-level block in `corpus.json`:

```json
{
  "adventure": { ... },
  "rooms": { ... },
  "entities": { ... },
  "mechanics": { ... },
  "stats": {
    "definitions": {
      "STR": { "name": "Strength", "description": "Physical power and melee capability" },
      "DEX": { "name": "Dexterity", "description": "Agility, reflexes, and ranged capability" },
      "CON": { "name": "Constitution", "description": "Endurance, stamina, and resilience" },
      "INT": { "name": "Intelligence", "description": "Reasoning, memory, and arcane knowledge" },
      "WIS": { "name": "Wisdom", "description": "Perception, intuition, and willpower" },
      "CHA": { "name": "Charisma", "description": "Force of personality, persuasion, and leadership" }
    },
    "resolution_system": "d20"
  }
}
```

- `definitions` is a dict of stat keys → `{ name, description }`.
- `resolution_system` references a named built-in or a custom resolution definition (see §4).
- If `stats` is absent, the adventure has no stat system. All existing adventures continue to work.
- The schema also reserves space for a future optional `skills` block (parallel to `definitions`), and for a `proficiencies` dict on the player (`hard_state.player.proficiencies`) which would map skill IDs to a proficiency tier. These are not implemented in phase 2, but the `StatCheck` model may optionally reference a `skill` in addition to `stat` (reserved, unused in phase 2).

### 2. Player stats in hard state

```json
{
  "player": {
    "location": "axe_head",
    "inventory": [],
    "stats": {
      "STR": 14,
      "DEX": 12,
      "CON": 13,
      "INT": 10,
      "WIS": 8,
      "CHA": 16
    }
  },
  "flags": { ... },
  ...
}
```

- `stats` is an optional dict on `player`. If absent, the adventure has no stats.
- Values are integers. The meaning depends on the resolution system (for d20: these are the raw ability scores, modifiers are computed).
- Startup validation (in `state/manager.py` after both corpus and hard state are loaded) ensures that every stat key in `player.stats` has a matching entry in `corpus.stats.definitions`, and that `player.stats` is absent when `corpus.stats` is absent (and vice versa).

### 3. New condition domain: `stat`

Extend the condition string format:

```
stat:STR >= 12
stat:CHA >= 15
stat:DEX < 8
```

This evaluates to true when the player's current stat value meets the comparison. Uses the same `_compare()` function as other numeric conditions.

**In `engine/conditions.py`:**
```python
if domain == "stat":
    if op is None or value is None:
        raise ValueError(f"stat condition requires operator and value: {raw!r}")
    if hard_state.player.stats is None:
        return False
    stat_val = hard_state.player.stats.get(key)
    if stat_val is None:
        return False
    return _compare(stat_val, op, value)
```

The syntax `npc_stat:<entity_id>.<stat_key>` is reserved for future NPC opposed checks (not implemented in phase 2). It is not added to the condition parser regex in phase 2; attempting to use it will fail with "Could not parse condition string" like any other unknown domain. This avoids adding dead code paths and is simpler to extend later.

**Usage in corpus conditions** (same condition-object nesting as everything else):

```json
{
  "require": "stat:STR >= 13"
}
```

```json
{
  "all": [
    "stat:CHA >= 15",
    "attitude:korbar >= 2"
  ]
}
```

This lets scenario authors gate interactions on stats. For example, a "Bend the Bars" interaction could require `stat:STR >= 15`. Persuading an NPC to share a secret could require `stat:CHA >= 12` in addition to attitude.

### 4. Resolution system abstraction

The resolution system defines **how stat checks translate to probability**. This is the translation layer that decouples adventures from specific RPG editions.

For the current phase, we only implement `d20`: 20-sided dice, modifier = (stat - 10) / 2, rounded down, roll(1d20) + modifier >= DC.

Custom systems are a future extension point — the schema reserves the space, but the engine only needs to handle the named built-in systems.  Eventually, the corpus generator could support translating a given scenario.md file into different resolution systems.

### 5. New check type: `stat_check`

Extend the `Check` model with a new type alongside `"roll"`:

```json
{
  "type": "stat_check",
  "stat": "STR",
  "dc": 12,
  "modifier": 0,
  "repeatable": true,
  "note": "Bend the iron bars."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `"stat_check"` | yes | Discriminator. |
| `stat` | string | yes | Stat key (must be defined in `corpus.stats.definitions`). |
| `dc` | number | yes | Difficulty class (or target number, depending on resolution system). |
| `modifier` | number | no | Flat modifier added to the roll (default 0). Represents situational bonuses: tools, conditions, etc. |
| `resolution_params` | dict | no | Resolution-system-specific options, keyed by system name. For d20: `{"d20": {"advantage": true}}`. Keeps edition-specific mechanics out of the generic schema. |
| `opposed_by` | string | no | Reserved for future NPC opposed checks (e.g. `"entity:spider.DEX"`). Not implemented in phase 2. |
| `repeatable` | boolean | yes | Whether the check can be retried. |
| `note` | string | no | Designer note. |

**Engine resolution flow:**

1. Engine receives an `interact` (or other) action whose interaction has a `stat_check`.
2. Engine looks up `corpus.stats.resolution_system` (currently `"d20"`).
3. Engine computes the modifier from the player's stat value using the resolution system's formula: for d20, `computed_modifier = compute_d20_modifier(stat_value)` where `compute_d20_modifier` is a standalone, unit-testable function: `(stat_value - 10) // 2`.
4. Engine reads `resolution_params` for the active system: e.g., for d20, checks `resolution_params.get("d20", {}).get("advantage")` and applies advantage/disadvantage logic (roll twice, take higher/lower). If both advantage and disadvantage are set, they cancel out. Parameters present for a non-active system key are silently ignored (a warning may be logged).
5. Engine rolls: `random.randint(1, 20) + computed_modifier + check.modifier >= dc`.
6. Engine selects `success` or `failure` result as with any check.
7. The roll details (stat, modifier, dc, raw roll, total, margin, outcome) are recorded in `EngineResult.rolls`.

**Pydantic model change** (in `mgmai/models/corpus.py`):

```python
class RollCheck(BaseModel):
    type: Literal["roll"] = "roll"
    threshold: float = Field(ge=0.0, le=1.0)
    repeatable: bool
    note: Optional[str] = None


class StatCheck(BaseModel):
    type: Literal["stat_check"] = "stat_check"
    stat: str
    dc: int
    modifier: int = 0
    resolution_params: Optional[Dict[str, Any]] = None
    opposed_by: Optional[str] = None  # reserved; future NPC opposed checks
    repeatable: bool
    note: Optional[str] = None
    skill: Optional[str] = None        # reserved for future skill checks


CheckType = RollCheck | StatCheck   # Union; discriminated by Literal["type"]
```

Update `Interaction.check` to use the union:

```python
class Interaction(BaseModel):
    # ... existing fields ...
    check: Optional[CheckType] = None   # was Optional[Check]
    # ... rest unchanged ...
```

This matches the existing discriminated-union pattern used for `PlayerAction`. Every site that accesses `check.threshold` must first guard on `check.type == "roll"` or use `isinstance(check, RollCheck)`.

**Reusable component positioning:** `StatCheck` is designed as a reusable component that can be attached to any rule-based resolution point in the corpus, not just `Interaction.check`. The schema treats `StatCheck` as optional within `EncounterRule`, `TraversalEffect`, and `OnEnterEvent` (phase 2 only implements `Interaction.check`; the other positions are reserved and will error if a `stat_check` is found there in phase 2). This mirrors how `ConditionExpression` is universally attachable throughout the corpus.

### 6. GMBriefing extension

Add to the GMBriefing:

```json
{
  "player_stats": {
    "STR": { "value": 14, "modifier": 2 },
    "DEX": { "value": 12, "modifier": 1 },
    "CON": { "value": 13, "modifier": 1 },
    "INT": { "value": 10, "modifier": 0 },
    "WIS": { "value": 8, "modifier": -1 },
    "CHA": { "value": 16, "modifier": 3 }
  }
}
```

A new `PlayerStatEntry` Pydantic model holds `value: int` and `modifier: int`. The Context Assembler needs access to `corpus.stats.resolution_system` (passed into `_build_player_state`) to compute modifiers. `player_stats` is omitted if the adventure has no stats. This gives the LLM direct knowledge of the player's capabilities without requiring it to do math.

### 7. EngineResult extension

Add stat check details to the existing `rolls` array:

```json
{
  "rolls": [
    {
      "check_id": "bend_bars",
      "type": "stat_check",
      "stat": "STR",
      "dc": 12,
      "modifier": 4,
      "computed_mod": 2,
      "flat_mod": 2,
      "raw_roll": 14,
      "total": 16,
      "margin": 4,
      "success": true,
      "advantage": false,
      "disadvantage": false
    }
  ]
}
```

This is backward-compatible — `rolls` already accepts `List[Dict[str, Any]]`. The `check_id` field (the interaction ID) is included for consistency with existing roll entries and for debuggability. The `computed_mod` is the modifier derived from the player's stat score; `flat_mod` is the check's own `modifier` field; `modifier` is the total modifier applied to the roll. The `margin` field (`total − DC`) supports future graded outcomes without requiring schema changes.

### 8. Character sheet display

In `mgmai/game/display.py`, when stats are present, render a character sheet panel using Rich:

```
┌─ Character Sheet ──────────────┐
│ STR 14 (+2)   INT 10 (+0)     │
│ DEX 12 (+1)   WIS  8 (-1)     │
│ CON 13 (+1)   CHA 16 (+3)     │
└────────────────────────────────┘
```

This is a display-only change. The `display.py` module already uses Rich panels.

### 9. Scenario integration examples

#### Example: Bending bars with STR

In the corpus, an interaction on a feature:

```json
{
  "id": "bend_bars",
  "label": "Bend the iron bars",
  "description": "Attempt to bend the rusty iron bars apart using brute strength.",
  "condition": { "require": "stat:STR >= 10" },
  "check": {
    "type": "stat_check",
    "stat": "STR",
    "dc": 14,
    "repeatable": true,
    "note": "STR check DC 14 to bend the bars."
  },
  "success": {
    "narrative": "You grip the bars and heave. Metal groans and bends — enough for you to squeeze through.",
    "set_flag": { "bars_bent": true }
  },
  "failure": {
    "narrative": "You strain against the bars, but they refuse to budge. You'll need more strength, or another approach."
  }
}
```

#### Example: Persuading an NPC with CHA

Gating a `will_reveal` topic on both attitude and stat:

```json
{
  "will_reveal": {
    "deep_secret": {
      "description": "The NPC reveals a deeply personal secret.",
      "conditions": [
        "attitude:guard >= 4",
        "stat:CHA >= 14"
      ]
    }
  }
}
```

#### Example: Perception check (WIS)

A hidden exit revealed by a WIS check:

```json
{
  "interactions": [
    {
      "id": "search_for_passage",
      "label": "Search for a hidden passage",
      "description": "Scan the walls carefully for any sign of a concealed exit.",
      "check": {
        "type": "stat_check",
        "stat": "WIS",
        "dc": 13,
        "repeatable": true
      },
      "success": {
        "narrative": "Your keen eye catches a faint seam in the stone — a hidden door!",
        "set_flag": { "passage_found": true }
      },
      "failure": {
        "narrative": "You scan the walls but nothing stands out. The stonework looks solid."
      }
    }
  ]
}
```

With the exit:

```json
{
  "id": "exit_hidden_passage",
  "direction": "Slip through the hidden passage",
  "target_room": "secret_tunnel",
  "conditions": [{ "require": "flag:passage_found == true" }],
  "hidden": true
}
```

---

## Translation Layer: How It Decouples from D&D

The key insight is that **the scenario references stats and DCs abstractly**; the resolution system provides the concrete math.

| Scenario says | d20 system interprets | 3d6 system interprets | Diceless interprets |
|---|---|---|---|
| `stat:STR >= 14` | Raw STR score >= 14 | Raw STR score >= 14 | Raw STR score >= 14 |
| `stat_check: STR, dc: 12` | d20 + (STR-10)//2 >= 12 | 3d6 <= STR | STR >= 12 |
| `stat_check: CHA, dc: 15, modifier: 2` | d20 + (CHA-10)//2 + 2 >= 15 | 3d6 <= CHA+2 | CHA + 2 >= 15 |

The scenario author only needs to think in terms of "is the character strong enough?" and "what's the difficulty?" The resolution system translates that into whatever probability curve the system uses.

A scenario written with `d20` in mind (DCs in the 10-20 range, stats 3-18) works naturally with d20. A scenario written for a point-buy system (stats 1-5) would use `flat` resolution. The scenario author picks the resolution system that matches their stat scale; the engine handles the rest.

---

## Implementation Scope

### In scope

1. `stats` block in corpus schema (definitions + resolution_system).
2. `player.stats` in hard state schema and Pydantic model.
3. `stat` condition domain in the condition evaluator.
4. `StatCheck` as a new check type alongside `RollCheck`.
5. d20 resolution system (the only built-in for now).
6. `player_stats` in GMBriefing.
7. Stat check details in `EngineResult.rolls`.
8. Character sheet display in the console UI.
9. Startup validation (stats in hard state match corpus definitions).
10. Update `scenario-generation.md` with stats instructions.

## File Changes Summary

| File | Change type | Description |
|---|---|---|
| `schema/corpus.md` | Add | Document `stats` block, `stat_check` type, `stat` condition domain |
| `schema/hard-state.md` | Add | Document `player.stats` |
| `schema/actions.md` | Add | Document `stat_check` in EngineResult.rolls |
| `schema/scenario-generation.md` | Add | Stats section in generation instructions |
| `mgmai/models/corpus.py` | Modify | Replace `Check` with `RollCheck` + `StatCheck` discriminated union (`CheckType`). Add `StatDefinition`, `StatsBlock`. Add `stats` to `ModuleCorpus`. |
| `mgmai/models/hard_state.py` | Add | `stats: Optional[Dict[str, int]]` to `PlayerState` |
| `mgmai/models/briefing.py` | Add | `PlayerStatEntry` model. `player_stats` to GMBriefing |
| `mgmai/engine/conditions.py` | Modify | Add `stat` to `DOMAINS` regex. Add `stat` domain branch in `evaluate_condition_string()` |
| `mgmai/engine/stat_checks.py` | New | `compute_d20_modifier()`, `compute_modifier()` public functions |
| `mgmai/engine/resolver.py` | Modify | Refactor `_resolve_interaction_check` → dispatch on `check.type`. Extract `_resolve_roll_check()`. Add `_resolve_stat_check()`. |
| `mgmai/engine/engine.py` | No change | Stat checks flow through existing `resolve()` pipeline |
| `mgmai/context/assembler.py` | Modify | Pass `corpus` to `_build_player_state`. Compute and include `player_stats` in GMBriefing |
| `mgmai/state/manager.py` | Modify | Add `_validate_player_stats()` call on load/new-game |
| `mgmai/game/display.py` | Add | Character sheet panel |

No existing fields, functions, or schemas are altered — all changes are additive.

## Open Questions

1. **Stat checks on non-player entities**: Should NPCs have stats too? Recommendation: not for this phase. The schema reserves an `opposed_by` field on `StatCheck` and an `npc_stat:` condition domain for future use. NPC capabilities remain modeled through `behavior` encounter rules and `attitude_limits`.

2. **LLM knowledge of stats**: Should the LLM Call 1 prompt include the full character sheet, or just the relevant stat for the current situation? Recommendation: include the full `player_stats` block in the GMBriefing. The LLM should understand the character holistically, not just in the context of a single check.

3. **Separation of player stats from adventure module**: Eventually, we want to be able to import a player stat block into a module (and export it!). This can be deferred till later, but the design should retain this possibility.
