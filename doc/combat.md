# Combat System

MGMAI supports a rudimentary, multi-round combat phase modelled after
D&D 5e but described in corpus-agnostic terms so other RPG systems can be
plugged in later.  Combat is a **phase** in the game loop, analogous to
dialogue mode: when active, the set of valid player actions narrows to
*attack* and *flee*.

## Resolution System Abstraction

All system-specific maths — ability modifiers, the d20 roll,
advantage/disadvantage, attack/crit/fumble rules, AC and HP formulas,
initiative, and (in future) saving throws — live behind a
`ResolutionSystem` interface in `mgmai.engine.systems`.  The combat loop,
the action resolver, and the encounter engine are system-agnostic: they
orchestrate turns and state, then call the active system for every die
roll and formula.

The active system is selected by `corpus.stats.system` (default `"5e"`)
via `get_system_for_corpus(corpus)`.  `FiveESystem` implements D&D 5e and
reproduces the rules documented in the sections below.  Adding a new
system (Pathfinder, GURPS, d20 Modern, …) means subclassing
`ResolutionSystem`, implementing its methods, and registering it with
`register_system(name, cls)` — **no edits to the combat loop or resolvers
are required.**  The system's dice are rolled through Python's shared
`random` module, so tests that monkeypatch `random.randint` /
`random.random` steer every system uniformly.

---

## Quickstart

To give an NPC combat capability, add a `combat` block and declare
`current_hp` in `state_fields`:

```json
{
  "goblin_scout": {
    "type": "npc",
    "description": "A scrawny goblin with a rusty knife.",
    "state_fields": {
      "alive": { "type": "boolean", "description": "Is the goblin alive?" },
      "current_hp": { "type": "number", "description": "Current hit points." }
    },
    "combat": {
      "hp": 7,
      "ac": 12,
      "atk": 4,
      "dmg": "1d6+2",
      "initiative_mod": 2,
      "flee_dc": 10
    }
  }
}
```

Also set `current_hp` in `hard-state.json`:

```json
"entity_states": {
  "goblin_scout": {
    "alive": true,
    "current_hp": 7
  }
}
```

That's it.  When the player uses an `interact` action with
`interaction_id: "attack"` targeting this NPC, combat begins.

---

## Data Model

### `CombatBlock` (on NPC entities in `corpus.json`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hp` | int (≥ 1) | *required* | Maximum hit points |
| `ac` | int | *required* | Armour Class |
| `atk` | int | *required* | Attack bonus (ability mod + proficiency) |
| `dmg` | str | `"1d6"` | Damage expression, e.g. `"1d6+2"`, `"2d4"`, `"1d8+1"`, or a flat integer like `"3"` |
| `initiative_mod` | int | `0` | DEX-like modifier for initiative rolls |
| `flee_dc` | int | `10` | Difficulty class for the player to flee |
| `on_hit_effects` | list[OnHitEffect] | `[]` | Secondary effects that trigger on a successful hit (saving throws + damage) |

All values are **pre-computed** by the adventure author — the engine does
not derive them from ability scores for NPCs.

### `OnHitEffect` (on-hit effects)

When an NPC's attack hits, each `on_hit_effect` triggers a saving throw
against the player:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `save.stat` | str | *required* | Ability score for the saving throw (e.g. `"CON"`) |
| `save.dc` | int | *required* | Difficulty class for the save |
| `damage` | str | `"1d6"` | Damage expression (dice or flat) |
| `on_save` | `"half"` \| `"none"` \| `"full"` | `"half"` | How a successful save modifies damage |
| `type` | str? | `null` | Optional damage type label (e.g. `"poison"`) |

Example — a spider bite that deals poison damage on a failed CON save:

```json
"combat": {
  "hp": 15,
  "ac": 14,
  "atk": 5,
  "dmg": "1d4+3",
  "on_hit_effects": [
    {
      "save": { "stat": "CON", "dc": 11 },
      "damage": "1d8",
      "on_save": "half",
      "type": "poison"
    }
  ]
}
```

### `PlayerState` extensions

The player gains optional combat fields on `HardGameState.player`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | int | `1` | Character level |
| `current_hp` | int? | `None` | Current hit points (initialised from CON at combat start) |
| `max_hp` | int? | `None` | Maximum hit points (computed from CON if absent) |
| `ac` | int? | `None` | Armour Class (computed from DEX if absent) |
| `proficiency_bonus` | int? | `None` | Proficiency bonus (defaults to `2`) |

When the adventure has a `corpus.stats` block and a field is absent, the
engine computes defaults at combat-start time:

- `max_hp` = 8 + CON modifier (minimum 1)
- `ac` = 10 + DEX modifier
- `proficiency_bonus` = 2 (level 1)

### `CombatState` (on `HardGameState.combat`)

| Field | Type | Description |
|-------|------|-------------|
| `active` | bool | `True` when combat is live |
| `combatants` | list[str] | Entity IDs plus `"player"` |
| `initiative_order` | list[str] | Sorted turn order (highest initiative first) |
| `current_index` | int | Index into `initiative_order` of next actor |
| `round_number` | int | Current round (starts at 1) |
| `log` | list[CombatLogEntry] | Per-round event log |

---

## Combat Flow

> The rules below are those of `FiveESystem`; the engine applies them by
> delegating to the active `ResolutionSystem` (see above).  A different
> system would substitute its own dice, crit thresholds, and formulas
> without the combat loop changing.

### Entering Combat

Combat starts in one of two ways:

1. **Direct attack** — The player uses `interact` + `interaction_id: "attack"`
   on an NPC that has a `CombatBlock`. If the NPC has an `interaction.used`
   reaction that triggers an encounter, the encounter rules run first; an
   encounter outcome of `"combat"` (or a direct attack on an NPC without such
   a reaction) starts combat.
2. **Encounter outcome `"combat"`** — An NPC's `behavior.encounter_rules` or a
   `mechanics` encounter returns outcome `"combat"`.

On entry:
- Player HP is initialised from CON if not already set.
- Each enemy's `current_hp` is initialised from their `CombatBlock.hp`.
- Initiative is rolled once: `d20 + DEX_modifier` (player) or
  `d20 + initiative_mod` (NPC).  Ties are broken by modifier then coin flip.
- Any enemy who rolled higher than the player takes their turn immediately.
- The player's narrated attack does **not** deal damage on this turn — it
  only triggers combat entry.
- Dialogue mode is exited if active.

### Turn Order

The engine processes turns in initiative order.  The player is prompted
only when `initiative_order[current_index] == "player"`.

### Player Actions in Combat

When combat is active, only two action types are valid:

| Action | Description |
|--------|-------------|
| `combat` (`combat_action: "attack"`) | Attack a combatant.  `target` must be an entity ID in `combatants`. |
| `move` | Attempt to flee (see below). |

All other actions (`examine`, `talk`, `transfer`, `interact`) are rejected
by the engine while combat is active.

### Attack Resolution

**Player attack:**

- Attack roll: `d20 + STR_modifier + proficiency_bonus` (melee only).
  - Natural 1: auto-miss.
  - Natural 20: auto-hit and critical.
- Compare total vs target's `CombatBlock.ac`.
- Damage on hit:
  - Unarmed / no weapon tag: `1d6 + STR_modifier`.
  - Any item in inventory with `tag: "weapon"`: `1d8 + STR_modifier`.
  - Critical: double the number of damage dice; modifier added once.
- If the target's `current_hp` drops to ≤ 0, it dies: `alive` is set to
  `false` and it is removed from `combatants`.

**NPC attack:**

- Attack roll: `d20 + CombatBlock.atk` vs player AC.
  - Same natural-1 / natural-20 rules.
- Damage: parsed from `CombatBlock.dmg` (e.g., `"1d6+2"`).
- Critical: double dice, modifier once.
- If the player's `current_hp` drops to ≤ 0, `game_over` is set with
  `type: "lose"` and `trigger: "player_death"`.

After the player's turn, all surviving enemies take their turns in
initiative order.  Then the round advances.

### Ending Combat

Combat ends when:

- All enemies are dead → victory.  Control returns to normal exploration.
- The player dies → game over (defeat).
- The player successfully flees.

### Fleeing

When the player uses `move` during combat:

1. The target exit must be a valid, accessible exit from the current room.
2. Roll a DEX check: `d20 + DEX_modifier` vs the **highest** `flee_dc`
   among active enemies.
3. **Success**: combat ends, the player moves to the target room.
   `traversal.succeeded` reactions are **not** evaluated.
4. **Failure**: the player stays, turn is consumed, and remaining enemy
   turns are resolved normally.

---

## Display and Narration

### Combat Status Panel

Between combat turns, the console UI shows a status panel:

```
┌─ Combat: Round 2 ──────────────────────────────────────┐
│ Initiative: Player → Spider → Goblin                    │
│                                                         │
│ Player    HP ████████░░ 10/12                           │
│ Spider    HP ██████████ 18/18                           │
│ Goblin    HP ████░░░░░░  5/10                           │
│                                                         │
│ It's your turn.                                         │
└─────────────────────────────────────────────────────────┘
```

### Combat Prefix

Before each narrated combat turn, a brief prefix summarises the round's
mechanical events (e.g., `**Spider attacks you: hit for 3 damage.**`).
This is prepended to the LLM's narration so the player always sees the
authoritative dice results.

---

## Examples

### NPC with combat stats (corpus.json)

```json
{
  "spider": {
    "type": "npc",
    "description": "A hairy spider the size of a dog.",
    "state_fields": {
      "alive": { "type": "boolean", "description": "Is the spider alive?" },
      "fled": { "type": "boolean", "description": "Has the spider fled?" },
      "current_hp": { "type": "number", "description": "Current hit points." }
    },
    "behavior": {
      "encounter_rules": [
        {
          "condition": { "require": "spider_fled" },
          "outcome": "combat",
          "narrative": "The spider, cornered, skitters forward to attack!"
        }
      ]
    },
    "reactions": [
      {
        "id": "spider_attack_on_sight",
        "on": "interaction.used",
        "condition": { "require": "event:interaction_id == attack" },
        "effects": { "trigger_encounter": "self" }
      }
    ],
    "combat": {
      "hp": 18,
      "ac": 13,
      "atk": 5,
      "dmg": "1d8+3",
      "initiative_mod": 3,
      "flee_dc": 12
    }
  }
}
```

Here the encounter system first checks `spider_fled`.  If the spider
already fled, the `"combat"` outcome triggers the combat system instead
of the old one-shot resolution.

### Player character sheet with combat stats

```json
{
  "system": "5e",
  "player": {
    "level": 1,
    "stats": {
      "STR": 16,
      "DEX": 14,
      "CON": 12,
      "INT": 10,
      "WIS": 8,
      "CHA": 10
    },
    "current_hp": 10,
    "max_hp": 10,
    "ac": 14,
    "proficiency_bonus": 2
  }
}
```

---

## Limitations (Phase 1)

The minimum viable combat system deliberately excludes:

- Gear / equipment (beyond weapon tag detection)
- Movement / positioning / tactical maps
- Spellcasting and class features
- Conditions (poisoned, stunned, etc.)
- Death saving throws
- Healing during combat
- Multi-attack, reactions, opportunity attacks
- NPC-vs-NPC combat
- NPC-initiated fleeing
- Enemy AI / decision-making (enemies always attack)

These may be added in future phases.

> Note: the *engine* is already system-agnostic through the
> `ResolutionSystem` interface; the limitations above concern combat
> *features* (gear, conditions, spells, …), not system portability.  The
> saving-throw hook (`ResolutionSystem.resolve_save`) is wired into the
> on-hit effects phase of NPC attacks — see `OnHitEffect` above.
