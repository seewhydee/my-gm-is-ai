# Scenario-to-JSON Generation Instructions

This document is a prompt/checklist for an LLM to convert a
natural-language adventure scenario (e.g., `scenario.md`) into an
adventure module consisting of three structured JSON files:

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
Step 5: Build hard-state.json
     │  Output: complete hard-state.json
     ▼
Step 6: Build soft-state.json
     │  Output: complete soft-state.json
     ▼
Cross-file validation
```

Each step produces intermediate output in the adventure module folder.
Step 1 writes the Scenario Map — a document named `scenario-map.md`
that all subsequent steps read from.  Steps 2–4 produce draft corpus
blocks; Steps 5–6 produce the final `hard-state.json` and
`soft-state.json`.  After cross-file validation, assemble the complete
`corpus.json` from the draft blocks.

At the end of every step, run through the step's validation checklist.
If anything fails, **stop and fix before proceeding**.

---

## Step 1: Parse & Extract

**Objective:** make a structured list of everything that needs to be
modelled, including consistent IDs for all rooms, entities, flags,
interactions, state fields, entity tags, etc.  All IDs in snake_case.

Read README.md and doc/intro.md, followed by the supplied scenario
(usually a Markdown file in adventures/MODULE-NAME/).

Then follow the specs below to write a Scenario Map (a text document,
not JSON), and save it to `scenario-map.md` in the adventure module
folder.  This will be the working plan for all subsequent steps.
Follow steps 1A to 1H carefully, and in order.

### 1A. Adventure metadata

Write down, at the top of the Scenario Map:

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

Now we will construct a list of rooms based on the scenario.  Every
distinct location that can be visited should be a room.  Avoid
creating extra rooms not in the scenario, *unless* necessary for
gameplay (in which case note this in your report).

For each room, write out:

- **Room ID** — assign a globally-unique ID.

- **Room name** — a short identifying phrase (e.g., for traversal).
  Avoid giving consecutive rooms the same name, except under special
  circumstances (e.g., rooms in a featureless maze).

- **Description** — a note saying what the room is, its key
  characteristics, and how it is connected to other rooms.  Keep it
  factual and succinct; this is for scenario mapping, not narration.

- **Start room?** — note the room where the player begins.
  There must be exactly one.

### 1C. Entities (Pass 1)

List out every distinct entity mentioned in the scenario, specifying:

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
  - `feature` — environmental object (walls, piles, handkerchiefs)
  - `item` — object that can be picked up

- **Description** — a note about what this entity is, its location at
  game start (room, container entity, or player inventory), and any
  narratively important details.  Keep it factual and succinct.  We
  will fill in mechanical details later (§1G).  If the entity is a
  feature visible from multiple rooms, note which rooms it spans.

### 1D. Global Flags

Make a list of global flags: boolean conditions tracking elements of
world state not tied to any specific room or entity.  In particular,
global flags should be assigned for:

- each major secret or piece of information the player can learn
  during the adventure ("the vizier is a lich", "password is foo").

- any plot-relevant or narrative event affecting many entities
  simultaneously ("the revolt has started", "night has fallen").

For each flag, specify:

- **Flag Name** — a globally-unique ID.
- **Description** — an explanation of the flag condition.
- **Initial Value** — the value at game start.

### 1E. Mechanics

Now list the mechanics — bundles of module-level (global) rules that
are not tied to a specific room or entity.  (Room- and entity-scoped
effects are covered later.)  There are two types:

1. **Game-over condition** — a `win` or `lose` trigger for the game.
   Every adventure should have at least one win condition; many also
   have loss conditions (death, time runs out, etc.).

   Example: player wins on reaching exit with artifact in inventory.

2. **Mechanic** — a named bundle of rules that can contain reactions,
   encounter rules, or both.  These reactions fire on game events
   regardless of which room the player is in.  Encounter rules set
   conditional outcomes (death, flee, stat check, combat).

   Example: dropping from one room to another, and taking fall damage.

   Example: a life ward fires if HP drops to ≤ 3.

   Example: a chained-encounter orchestrator watches a flag set by a
   first encounter, and triggers a second.

For each mechanic, specify:

- **Mechanic ID** — assign a globally-unique ID.
- **Kind** — either game-over condition or mechanic.
- **Description** — how the mechanic works, its trigger, and its
  effects (e.g., damage dealt, flags set).  Must give enough info to
  write the JSON later.  Can reference flag IDs (§1D), entity tags
  (§1G), and room/entity state IDs.

#### When to use a mechanic vs. a room/entity reaction

| Situation | Use |
|---|---|
| Trigger should fire regardless of player location | Mechanic with reactions (adventure-wide event watcher) |
| An encounter can be triggered from >1 room or entity | Mechanic with rules (referenced by `trigger_encounter`) |
| A condition means the player wins or loses | Game-over condition mechanic |
| A trigger fires only when the player is in a specific room | Room reaction (§1F) |
| A trigger fires only near a specific entity | Entity reaction (§1G) |

### 1F. Rooms (Pass 2)

Revisit the room list, and add the following info to each room:

- **Exits** — every way out.  For each, assign a room-unique exit ID,
  give a brief description (e.g., "through the north doorway"), and
  specify the destination room ID (§1B).
  
  Optionally, describe (i) a set of traversal conditions (stat check
  or other condition to traverse the exit), and/or (ii) conditions
  under which the exit is hidden (e.g., a secret door revealed only
  when a lever is pulled).

- **Entities present** — list the ID of each entity in the room at
  start (from §1C), including hidden ones (e.g., a lurking thief).

- **Special interactions** — assign a room-unique ID to any special
  interaction the player can have with the *room* (not an entity inside
  the room): e.g., shouting out a magic command word.
  
  DO NOT define interactions similar to these generic player actions:
  `move` (traversing rooms), `examine` (cursory or in-depth study), or
  `transfer` (moving items to/from a container or location).

- **Reactions** — describe any consequential event-driven reaction
  tied to the *room* (not an entity in the room).  Each reaction can
  occur only if the player is in the room.
  
  Examples:
  - combat triggered when the player enters
  - force-field blocks an exit traversal

  Assign each reaction a globally-unique reaction ID.  Then, describe
  (i) the trigger event: a special interaction, a standard player
  action, a global flag set/cleared, a dialogue event, etc.; (ii) any
  additional stat checks or other gating for the reaction to trigger;
  and (iii) the consequences.  These descriptions should be in plain
  text, but give enough info to form a JSON object later.

- **State Fields** — assign a room-unique ID for each mutable property
  of the room, and specify the initial value (boolean, number, or
  string).  Don't invent these nilly-willy; focus on properties needed
  for gameplay or narration: e.g., `filled_with_poison_gas`,
  `time_of_day` (if the scenario progresses time).

- **On-Examine Effects** — describe any effects triggered by the
  player examining the room (the room itself, not an entity in it),
  possibly gated by a condition or stat check.  Example: viewing a
  dusty storeroom, and deducing that nobody has come through in years
  (a plot point).  Can be gated by a stack check or other condition.

When describing events/reactions, special interactions, or state
fields, you can reference flags defined in §1D.  If you overlooked a
flag that you now need, update that list.  You can also reference
entity tags or IDs for room/entity state fields (whether already
defined, or to be defined later).

### 1G. Entities (Pass 2)

Revisit the entity list, and add the following to each entity:

- **Tags** — any semantic features relevant to gameplay.  Tags are
  defined at your discretion based on adventure requirements (e.g.,
  items with `heavy` tag can trigger a pressure plate).  Do not define
  game-irrelevant tags.

- **Equippable?** — if this entity is an item that can be equipped
  (weapon, armor, shield, ring, etc.), write a textual description of
  how it is worn or wielded, and any special properties the scenario
  provided (damage expression, stat bonuses, AC bonus, restrictions
  such as "two-handed" or "incompatible with shields").  Text only; do
  not structure as JSON.

- **Contained Entities** — if this entity contains other entities
  (e.g., a drawer holding a key), list the entity IDs inside.  Use the
  descriptions in §1C as a guide.

- **Special interactions** — for every special interaction the player
  can have with the entity (e.g., pulling a lever), assign a
  entity-unique interaction ID.  Include the `attack` interaction if
  the entity can be attacked.
  
  DO NOT define interactions similar to the following generic player
  actions: `examine` (cursory or in-depth study), `talk` (conversing
  with NPC), or `transfer` (moving items to/from).

- **State fields** — list each scenario-relevant mutable property the
  entity has, and its initial value (boolean, number, or string).
  
  For NPCs, state fields must include `alive` (boolean), and can also
  include `fled` (boolean, if the NPC can flee), `attitude` (number),
  `hidden` (boolean), `following` (boolean, for NPC companions),
  `current_hp` (number, required if the NPC has a `combat` block), and
  custom fields.  For non-NPC entities, state fields can be `hidden`
  (boolean), or custom (e.g., `opened`, `locked`, `lit`).

  The boolean state field `hidden` must be set if the entity is
  concealed from the player, either at game start or subsequently.

  For each custom field, note down its meaning.

- **Reactions** — describe any consequential event-driven reaction
  tied to the entity.  Each reaction can occur only if the entity is
  in the current room (and, for an NPC, alive and active).

  Examples:
  - picking up an item fires a magic effect
  - NPC attitude going too low trigers combat
  - exiting dialogue alters an NPC's state (e.g., it dies)
  
  Assign each reaction a globally-unique reaction ID.  Then, describe
  (i) the trigger event: a special interaction, a standard player
  action, a global flag set/cleared, a dialogue event, etc.; (ii) any
  additional stat checks or other gating for the reaction to trigger;
  and (iii) the consequences.

- **On-Examine Effects** — describe any effects triggered by the
  player examining the entity, possibly gated by a condition or stat
  check.  Important: this field belongs on the thing being examined,
  *not* the room containing it.  E.g., when the scenario says "upon
  examining the statue, the player notices...", the on_examine event
  belongs on the statue entity.

For items, also note:

- **Take Check** (optional) — conditions or checks that must be passed
  for the player to take the item.

For NPCs, also add descriptions for the following:

- **Combat Stats** — if the NPC is combat-capable and the scenario
  provides stat block details (HP, AC, attack bonus, damage dice,
  initiative modifier, flee DC, etc.), write them down verbatim.  Also
  note any special on-hit effects (e.g., poison save, paralysis,
  ongoing damage).  If the scenario doesn't give exact numbers, just
  record whatever info is provided.

- **Behavior** — if the NPC can fight, enumerate its encounter rules.
  Encounter rules specify the different ways a combat encounter might
  unfold, either when the player attacks the NPC, or vice versa (e.g.,
  via a reaction).  Each rule specifies a set of conditions (e.g.,
  "player has a weapon and NPC is hostile"), and the outcome (e.g.,
  "launch multi-turn combat").  The first encounter rule with matching
  conditions is dispatched.

  Common encounter rule outcomes are:
  - begin multi-round combat (NPC needs combat stats)
  - player auto-death
  - NPC flee or auto-death
  - stat check with success/failure branches (flee, auto-death)

  Also note any effects of NPC fleeing (e.g., setting a flag, or
  moving the NPC to another room).

  You may omit the behavior specification to accept the default rule:
  if the NPC has combat stats, begin turn-based multi-round combat;
  otherwise, the NPC dies.

- **Dialogue Paths** — for dialogue, if the NPC talks.
  Assign an NPC-unique ID for each special line of conversation the
  player can engage the NPC with.  Must have plot/gameplay relevance.
  
  Examples: bribing a guard to pass a gate, or convincing a prince
  that his vizier is evil.
  
  Describe (i) the conditions for the dialogue path to be available,
  (ii) any gating (e.g., stat check), and how the NPC reacts
  (non-verbatim) if successful/unsuccessful, and (iii) the effects of
  success/failure.  Dialogue paths are often triggering events for
  mechanics (§1E) or reactions (see above).

- **Will-Reveal Topics** — for dialogue, if the NPC talks.
  Assign an NPC-unique ID for each significant conversational topic
  the NPC can conditionally divulge information on.  Unlike a dialogue
  path, such a topic usually has no immediate mechanical effect.

  Example: a guard may have a dialogue path `bribe_to_enter` (player
  pays to get past — a mechanic), and a will-reveal topic
  `recent_visitors` (reveals which visitors have come through — just
  useful info).
  
  Describe (i) the gating conditions for the NPC to reveal info on the
  topic, (ii) what the NPC conveys (non-verbatim), and (iii) the
  consequences if any.  Regarding consequences: best practice is to
  set a global flag (§1D) to track the player's knowledge (different
  NPCs giving similar info can set the same flag).  Will-reveal topics
  can also alter entity state fields, but cannot trigger reactions.

- **Knowledge** — for dialogue, if the NPC talks.
  A list of incidental, non-plot-relevant bits of knowledge possessed
  by the NPC, used by the GM to craft dialogue.  This serves to pin
  down details that you don't want the GM to ad-lib.

### 1H. Cleanup

Go through the lists you have constructed, and check that IDs are
consistent, every ID required by a mechanic is defined, etc.

For each game mechanic, check that you have assigned it to the right
host (global, room, or entity), and that it accurately captures the
spirit of what's written in the scenario.  Minor deviations are OK,
but should be noted and surfaced in the final task report.

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
- [ ] All IDs (rooms, entities, flags, mechanics, reactions, dialogue
      paths, topics) are in snake_case and appropriately disambiguated

#### Structural correctness

- [ ] Exactly one room is the start room (§1B)
- [ ] Exactly one entity has `type: "player"` (§1C)
- [ ] No non-NPC entity has dialogue or behavior plans (§1G)
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

#### Mechanics

- [ ] Stat checks identified and resolution system noted (or "no stats")
- [ ] Every global mechanic is correctly classified: game-over
      condition or mechanic with rules/reactions
- [ ] Event-driven reactions scoped correctly (room, entity, or global
      mechanic)

#### Exits

- [ ] Hidden exits have a planned flag-based reveal mechanism (companion
      interaction sets a flag, exit hide_conditions require that flag)
- [ ] One-way exits have a planned return path (or a narrative reason
      they are permanently one-way)

---

## Step 2: Build Entities

**Input:** Scenario Map from Step 1 + Corpus Schema
**Output:** Corpus metadata, global flags, and entities data

Read the corpus schema (`schema/corpus.md`).  You will now write the
corpus file (`adventures/MODULE-NAME/corpus.json`), starting with the
metadata and global flags, followed by the entities block.  The
Scenario Map (`adventures/MODULE-NAME/scenario-map.md`) should be your
primary source; only refer to the original scenario to look up missing
information.

### 2A. Metadata and Global Flags

Populate the `adventure` field using the information from the top of
the Scenario Map: id, title, credits (author, source, license),
introduction, and atmosphere (setting, tone).

Next, construct `flags_declared` from the list of Global Flags in the
Scenario Map.  This is just used for validation/debugging.

If, during subsequent JSON implementation of various game mechanics,
you find it necessary to add extra global flags, be sure to update
`flags_declared`.

### 2B. Entity Data

You must now construct a JSON definition for each entity listed in the
Scenario Map, following the corpus schema (§2 Entities).

Here are general tips for writing the JSON objects, followed by
specific tips for items (§2C), features (§2D), the player (§2E), and
NPCs (§2F).  NPCs are the most complicated.

#### Description

When generating each entity's `description`, do not just translate the
description field from the Scenario Map.  Take a holistic view, and
write a timeless, spoiler-free description of the entity.  This
description is provided to the GM whenever the entity is present; it
should be factual, and independent of the entity's state (e.g., dead
or alive).  You may inject small details to add flavor, without
contradicting the scenario.

Example: "A massive black spider, about the size of a large dog, with
eight glittering red eyes, sharp mandibles, and eight hairy legs".

Do not use excessively poetic language; the GM is responsible for
turning the description into atmospheric narration.

Avoid situational framing that can be invalidated during the game:
e.g., "It lurks in the shadows..." is no good if the creature can be
fought and killed.

#### State fields

When generating the entity's `state_fields`, refer to the state fields
planned out in the Scenario Map.  Specify the initial value, and add a
terse description – the GM uses this to infer what the field means.
Each field must be one of the supported types: `boolean`, `number`, or
`string`.

Example:

```json
"state_fields": {
  "alive": { "type": "boolean", "description": "Whether the spider is alive." },
  "fled": { "type": "boolean", "description": "Whether the spider has fled." },
  "attitude": { "type": "number", "description": "Attitude toward the player, -10 to 10." },
  "hidden": { "type": "boolean", "description": "Whether the entity is hidden from view." }
}
```

If an entity is initially concealed (a key in a drawer, a hiding
thief, etc.), it MUST have a `hidden` state field.  This field is
handled specially by the engine: when true, the entity is concealed
(even from the GM) to avoid leakage.

#### Entity reactions

The `reactions` field is used for event-driven entity behavior.  To
translate the Scenario Map's reaction description into JSON, refer to
the spec in [`events.md`](events.md).  Note: entity reactions only
trigger if the entity is in the current room, alive, and not-fled.

Reaction `result` objects support the same fields as interaction
results: `narrative`, `set_flag`, `set_entity_state`, `set_room_state`,
`alter_stat`, `adjust_attitude`, `add_item`, `remove_item`, `reveals`,
`chain_check`, and `player_damage`.  Use whichever best fits.

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

The On-Examine Effects stated in the Scenario Map should be translated
into `on_examine` effects.

If the scenario is ambiguous about whether the `on_examine` effect
triggers on an ordinary or rigorous examination, use your judgment: an
ordinary examination suffices if the discovery is made just by
looking, but a rigorous examination is needed if it involves a
physical search.  Note how you resolved the ambiguity in your report.

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

Note: **when does a hidden entity become visible?** If the revealing
result includes `set_entity_state: { "<entity>": { "hidden": false } }`
directly, the entity is visible to the narrator in the same turn. If
you use a separate reaction on `flag.set`, the reveal is deferred to
the next turn's briefing.  The direct approach is usually preferred
for dramatic effect, unless otherwise indicated by the scenario.

### 2C. Item entities

For every item entity, `name` is required and should be a noun/phrase
referring unambiguously, module-wide, to the item.  It is used for
player commands, inventory, etc.  If not a proper name, use lower
case.  Can use adjectives to disambiguate (e.g., "ornate sword"), or,
as a last resort, numbers (e.g. "rusty sword 1").

The semantic Tags listed in the Scenario Map go into the `tags` field.

For equippable items, set up an `equip_block` field based on the
textual description in the Scenario Map, following the corpus schema.
If the scenario provides incomplete information, use your best
judgment, and surface the issue in your task report.  Note that
`equip_block.equip_tags` is *not* the same as the semantic tags: the
former drive the equipment system (what can be equipped, damage
expressions, AC, etc.).

If a mechanic or reaction is used to gate the player picking up the
item (e.g., STR check to pull a sword from a stone), use `take_check`
on the item entity.  The engine resolves that check when the player
tries a `transfer` action to take the item.  For a one-time success gate
(pass the check once, then the item is picked up freely thereafter),
use `take_check.gating` with a flag that `success` sets:

```json
"take_check": {
  "gating": { "require": "flag:sword_claimed == false" },
  "check": { "type": "stat_check", "stat": "STR", "dc": 17, "repeatable": true },
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
`check.repeatable` to `false` instead of using `gating`.

### 2D. Feature entities

For every feature entity, `name` should be in lower case if not a
proper name.  It only needs to be unambiguous at the level of the
room(s) the feature occurs in: e.g., two different rooms can have
features named `fountain`, with different entity IDs.

For features spanning multiple rooms, use `spans_rooms` to list all
rooms where the feature is visible.  The entity ID should be listed in
`entities_present` for each of those rooms.

#### Containers

A common pattern: a `feature` entity (e.g., a chest, a cabinet)
contains other entities (usually items) that start concealed.  The
engine provides built-in container mechanics: when a feature entity
has `tags: ["container"]` and declares `open` in `state_fields`, the
engine automatically hides its `contained_entities` and `soft_items`
when `open` is `false`, and surfaces them when `open` is `true`.

To model a closed-by-default container, the author only needs:

1. Set `tags: ["container"]` on the feature entity.
2. Declare `open` in `state_fields`.
3. Initialize `open: false` in `hard_state.entity_states`.
4. List the starting contents in `contained_entities` (and optional
   loose items in `soft_items`).
5. Add an interaction that sets `open: true`, with a condition so it
   only works while the container is closed.

Example — a chest with a hidden gem:

```json
"chest": {
  "type": "feature",
  "description": "A decrepit wooden chest, its surface covered in dust.",
  "tags": ["container"],
  "state_fields": {
    "open": { "type": "boolean", "description": "Whether the chest is open." }
  },
  "contained_entities": ["glowing_gem"],
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
    }
  ]
}
```

The engine automatically hides the chest's contents while `open` is
`false`, and surfaces them when `open` becomes `true`.  Any individual
`hidden` state on a contained entity is still respected — so items can
be individually concealed (by darkness, burial, magic, etc.) even
inside an open container.

Soft items declared directly on a closed container entity are treated
as inside it and are also unavailable until opened.

Containers without the `open` field in `state_fields` (even if tagged
`"container"`) are treated as default-open — their contents are always
visible and accessible (e.g., an open shelf or a corpse).

Open/close semantics without a container: doors, windows, and other
non-container entities may still use `open` as a state field without
the `container` tag.  The engine only applies container gating when
*both* the tag and the state field are present.

### 2E. Player entity

The player's `description` should be a general description of the
player character (from their perspective, used when examining
themself).  If no information is provided by the scenario, write up
something vague or nondescript.

The player entity can have standard `state_fields` like `alive` (if
death is possible).  Any state field declared here must also be
initialized in the hard state file (`entity_states.player`) later.  No
`dialogue_guidelines`, `behavior`, `interactions`, or `on_examine`.
The player usually starts with an empty `equipped` list.

### 2F. NPC entities

#### `follower_blacklist`

If an NPC can become a follower (via `state_fields.following`), and
the scenario says they refuse to enter certain rooms, add a
`follower_blacklist` field listing room IDs they won't enter:

```json
"korbar": {
  "type": "npc",
  "follower_blacklist": ["secret_compartment"]
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
`state_fields` and initialize it in hard state (Step 5).  The combat
engine will fall back to `combat.hp` if `current_hp` is absent, but
the validator requires the field to be present.

If an NPC can engage in a combat encounter with the player (by either
side attacking), such encounters are typically resolved by either
single-turn resolution (e.g., one-shot kills), or multi-round combat.
Dispatch occurs via `behavior.encounter_rules`; the first matching
rule takes effect.  Construct these encounter rules from the NPC's
Behavior description in the Scenario Map, or accept the default rule
(start combat if NPC has a `combat` block, NPC dies otherwise).

If the Scenario Map noted `on_flee` behavior for the NPC, encode it in
`behavior.on_flee` with any flags or entity state changes it should
apply and a short narrative effect description.

Here is an example of a mechanical (one-turn) encounter:

```json
"encounter_rules": [
  {
    "condition": { "require": "tag:weapon" },
    "outcome": "stat_check",
    "check": { "type": "stat_check", "stat": "STR", "dc": 10, "repeatable": true },
    "success": {
      "outcome": "flee",
      "narrative": "You land a solid blow. The goblin hisses and flees.",
      "set_flag": { "goblin_fled": true }
    },
    "failure": {
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

#### NPC dialogue

For every conversational NPC, write a `dialogue_guidelines` block.
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
    "condition": { "require": "attitude:fairy >= 0" },
    "check": { "type": "stat_check", "stat": "CHA", "dc": 12, "repeatable": true },
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
    "conditions": ["attitude:korbar >= 1"],
    "set_flag": { "bag_of_holding_learned": true }
  },
  "secret_compartment": {
      "description": "Korbar points out a handkerchief in the nearby pile, and says it hides a flap leading to a secret compartment with a key.",
    "conditions": ["attitude:korbar >= 3"],
    "set_flag": { "handkerchief_revealed": true }
  }
}
```

### 2G. Soft Items

> TBD: instructions to generate a list of soft items for
> container-type features, and NPCs...


---

### Step 2 validation checklist

- [ ] Every item entity has a non-empty `name` (display name; required by the engine)
- [ ] State fields for `alive` are `true` for creatures that start alive
- [ ] Every NPC with a `combat` block has `current_hp` in `state_fields`
- [ ] Every NPC with `dialogue_guidelines` has `attitude` in `state_fields`
- [ ] Every NPC with `dialogue_guidelines` has `attitude_limits` declared
- [ ] Every `will_reveal` entry uses valid condition syntax
- [ ] Every `set_flag` in `will_reveal` sets a value matching the flag's
      type (always boolean)
- [ ] Every `set_entity_state` in `will_reveal` sets a field declared in the
      target entity's `state_fields`
- [ ] Entities that span multiple rooms have `spans_rooms` and appear in
      each room's `entities_present` (cross-check with Step 3 once rooms exist)
- [ ] Entity `reactions` use valid event types (see [`events.md`](events.md))
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

### 3B. Entities present

In `entities_present`, list the IDs for all entities **directly**
present in the room at game start.  **This includes hidden entities**.

Exclude entities contained in other entities: e.g., if a key is inside
a box in the room, the key should NOT be in `entities_present`.

### 3C. Exits

The `exits` field should list ALL possible exits a room can have over
the course of gameplay.

To make an exit hidden until certain conditions are met, use the
`hide_conditions` field.  List one or more condition expressions; the
exit is hidden from the player until ALL conditions evaluate to true.
Omit the field (or set to `null`) for an exit that is always visible.

Typically, `hide_conditions` checks a global flag, and there is a
companion effect (a mechanic, reaction, etc.) that sets this flag to
reveal the exit.  Example:

```json
"hide_conditions": [{ "require": "flag:curtain_opened == true" }]
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

Exits do not have a `reactions` field. To react to traversal events
(`traversal.succeeded`, `traversal.attempted`, etc.), place reactions
on the **containing room's** `reactions` array. Filter by exit ID
using an `event:` condition:

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

### 3E. On-enter events

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

### 3F. Room reactions

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
section "Step 6". The correct location is Step 3H.

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
it on the **room** (see Common Pitfall #23 for details).

#### Multiple on_examine events on one target

An entity or room can have multiple `on_examine` events. Each is
evaluated independently in definition order, and each matching event's
narrative is appended.  Use this when a successful INT check chains
into a second lore check (see the bag_of_holding_from_rubbish event in
the Bag of Holding corpus for an example of gated sequential
deductions).

### 3H. Soft items

Plausible generic items the player might pick up. These should be
environmentally appropriate items with no plot significance.

**Test:** Will a condition, mechanic, or specific interaction reference this
thing by name? If yes, it should be a proper entity, not a soft item.


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
- [ ] Every `set_flag` references a flag name from Step 1D
- [ ] Every condition object follows the condition object format — no bare
  condition strings outside `any`/`all` arrays
- [ ] Every interaction with a check also has `success` and optionally
  `failure`
- [ ] Every interaction without a check has `result`
- [ ] Every `on_examine` event with a `check` has `success`
- [ ] Every `on_examine` event without a `check` has `result`
- [ ] Interactions that should accept a `using` item have a
  `parameter_signature` defining accepted types
- [ ] If interactions reference `using_results`, each key is a valid entity
  ID or `"*"` wildcard
- [ ] Room `reactions` use valid event types (see [`events.md`](events.md))
- [ ] Room `reactions` with `event:` conditions reference valid context keys
  for their event type (see [`events.md`](events.md))

---

## Step 4: Build Mechanics

**Input:** Mechanic list from Step 1 + entities/rooms from Steps 2-3.
**Output:** The full `"mechanics"` block for `corpus.json`.

Two structural kinds of mechanics live here: game-over conditions (win/lose),
and mechanics containing encounter rules and/or reactions (adventure-wide
state-based triggers).  A mechanic with only reactions is simply a mechanic
without encounter rules, not a distinct type.

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
| `outcome` | str | `"death"`, `"flee"`, `"roll"`, `"stat_check"`, or `"combat"` |
| `condition` | condition object | Gate for the rule |
| `check` | StatCheck | The stat check to resolve (for `stat_check` outcome) |
| `threshold` | float 0-1 | Roll-under threshold (for `roll` outcome) |
| `narrative` | str | Prose shown when the rule fires |
| `set_flag` | dict[str, bool] | Flags to set |
| `alter_stat` | dict[str, StatModifier] | Fixed stat modifications (delta or set) |
| `player_damage` | str | Dice expression rolled as HP damage (e.g. `"3d6"`, `"2d4+1"`) |
| `success` | BranchOutcome | Branch when check/roll succeeds |
| `failure` | BranchOutcome | Branch when check/roll fails |

> **When `outcome` is `"combat"`:** The engine starts multi-round combat.
> The NPC must have a `combat` block with HP, AC, attack bonus, initiative,
> etc. — see §2B and [`doc/combat.md`](../doc/combat.md).  Without it, the
> engine will error.

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

### 4C. Mechanics with reactions only

For adventure-wide state-based triggers that aren't tied to a specific room or
entity, create a mechanic that carries a `reactions` array without `rules` or a
`type`.  This is not a distinct structural type — it is simply a mechanic where
`rules` is absent. See [`events.md`](events.md) for the full list of event types
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

- [ ] Every mechanic referenced by a `trigger_encounter` exists in the block
- [ ] Every `trigger_id` is unique across all mechanics
- [ ] Game-over mechanics have `condition`, `narrative`, and `trigger_id`
- [ ] Encounter mechanics have `rules` (not `condition`/`type`/`trigger_id`)
- [ ] Mechanics with `reactions` but no `type` or `rules` are valid
      (adventure-wide event watchers)
- [ ] If stats block present: only stats actually used are defined
- [ ] If stats block absent: no stat_check interactions or stat: conditions
      exist in rooms/entities
- [ ] Mechanic `reactions` use valid event types (see
      [`events.md`](events.md)) and effect fields

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
    "equipped": [],
    "stats": { /* only if corpus has a stats block */ },
    "level": 1,
    "current_hp": 10,
    "max_hp": 10,
    "ac": 10,
    "proficiency_bonus": 2,
    "save_proficiencies": []
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

3. **`player.equipped`** — usually `[]` at start.  Starting equipment is rare
   and should be declared explicitly.

4. **`player.stats`** — only if the corpus has a `stats` block. Under 5e,
   typical values range 3-18 with 10 as average. If the scenario doesn't specify
   stat values, use 10 across all stats declared in the corpus definitions.

5. **Player combat fields** — if the scenario supplies them, set `level`,
   `current_hp`, `max_hp`, `ac`, `proficiency_bonus`, and `save_proficiencies`.
   If any are absent, choose reasonable defaults and note the omission.

6. **`flags`** — enumerate every flag name used anywhere:
   - In condition strings (`flag:...`)
   - In `set_flag` results
    - In encounter `set_flag`
   - In `on_examine` events and reaction `result.set_flag` effects
   Set each to its initial value (almost always `false`). This is a flat dict;
   all flag values should be booleans.

7. **`room_states`** — for every room in the corpus, add `{ "visited": false }`.
   If a room has additional state fields (none currently defined), add those
   with initial values.

8. **`entity_states`** — for every entity that declared `state_fields` in the
   corpus, add an entry with initial values for every declared field:
   - Boolean fields: `false` (or `true` for `alive` on things that start alive)
   - Number fields: `0` (or the NPC's `attitude_limits.initial` for attitude,
     or the NPC's `combat.hp` for `current_hp` on combat-capable NPCs)
   - String fields: `""`
   **Do not skip any entity that has state_fields.** Every field declared in
   the entity's `state_fields` must have a value here.

9. **`turn_count`** — always `0`.

8. **`game_over`** — always `null`.

---

### Step 5 validation checklist

- [ ] Every room in corpus has a `room_states` entry with `visited: false`
- [ ] Every entity with `state_fields` in corpus has an `entity_states`
      entry with every field initialised
- [ ] Every entity with `hidden` in `state_fields` has `hidden` initialised
      in `entity_states`
- [ ] Every flag name used anywhere in the corpus appears in `flags`
- [ ] `player.location` references the room with `is_start_room: true`
- [ ] No entity in `player.inventory` also appears in a room's
      `entities_present` at start
- [ ] If corpus has `stats`: `player.stats` is present, and every key matches
      a key in `stats.definitions`
- [ ] If corpus has no `stats`: `player.stats` is absent
- [ ] Every NPC with `dialogue_guidelines` has `attitude` set to the value
      from the NPC's `attitude_limits.initial` (default 0) in `entity_states`
- [ ] Every NPC with `dialogue_guidelines` has `attitude` in both
      `state_fields` and `entity_states`
- [ ] Every NPC with a `combat` block has `current_hp` in both
      `state_fields` and `entity_states`, initialized to `combat.hp`
- [ ] Every state field declared for the player entity has a matching entry
      in `entity_states.player`
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
- [ ] Every NPC with a `combat` block has `current_hp` in both `state_fields`
  and `entity_states`, initialized to `combat.hp`
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

All condition fields use **condition objects** — never bare strings —
except for `will_reveal.conditions`, which is a list of bare condition
strings.  Condition objects enable compound AND/OR logic with nesting.

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
- `will_reveal.conditions` is a list of bare condition strings, not condition
  objects (e.g., `["attitude:korbar >= 2", "flag:spider_fled == true"]`).

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

4. **Hidden exits without reveal conditions**: An exit with non-empty
   `hide_conditions` needs a companion interaction that sets a flag;
   the conditions should require that flag. Otherwise the exit is permanently
   invisible.

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
    interaction conditions, game-over mechanic conditions, or exit hide_conditions
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
