# Equipment and Gear System

MGMAI supports equippable items through a **tag-based compatibility system**
modelled after tabletop RPG convention.  Instead of hard-coded slot types
("helmet slot", "ring slot"), items declare what they *are* via tags and
what they conflict with.  The engine validates conflicts; the LLM proposes
equip/unequip actions using common sense.

This mirrors how a human GM operates ("you can't wear two helmets") without
being rigid ("but this ethereal circlet floats above your head, so fine").

---

## Quickstart

To make an item equippable, add an `equip_block` to its entity definition:

```json
{
  "toenail_sword": {
    "type": "item",
    "name": "Toenail Sword",
    "description": "A giant toenail clipping, curved and razor-sharp...",
    "tags": ["weapon"],
    "equip_block": {
      "equip_tags": ["weapon"],
      "damage_expr": "1d6",
      "hit_bonus": 0
    }
  }
}
```

Every `item` entity must carry a `name` — this is the display string shown in
the `/inv` panel and in the LLM-facing `equipped_items` briefing, rather than
the raw snake_case entity ID. (Other entity types may omit `name`, in which
case the engine falls back to the entity ID.)

The player can then equip it via the LLM ("I draw the sword") and unequip it ("I sheathe it").  The engine handles adjusting inventory counts and moving IDs between `inventory` and `equipped`, computing effective stats, and validating conflicts.

---

## Data Model: `EquipBlock`

The `EquipBlock` object sits on item-type entities in `corpus.json`.  Items
without an `equip_block` cannot be equipped (keys, potions, quest items, etc.).

| Field               | Type        | Default  | Description |
|---------------------|-------------|----------|-------------|
| `equip_tags`        | `[string]`  | required | Category tags describing what this item "is" when worn/wielded.  The first element is the **slot** (controls default incompatibility and `max_equipped` caps); remaining elements are sub-tags.  Examples: `["headwear"]`, `["weapon", "two_handed"]`, `["armor", "heavy"]`, `["shield"]`, `["ring"]`. |
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

### Examples

**Longsword** — a standard one-handed weapon:
```json
{
  "equip_tags": ["weapon"],
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

**Greatsword** — two-handed:
```json
{
  "equip_tags": ["weapon", "two_handed", "heavy"],
  "incompatible_with": ["shield", "handwear"],
  "damage_expr": "2d6",
  "hit_bonus": 0
}
```

---

## Action System

Two new player actions control equipment:

### `equip` — Equip an item

```json
{
  "action_type": "equip",
  "target": "toenail_sword",
  "unequip_targets": [],
  "detail": "Player draws the toenail sword and holds it ready."
}
```

| Field              | Type     | Description |
|--------------------|----------|-------------|
| `target`           | `string` | Entity ID of the item to equip.  Must be in the player's `inventory` and must have an `equip_block`. |
| `unequip_targets`  | `[string]` | **Optional.** Items to unequip as part of the same action, so weapon swaps happen in one turn.  Each must be currently `equipped`.  The engine unequips them before checking conflicts for the new item. |

**Engine validation** (in order):
1. Each `unequip_target` must be in `player.equipped`.
2. `target` must be in `player.inventory`.
3. `target` must have a non-null `equip_block`.
4. Build the set of incompatible tags from `incompatible_with`, and the
   default self-conflict for items sharing the same slot tag.
5. Check each already-equipped item (post-unequip) — if any of its `equip_tags` overlaps the incompatible set, reject.
6. Check `max_equipped` for the slot tag group.
7. On success: decrement `target`'s count in `inventory` by 1 (remove the key
   if the count reaches 0) and append it to `equipped`; increment each
   `unequip_target`'s count in `inventory` by 1 and remove it from `equipped`.

### `unequip` — Unequip an item

```json
{
  "action_type": "unequip",
  "target": "toenail_sword",
  "detail": "Player sheathes the toenail sword."
}
```

| Field    | Type     | Description |
|----------|----------|-------------|
| `target` | `string` | Entity ID of the item to unequip.  Must be in `player.equipped`. |

On success: the item is removed from `equipped` and its count in `inventory`
is incremented by 1. Its stat modifiers, AC bonuses, and damage expression stop applying.

### Hard state changes

Both actions set `equipment_changed: true` on the `HardStateChanges` object,
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
- Proficiency bonus.
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
- Swapping weapons in combat is one action using `unequip_targets`.

If a conflict is detected, the **engine rejects the action** — the LLM must
explicitly unequip the conflicting item first.  This keeps narrative control
with the ruling model.

---

## Consumables

Items with a `consumable` block can be used (drunk, eaten, activated).
In combat this is the `use_item` combat action, which consumes the
player's action:

```json
{
  "health_potion": {
    "type": "item",
    "name": "Healing Potion",
    "description": "A small vial of red liquid.",
    "consumable": {
      "heal": "2d4+2",
      "cure_status_effects": ["poisoned"],
      "destroy": true
    }
  }
}
```

| Field             | Type      | Default | Description |
|-------------------|-----------|---------|-------------|
| `heal`            | `string`  | `""`    | Healing dice expression (e.g. `"2d4+2"`); clamped to max HP. Empty = no healing. |
| `cure_status_effects` | `[string]`| `[]`    | Status effects removed on use (e.g. `["poisoned"]`); works for any defined status effect, in or out of combat. |
| `destroy`         | `bool`    | `true`  | Consume one count of the item on use. |

The combat briefing lists the player's usable consumables under
`combat_state.usable_items` so the ruling LLM can map requests like "I
drink the potion" to `use_item`.

---

## Improvised Weapons

When a player grabs a non-equippable object and uses it as a weapon (chair
leg, broken bottle, heavy rock), the LLM can set an improvised weapon via
soft state:

```
SoftStatePatch
  field: "set_improvised_weapon"
  new_value: {
    "damage_expr": "1d4",
    "hit_bonus": 0,
    "description": "broken bottle",
    "clears_after_turn": true
  }
```

| Field               | Type    | Default  | Description |
|---------------------|---------|----------|-------------|
| `damage_expr`       | string  | `"1d6"`  | Damage dice. |
| `hit_bonus`         | int     | `0`      | Flat bonus to hit rolls. |
| `description`       | string  | `""`     | Narrative description ("chair leg", "broken bottle"). |
| `clears_after_turn` | bool    | `false`  | If true, the improvised weapon is automatically cleared at the start of the next player turn (one-shot use like a shattering bottle). |

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
(legacy) → unarmed.

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
        "equip_tags": ["weapon"],
        "effects_summary": "1d6 damage"
      }
    ],
    "effective_ac": 14,
    "effective_stats": { "STR": 11, "DEX": 10, "CON": 10 }
  }
}
```

| Field              | Description |
|--------------------|-------------|
| `equipped_items`   | List of currently equipped items with names, descriptions, tags, and a plain-English effects summary. |
| `effective_ac`     | Computed AC after applying the active system's equipment rules (e.g. 5e's `ac_override` and `ac_bonus` extras). |
| `effective_stats`  | Stat values after applying equipped items' `stat_effects` on top of the permanent baseline. |

The LLM prompts reference these fields so the ruling model knows what gear
the player is wearing and the prose model can describe equipment changes
narratively.

---

## Soft State: Appearance Notes

Narrative-only equipment that has no mechanical effect can be tracked via
soft state:

```
SoftStatePatch
  field: "appearance_note_add"
  new_value: "tattered cloak pulled from a goblin corpse"
  reason: "Player described wearing the goblin cloak as a trophy."
```

Appearance notes accumulate in `soft_state.appearance_notes` and are
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
