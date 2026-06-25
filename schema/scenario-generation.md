# Scenario-to-JSON Generation Instructions

This document is a prompt/checklist for an LLM to convert a natural-language
adventure scenario (e.g., `scenario.md`) into the three structured JSON files
the engine requires:

- **`corpus.json`** — read-only adventure content (rooms, entities, mechanics)
- **`hard-state.json`** — initial authoritative runtime state
- **`soft-state.json`** — initial narrative-oriented mutable state

The schemas for these files are defined in:
- [`corpus.md`](corpus.md) for the Module Corpus
- [`events.md`](events.md) for the canonical event model and reaction event types
- [`hard-state.md`](hard-state.md) for Hard Game State
- [`soft-state.md`](soft-state.md) for Soft Game State
- [`actions.md`](actions.md) for actions (engine validation logic)

---

## Generation Workflow

Do **not** attempt to generate all three JSON files in one pass. Instead,
follow these six sequential steps. Each step produces intermediate output
that the next step consumes. Validate each step before proceeding.

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
Step 5: Build hard-state.json
     │  Output: complete hard-state.json
     ▼
Step 6: Build soft-state.json
     │  Output: complete soft-state.json
     ▼
Cross-file validation
```

Each step produces intermediate output in the adventure directory.
Step 1 writes a structured plan to `scenario-map.md` — the working
document all subsequent steps read from.  Steps 2–4 produce draft
corpus blocks; Steps 5–6 produce the final `hard-state.json` and
`soft-state.json`.  After cross-file validation, assemble the complete
`corpus.json` from the draft blocks.

At the end of every step, run the step's validation checklist.  If any
check fails, **stop and fix before proceeding**.

---

## Step 1: Parse & Extract

**Objective:** produce a structured list of everything that needs to
be modelled, including consistent IDs for all the rooms, entities,
interactions, flags, state fields, entity tags, etc.  All IDs are in
snake_case.

Read the scenario writeup (usually a Markdown file).  Then extract the
following into a clean document (text, not JSON) and write it to
`scenario-map.md` in the adventure directory.  This file is the
working plan for all subsequent steps.

### 1A. Adventure metadata

- *Title* — The title of the adventure scenario.

- *Credits* — The author and other credits, including copyright info.

- *Introduction* — The opening paragraph (used verbatim).
  Write it up in second-person narrator voice.  No spoilers.

- *Adventure ID* — A short snake_case identifier (e.g., `bag-of-holding`).
  Optional but recommended for save/load safety.

- *Atmosphere* — One or two sentences to set the tone, synthesised
  from your reading of the scenario.  No spoilers.  This will be
  encoded as `corpus.adventure.atmosphere`, which has two sub-fields:
  `setting` (world description) and `tone` (narrative style).

If the scenario uses player stats, note:

- Which stats are used
- The resolution system (typically 5e)
- Whether the scenario specifies player stat values, or defaults (e.g., all 10s)

### 1B. Rooms (Pass 1)

Construct a list of rooms based on the scenario writeup.  Every
visitable location in the scenario should be a distinct in-game room.
Avoid creating extra rooms not in the scenario, *unless* necessary for
special game mechanics (in which case note this in your final report).

For each room, write out the following info:

- **Room ID** — assign a scenario-wide unique ID.

- **Room name** — a short identifying phrase (e.g., for traversal).
  Avoid giving consecutive rooms the same name, except under special
  circumstances (e.g., rooms in a featureless maze).

- **Description** — a note saying what the room is, its key
  characteristics, and how it is connected to other rooms.  Keep it
  factual and succinct; this is for scenario mapping, not narration.

- **Start room?** — whether this is the room where the player begins.
  (There must be exactly one.)

### 1C. Entities (Pass 1)

For every distinct entity mentioned in the scenario, list out:

- **Entity ID** — assign a scenario-wide unique ID.

- **Name** — a short identifying phrase (e.g., for player commands).
  Capitalize both proper names ("Aragon") and generic names ("Goblin").

  If a room has multiple similar creatures without proper names,
  disambiguate.  If these creatures lack distinguishing
  characteristics, use numbering (e.g., "Goblin 1", "Goblin 2").

- **Type** — one of:
  - `player` — the player character (exactly one)
  - `npc` — characters that can talk or fight
  - `feature` — environmental objects (walls, piles, handkerchiefs)
  - `item` — objects that can be picked up

- **Description** — a note about what this entity is, its location at
  game start (room, container entity, or player inventory), its broad
  relevance to the scenario, and any details that are narratively
  important.  We will fill in mechanical details later (§1G).  If the
  entity is a feature visible from multiple rooms, note which rooms it
  spans.

### 1D. Global Mechanics

List out every mechanic in the scenario that is not tied to a specific
room or entity.  Mechanics in the corpus come in three kinds (see
corpus.md):

- **encounters** — combat or hazard events with rules
- **game-over conditions** — win/lose triggers
- **reaction-only mechanics** —  effects triggered by global adventure state

Note: entity-scoped encounters (e.g., attacking an NPC) are specified
at entity level, not here.

For each mechanic, note:

- **Mechanic ID** — assign a scenario-wide unique ID.

- **Kind** — which of the three kinds: encounter, game-over condition,
  or reaction-only mechanic.

- **Description** — a note about how the mechanic works, its trigger,
  and its effects (e.g., damage dealt to the player).

  This description, like the other mechanical descriptions in Step 1,
  should be textual but logically complete.  We will use it to build
  the actual JSON structure later.  It can reference flag IDs (e.g.,
  `password_discovered`), entity tags (e.g., `valuable`, `draggable`),
  and room/entity state IDs and their values (e.g., `locked`),
  including IDs that have yet to be defined.

### 1E. Global Flags

Draw up a list of global flags: boolean conditions that track
plot-relevant world state, such as secrets discovered or key NPCs met.
For each flag, specify:

- **Flag Name** — a scenario-wide unique ID.

- **Description** — an explanation of the flag condition.

- **Initial Value** — the value at game start.

Be sure to include any flag already referenced in your list of global
mechanics.

### 1F. Rooms (Pass 2)

Revisit the room list, and add the following information to each room:

- **Exits** — every way out.  For each exit, assign a room-unique ID,
  and give a brief description of the exit (e.g., "through the north
  doorway"), and specify the destination room ID (from §1B).
  Traversal conditions are handled in "Events and Reactions" below.

- **Entities present** — list the ID of each entity in the room at
  start (from §1C), including hidden ones (e.g., a lurking thief).

- **Special interactions** — assign a room-unique ID to any special
  interaction the player can have with the *room* (not an entity inside
  the room): e.g., shouting out a magic command word.
  
  Do not define interactions mapping to these generic player actions:
  `move` (traversing rooms), `examine` (cursory or in-depth study), or
  `transfer` (moving items to/from).

- **Event Reactions** — describe any consequential event-driven
  reaction tied to the *room* (not an entity in the room), that can
  occur only if the player is in the room.  Examples: a combat is
  triggered when the player enters, or a force-field blocks any
  attempt to use an exit.

  You must assign each reaction a scenario-unique reaction ID.  Then,
  describe (i) the trigger: a special interaction, a standard player
  action, etc.; (ii) any stat checks or other gating, and (iii) the
  consequences.  These descriptions should be textual, and logically
  sufficient to form a JSON object later – but don't write the JSON yet.

- **State fields** — assign a room-unique ID for each mutable property
  the room has, and note the initial value.  Don't list properties
  nilly-willy; focus on those needed for mechanics or narration, e.g.,
  `filled_with_poison_gas`, `time_of_day` (if the scenario progresses
  time).  Values can be boolean, numbers, or strings.

- **On-examine events** — note any effects triggered by the player
  examining the room itself (rather than a specific entity in the
  room): e.g., viewing a dilapidated courtyard, and realizing that
  nobody has visited in years (if that's a relevant plot point).  Can
  be gated, e.g. by a stack check.

While describing events/reactions, special interactions, or state
fields, you can reference flags defined in §1D.  If you overlooked a
flag that you now need, update that list.  You can also reference IDs
for entity tags or room/entity state fields that are already defined,
or will be defined later.

### 1G. Entities (Pass 2)

Revisit the entity list, and add the following information to each
entity:

- **Tags** — any semantic features relevant to a mechanic in the
  scenario (e.g., a pressure plate triggered by items with the `heavy`
  tag).  Do not define tags that lack relevance to mechanics.

- **Equippable?** — if the entity is an item that can be equipped
  (weapon, armor, shield, etc.), note the equipment category and any
  special properties (damage expression, stat bonuses, etc.).

- **Contained Entities** — If the entity contains other entities
  (e.g., a drawer holding a key), note which entity IDs are inside it.
  This should be consistent with the descriptions in §1C.

- **Special interactions** — assign an entity-unique ID to any special
  interactions the player can have with it: e.g., pulling a lever.

  Do not define interactions mapping to these generic player actions:
  `examine` (cursory or in-depth study), `talk` (conversing with NPC),
  or `transfer` (moving items to/from).

- **State fields** — list each relevant mutable property the entity
  has, and their initial values.  Think about what states are needed
  for game mechanics, and focus on those.
  
  For NPCs, state fields must include `alive` and `fled` (booleans),
  but can also include `attitude` (number), `hidden` (boolean),
  `following` (boolean, for NPC companions), and custom fields.  For
  non-NPC entities, state fields can be `hidden` (boolean), or custom
  (e.g., `opened`, `locked`, `lit`).

  The boolean state field `hidden`, for either NPCs or non-NPCs,
  should be set if the entity might be concealed from the player,
  either at game start or subsequently.

  For each custom field, note down its meaning.

- **Event Reactions** — describe any consequential event-driven
  reaction tied to the entity, that can occur only if the entity is in
  the current room (and, for NPCs, alive and active).  Examples:
  combat triggered by an NPC's attitude dropping below some level, or
  a magic effect firing when an item is picked up.
  
  You must assign each reaction a scenario-unique reaction ID.  Then,
  textually describe (i) the trigger: a special interaction, a
  standard player action, etc.; (ii) a description of any checks tied
  to the event, and (iii) a description of the consequences.

- **On-examine events** — note any effects triggered by the player
  examining the entity.  Important: this field belongs on the thing
  being examined, *not* the room containing it.  Thus, when the
  scenario says "upon examining the statue, the player notices...",
  that on_examine event belongs on the statue entity.

For NPCs, also add descriptions for the following:

- **Combat Stats** — if the NPC is combat-capable and the scenario
  provides stat block details (HP, AC, damage dice, initiative
  modifier, etc.), write them down verbatim.  If the scenario doesn't
  give exact numbers, note that the NPC fights and any narrative
  description of its combat style (e.g., "constricts with webs",
  "breathes fire").

- **Behavior** — summarize the personality, whether it fights, etc.

- **Dialogue Paths** — for dialogue, if the NPC talks.
  Assign an NPC-unique ID for each special line of conversation the
  NPC can engage with.  Unlike ordinary conversational topics,
  dialogue paths have connections to the game's plot or mechanics,
  e.g. bribing a guard to get through a gate, or convincing a prince
  that his vizier is evil.  Describe when this dialogue path is
  available, and what transpires during it (including stat check
  gating, consequences, etc.).

- **Topics** — for dialogue, if the NPC talks.
  Assign an NPC-unique ID for each significant conversational topic.
  This is a topic that is not relevant enough to mechanics/plot to
  warrant a dialogue path, but ought to be specified ahead of time
  rather than letting the GM ad-lib.  Describe (i) the conditions
  under which the NPC will engage in the topic, and (ii) what the NPC
  should convey (non-verbatim).

  For example: a guard NPC might have a dialogue path `bribe` (the
  player pays to get through the gate — mechanical consequence) and a
  topic `personal_life` (the guard mentions they have a family — no
  mechanical consequence, but might be useful for consistency).

### 1H. Cleanup

Go through the lists you have constructed, and check for consistency:
IDs are consistent, every ID required by a mechanic is defined, etc.

Double-check that the mechanics, as planned, will accurately capture
the spirit of what's written in the scenario document.  Minor
deviations are OK, but these should be noted and surfaced in the final
task report.

Revise as necessary.

---

### Step 1 validation checklist

- [ ] Every room in the scenario is captured in the room list
- [ ] Every entity is classified with a type
- [ ] Every conditional gate is reflected as a flag
- [ ] Stat checks identified and resolution system noted (or "no stats")
- [ ] Exactly one start room identified
- [ ] No rooms or entities invented that aren't in the scenario
- [ ] State-based triggers and event-driven effects identified as reaction candidates

---

## Step 2: Build Entities

**Input:** `scenario-map.md` document from Step 1.
**Output:** The full `"entities"` block for `corpus.json`.

For each entity listed in the scenario map, produce an entity
definition following the schema in [`corpus.md`](corpus.md) (§2
Entities).

### 2A. General Entity Fields

#### Description

When generating the entity's `description` field, do not just rely on
the description field from the scenario map.  Instead, you now need to
write a timeless description of the entity, which will be provided to
the GM any turn the entity is present.  It must be factual, include
relevant sensory details, and remain accurate regardless of the
entity's current state (e.g., dead or alive).

Example: "A massive black spider, about the size of a large dog, with
eight glittering red eyes, sharp mandibles, and eight hairy legs".

Do not use poetic language; the narrator will turn the description
into something atmospheric.

Avoid situational framing that can be invalidated during the game
(e.g., "It lurks in the shadows...").

#### State fields

When generating the entity's `state_fields`, refer to the state fields
devised in the scenario map.  Do include the initial value, as well as
a terse description (which explains to the GM what the state field
means).

Example:

```json
"state_fields": {
  "alive": { "type": "boolean", "description": "Whether the spider is alive." },
  "fled": { "type": "boolean", "description": "Whether the spider has fled." },
  "attitude": { "type": "number", "description": "Attitude toward the player, -10 to 10." },
  "hidden": { "type": "boolean", "description": "Whether the entity is hidden from view." }
}
```

If an entity is initially concealed from the player (an key in a
drawer, a thief hiding in the shadows, etc.), you MUST declare a
`hidden` state field.  This is handled specially by the engine: when
true, the entity is concealed even from the GM, to avoid leakage.
Later, when writing hard-state.json, you will need to initialize
`hidden: true` in the entity's `entity_states`.

Note that every entity initialized with `hidden: true` ought to have
some way to set `hidden: false` (examination, interaction, etc.) in
the scenario; otherwise, it is permanently hidden.

#### Entity reactions

The `reactions` field is used for event-driven entity behavior.  When
translating reactions from the scenario map into JSON, you may refer
to [`events.md`](events.md) for a list of triggering events.  Note
that entity-scoped reactions are active only if the entity is present
in the current room, alive, and not-fled.

Example of an attack on sight reaction:
```json
"reactions": [
  {
    "id": "goblin_ambush",
    "on": "room.entered",
    "effects": { "trigger_encounter": "goblin_attack" }
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
    "effects": {
      "result": {
        "set_entity_state": { "stuck_fly": { "alive": false } },
        "narrative": "The fly's groaning ceases. Its tiny body goes still."
      }
    }
  }
]
```

#### Examination

The `on_examine` field is used to trigger effects when a player
examines an entity (or room).

The scenario might be ambiguous about whether the `on_examine` effect
triggers on an ordinary or rigorous examination.  In that case, use
your judgment.  Here is a rule of thumb: an ordinary examination
suffices if the discovery can be made by a cursory look at the object,
whereas a rigorous examination is necessary if the discovery requires
a physical search.  Remember how you resolved this ambiguity, and note
it in your task report.

Often, `on_examine` is used to reveal a hidden entity:

```json
{
  "id": "notice_spider",
  "condition": { "require": "entity:spider.hidden == true" },
  "check": {
    "type": "stat_check",
    "stat": "WIS",
    "dc": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You notice eight glittering eyes watching you from above.",
    "set_entity_state": { "spider": { "hidden": false } },
    "set_flag": { "spider_noticed": true }
  }
}
```

**When does a hidden entity become visible?** If the revealing result
includes `set_entity_state: { "<entity>": { "hidden": false } }`
directly, the entity is visible to the narrator in the same turn. If
you use a separate reaction on `flag.set`, the reveal is deferred to
the next turn's briefing.  The direct approach is usually preferred
for immediate dramatic effect, unless otherwise indicated by the
scenario.

### 2C. NPC dialogue guidelines

For every conversational NPC, write a `dialogue_guidelines` block:

- **`personality`**: 2-4 sentences. Manner of speaking, emotional state, core
  motivation, fears. Extract from the scenario's NPC section.
- **`on_encounter`**: What happens on first meeting. If the scenario says
  "the fly groans when the player enters", encode that here.
- **`can` / `cannot`**: Hard constraints from the scenario. These are the
  "firewall" against LLM confabulation. Be specific.
  - Example: `["will warn about the spider", "expresses satisfaction if spider is dead"]`
  - Example: `["will never agree to fight the spider", "will not follow into the secret compartment"]`
- **`knows`**: All facts the NPC possesses. Every piece of plot-relevant
  information the NPC can potentially share, even if gated.
- **`attitude_limits`**: Integer bounds to attitude.
  - `min` / `max`: The range. If not specified by the scenario,
    a sensible default is `-10` to `10`, but NPCs that the scenario
	assumes to be permanently hostile could run from `-10` to `0`;
    use your judgment.
  - `step_per_turn`: Maximum attitude change per turn. Default `1` unless the
    scenario says otherwise.
  - `initial`: Starting attitude. Default `0`.
- **`will_reveal`**: Gated topics. See below.
- **`dialogue_paths`**: Special conversation paths with mechanical effects.
  See below.

#### `will_reveal` topics

For every secret or piece of information the NPC can reveal, create a topic.
Each topic's `conditions` array should include every gate mentioned in the
scenario; the conditions in the array are ANDed together.

```json
"will_reveal": {
  "bag_mechanism": {
    "description": "Korbar explains how the Bag of Holding works — it's a dimensional pocket.",
    "conditions": ["attitude:korbar >= 1"]
  },
  "secret_compartment": {
    "description": "Korbar reveals the handkerchief hides a flap leading to a secret compartment with a key.",
    "conditions": ["attitude:korbar >= 3"]
  }
}
```

Each topic may also carry `set_flag` and `set_entity_state` side effects — these
are applied by the engine when the LLM tags the topic as revealed in dialogue.

#### `dialogue_paths`

Define special conversation paths that trigger mechanical effects when the
player invokes them via a `talk` action with `dialogue_path` set. This is useful
for social interactions tied to stat checks (flatter, intimidate), delivering plot-critical information, or any dialogue with engine-resolved consequences.

Each dialogue path has:

- **Path ID** (required): the machine key (e.g., `flatter`,
  `inform_spy_dead`).  This is what the `talk` action sets as
  `dialogue_path`, and what the engine uses to look up the path.
- `description` (required): a required human-readable string
  explaining what the path represents. This is surfaced to the LLM as
  a map of `{path_id: description}`, which uses the description to
  decide whether the player's input matches a defined path.  Write
  descriptions as clear player-intent phrases (e.g., "Praise the
  spider to flatter it" or "Tell Bruce the spy has been dealt with").
- `condition`: gates when the path is available
- `check` + `success`/`failure`: a probabilistic stat check with outcomes
- `result`: a deterministic outcome when no check is needed.  Path
  results support the same fields as interaction results (`narrative`,
  `set_flag`, `alter_stat`, `adjust_attitude`, etc.).

Example: a fairy that can be flattered with a CHA check to improve attitude:

```json
"dialogue_paths": {
  "flatter": {
    "description": "Praise the fairy's beauty.",
    "condition": { "require": "attitude:fairy < 0" },
    "check": { "type": "stat_check", "stat": "CHA", "dc": 12, "repeatable": true },
    "success": {
      "narrative": "The fairy preens at your praise.",
      "adjust_attitude": { "fairy": 1 }
    },
    "failure": {
      "narrative": "The fairy rolls her eyes."
    }
  }
}
```

### 2D. NPC behavior (combat rules)

For every NPC that fights, produce a `behavior` block:

- **`encounter_rules`**: One rule per combat branch. Rules are evaluated
  top-to-bottom; the first matching condition fires. To trigger combat from a
  specific action (e.g. attacking the NPC), define an entity-scoped reaction on
  `interaction.used` with `effects.trigger_encounter: "self"` (see Entity-scoped
  reactions above).

When a combat scenario has multiple conditional branches (e.g., "if armed AND
STR check succeeds → goblin dies" vs "if armed AND STR fails → goblin strikes
back"), model each as a separate rule with its own `condition`:

```json
"encounter_rules": [
  {
    "condition": { "require": "tag:weapon" },
    "outcome": "stat_check",
    "check": { "type": "stat_check", "stat": "STR", "dc": 10, "repeatable": true },
    "on_success": {
      "outcome": "flee",
      "narrative": "You land a solid blow. The goblin hisses and flees.",
      "set_flags": { "goblin_fled": true }
    },
    "on_failure": {
      "outcome": "death",
      "narrative": "The goblin strikes back! Its cleaver goes through your neck."
    }
  },
  {
    "condition": { "unless": "tag:weapon" },
    "outcome": "death",
    "narrative": "Bare-handed, you cannot fend off the goblin's attack. It quickly overcomes you."
  }
]
```

Note: `outcome: "death"` always kills the player (game over). `outcome: "flee"`
removes the NPC. For non-lethal combat outcomes (e.g., NPC is knocked out but
doesn't die), use `outcome: "flee"` with appropriate `set_flags` and narrative,
since `flee` removes the NPC from play without killing the player.

### 2E. Item entities

For every item entity:

- **`name`** (required): a human-readable display name (e.g., `"Toenail Sword"`,
  `"Rusty Key"`). This is what the player sees in the `/inv` panel and what both
  LLM calls receive in briefings — not the raw snake_case entity ID. The engine
  rejects item entities without a `name` at load time.
- Add relevant `tags`: `"weapon"` (if usable in combat), `"key_item"` (plot-significant)
- Set `draggable: true` if the item encumbers the player while carried
- Set `dragging_note` to a narrative description of the encumbrance
- Normally no `interactions` or `on_examine` unless the scenario explicitly
  specifies special interactions with the item

### 2F. Feature entities

For features that span multiple rooms:
- Use `spans_rooms` to list all rooms where the feature is visible
- List the entity in each room's `entities_present`

**`follower_blacklist` (for NPCs that follow the player):**

If an NPC can become a follower (via `state_fields.following`), and the
scenario says they refuse to enter certain rooms, add `follower_blacklist`
to the NPC's entity definition listing room IDs they won't enter:

```json
"korbar": {
  "type": "npc",
  "follower_blacklist": ["secret_compartment"]
}
```

When the player moves into a blacklisted room while the NPC is following,
the engine automatically clears the NPC's `following` state and adds a
narrative note. Apply this to any NPC that has location constraints as
a companion.

### 2G. Player entity

Exactly one entity with `type: "player"`.

- `description`: a general description of the player character (from their
  perspective, used when examining oneself).
- `state_fields`: standard fields like `alive` if death is possible.
- No `dialogue_guidelines`, `behavior`, `interactions`, or `on_examine`.

---

### Step 2 validation checklist

- [ ] Exactly one entity has `type: "player"`
- [ ] Every NPC with `dialogue_guidelines` has `attitude` declared in `state_fields`
- [ ] Every NPC with dialogue has a `dialogue_guidelines` block
- [ ] Every NPC that fights has a `behavior` block
- [ ] Every NPC with both dialogue AND combat has both blocks
- [ ] `attitude_limits` on every NPC with `dialogue_guidelines`
- [ ] NPCs that die, flee, or change state after dialogue have a
  `dialogue.ended` reaction (entity-scoped) instead of `on_dialogue_exit`
- [ ] Every `will_reveal` topic's `conditions` array uses valid condition strings
- [ ] Every `set_flag` in `will_reveal` references a flag from Step 1E
- [ ] Every `set_entity_state` in `will_reveal` references an entity that
  has that field in `state_fields`
- [ ] Item entities carry appropriate `tags` where the scenario implies them
- [ ] Every item entity has a non-empty `name` (display name; required by the engine)
- [ ] State fields for `alive` are `true` for creatures that start alive
- [ ] No entity has `dialogue_guidelines` or `behavior` unless `type: "npc"`
- [ ] Entities that span multiple rooms have `spans_rooms` and appear in each
  room's `entities_present`
- [ ] NPCs that refuse to enter certain rooms have `follower_blacklist`
- [ ] Every entity with `hidden` in `state_fields` has `hidden` initialised
  in `entity_states`
- [ ] Every entity with `hidden: true` in initial `entity_states` has at
  least one companion `on_examine` or interaction that can set `hidden: false`
- [ ] Entity `reactions` use valid event types (see [`events.md`](events.md)) and effect fields
- [ ] Entity `reactions` using `"self"` in `trigger_encounter` or
  `trigger_dialogue` are on entities of the correct type (encounter for any,
  dialogue for `npc` only)

---

## Step 3: Build Rooms

**Input:** Room list from Step 1 + entity definitions from Step 2.
**Output:** The full `"rooms"` block for `corpus.json`.

For each room from the room list, produce a complete room definition following
the schema in [`corpus.md`](corpus.md) (§1 Rooms).

### 3A. Room description

Write a full present-tense `description` for the room, replacing the
placeholder description from §1B.

This description is used for both room entry and examination.  Focus
on facts and notable features, as well as key sensory details (what
the player sees, hears, smells, etc.).

Example: "A large square courtyard ringed with laurel trees.  It has a
dilapidated air, with thick weeds sprouting through the cracks between
the flagstones on the ground."

The description can set the tone, but excessively poetic language is
not necessary; the narrator will adapt it into something suitably
atmospheric.

The description should remain accurate regardless of the game state.
DO NOT include entities that might leave the room (e.g., NPCs that
might move elsewhere), or invalidate the description in some way; the
narrator has data about the entities present and can weave in that
information.  DO NOT include hidden information, or clues gated behind
a rigorous search or NPC reveal.

### 3B. Entities present

List the entity IDs (from Step 2) physically in the room at game
start, including hidden entities.

### 3C. Soft items

Plausible generic items the player might pick up. These should be
environmentally appropriate items with no plot significance.

**Test:** Will a condition, mechanic, or specific interaction reference this
thing by name? If yes, it should be a proper entity, not a soft item.

### 3D. Exits

For every exit described in the scenario, produce an exit object:

- **`id`**: `exit_<short_description>` in snake_case
- **`direction`**: Natural language label (e.g., "Climb carefully down the axe handle")
- **`target_room`**: Room ID of the destination
- **`conditions`**: Array of condition objects gating availability. Empty array
  means always available.
- **`hidden`**: `true` for secret exits. Must have a companion mechanic that
  sets a flag, and the exit's conditions should require that flag.
- **`one_way`**: `true` if the exit cannot be traversed in reverse.
- **`traversal_check`**: **Optional.** A check that gates the *attempt*, not
  the *availability*. The exit is visible and the player can try, but may fail
  and stay in place. Use for patterns like "dragging the heavy key requires
  STR check to move between rooms".

Exits do **not** have a `reactions` field. To react to traversal events
(`traversal.succeeded`, `traversal.attempted`, etc.), place reactions on the
**containing room's** `reactions` array. Filter by exit ID using an `event:`
condition:

```json
"reactions": [
  {
    "id": "on_exit_used",
    "on": "traversal.succeeded",
    "condition": { "require": "event:exit_id == exit_climb_down" },
    "effects": {
      "result": { "narrative": "You descend carefully." }
    }
  }
]
```

#### `traversal_check` fields

| Field | Description |
|-------|-------------|
| `check` | The roll or stat_check to resolve |
| `condition` | Optional condition — the check only fires if this is met. When absent (or condition not met), traversal proceeds without a check |
| `skip_check_if` | Optional condition — if met, the check is skipped entirely (bypasses `condition`) |
| `failure_narrative` | Prose shown when the check fails |
| `using_results` | Optional dict mapping item entity IDs (or `"*"` wildcard) to override check/success/failure. When the `move` action carries a `using` parameter matching a key, the override replaces the check (allowing different DCs per item). See below. |

#### `using_results` for traversal checks

When the scenario requires different DCs depending on what the player is
carrying (e.g., clearing webs without a weapon is harder), add a
`using_results` map to the `traversal_check`. Each entry can override the
`check`. The player's `move` action sets `using` to an item entity ID:

```json
"traversal_check": {
  "check": { "type": "stat_check", "stat": "STR", "dc": 14, "repeatable": true },
  "failure_narrative": "You strain against the sticky webs.",
  "using_results": {
    "toenail_sword": {
      "check": { "type": "stat_check", "stat": "STR", "dc": 10, "repeatable": true }
    }
  }
}
```

Use `"*"` as a wildcard key to match any using item (applies a blanket weapon
bonus regardless of which specific weapon is carried).

#### When to use `traversal_check` vs `conditions`

| Pattern | Use |
|---------|-----|
| "Can't leave until spider is resolved" | `conditions: { "require": "flag:spider_fled == true" }` |
| "The key is heavy — STR check to move between rooms" | `traversal_check: { check: { type: "stat_check", ... } }` |
| "Secret compartment is hidden until noticed" | `hidden: true` + companion interaction that sets flag + `conditions: [ { "require": "flag:... == true" } ]` |
| "Dropping down is one-way" | `one_way: true` (and a separate exit to go back up) |

#### Clearable obstacle pattern (one-time obstacle)

When the player must overcome an obstacle to pass (e.g., force through a
spider's web), and once cleared the obstacle is no longer an impediment:

1. Add a `traversal_check` on the blocked exit with the initial check
2. Use `skip_check_if` on the `traversal_check` to bypass once the flag is set
3. Add a `traversal.succeeded` reaction (on the room or the exit's containing
   room) that matches this exit and sets the flag / triggers the encounter

```json
{
  "exit_force_through_web": {
    "target_room": "axe_handle_lower",
    "traversal_check": {
      "condition": { "unless": "flag:webs_cleared == true" },
      "check": { "type": "stat_check", "stat": "STR", "dc": 14, "repeatable": true },
      "skip_check_if": { "require": "flag:webs_cleared == true" },
      "failure_narrative": "You strain against the sticky webs but can't break through."
    }
  }
},
"reactions": [
  {
    "id": "clear_webs_on_force",
    "on": "traversal.succeeded",
    "condition": { "require": "event:exit_id == exit_force_through_web" },
    "effects": {
      "result": {
        "narrative": "You burst through the webs, clearing a path.",
        "set_flag": { "webs_cleared": true }
      },
      "trigger_encounter": "spider_attack"
    }
  }
]
```

#### Global traversal check (item weight)

If carrying a certain item makes every exit harder (e.g., a heavy body),
the same `traversal_check` must be duplicated on **every exit** the player
can use while carrying it. There is currently no mechanism to apply a
traversal check globally — per-exit duplication is the required pattern.

```json
"exit_up_stairs": {
  "target_room": "foyer",
  "traversal_check": {
    "condition": { "require": "inventory:dead_body" },
    "check": { "type": "stat_check", "stat": "STR", "dc": 13, "repeatable": true },
    "skip_check_if": { "require": "entity:butler.following == true" },
    "failure_narrative": "The body is too heavy to haul up the stairs."
  }
}
```

Apply this same block to every relevant exit. Use `skip_check_if` there is a way to skip the requirement.

#### Explicit win traversal action

For win conditions that require an explicit player action in a specific room, one implementation trick is to create an exit representing that final action.  Target it to a virtual exit room (not a real room) or use an interaction that sets the final flag:

```json
{
  "id": "exit_enter_vault",
  "direction": "Enter the treasure vault",
  "target_room": "vault_interior",
  "hidden": true,
  "conditions": [{ "require": "flag:vault_unlocked == true" }]
}
```

with a room-scoped reaction:

```json
"reactions": [
  {
    "id": "enter_vault_sets_flag",
    "on": "traversal.succeeded",
    "condition": { "require": "event:exit_id == exit_enter_vault" },
    "effects": {
      "result": {
        "narrative": "You turn the heavy wheel and the vault door swings open, revealing glittering treasure within.",
        "set_flag": { "player_entered_vault": true }
      }
    }
  }
]
```

Then reference `flag:player_entered_vault` in the win condition's
`condition`. This ensures the player must explicitly choose the final
action, which is distinct from the engine passively detecting a condition.

### 3E. Interactions (room-level)

Define interactions only for room-specific actions that aren't covered by
generic actions (attack, examine, move, talk, transfer).

#### When to use `interaction` vs `on_examine`

A **frequent anti-pattern** is placing examine-gated discoveries in
`interactions` instead of `on_examine` events. Use this decision table:

| Scenario phrase | Right mechanism |
|-----------------|-----------------|
| "Upon examining the pile, the player notices a toenail" | `on_examine` on the pile entity (or room), with a `result` containing `narrative` |
| "The player rummages through the pile and pulls out a sword" | `interaction` on the room, with a `check` and `success.add_item` |
| "Looking closely at the webs reveals a hidden spider (WIS check)" | `on_examine` on the webs entity, with a `check` |
| "The player hauls aside the heavy handkerchief (STR check)" | `interaction` on the room, with a `check` |
| "The player picks the lock (DEX check)" | `interaction` on the room or feature, with a `check` |
| "When the player studies the carving, they recognize the symbol" | `on_examine` on the carving entity, with a `result` |

**Key rule:** If the scenario describes something the player **notices,
sees, or recognizes** by looking closely, it belongs in `on_examine`.
If the scenario describes something the player **does, manipulates, or
actively performs** (searching, pulling, forcing, hauling), it belongs
in `interaction`.

In the common two-step pattern "examine reveals an item; taking it
requires a check":

1. **Step 1 — reveal:** Add an `on_examine` event on the containing entity
   or room. It produces a `narrative` describing what the player sees,
   sets a `flag` (e.g. `toenail_noticed`), and **unhides** the contained
   item via `set_entity_state`.
2. **Step 2 — take:** Add the item entity to the container's
   `contained_entities` and give it a `take_check`. The player then uses a
   `transfer` action to take the item, and the engine resolves the
   `take_check` automatically. (No separate interaction needed.)

The contained item does **not** need to appear in the room's
`entities_present`. The context assembler surfaces all non-hidden
contained entities through the parent entity's `contained_entities`
field in the LLM briefing. Once the item is unhidden, the LLM sees it
in the container's briefing entry and can propose a `transfer` targeting
the container.

Example — a loose pile containing a sword that takes effort to pull free:

```json
// Entity: the rubbish pile
"rubbish_pile": {
  "type": "feature",
  "contained_entities": ["toenail_sword"],
  "on_examine": [
    {
      "id": "notice_toenail",
      "condition": { "require": "flag:toenail_noticed == false" },
      "rigorous_only": false,
      "result": {
        "narrative": "Among the rubbish, you spot a giant toenail clipping — curved and razor-edged.",
        "set_flag": { "toenail_noticed": true },
        "set_entity_state": { "toenail_sword": { "hidden": false } }
      }
    }
  ]
},

// Entity: the item — must declare 'hidden' in state_fields
"toenail_sword": {
  "type": "item",
  "name": "Toenail Sword",
  "state_fields": {
    "hidden": { "type": "boolean", "description": "Whether the sword is visible." }
  },
  "take_check": {
    "check": { "type": "stat_check", "stat": "DEX", "dc": 8, "repeatable": true },
    "success": {
      "narrative": "You work the toenail free from the pile. It's a perfect makeshift shortsword.",
      "set_flag": { "toenail_sword_found": true }
    },
    "failure": {
      "narrative": "You grasp at the toenail but it's stuck fast. You'll need to try again."
    }
  }
}

// In hard-state.json: initialize the contained entity as hidden
// "entity_states": {
//   "toenail_sword": { "hidden": true }
// }
```

Note: the item does NOT need to be listed in the room's `entities_present`
array. The assembler discovers it through `rubbish_pile.contained_entities`
and surfaces it (if not hidden) in the parent entity's briefing.

With this setup: examining the pile → reveals/unhides the toenail
(Step 1). The next turn's briefing shows `toenail_sword` in
`rubbish_pile.contained_entities`. A `transfer` action to take
`toenail_sword` from `rubbish_pile` → engine runs the `take_check`
(Step 2). No `interaction` is needed, no `entities_present` duplication.

Each interaction must have:
- **`id`**: snake_case, unique within the room
- **`label`**: short UI label
- **`description`**: what the player is attempting
- `check` + `success` + `failure`, or `result` (deterministic)

#### Deterministic (no check)
```json
{
  "id": "leave_secret_compartment",
  "label": "Leave",
  "description": "Squeeze back out of the secret compartment.",
  "result": { "narrative": "You squeeze back out to the Bag Floor." }
}
```

#### Probabilistic (with check)
```json
{
  "id": "rummage_rubbish",
  "label": "Rummage through rubbish",
  "description": "Search through the pile of rubbish for useful items.",
  "check": {
    "type": "stat_check",
    "stat": "DEX",
    "dc": 10,
    "repeatable": true
  },
  "success": {
    "narrative": "Your hands close on something sharp — a giant toenail clipping, usable as a weapon.",
    "add_item": "toenail_sword"
  },
  "failure": {
    "narrative": "You find nothing useful."
  }
}
```

#### Using_results for item-specific overrides

When an interaction has different outcomes depending on what the player uses,
you may define a `using_results` map. This allows the same interaction to resolve differently based on the `using` parameter of the `interact` action:

```json
{
  "id": "force_through_web",
  "label": "Force through web",
  "description": "Push through the dense webbing.",
  "check": {
    "type": "stat_check",
    "stat": "STR",
    "dc": 14,
    "repeatable": true
  },
  "success": {
    "narrative": "You force your way through the sticky webbing."
  },
  "failure": {
    "narrative": "You struggle but can't break through."
  },
  "using_results": {
    "toenail_sword": {
      "check": {
        "type": "stat_check",
        "stat": "STR",
        "dc": 10,
        "repeatable": true
      },
      "success": {
        "narrative": "You slash through the webbing with the sharp toenail clipping."
      },
      "failure": {
        "narrative": "You hack at the webs but can't cut through."
      }
    }
  }
}
```

#### Chained checks pattern

When a check result triggers a follow-up check (for escalating consequences,
multiple stages, or branching outcomes), encode the follow-up as
`chain_check` on the success or failure result of the first check.

The typical structure is: a failed (or succeeded) check leads to a second
check with its own success/failure branches. The second check's failure may
set a flag that a game-over mechanic watches for, or it may simply produce
a narrative outcome:

```json
{
  "id": "vault_trap",
  "label": "Disarm the vault trap",
  "description": "Attempt to disarm the pressure plate.",
  "check": {
    "type": "stat_check",
    "stat": "DEX",
    "dc": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You carefully disable the pressure plate. The vault is safe."
  },
  "failure": {
    "narrative": "The mechanism clicks. Dart shooters whir to life!",
    "chain_check": {
      "check": {
        "type": "stat_check",
        "stat": "DEX",
        "dc": 10,
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

When the chain check's final failure sets a game-over flag, pair it with
a `lose` mechanic:

```json
"fell_to_chasm": {
  "id": "fell_to_chasm",
  "type": "lose",
  "description": "Player falls into the chasm.",
  "condition": { "require": "flag:fallen_into_chasm == true" },
  "narrative": "You lose your footing and tumble into the darkness below.",
  "trigger_id": "chasm_fall"
}
```

#### Stat-check-gated attitude changes via `dialogue_paths`

When a scenario calls for a CHA check (or other stat check) to mechanically change an NPC's attitude during special dialogue paths, define a `dialogue_path` in the NPC's `dialogue_guidelines`. The player uses a `talk` action with `dialogue_path` set to the path ID; the engine resolves the check
and applies `adjust_attitude` (or other results) directly.

Example: a spider that can be flattered with a CHA check to improve attitude:

```json
"dialogue_paths": {
  "flatter": {
    "description": "Praise the spider's hunting prowess to improve its attitude toward the player.",
    "condition": { "require": "attitude:spider < 0" },
    "check": {
      "type": "stat_check",
      "stat": "CHA",
      "dc": 12,
      "repeatable": true
    },
    "success": {
      "narrative": "The spider preens at your praise.",
      "adjust_attitude": { "spider": 1 }
    }
  }
}
```

**NPC action blocking pattern:**

When an NPC's presence or attitude should block the player from using an
interaction or examining a room, add a `condition` to the interaction that
checks the NPC's attitude. If the NPC has low attitude and is present, the
interaction is unavailable (or produces a different result):

```json
{
  "id": "move_handkerchief",
  "label": "Haul aside the handkerchief",
  "description": "Pull back the damp handkerchief to see what's underneath.",
  "condition": {
    "any": [
      { "require": "entity:korbar.alive == false" },
      "attitude:korbar >= 3",
      "flag:korbar_knows_handkerchief == true"
    ]
  },
  "check": { "type": "stat_check", "stat": "STR", "dc": 10, "repeatable": true },
  "success": {
    "narrative": "You heave the heavy handkerchief aside, revealing a flap in the canvas floor.",
    "set_flag": { "handkerchief_moved": true },
    "reveals": "The handkerchief conceals a flap leading to a secret compartment."
  },
  "failure": {
    "narrative": "The handkerchief is heavier than it looks. You struggle but can't move it."
  }
}
```

When `condition` is not met, the engine omits the interaction from the available
actions presented to the LLM, effectively blocking the action. Use `any` to
model alternative unblocking conditions (NPC dead, high enough attitude, or
flag already set).

### 3F. On-enter events

For each room, identify any events that should fire when the player enters:

- Introductory flavour on first entry
- NPC auto-dialogue (use `trigger_dialogue`)
- Conditional events (e.g., spider is in this room, trigger an encounter)
- Flag changes or entity state changes on first visit

**Pattern for one-shot first-entry events:**
```json
{
  "id": "first_entry_axe_head",
  "condition": null,
  "narrative": "The axe head leans at an angle. The handle slopes down into darkness."
}
```
With `condition: null`, the event fires on first entry only (the engine tracks it).

**Pattern for conditional automatic events:**
```json
{
  "id": "fly_groans",
  "condition": { "require": "entity:stuck_fly.alive == true" },
  "narrative": "A groaning sound comes from the webbing nearby."
}
```

### 3F-2. Room reactions

Reactions on rooms fire when the player is in that room. Use them for
event-driven triggers that respond to game events (flag changes, check
outcomes, item acquisition, etc.). See [`events.md`](events.md) for the full
list of event types and context keys.

**Common patterns:**

State-based trigger reacting to a flag change:
```json
"reactions": [
  {
    "id": "room_cleared_reaction",
    "on": "flag.set",
    "condition": { "require": "event:flag_name == spider_fled" },
    "effects": {
      "result": {
        "narrative": "With the spider gone, you can finally look around properly.",
        "set_flag": { "room_safe": true }
      }
    }
  }
]
```

Failed-check consequence:
```json
"reactions": [
  {
    "id": "web_fail_damage",
    "on": "check.failed",
    "condition": {
      "all": [
        { "require": "event:source_id == force_through_web" },
        { "require": "event:check_type == stat_check" }
      ]
    },
    "effects": {
      "result": {
        "narrative": "The webs constrict painfully around you.",
        "alter_stat": { "STR": { "value": -2 } }
      }
    }
  }
]
```

**When to use room reactions:**
- `reactions`: event-driven triggers that respond to any game event while the
  player is in the room. Use `on: "room.entered"` for effects that should fire
  when the player enters the room (replacing the legacy `on_enter` field).

**Timing note:** Reactions on state-change events (`flag.set`,
`entity_state.changed`, `stat.changed`) fire during **deferred dispatch** at
end-of-turn, not immediately after the triggering action. To chain an
immediate follow-up check within a single action (e.g., a second stat check
right after the first), use `chain_check` on the success/failure result
(see Step 3E).

### 3G. On-examine events

For examine-gated stat checks or conditional discoveries:

**Note:** Earlier versions of this document mistakenly labelled this
section "Step 6". The correct location is Step 3G.

On-examine events fire when the player uses the `examine` (or `examine
(rigorous)`) action. They can be placed on rooms or on individual
entities.  See § 3E for the decision table on when to use `on_examine`
vs `interaction`.

Fields:
- `id`: unique identifier for this event
- `condition`: controls when the event is available (optional)
- `rigorous_only`: `true` if the player must use a rigorous examine to trigger
- `check` + `success` + `failure`: a stat_check or roll with outcome branches
- `result`: a deterministic outcome (no check needed)

#### Pattern A: Deterministic discovery (no check)

When examining something always reveals something — no stat check needed.
Use `result` (not `check`/`success`):

```json
{
  "id": "notice_toenail",
  "condition": { "require": "flag:toenail_noticed == false" },
  "rigorous_only": false,
  "result": {
    "narrative": "Among the rubbish, you spot a giant toenail clipping — curved and razor-edged. It's disgusting, but it could work as a shortsword.",
    "set_flag": { "toenail_noticed": true }
  }
}
```

This pattern is appropriate when the scenario says "examining the pile
reveals..." or "upon closer inspection, the player notices..." without
mentioning a check. The `condition` prevents the event firing again
once the flag is set.

#### Pattern B: Examine-gated stat check

When noticing something requires a check (perception, knowledge, etc.):

```json
{
  "id": "study_canvas_glow",
  "condition": { "unless": "flag:glow_noticed == true" },
  "check": {
    "type": "stat_check",
    "stat": "INT",
    "dc": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "You deduce that the faint luminescence is magical in nature.",
    "set_flag": { "glow_noticed": true }
  }
}
```

#### Pattern C: Rigorous-only lore deductions

Some discoveries require a thorough, dedicated examination. Use
`rigorous_only: true` for these — they only fire when the player uses
`examine (rigorous)`, not a casual look:

```json
{
  "id": "realize_supplies",
  "condition": { "unless": "flag:realized_supplies == true" },
  "rigorous_only": true,
  "check": {
    "type": "stat_check",
    "stat": "INT",
    "dc": 8,
    "repeatable": false
  },
  "success": {
    "narrative": "As you look over the rubbish, something clicks. This isn't a random pile — it's adventuring gear.",
    "set_flag": { "realized_supplies": true },
    "reveals": "The rubbish is actually someone's adventuring supplies, shrunk by the Bag's magic."
  }
}
```

#### Pattern D: Revealing a hidden entity

When the examination uncovers a previously hidden creature or object,
use `set_entity_state` to un-hide it. The entity must have `hidden`
declared in its `state_fields` and set to `true` in `hard-state.json`:

```json
{
  "id": "reveal_fly",
  "condition": {
    "all": [
      { "require": "entity:stuck_fly.hidden == true" },
      { "require": "entity:stuck_fly.alive == true" }
    ]
  },
  "rigorous_only": false,
  "result": {
    "narrative": "As you examine the sticky strands, one of the masses twitches. It's a FLY — about the size of a dog, tightly wrapped in webbing. Its multifaceted eyes swivel weakly toward you.",
    "set_entity_state": { "stuck_fly": { "hidden": false } },
    "set_flag": { "fly_revealed": true }
  }
}
```

The `condition` uses event-type conditions (`entity:<id>.<field>`).

#### Entity vs room placement

When the scenario says "examining the statue, the player notices...",
place the `on_examine` on the **statue entity**, not the room.  When
the scenario says "examining the chamber, the player notices...", place
it on the **room**.  See § 2F for the full distinction.

#### Multiple on_examine events on one target

An entity or room can have multiple `on_examine` events. Each is
evaluated independently in definition order, and each matching event's
narrative is appended.  Use this when a successful INT check chains
into a second lore check (see the bag_of_holding_from_rubbish event in
the Bag of Holding corpus for an example of gated sequential
deductions).

---

### Step 3 validation checklist

- [ ] Every room has a `name` and `description`
- [ ] Exactly one room has `is_start_room: true`
- [ ] Every exit `target_room` references a valid room ID
- [ ] Every exit ID is unique across all rooms
- [ ] Every entity in `entities_present` exists in the `entities` block
- [ ] Every `trigger_encounter` in a `traversal.succeeded` reaction
  references a mechanic that will be created in Step 4
- [ ] Every `trigger_dialogue` references a valid NPC entity ID
- [ ] Every `set_entity_state` references an entity with that field in
  `state_fields`
- [ ] Every `set_flag` references a flag name from Step 1E
- [ ] Hidden exits have a flag-based reveal pattern (companion interaction
  sets flag, exit conditions require flag)
- [ ] One-way exits have a separate exit to go back (or a narrative reason
  they're permanently one-way)
- [ ] Every condition object follows the condition object format — no bare
  condition strings outside `any`/`all` arrays
- [ ] Every interaction with a check also has `success` and optionally
  `failure`
- [ ] Every interaction without a check has `result`
- [ ] Every `on_examine` event with a `check` has `success`
- [ ] Every `on_examine` event without a `check` has `result`
- [ ] Interactions that should accept a `using` item have a
  `parameter_signature` defining accepted types
- [ ] If interactions reference `using_results`, each key is a valid entity ID
  or `"*"` wildcard
- [ ] Room `reactions` use valid event types (see [`events.md`](events.md)) and effect fields
- [ ] Room `reactions` with `event:` conditions reference valid context keys
  for their event type (see [`events.md`](events.md))

---

## Step 4: Build Mechanics

**Input:** Mechanic list from Step 1 + entities/rooms from Steps 2-3.
**Output:** The full `"mechanics"` block for `corpus.json`.

Two kinds of mechanics live here: encounters and game-over conditions.
Reaction-only mechanics (adventure-wide state-based triggers) also belong here.

### 4A. Encounters

Encounters are referenced by exits (via `trigger_encounter`) or interactions.
They follow the same rule structure as NPC behavior encounter_rules:

```json
"fall_damage": {
  "id": "fall_damage",
  "description": "Player drops from various heights on the axe handle.",
  "rules": [
    {
      "condition": { "require": "room:axe_head.is_current == true" },
      "outcome": "stat_check",
      "check": { "type": "stat_check", "stat": "DEX", "dc": 8, "repeatable": true },
      "on_success": {
        "narrative": "You drop down and land heavily, but survive."
      },
      "on_failure": {
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
| `outcome` | str | `"death"`, `"flee"`, `"roll"`, `"stat_check"`, or `"combat"` |
| `condition` | condition object | Gate for the rule |
| `check` | StatCheck | The stat check to resolve (for `stat_check` outcome) |
| `threshold` | float 0-1 | Roll-under threshold (for `roll` outcome) |
| `narrative` | str | Prose shown when the rule fires |
| `set_flags` | dict[str, bool] | Flags to set |
| `alter_stat` | dict[str, StatModifier] | Fixed stat modifications (delta or set) |
| `player_damage` | str | Dice expression rolled as HP damage (e.g. `"3d6"`, `"2d4+1"`) |
| `on_success` | BranchOutcome | Branch when check/roll succeeds |
| `on_failure` | BranchOutcome | Branch when check/roll fails |

`player_damage` is available at both the rule level (applies unconditionally
when the rule fires) and the branch level (overrides the rule-level value).
The engine rolls the dice expression using the active resolution system.

### 4B. Game-over conditions

Model win and loss conditions as mechanic entries with `type: "win"` or
`"lose"`:

```json
"completed_quest": {
  "id": "completed_quest",
  "type": "win",
  "description": "Player completes the main quest.",
  "condition": {
    "all": [
      "flag:artifact_retrieved == true",
      "flag:player_escaped == true"
    ]
  },
  "narrative": "You emerge into the morning light, the ancient artifact clutched to your chest. Your quest is complete.",
  "trigger_id": "quest_complete"
}
```

```json
"death_by_fall": {
  "id": "death_by_fall",
  "type": "lose",
  "description": "Player falls into the chasm.",
  "condition": { "require": "flag:fallen_into_chasm == true" },
  "narrative": "You lose your footing and tumble into the darkness below. The fall is long, and then there is nothing.",
  "trigger_id": "chasm_fall"
}
```

For multi-step win conditions, use `"all"` to combine separate flags. Each
flag should be set by a different interaction, exit, or encounter along the
critical path.

### 4C. Reaction-only mechanics

For adventure-wide state-based triggers that aren't tied to a specific room or
entity, create a mechanic with only a `reactions` array (no `type`, `rules`, or
`trigger_id`). See [`events.md`](events.md) for the full list of event types
and context keys.

```json
"global_reactions": {
  "id": "global_reactions",
  "description": "Adventure-wide state-based reactions.",
  "reactions": [
    {
      "id": "near_death_warning",
      "on": "player.damaged",
      "condition": { "require": "event:new_hp <= 3" },
      "effects": {
        "result": {
          "narrative": "You are gravely wounded. One more hit could be your last.",
          "set_flag": { "near_death": true }
        }
      }
    }
  ]
}
```

Use reaction-only mechanics when:
- The trigger is adventure-wide (not scoped to a room or entity)
- The trigger responds to state changes (flags, stats, attitudes) rather than
  specific actions
- Multiple reactions share a logical grouping (e.g., all environmental effects)

#### Chained encounters via reaction-only mechanics

A reaction can trigger an encounter whose outcome sets a flag, and a second
reaction can fire on that flag to trigger another encounter. Keep chains short
and condition them carefully to avoid runaway loops.

```json
"global_reactions": {
  "id": "global_reactions",
  "description": "Chains the guardian fight into the wraith ambush.",
  "reactions": [
    {
      "id": "guardian_awakens",
      "on": "room.entered",
      "condition": { "require": "event:room_id == cave_depths" },
      "effects": { "trigger_encounter": "guardian_attack" }
    },
    {
      "id": "wraith_appears",
      "on": "flag.set",
      "condition": { "require": "event:flag_name == guardian_defeated" },
      "effects": { "trigger_encounter": "wraith_ambush" }
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

- [ ] Every encounter from the scenario is represented
- [ ] Every win condition is a mechanic with `type: "win"`
- [ ] Every loss condition is a mechanic with `type: "lose"` or `"death"`
- [ ] Every mechanic referenced by a `trigger_encounter` exists in the block
- [ ] Every `trigger_id` is unique across all mechanics
- [ ] Game-over mechanics have `condition`, `narrative`, and `trigger_id`
- [ ] Encounter mechanics have `rules` (not `condition`/`type`/`trigger_id`)
- [ ] Reaction-only mechanics have `reactions` only (no `type`/`rules`/`trigger_id`)
- [ ] If stats block present: only stats actually used are defined
- [ ] If stats block absent: no stat_check interactions or stat: conditions
  exist in rooms/entities
- [ ] Reaction-only mechanics have `reactions` but no `type` or `rules`
- [ ] Reaction-only mechanic `reactions` use valid event types (see [`events.md`](events.md)) and effect fields

---

## Step 5: Build hard-state.json

**Input:** Everything from Steps 2-4 + flag list from Step 1.
**Output:** Complete `hard-state.json` file.

Follow this exact structure:

```json
{
  "player": {
    "location": "<start_room_id>",
    "inventory": [],
    "stats": { /* only if corpus has a stats block */ }
  },
  "flags": {
    "<flag_name>": false,
    ...
  },
  "room_states": {
    "<room_id>": { "visited": false, ... },
    ...
  },
  "entity_states": {
    "<entity_id>": { "<field>": <initial_value>, ... },
    ...
  },
  "turn_count": 0,
  "game_over": null
}
```

### Step-by-step assembly

1. **`player.location`** — set to the room ID with `is_start_room: true`

2. **`player.inventory`** — always `[]` at start unless the scenario specifies
   starting items (extremely rare). Even if the player "has" something narratively,
   it's usually a soft item or entity in the start room.

3. **`player.stats`** — only if the corpus has a `stats` block. Under 5e,
   typical values range 3-18 with 10 as average. If the scenario doesn't specify
   stat values, use 10 across all stats declared in the corpus definitions.

4. **`flags`** — enumerate every flag name used anywhere:
   - In condition strings (`flag:...`)
   - In `set_flag` results
   - In encounter `set_flags`
   - In `on_examine` events and reaction `result.set_flag` effects
   Set each to its initial value (almost always `false`). This is a flat dict;
   all flag values should be booleans.

5. **`room_states`** — for every room in the corpus, add `{ "visited": false }`.
   If a room has additional state fields (none currently defined), add those
   with initial values.

6. **`entity_states`** — for every entity that declared `state_fields` in the
   corpus, add an entry with initial values for every declared field:
   - Boolean fields: `false` (or `true` for `alive` on things that start alive)
   - Number fields: `0` (or the NPC's `attitude_limits.initial` for attitude)
   - String fields: `""`
   **Do not skip any entity that has state_fields.** Every field declared in
   the entity's `state_fields` must have a value here.

7. **`turn_count`** — always `0`.

8. **`game_over`** — always `null`.

---

### Step 5 validation checklist

- [ ] Every room in corpus has a `room_states` entry with `visited: false`
- [ ] Every entity with `state_fields` in corpus has an `entity_states` entry
  with every field initialised
- [ ] Every flag name used anywhere in the corpus appears in `flags`
- [ ] `player.location` references the room with `is_start_room: true`
- [ ] No entity in `player.inventory` also appears in a room's
  `entities_present` at start
- [ ] If corpus has `stats`: `player.stats` is present, and every key matches
  a key in `stats.definitions`
- [ ] If corpus has no `stats`: `player.stats` is absent
- [ ] Every NPC with `dialogue_guidelines` has `"attitude"` set to the value from the NPC's
  `attitude_limits.initial` (default 0) in `entity_states`
- [ ] Every NPC with `dialogue_guidelines` has `attitude` in both `state_fields` and `entity_states`
- [ ] `turn_count` is `0`
- [ ] `game_over` is `null`

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

Run this checklist after all three JSON files are generated. This catches
cross-file consistency issues.

### Universal checks

- [ ] Every flag name used in any condition string, `set_flag`, or
  `set_entity_state` appears in `hard_state.flags`
- [ ] Every room ID referenced in any exit `target_room`, `spans_rooms`,
  `follower_blacklist`, etc. exists in `corpus.rooms`
- [ ] Every entity ID referenced in any `entities_present`, `add_item`,
  `remove_item`, `set_entity_state`, `trigger_dialogue`, `using_results`
  key, etc. exists in `corpus.entities`
- [ ] Every mechanic ID referenced in any `trigger_encounter` exists in
  `corpus.mechanics`
- [ ] Every `trigger_encounter` in a reaction references a valid mechanic ID
  or entity ID (or is `"self"` on an entity-scoped reaction)
- [ ] Every `trigger_dialogue` in a reaction references a valid NPC entity ID
  (or is `"self"` on an NPC entity)
- [ ] Every reaction `on` field is a valid event type (see [`events.md`](events.md))
- [ ] Every NPC with `dialogue_guidelines.will_reveal` entries has
  matching `set_flag` / `set_entity_state` values that exist
- [ ] Every `adjust_attitude` key references a valid NPC entity that has
  `attitude` declared in `state_fields`

### Corpus self-consistency

- [ ] `flags_declared` is present as a top-level list of all flag names used
  in conditions and set_flag results
- [ ] Every flag in `flags_declared` exists in `hard_state.flags`
- [ ] No duplicate IDs across all rooms, exits, entities, interactions,
  mechanics, reactions, flags, and topics
- [ ] Every `will_reveal.conditions` string references entities, flags,
  attitudes, topics, or tags that exist in the corpus/hard state
- [ ] Every `on_examine` event with a condition references an existing flag
- [ ] Every `using_results` key is either an entity ID in corpus or `"*"`
- [ ] Every stat check (stat_check type) references a stat key in
  `corpus.stats.definitions` (if stats block exists; otherwise, no stat_check
  should appear)
- [ ] Every `alter_stat` result references a stat key in `stats.definitions`
  (if stats block exists; otherwise, no alter_stat should appear)

### Hard-state checks

- [ ] `hard_state.player.location` matches the room with `is_start_room: true`
- [ ] Every entity with `state_fields` has a complete `entity_states` entry
- [ ] `entity_states` contains no fields not declared in the entity's `state_fields`
- [ ] Entities with `hidden: true` in initial `entity_states` are still
  listed in the room's `entities_present` (the engine handles filtering
  based on the state field)
- [ ] `entity_states` contains all fields declared in the entity's `state_fields`
- [ ] Every NPC with `dialogue_guidelines` has `attitude` in both `state_fields` and `entity_states`
- [ ] NPC attitude values are within the `[min, max]` range from their
  `attitude_limits`

### Soft-state checks

- [ ] Every NPC with `dialogue_guidelines` has `attitude` initialised in `entity_states`
- [ ] `dialogue_state` has the standard null structure
- [ ] `player_knowledge` is `[]`

After completing all three JSON files and this checklist, run the
engine's validator to catch mechanical errors you might have missed:

```
python scripts/validate_adventure.py <adventure_dir>
```

Fix any reported issues before declaring the generation complete.

---

## Condition Syntax Reference

All condition fields use **condition objects** — never bare strings. This
enables compound AND/OR logic with nesting.

### Simple condition (object-based)

```json
{ "require": "flag:spider_fled == true" }
{ "unless": "flag:injured == true" }
```

### Compound condition (AND/OR with nesting)

```json
{ "any": [
  "flag:handkerchief_noticed == true",
  { "all": [
    "attitude:korbar >= 4",
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
| `inventory`  | `inventory:rusty_key`            | Item entity ID in player inventory |
| `item`       | `item:rusty_key`                 | Alias for `inventory` |
| `tag`        | `tag:weapon`                     | Any item with this tag in player inventory |
| `entity`     | `entity:spider.alive == true`    | Entity hard-state field |
| `room`       | `room:axe_head.visited == true`  | Room state field |
| `attitude`   | `attitude:korbar >= 2`           | NPC soft-state attitude |
| `topic`      | `topic:abandonment`              | Topic ID discussed in current dialogue |
| `stat`       | `stat:STR >= 12`                 | Player stat value vs threshold. Requires corpus.stats. |
| `event`      | `event:exit_id == exit_climb`    | Event context value. Only valid during reaction dispatch. |
| `any`        | *compound*                       | At least one sub-condition must be true |
| `all`        | *compound*                       | All sub-conditions must be true |
| `require`    | `{ "require": "..." }`           | Condition must be true |
| `unless`     | `{ "unless": "..." }`            | Condition must be false |

Supported ops: `== true`, `== false`, `== <string>`, `>= <number>`,
`> <number>`, `<= <number>`, `< <number>`.

### Usage notes

- For `unless`, the inner condition being true **blocks** the action
- `inventory` and `tag` test presence, not equality
- `tag:weapon` succeeds if *any* item in inventory has the `"weapon"` tag
- `stat:STR >= 12` evaluates the player's current Strength value (only valid
  when corpus has a `stats` block)
- `topic:<id>` succeeds if the topic ID appears in
  `dialogue_state.topics_discussed`
- `room:<id>.is_current` is a special value that checks if the player is
  currently in that room (available in encounter rules)
- `event:<key>` checks a value in the current event context. Only valid inside
  reaction conditions during dispatch. Outside dispatch, evaluates to `false`.
  Common keys: `exit_id`, `interaction_id`, `npc_id`, `flag_name`, `source_id`,
  `check_type`, `stat`, `amount`, `new_hp`.

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
   `hard_state.flags` with an initial value.

3. **Missing state_fields declarations**: Every mutable property of an entity
   that changes during play must be declared in `state_fields`. The engine
   validates that `entity_states` and `state_fields` match at startup.

4. **Hidden exits without reveal conditions**: A `hidden: true` exit needs a
   companion interaction that sets a flag; the exit's `conditions` should
   require that flag. Otherwise the exit is permanently invisible.

5. **One-way exits without return path**: A `one_way: true` exit should have a
   separate exit for the return direction (or the scenario narrative justifies
   the one-way nature).

6. **Duplicate IDs**: Ensure every ID (room, entity, exit, interaction,
   mechanic, flag, topic) is unique across the entire corpus.

7. **NPCs with neither dialogue_guidelines nor behavior**: Conversational NPCs
   need `dialogue_guidelines`; combat NPCs need `behavior`. An NPC with
   neither will be purely decorative. If the scenario expects interaction,
   one of these must be present.

8. **Condition syntax**: All condition fields use the condition object form
   (`{ "require": "..." }`, `{ "unless": "..." }`, `{ "any": [...] }`,
   `{ "all": [...] }`). Bare strings are not accepted outside `any`/`all`
   arrays.

9. **Attitude initialisation**: Each NPC's initial attitude must be in both
   `state_fields` (declaration) and `entity_states` (value), and match the
   NPC's `attitude_limits.initial`.

10. **Item placement**: Items that start in a specific location appear in
    that room's `entities_present`. Items the player starts carrying are in
    `hard_state.player.inventory`. Never put the same item ID in both.

11. **Prose style**: All `description`, `narrative`, and `introduction` fields
    should be in second-person present tense ("You see... You are...").

12. **Stat value ranges**: Under 5e, stat values typically range 3-18. DCs
    should match character capabilities: stat 10 (+0 modifier) has ~55% vs
    DC 10, ~30% vs DC 15, ~5% vs DC 20. Do not set impossible DCs without
    an alternative path.

13. **Chained check maximal depth**: Nested chain_check supports up to 3
    levels of depth.

14. **Follower_blacklist**: If an NPC follows the player, and the scenario
    says they refuse to enter certain rooms, add `follower_blacklist` to
    the NPC's entity definition.

15. **Chain check does not trigger game-over directly**: A `chain_check`
    failure cannot set `game_over` directly. Instead, use `set_flag` in the
    failure result and add a `lose` mechanic watching that flag.

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
    The legacy `on_enter`, `on_traverse`, `behavior.triggers_on`, and
    `on_dialogue_exit` fields have been removed.

21. **`event:` domain only works in reactions**: The `event:` condition domain
    is only valid inside reaction conditions during dispatch. Using it in
    interaction conditions, game-over mechanic conditions, or exit conditions
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
    event must go on the lever entity, not on the room.  See § Step 2F
    for guidance.

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
