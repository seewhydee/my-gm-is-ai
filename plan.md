# Plan: Abstract `EquipBlock` to system-agnostic core + 5e extras

## Rationale

`EquipBlock` (corpus.md:932) bakes D&D-5e-specific combat mechanics directly
into what should be a system-agnostic schema.  This violates the design
principle already exemplified by `StatCheck` (corpus.md:152–190), which cleanly
separates agnostic core fields (`stat`, `target`, `modifier`, `repeatable`) from
system-specific extras (`advantage`, `disadvantage`) via `ConfigDict(extra="allow")`
and documents them in a "The 5e system uses..." subsection.

### What StatCheck does right

| Element | Design |
|---------|--------|
| Core fields | `type`, `stat`, `target`, `modifier`, `repeatable`, `note` — works for any RPG |
| Extras | `advantage`, `disadvantage` — 5e-specific, stored via `extra="allow"` on the Pydantic model |
| Resolution | The `stats.system` string (`"5e"`) tells the engine which system interprets the extras |
| Documentation | Core table first, then a "The 5e system uses..." subsection |

### What EquipBlock does wrong

| Field | Problem |
|-------|---------|
| `ac_override` | D&D-specific.  Not all RPGs use Armor Class.  Zero live JSON usage. |
| `ac_bonus` | Same D&D coupling.  Zero live JSON usage. |
| `two_handed` | D&D-specific mechanic.  Hard-coded in the agnostic `resolver.py` (line 1665), not in the 5e system module. |
| `attack_bonus` | Concept is agnostic but name is D&D-flavored. |
| No `extra="allow"` | A non-5e system cannot add its own equipment fields. |

Additionally, the agnostic `resolver.py` hard-codes D&D logic for `two_handed`:
```python
if eb.two_handed:
    incompatible.update(["handwear", "weapon", "shield"])
```
This should live in the 5e resolution system, not in the shared engine.

## Design decision: core agnostic fields + system extras

Following the StatCheck pattern, we:

1. **Shrink `EquipBlock`** to only genuinely agnostic fields:
   `equip_tags`, `incompatible_with`, `equip_effects`, `max_equipped`,
   `damage_expr`, `hit_bonus` (renamed from `attack_bonus`).

2. **Add `ConfigDict(extra="allow")`** so 5e (and future systems) can
   supply extra top-level keys (`ac_override`, `ac_bonus`, `two_handed`)
   that their resolution system knows how to interpret.

3. **Add `get_equip_incompatibilities(equip_block)` to the resolution
   system interface.**  The default returns an empty set.  5e adds
   `{"handwear", "weapon", "shield"}` when `two_handed` is true.  The
   agnostic resolver calls this instead of hard-coding D&D tags.

4. **Rename `attack_bonus` → `hit_bonus`** for system neutrality
   (matching how `StatModifier` already avoids D&D naming).  Apply the
   same rename to `ImprovisedWeapon` in `soft_state.py`.

5. **Leave `damage_expr` in the core** — dice expressions like `"1d8"` are
   universal in dice-based RPGs.  Systems that don't use dice damage
   simply won't set this field.

### End-state EquipBlock

```python
class EquipBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Core agnostic fields
    equip_tags: list[str]
    incompatible_with: list[str] = Field(default_factory=list)
    equip_effects: Dict[str, StatModifier] = Field(default_factory=dict)
    max_equipped: int | None = 1
    damage_expr: str = "1d8"
    hit_bonus: int = 0
```

Fields `ac_override`, `ac_bonus`, and `two_handed` are removed from the
core model.  When using the 5e system, corpus authors write them as extra
top-level keys in the JSON — exactly as they do today with `advantage` on
a stat check.  The 5e engine reads them via `getattr()`.

### End-state ResolutionSystem interface

```python
class ResolutionSystem(ABC):
    ...

    def get_equip_incompatibilities(self, equip_block: EquipBlock) -> set[str]:
        """Return extra tags that this equipment conflicts with.
        
        Called during equip validation.  Default: no system-specific
        incompatibilities.  Override per system (e.g. 5e adds handwear/
        weapon/shield for two_handed items).
        """
        return set()
```

## Schema changes (`schema/corpus.md`)

### 1. Restructure the Equipment subsection (lines 932–963)

Split into two parts:

**Part A — Core agnostic fields** (main table):
```
| Field               | Type       | Required | Description |
|---------------------|------------|----------|-------------|
| `equip_tags`        | `[string]` | yes      | Category tags. |
| `incompatible_with` | `[string]` | no       | Tags that conflict. |
| `equip_effects`     | `{string: {mode, value}}` | no | Stat changes applied while equipped. |
| `max_equipped`      | `int|null` | no       | Max items of primary tag (default 1). |
| `damage_expr`       | `string`   | no       | Damage dice expression when wielded (e.g. `"1d6"`). |
| `hit_bonus`         | `int`      | no       | Flat bonus to hit rolls (default 0). |
```

Update the JSON example to match (remove `ac_override`, `ac_bonus`,
`two_handed`, rename `attack_bonus` → `hit_bonus`).

**Part B — 5e-specific extras** (new subsection, same pattern as
stat_check line 180):

```
Aside from the above fields, system-specific fields are accepted as
extra top-level keys.  Various systems can implement their own
equipment rules and define their own extra fields.

The `5e` system uses the following additional fields:

| Field          | Type       | Description |
|----------------|------------|-------------|
| `ac_override`  | `int|null` | If set, player AC becomes this value (e.g. plate: 18).  Highest override among equipped items takes effect. |
| `ac_bonus`     | `int`      | Added to player's base AC (default 0).  Stacks across equipped items. |
| `two_handed`   | `bool`     | If true, incompatible with `"handwear"`, `"weapon"`, `"shield"` (default false). |
```

### 2. Update gear doc (`doc/gear.md`)

- Rename `attack_bonus` → `hit_bonus` in all field tables, examples, and prose.
- Move `ac_override`, `ac_bonus`, `two_handed` into a "5e system extras"
  subsection (or note them as 5e-specific in the table).
- Update JSON examples to use `hit_bonus` instead of `attack_bonus`.

### 3. Update actions doc (`schema/actions.md`)

- Any mention of `two_handed` in equip resolution docs → note it as a
  5e-specific extra handled by the system, not the core resolver.

## Model changes (`mgmai/models/corpus.py`)

### 4. `EquipBlock` — remove 5e fields, add extras, rename

```python
class EquipBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    equip_tags: list[str]
    incompatible_with: list[str] = Field(default_factory=list)
    equip_effects: Dict[str, StatModifier] = Field(default_factory=dict)
    max_equipped: int | None = 1
    damage_expr: str = "1d8"
    hit_bonus: int = 0
```

Remove `ac_override`, `ac_bonus`, `two_handed`.  Rename `attack_bonus` →
`hit_bonus`.  Add `ConfigDict(extra="allow")`.

### 5. `EquipBlock.effects_summary()` — adapt to extra fields

The method currently reads `self.ac_override`, `self.ac_bonus`,
`self.attack_bonus` directly.  Change to read from extras via `getattr`:

```python
def effects_summary(self) -> str:
    parts: list[str] = []
    for stat_key, mod in self.equip_effects.items():
        if mod.mode == "set":
            parts.append(f"{stat_key} = {mod.value}")
        else:
            sign = "+" if mod.value >= 0 else ""
            parts.append(f"{stat_key} {sign}{mod.value}")
    # 5e extras (safe via getattr; absent in non-5e contexts)
    ac_override = getattr(self, "ac_override", None)
    if ac_override is not None:
        parts.append(f"AC {ac_override}")
    ac_bonus = getattr(self, "ac_bonus", 0)
    if ac_bonus != 0:
        parts.append(f"AC {'+' if ac_bonus >= 0 else ''}{ac_bonus}")
    if "weapon" in self.equip_tags:
        parts.append(f"{self.damage_expr} damage")
        if self.hit_bonus != 0:
            parts.append(
                f"{'+' if self.hit_bonus >= 0 else ''}{self.hit_bonus} to hit"
            )
    return ", ".join(parts)
```

### 6. `ImprovisedWeapon` (soft_state.py) — rename

```python
class ImprovisedWeapon(BaseModel):
    damage_expr: str = "1d6"
    hit_bonus: int = 0        # was attack_bonus
    description: str = ""
    clears_after_turn: bool = False
```

## System interface changes

### 7. Add `get_equip_incompatibilities()` to base class

In `mgmai/engine/systems/base.py` (or wherever `ResolutionSystem` is defined):

```python
def get_equip_incompatibilities(self, equip_block: EquipBlock) -> set[str]:
    """Return system-specific incompatibility tags for this equip_block."""
    return set()
```

### 8. `FiveESystem.get_equip_incompatibilities()` — implement

In `mgmai/engine/systems/five_e.py`:

```python
def get_equip_incompatibilities(self, equip_block: EquipBlock) -> set[str]:
    """5e: two_handed → incompatible with handwear, weapon, shield."""
    two_handed = getattr(equip_block, "two_handed", False)
    if two_handed:
        return {"handwear", "weapon", "shield"}
    return set()
```

## Engine changes

### 9. `resolver.py` — remove hard-coded `two_handed`, delegate to system

In `_resolve_equip()` (around line 1665):

```python
# Before:
# if eb.two_handed:
#     incompatible.update(["handwear", "weapon", "shield"])

# After:
incompatible.update(self._system.get_equip_incompatibilities(eb))
```

### 10. `five_e.py` — read AC extras via `getattr`

In `compute_player_ac()` (lines 474–488):

```python
# Before (line 479):
# if entity.equip_block.ac_override is not None:
# After:
ac_override_val = getattr(entity.equip_block, "ac_override", None)
if ac_override_val is not None:
    ...

# Before (line 488):
# effective_ac += entity.equip_block.ac_bonus
# After:
effective_ac += getattr(entity.equip_block, "ac_bonus", 0)
```

### 11. `five_e.py` — rename `attack_bonus` → `hit_bonus`

In `compute_player_attack_bonus()` (line 171):

```python
# Before:
# weapon_bonus += entity.equip_block.attack_bonus
# After:
weapon_bonus += entity.equip_block.hit_bonus
```

In `compute_player_damage_expr()` (line 203):

```python
# Before:
# base = soft.improvised_weapon.damage_expr
# After (no change — damage_expr is unchanged):
base = soft.improvised_weapon.damage_expr
```

### 12. `five_e.py` — compute NPC stat block extras

If `CombatBlock` has any similar issues (it's documented as "5e-flavoured
but corpus-agnostic" in the code comment at line 496), audit it but do
not change it as part of this plan — it's already explicitly scoped to
combat-capable NPCs and does not pollute the broader entity schema.

### 13. Assembler / briefing — cosmetic renames

In `assembler.py`: if `effects_summary()` already handles the fields, no
further change needed.  The brevity of `hit_bonus` vs `attack_bonus` is
handled inside `effects_summary()`.  Search for any direct `attack_bonus`
references in briefing code and rename.

## Test changes

### 14. `tests/test_equip_gear.py` — update EquipBlock construction

- Remove `ac_override=`, `ac_bonus=`, `two_handed=` from `EquipBlock()`
  constructor calls.  If testing 5e-specific behavior, pass them as extra
  kwargs (Pydantic `extra="allow"` will accept them).
- Rename `attack_bonus=` → `hit_bonus=` in all `EquipBlock()` calls.
- Update assertions:
  - `assert eb.ac_override is None` → remove (field no longer exists).
    If testing 5e extras, use `getattr(eb, "ac_override", None)`.
  - `assert eb.ac_bonus == 0` → remove (field no longer exists).
  - `assert eb.two_handed == False` → remove (field no longer exists).
  - `assert eb.attack_bonus == 0` → `assert eb.hit_bonus == 0`.
- Monkey-patched fields in tests: rename `ac_bonus`, `attack_bonus`
  assignments.

### 15. `tests/test_systems.py` — update AC computation tests

- `_corpus_with_item(ac_override=...)` → supply as extra field (still
  works with `extra="allow"`).
- Update assertions that reference `attack_bonus`.

### 16. `tests/test_commands.py` — update `/inv` display tests

- Rename monkey-patched `attack_bonus` → `hit_bonus`.
- Rename monkey-patched `ac_bonus` (still works via `getattr`).

### 17. `tests/test_combat.py` — update attack/damage tests

- `test_attack_bonus` → rename to `test_hit_bonus`.
- Update `compute_player_attack_bonus` calls and assertions.

### 18. `tests/fixtures/corpus.json` — rename field

- `"attack_bonus": 0` → `"hit_bonus": 0` (line 699).

### 19. `adventures/bag-of-holding/corpus.json` — rename field

- `"attack_bonus": 0` → `"hit_bonus": 0` (line 726).

### 20. Add test for system-agnostic extras

```python
def test_equip_block_extra_fields():
    """5e extras are accepted via extra='allow' but not core fields."""
    eb = EquipBlock(
        equip_tags=["armor", "heavy"],
        ac_override=18,
        ac_bonus=0,
        two_handed=False,
    )
    # Core fields are directly accessible
    assert eb.equip_tags == ["armor", "heavy"]
    # Extras accessible via getattr
    assert getattr(eb, "ac_override") == 18
    assert getattr(eb, "ac_bonus") == 0
    assert getattr(eb, "two_handed") == False
    # Extras absent from non-5e items
    simple = EquipBlock(equip_tags=["ring"])
    assert getattr(simple, "ac_override", None) is None
```

### 21. Add test for `get_equip_incompatibilities()`

```python
def test_five_e_two_handed_incompatibilities():
    """Two-handed weapons add implicit incompatibilities in 5e."""
    from mgmai.engine.systems.five_e import FiveESystem
    sys = FiveESystem()
    eb = EquipBlock(equip_tags=["weapon", "heavy"], two_handed=True)
    assert sys.get_equip_incompatibilities(eb) == {"handwear", "weapon", "shield"}

    eb_normal = EquipBlock(equip_tags=["weapon"])
    assert sys.get_equip_incompatibilities(eb_normal) == set()
```

## What does NOT change

- **JSON corpus files** — no `ac_override`, `ac_bonus`, or `two_handed`
  exist in any live JSON.  Only `attack_bonus` (1 occurrence each in
  `bag-of-holding/corpus.json` and `tests/fixtures/corpus.json`) is
  renamed to `hit_bonus`.
- **`CombatBlock`** — stays as-is.  It's explicitly scoped to
  combat-capable NPCs, already documented as "5e-flavoured", and doesn't
  pollute the broader entity/item schema.
- **`equip_effects`** — unchanged.  The `StatModifier` format
  (`{mode, value}`) is already well-abstracted.
- **`incompatible_with` default behavior** — unchanged.  Empty list still
  means "conflicts with items sharing primary tag."
- **`max_equipped` semantics** — unchanged.
- **`damage_expr`** — unchanged.
- **`ImprovisedWeapon.clears_after_turn`** — unchanged.
- **Save/load format** — no change to `player.equipped` or `player.inventory`.

## File-change inventory

| File | Change |
|------|--------|
| `schema/corpus.md` | Restructure Equipment subsection: core agnostic table + 5e extras subsection; rename `attack_bonus` → `hit_bonus`; remove `ac_override`/`ac_bonus`/`two_handed` from core table, add to 5e subsection |
| `schema/soft-state.md` | Rename `attack_bonus` → `hit_bonus` in `ImprovisedWeapon` table |
| `schema/actions.md` | Update equip resolution docs to note system delegation for `two_handed` |
| `doc/gear.md` | Rename `attack_bonus` → `hit_bonus` throughout; move `ac_override`/`ac_bonus`/`two_handed` to 5e extras subsection; update JSON examples |
| `mgmai/models/corpus.py` | `EquipBlock`: add `ConfigDict(extra="allow")`, remove `ac_override`/`ac_bonus`/`two_handed`, rename `attack_bonus` → `hit_bonus`; update `effects_summary()` to use `getattr` for 5e extras |
| `mgmai/models/soft_state.py` | `ImprovisedWeapon`: rename `attack_bonus` → `hit_bonus` |
| `mgmai/engine/systems/base.py` | Add `get_equip_incompatibilities()` to `ResolutionSystem` (default returns `set()`) |
| `mgmai/engine/systems/five_e.py` | Implement `get_equip_incompatibilities()`; read AC extras via `getattr` in `compute_player_ac()`; rename `attack_bonus` → `hit_bonus` in `compute_player_attack_bonus()` and related methods |
| `mgmai/engine/resolver.py` | Replace hard-coded `two_handed` logic with `self._system.get_equip_incompatibilities(eb)` |
| `mgmai/context/assembler.py` | Rename any direct `attack_bonus` references (if any) |
| `adventures/bag-of-holding/corpus.json` | `"attack_bonus"` → `"hit_bonus"` |
| `tests/fixtures/corpus.json` | `"attack_bonus"` → `"hit_bonus"` |
| `tests/test_equip_gear.py` | Update EquipBlock construction, assertions, monkey-patches |
| `tests/test_systems.py` | Update AC computation tests, rename `attack_bonus` references |
| `tests/test_commands.py` | Rename monkey-patched fields |
| `tests/test_combat.py` | Rename test, update assertions |
| New test (any file) | Tests for `extra="allow"` behavior and `get_equip_incompatibilities()` |

## Task ordering

1. **Model** — `mgmai/models/corpus.py`:
   - Add `ConfigDict(extra="allow")` to `EquipBlock`
   - Remove `ac_override`, `ac_bonus`, `two_handed`
   - Rename `attack_bonus` → `hit_bonus`
   - Update `effects_summary()` to use `getattr` for 5e extras
2. **Model** — `mgmai/models/soft_state.py`:
   - Rename `attack_bonus` → `hit_bonus` on `ImprovisedWeapon`
3. **System interface** — `mgmai/engine/systems/base.py`:
   - Add `get_equip_incompatibilities()` default method
4. **5e system** — `mgmai/engine/systems/five_e.py`:
   - Implement `get_equip_incompatibilities()`
   - Update `compute_player_ac()` to use `getattr` for extras
   - Rename `attack_bonus` → `hit_bonus` in `compute_player_attack_bonus()`
5. **Resolver** — `mgmai/engine/resolver.py`:
   - Replace `two_handed` hard-code with system call
6. **JSON data** — rename `attack_bonus` → `hit_bonus` in:
   - `adventures/bag-of-holding/corpus.json`
   - `tests/fixtures/corpus.json`
7. **Tests** — update all references (6 test files)
8. **Add new tests** — `extra="allow"` and `get_equip_incompatibilities()`
9. **Schema/docs** — `schema/corpus.md`, `schema/soft-state.md`,
   `schema/actions.md`, `doc/gear.md`
10. `pytest` green
11. `rg 'attack_bonus' mgmai/ tests/ schema/ doc/ --type py --type md --type json` clean
    (except historical references in prose like doc/gear.md and doc/combat.md
    that predate this change — update those too)
