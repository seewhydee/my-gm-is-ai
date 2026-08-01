# Equipment and Gear System

MGMAI supports equippable items through a tag-based compatibility
system modelled after tabletop RPG conventions.  Instead of hard-coded
slot types ("helmet", "ring", etc.), items declare what they *are* via
tags and what they conflict with.

The player can equip/unequip gear items via natural language ("I draw
the sword", "I sheathe it", etc.).  The LLM interprets the command,
including what item ID the player refers to and whether the action
makes sense.  The engine handles adjusting inventory counts,
recomputing stats, validating conflicts, etc.

---

## Gear model

An equippable **gear** item has an `equip_block` in its entity
definition.  Items without an `equip_block` cannot be equipped (keys,
potions, quest items, etc.).

```json
{
  "dragonslaying_saber": {
    "type": "item",
    "name": "Dragonslaying Saber",
      "description": "A curved saber, exceptionally well-balanced, engraved with intricate runes.  It is said that the wielder of this blade can rule the martial world.",
    "tags": ["weapon"],
    "equip_block": {
      "equip_tags": ["weapon", "martial"],
      "damage_expr": "2d6",
      "damage_type": "piercing",
      "properties": ["finesse"],
      "hit_bonus": 0
    }
  }
}
```

| Field               | Type        | Default  | Description |
|---------------------|-------------|----------|-------------|
| `equip_tags`        | `[string]`  | required | Category tags describing what this item "is" when worn/wielded.  The first element is the **slot** (controls default incompatibility and `max_equipped` caps); remaining elements are sub-tags.  Examples: `["headwear"]`, `["weapon", "martial"]`, `["weapon", "two_handed"]`, `["armor", "heavy"]`, `["shield"]`, `["ring"]`.  For weapons, include a proficiency category tag (`"simple"` or `"martial"`) so the engine can gate the proficiency bonus (see [weapon proficiencies](player-stats.md#weapon-proficiencies-5e)). |
| `incompatible_with` | `[string]`  | `[]`     | Tags that conflict with this item.  When equipping, the engine checks all already-equipped items: if any of *their* `equip_tags` intersects this list, the equip is rejected.  Default (empty) means items conflict with anything sharing the same slot tag (the first element of `equip_tags`). |
| `stat_effects`      | `{string: {mode, value}}` | `{}` | Stat changes applied while equipped.  Keys are stat names (e.g. `"STR"`, `"DEX"`), values follow the `StatModifier` format: `{"mode": "delta"|"set", "value": int}`.  Set modifiers apply first (e.g. "belt of giant strength sets STR to 21"), then delta modifiers (e.g. "gauntlets give +1 STR"). |
| `max_equipped`      | `int|null`  | `1`      | How many items of this slot can be equipped simultaneously.  `1` = standard (one helmet, one armour).  `2` = rings (two ring slots).  `null` = unlimited (artifacts, auras).  The engine uses the **highest** value among all items sharing the same slot tag. |
| `damage_expr`       | `string`    | `"1d8"`  | Damage dice expression for this weapon (e.g. `"1d6"`, `"2d4"`, `"1d12"`).  Only meaningful when `"weapon"` is in `equip_tags`. |
| `hit_bonus`         | `int`       | `0`      | Flat bonus to hit rolls.  A "+1 sword" has `hit_bonus: 1`.  Stacks across equipped weapons. |
| `properties`        | `[string]`  | `[]`     | Weapon properties.  The `5e` system recognizes `"finesse"` (attack and damage use the better of STR or DEX) and `"ranged"` (attack and damage use DEX; no range mechanics exist). |
| `damage_type`       | `string`    | `""`     | Damage type of the weapon (e.g. `"slashing"`, `"fire"`) used for resistance/vulnerability/immunity.  Empty = untyped. |

System-specific fields are also accepted as extra top-level keys.  The `5e`
system recognises the following extras:

| Field          | Type       | Description |
|----------------|------------|-------------|
| `ac_override`  | `int|null` | If set, the player's AC becomes this value (e.g. heavy plate armour: 18).  Only the highest `ac_override` among equipped items takes effect. |
| `ac_bonus`     | `int`      | Added to the player's base AC.  Used for light/medium armour and shields.  Stacks across all equipped items. |

---

## SRD Data Pack

The full SRD 5.2.1 weapon and armor tables, plus the four tiers of
healing potion, come as a data pack (`mgmai/data/srd_5e/gear.json`).
At load time every pack item is minted as an item entity, so rooms,
inventories, and character sheets can reference pack IDs (`longsword`,
`plate_armor`, `shield`, `potion_of_healing`, etc.) without declaring
them:

```json
"inventory": { "longsword": 1, "potion_of_healing": 2 },
"equipped": ["longsword"]
```

A corpus item entity with the same ID replaces the pack entry wholesale
(no field-level merge); the validator warns when an adventure does
this.  Unknown item IDs remain load-time validation errors.

Pack conventions:

- **Weapons** — `damage_expr` is the one-handed die (versatile
  two-handed dice are not modeled); `properties` carries the SRD
  property list, of which the engine acts on `finesse` and `ranged`
  (thrown/ammunition/loading/reach are data only).  Each weapon also
  carries a `"simple"` or `"martial"` proficiency category in
  `equip_tags` (gates the proficiency bonus on attack rolls; see
  [weapon proficiencies](player-stats.md#weapon-proficiencies-5e)).
  Two-handed weapons use the `two_handed` equip tag and conflict with
  `shield`.
- **Armor** — light armor is `ac_bonus` (+1/+1/+2, exact for
  `N + DEX`); medium armor is `ac_bonus` (+2…+5, the SRD `max 2` Dex
  cap is **not** modeled); heavy armor is a flat `ac_override`
  (14/16/17/18); `shield` is `ac_bonus` +2.  Strength requirements and
  Stealth disadvantage are noted in descriptions for GM adjudication.
- **Potions** — `potion_of_healing` (2d4+2) through
  `potion_of_supreme_healing` (10d4+20) as items with a `drink` interaction.

### Examples

**Longsword** — a standard one-handed martial weapon:
```json
{
  "equip_tags": ["weapon", "martial"],
  "damage_expr": "1d8",
  "hit_bonus": 0
}
```

**Plate Armour** — heavy armour with AC override:
```json
{
  "equip_tags": ["armor", "heavy"],
  "ac_override": 18,
  "incompatible_with": ["light_armor"]
}
```

**Ring of Protection** — stacks with everything:
```json
{
  "equip_tags": ["ring"],
  "max_equipped": 2,
  "ac_bonus": 1
}
```

**Greatsword** — two-handed martial:
```json
{
  "equip_tags": ["weapon", "martial", "two_handed", "heavy"],
  "incompatible_with": ["shield", "handwear"],
  "damage_expr": "2d6",
  "hit_bonus": 0
}
```

---

## Action System

A single player action controls equipment:

### `gear` — Equip and/or unequip items

```json
{
  "action_type": "gear",
  "equip_targets": ["toenail_sword"],
  "unequip_targets": [],
  "detail": "Player draws the toenail sword and holds it ready."
}
```

| Field              | Type       | Description |
|--------------------|------------|-------------|
| `equip_targets`    | `[string]` | **Optional.** Entity IDs of items to equip.  Each must be in the player's `inventory` and must have an `equip_block`. |
| `unequip_targets`  | `[string]` | **Optional.** Items to unequip as part of the same action, so weapon swaps happen in one turn.  Each must be currently `equipped`.  The engine unequips them before checking conflicts for the new items. |

At least one of the two fields must be non-empty; duplicates within a field
are rejected.

**In combat**, a `gear` action is the player's **one free object
interaction per turn** (SRD 5.2.1): it consumes
`player_budget.free_interaction_used` and the turn continues for the
round's real action.  A second object interaction in the same turn (a
second swap, or a swap after another free interaction) costs the action
(Utilize) — and is rejected outright if no budget remains.  A weapon can
also be **equipped or unequipped as part of an attack** via
`CombatAction.equip_target` / `unequip_target` (at most one of the two):
the swap is validated through the same code path as `gear`, applied to
the player's gear immediately before the attack roll, and the drawn
weapon is the one used for the attack.  This costs the free interaction,
not the action, and is a single ruling (no chained action needed).
Outside combat the action is unchanged (full turn).

**Dual wielding.**  The `weapon` slot is a two-item slot: the SRD pack's
weapons carry `max_equipped: 2`, so two weapons can be equipped
simultaneously (one per hand; a `max_equipped: 1` item still blocks a
second of its own slot, e.g. armour).  Equipping a third weapon is
rejected.  Two *Light* weapons in hand enable the **off-hand attack**
(see [combat.md](combat.md) — *Off-hand attack (Light property)*).
Two-handed weapons are incompatible with any second weapon (and with a
shield), regardless of equip order.

**Engine validation** (in order):
1. Each `unequip_target` must be in `player.equipped`.
2. For each `equip_target`, in order:
   a. It must be in `player.inventory`.
   b. It must have a non-null `equip_block`.
   c. Build the set of incompatible tags from `incompatible_with`; when
      that is empty, the default self-conflict applies only for a
      *single-item* slot (the slot group's `max_equipped` resolves to 1) —
      a multi-item slot (e.g. `weapon` with `max_equipped: 2`) does not
      self-conflict, the cap enforces the limit instead.
   d. Check each already-equipped item (post-unequip, plus any items already
      equipped by this same action) — if any of its `equip_tags` overlaps
      the incompatible set, reject; also reject when the equipped item's
      own explicit `incompatible_with` covers the new item's tags (the
      check is symmetric).
   e. Check `max_equipped` for the slot tag group.
3. On success: decrement each `equip_target`'s count in `inventory` by 1
   (remove the key if the count reaches 0) and append it to `equipped`;
   increment each `unequip_target`'s count in `inventory` by 1 and remove it
   from `equipped`.  Unequipped items' stat modifiers, AC bonuses, and damage
   expressions stop applying.  The action is atomic: any failure rejects the
   whole change.

### Hard state changes

The action sets `equipment_changed: true` on the `HardStateChanges` object,
signalling downstream systems (combat, context assembler) to recompute
effective stats and AC.

---

## Mechanical Effects

### Effective stats

Equipment stat modifiers are **never written** into `hard.player.stats`.
Instead, `compute_effective_stats(player, corpus)` builds a transient view:

1. Start from `hard.player.stats` (the permanent mutable baseline — includes
   all `alter_stat` effects from interactions, dialogue, curses, etc.).
2. For each equipped item, apply its `stat_effects`:
   - `mode: "set"` modifiers first (e.g. "STR = 21" from a belt).
   - `mode: "delta"` modifiers second (e.g. "+1 STR" from gauntlets).
3. Return a transient dict.  The baseline is never touched.

The context assembler includes effective stats in every `GMBriefing`, so both
LLMs see post-gear values.

### Armour Class

`compute_player_ac(player, corpus)` computes AC in three steps:

1. **Base AC** — `hard.player.ac` if explicitly set (e.g. from a character
   sheet or magical effect), otherwise `10 + DEX_modifier`.
2. **Override** — the highest `ac_override` among equipped items (e.g. heavy
   armour) replaces the base.
3. **Bonuses** — all `ac_bonus` values from equipped items are added (shields,
   rings of protection, etc. stack).

The combat engine uses this AC for NPC hit calculations.

### Damage and attack bonus

Attack resolution is delegated to the active `ResolutionSystem`
(`resolve_player_attack` / `resolve_npc_attack`).  The engine no longer
computes `atk_bonus` itself.

`FiveESystem.compute_player_damage_expr(hard, corpus, soft)` follows this
priority:

1. **Equipped weapon** — the first equipped item with `"weapon"` in its
   `equip_tags` provides its `damage_expr`.
2. **Improvised weapon** — if `soft.improvised_weapon` is set, its
   `damage_expr` is used (superseded by a proper equipped weapon).
3. **Legacy inventory** — any item tagged `"weapon"` in `inventory` (backward
   compatible fallback) → `"1d8"`.
4. **Unarmed** — `"1d6"`.

`FiveESystem.compute_player_attack_bonus(hard, corpus)` sums:
- The weapon's attack ability modifier: STR by default, DEX for `ranged`
  weapons, the better of STR or DEX for `finesse` weapons.
- Proficiency bonus — **only when the player is proficient with the
  weapon** (via `weapon_proficiencies`; see
  [player stats](player-stats.md#weapon-proficiencies-5e)). A
  non-proficient weapon is still usable without it. Unarmed strikes are
  always proficient.
- `hit_bonus` from all equipped weapons.

---

## Conflict Resolution

When the player attempts to equip an item, the engine validates tag conflicts
before applying the change.

### How conflicts work

1. Build the **incompatible set**:
   - Start with `incompatible_with` from the item's `EquipBlock`.
   - If `incompatible_with` is empty, add the item's own slot tag
     (the first element of `equip_tags`) — this prevents equipping two
     items of the same category.  For items tagged `"two_handed"`, the
     author should list `"shield"` and `"handwear"` in
     `incompatible_with`.
2. For each already-equipped item, check if its `equip_tags` intersect the
   incompatible set.  If yes → **reject**.
3. Check `max_equipped`: count how many items share the new item's slot
   tag.  If count ≥ limit → **reject**.

### Rule of thumb for LLM

The LLM prompt instructs the ruling model to use common sense:
- One helmet, one suit of armour, one pair of gauntlets, one pair of boots.
- A couple of rings (max_equipped: 2).
- One weapon per hand, or one two-handed weapon.
- Doffing armour during combat is never allowed (takes minutes).
- Swapping weapons in combat is one `gear` action using both `equip_targets`
  and `unequip_targets`.

If a conflict is detected, the **engine rejects the action** — the LLM must
explicitly unequip the conflicting item first.  This keeps narrative control
with the ruling model.

---

## Consumables

Items with an `interactions` list that carry mechanical effects can be
used in or out of combat via the `interact` action targeting the item
itself.  For example, a potion defines a `drink` interaction whose
`Result` heals the player and consumes one count:

```json
{
  "health_potion": {
    "type": "item",
    "name": "Healing Potion",
    "description": "A small vial of red liquid.",
    "interactions": [
      {
        "id": "drink",
        "description": "Drink the potion to restore 2d4+2 hit points.",
        "result": {
          "player_heal": "2d4+2",
          "cure_status_effects": ["poisoned"],
          "remove_item_count": {"health_potion": 1}
        }
      }
    ]
  }
}
```

The `Result` carries the mechanical primitives:

| Field             | Type      | Description |
|-------------------|-----------|-------------|
| `player_heal`     | `string`  | Healing dice expression (e.g. `"2d4+2"`); clamped to max HP. |
| `cure_status_effects` | `[string]`| Status effects removed on use (e.g. `["poisoned"]`). |
| `remove_item_count` | `object` | Item IDs → counts consumed on use; omit for multi-use items. |

The player and combat briefings list usable inventory items under
`player_state.usable_items` / `combat_state.usable_items` so the ruling
LLM can map requests like "I drink the potion" to `interact`/`drink`
targeting the item's ID.

Other item interaction IDs (`read`, `activate`, `pour`, etc.) work
identically — each is an `interact`/`<id>` action on the item.

---

## Improvised Weapons

When a player grabs a non-equippable object and uses it as a weapon (chair
leg, broken bottle, heavy rock), the LLM can set an improvised weapon via
soft state:

```
SoftStatePatch
  field: "set_improvised_weapon"
  new_value: {
    "keyword": "light",
    "damage_type": "piercing",
    "description": "broken bottle",
    "clears_after_turn": true
  }
```

The LLM picks a size `keyword` and (optionally) a `damage_type`; the
resolution system maps the keyword to concrete stats when the patch is
applied (5e: `light` → 1d4, `standard` → 1d6, `heavy` → 1d8).

| Field               | Type    | Default         | Description |
|---------------------|---------|-----------------|-------------|
| `keyword`           | string  | (required)      | Size class: `light`, `standard`, or `heavy` (system-defined). |
| `damage_type`       | string  | `"bludgeoning"` | One of the system's improvised damage types (5e: `bludgeoning`, `piercing`, `slashing`). |
| `description`       | string  | `""`            | Narrative description ("chair leg", "broken bottle"). |
| `source_item`       | string  | (omitted)       | Name of a carried soft item the weapon is made from. It stays in `soft_inventory` while wielded; when a `clears_after_turn` weapon expires, the item is consumed. If the player drops or gives the item away (a `transfer`), the weapon is cleared automatically. |
| `clears_after_turn` | bool    | `false`         | If true, the improvised weapon is automatically cleared at the start of the next player turn (one-shot use like a shattering bottle). |

Clear it with `new_value: null`:

```
SoftStatePatch
  field: "set_improvised_weapon"
  new_value: null
  reason: "The chair leg splinters apart"
```

Improvised weapons take **lower priority** than properly equipped weapons
but **higher priority** than unarmed combat.  The combat engine checks them
in this order: equipped weapon → improvised weapon → inventory weapon tag
(legacy) → unarmed.  Improvised attacks add the weapon's `hit_bonus` (if
any) but never a proficiency bonus, and the weapon's `damage_type`
participates in resistance/vulnerability/immunity as usual.

---

## Condition Domain

The condition engine supports an `equipped:` domain for gating adventure
content on what the player is wearing:

| Condition                          | True when |
|------------------------------------|-----------|
| `equipped:toenail_sword`           | The item entity ID `toenail_sword` is in `player.equipped`. |
| `equipped:weapon`                  | Any equipped item has `"weapon"` in its `tags`. |

This enables encounter rules, dialogue branches, and mechanics gated on
equipment:

```json
{
  "condition": { "require": "equipped:ring_of_seeing" },
  "narrative": "The ring glows faintly, revealing a hidden inscription on the wall."
}
```

### Backward compatibility

The existing `tag:` domain now scans **both** `player.inventory` AND
`player.equipped`.  This means a `tag:weapon` condition in an existing
adventure works whether the sword is in the player's pack or in their hand.

---

## Effective Stats in the Briefing

The context assembler includes gear-aware information in every `GMBriefing`,
visible in `player_state`:

```json
{
  "player_state": {
    "hard_inventory": {"iron_sword": 1, "health_potion": 1},
    "equipped_items": [
      {
        "id": "toenail_sword",
        "name": "Giant Toenail Clipping",
        "description": "A giant toenail clipping, curved and razor-sharp...",
        "equip_tags": ["weapon", "martial"],
        "effects_summary": "1d6 damage"
      }
    ],
    "player_stats": {
      "STR": { "value": 11, "modifier": 0 },
      "DEX": { "value": 10, "modifier": 0 },
      "CON": { "value": 10, "modifier": 0 }
    },
    "combat_stats": { "current_hp": 12, "max_hp": 12, "ac": 14, "...": "..." }
  }
}
```

| Field              | Description |
|--------------------|-------------|
| `equipped_items`   | List of currently equipped items with names, descriptions, tags, and a plain-English effects summary. |
| `player_stats`     | Effective stat values — permanent baseline plus equipped items' `stat_effects` — each with its computed modifier. |
| `combat_stats.ac`  | Computed AC after applying the active system's equipment rules (e.g. 5e's `ac_override` and `ac_bonus` extras). |

The LLM prompts reference these fields so the ruling model knows what gear
the player is wearing and the prose model can describe equipment changes
narratively.

---

## Soft State: Appearance Notes

Narrative-only equipment that has no mechanical effect can be tracked via
an `entity_note` on the player entity:

```
SoftStateNote
  field: "entity_note"
  entity_id: "player"
  new_value: "Wearing a tattered cloak pulled from a goblin corpse."
  reason: "Player described wearing the goblin cloak as a trophy."
```

Notes on the player entity follow the player across rooms and are
displayed in the GMBriefing's player state section so both LLMs can
reference them.  They carry no mechanical weight.

---

## Save and Load

The `equipped` field is a `list[str]` on `PlayerState` in `HardGameState`.
`inventory` is a `dict[str, int]` mapping item IDs to counts.
It is serialised and deserialised alongside `equipped`:

```json
{
  "player": {
    "location": "bag_floor",
    "inventory": {"health_potion": 1, "torch": 1},
    "equipped": ["toenail_sword"]
  }
}
```

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
