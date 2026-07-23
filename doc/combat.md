# Combat System

MGMAI supports a rudimentary, multi-round combat phase modelled after
D&D 5e but described in corpus-agnostic terms so other RPG systems can be
plugged in later.  Combat is a **phase** in the game loop, analogous to
dialogue mode: when active, the set of valid player actions narrows to
*attack* and *flee*.

## Resolution System Abstraction

All system-specific maths — ability modifiers, the d20 roll,
advantage/disadvantage, attack/crit/fumble rules, AC and HP formulas,
initiative, and saving throws — live behind a
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
| `dmg_type` | str | `""` | Damage type of the NPC's damage (untyped if empty) |
| `resistances` | list[str] | `[]` | Damage types halved (rounded down) against this NPC |
| `vulnerabilities` | list[str] | `[]` | Damage types doubled against this NPC |
| `immunities` | list[str] | `[]` | Damage types reduced to 0 against this NPC |
| `on_hit_effects` | list[CheckResolution] | `[]` | Secondary effects that trigger on a successful hit (saving throws + damage) |
| `attacks` | list[NPCAttackDef] | `[]` | Named attack options (`{id, name?, atk, dmg, dmg_type?, on_hit_effects?}`) |
| `multiattack` | list[str] | `[]` | Ordered attack ids performed each turn (repeats allowed) |
| `ai` | CombatAIBlock? | `null` | Rule-of-thumb combat AI configuration (see [Party Combat and Combat AI](#party-combat-and-combat-ai)) |

An NPC with no `attacks` makes one basic attack per turn from the
block-level `atk` / `dmg` / `on_hit_effects`.  With `attacks`, it uses
the `multiattack` sequence (or the first listed attack when no sequence
is given), each with its own bonus, damage, and on-hit effects; the
sequence stops early if the target drops.  Attack `name` is a verb
phrase used by the combat prefix ("Wolf bites you").  When `attacks` is
present, block-level `on_hit_effects` is forbidden and `atk` optional.

Damage types use the 5e vocabulary (acid, bludgeoning, cold, fire,
force, lightning, necrotic, piercing, poison, radiant, slashing,
thunder).  Mitigation applies to any typed damage dealt to the NPC —
by the player's weapons (`EquipBlock.damage_type`) or by other NPCs;
untyped damage is never mitigated, and the player has no damage-type
modifiers yet.  Combat log entries record the `damage_type` and the
applied `mitigation` (`"resisted"`, `"vulnerable"`, `"immune"`), which
the combat prefix annotates.

All values are **pre-computed** by the adventure author — the engine does
not derive them from ability scores for NPCs.

### On-hit effects (`CheckResolution`)

When an NPC's attack hits, each `on_hit_effect` resolves a
[CheckResolution](../schema/corpus.md#follow-up) against the player.
The `check` is usually a `stat_check` saving throw, with `success` and
`failure` [Results](../schema/corpus.md#result) describing what happens.
Only a combat-safe subset of result fields is allowed: `narrative`,
`set_flag`, `player_damage`, `game_over`, `reveals`, and nested
`then_check`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `check` | Check | *required* | The check to resolve, e.g. a `stat_check` save |
| `success` | Result | *required* | Result on a successful save/check |
| `failure` | Result | — | Result on a failed save/check |
| `tag` | str? | `null` | Optional damage type label (e.g. `"poison"`) |

Example — a spider bite that deals poison damage on a failed CON save,
half damage on a successful save, and applies the `poisoned` flag:

```json
"combat": {
  "hp": 15,
  "ac": 14,
  "atk": 5,
  "dmg": "1d4+3",
  "on_hit_effects": [
    {
      "check": {
        "type": "stat_check",
        "stat": "CON",
        "target": 11,
        "save": true,
        "repeatable": false
      },
      "tag": "poison",
      "success": {
        "narrative": "You shake off the worst of the venom.",
        "player_damage": "half(1d8)"
      },
      "failure": {
        "narrative": "The venom courses through you.",
        "player_damage": "1d8",
        "set_flag": { "poisoned": true }
      }
    }
  ]
}
```

If `check.save` is true, the check is a saving throw: the player's save
proficiency for that stat is added to the roll.  In 5e this means adding
`proficiency_bonus` when the stat is listed in `save_proficiencies`.

Damage expressions may use `half(expr)` to deal half of `expr` rounded
down (minimum 1), typically on a successful save.

### `PlayerState` extensions

The player gains optional combat fields on `HardGameState.player`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | int | `1` | Character level |
| `current_hp` | int? | `None` | Current hit points (initialised from CON at combat start) |
| `max_hp` | int? | `None` | Maximum hit points (computed from CON if absent) |
| `ac` | int? | `None` | Armour Class (computed from DEX if absent) |
| `proficiency_bonus` | int? | `None` | Proficiency bonus (defaults to `2`) |
| `save_proficiencies` | list[str]? | `[]` | Ability scores the player is proficient in for saving throws (e.g. `["DEX","INT"]`) |
| `weapon_proficiencies` | list[str]? | `[]` | Weapon proficiency categories (`"simple"`, `"martial"`) and/or weapon entity IDs. The proficiency bonus is added to a weapon's attack roll only when proficient; unarmed strikes are always proficient (see [player stats](player-stats.md#weapon-proficiencies-5e)) |
| `status_effects` | dict[str,int] | `{}` | Active status effects (status effect id → rounds remaining); combat-scoped entries clear at combat end, persistent ones survive |

### Status Effects

Status effects are declared in the corpus top-level `status_effects`
block (see [schema/corpus.md — Status Effects](../schema/corpus.md#status-effects)),
overlaid on the built-in SRD condition list (`poisoned`, `stunned`,
`prone`, `blinded`, `invisible`, the exhaustion levels, …), which ships
with the engine as a data pack (`mgmai/data/srd_5e/conditions.json`).
The player's status effects live on `PlayerState.status_effects`; NPC
status effects live in `entity_states[id]["status_effects"]`.  Both map a
status effect ID to its remaining rounds.

Each definition's `scope` and `duration` drive its lifetime:

- `scope: "combat"` — ticks at the start of the afflicted combatant's
  turn; cleared when combat ends.
- `scope: "persistent"` — ticks once per turn-costing player action
  (`turn.end` fires only when the action costs a turn); survives
  combat end.
- `duration: "rounds"` — decrements on each tick, expires at zero.
- `duration: "until_turn_start"` — removed on the afflicted's first
  tick (legacy `prone` behavior).
- `duration: "until_cleared"` — removed only by curing, combat end
  (combat-scoped), or a manual Result.

The built-in defaults reproduce the 5e SRD conditions:

| Status effect | Effect (simplified) |
|-----------|---------------------|
| `poisoned` | Disadvantage on own attack rolls and ability checks (including the flee check). |
| `stunned` | The combatant loses its turn; attack rolls against it have advantage; it auto-fails STR and DEX saves. |
| `prone` | Attack rolls against it have advantage; it automatically stands at the start of its turn. |
| `blinded` | Attack rolls against it have advantage; its own attack rolls have disadvantage. |
| `frightened` | Disadvantage on own attack rolls and ability checks. |
| `invisible` | Its attack rolls have advantage; attack rolls against it have disadvantage. |
| `incapacitated` / `paralyzed` / `petrified` / `unconscious` | The combatant loses its turn; `paralyzed`/`petrified`/`unconscious` also grant advantage to attackers and auto-fail STR and DEX saves. |
| `restrained` | Disadvantage on own attack rolls; attack rolls against it have advantage. |
| `charmed` / `deafened` / `grappled` | No roll modifiers; adjudicated by the GM from the description. |
| `exhaustion-1` … `exhaustion-6` | Persistent; −2 × level on all of the combatant's d20 rolls (attacks, checks, saves). |

Custom status effects declare their roll modifiers per system via
`system_effects` (e.g. `{ "5e": { "disadvantage_on_attack": true } }`),
`skip_turn` for turn loss, and `tick_effect` for per-tick damage.
Advantage and disadvantage cancel each other as usual.  Status effects are
applied to the player through the `apply_status_effect` field of combat-safe
Results (typically on-hit effects):

```json
"failure": {
  "narrative": "The venom courses through you.",
  "player_damage": "1d8",
  "apply_status_effect": { "id": "poisoned", "rounds": 3 }
}
```

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
| `allies` | list[str] | Combatant IDs fighting on the player's side (reserved for party combat; empty in solo encounters) |
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
   on an NPC that has a `CombatBlock`. A direct attack immediately enters
   combat with that NPC plus any present, living members of its
   `combat_group`.  If the NPC has an `interaction.used` reaction that
   triggers an encounter, the encounter rules run first.  A `combat`
   action (`combat_action: "attack"`) received while *not* in combat is
   treated the same way — the engine routes it through this path rather
   than rejecting it, since the intent is unambiguous.
2. **Encounter outcome** — An NPC's `aggro.encounter_rules` or a
   `mechanics` encounter returns a `result.start_combat` list.  The
   listed entity IDs are added to the source, and each id's
   `combat_group` is expanded.

In both cases the enemy set is the filtered union of the source,
its `combat_group`, and any ids listed in `start_combat`.  Enemies must be
present in the current room and alive; dead, absent, or non-stat-blocked
ids are silently dropped.  If the filtered set is empty, no combat is
entered.

**Allies.**  When combat begins, every present living **follower** (an
NPC with `following: true` in its entity state) that has a combat block
automatically joins the player's side: it rolls initiative, appears in
`combatants` and `allies`, and acts on its own turn via the combat AI
(see *Party Combat and Combat AI* below).  Followers without combat
blocks stay non-combatant bystanders.  A follower the player attacked
directly joins as an enemy, not an ally.

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

When combat is active, the following action types are valid:

| Action | Description |
|--------|-------------|
| `combat` (`combat_action: "attack"`) | Attack a combatant.  `target` must be an enemy entity ID in `combatants`. |
| `combat` (`combat_action: "use_item"`) | Use a consumable item.  `target` must be an inventory item with a `consumable` block (healing clamps to max HP; consumes the player's action). |
| `move` | Attempt to flee (see below). |
| `wait` | Pass the turn: no attack/item/ability, but the `detail` is narrated as usual and soft-state patches apply. NPC turns proceed and the round advances. |
| `examine` | Free cursory look (non-rigorous only). Rigorous examine is not allowed during combat. |

All other actions (`talk`, `transfer`, `interact`) are rejected by the
engine while combat is active.

### Attack Resolution

**Player attack:**

- Attack roll: `d20 + weapon_ability_modifier + proficiency_bonus (if
  proficient) + weapon_hit_bonus`.  The weapon ability is STR by default,
  DEX for `ranged` weapons, the better of STR/DEX for `finesse` weapons.
  The proficiency bonus is added only when the player is proficient with
  the equipped weapon (see [weapon proficiencies](player-stats.md#weapon-proficiencies-5e));
  a non-proficient weapon is still usable without it.  Unarmed strikes
  (no equipped weapon) are always proficient.
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

- Attack roll: `d20 + CombatBlock.atk` vs the target's AC.  The engine
  chooses the target (currently always the player; the resolution path is
  generalized so NPCs can target any combatant).
  - Same natural-1 / natural-20 rules.
- Damage: parsed from `CombatBlock.dmg` (e.g., `"1d6+2"`).
- Critical: double dice, modifier once.
- If the player's `current_hp` drops to ≤ 0, combat ends immediately —
  this is checked after **every** action against damage accumulated
  across all attackers in the current turn, so several enemies whose
  combined damage is lethal end combat immediately rather than after a
  phantom extra turn.  The `player.died` event then fires (see
  [Events](../schema/events.md#player-death)): if no reaction restores
  HP above 0, `game_over` is set with `type: "lose"` and
  `trigger: "player_death"`.

After the player's turn, all surviving enemies take their turns in
initiative order.  Then the round advances.  Enemies killed earlier in
the round (e.g. by the player's attack) are removed from `combatants`
immediately and do not act when their initiative slot comes up.

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
   turns are resolved normally — if the player drops to 0 HP, combat
   ends and, unless a `player.died` rescue reaction intervenes, the
   game is over (a loss).

---

## Party Combat and Combat AI

Combat has two sides: the **party** (the player plus allied followers)
and the **enemies**.  Every NPC combatant — on either side — is
controlled by a deterministic, rule-of-thumb combat AI in the engine;
no LLM calls are involved in NPC decisions, and the narration LLM call
simply narrates the outcomes.

### Target selection

When an NPC acts, the engine picks its target among the living members
of the opposing side according to the NPC's `combat.ai.targeting` rule:

| Rule | Behavior |
|------|----------|
| `last_attacker` (default) | Attack whoever landed the most recent hit on the NPC.  Enemies fall back to the player when never hit; allies fall back to the weakest enemy. |
| `player` | Always attack the player (meaningful for enemies only). |
| `lowest_hp` | Attack the living opponent with the lowest current HP. |
| `random` | Attack a random living opponent. |

Without an `ai` block, enemies use `last_attacker` — in solo combat the
last attacker is always the player, so existing adventures behave
exactly as before.  Allies without an `ai` block attack the player's
most recent target, then their own last attacker, then the weakest
enemy (focus fire by default).

The engine tracks `last_attacker` (who last hit each combatant) and
`player_last_target` on `CombatState` to drive these rules.

### NPC fleeing

An enemy with `ai.flee_below_hp_pct` set flees on its turn when its
current HP percentage falls below the threshold: it is removed from
combat, its engine-owned `fled` entity state is set to `true` (the
adventure can react to it, e.g. with `entity:<id>.fled` conditions),
and if it was the last living enemy, combat ends.  Allies never flee —
they withdraw with the player when the player flees.

### Passive NPCs

An NPC with `ai.passive: true` joins combat (it can be targeted and
hurt) but never acts — for cowering civilians, pack animals, or
bystanders.  A declared `passive` entity state overrides the corpus
default at runtime, so adventure content can flip it either way (e.g. a
`set_entity_state` result that sets `passive: false` after the player
persuades an ally to fight).

### Death and victory in party combat

- An ally reduced to 0 HP dies (`alive: false`) and is removed from
  combat; a dead follower stops following.  Combat continues as long as
  the player lives.
- Combat ends in victory when no living enemies remain — including when
  an ally lands the killing blow, or when the last enemy flees.
- The player may only target enemies; allies cannot be attacked
  mid-combat (attacking a follower works as before: as a combat-entry
  trigger, making it hostile).
- When the player flees, combat ends for the whole party; followers
  move to the new room with the player as usual.

---

## Abilities in Combat

Named abilities — spells, class features, monster powers — are defined
in the top-level corpus `abilities` block (see
[schema/corpus.md](../schema/corpus.md#abilities)) and used in combat
by the player and by NPCs.  Each ability has a target kind (`self`,
`ally`, `enemy`), a per-combat use limit (`-1` = unlimited), and
exactly one effect:

- **`attack`** — an attack roll (the player's named ability modifier +
  proficiency, or the NPC's `atk` bonus) plus damage, with the usual
  crit, fumble, and damage-type mitigation rules.
- **`save`** — the target makes a saving throw (the player with normal
  proficiency rules; NPCs with `d20 + save_bonus`), taking half or no
  damage on success and possibly a status effect on failure.
- **`heal`** — a healing dice expression, clamped to the target's max
  HP.  Heal abilities target `self` or `ally` only.

### Player abilities

The character sheet's `abilities` list (see
[player-stats.md](player-stats.md)) names the abilities the player
knows.  In combat the player uses them via the `combat` action with
`combat_action: "use_ability"`, an `ability_id`, and a `target`
matching the ability's target kind (`"player"` for `self`, a party
combatant for `ally`, an enemy for `enemy`).  Uses are consumed even on
a missed attack roll, and exhausted abilities are rejected by the
engine.  The combat briefing lists the player's abilities with
remaining uses and effect summaries.

### NPC abilities

An NPC's `CombatBlock.abilities` lists the abilities it knows, in
preference order.  On its turn, the combat AI uses the **first** entry
that is usable — uses remaining, cooldown expired, and any
`ai.ability_rules` condition met — falling back to its normal attack(s)
when none qualifies.  `ai.ability_rules` provides per-ability
constraints: `cooldown_rounds` (unusable for N rounds after each use)
and `use_below_own_hp_pct` (only while the NPC is below the given HP
percentage).  NPC healers target the most-injured living same-side
combatant and skip healing entirely when everyone is healthy.
Cooldowns tick at the end of each round; uses and cooldowns are tracked
on `CombatState` and reset when combat ends.

---

## Display and Narration

### Combat Status Panel

Between combat turns, the console UI shows a status panel.  Combatants
are grouped under **Party** and **Enemies** headings; the current actor
is marked in the initiative order, and each row shows active status effects
(with remaining rounds) and status markers (`†` for the dead, `(fled)`
for fled enemies).  For enemies, the panel also lists damage
mitigations the party has already discovered by landing hits (derived
from the combat log, so nothing unlearned is revealed).  A footer line
summarises the player's resources: AC, equipped weapon, ability uses
left, and consumables.

The layout adapts to the terminal width: narrow terminals get a single
stacked column, wide ones (≥ 100 columns) a two-column Party-vs-Enemies
layout with a wider HP bar.

```
┌─ Combat: Round 2 ──────────────────────────────────────┐
│ Initiative: Spider → Player → Goblin                    │
│                                                         │
│ Party                                                   │
│ Player              HP ████████░░ 10/12 [poisoned 2]    │
│                                                         │
│ Enemies                                                 │
│ Spider              HP ██████████ 18/18                 │
│ Goblin              HP ████░░░░░░  5/10                 │
│ Wolf †              HP ░░░░░░░░░░  0/11                 │
│                                                         │
│ AC 14 · Longsword (1d8 slashing) · Items: Potion x2     │
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
      "current_hp": { "type": "number", "description": "Current hit points." }
    },
    "aggro": {
      "encounter_rules": [
        {
          "condition": { "require": "flag:spider_fled == true" },
          "result": {
            "start_combat": [],
            "narrative": "The spider, cornered, skitters forward to attack!"
          }
        }
      ]
    },
    "reactions": [
      {
        "id": "spider_attack_on_sight",
        "on": "interaction.used",
        "condition": { "require": "event:interaction_id == attack" },
        "effect": { "trigger_encounter": "self" }
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
    "proficiency_bonus": 2,
    "weapon_proficiencies": ["simple", "martial"]
  }
}
```

---

## Limitations

The combat system deliberately excludes:

- Movement / positioning / tactical maps
- Death saving throws (player 0 HP is death unless a rescue reaction intervenes)
- Reactions, opportunity attacks
- Bonus actions and the 5e action/movement split (one action per turn)

Gear and equipment are supported — see [gear.md](gear.md).  Status
effects, abilities, and saving throws are supported; see the sections
above.  The remaining exclusions may be added in future phases (see
`plan.md`).

> Note: the *engine* is already system-agnostic through the
> `ResolutionSystem` interface; the limitations above concern combat
> *features* (gear, status effects, spells, …), not system portability.  Player
> and NPC attacks are resolved by `ResolutionSystem.resolve_player_attack` and
> `ResolutionSystem.resolve_npc_attack`; the latter takes a `target_id`
> (player or NPC combatant) and reports `target_hp_delta` / `target_died`,
> leaving HP bookkeeping, death, and game-over decisions to the engine.
> On-hit effects are resolved as generic `CheckResolution` objects via the
> active resolution system's `roll_check` and `proficiency_bonus` hooks,
> and only fire against the player.
