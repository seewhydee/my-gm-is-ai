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

For testing, we will set up one short sample adventure consisting of a hand written text adventure consisting of a 5 room dungeon with no combat (just traps and puzzles). This will be written up as a single long planning document, and converted unto the appropriate schema (with validation) by LLM assistants. Much later, we will explore setting up a more general conversion pipeline, e.g. finding adventures from interactive fiction or tabletop modules with permissive licenses, and translating them.

Other scoping issues:

* We will fix on OpenAI compatible API calls. For development, we will probably use Deepseek v4 Flash for cost savings.
* The input/output will be console based, with no graphics. Much later, we will extend to allow playing via Telegram bot, website, etc.
* Combat will probably need a special mode, and will be handled in the next phase of development.

## Proposed Architecture 

### Core Loop

Player Input
    │
    ▼
┌─────────────────────┐
│  Context Assembler  │ Retrieves current room, entities, and dynamic
│  (RAG + State join) │ state from the two stores; builds GM Briefing
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│  LLM Call 1: Ruling │ Receives GM Briefing + player input.
│  (structured JSON)  │ Outputs action + proposed soft-state patches └─────────────────────┘
    │
    ▼
┌─────────────────────┐
│  Engine Resolution  │ Validates action against world, rules, etc.
│  (deterministic)    │ Resolves rolls.  Applies hard-state changes
└─────────────────────┘ and in-scope soft-state patches.
    │
    ▼
┌─────────────────────┐
│  LLM Call 2: Prose  │ Receives chat log + GM Briefing + engine result.
│  (freeform text)    │ Narrates outcome. Cannot alter state.
└─────────────────────┘
    │
    ▼
   Player

### Components

State is stored in three databases:

* A Module Corpus acts like the printed book from a D&D adventure module. It contains the canonical adventure content: room descriptions, item stats, trap mechanics, NPC lore, exit graph. Read-only during play.
* A Hard Game State Store records runtime state: player HP, inventory, current room ID, triggered flags.
* A Soft Game State Store records fuzzier info: NPC attitude patches, environmental changes, a structured turn history. The LLM may propose soft-state patches in its structured ruling output, according to a fixed  schema to enforce discipline.

Joining these databases is a Context Assembler component. It is tasked with constructing a GM Briefing Document at each step: a prepopulated prompt block containing the current game state, a short curated event log, and the player's last message.

For the reference implementation (a single hand-coded five-room dungeon), no vector database is required. Retrieval is by deterministic ID lookup: the engine knows the player's current room and visible entities, so the Assembler fetches those nodes from the Module Corpus. (Later, we can explore semantic search.)

One tricky issue is how to handle raw chat history, which can include dangerous details that are hallucinated by the narrator or injected by the player, yet is important for the conversational feel of the tabletop GM experience. Proposed initial approach: supply LLM Call 1 with a structured (not verbatim) history consisting of the last 3–5 turns, with prominent disclaimers about possible non-canonicity; supply LLM Call 2 with verbatim logs, but with prominent instructions not to contradict engine rulings.

### World model

The internal world model is built from first principles around tabletop concepts, not interactive-fiction parsers:
 
* Rooms are nodes in a graph.
* Entities (items, NPCs, features, traps, exits) are typed objects with state, linked to room nodes.
* Actions are natural-language inputs parsed by the LLM into structured intent, then resolved by the engine against the graph and rules.

Incidentally, there are precedents for AI interaction with interactive fiction through the TextWorld and Jericho projects. However, these are treated as references for natural-language action parsing only; we will not adopt their structured action grammars.
