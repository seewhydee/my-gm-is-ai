# Player Stats

At present, we implement a rudimentary player stat system, supporting the following:

1. A basic character sheet with ability scores (STR, DEX, CON, INT, WIS, CHA).
2. Stat checks (e.g., "STR vs DC 12") for gating actions and resolving uncertain outcomes.
3. Adventure module-level references to stats in conditions and interactions.
4. A **resolution system abstraction** that decouples adventures from specific RPG editions (D&D 5e, Pathfinder, GURPS, etc.).

## Character Sheets

You can use a custom player character sheet for a new game:

```bash
mgmai adventures/bag-of-holding --char-sheet my-character.json
# or: python -m mgmai.cli adventures/bag-of-holding --char-sheet my-character.json
```

The character sheet JSON must declare the RPG `system` (e.g. `"5e"`) and may
override any field under `player`, such as `stats`, `location`, or `inventory`.
`--char-sheet` cannot be combined with `--load`.

### Default player character

Adventures with a `corpus.stats` block should ship a `default-player.json`
file in the adventure directory.  This file uses the same character-sheet
format as `--char-sheet`:

```json
{
  "system": "5e",
  "player": {
    "stats": { "STR": 10, "DEX": 13, "CON": 12, "INT": 11, "WIS": 10, "CHA": 10 },
    "level": 4,
    "max_hp": 27,
    "current_hp": 27,
    "ac": 11,
    "proficiency_bonus": 2,
    "save_proficiencies": ["DEX", "INT"],
    "skill_proficiencies": ["acrobatics"],
    "weapon_proficiencies": ["simple", "martial"],
    "abilities": ["fire_bolt", "cure_wounds"]
  }
}
```

The optional `abilities` list names the combat abilities the player
knows (defined in the corpus's
[abilities](../schema/corpus.md#abilities) block); the player uses them
in combat via the `use_ability` combat action.

At new-game init the player block is resolved as a field-by-field overlay:

1. Base: `location` seeded from the start room; all other fields default.
2. `default-player.json` (if present) — the adventure's default hero.
3. `hard-state.json`'s `player` block (if present) — author's tweak.
4. `--char-sheet` (if supplied) — the player's own character.

Each layer overrides only the fields it specifies, so a partial
`--char-sheet` that sets only `inventory` composes on top of
`default-player.json` without wiping its stats.

For characters above level 1, `default-player.json` must carry the full
combat block explicitly (`max_hp`, `current_hp`, `ac`,
`proficiency_bonus`, `save_proficiencies`) because the engine cannot
derive multi-level HP from ability scores alone.

## Design Overview

### Stat definitions in the corpus

An optional `stats` block in `corpus.json` declares which stats the adventure uses and which resolution system applies:

```json
{
  "adventure": { ... },
  "rooms": { ... },
  "entities": { ... },
  "mechanics": { ... },
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
}
```

- `definitions` is a dict of stat keys → `{ name, description }`.
- `system` references a named built-in (currently only `5e`).
- If `stats` is absent, the adventure has no stat system — existing adventures work unchanged.

### Player stats in hard state

Player stat values live in `hard_state.player.stats` as an optional dict of stat key → integer value. These are engine-authoritative (hard state), so the LLM cannot mutate them directly. At game start the default source of player stats is `default-player.json`, overridable by `--char-sheet`; an optional `player` block in `hard-state.json` can also tweak the default. The engine validates that every stat key in the player state has a matching entry in the corpus definitions, and that stats are consistently present or absent in both.

### Condition domain: `stat`

A condition domain extends the condition string format:

```
stat:STR >= 12
stat:CHA >= 15
```

This lets scenario authors gate interactions, exits, encounters, and knowledge reveals on stat thresholds. For example, a "Bend the Bars" interaction might require both `stat:STR >= 13` and the presence of a crowbar in inventory.

### The `stat_check` check type

This check type exists alongside the `roll` (flat percentage) check:

| Field | Description |
|-------|-------------|
| `type` | `"stat_check"` |
| `stat` | Stat key (defined in corpus.stats.definitions, or a skill known to the system) |
| `target` | Target number / difficulty class |
| `modifier` | Flat situational modifier (default 0) |
| `save` | 5e: this check is a saving throw (default false) |
| `repeatable` | Whether the check can be retried |

System-specific fields (e.g. `advantage` / `disadvantage` for `5e`) are
accepted as extra top-level keys. The engine dispatches `stat_check` to the
active resolution system, which computes the dice formula and produces a
success/failure outcome. Advantage/disadvantage may also be imposed by the
player's active status effects (5e: `advantage_on_ability_checks` /
`disadvantage_on_ability_checks`); these apply to ability and skill checks
but not to saving throws (`save: true`).

### Skill checks (5e)

For the `5e` system, `stat` may also name one of the 18 SRD skills
(Acrobatics, Athletics, Stealth, …; matched case-insensitively). The skill
list and each skill's governing ability are built into `FiveESystem`
(`SKILL_ABILITIES`); corpus authors do not declare skills in
`stats.definitions`.

A skill check rolls against the player's score in the governing ability
(e.g. Acrobatics → DEX), adding the player's proficiency bonus when the
skill appears in `hard.player.skill_proficiencies`:

```json
{ "type": "stat_check", "stat": "acrobatics", "target": 13, "repeatable": true }
```

Skills are not scores — a character's skill proficiencies are a list of
skill names on the player state (mirroring `save_proficiencies`), settable
via `default-player.json` or `--char-sheet`:

```json
"skill_proficiencies": ["acrobatics", "stealth"]
```

The resolution goes through the system's `stat_value_for_check(stat,
player)` hook (skill → governing ability score) and `skill_modifier(stat,
player)` hook (proficiency bonus when proficient); the default base-class
implementations handle plain ability-score stats, so other systems are
unaffected.

### Weapon proficiencies (5e)

A player's weapon proficiencies determine whether the proficiency bonus is
added to a weapon's **attack roll**.  They live on the player state as a
list whose entries are combined with OR (the player is proficient if any
entry matches the weapon).  Each entry is one of:

- a weapon-category name (`"simple"` or `"martial"`), or
- an individual weapon entity ID, or
- a **property-filtered clause** object
  `{"category": "...", "properties": [...]}` granting proficiency with
  weapons of that category whose `properties` include at least one of the
  listed properties (OR within the list).

```json
"weapon_proficiencies": ["simple", "martial", "longsword"]
```

The clause form models class proficiencies that the bare categories
cannot express — e.g. the Rogue's "Simple weapons and Martial weapons
that have the Finesse or Light property", or the Monk's "…Martial
weapons that have the Light property":

```json
"weapon_proficiencies": [
  "simple",
  {"category": "martial", "properties": ["finesse", "light"]}
]
```

- The two categories are `"simple"` and `"martial"` (matching the SRD
  weapon tables).  Each SRD pack weapon carries its category as an
  `equip_tag` (see [gear](gear.md#data-model-equipblock)).
- An individual weapon entity ID grants proficiency with that weapon
  alone (used for racial or class grants outside the two categories,
  e.g. an elf's longsword proficiency or a custom weapon with no
  category).
- A clause grants proficiency with any weapon in `category` that shares
  at least one property with `properties`.  Property names match the
  weapon's `properties` list (e.g. `"finesse"`, `"light"`, `"thrown"`).
- A weapon the player is **not** proficient with may still be used — it
  simply does not add the proficiency bonus to the attack roll (the
  ability modifier and the weapon's `hit_bonus` still apply).
- **Unarmed strikes are always proficient**, regardless of the list.

The check is performed by `FiveESystem._player_proficient_with_weapon`
and applied in `compute_player_attack_bonus`.  Unknown categories or IDs
are rejected at load time (see [hard state](../schema/hard-state.md)).

### Resolution system abstraction

The resolution system defines **how stat checks translate to probability**, decoupling adventures from specific RPG mechanics.

| System | Formula | Use case |
|--------|---------|----------|
| `5e` | roll(1d20) + (stat-10)//2 + modifier >= target | D&D 5e ability checks with advantage/disadvantage |
| `3d6` | 3d6 <= stat + modifier | GURPS-style |
| `flat` | stat + modifier >= DC | Diceless / point-buy |

Currently only `5e` is implemented, as `FiveESystem` in
`mgmai.engine.systems`.  The engine obtains a `ResolutionSystem`
instance via `get_system(name)` / `get_system_for_corpus(corpus)` and
delegates modifiers, dice, checks, saving throws, attack/crit rules,
AC/HP formulas, and initiative to it.  Adding a system means
subclassing `ResolutionSystem` and registering it with
`register_system(name, cls)`.  The table above sketches candidate
systems; their formulas would live inside the corresponding subclass.

### GMBriefing extension

When stats are present, the GMBriefing includes a `player_stats` section with each stat's value and computed modifier (e.g., `STR: { value: 14, modifier: 2 }`). This gives the LLM direct knowledge of the player's capabilities without requiring it to do the math.

### EngineResult extension

Stat check details are recorded in the existing `rolls` array, including the stat name, DC, modifier breakdown, raw roll, total, margin (total − DC), and advantage/disadvantage status.

### Character sheet display

When stats are present, the console UI renders a Rich panel showing all stats with computed modifiers:

```
┌─ Character Sheet ──────────────┐
│ STR 14 (+2)   INT 10 (+0)     │
│ DEX 12 (+1)   WIS  8 (-1)     │
│ CON 13 (+1)   CHA 16 (+3)     │
└────────────────────────────────┘
```

## What changes

The following files need modification or addition:

| Area | Change |
|------|--------|
| **Corpus schema** | Add `stats` block with definitions + `system`. Replace flat `Check` model with `RollCheck | StatCheck` discriminated union. |
| **Hard state schema** | Add optional `player.stats`. |
| **Briefing schema** | Add `PlayerStatEntry` model; include `player_stats` in GMBriefing. |
| **Conditions evaluator** | Add `stat` domain to condition parser regex and evaluation branch. |
| **Engine resolver** | Add `_resolve_stat_check()`; dispatch on check type. |
| **Stat checks module** (new) | Standalone `compute_5e_modifier()`, `roll_d20()`, and `compute_modifier()` functions (now thin backward-compat shims over `mgmai.engine.systems.FiveESystem`). |
| **Context Assembler** | Pass corpus to player-state builder; compute and include `player_stats`. |
| **State manager** | Add `_validate_player_stats()` on load/new-game. |
| **Console display** | Add character sheet Rich panel. |
| **Schema docs** | Document stats block, stat_check type, and stat condition domain. |

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
