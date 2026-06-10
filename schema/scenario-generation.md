# Scenario-to-JSON Generation Instructions

This document is a prompt/checklist for an LLM to convert a natural-language
adventure scenario (e.g., `scenario.md`) into the three structured JSON files
the engine requires:

- **`corpus.json`** — read-only adventure content (rooms, entities, mechanics)
- **`hard-state.json`** — initial authoritative runtime state
- **`soft-state.json`** — initial narrative-oriented mutable state

The schemas for these files are defined in:
- [`corpus.md`](corpus.md) for the Module Corpus
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
     │  Output: entity_lists, room_lists, mechanics_list, flag_list
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

At the end of every step, run the step's validation checklist. If any check
fails, **stop and fix before proceeding**.

---

## Step 1: Parse & Extract

**Objective:** Read the scenario Markdown and produce a structured inventory of
everything that needs to be modelled.

Read the entire scenario and extract the following into a clean list:

### 1A. Adventure metadata

| Item | Source |
|------|--------|
| ID | Short snake_case identifier (e.g., `bag-of-holding`) — optional but recommended |
| Title | First heading or preamble |
| Author / credits | Preamble footer or credits note |
| Introduction | Opening paragraph (verbatim) |
| Atmosphere | Synthesise from overall feel (1-2 sentences, no spoilers) |

### 1B. Room list

For every room described, note:

- **Room name** (as written in the heading)
- **Prose description** — the full text describing what the player sees
- **Entities present** — every entity mentioned as being in this room at start
- **Soft items** — generic plausible items in the room (rocks, corks, coins)
- **Exits** — every way out, with target room and any conditions/gating described
- **Special interactions** — things the player can do in this room that aren't
  generic (e.g., search the rubbish pile, force through webbing)
- **On-enter events** — things that happen when the player first arrives
- **On-examine events** — stat checks or discoveries gated on examining
- **Start room** — exactly one room where the player begins

Avoid creating extra rooms not in the scenario. Every room in the output must
correspond to a distinct location described in the scenario.

### 1C. Entity list

For every distinct entity mentioned, note:

- **Name** — as used in the scenario
- **Type** — classify as:
  - `player` — the player character (exactly one)
  - `npc` — characters that can talk or fight
  - `feature` — environmental objects (walls, piles, handkerchiefs)
  - `item` — objects that can be picked up
  - `trap` — hazards with mechanical consequences
- **Description** — canonical prose for examine action
- **Dialogue** — does it talk? Note personality, knows, attitude gating
- **Behavior** — does it fight? Note triggers, combat rules
- **Tags** — e.g., `weapon`, `key_item`, `draggable`
- **State fields** — what mutable properties does it have? (alive, fled, opened, etc.)
- **Interactions** — anything special the player can do with it
- **On-examine events** — stat checks or discoveries gated on examining it

Also note:
- Which entities are in which rooms at game start
- Which entities span multiple rooms (visible from several rooms)
- Which entities the player starts with in inventory (usually none)

### 1D. Mechanic list

For every mechanic described (not tied to a specific entity), note:

- **Encounters** — combat or hazard events (spider attack, fall damage)
- **Game-over conditions** — win/lose triggers and their conditions
- **Dropping rules** — what happens when falling from various heights
- **Item interaction rules** — carrying heavy items, key insertion, etc.

### 1E. Flag list

Enumerate every flag mentioned or implied. A flag is any boolean state condition
that changes during play. Examples: `spider_fled`, `injured`, `handkerchief_moved`,
`padlock_unlocked`, `player_escaped`.

Note initial values (almost always `false`).

Add a `flags_declared` field as a top-level corpus array (alongside
`adventure`, `rooms`, `entities`, `mechanics`) listing all flag names
used in conditions, set_flag results, and encounters. This is a
convenience field for validation and debugging. Generate it during
cross-validation (after all corpus sections are complete).

### 1F. Stat system (if applicable)

If the scenario uses stat checks (STR, DEX, INT, etc.), note:
- Which stats are used
- The resolution system (typically d20)
- Whether the scenario specifies player stat values, or defaults (e.g., all 10s)

If the scenario has no stat checks, note that no stats block is needed.

---

### Step 1 validation checklist

- [ ] Every room in the scenario is captured in the room list
- [ ] Every entity is classified with a type
- [ ] Every conditional gate is reflected as a flag
- [ ] Stat checks identified and resolution system noted (or "no stats")
- [ ] Exactly one start room identified
- [ ] No rooms or entities invented that aren't in the scenario

---

## Step 2: Build Entities

**Input:** Entity list from Step 1.
**Output:** The full `"entities"` block for `corpus.json`.

For each entity in the list from Step 1, produce a complete entity definition
following the schema in [`corpus.md`](corpus.md) (§2 Entities).

### 2A. State fields

Every mutable property of an entity must be declared in `state_fields`. For
every entity, think about what changes during play:

- NPCs: `alive` (boolean), `fled` (boolean), `attitude` (number, always
  required for NPCs), `told_secret` (boolean), `following` (boolean)
- Features: `opened` (boolean), `revealed` (boolean), `activated` (boolean)
- Items: none usually (items just exist in inventory)
- Traps: `triggered` (boolean), `activated` (boolean)

```json
"state_fields": {
  "alive": { "type": "boolean", "description": "Whether the spider is alive." },
  "fled": { "type": "boolean", "description": "Whether the spider has fled." },
  "attitude": { "type": "number", "description": "Attitude toward the player, -10 to 10." }
}
```

### 2B. NPC dialogue guidelines

For every conversational NPC, produce a `dialogue_guidelines` block:

- **`personality`**: 2-4 sentences. Manner of speaking, emotional state, core
  motivation, fears. Extract from the scenario's NPC section.
- **`on_encounter`**: What happens on first meeting. If the scenario says
  "the fly groans when the player enters", encode that here.
- **`can` / `cannot`**: Hard constraints from the scenario. These are the
  "firewall" against LLM confabulation. Be specific.
  - Example: `["will warn about the spider", "expresses satisfaction if spider is dead"]`
  - Example: `["will never agree to fight the spider", "will not follow into the secret compartment"]`
- **`knows`**: All facts the NPC possesses. Every piece of information the NPC
  can potentially share, even if gated.
- **`attitude_limits`**: Integer bounds from the scenario.
  - `min` / `max`: The range. A hostile spider never goes positive: `-5` to `0`.
    A friendly dwarf can go from `-10` to `10`.
  - `step_per_turn`: Maximum attitude change per turn. Default `1` unless the
    scenario says otherwise.
  - `initial`: Starting attitude. Default `0`.
- **`will_reveal`**: Gated topics. See below.

**The `will_reveal` topics:**

For every secret or piece of information the NPC can reveal, create a topic.
Each topic's `conditions` array must include every gate mentioned in the
scenario. All conditions in the array are ANDed together.

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
are applied by the engine when the LLM Call tags the topic as revealed in dialogue.

**`on_dialogue_exit`:**

If the NPC undergoes a state change when dialogue ends (the player walks away,
uses `ends_dialogue`, or a stall is detected), add an `on_dialogue_exit` block.
Common uses: the NPC dies, flees, or changes attitude after conversation.
All fields are optional.

```json
"on_dialogue_exit": {
  "set_entity_state": { "stuck_fly": { "alive": false } },
  "set_flag": { "fly_warning_given": true },
  "narrative": "The fly's groaning ceases. Its tiny body goes still."
}
```

Engine behaviour: when dialogue mode exits (regardless of cause — player leaves,
ends_dialogue, or stall timeout), the engine applies these effects after the
`on_dialogue_exit.narrative` is passed as `triggered_narration` to LLM Call 2.

**Hostile NPC dialogue pattern:**

Some NPCs start hostile (negative attitude) but can be improved through
dialogue, unlocking mechanical benefits. Model this as:

- Set `attitude_limits.initial` to the starting negative value (e.g., `-2`)
- Set `attitude_limits.max` to the highest possible attitude (e.g., `0`)
- Set `step_per_turn` to limit single-turn attitude shifts (e.g., `1`)
- In `can`, list dialogue actions that improve attitude: `["can be flattered with CHA checks (DC 12)"]`
- Use `will_reveal` topics gated on attitude thresholds
- In `behavior`, use `encounter_rules` with conditions checking both flags
  and attitudes (e.g., combat only triggers if `attitude < 0`)

Example: a spider that starts at -2 attitude, can be flattered up to 0
(max), and at 0 can be persuaded to flee:

```json
"dialogue_guidelines": {
  "personality": "A giant spider, hungry and malicious. It speaks grudgingly.",
  "attitude_limits": { "min": -5, "max": 0, "step_per_turn": 1, "initial": -2 },
  "can": ["can be flattered to improve attitude", "will let player through if persuaded at attitude 0"],
  "cannot": ["will never make agreements", "will lie about letting the player through"],
  "will_reveal": {
    "spider_knowledge": {
      "description": "The spider knows of Korbar as prey it hasn't caught yet.",
      "conditions": ["attitude:spider >= -2"]
    }
  }
}
```

### 2C. NPC behavior (combat rules)

For every NPC that fights, produce a `behavior` block:

- **`triggers_on`**: What actions trigger combat. List exit IDs and/or
  interaction IDs. An empty array means combat is only triggered when the
  player directly attacks.
- **`encounter_rules`**: One rule per combat branch. Rules are evaluated
  top-to-bottom; the first matching condition fires.

When a combat scenario has multiple conditional branches (e.g., "if armed AND
STR check succeeds → spider dies" vs "if armed AND STR fails → spider strikes
back"), model each as a separate rule with its own `condition`:

```json
"encounter_rules": [
  {
    "condition": { "require": "tag:weapon" },
    "outcome": "stat_check",
    "check": { "type": "stat_check", "stat": "STR", "dc": 10 },
    "on_success": {
      "outcome": "flee",
      "narrative": "You land a solid blow. The spider hisses and flees.",
      "set_flags": { "spider_fled": true }
    },
    "on_failure": {
      "outcome": "stat_check",
      "check": { "type": "stat_check", "stat": "DEX", "dc": 10 },
      "on_success": {
        "outcome": "death",
        "narrative": "The spider strikes back! You dodge, barely."
      },
      "on_failure": {
        "outcome": "death",
        "narrative": "The spider's venom fills your veins. Everything goes dark."
      }
    }
  },
  {
    "condition": { "unless": "tag:weapon" },
    "outcome": "death",
    "narrative": "Bare-handed, you cannot fend off the spider's attack. Its venom overcomes you."
  }
]
```

Note: `outcome: "death"` always kills the player (game over). `outcome: "flee"`
removes the NPC. For non-lethal combat outcomes (e.g., NPC is knocked out but
doesn't die), use `outcome: "flee"` with appropriate `set_flags` and narrative,
since `flee` removes the NPC from play without killing the player.

### 2D. Item entities

For every item entity:

- Add relevant `tags`: `"weapon"` (if usable in combat), `"key_item"` (plot-significant)
- Set `draggable: true` if the item encumbers the player while carried
- Set `dragging_note` to a narrative description of the encumbrance
- Normally no `interactions` or `on_examine` unless the scenario specifies
  special interactions with the item

### 2E. Feature entities

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

### 2F. Player entity

Exactly one entity with `type: "player"`.

- `description`: a general description of the player character (from their
  perspective, used when examining oneself).
- `state_fields`: standard fields like `alive` if death is possible.
- No `dialogue_guidelines`, `behavior`, `interactions`, or `on_examine`.

---

### Step 2 validation checklist

- [ ] Exactly one entity has `type: "player"`
- [ ] Every NPC entity has `attitude` declared in `state_fields`
- [ ] Every NPC with dialogue has a `dialogue_guidelines` block
- [ ] Every NPC that fights has a `behavior` block
- [ ] Every NPC with both dialogue AND combat has both blocks
- [ ] `attitude_limits` on every NPC with `dialogue_guidelines`
- [ ] `on_dialogue_exit` present for NPCs that die, flee, or change state after dialogue
- [ ] Every `will_reveal` topic's `conditions` array uses valid condition strings
- [ ] Every `set_flag` in `will_reveal` references a flag from Step 1E
- [ ] Every `set_entity_state` in `will_reveal` references an entity that
  has that field in `state_fields`
- [ ] Item entities carry appropriate `tags` where the scenario implies them
- [ ] State fields for `alive` are `true` for creatures that start alive
- [ ] No entity has `dialogue_guidelines` or `behavior` unless `type: "npc"`
- [ ] Entities that span multiple rooms have `spans_rooms` and appear in each
  room's `entities_present`
- [ ] NPCs that refuse to enter certain rooms have `follower_blacklist`

---

## Step 3: Build Rooms

**Input:** Room list from Step 1 + entity definitions from Step 2.
**Output:** The full `"rooms"` block for `corpus.json`.

For each room from the room list, produce a complete room definition following
the schema in [`corpus.md`](corpus.md) (§1 Rooms).

### 3A. Room description

Write full second-person present-tense prose for `description`. It should be
sufficient for both room entry and re-examination. Include what the player
sees, hears, smells, and any notable features.

**Do not** include clues gated behind a rigorous search or NPC reveal — those
are returned by the engine as examine outcomes, not as the base description.

Surface-level impressions only. "You see a pile of rubbish" is fine. "You see
a giant iron key hidden beneath a handkerchief" is not — that should be an
on-examine event or revealed by dialogue.

### 3B. Entities present

List the entity IDs (from Step 2) that are physically in this room at game
start.

- Features spanning multiple rooms should appear in every room they span
- Hidden entities (e.g., a key in a secret compartment) are still listed in
  the room that contains them — the room access gating prevents the player
  from reaching them until revealed

**Hidden entity reveal pattern:**

Some entities are not initially visible to the player — the spider in the
webs, the handkerchief in the rubbish, etc. Currently, the engine does NOT
support filtering entities from `entities_visible` based on state fields.
All entities in `entities_present` are shown to the LLM regardless.

Until entity-level hiding is implemented in the engine, model hidden
entities with this workaround:

1. **List the entity in `entities_present`** as normal. The LLM will see
   it in the GMBriefing and must be instructed not to narrate it until
   the player discovers it.
2. **Add an `on_examine` event** on the room or a covering entity that
   gates the discovery on a stat check:

   ```json
   {
     "id": "notice_spider",
     "condition": { "require": "entity:spider.fled == false" },
     "check": {
       "type": "stat_check",
       "stat": "WIS",
       "dc": 12,
       "repeatable": true
     },
     "success": {
       "narrative": "You notice eight glittering eyes watching you from above.",
       "set_flag": { "spider_noticed": true }
     }
   }
   ```

3. **For the NPC's `behavior` trigger**, gate combat on the noticing flag:

   ```json
   "triggers_on": ["exit_force_through_web"],
   "encounter_rules": [
     {
       "condition": { "require": "flag:spider_noticed == true" },
       ...
     }
   ]
   ```

4. **For the entity's `description`**, write a vague description that
   doesn't spoil the discovery. The `on_examine` success narrative adds
   the dramatic reveal.

This approach relies on the LLM respecting the discovery gate in narration.
It is not enforcement — a disobedient LLM could narrate the spider before
the player notices it. A proper entity-level hidden/revealed mechanism
would need engine support.

### 3C. Soft items

Plausible generic items the player might pick up. These should be
environmentally appropriate items with no plot significance.

**Test:** Will a condition, mechanic, or specific interaction reference this
thing by name? If yes → it should be a proper entity, not a soft item.

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
- **`on_traverse`**: Effects applied on successful traversal (set_flag,
  narrative, trigger_encounter)
- **`traversal_check`**: **Optional.** A check that gates the *attempt*, not
  the *availability*. The exit is visible and the player can try, but may fail
  and stay in place. Use for patterns like "dragging the heavy key requires
  STR check to move between rooms".

**`on_traverse` effect fields:**

| Field | Description |
|-------|-------------|
| `set_flag` | Object of flags to set on traversal: `{ "<name>": true/false }` |
| `narrative` | Canonical prose for the traversal event, passed as `triggered_narration` to LLM Call 2 |
| `trigger_encounter` | Mechanic ID to trigger on traversal (e.g., `"fall_damage"`) |
| `skip_if` | Condition object — if met, the traverse effect (narrative, flag setting, etc.) is skipped |
| `narrative_skip` | Alternative prose when the effect is skipped via `skip_if` |

**`traversal_check` fields:**

| Field | Description |
|-------|-------------|
| `check` | The roll or stat_check to resolve |
| `condition` | Optional condition — the check only fires if this is met. When absent (or condition not met), traversal proceeds without a check |
| `skip_check_if` | Optional condition — if met, the check is skipped entirely (bypasses `condition`) |
| `failure_narrative` | Prose shown when the check fails |

**When to use `traversal_check` vs `conditions`:**

| Pattern | Use |
|---------|-----|
| "Can't leave until spider is resolved" | `conditions: { "require": "flag:spider_fled == true" }` |
| "The key is heavy — STR check to move between rooms" | `traversal_check: { check: { type: "stat_check", ... } }` |
| "Secret compartment is hidden until noticed" | `hidden: true` + companion interaction that sets flag + `conditions: [ { "require": "flag:... == true" } ]` |
| "Dropping down is one-way" | `one_way: true` (and a separate exit to go back up) |

**Clearable obstacle pattern (one-time obstacle):**

When the player must overcome an obstacle to pass (e.g., force through a
web), and once cleared the obstacle is no longer an impediment:

1. Add a `traversal_check` on the blocked exit with the initial check
2. On check success, set a flag via the exit's `on_traverse.set_flag`
3. Use `skip_check_if` on the `traversal_check` to bypass once the flag is set

```json
{
  "exit_force_through_web": {
    "target_room": "axe_handle_lower",
    "traversal_check": {
      "condition": { "unless": "flag:webs_cleared == true" },
      "check": { "type": "stat_check", "stat": "STR", "dc": 14, "repeatable": true },
      "skip_check_if": { "require": "flag:webs_cleared == true" },
      "failure_narrative": "You strain against the sticky webs but can't break through."
    },
    "on_traverse": {
      "narrative": "You burst through the webs, clearing a path.",
      "set_flag": { "webs_cleared": true },
      "trigger_encounter": "spider_attack"
    }
  }
}
```

**Global traversal check (item weight):**

If carrying a certain item makes every exit harder (e.g., a heavy key),
the same `traversal_check` must be duplicated on **every exit** the player
can use while carrying it. There is currently no mechanism to apply a
traversal check globally — per-exit duplication is the required pattern.

```json
"exit_climb_down_handle": {
  "target_room": "axe_handle_upper",
  "traversal_check": {
    "condition": { "require": "inventory:rusty_key" },
    "check": { "type": "stat_check", "stat": "STR", "dc": 13, "repeatable": true },
    "skip_check_if": { "require": "entity:korbar.following == true" },
    "failure_narrative": "The giant key is too heavy to haul up the handle."
  }
}
```

Apply this same block to every relevant exit. Use `skip_check_if` when an
NPC follower can bypass the weight requirement.

**Approach-specific traversal effects (different drop penalties):**

When the same action (dropping) has different consequences depending on
which room triggers it, use `on_traverse.set_stat` with different values
on each exit:

```json
// On the Axe Head drop exit:
"on_traverse": {
  "narrative": "You leap into the darkness and land hard among the rubbish below.",
  "set_stat": { "STR": -4, "DEX": -4, "CON": -4 }
}

// On the Axe Handle Upper drop exit:
"on_traverse": {
  "narrative": "You drop down and land heavily, spraining your ankle.",
  "set_stat": { "DEX": -2, "CON": -2 }
}

// On the Axe Handle Lower drop exit:
"on_traverse": {
  "narrative": "You drop down safely onto the rubbish pile below."
}
```

Each exit's `on_traverse` can set different stat deltas because each exit is
a distinct object. The engine applies `set_stat` as hard-state deltas when
the player traverses that exit.

**Multi-step escape action:**

For win conditions that require an explicit player action (e.g., "squirm
free through the rip"), create an exit that represents the escape action.
Target it to a virtual exit room (not a real room) or use an interaction
that sets the final flag:

```json
{
  "id": "exit_squirm_free",
  "direction": "Squirm free through the rip into freedom",
  "target_room": "free_at_last",
  "hidden": true,
  "conditions": [{ "require": "flag:padlock_unlocked == true" }],
  "on_traverse": {
    "narrative": "You squeeze through the rip and tumble out into the open air.",
    "set_flag": { "player_escaped": true }
  }
}
```

Then reference `flag:player_escaped` in the win condition's `condition`.
This ensures the player must explicitly choose the escape action, which
is distinct from the engine passively detecting a condition.

**Special case — exits that require an NPC to be present:**

If an exit's availability depends on whether an NPC is in the room (e.g.,
Korbar helping carry the key), use an `entity:` condition:

```json
"conditions": [{ "unless": "entity:korbar.following == true" }]
```

This means: "the exit has a traversal check unless Korbar is following."
Together with a separate exit for the "Korbar helps" case, or with
`traversal_check.skip_check_if`:

```json
"traversal_check": {
  "check": { "type": "stat_check", "stat": "STR", "dc": 13 },
  "skip_check_if": { "require": "entity:korbar.following == true" }
}
```

### 3E. Interactions (room-level)

Define interactions only for room-specific actions that aren't covered by
generic actions (attack, examine, move, talk, transfer).

Each interaction must have:
- **`id`**: snake_case, unique within the room
- **`label`**: short UI label
- **`description`**: what the player is attempting
- `check` + `success` + `failure`, **or** `result` (deterministic)

**Deterministic (no check):**
```json
{
  "id": "leave_secret_compartment",
  "label": "Leave",
  "description": "Squeeze back out of the secret compartment.",
  "result": { "narrative": "You squeeze back out to the Bag Floor." }
}
```

**Probabilistic (with check):**
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

**Using_results for item-specific overrides:**

When an interaction has different outcomes depending on what the player uses,
define a `using_results` map. This allows the same interaction to resolve
differently based on the `using` parameter of the `interact` action:

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

**Chain-check-to-game-over pattern:**

When a failed check triggers a follow-up check, and that failure leads to
a game-over, encode it as `chain_check` on the first check's failure result.
The chain check's failure sets a flag, and a `lose` mechanic watches for
that flag:

```json
{
  "id": "key_insertion",
  "label": "Push the key through the rip into the padlock",
  "description": "Insert the giant key into the padlock outside the Bag.",
  "check": {
    "type": "stat_check",
    "stat": "STR",
    "dc": 12,
    "repeatable": true
  },
  "success": {
    "narrative": "With a grunt, you push the key through the rip and into the padlock.",
    "set_flag": { "padlock_unlocked": true }
  },
  "failure": {
    "narrative": "You fumble. The heavy key slips!",
    "chain_check": {
      "check": {
        "type": "stat_check",
        "stat": "DEX",
        "dc": 8
      },
      "success": {
        "narrative": "You catch the key just in time."
      },
      "failure": {
        "narrative": "The key falls through the rip and disappears into the Astral Plane forever.",
        "set_flag": { "key_lost_to_astral": true }
      }
    }
  }
}
```

Then in Step 4B, create a `lose` mechanic that checks the flag:

```json
"key_dropped_through_rip": {
  "id": "key_dropped_through_rip",
  "type": "lose",
  "description": "Player drops the key through the rip.",
  "condition": { "require": "flag:key_lost_to_astral == true" },
  "narrative": "You are trapped forever inside the Bag of Holding.",
  "trigger_id": "key_lost"
}
```

**Escalating DC pattern (repeated interactions):**

When the same interaction can be repeated with increasing difficulty (e.g.,
Korbar's CHA check: DC 9, 12, 15), model it as multiple interaction entries
with mutually exclusive conditions:

```json
{
  "id": "cheer_korbar_1",
  "label": "Comfort Korbar",
  "description": "Try to cheer up the miserable dwarf.",
  "check": {
    "type": "stat_check",
    "stat": "CHA",
    "dc": 9,
    "repeatable": false
  },
  "success": {
    "narrative": "Korbar seems a little better.",
    "set_entity_state": { "korbar": { "attitude": 1 } }
  },
  "failure": {
    "narrative": "Korbar shrugs you off."
  }
}
```

Separate interactions are needed because the schema does not support dynamic
DC scaling. Use conditions on each entry to ensure only the appropriate one
is available. The engine tracks which interaction IDs have been attempted
(and their outcomes) via `checks_attempted` in soft state.

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

### 3G. On-examine events

For examine-gated stat checks or conditional discoveries:

**Note:** Earlier versions of this document mistakenly labelled this
section "Step 6". The correct location is Step 3G.

- `check`: The stat_check or roll that determines outcome
- `condition`: Controls when the event is available (e.g., only if spider is
  still alive)
- `rigorous_only`: `true` if the player must use `examine (rigorous)` to trigger

**Pattern for examine-gated stat checks:**
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

---

### Step 3 validation checklist

- [ ] Every room has a `name` and `description`
- [ ] Exactly one room has `is_start_room: true`
- [ ] Every exit `target_room` references a valid room ID
- [ ] Every exit ID is unique across all rooms
- [ ] Every entity in `entities_present` exists in the `entities` block
- [ ] Every `trigger_encounter` in an exit's `on_traverse` references a
  mechanic that will be created in Step 4
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

---

## Step 4: Build Mechanics

**Input:** Mechanic list from Step 1 + entities/rooms from Steps 2-3.
**Output:** The full `"mechanics"` block for `corpus.json`.

Two kinds of mechanics live here: encounters and game-over conditions.

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
      "check": { "type": "stat_check", "stat": "DEX", "dc": 8 },
      "on_success": {
        "narrative": "You drop down and land heavily, but survive."
      },
      "on_failure": {
        "outcome": "flee",
        "narrative": "You fall hard and injure yourself badly."
      }
    }
  ]
}
```

**Note:** Encounters evaluate `condition` against game state when triggered.
The `room:<id>.is_current` condition is available — it checks whether the
player is currently in that room. This enables encounter rules that branch
based on which room triggered them (e.g., different fall damage by room).

### 4B. Game-over conditions

Model win and loss conditions as mechanic entries with `type: "win"` or
`"lose"`:

```json
"escape": {
  "id": "escape",
  "type": "win",
  "description": "Player unlocks the padlock and escapes.",
  "condition": {
    "all": [
      "flag:padlock_unlocked == true",
      "flag:player_escaped == true"
    ]
  },
  "narrative": "You turn the key. The padlock springs open. You squirm through the rip and tumble into the Astral Plane — and then you're falling, falling, until you land on solid ground, outside the Bag.",
  "trigger_id": "escaped"
}
```

```json
"key_dropped_through_rip": {
  "id": "key_dropped_through_rip",
  "type": "lose",
  "description": "Player drops the key through the rip into the Astral Plane.",
  "condition": { "require": "flag:key_lost_to_astral == true" },
  "narrative": "The key falls into the Astral Plane, lost forever. You are trapped in the Bag of Holding.",
  "trigger_id": "key_lost"
}
```

For multi-step win conditions (e.g., unlock padlock AND escape), use `"all"`
to combine separate flags. Each flag should be set by a different interaction,
exit, or encounter along the critical path.

### 4C. Stats block (if applicable)

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
  "resolution_system": "d20"
}
```

Rules:
- Only declare stats actually used in stat_check interactions or stat: conditions
- If no stat checks exist in the scenario, omit this block entirely
- Resolution system is always `"d20"` for now

---

### Step 4 validation checklist

- [ ] Every encounter from the scenario is represented
- [ ] Every win condition is a mechanic with `type: "win"`
- [ ] Every loss condition is a mechanic with `type: "lose"` or `"death"`
- [ ] Every mechanic referenced by a `trigger_encounter` exists in the block
- [ ] Every `trigger_id` is unique across all mechanics
- [ ] Game-over mechanics have `condition`, `narrative`, and `trigger_id`
- [ ] Encounter mechanics have `rules` (not `condition`/`type`/`trigger_id`)
- [ ] If stats block present: only stats actually used are defined
- [ ] If stats block absent: no stat_check interactions or stat: conditions
  exist in rooms/entities

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

3. **`player.stats`** — only if the corpus has a `stats` block. Under d20,
   typical values range 3-18 with 10 as average. If the scenario doesn't specify
   stat values, use 10 across all stats declared in the corpus definitions.

4. **`flags`** — enumerate every flag name used anywhere:
   - In condition strings (`flag:...`)
   - In `set_flag` results
   - In encounter `set_flags`
   - In on_enter/on_examine events
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
- [ ] Every NPC has `"attitude"` set to the value from the NPC's
  `attitude_limits.initial` (default 0) in `entity_states`
- [ ] Every NPC's `entity_states` includes an `attitude` field that is also
  declared in the NPC's `state_fields`
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
  "npc_revelations": {},
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

6. **`npc_revelations`** — always `{}`. Populated during play when NPCs
   reveal gated topics.

7. **`revealed_hints`** — `[]`. Stores `reveals` strings from successful
   interactions. Starts empty.

8. **`turn_history`** — always `[]`.

9. **`dialogue_state`** — always the null structure shown above.

10. **`player_knowledge`** — `[]`. List of revelation descriptions accumulated
    during play (from `reveals` fields in Result objects). Starts empty.

---

### Step 6 validation checklist

- [ ] `soft_inventory` is `[]`
- [ ] `surfaced_soft_items` is `{}`
- [ ] `checks_attempted` is `{}`
- [ ] `revealed_hints` is `[]`
- [ ] `npc_revelations` is `{}`
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
- [ ] Every NPC with `dialogue_guidelines.will_reveal` entries has
  matching `set_flag` / `set_entity_state` values that exist

### Corpus self-consistency

- [ ] `flags_declared` is present as a top-level list of all flag names used
  in conditions and set_flag results
- [ ] Every flag in `flags_declared` exists in `hard_state.flags`
- [ ] No duplicate IDs across all rooms, exits, entities, interactions,
  mechanics, flags, and topics
- [ ] Every `will_reveal.conditions` string references entities, flags,
  attitudes, topics, or tags that exist in the corpus/hard state
- [ ] Every `on_examine` event with a condition references an existing flag
- [ ] Every `using_results` key is either an entity ID in corpus or `"*"`
- [ ] Every stat check (stat_check type) references a stat key in
  `corpus.stats.definitions` (if stats block exists; otherwise, no stat_check
  should appear)
- [ ] Every `set_stat` result references a stat key in `stats.definitions`
  (if stats block exists; otherwise, no set_stat should appear)

### Hard-state checks

- [ ] `hard_state.player.location` matches the room with `is_start_room: true`
- [ ] Every entity with `state_fields` has a complete `entity_states` entry
- [ ] `entity_states` contains no fields not declared in the entity's `state_fields`
- [ ] Entities that are narratively hidden (e.g., spider in webs) are still
  listed in `entities_present` until engine-level entity hiding is supported
- [ ] `entity_states` contains all fields declared in the entity's `state_fields`
- [ ] Every NPC has `attitude` in both `state_fields` and `entity_states`
- [ ] NPC attitude values are within the `[min, max]` range from their
  `attitude_limits`

### Soft-state checks

- [ ] Every NPC in corpus has `attitude` initialised in `entity_states`
- [ ] `dialogue_state` has the standard null structure
- [ ] `npc_revelations` is `{}`

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

12. **Stat value ranges**: Under d20, stat values typically range 3-18. DCs
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

16. **Entity-level hiding not yet supported**: The engine does not currently
    filter entities from the GMBriefing based on state. Entities in
    `entities_present` are always visible to the LLM. Hidden entity patterns
    currently rely on LLM compliance and gated interactions.

17. **Global traversal checks**: There is no mechanism to apply a
    traversal_check to all exits at once. If carrying an item affects
    movement, duplicate the traversal_check on every relevant exit.

18. **No dynamic DC scaling**: The schema does not support stat checks with
    escalating DCs based on attempt count. Model repeated interactions with
    increasing DCs as separate interaction entries with mutually exclusive
    conditions.

19. **`on_dialogue_exit` for post-dialogue state changes**: If an NPC dies,
    flees, or changes state when dialogue ends (not during dialogue), use
    `on_dialogue_exit` rather than an interaction result.
