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
