# My GM is AI — Architecture Guide

This is an experimental software project to implement an AI-driven
Game Master (GM) that replicates the tabletop RPG experience.  It aims
to function like a human GM running a pre-written adventure module.
The GM knows and follows the rules, but also accommodates the player's
unpredictable intentions and provides customized narrative flavor.

The system uses a large language model (LLM) to drive interpretation
and narration, and a deterministic engine to impose game mechanics.
LLMs are good at natural-language understanding and prose generation,
but unreliable for persistent rule enforcement and state tracking.
Therefore, the system splits the GM's responsibilities: the LLM
interprets player intent, constructs structured actions, and weaves
outcomes into compelling prose; the engine validates actions against
the rules, resolves mechanics, and constrains the narrative output to
the actual game state.

## Architecture

Each turn, we run two LLM calls sandwiching a coded engine.  The LLM
calls and engine are informed by three data stores that track the game
state.

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
│  the player     │  Output: structured PlayerAction
│  attempt?"      │         + optional soft state patch
└────┬────────────┘
     │ PlayerAction
     ▼
┌─────────────────┐
│  Engine         │  Reads: Corpus, Hard State, Soft State
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

**Module Corpus**: the equivalent of a printed adventure module,
loaded at startup and never modified during play.  It specifies rooms,
entities (player, NPCs, features, items), interactions (named actions
gated by conditions), mechanics, global flags and their initial
values, etc.

**Hard Game State**: mutable runtime state managed exclusively by the
engine.  It tracks player location, inventory, flags, room/entity
states (including per-NPC attitude values), turn count, and game-over
conditions.

**Soft Game State**: narrative elements that the LLM can propose
changes to: soft inventory (non-unique items like "a rock"), room
notes, entity notes, dialogue state, turn history, player knowledge,
etc.  Changes to soft game state follow fixed schema and are validated
by the engine.

### The Context Assembler and GMBriefing

Each turn, the Context Assembler builds a **GMBriefing** — a JSON
document describing the current world state, containing the following:

- **Global setting**: introductory sentences about the adventure.
- **Current room**: ID, name, prose description, available exits,
  available interactions, etc.
  - All **Entities** visible in the current room: ID, name, type
    (feature/item/NPC), description, state, etc.
- **Player state**: location, hard/soft inventory, active flags.
- **Recent history**: summary of the last 5 turns.
- **Player knowledge**: key topics the player has learned about through dialogue, interactions, examination, etc.
- **Dialogue context** (when in conversation): active NPC identity, attitude, dialogue guidelines, recent exchanges, topics discussed.
- **Player input**: the verbatim input for this turn.

In the future, we might turn to a vector database, but for now lookups
are deterministic.

### LLM Call 1 and player actions

LLM Call 1, which runs at a moderately low temperature, receives the
GMBriefing + verbatim player input and is tasked with interpreting the
player's input.  It cannot propose hard-state changes (those are the
engine's domain).  Instead, it is tasked with producing a structured
PlayerAction in JSON, consisting of exactly one of these types:

- `move`: travel to another room via an exit; in combat, try to flee
- `examine`: inspect a room, entity, or soft item
- `interact`: perform a named interaction on a room or entity
- `talk`: start or continue dialogue with an NPC
- `transfer`: give/take items between inventory and entity/room
- `gear`: equip or unequip a gear item
- `wait`: catch-all for below-threshold actions, or pass time or combat turn
- `combat`: combat action: attack or maneuver
- `use_ability`: use a spell, class feature, or other ability
- `ooc_discussion`: out-of-character question to GM

Every action has a `detail` field with a natural-language description
of what the player does, optional `soft_state_patches`, optional
`follow_up` for chained actions (see below), plus action-specific
fields (e.g., `move` has a `target` field for the exit ID).

Only one action can occur per turn.  Multi-step inputs ("I pick up the
key and unlock the door") are handled via **chained actions**.  The
LLM extracts the first action ("I pick up the key") and stores the
rest in the `follow_up` field ("unlock the door").  After the first
action is processed, the engine injects the follow-up as a new turn
without further player input.  This follow-up can itself be broken up,
thereby extending the chain.  The chain terminates if any step fails
validation, or the LLM decides it is narratively invalidated, or the
chain length exceeds a maximum.

### Engine resolution

The engine is the system's source of truth.  It receives the PlayerAction and:

1. **Validates** the action (e.g., is the entity alive? does the item exist?).
2. **Resolves mechanics**: evaluates conditions, rolls dice for checks, dispatches encounters, etc.
3. **Applies hard-state changes**: flags, inventory, location, entity states.
4. **Validates soft-state patches**: accepts/rejects with reasons.
5. **Checks for game-over**.
6. **Produces an EngineResult** containing the full outcome: stat check success/failure, a diff of state changes, etc.

### LLM Call 2: Prose narration

LLM Call 2 receives the GMBriefing, PlayerAction, EngineResult, and a
verbatim chat log.  Its task is to weave the outcome into natural
prose, while obeying the engine: it is instructed never to contradict
the engine result, respect game-over triggers, etc.

However, LLM Call 2 is not a pure narrator, and it also has leeway to
affect the game's soft state to fit the narrative.  It helps
adjudicate the insertion of soft items into the narrative, as well as
managing the topics NPCs reveal in conversation and changes in NPC
attitude; see [npcs.md](npcs.md) for details.

### Dialogue and combat modes

The system implements two situational modes that layer over the above
pipeline (LLM Call 1 → Engine → LLM Call 2).

**Dialogue mode** activates when the player talks to an NPC.  It
extends the pipeline in three ways:

- The Context Assembler injects a `dialogue_context` block into the
  GMBriefing, giving both LLM calls access to the conversation log,
  NPC personality guidelines, attitude, and topics discussed.

- The prose renderer injects a dialogue-specific template section,
  instructing LLM Call 2 to manage NPC speech inline, propose attitude
  shifts, and track knowledge revelations.

- After Call 2 returns, a lightweight post-processing step feeds the
  NPC's verbatim response into the dialogue log and, if conversation
  has ended, archives a summary as an entity note on the NPC.

**Combat mode** uses the same layering pattern with more aggressive
constraints:

- The Assembler injects a `combat_state` block with positioning data,
  HP, initiative order, usable item effects, and ability summaries.

- Template injections constrain LLM Call 1 to specific action types
  (attack, use ability, flee, wait, interact, or cursory examine) and
  instruct LLM Call 2 to narrate from the combat log.

- The engine runs the turn-based combat loop (initiative tracking, NPC
  AI turns, status effects, etc.) entirely within its step of the
  pipeline.  The LLMs only see the briefing and the log.

### Error handling

Each stage of the pipeline has its own error path.

**LLM Call 1** (ruling): On malformed JSON, unknown action type, or
(in combat) invalid targets/abilities, the system retries once with
the error appended to the prompt.  A second failure aborts the turn,
and skips to the next player input with no narration.

**Engine**: Validly-structured actions that violate game rules (e.g.,
missing item, dead NPC, room has no such exit) return `success: false`
on the `EngineResult`.  This is not a turn abort; LLM Call 2 proceeds
normally and narrates the failure.  Soft-state patches proposed by the
LLM that reference nonexistent entities or contradict current state
are rejected individually while the rest apply.

**LLM Call 2** (prose): On malformed JSON, the system retries once.  A
second failure falls back to an engine-generated narration string
rather than aborting.  Semantic validation (missing or mangled marker
tags, contradiction of the engine's success/failure outcome, empty
narration) also retries once, and on a second failure logs a warning
and continues with the output as-is.

**Post-validation** (after Call 2): Knowledge tags, attitude changes,
and soft-item adjudications proposed by the prose LLM are validated
against the game state.  Invalid entries are rejected silently,
without preventing the rest of the turn from completing.

### Serialization

After each non-chain turn, the system saves hard state + soft state as
a JSON file.  The GMBriefing is reconstructed from scratch on load; no
LLM context is persisted.

## Directory Structure

```
mgmai/
├── cli.py               # Entry point, argument parsing, game start
├── models/              # Pydantic models — all structured data
│   ├── corpus.py        # Module Corpus
│   ├── hard_state.py    # Hard Game State
│   ├── soft_state.py    # Soft Game State
│   ├── actions.py       # PlayerAction, EngineResult
│   ├── briefing.py      # GMBriefing, dialogue_context
│   └── narration.py     # NarrationOutput, AttitudeChange, KnowledgeTags
├── engine/              # Deterministic game engine
│   ├── conditions.py    # Condition evaluator
│   ├── resolver.py      # Action resolvers (move, examine, interact, etc.)
│   ├── encounters.py    # Encounter resolution
│   ├── combat.py        # Turn-based combat loop (system-agnostic)
│   ├── stat_checks.py   # Backward-compat shims + narrative prefixes
│   ├── systems/         # Resolution-system abstraction
│   │   ├── base.py      # ResolutionSystem base
│   │   ├── five_e.py    # D&D 5e implementation
│   │   └── dice.py      # Dice-expression parsing
│   ├── dialogue.py      # Dialogue lifecycle
│   ├── engine.py        # Main engine pipeline
│   └── post_validate.py # Post-validation of knowledge, attitude
├── state/
│   └── manager.py       # Load/save corpus and game state
├── context/
│   └── assembler.py     # Build GMBriefing from corpus + state
├── llm/
│   ├── client.py        # OpenAI-compatible LLM client wrapper
│   ├── model_config.py  # Model configuration and selection
│   └── parser.py        # Parse structured JSON from LLM output
├── game/
│   ├── loop.py          # Main turn loop
│   └── display.py       # Console UI (Rich-based)
├── templates/
│   ├── ruling.j2        # System prompt for LLM Call 1
│   └── prose.j2         # System prompt for LLM Call 2
├── tests/               # pytest unit tests
├── scripts/
│   ├── validate.py      # Runtime validation tool
│   └── validate_adventure.py # Static adventure corpus validation
└── adventures/
    └── bag-of-holding/       # Sample adventure
        ├── corpus.json
        └── soft-state.json
```

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
