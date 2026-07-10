# Scenario-to-JSON Generation Instructions

This document is a prompt/checklist for an LLM to convert a
natural-language adventure scenario (e.g., `scenario.md`) into an
adventure module consisting of these structured JSON files:

- **`corpus.json`** — read-only adventure content (rooms, entities, mechanics)
- **`soft-state.json`** — initial narrative-oriented mutable state
- **`default-player.json`** — default player character (required when `corpus.stats` is present)
- **`hard-state.json`** — optional world-state override (usually omitted)

The schemas for these files are defined in:
- [`corpus.md`](corpus.md) for the Module Corpus
- [`events.md`](events.md) for the canonical event model and reaction event types
- [`hard-state.md`](hard-state.md) for Hard Game State
- [`soft-state.md`](soft-state.md) for Soft Game State
- [`actions.md`](actions.md) for actions (engine validation logic)

---

## Generation Workflow

Do NOT try to generate all three JSON files in one shot. Instead,
follow these six sequential steps.  Validate each step before
proceeding.

```
scenario.md
     │
     ▼
Step 1: Parse & Extract
     │  Output: scenario-map.md
     ▼
Step 2: Build Entities
     │  Output: draft corpus.entities block
     ▼
Step 3: Build Rooms
     │  Output: draft corpus.rooms block (references entities from Step 2)
     ▼
Step 4: Build Mechanics
     │  Output: draft corpus.mechanics block
     ▼
Step 5: Build default-player.json
     │  Output: complete default-player.json (if corpus has stats)
     ▼
Step 6: Build soft-state.json
     │  Output: complete soft-state.json
     ▼
Cross-file validation
```

Each step produces intermediate output in the adventure module folder.
Step 1 writes the Scenario Map — a document named `scenario-map.md`
that all subsequent steps read from.  Steps 2–4 produce draft corpus
blocks; Steps 5–6 produce the final `default-player.json` (when needed)
and `soft-state.json`.  After cross-file validation, assemble the complete
`corpus.json` from the draft blocks.

At the end of every step, run through the step's validation checklist.
If anything fails, **stop and fix before proceeding**.

---

## Step 1: Parse & Extract

**Objective:** make a structured list of everything that needs to be
modelled, including consistent IDs for all rooms, entities, flags,
interactions, state fields, entity tags, etc.  All IDs must be in
snake_case; `self` is reserved.

Read README.md and doc/intro.md, followed by the supplied scenario
(usually a Markdown file in adventures/MODULE-NAME/).

Then follow the specs below to write a Scenario Map (a text document,
not JSON), and save it to `scenario-map.md` in the adventure module
folder.  This will be the working plan for all subsequent steps.

To avoid context pressure, it is strongly recommended NOT to read the
schema docs in Step 1.  The schema will be read in Step 2, when we
write the actual JSON.

Follow Steps 1A–1H in order.  Each describes a top-level markdown
section for `scenario-map.md`.  You may also add implementation notes
anywhere in the document, as you deem appropriate.

### 1A. Adventure metadata

Write down, in a section at the top of the Scenario Map:

- *Title* — The title of the adventure.

- *Credits* — The author and other credits, including copyright info.

- *Introduction* — The opening paragraph (used verbatim).
  Write it up in second-person narrator voice.  No spoilers.

- *Adventure ID* — A short identifier for the adventure module (e.g.,
  `bag_of_holding`).  Used for save/load validation.

- *Atmosphere* — A few sentences about the world setting and narrative
  tone, synthesised from your reading of the scenario.  No spoilers.

If the scenario uses player stats, note:

- Which stats are used
- The resolution system (typically 5e)
- The initial player stats, including combat stats (level, current and
  max HP, etc.), and any starting inventory.  If the scenario leaves
  these unspecfied, yet requires them, choose reasonable defaults and
  note the omission in your post-task report.

### 1B. Rooms (Pass 1)

This section lists the rooms in the adventure.  Every visitable
location in the scenario should be a room.  Don't create rooms not in
the scenario, *unless* needed for gameplay; note deviations in your
report.  For each room, write out:

- **Room ID** — assign a globally-unique ID.

- **Room name** — a short identifying phrase for traversal.  Don't
  give consecutive rooms the same name, except under special
  circumstances (e.g., rooms in a featureless maze).

- **Description** — a prose description of what the room is, its key
  characteristics, and how it is connected to other rooms.  Keep it
  factual and succinct; this is for scenario mapping, not narration.

- **Start room?** — indicate the room where the player begins.
  There must be exactly one.

### 1C. Entities (Pass 1)

In this section, list out every gameplay-relevant entity (the player,
immobile features, NPCs, and items), specifying:

- **Entity ID** — assign a globally-unique ID.

- **Name** — a short identifying phrase (e.g., for player commands).
  For NPCs, capitalize both proper names ("Aragon") and generic names
  ("Goblin"); for other entities, only capitalize proper names.

  If a room has multiple similar NPCs without proper names,
  disambiguate.  If they lack distinguishing characteristics, fall
  back on numbering (e.g., "Goblin 1", "Goblin 2").

- **Type** — one of:
  - `player` — the player character (exactly one)
  - `npc` — character that can talk or fight
  - `feature` — immovable environmental object
  - `item` — object that can be picked up

- **Description** — a prose description of what this entity is, its
  location at game start (room, container, player inventory, etc.),
  and any other notable details.  Keep it factual and succinct.  We
  will fill in mechanical details later (§1G).  If the entity is a
  feature visible from multiple rooms, note which rooms it spans.

### 1D. Global Flags

Make a list of global flags: boolean conditions tracking world state
not tied to any specific room or entity.  In particular, consider
assigning global flags for:

- each major secret or piece of information the player can learn
  during the adventure ("the vizier is a lich", "password is foo").

- any plot-relevant or narrative event affecting many entities
  simultaneously ("the revolt has started", "night has fallen").

For each flag, specify:

- **Flag Name** — a globally-unique ID.
- **Description** — a prose explanation of the flag condition.
- **Initial Value** — the value at game start.

### 1E. Mechanics

Now list out mechanics — module-level (global) rules that are not
bound to a single room or entity.  For each mechanic, specify:

- **Mechanic ID** — assign a globally-unique ID
- **Kind** — one of these two:
  - **Game-over condition** — a rule leading to a game-over
  - **Mechanic** — state changes or encounter triggered by an event
- **Description** — how the mechanic works, and its effects

When writing the description, don't worry about the schema-following
implementation; the schema can accommodate many triggers and outcomes,
including branching outcomes.  Focus on crafting a precise *prose*
description, specifying flag IDs (§1D), room exit IDs (§1F), entity
tags (§1G), etc.  Backfill if necessary.

How to decide if an effect should be a mechanic, rather than a room-
or entity-scoped interaction or reaction (described below)?  Some
examples follow.

- **Encounters** (set-piece confrontations or action sequences, with
  branching outcomes and/or leading to combat) are usually mechanics.

  Example: a confrontation with three goblins, who ambush an unaware
  player, or flee if the player looks strong, or just start combat.
  If the encounter starts when the player arrives in the room, the
  trigger can be supplied by a separate room-scoped reaction (§1F).
  
  However, an encounter involving a single NPC (e.g., the NPC aggros
  when the player attacks) should be NPC-scoped.
   
- For an outcome arising directly from doing a special action (e.g.,
  pulling a lever), use a room/entity interaction instead (§1F,1G).

- For state changes that are a **reaction** to an event, if the
  reaction occurs only in a given room, use a room reaction (§1F); if
  it requires a given entity's presence, use an entity reaction (§1G).
  
  If the reaction doesn't fit such scoping, use a mechanic.  Examples:
  - player's HP dropping to ≤ 3 fires off a life ward
  - starting combat anywhere in a town makes all guards hostile
  - a zombie spawns at the start of each turn during nighttime

  Exception: an entity reaction cannot react to *its own* entity's
  death, so a consequence of an NPC dying must live elsewhere: a room
  reaction if it is location-bound, otherwise a mechanic.

- If a **game-over condition** is plot-significant and/or reachable in
  many different ways, use a mechanic.  Examples:
  - player wins on leaving the castle with the artifact
  - player loses if HP drops to ≤ 0.

  A game-over condition reached by a specific route (e.g., falling
  into *this* pit) should be room- or entity-scoped.

### 1F. Rooms (Pass 2)

Revisit the room list, and add the following info to each room:

- **Exits** — every way out.  For each, assign a room-unique exit ID,
  give a brief description (e.g., "through the north doorway"), and
  specify the destination room ID (§1B).

  Optionally, describe:
  - any conditions gating the exit's availability
  - any success check (e.g., stat check) needed to traverse the exit
  - any side-effects of succeeding or failing in traversing the exit

  Be specific: e.g., if a secret door appears when a lever is pulled,
  state the lever's entity ID, the interaction ID for pulling, etc.

- **Entities present** — list IDs of every entity present in the room
  at start (from §1C), including hidden ones (e.g., lurking thief).

  The player must be present in exactly one room.  Each item and NPC
  may be present in at most one room.  Features are allowed to be
  present in multiple rooms.  If an entity is inside *another entity*,
  it is not considered "present" in the surrounding room.

- **Special interactions** — assign a room-unique ID to any special
  interaction the player can have with the *room* (not an entity inside
  the room): e.g., shouting out a magic command word.

  Interactions can have availability conditions, success checks, and
  different results on success/failure.  Write a plain-text
  description, clearly specifying the game pieces affected: give
  specific flag IDs, room/entity IDs, state field names, etc.
  
  DO NOT define interactions similar to these generic player actions:
  `move` (traversing rooms), `examine` (cursory or in-depth study), or
  `transfer` (moving items to/from a container or location).

- **Reactions** — describe any consequential reaction tied to the
  *room* (not an entity in the room).  Each reaction can occur only if
  the player is in the room.

  Examples:
  - once a turn, the poison gas in the room damages the player.
  - when the player enters the room, three goblins attack.  The
    reaction can start combat directly, or, for a complex set-piece
    confrontation, trigger an encounter mechanic (1E).

  Assign each reaction an ID (globally-unique if it's a one-off
  reaction, room-unique otherwise).  Then write up a precise
  description of the reaction, including:

  - the trigger event: player entering the room, exit traversed, a
    special interaction is attempted, dialogue/combat start/end, item
    acquired/lost, global flag or entity state set/cleared, etc.
  - any additional gating condition for the reaction to occur
  - the consequences if the reaction indeed occurs
  - whether the reaction is one-off, or recurring

  Again, don't try to work out the schema-following implementation:
  focus on naming the specific entity/room IDs, etc.

- **State Fields** — assign a room-unique ID for each mutable property
  of the room, and specify the initial value (boolean, number, or
  string).  Don't invent these nilly-willy; focus on properties needed
  for gameplay or narration: e.g., `filled_with_poison_gas`.  Do not
  use the reserved fields `is_current` and `visited`.

- **On-Examine Effects** — describe any effects triggered by the
  player examining the room (the room itself, not an entity in it),
  possibly gated by an availability condition or success check.
  Example: viewing a dusty storeroom, and deducing that nobody has
  come through in years (a plot point).

While writing up the descriptions, you may find it necessary to add
extra global flags (§1D), update previous rooms (e.g., by adding more
state fields and reactions), etc.  Do so as necessary.

### 1G. Entities (Pass 2)

Revisit the entity list, and add the following to each entity:

- **Tags** — any semantic features relevant to gameplay.
  Assign the special tag `container` to any entity that acts as a
  container with open/close functionality (e.g., a chest).  A
  tabletop, with no open/close function, should not have this tag.

  Other tags are defined at your discretion based on adventure
  requirements (e.g., items with `heavy` tag can trigger a pressure
  plate).  Do not define gameplay-irrelevant tags.

- **Equippable?** — if this entity is an item that can be equipped
  (weapon, armor, shield, ring, etc.), write a textual description of
  how it is worn or wielded, and any relevant properties from the
  scenario (damage expression, stat bonuses, AC bonus, restrictions
  such as "two-handed" or "incompatible with shields").

- **Contained Entities** — if this entity contains other entities
  (e.g., a drawer holding a key, a rubbish pile holding a gem), list
  the entity IDs inside.  Use the descriptions in §1C as a guide.

- **Special interactions** — assign an entity-unique interaction ID to
  every special action the player can perform on the entity (e.g.,
  pulling a lever).  No need for synonyms; one interaction ID per
  gameplay-relevant interaction.

  Include an `open` and/or `close` interaction if it's a container
  that can be directly opened/closed by the player.

  DO NOT define interactions for built-in generic actions: `attack`,
  `examine`, `talk`, or `transfer`.

- **State fields** — list each of the entity's scenario-relevant
  mutable properties, and the initial value (boolean, number, or
  string).  Some state fields, listed below, have special engine
  effects, but you can also define custom ones.

  NPC state fields:
  - `alive` (boolean) is required
  - `attitude` (number) if able to change attitude to the player
  - `hidden` (boolean) if concealable; see below
  - `following` (boolean) if a possible companion
  - `current_hp` (number) if able to engage in combat
  - custom state fields (e.g., `charmed`)

  To model an NPC leaving the scene, set its `location` to `null` via a
  result or reaction (e.g., `"set_entity_state": { "spider": { "location":
  null } }`).  This removes the NPC from `room_contains`, which in turn
  excludes it from combat and entity-scoped reactions.

  Non-NPC state fields:
  - `hidden` (boolean) if concealable; see below
  - `open` (boolean) for container with open/close functionality,
    with a `container` tag; initial value is typically false
  - custom state fields (e.g., `locked`, `lit`)

  The `hidden` state field denotes explicit concealment (e.g., a thief
  hiding in shadows, or sword buried in rubble).  Do not use it for
  items that are out of view due to being inside a closed container.

  For each custom field, note down its meaning.

- **Reactions** — describe any consequential reaction tied to the
  entity.  Each reaction can occur only if the entity is in the
  current room (and, for an NPC, alive and active).

  Examples:
  - if an item is picked up, inflict a curse on the player
  - if an NPC's attitude drops, the NPC attacks
  - if an NPC exits dialogue, it dies

  Assign each reaction an ID (globally-unique if it's a one-off
  reaction, entity-unique otherwise).  Describe the reaction,
  including:

  - the trigger event
  - any additional gating condition for the reaction to occur
  - the consequences if the reaction indeed occurs
  - whether the reaction is one-off, or recurring

- **On-Examine Effects** — describe any effects triggered by the
  player examining the entity, possibly gated by a condition or stat
  check.  Note that this field belongs on the thing being examined,
  *not* the room containing it: e.g., when the scenario says "upon
  examining the statue, the player notices...", the examination effect
  belongs on the statue entity.

For items, also note:

- **Take Check** (optional) — availability conditions or success
  checks for the player to take the item.  Can have failure effects.

For NPCs, also add descriptions for the following:

- **Combat Stats** — if the NPC is combat-capable and the scenario
  provides a stat block (HP, AC, attack bonus, damage dice, initiative
  modifier, flee DC, etc.), write it down verbatim.  Note any special
  combat features, such as on-hit effects.  If the scenario doesn't
  give exact numbers, record whatever info is provided.

- **Behavior** — if the NPC can fight, enumerate its encounter rules.
  Encounter rules specify the ways a combat encounter might unfold,
  either when the player attacks the NPC, or vice versa.  Each rule
  specifies a set of conditions (e.g., "player has a weapon and NPC is
  hostile"), and the outcome (e.g., "launch multi-turn combat").  The
  first encounter rule with matching conditions is dispatched.

  Common encounter rule outcomes are:
  - begin multi-round combat (NPC needs combat stats)
  - player auto-death
  - NPC flee or auto-death
  - stat check with success/failure branches (flee, auto-death)

  For multi-enemy fights, use one of these idioms:
  - **`combat_group`** — give every member of a homogeneous band (e.g.,
    three goblins) the same string tag.  Attacking any present, living
    member pulls the rest of the band into combat.  Followers (NPCs with
    a `dialogue` block whose state says `following: true`) are treated as
    allies and are never auto-pulled, even if they share the tag.
  - **`start_combat`** — on an encounter result, a list of extra enemy
    entity IDs to fight alongside the source (e.g., the captain and two
    archers).  Use `[]` to fight the encounter source alone.  The list
    expands by `combat_group` too, so listing one band member will
    pull the whole present band; to select a subset, omit `combat_group`.

  Also note any effects of NPC fleeing (e.g., setting a flag, or
  moving the NPC to another room).

  You may omit the aggro specification to accept the default rule:
  if the NPC has combat stats, begin turn-based multi-round combat;
  otherwise, the NPC dies.

- **Dialogue Paths** — for dialogue, if the NPC talks.
  A dialogue path is any special plot/gameplay-relevant line of
  conversation the player can engage the NPC with: e.g., bribing a
  guard to pass a gate, or convincing a prince his vizier is evil.

  Assign an NPC-unique ID for each dialogue path, and describe:

  - availability conditions for the dialogue path
  - any success gating (e.g., stat check)
  - how the NPC reacts if successful/unsuccessful (just guidelines and
    key details; no need for verbatim dialogue; the GM will fill in)
  - any additional effects of success/failure, such as setting flags,
    or triggering mechanics/reactions

- **Will-Reveal Topics** — for dialogue, if the NPC talks.
  Assign an NPC-unique ID for each major topic the NPC might divulge
  information on.  Unlike a dialogue path, such a topic usually has no
  immediate mechanical effect.

  Example: a guard may have a dialogue path `bribe_to_enter` (player
  pays to get past — a mechanic), and a topic `recent_visitors`
  (reveals which visitors have come through — just useful info).

  Describe (i) the gating conditions for the NPC to discuss the topic,
  (ii) what the NPC conveys (non-verbatim), and (iii) consequences.
  For consequences, best practice is to set a global flag (§1D) to
  track the player's knowledge (different NPCs giving similar info can
  set the same flag).  Will-reveal topics can also alter entity state
  fields, but cannot trigger reactions.

- **Knowledge** — for dialogue, if the NPC talks.
  A list of canonical non-plot-relevant bits of knowledge possessed by
  the NPC, to pin down details you don't want the GM to ad-lib.

### 1H. Cleanup

Go through the lists you have constructed, and check that IDs are
consistent, every ID required by a mechanic is defined, etc.

For each game mechanic, check that you have assigned it to the right
host (global, room, or entity), and that it accurately captures the
spirit of what's written in the scenario.  Deviations from the
scenario may be OK, but should be noted down clearly in:

- an Errata section at the bottom of the Scenario Map
- your task report

Revise as necessary.

---

### Step 1 validation checklist

Check the following before proceeding to Step 2.  The Scenario Map
(`scenario-map.md`) will be the blueprint for all later steps;
catching gaps here avoids rework downstream.

#### Coverage and Consistency

- [ ] Every room in the scenario is captured in the room list (§1B)
- [ ] Every entity in the scenario is captured and classified with a
      valid type (`player`, `npc`, `feature`, `item`) (§1C)
- [ ] Every item entity is something the player can possibly put into
      inventory; otherwise it should be a `feature` (§1C)
- [ ] Every win/loss condition and global effect/mechanic from the
      scenario is captured in the global mechanic list (§1E)
- [ ] All IDs (rooms, entities, flags, mechanics, reactions, etc.) are
	  in snake_case and appropriately disambiguated

#### Structural correctness

- [ ] Exactly one room is the start room (§1B)
- [ ] Exactly one entity has `type: "player"` (§1C)
- [ ] No non-NPC entity has dialogue or aggro plans (§1G)
- [ ] Every mechanic that can be triggered by NPC dialogue has a
      Dialogue Path trigger (§1G), with consequences planned via
      reaction, global flag, etc.
- [ ] Every important piece of info that can be divulged by an NPC, if
      not assigned a Dialogue Path, should have a Topic ID (§1G), and
      (usually) a global flag to track the player's knowledge (§1D)
- [ ] Every NPC whose attitude to the player can shift should have an
      `attitude` state field (§1G).
- [ ] Every NPC with `behavior` encounter rules specifying multi-turn
      combat should have combat stats (§1G)
- [ ] `start_combat` is only used inside encounter
      rules (`entity.aggro` or `mechanic.rules`)
- [ ] Every id in a `start_combat` list belongs to an NPC with combat stats
- [ ] Every NPC sharing a `combat_group` value has combat stats and is an NPC
- [ ] Mechanic encounters that enter combat list enemies via
      `start_combat` or `combat_group` (the mechanic id is not a combatant)

#### Flags, state, and tags

- [ ] Every global flag referenced (by global mechanic, Event
      Reaction, On-Examine Effect, Dialogue Path, or Topic, etc.)
      should have an entry in the list of global flags (§1D).
- [ ] If a mechanic (Event Reaction, dialogue, etc.) refers to a
      custom (non-standard) state field for a room or entity, that
      room or entity must have the state field prepped, with an
      initial value and description (§1F, §1G).
- [ ] If any mechanic refers to a semantic tag, there should be one
      or more entities with that tag defined.
- [ ] Every entity with `hidden: true` at start has a planned
      mechanism to unhide it (otherwise it is permanently invisible)
- [ ] Every container-like entity has the `container` tag, and the
      `open` state field defined

#### Mechanics

- [ ] Stat checks identified and resolution system noted (or "no stats")
- [ ] Every global mechanic is correctly classified: game-over
      condition or mechanic with rules/reactions
- [ ] Event-driven reactions scoped correctly (room, entity, or global
      mechanic)

#### Exits

- [ ] Hidden exits have a planned flag-based reveal mechanism (companion
      interaction sets a flag, exit condition requires that flag)
- [ ] One-way exits have a planned return path (or a narrative reason
      they are permanently one-way)

---

## Step 2: Build Entities

**Input:** Scenario Map from Step 1 + Corpus Schema
**Output:** Corpus metadata, global flags, and entities data

In preparation for this step, read the latest version of the Scenario
Map (`adventures/MODULE-NAME/scenario-map.md`), the corpus schema
(`schema/corpus.md`), and any other necessary subsidiary schema
referenced therein.

You will now write the corpus (`adventures/MODULE-NAME/corpus.json`),
starting with the metadata and global flags, followed by the entities
block.  The Scenario Map should be your primary source; only refer to
the original scenario to look up missing information.

### 2A. Metadata and Global Flags

Populate the `adventure` field using the information from the top of
the Scenario Map: id, title, credits (author, source, license),
introduction, and atmosphere (setting, tone).

Next, construct `flags_declared` from the list of Global Flags in the
Scenario Map.  Plain strings start `false`; use single-key objects to
start a flag `true`.  This list is used for validation and to seed the
initial world state.  If, during subsequent implementation, you find it
necessary to add extra global flags, keep `flags_declared` updated.

### 2B. Entity Data

You must now construct a JSON definition for each entity listed in the
Scenario Map, following the corpus schema.

Here are some general tips for writing the JSON objects, followed by
specific tips for items (§2C), features (§2D), the player (§2E), and
NPCs (§2F).  NPCs are the most complicated, so write them carefully.

While constructing the JSON objects, you may find it necessary to
deviate from the Scenario Map, e.g. by adding extra unforseen elements
(flags, entity/room state fields, reactions, etc.).  Remember these
deviations, and revise the Scenario Map at the end of Step 2 (§2H)
before going to Step 3.  Major deviations must be surfaced in your
task report.

#### Description

When generating each entity's `description`, do not just translate the
description field from the Scenario Map.  Take a holistic view, and
write a timeless, spoiler-free description of the entity.  This
description is provided to the GM whenever the entity is present, and
must be factual and independent of the entity's state (e.g., dead or
alive).  You may inject small details to add flavor, without
contradicting the scenario.

Example: "A massive black spider, about the size of a large dog, with
eight glittering red eyes, sharp mandibles, and eight hairy legs".

Do not be overly poetic; the GM handles atmospheric narration.

Avoid situational framing that can be invalidated during the game:
e.g., "It lurks in the shadows..." is no good if the creature can be
killed.

#### Interactions

The Scenario Map may have planned some special interactions – discrete
non-generic actions the player can perform on the entity.  For each,
construct an interaction object to put into `interactions`.

Interactions can be gated by availability conditions and/or success
checks, and can have distinct success and failure results.  These
results can set flags, altering entity states, etc.  Optionally, the
gating/results can be modified if the player uses certain items as
part of the interaction.

Example: forcing a stuck door.  Bare-handed is hard; a crowbar helps;
any improvised tool is somewhere in between:

```json
{
  "id": "force_door",
  "label": "Force door open",
  "description": "Shoulder the door until the frame splinters.",
  "check": {
    "type": "stat_check",
    "stat": "STR",
    "target": 18,
    "repeatable": true
  },
  "success": {
    "narrative": "The door bursts open with a crash.",
    "set_flag": { "door_forced": true }
  },
  "failure": {
    "narrative": "The door rattles but holds firm."
  },
  "using_results": {
    "crowbar": {
      "check": { "type": "stat_check", "stat": "STR", "target": 12, "repeatable": true },
      "success": { "narrative": "You wedge the crowbar into the frame and lever the door open.", "set_flag": { "door_forced": true } },
      "failure": { "narrative": "The crowbar slips, but the frame groans." }
    },
    "*": {
      "check": { "type": "stat_check", "stat": "STR", "target": 15, "repeatable": true },
      "success": { "narrative": "You bash the door with whatever you have at hand and it yields.", "set_flag": { "door_forced": true } },
      "failure": { "narrative": "Your improvised tool does little damage to the stout door." }
    }
  }
}
```

Notes:

- If the action always succeeds (e.g., flipping a simple switch), use
  `result` with no `check`.

- Use `condition` to gate availability: e.g., an "open" interaction on
  a chest can be gated on `entity:chest.locked == false`.

- Use `skip_check_if` to bypass gating and checks entirely.

- Set `repeatable: false` for tasks where failure is permanent: the
  engine will block any retry after failure.  For tasks with one-off
  success (e.g., smashing a pot), use `condition` as described above.

  If the scenario and Scenario Map are ambiguous about whether an
  interaction should be one-off success and/or failure, use your
  judgment; if the decision is tricky, note in your report.

- If the optional `failure` field is omitted, the engine returns a
  generic "nothing happens" narrative on failure.

- When an interaction behaves differently depending on what the player
  uses, define a `using_results` map.  Each key is an item entity ID
  (not soft-item name); the special key `"*"` matches any `using`
  value not explicitly listed.  The engine substitutes the matched
  override for the interaction's `check`, `success`, `failure`, and
  `result` — it replaces them entirely, it does not merge.

#### State fields

Using the state fields planned in the Scenario Map, construct the
entity's `state_fields`.  Each field must have a `type`, a terse but
informative `description`, and — wherever the initial value differs
from the type default or reserved-field default — an explicit
`initial` value.  The engine generates the initial world state directly
from these declarations, so `initial` is the canonical source of truth
for starting values.

Example:

```json
"state_fields": {
  "alive": { "type": "boolean", "initial": true, "description": "Whether the spider is alive." },
  "attitude": { "type": "number", "description": "Attitude toward the player, -10 to 10." },
  "hidden": { "type": "boolean", "initial": true, "description": "Whether the entity is hidden from view." }
}
```

Notes:

- `initial` is optional.  When omitted, the engine uses the reserved-field
  default if one exists (e.g., `alive` defaults to `true`, `current_hp`
  defaults to `combat.hp`); otherwise it falls back to the type default
  (`false` for boolean, `0` for number, `""` for string).  Attitude has
  no special default — set `initial` explicitly when the NPC's starting
  disposition differs from 0.

- Fields whose starting value matches the default do not need an
  `initial` key, though including it explicitly is harmless and
  recommended for clarity.

- If a `hard-state.json` override is supplied, it can override any corpus
  `initial` value.  In the normal workflow, `hard-state.json` is omitted
  and the generated world state is used.

If an entity is concealed (initially, or subsequently in the
adventure), it must have a `hidden` state field: e.g., a lurking
enemy, or a sword in long grass.  When `hidden` is true, the engine
omits the entity even from the GM (to avoid leakage).  However, don't
use `hidden` to describe entities that are masked just by being in a
closed container (see Containers, below).

**Timing:** when a result directly sets `hidden: false` via
`set_entity_state` (e.g., in an `on_examine` event or interaction
result), the entity becomes visible to the narrator in the same turn.
If the reveal is gated through a separate reaction on `flag.set` that
then sets `hidden: false`, the entity does not appear until the next
turn, because state-change events fire during deferred end-of-turn
dispatch.  Prefer the direct approach for dramatic immediacy, unless
the scenario requires the reveal to be deferred.

#### Entity Reactions

The `reactions` field is used for event-driven entity behavior.  To
help translate the Scenario Map's reaction descriptions into JSON, see
`events.md` for the specs on trigger events.  Entity reactions only
trigger if the entity is in the current room, alive, and present.

Reaction `result` objects support the same fields as interaction
results: `narrative`, `set_flag`, `set_entity_state`, etc.  Use
whichever best fits.

Example of an attack on sight reaction:
```json
"reactions": [
  {
    "id": "goblin_ambush",
    "on": "room.entered",
    "effect": { "trigger_encounter": "goblin_attack" }
  }
]
```

Example of a post-dialogue state change:
```json
"reactions": [
  {
    "id": "fly_dies_after_talk",
    "on": "dialogue.ended",
    "condition": { "require": "event:npc_id == stuck_fly" },
    "effect": {
      "result": {
        "set_entity_state": { "stuck_fly": { "alive": false } },
        "narrative": "The fly's groaning ceases. Its tiny body goes still."
      }
    }
  }
]
```

#### Examination

The On-Examine Effects stated in the Scenario Map should be translated
into `on_examine` effects.

If the scenario is ambiguous about whether the `on_examine` effect
triggers on an ordinary or rigorous examination, use your judgment: an
ordinary examination suffices if the discovery is made just by
looking, but a rigorous examination is needed if it involves a
physical search.  Note how you resolved the ambiguity in your report.

Often, `on_examine` is used to reveal a hidden entity, possibly gated
by a stat check:

```json
{
  "id": "notice_spider",
  "condition": { "require": "entity:spider.hidden == true" },
  "check": {
    "type": "stat_check",
    "stat": "WIS",
    "target": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You notice eight glittering eyes watching you from above.",
    "set_entity_state": { "spider": { "hidden": false } },
    "set_flag": { "spider_noticed": true }
  }
}
```

For containers (see below), examination should not open the container
as an effect.  Opening should be an explicit player action (usually
implemented as an interaction type on the container entity).  Even a
rigorous examination should be interpreted as a physical examination
of the container's exterior, short of opening it.

An entity can have multiple `on_examine` events. Each is evaluated
independently in definition order, and every successful event's
narrative is appended.  This is useful when there are multiple secrets
to be uncovered by examining a single entity.

### 2C. Item entities

For every item entity, `name` is required and should be a noun/phrase
referring unambiguously, module-wide, to the item.  It is used for
player commands, inventory, etc.  If not a proper name, use lower
case.  Can use adjectives to disambiguate (e.g., "ornate sword"), or,
as a last resort, numbers (e.g. "rusty sword 1").

The semantic Tags listed in the Scenario Map go into the `tags` field.

For equippable items, define an `equip_block` field based on the
textual description in the Scenario Map.  If the scenario provides
incomplete item stats, use your best judgment, and surface the issue
in your task report.  Note that `equip_block.equip_tags` drive the
equipment system (what can be equipped, damage expressions, AC, etc.),
and are *not* the same as semantic tags.

If a mechanic or reaction is used to gate the player picking up the
item (e.g., STR check to pull a sword from a stone), use `take_check`
on the item entity.  The engine resolves that check when the player
tries a `transfer` action to take the item.  For a one-time success gate
(pass the check once, then the item is picked up freely thereafter),
use `take_check.gating` with a flag that `success` sets:

```json
"take_check": {
  "gating": { "require": "flag:sword_claimed == false" },
  "check": { "type": "stat_check", "stat": "STR", "target": 17, "repeatable": true },
  "success": {
    "narrative": "You wrench the sword from the stone.",
    "set_flag": { "sword_claimed": true }
  },
  "failure": {
    "narrative": "The sword won't budge."
  }
}
```

For a permanent one-attempt gate (failure locks you out), set
`check.repeatable` to `false`.

### 2D. Feature entities

For every feature entity, `name` should be in lower case if not a
proper name.  It only needs to be unambiguous at the level of the
room(s) the feature occurs in: e.g., two different rooms can have
features named `fountain`, with different entity IDs.

For features spanning multiple rooms, list the entity ID in the
`contains` array of each room where the feature appears.

#### Containers

A common pattern: an entity (usually a feature) such as a chest or
cabinet can be opened/closed, and contains other entities (usually
items).  The container is initially closed, so the contents are
concealed.

The engine provides special support for this case:

- The container entity should have a `container` tag AND `open` as a
  state field.  When `open` is false, the engine hides its contents
  (`contains` and `soft_items`); when `open` is true, the
  contents are surfaced.

- To let the player open/close the container, give the container
  entity interactions called `open` and `close`, which alter the
  `open` state as an effect.

- Alternatively, the container's `open` state can be altered by
  reactions, mechanics, etc.

Example — a chest containing a gem:

```json
"chest": {
  "type": "feature",
  "description": "A decrepit wooden chest, its surface covered in dust.",
  "tags": ["container"],
  "state_fields": {
    "open": { "type": "boolean", "description": "Whether the chest is open." }
  },
  "contains": ["glowing_gem"],
  "interactions": [
    {
      "id": "open",
      "label": "Open",
      "description": "Open the chest.",
      "condition": { "require": "entity:chest.open == false" },
      "result": {
        "narrative": "You lift the lid of the chest.",
        "set_entity_state": { "chest": { "open": true } }
      }
    },
    {
      "id": "close",
      "label": "Close",
      "description": "Close the chest.",
      "condition": { "require": "entity:chest.open == true" },
      "result": {
        "narrative": "You close the lid of the chest.",
        "set_entity_state": { "chest": { "open": false } }
      }
    }
  ]
}
```

Note that the `hidden` state of any individual contained entity is
still respected.  Thus, items can remain concealed (by darkness,
magic, etc.) even inside an open container.

Doors, windows, and other non-container entities may still use `open`
as a state field without the `container` tag.  The engine only applies
container gating when *both* the tag and the state field are present.

### 2E. Player entity

The player's `description` should be a general description of the
player character (from their perspective, used when examining
themself).  If no information is provided by the scenario, write up
something vague or nondescript.

The player entity can have standard `state_fields` like `alive` (if
death is possible).  These fields seed the generated world state; an
optional `hard-state.json` override can adjust them later.  No
`dialogue`, `aggro`, `interactions`, or `on_examine`.
The player usually starts with an empty `equipped` list.

### 2F. NPC entities

#### `follower` config

If an NPC can become a follower (via `state_fields.following`), and
the scenario says they refuse to enter certain rooms, add a
`follower` object with a `blacklist` field listing room IDs they won't enter:

```json
"korbar": {
  "type": "npc",
  "follower": { "blacklist": ["secret_compartment"] }
}
```

When the player moves into a blacklisted room while the NPC is
following, the engine automatically clears the NPC's `following` state
and adds a narrative note.  If the NPC should resume following when
the player returns to the current room, use an on-entry reaction.

#### Combat Stats and Combat Encounters

If the Scenario Map supplies a set of NPC Combat Stats, format them
into a `combat` block: e.g.,

```json
"goblin_scout": {
  "type": "npc",
  "combat": {
    "hp": 7,
    "ac": 12,
    "atk": 4,
    "dmg": "1d6+2",
    "initiative_mod": 2,
    "flee_dc": 10
  },
  "state_fields": {
    "current_hp": { "type": "number", "description": "Current hit points." }
  }
}
```

Any NPC with a `combat` block must also declare `current_hp` in
`state_fields`; the engine initializes it to `combat.hp` when generating
world state.  The validator requires the field to be present.

If an NPC can engage in a combat encounter with the player (by either
side attacking), such encounters are typically resolved by either
single-turn resolution (e.g., one-shot kills), or multi-round combat.
Dispatch occurs via `aggro.encounter_rules`; the first matching
rule takes effect.  Construct these encounter rules from the NPC's
Aggro description in the Scenario Map, or accept the default rule
(start combat if NPC has a `combat` block, NPC dies otherwise).

If the Scenario Map noted `on_flee` aggro for the NPC, encode it in
`aggro.on_flee` with any flags or entity state changes it should
apply and a short narrative effect description.

Here is an example of a mechanical (one-turn) encounter:

```json
"encounter_rules": [
  {
    "condition": { "require": "tag:weapon" },
    "check": { "type": "stat_check", "stat": "STR", "target": 10, "repeatable": true },
    "success": {
      "narrative": "You land a solid blow. The goblin hisses and flees.",
	  "set_entity_state": { "goblin": { "location": null } }
    },
    "failure": {
      "narrative": "The goblin strikes back! Its cleaver goes through your neck.",
      "game_over": { "type": "lose", "trigger": "goblin" }
    }
  },
  {
    "condition": { "unless": "tag:weapon" },
    "result": {
      "narrative": "Bare-handed, you cannot fend off the goblin's attack. It quickly overcomes you.",
      "game_over": { "type": "lose", "trigger": "goblin" }
    }
  }
]
```

#### NPC dialogue

For every conversational NPC, write a `dialogue` block.
Its contents – `personality`, `on_encounter`, `can`/`cannot` arrays,
`knows`, etc. – guide the GM on how the NPC talks, behaves, and
responds to the player.  Each string should be concise, informative,
and factual.  No embellishment: the GM handles injecting color.

Example of a `cannot` array:

```json
["will never agree to fight the spider; secretly scared of spiders, but reluctant to admit it", "will not follow into the secret compartment (can't fit through flap)"]
```

Translate the `dialogue_paths`, `will_reveal`, and `knows` fields from
the Dialogue Paths, Will-Reveal Topics, and Knowledge descriptors in
the Scenario Map.  The GM uses this info to narrate how the NPC
conversations go, so don't be vague.  Dialogue Paths should usually
have a side-effect.  Will-Reveal Topics often have a side-effect
(typically setting a global flag to track the player's knowledge), but
purely informational topics are allowed.

Example of a fairy with a dialogue path allowing it to be flattered
with a CHA check:

```json
"dialogue_paths": {
  "flatter": {
    "description": "Praise the fairy's beauty.",
    "condition": { "require": "entity:fairy.attitude >= 0" },
    "check": { "type": "stat_check", "stat": "CHA", "target": 12, "repeatable": true },
    "success": {
      "narrative": "The fairy preens as you praise her.",
      "adjust_attitude": { "fairy": 1 }
    },
    "failure": {
      "narrative": "The fairy rolls her eyes."
    }
  }
}
```

Example of a will_reveal structure:

```json
"will_reveal": {
  "bag_mechanism": {
    "description": "Korbar explains how the Bag of Holding works — it's a dimensional pocket.",
    "conditions": ["entity:korbar.attitude >= 1"],
    "set_flag": { "bag_of_holding_learned": true }
  },
  "secret_compartment": {
      "description": "Korbar points out a handkerchief in the nearby pile, and says it hides a flap leading to a secret compartment with a key.",
    "conditions": ["entity:korbar.attitude >= 3"],
    "set_flag": { "handkerchief_revealed": true }
  }
}
```

### 2G. Soft Items

> TBD: instructions to generate a list of soft items for
> container-type features, and NPCs...

### 2H. Cleanup

> TBD: instructions to keep global flags up to date, and revise
> Scenario Map to reflect updates...


---

### Step 2 validation checklist

- [ ] Every item entity has a non-empty `name` (display name; required by the engine)
- [ ] State fields for `alive` are `true` for creatures that start alive
- [ ] Every NPC with a `combat` block has `current_hp` in `state_fields`
- [ ] Every NPC with `dialogue` has `attitude` in `state_fields`
- [ ] Every NPC with `dialogue` has `attitude_limits` declared
- [ ] Every `will_reveal` entry uses valid condition syntax
- [ ] Every `set_flag` in `will_reveal` sets a value matching the flag's
      type (always boolean)
- [ ] Every `set_entity_state` in `will_reveal` sets a field declared in the
      target entity's `state_fields`
- [ ] Entities that span multiple rooms appear in each room's `contains`
      (cross-check with Step 3 once rooms exist)
- [ ] Entity `reactions` use valid event types (see `events.md`)
- [ ] Entity `reactions` using `"self"` in `trigger_encounter` or
      `trigger_dialogue` are on entities of the correct type (encounter for
      any, dialogue for `npc` only)
- [ ] NPCs that die, flee, or change state when dialogue ends have a
      `dialogue.ended` reaction (not the removed `on_dialogue_exit` field)

---

## Step 3: Build Rooms

**Input:** Scenario Map + corpus schema + corpus draft from Step 2.
**Output:** The `rooms` block for `corpus.json`.

For each room listed in the Scenario Map, produce a complete room
definition following the corpus schema (§1 Rooms).  Several tips are
provided below:

### 3A. Room description

Write a full present-tense `description` for the room, which will be
used for both room entry and examination.  Do not rely solely on the
room description from the Scenario Map, but craft a description based
on your holistic understanding of the scenario.

Focus on facts, notable features, as well as key sensory details: what
the player sees, hears, smells, etc.  You may inject details to add
flavor, without contradicting the scenario.  Excessively poetic
language is not necessary; the GM can make it more atmospheric.

Example: "A large square courtyard ringed with overgrown laurel trees.
It has a dilapidated air, with thick weeds sprouting through the
cracks between the flagstones on the ground."

The description should remain accurate regardless of the game state.
DO NOT include entities that might leave the room (e.g., NPCs that
might move elsewhere), or invalidate the description in some way; the
GM can weave in info about entities present.

DO NOT include hidden information, clues gated behind a rigorous
search or NPC reveal, or spoilers.

### 3B. Entities Present

The `contains` field should list the IDs for all entities
present in the room at game start, **including hidden entities**.

Exclude entities contained in other entities: e.g., if a key is inside
a box in the room, the key should NOT be in `contains`.

### 3C. Exits

The `exits` field should list ALL possible exits a room can have over
the course of gameplay.

To make an exit hidden until certain conditions are met, use the
`condition` field.  This is a Condition expression; the exit is
hidden from the player until the condition evaluates to true.
When absent, the exit is always visible.

Typically, `condition` checks a global flag, and there is a
companion effect (a mechanic, reaction, etc.) that sets this flag to
reveal the exit.  Example:

```json
"condition": { "require": "flag:curtain_opened == true" }
```

If an exit is visible but not necessarily traversible, use the
optional `traversal_check` field.  This gates the traversal *attempt*:
the exit is visible but the player can fail to use it.  Examples:
climbing up a wall, or dragging a heavy body into the next room.  If
the gating is due to a temporary obstacle, specify a `skip_check_if`
condition that checks a flag; when the obstacle is removed, set/clear
that flag (via a mechanic, reaction, etc.).

Set the `one_way` field based on your understanding of the exit's
description (e.g., dropping through a trapdoor).  This field has no
gameplay effect: it only adds an indicator telling the player that the
exit *seems* to be one-way.

Exits have no `reactions` field.  To define a reaction to a traversal
event, used a room-scoped reaction (§3E).

### 3D. Examination

The On-Examine Effects stated in the Scenario Map should be translated
into `on_examine` effects.

If the scenario is ambiguous about whether the `on_examine` effect
triggers on an ordinary or rigorous examination, use your judgment: an
ordinary examination suffices if the discovery is made just by
looking, but a rigorous examination is needed if it involves a
physical search.  Note how you resolved the ambiguity in your report.

Sometimes, there is a semantic overlap between examining a room and an
entity (usually a feature) inside it.

- If there's strong overlap between examining the room and the entity,
  the room and entity can have redundant `on_examine` effects (use
  flags to avoid double discoveries).  Example: in a room filled with
  spider webs, searching the room or the webs has the same effect.

- If the're a partial overlap, a useful pattern is to make the room's
  `on_examine` produce a narrative hint to the player, indicating that
  there's something interesting about the entity.  This guides them to
  examine the entity directly to get the actual discovery.

A room can have multiple `on_examine` events. Each is evaluated
independently in definition order, and every successful event's
narrative is appended.  This is useful when there are multiple secrets
to be uncovered by examining a single room.

### 3E. Room Reactions

To implement the room-scoped reactions planned in the Scenario Map,
consult `events.md` for the spec of triggering events.  Room-scoped
reactions can only fire when the player is currently in that room.

When the player moves from room A to room B via an exit, events fire
in this sequence, and the reaction-scoping room changes at the moment
of arrival:

| Event | Player location | Whose reactions fire |
|-------|----------------|-----------------------|
| `traversal.attempted` | A | Room A only |
| `traversal.succeeded` | A | Room A only |
| `traversal.failed` | A | Room A only |
| `room.entered` | B | Room B only |

Therefore, put entry-trigger reactions on the destination room (using
`room.entered`), and traversal-related reactions on the source room
(using `traversal.attempted`, `traversal.succeeded`, or
`traversal.failed`).

Entering a room emits `room.entered` with `room_id` set to the
destination.  Immediate-phase reactions are permitted on
`room.entered`, and fire before the entry narration is built — useful
for blocking or redirecting narration.

Example — portcullis slams shut on entry:

```json
{
  "id": "portcullis_slam",
  "on": "room.entered",
  "condition": { "require": "event:room_id == castle_gatehouse" },
  "phase": "immediate",
  "effect": {
    "result": {
      "narrative": "The portcullis crashes down behind you.",
      "set_entity_state": { "portcullis": { "closed": true } }
    }
  }
}
```

This reaction lives on the room `castle_gatehouse`, and fires the
moment the player arrives, before the room description is narrated.
Use `"once": true` (or a custom condition) to make this one-shot.

Example — goblin ambush on entry:

```json
{
  "id": "goblin_ambush",
  "on": "room.entered",
  "effect": { "trigger_encounter": "goblin_ambush_encounter" }
}
```

Example — falling damage on failed ledge climb:

```json
{
  "id": "ledge_fall_damage",
  "on": "traversal.failed",
  "condition": { "require": "event:exit_id == climb_to_ledge" },
  "effect": {
    "result": {
      "narrative": "You lose your grip and tumble to the ground.",
      "player_damage": "1d6"
    }
  }
}
```

This reaction lives on the source room, which contains the
`climb_to_ledge` exit.  On failure, the player stays in the room (from
the traversal failure) and takes damage (from the reaction).

As an exception, when the player flees combat by using `move`,
`traversal.succeeded` reactions are not evaluated, so do not rely on
such reactions for cleanup that must always fire on combat escape.
Use a `room.entered` reaction on the destination room instead.

Since `room.entered` fires on all arrivals, regardless of origin, some
trickery is needed if you want to react to arrivals from a specific
entrance:

- Use `traversal.succeeded` on the source room with a condition on
  `event:exit_id`.  This fires with the player still in the source
  room, so it cannot read the destination room's state.

- Alternatively, use `set_room_state` in the exit's `success` result
  to record the entry direction (e.g., `{ "from": "courtyard" }`) and
  use a room condition like `"room:bunkhouse.from == courtyard"` in
  the destination's `room.entered` reaction.

### 3F. Soft items

Plausible generic items the player might pick up. These should be
environmentally appropriate items with no plot significance.

**Test:** Will a condition, mechanic, or specific interaction
reference this thing by name? If yes, it should be a proper entity,
not a soft item.

### 3G. Other Fields

Rooms can have special interactions, similar to entities (see §2B,
above).

---

### Step 3 validation checklist

- [ ] Every room has a `name` and `description`
- [ ] Exactly one room has `is_start_room: true`
- [ ] Every exit `target_room` references a valid room ID
- [ ] Every exit ID is unique across its host room
- [ ] Every entity in `contains` exists in the `entities` block
- [ ] Every `trigger_encounter` in a `traversal.succeeded` reaction
  references a mechanic that will be created in Step 4
- [ ] Every `trigger_dialogue` references a valid NPC entity ID
- [ ] Every `set_entity_state` references an entity with that field in
  `state_fields`
- [ ] Every `set_flag` references a flag name from Step 1D
- [ ] Every condition object follows the condition object format — no bare
  condition strings outside `any`/`all` arrays
- [ ] Every interaction with a check also has `success` and optionally
  `failure`
- [ ] Every interaction without a check has `result`
- [ ] Every `on_examine` event with a `check` has `success`
- [ ] Every `on_examine` event without a `check` has `result`
- [ ] Interactions that should accept a `using` item have a `using_results`
  map or appropriate condition gating
- [ ] If interactions reference `using_results`, each key is a valid entity
  ID or `"*"` wildcard
- [ ] Room `reactions` use valid event types (see [`events.md`](events.md))
- [ ] Room `reactions` with `event:` conditions reference valid context keys
  for their event type (see [`events.md`](events.md))

---

## Step 4: Build Mechanics

**Input:** Scenario Map + Corpus draft from step 3.
**Output:** The `mechanics` block and the top-level
`game_over_conditions` array for the corpus.

Game-over (win/lose) outcomes are authored separately (see 4A), and the
`mechanics` block itself holds only mechanics containing encounter rules
and/or reactions (adventure-wide state-based triggers) — never game-over
predicates.

### 4A. Game-over outcomes

There are two idioms; pick per-case:

- **Inline `Result.game_over` (preferred when a single result owns the
  outcome):** put `game_over` directly on the [Result](corpus.md#result)
  that causes the ending — a specific killing blow, a fatal choice.  No
  separate registry entry is needed.

  ```json
  "confirm_squeeze_through_rip": {
    "id": "confirm_squeeze_through_rip",
    "description": "Squeeze through the rip into the void beyond.",
    "condition": { "require": "flag:rip_squeeze_possible == true" },
    "result": {
      "narrative": "You tumble into the endless gray of the Astral Plane.",
      "game_over": { "type": "lose", "trigger": "astral_plane" }
    }
  }
  ```

- **Top-level `game_over_conditions` (for cross-cutting states):** a
  win/loss predicate reachable from several paths, with no single owning
  result, goes in the top-level `game_over_conditions` array.  Each entry
  has `type` (`"win"`/`"lose"`), `condition`, `trigger`, and
  optional `narrative`/`note`.  These are polled once at end of
  turn.

  ```json
  "game_over_conditions": [
    {
      "type": "win",
      "note": "Player completes the main quest.",
      "condition": {
        "all": [
          "flag:artifact_retrieved == true",
          "flag:player_escaped == true"
        ]
      },
      "narrative": "You emerge into the morning light, the ancient artifact clutched to your chest. Your quest is complete.",
      "trigger": "quest_complete"
    },
    {
      "type": "lose",
      "note": "Player falls into the chasm.",
      "condition": { "require": "flag:fallen_into_chasm == true" },
      "narrative": "You lose your footing and tumble into the darkness below. The fall is long, and then there is nothing.",
      "trigger": "chasm_fall"
    }
  ]
```

For multi-step win conditions, use `"all"` to combine separate flags in
a `game_over_conditions` entry. Each flag should be set by a different
interaction, exit, or encounter along the critical path.

>> FIXME: HP to 0 needs to be explicitly set up, or automatic? <<



### 4B. Encounters

Encounters are referenced by exits (via `trigger_encounter`) or interactions.
They follow the same rule structure as NPC aggro encounter_rules:

```json
"fall_damage": {
  "id": "fall_damage",
  "description": "Player drops from various heights on the axe handle.",
  "rules": [
    {
      "condition": { "require": "room:axe_head.is_current == true" },
      "outcome": "stat_check",
      "check": { "type": "stat_check", "stat": "DEX", "target": 8, "repeatable": true },
      "success": {
        "narrative": "You drop down and land heavily, but survive."
      },
      "failure": {
        "outcome": "flee",
        "narrative": "You fall hard and injure yourself badly.",
        "alter_stat": { "STR": { "value": -4 }, "DEX": { "value": -4 }, "CON": { "value": -4 } },
        "player_damage": "3d6"
      }
    }
  ]
}
```

**Note:** Encounters evaluate `condition` against game state when triggered.
The `room:<id>.is_current` condition is available — it checks whether the
player is currently in that room. This enables encounter rules that branch
based on which room triggered them (e.g., different fall damage by room).

**Encounter rule and branch fields:**

| Field | Type | Description |
|-------|------|-------------|
| `condition` | condition object | Gate for the rule |
| `result` | Result | Direct result (use exactly one of `result` or `check`) |
| `check` | CheckType | `RollCheck` or `StatCheck` (use exactly one of `result` or `check`) |
| `success` | Result | Branch when check/roll succeeds |
| `failure` | Result | Branch when check/roll fails |
| `skip_check_if` | condition object | Bypass the check, apply `success` directly |

> **`start_combat` on Result:** `start_combat` is only honoured on
> results inside an encounter rule (`entity.aggro` or
> `mechanic.rules`).  When such a result fires, the engine starts
> multi-round combat with the encounter source plus every id listed in
> `start_combat`, expanding each id's `combat_group`.  Use `[]` to
> fight the source alone.  Every enemy must be a stat-blocked NPC; if
> the filtered enemy set is empty, no combat is entered.  Using
> `start_combat` outside encounter results is a load-time validation
> error.

`player_damage` is available at both the rule level (applies unconditionally
when the rule fires) and the branch level (overrides the rule-level value).
The engine rolls the dice expression using the active resolution system.

### 4C. Mechanics with reactions only

For adventure-wide state-based triggers that aren't tied to a specific room or
entity, create a mechanic that carries a `reactions` array without `rules` or a
`type`.  This is not a distinct structural type — it is simply a mechanic where
`rules` is absent. See [`events.md`](events.md) for the full list of event types
and context keys.

```json
"global_reactions": {
  "description": "Adventure-wide state-based reactions.",
  "reactions": [
    {
      "id": "near_death_warning",
      "on": "player.damaged",
      "condition": { "require": "event:new_hp <= 3" },
      "effect": {
        "result": {
          "narrative": "You are gravely wounded. One more hit could be your last.",
          "set_flag": { "near_death": true }
        }
      }
    }
  ]
}
```

Use mechanics with reactions only when:
- The trigger is adventure-wide (not scoped to a room or entity)
- The trigger responds to state changes (flags, stats, attitudes) rather than
  specific actions
- Multiple reactions share a logical grouping (e.g., all environmental effects)

#### Chained encounters via a mechanic with reactions

A reaction can trigger an encounter whose outcome sets a flag, and a second
reaction can fire on that flag to trigger another encounter. Keep chains short
and condition them carefully to avoid runaway loops.

```json
"global_reactions": {
  "description": "Chains the guardian fight into the wraith ambush.",
  "reactions": [
    {
      "id": "guardian_awakens",
      "on": "room.entered",
      "condition": { "require": "event:room_id == cave_depths" },
      "effect": { "trigger_encounter": "guardian_attack" }
    },
    {
      "id": "wraith_appears",
      "on": "flag.set",
      "condition": { "require": "event:flag_id == guardian_defeated" },
      "effect": { "trigger_encounter": "wraith_ambush" }
    }
  ]
}
```

### 4D. Stats block (if applicable)

If the scenario uses stat checks, add a `stats` block to the corpus:

```json
"stats": {
  "definitions": {
    "STR": { "name": "Strength", "description": "Physical power" },
    "DEX": { "name": "Dexterity", "description": "Agility and reflexes" },
    "CON": { "name": "Constitution", "description": "Endurance" },
    "INT": { "name": "Intelligence", "description": "Reasoning" },
    "WIS": { "name": "Wisdom", "description": "Perception" },
    "CHA": { "name": "Charisma", "description": "Force of personality" }
  },
  "system": "5e"
}
```

Rules:
- Only declare stats actually used in stat_check interactions or stat: conditions
- If no stat checks exist in the scenario, omit this block entirely
- Resolution system is always `"5e"` for now

---

### Step 4 validation checklist

- [ ] Every mechanic referenced by a `trigger_encounter` exists in the block
- [ ] Every `trigger` is unique across all mechanics
- [ ] Game-over mechanics have `condition`, `narrative`, and `trigger`
- [ ] Encounter mechanics have `rules` (not `condition`/`type`/`trigger`)
- [ ] Mechanics with `reactions` but no `type` or `rules` are valid
      (adventure-wide event watchers)
- [ ] If stats block present: only stats actually used are defined
- [ ] If stats block absent: no stat_check interactions or stat: conditions
      exist in rooms/entities
- [ ] Mechanic `reactions` use valid event types (see
      [`events.md`](events.md)) and effect fields

---

## Step 5: Build default-player.json

**Input:** Scenario Map from Step 1 + assembled `corpus.json`.
**Output:** Complete `default-player.json` file (only if the corpus has a `stats` block).

If the adventure has no `corpus.stats` block, skip this step.

The `default-player.json` file uses the same format as a `--char-sheet`
file:

```json
{
  "system": "5e",
  "player": {
    "location": "<start_room_id>",
    "inventory": {},
    "equipped": [],
    "stats": { "STR": 10, "DEX": 13, "CON": 12, "INT": 11, "WIS": 10, "CHA": 10 },
    "level": 4,
    "current_hp": 27,
    "max_hp": 27,
    "ac": 11,
    "proficiency_bonus": 2,
    "save_proficiencies": ["DEX", "INT"]
  }
}
```

### Step-by-step assembly

1. **`system`** — must match `corpus.stats.system` (e.g., `"5e"`).

2. **`player.location`** — set to the room ID with `is_start_room: true`.

3. **`player.inventory`** — always `{}` at start unless the scenario specifies
   starting items (extremely rare).

4. **`player.equipped`** — usually `[]` at start.  Starting equipment is rare
   and should be declared explicitly.

5. **`player.stats`** — map each stat key declared in `corpus.stats.definitions`
   to its initial integer value. If the scenario doesn't specify values, use
   10 across all stats.

6. **Player combat fields** — if the scenario supplies them, set `level`,
   `current_hp`, `max_hp`, `ac`, `proficiency_bonus`, and `save_proficiencies`.
   For characters above level 1 these must be explicit, because the engine
   cannot derive multi-level HP from ability scores alone. If any are absent,
   choose reasonable defaults and note the omission.

Only fields that differ from the engine defaults need to be supplied;
unknown fields are ignored for forward compatibility.

---

### Step 5 validation checklist

- [ ] File exists iff `corpus.stats` is present
- [ ] `system` matches `corpus.stats.system`
- [ ] `player.location` references the room with `is_start_room: true`
- [ ] `player.stats` is present iff `corpus.stats` is present
- [ ] Every key in `player.stats` exists in `corpus.stats.definitions`
- [ ] Every stat in `corpus.stats.definitions` has a key in `player.stats`
- [ ] For multi-level characters, `max_hp`, `current_hp`, `ac`,
      `proficiency_bonus`, and `save_proficiencies` are explicit
- [ ] No entity in `player.inventory` also appears in a room's
      `contains` at start

---

## Step 6: Build soft-state.json

**Input:** Everything from Steps 2-5.
**Output:** Complete `soft-state.json` file.

The soft state stores narrative-oriented mutable data. Most fields start empty.

```json
{
  "soft_inventory": [],
  "room_notes": {},
  "entity_notes": {},
  "surfaced_soft_items": {},
  "checks_attempted": {},
  "revealed_hints": [],
  "turn_history": [],
  "dialogue_state": {
    "active_npc": null,
    "conversation_log": [],
    "topics_discussed": [],
    "entered_turn": 0,
    "stall_counter": 0
  },
  "player_knowledge": []
}
```

### Step-by-step assembly

1. **`soft_inventory`** — always `[]`. The player starts with no soft items.

2. **`room_notes`** — `{}`. The engine populates this dynamically. You may
   pre-initialise as an empty object.

3. **`entity_notes`** — `{}`. Same as room_notes.

4. **`surfaced_soft_items`** — `{}`. Tracks which soft items have been
   discovered per room/entity. Starts as empty dict.

5. **`checks_attempted`** — `{}`. Records which non-repeatable checks have
   been attempted. Starts as empty dict.

6. **`revealed_hints`** — `[]`. Stores `reveals` strings from successful
   interactions. Starts empty.

7. **`turn_history`** — always `[]`.

8. **`dialogue_state`** — always the null structure shown above.

9. **`player_knowledge`** — `[]`. List of knowledge entries accumulated
    during play (from NPC dialogue revelations and `reveals` fields in
    Result objects). Starts empty.

---

### Step 6 validation checklist

- [ ] `soft_inventory` is `[]`
- [ ] `surfaced_soft_items` is `{}`
- [ ] `checks_attempted` is `{}`
- [ ] `revealed_hints` is `[]`
- [ ] `dialogue_state.active_npc` is `null`
- [ ] `dialogue_state.conversation_log` is `[]`
- [ ] `dialogue_state.topics_discussed` is `[]`
- [ ] `dialogue_state.entered_turn` is `0`
- [ ] `dialogue_state.stall_counter` is `0`
- [ ] `turn_history` is `[]`
- [ ] `player_knowledge` is `[]`

---

## Cross-File Validation (Final)

Run this checklist after `corpus.json`, `soft-state.json`, and
`default-player.json` (when applicable) are generated. This catches
cross-file consistency issues.  If `hard-state.json` is provided as an
optional world-state override, include it in the checks below.

### Universal checks

- [ ] Every flag name used in any condition string, `set_flag`, or
  `will_reveal.set_flag` appears in `flags_declared`
- [ ] Every room ID referenced in any exit `target_room`,
      `follower.blacklist`, etc. exists in `corpus.rooms`
- [ ] Every entity ID referenced in any `contains`, `add_item`,
  `remove_item`, `set_entity_state`, `trigger_dialogue`, `using_results`
  key, etc. exists in `corpus.entities`
- [ ] Every mechanic ID referenced in any `trigger_encounter` exists in
  `corpus.mechanics`
- [ ] Every `trigger_encounter` in a reaction references a valid mechanic ID
  or entity ID (or is `"self"` on an entity-scoped reaction)
- [ ] Every `trigger_dialogue` in a reaction references a valid NPC entity ID
  (or is `"self"` on an NPC entity)
- [ ] Every reaction `on` field is a valid event type (see [`events.md`](events.md))
- [ ] Every NPC with `dialogue.will_reveal` entries has
  matching `set_flag` / `set_entity_state` values that exist
- [ ] Every `adjust_attitude` key references a valid NPC entity that has
  `attitude` declared in `state_fields`

### Corpus self-consistency

- [ ] `flags_declared` is present as a top-level list of all flag names used
  in conditions and `set_flag` results.  Entries may be plain strings
  (start `false`) or single-key objects mapping a flag id to its initial
  boolean value.
- [ ] No duplicate IDs across all rooms, exits, entities, interactions,
  mechanics, reactions, flags, and topics
- [ ] Every `will_reveal.conditions` string references entities, flags,
  attitudes, topics, or tags that exist in the corpus
- [ ] Every `on_examine` event with a condition references an existing flag
- [ ] Every `using_results` key is either an entity ID in corpus or `"*"`
- [ ] Every stat check (`stat_check` type) references a stat key in
  `corpus.stats.definitions` (if stats block exists; otherwise, no stat_check
  should appear)
- [ ] Every `alter_stat` result references a stat key in `stats.definitions`
  (if stats block exists; otherwise, no alter_stat should appear)
- [ ] If `corpus.stats` is present, `default-player.json` exists and its
  `system` matches `corpus.stats.system`

### Hard-state checks (only if `hard-state.json` is used as an override)

- [ ] `hard_state.player.location` matches the room with `is_start_room: true`
- [ ] Every entity with `state_fields` has a complete `entity_states` entry
- [ ] `entity_states` contains no fields not declared in the entity's `state_fields`
- [ ] Entities with `hidden: true` in initial `entity_states` are still
  listed in the room's `contains` (the engine handles filtering
  based on the state field)
- [ ] `entity_states` contains all fields declared in the entity's `state_fields`
- [ ] Every NPC with `dialogue` has `attitude` in both `state_fields` and `entity_states`
- [ ] Every NPC with a `combat` block has `current_hp` in both `state_fields`
  and `entity_states`, initialized to `combat.hp`
- [ ] NPC attitude values are within the `[min, max]` range from their
  `attitude_limits`

### Soft-state checks

- [ ] `soft_inventory` is `[]`
- [ ] `surfaced_soft_items` is `{}`
- [ ] `checks_attempted` is `{}`
- [ ] `revealed_hints` is `[]`
- [ ] `dialogue_state` has the standard null structure
- [ ] `turn_history` is `[]`
- [ ] `player_knowledge` is `[]`

After completing the JSON files and this checklist, run the engine's
validator to catch mechanical errors you might have missed:

```
python scripts/validate_adventure.py <adventure_dir>
```

Fix any reported issues before declaring the generation complete.

---

## Condition Syntax Reference

All condition fields use **condition objects** — never bare strings —
except for `will_reveal.conditions`, which is a list of bare condition
strings.  Condition objects enable compound AND/OR logic with nesting.

### Simple condition (object-based)

```json
{ "require": "flag:daytime == true" }
{ "unless": "flag:cursed == true" }
```

### Compound condition (AND/OR with nesting)

```json
{ "any": [
  "flag:handkerchief_noticed == true",
  { "all": [
    "entity:korbar.attitude >= 4",
    "flag:padlock_unlocked == false"
  ] }
] }
```

```json
{ "all": [
  "tag:weapon",
  { "unless": "flag:injured == true" }
] }
```

Elements inside `any` and `all` arrays may be:
- A condition string like `"flag:spider_fled == true"`
- A nested condition object like `{ "require": "..." }` or `{ "unless": "..." }`
- A further `{ "any": [...] }` or `{ "all": [...] }` (arbitrary nesting)

### Condition string format

```
<domain>:<key> <op> <value>
```

| Domain       | Example                          | Meaning |
|--------------|----------------------------------|---------|
| `flag`       | `flag:door_opened == true`       | Hard-state flag |
| `inventory`  | `inventory:rusty_key`            | Item entity ID in player inventory (count > 0); operators like `inventory:coins >= 30` are supported for stackable items |
| `tag`        | `tag:weapon`                     | Any item with this tag in inventory or equipped gear |
| `entity`     | `entity:spider.alive == true`    | Entity hard-state field |
| `room`       | `room:axe_head.visited == true`  | Room state field |
| `topic`      | `topic:abandonment`              | Topic ID discussed in current dialogue |
| `stat`       | `stat:STR >= 12`                 | Player stat value vs threshold |
| `event`      | `event:exit_id == exit_climb`    | Event context value. Only valid during reaction dispatch. |
| `any`        | *compound*                       | At least one sub-condition must be true |
| `all`        | *compound*                       | All sub-conditions must be true |
| `require`    | `{ "require": "..." }`           | Condition must be true |
| `unless`     | `{ "unless": "..." }`            | Condition must be false |

Supported ops: `== true`, `== false`, `== <string>`, `>= <number>`,
`> <number>`, `<= <number>`, `< <number>`.

### Usage notes

- For `unless`, the inner condition being true **blocks** the action
- `inventory` tests presence (count > 0) by default and supports quantity
  operators for stackable items; `tag` tests presence, not equality
- `tag:weapon` succeeds if *any* item in inventory or equipped gear has the
  `"weapon"` tag
- `stat:STR >= 12` evaluates the player's current Strength value
- `topic:<id>` succeeds if the topic ID appears in
  `dialogue_state.topics_discussed`
- `room:<id>.is_current` is a special value that checks if the player is
  currently in that room (available in encounter rules)
- `event:<key>` checks a value in the current event context. Only valid inside
  reaction conditions during dispatch. Outside dispatch, evaluates to `false`.
  Common keys: `exit_id`, `interaction_id`, `npc_id`, `flag_id`, `source_id`,
  `check_type`, `stat`, `amount`, `new_hp`.
- `will_reveal.conditions` is a list of bare condition strings, not condition
  objects (e.g., `["entity:korbar.attitude >= 2", "flag:spider_fled == true"]`).

---

#### Follow-up checks pattern

When a check result triggers a follow-up check (for escalating consequences,
multiple stages, or branching outcomes), encode the follow-up as
`then_check` on the success or failure result of the first check.

The typical structure is: a failed (or succeeded) check leads to a second
check with its own success/failure branches. The second check's failure may
set a flag that a game-over condition watches for, or it may simply produce
a narrative outcome:

```json
{
  "id": "vault_trap",
  "label": "Disarm the vault trap",
  "description": "Attempt to disarm the pressure plate.",
  "check": {
    "type": "stat_check",
    "stat": "DEX",
    "target": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You carefully disable the pressure plate. The vault is safe."
  },
  "failure": {
    "narrative": "The mechanism clicks. Dart shooters whir to life!",
    "then_check": {
      "check": {
        "type": "stat_check",
        "stat": "DEX",
        "target": 10,
        "repeatable": true
      },
      "success": {
        "narrative": "You throw yourself aside as darts whistle past your head."
      },
      "failure": {
        "narrative": "A dart catches you in the shoulder. Poison seeps into your veins.",
        "set_flag": { "poisoned": true }
      }
    }
  }
}
```

When the follow-up check's final failure sets a game-over flag, pair it with
a top-level `game_over_conditions` entry:

```json
"game_over_conditions": [
  {
    "type": "lose",
    "note": "Player falls into the chasm.",
    "condition": { "require": "flag:fallen_into_chasm == true" },
    "narrative": "You lose your footing and tumble into the darkness below.",
    "trigger": "chasm_fall"
  }
]
```

---
  

(Showing matches; edit interrupted by user)

---
## Naming Conventions (All Steps)

All IDs must be **snake_case, lowercase ASCII**:

| Type | Convention | Example |
|------|-----------|---------|
| Room IDs | descriptive | `axe_head`, `bag_floor`, `secret_compartment` |
| Entity IDs | descriptive | `spider`, `korbar`, `rusty_key`, `toenail_sword` |
| Exit IDs | prefixed `exit_` | `exit_climb_down_handle`, `exit_drop_into_darkness` |
| Interaction IDs | descriptive snake_case | `force_through_web`, `rummage_rubbish` |
| Mechanic IDs | descriptive | `fall_damage`, `win_escape_bag`, `key_lost` |
| Reaction IDs | descriptive | `spider_attack_on_sight`, `room_cleared`, `near_death_warning` |
| Flag names | descriptive snake_case | `spider_fled`, `injured`, `handkerchief_noticed` |
| Topic IDs (will_reveal) | descriptive snake_case | `padlock_mechanism`, `secret_compartment` |
| Soft item names | lowercase generic | `rock`, `cork`, `sandwich` |

---

## Common Pitfalls

1. **Confusing soft items with entities**: If a condition, mechanic, or
   specific interaction references it by name → entity. If it's just
   environmentally appropriate → soft item.

2. **Forgetting to declare flags**: Every flag referenced in any `set_flag`,
   condition string, or `require`/`unless` block must appear in
   `flags_declared` with an initial value.

3. **Missing state_fields declarations**: Every mutable property of an entity
   that changes during play must be declared in `state_fields`. The engine
   validates that `entity_states` and `state_fields` match at startup.

4. **Hidden exits without reveal conditions**: An exit with a
   `condition` needs a companion interaction that sets a flag;
   the condition should require that flag. Otherwise the exit is permanently
   invisible.

5. **One-way exits without return path**: A `one_way: true` exit should have a
   separate exit for the return direction (or the scenario narrative justifies
   the one-way nature).

6. **Duplicate IDs**: Ensure every ID (room, entity, exit, interaction,
   mechanic, flag, topic) is unique across the entire corpus.

7. **NPCs with neither dialogue nor aggro**: Conversational NPCs
   need `dialogue`; combat NPCs need `aggro`. An NPC with
   neither will be purely decorative. If the scenario expects interaction,
   one of these must be present.

8. **Condition syntax**: All condition fields use the condition object form
   (`{ "require": "..." }`, `{ "unless": "..." }`, `{ "any": [...] }`,
   `{ "all": [...] }`). Bare strings are not accepted outside `any`/`all`
   arrays.

9. **Attitude initialisation**: Each NPC's initial attitude must be declared
   in `state_fields` with an explicit `initial` value when it differs from
   0.  The `attitude_limits` block only defines the static bounds
   (`min`, `max`, `step_per_turn`).

10. **Item placement**: Items that start in a specific location appear in
    that room's `contains`. Items the player starts carrying are in
    `hard_state.player.inventory`. Never put the same item ID in both.

11. **Prose style**: All `description`, `narrative`, and `introduction` fields
    should be in second-person present tense ("You see... You are...").

12. **Stat value ranges**: Under 5e, stat values typically range 3-18. DCs
    should match character capabilities: stat 10 (+0 modifier) has ~55% vs
    DC 10, ~30% vs DC 15, ~5% vs DC 20. Do not set impossible DCs without
    an alternative path.

13. **Follow-up check maximal depth**: Nested `then_check` supports up to 3
    levels of depth.

14. **Follower blacklist**: If an NPC follows the player, and the scenario
    says they refuse to enter certain rooms, add `follower.blacklist` to
    the NPC's entity definition.

15. **Follow-up check does not trigger game-over directly**: A `then_check`
    failure cannot set `game_over` directly. Instead, use `set_flag` in the
    failure result and add a top-level `game_over_conditions` entry watching
    that flag.

16. **Hidden entities need a reveal mechanism**: Every entity with
    `hidden: true` in its initial `entity_states` must have a companion
    `on_examine` event or interaction that sets `hidden: false`. Without one,
    the entity is permanently invisible to the LLM. The room description
    and entity description must not spoil the hidden entity's nature.

17. **Global traversal checks**: There is no mechanism to apply a
    traversal_check to all exits at once. If carrying an item affects
    movement, duplicate the traversal_check on every relevant exit.

18. **No dynamic DC scaling**: The schema does not support stat checks with
    escalating DCs based on attempt count. Model repeated interactions with
    increasing DCs as separate interaction entries with mutually exclusive
    conditions.

19. **Post-dialogue state changes**: If an NPC dies, flees, or changes state
    when dialogue ends (not during dialogue), use a `dialogue.ended` reaction
    on the entity. The legacy `on_dialogue_exit` field has been removed.

20. **Reactions vs legacy triggers**: Use `reactions` for all event-driven
    effects. Reactions are more flexible (any event × any effect), support
    state-based triggers (flag changes, stat changes), and compose cleanly.
    The legacy `on_enter`, `on_traverse`, `aggro.triggers_on`, and
    `on_dialogue_exit` fields have been removed.

21. **`event:` domain only works in reactions**: The `event:` condition domain
    is only valid inside reaction conditions during dispatch. Using it in
    interaction conditions, game-over condition predicates, or exit conditions
    will always evaluate to `false`.

22. **`combat.ended` is not yet emitted**: The `combat.ended` event has not
    been wired into the engine.  Do not use it in reaction `on` fields.  To
    react to a combatant's death, use `on: "entity_state.changed"` with a
    condition watching `event:entity_id == <npc_id>` and `event:field == alive`
    and `event:new_value == false`.  See [`events.md`](events.md) § Known gaps.

23. **Entity on_examine vs room on_examine**: When the player examines a
    specific entity (a carving, a lever, a hidden switch), only that
    entity's `on_examine` events fire. Room `on_examine` events fire
    only when the player examines the room itself. If the scenario
    says "examining the lever reveals a secret catch", the on_examine
    event must go on the lever entity, not on the room.  See § 3H for entity vs. room placement
    rules.

24. **Examine-gated discoveries written as interactions**: Do not model
    discoveries the player makes by *looking* ("examine the pile",
    "examine the webs") as room interactions requiring the player to
    explicitly choose an action from a list.  These should be
    `on_examine` events instead.  An `interaction` with a name like
    `examine_the_webs` is a red flag — the generic `examine` action
    already covers looking at entities; use entity `on_examine` for any
    mechanical consequences.  Only use `interaction` for active
    physical manipulation: searching a pile, forcing a door, hauling
    an object.  See § 3E for the full decision table and examples.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
