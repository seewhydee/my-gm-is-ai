# Player Stats

At present, we implement a rudimentary player stat system, supporting the following:

1. A basic character sheet with ability scores (STR, DEX, CON, INT, WIS, CHA).
2. Stat checks (e.g., "STR vs DC 12") for gating actions and resolving uncertain outcomes.
3. Adventure module-level references to stats in conditions and interactions.
4. A **resolution system abstraction** that decouples adventures from specific RPG editions (D&D 5e, Pathfinder, GURPS, etc.).

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
    "resolution_system": "d20"
  }
}
```

- `definitions` is a dict of stat keys → `{ name, description }`.
- `resolution_system` references a named built-in (currently only `d20`).
- If `stats` is absent, the adventure has no stat system — existing adventures work unchanged.

### Player stats in hard state

Player stat values live in `hard_state.player.stats` as an optional dict of stat key → integer value. These are engine-authoritative (hard state), so the LLM cannot mutate them directly. On startup, the system validates that every stat key in the player state has a matching entry in the corpus definitions, and that stats are consistently present or absent in both.

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
| `stat` | Stat key (must be defined in corpus.stats.definitions) |
| `dc` | Difficulty class (or target number) |
| `modifier` | Flat situational modifier (default 0) |
| `resolution_params` | System-specific options (e.g., advantage for d20) |
| `repeatable` | Whether the check can be retried |
| `opposed_by` | Reserved for future NPC opposed checks |
| `skill` | Reserved for future skill checks |

The engine dispatches `stat_check` to the active resolution system, which computes the dice formula and produces a success/failure outcome.

### Resolution system abstraction

The resolution system defines **how stat checks translate to probability**, decoupling adventures from specific RPG mechanics.

| System | Formula | Use case |
|--------|---------|----------|
| `d20` | roll(1d20) + (stat-10)//2 + modifier >= DC | D&D-style (3-18 stats, DC 10-20) |
| `3d6` | 3d6 <= stat + modifier | GURPS-style |
| `flat` | stat + modifier >= DC | Diceless / point-buy |

Currently only `d20` is implemented. The schema reserves the space for additional systems; the engine dispatches via a named lookup.

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
| **Corpus schema** | Add `stats` block with definitions + resolution_system. Replace flat `Check` model with `RollCheck | StatCheck` discriminated union. |
| **Hard state schema** | Add optional `player.stats`. |
| **Briefing schema** | Add `PlayerStatEntry` model; include `player_stats` in GMBriefing. |
| **Conditions evaluator** | Add `stat` domain to condition parser regex and evaluation branch. |
| **Engine resolver** | Add `_resolve_stat_check()`; dispatch on check type. |
| **Stat checks module** (new) | Standalone `compute_d20_modifier()` and `compute_modifier()` functions. |
| **Context Assembler** | Pass corpus to player-state builder; compute and include `player_stats`. |
| **State manager** | Add `_validate_player_stats()` on load/new-game. |
| **Console display** | Add character sheet Rich panel. |
| **Schema docs** | Document stats block, stat_check type, and stat condition domain. |

## Open questions

1. **NPC stats**: Not for this phase. The `StatCheck` schema reserves an `opposed_by` field and the condition parser reserves an `npc_stat:` domain for future use. NPC capabilities remain modelled through `behavior` encounter rules and `attitude_limits`.

2. **LLM knowledge**: Include the full player_stats block in the GMBriefing (not just the relevant stat) so the LLM understands the character holistically.

3. **Portability**: Eventually we want to import/export player stat blocks across adventures. The design uses `hard_state.player.stats` as a pure data dict, making this straightforward later.
