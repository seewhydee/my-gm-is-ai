# Plan: Unify on-hit effects into CheckResolution

## Overview

`OnHitEffect` and `CheckResolution` are two ways to express the same
shape — "after X happens, roll a check, then apply an effect based on
the outcome." This plan replaces the combat-specific `OnHitEffect` with
the general-purpose `CheckResolution`, so the engine maintains one
resolution path instead of two, and on-hit effects gain the full
expressiveness of `Result` (flags, stat changes, narrative branching,
nesting).

Three supporting changes make the merge behaviour-preserving and sound:

1. **`half(expr)` dice notation** — recovers the `on_save: "half"`
   mechanic that `CheckResolution` cannot otherwise express.
2. **An optional proficiency marker on `StatCheck`** — preserves the
   save-proficiency bonus that today's bespoke on-hit path applies, and
   fixes a pre-existing inconsistency where every *non*-combat save
   authored as a `StatCheck` silently lost proficiency.
3. **A combat-safe effect subset** — constrains what an on-hit `Result`
   may do, so the generic resolution path can run inside the combat loop
   without producing nonsensical mid-combat outcomes (relocating the
   player, starting a new combat, etc.).

On-hit resolution moves out of the 5e system and into the combat
manager, where the `HardStateChanges` accumulator already lives.

## Background and motivation

`OnHitEffect` (`corpus.py:603`) is a four-field shorthand for "NPC hits
→ player rolls a saving throw → take modified damage." `CheckResolution`
(`corpus.py:230`) is the general mechanism for "after a result, roll a
check and branch," carried by `Result.then_check` and resolved by
`_resolve_checkable` (`resolver.py:1455`).

The duplication has two costs:

- **Expressiveness.** `OnHitEffect` cannot set flags, alter stats,
  branch narratively, or nest. An author who wants a spider bite that
  also sets `poisoned`, or a paralyzing strike that forces a second
  save, has no path.
- **Two codepaths.** The engine keeps `_resolve_on_hit_effects`
  (`five_e.py:217`) and `_resolve_checkable` (`resolver.py:1455`).

A naive merge loses two things, which the supporting changes recover:

- `on_save: "half"` needs a way to halve a rolled damage expression —
  recovered by `half(expr)`.
- Today's on-hit saves go through `resolve_save` (`five_e.py:513`),
  which adds the player's save-proficiency bonus via
  `compute_save_modifier` (`five_e.py:547`). `CheckResolution` resolves
  through `roll_check` (`five_e.py:76`), which does **not** apply
  proficiency. Without a proficiency marker, every proficient saving
  throw would be silently nerfed. Worse, this gap already exists for
  *all* non-combat saves authored as `StatCheck` (traps, traversal
  saves, encounter saves) — they never got proficiency. The marker
  fixes both.

## Design

### Mapping OnHitEffect to CheckResolution

With `half(expr)` available, every `OnHitEffect` becomes a
`CheckResolution` whose `check` is the saving throw (`StatCheck` with
`proficiency: "save"`) and whose `success`/`failure` branches carry the
damage:

| `on_save` | `success` Result (save made) | `failure` Result (save failed) |
|---|---|---|
| `"half"` | `player_damage: "half(1d8)"` | `player_damage: "1d8"` |
| `"none"` | *(no `player_damage`)* | `player_damage: "1d8"` |
| `"full"` | `player_damage: "1d8"` | `player_damage: "1d8"` |

Note the semantic alignment: `CheckResolution.success` means the *check
passed* (the save was made), so it gets the reduced/no-damage branch;
`failure` means the save was failed, so it gets full damage. `roll_check`
succeeds on `total >= target` (`five_e.py:92`), identical to
`resolve_save`'s `total >= dc` (`five_e.py:533`), so the mapping is
exact. The `"full"` case requires both branches to carry
`player_damage` — omitting `failure` would make a failed save a no-op
and drop the damage.

The `type` field (e.g. `"poison"`) becomes an optional `tag` on
`CheckResolution` (see "Damage-type labelling" below).

Before:
```json
"on_hit_effects": [
  {
    "save": { "stat": "CON", "dc": 11 },
    "damage": "1d8",
    "on_save": "half",
    "type": "poison"
  }
]
```

After:
```json
"on_hit_effects": [
  {
    "check": {
      "type": "stat_check",
      "stat": "CON",
      "target": 11,
      "proficiency": "save",
      "repeatable": false
    },
    "tag": "poison",
    "success": {
      "narrative": "You resist the poison.",
      "player_damage": "half(1d8)"
    },
    "failure": {
      "narrative": "The poison courses through your veins.",
      "player_damage": "1d8"
    }
  }
]
```

### The `half(expr)` dice notation

A small extension to damage expressions: `half(expr)` evaluates `expr`
normally, then returns `max(1, result // 2)` — matching today's
`on_save: "half"` semantics (`five_e.py:245`).

```
half(1d8)     → roll 1d8, return max(1, result // 2)
half(2d6+3)   → roll 2d6+3, return max(1, result // 2)
half(4)       → return max(1, 4 // 2) = 2
```

The wrapper is stripped before delegating to the existing parser
(`dice.py:parse_damage_dice`, which uses `re.fullmatch` on `NdM[+/-k]`
or a bare integer and would not match `half(...)`). Nested
`half(half(1d8))` is valid (double-halves).

Because `Result.player_damage` is rolled through `system.roll_damage`
(`resolver.py:1408`) — the same `roll_damage` used for NPC `dmg` — a
single extension in the 5e system's `roll_damage` covers both uses.
`"none"` and `"full"` map to omitting or including `player_damage` in
the branch, so `half(...)` is the only new notation.

### StatCheck proficiency marker

Add an optional field to `StatCheck`:

```python
proficiency: Optional[str] = None
```

Currently the only recognized value is `"save"`. When set, the engine
adds `compute_save_modifier(stat, hard.player)` (`five_e.py:547`) — the
player's proficiency bonus if they are proficient in that stat's saves,
else 0 — to the check's flat modifier before rolling.

This is **not** a boolean "is the player proficient" assertion.
Proficiency is player state (`hard_state.py:33`: `save_proficiencies`),
and the author cannot know the player's build. The check declares
*which proficiency domain applies*; the engine resolves it against the
player's proficiency set, exactly as `compute_save_modifier` already
does. A boolean would force the author to guess the build and would be
semantically broken.

Implementation:

- Add `proficiency: Optional[str] = None` to `StatCheck` (`corpus.py`).
  `StatCheck` already has `extra="allow"` and a `modifier: int = 0`
  field; this is a first-class, documented version of the existing
  extension seam (extras already flow to `roll_check` as `params`,
  `resolver.py:1529`).
- Add a system hook `proficiency_bonus(check, player_state) -> int` to
  `ResolutionSystem` (`base.py`), defaulting to `0`. The 5e impl returns
  `compute_save_modifier(check.stat, player_state)` when
  `check.proficiency == "save"`, else `0`. This keeps the resolver
  system-agnostic.
- In `_resolve_checkable`'s `StatCheck` branch (`resolver.py:1512`),
  change the flat modifier to
  `check.modifier + system.proficiency_bonus(check, hard.player)`.

Consequences:

- On-hit saves retain proficiency after the merge.
- `resolve_save` (`five_e.py:513`, `base.py:331`) becomes dead code
  (only `_resolve_on_hit_effects` called it) and is removed.
  `compute_save_modifier` is retained and reused by the hook.
- Non-combat saves (traps, traversal, encounters) authored as
  `StatCheck` can now set `proficiency: "save"` to opt into
  save-proficiency — fixing the pre-existing inconsistency.
- The field is documented as 5e-specific and extensible: future
  values (`"athletics"`, `"thieves_tools"`, …) can be added once player
  state models skill/tool proficiencies. Until then, only `"save"` is
  resolvable.

### Combat-safe effect subset

On-hit `Result`s run inside the combat loop via the generic resolution
path, so they must only produce effects the combat manager can consume
and that make sense mid-NPC-attack. A `model_validator` on
`CombatBlock` restricts the `success`/`failure` Results of each on-hit
`CheckResolution` (recursing through `then_check` chains) to:

**Allowed:** `narrative`, `player_damage`, `set_flag`, `alter_stat`,
`reveals`, `game_over`, `then_check`.

**Prohibited:** `add_item`, `add_item_count`, `remove_item`,
`remove_item_count`, `set_entity_state`, `set_room_state`,
`adjust_attitude`, `set_player_location`, `start_combat`.

Rationale: the allowed set covers the advertised rich effects (a
`poisoned` flag, a STR-draining bite, a save-or-die, narrative
branching, further checks) and maps cleanly onto `HardStateChanges`
fields the combat manager already merges. The prohibited set is either
not combat-safe (`set_player_location` breaks combat invariants;
`start_combat` is nonsensical when already in combat) or not meaningful
mid-NPC-attack (inventory, attitude, entity/room state). `then_check` is
allowed so nesting works, but its branch `Result`s must obey the same
subset.

### On-hit resolution in the combat manager

Today, `resolve_npc_attack` (`five_e.py:337`) rolls the base attack,
calls `_resolve_on_hit_effects`, sums the extra damage into
`total_damage`, and returns `NPCAttackResult.player_hp_delta`. The
combat manager (`combat.py`) already maintains a `HardStateChanges`
accumulator and folds `npc_result.player_hp_delta` and
`npc_result.game_over` into it (`combat.py:311-313, 454-461`).

The new design:

- **`resolve_npc_attack` returns the base attack only** — hit/miss,
  base damage, base-attack player death. On-hit handling is removed
  from the 5e system entirely (`_resolve_on_hit_effects` is deleted).
  `NPCAttackResult.player_hp_delta` carries base damage only;
  `NPCAttackResult.game_over` reflects base-attack player death.
- **The combat manager resolves on-hit effects.** In both the
  `enter_combat` pre-player loop (`combat.py:296`) and the
  `resolve_combat_turn` post-player loop (`combat.py:439`), after
  calling `resolve_npc_attack`, the manager iterates
  `combat_block.on_hit_effects` and calls `_resolve_checkable` for each,
  passing `changes=hard_changes` (the manager's existing accumulator)
  plus `soft`, `state_manager`, `room_id=hard.player.location`,
  `source_id=npc_id`, `source_type="combat"`, and the shared
  `narrative`/`revealed_hints`/`rolls` lists.
- **Effects flow through `HardStateChanges`.** `player_damage` →
  `hard_changes.player_hp_delta` (merged, sums with base damage);
  `set_flag` → `flags_set`; `alter_stat` → `stat_modifiers`; `reveals`
  → the `revealed_hints` list; `narrative` → the narrative list;
  `game_over` → `hard.game_over` (set by `_apply_result` at
  `resolver.py:1416`, consistent with non-combat resolution — the
  manager detects it and sets its `game_over` flag).
- **Player death from on-hit damage.** Base-attack death stays in
  `resolve_npc_attack`. On-hit death is detected by the manager: after
  resolving an on-hit effect, if the player's effective HP
  (`hard.player.current_hp + hard_changes.player_hp_delta`) is `<= 0`,
  emit a death log entry and set `game_over`. (HP is not mutated
  mid-loop; the delta is applied later by the engine, as today.)
- **Context plumbing.** `enter_combat` and `resolve_combat_turn` gain
  `soft` and `state_manager` parameters. Their sole callers
  (`resolver.py:1716, 1740`) have both in scope and pass them through.

This puts on-hit resolution where `HardStateChanges` already lives, and
treats on-hit as the generic `CheckResolution` it now is. The 5e system
stays focused on attack math; save proficiency is handled inside
`_resolve_checkable` via the marker, not in the system.

### Independence and nesting

`on_hit_effects` stays a **list** of `CheckResolution` objects, resolved
independently (preserving "roll all saves, sum all damage"). Nesting
*within* a single effect is supported via `then_check` on the
success/failure `Result`s, routed through `_resolve_checkable`, bounded
by `MAX_THEN_CHECK_DEPTH = 3` (`resolver.py:64`). The on-hit
`CheckResolution` enters at `depth=0`, so the chain can extend three
levels deep (the on-hit check plus two `then_check` levels) before the
guard blocks further nesting — the same budget as other top-level
checkables (e.g. `take_check`).

### Damage-type labelling

The combat log (`hard-state.md:305`) records `on_hit_effects` as
structured dicts with `save_stat`, `save_dc`, `save_roll`, `save_total`,
`save_success`, `damage_expr`, `damage`, and `damage_type`. With
`CheckResolution`, the damage type is no longer a first-class field on
the effect — but it cannot be reliably inferred from `narrative` text.

The fix is an optional **`tag: Optional[str] = None`** field on
`CheckResolution` (`corpus.py`). For on-hit effects it carries the
damage-type label (e.g. `"poison"`); the combat manager copies it into
the log entry's `damage_type`. The `on_save` field is dropped from the
log — `save_success` plus the per-branch `damage` already convey the
outcome. The log entry is built by the combat manager from the
`CheckResolution.check` (stat/target), the resolved save outcome
(roll/total/success), the resolved `player_damage`, and `tag`.

## Implementation phases

### Phase A: `half(expr)` dice notation

**A1. Parser extension (`mgmai/engine/systems/five_e.py`,
possibly `mgmai/engine/systems/dice.py`)**

In `FiveESystem.roll_damage`, strip an outer `half(...)` wrapper before
calling `parse_damage_dice`, roll the inner expression normally, then
return `max(1, total // 2)` with a readable roll string. The wrapper is
recursive.

**A2. Tests**

- `half(1d8)` returns a value in `[1, 4]`.
- `half(1d8)` with a roll of 1 returns 1 (min-1 guard).
- `half(2d6+3)` halves the total.
- `half(4)` returns 2.
- Nested `half(half(1d8))` works.
- `player_damage: "half(1d8)"` in a `Result` deals halved damage
  (integration test via the resolver).

### Phase B: StatCheck proficiency marker

**B1. Schema (`mgmai/models/corpus.py`)** — add
`proficiency: Optional[str] = None` to `StatCheck`.

**B2. System hook (`mgmai/engine/systems/base.py`,
`mgmai/engine/systems/five_e.py`)** — add abstract
`proficiency_bonus(check, player_state) -> int` (default `0`) to
`ResolutionSystem`; 5e impl returns `compute_save_modifier(check.stat,
player_state)` when `check.proficiency == "save"`, else `0`.

**B3. Resolver (`mgmai/engine/resolver.py`)** — in the `StatCheck`
branch of `_resolve_checkable`, set
`flat_modifier = check.modifier + system.proficiency_bonus(check,
hard.player)`.

**B4. Tests** — proficiency bonus applied for save-proficient players;
not applied for non-proficient; non-save checks unaffected; bonus
stacks with `check.modifier`.

### Phase C: Schema and model changes

**C1. `CombatBlock.on_hit_effects` type (`mgmai/models/corpus.py`)** —
change to `list[CheckResolution]`.

**C2. `CheckResolution.tag` (`mgmai/models/corpus.py`)** — add
`tag: Optional[str] = None`.

**C3. Combat-safe subset validator (`mgmai/models/corpus.py`)** —
`model_validator` on `CombatBlock` that, for each on-hit
`CheckResolution`, walks `success`/`failure` (and recurses through
`then_check`), rejecting any `Result` that sets a prohibited field.

**C4. Remove `OnHitEffect` / `OnHitSave` (`mgmai/models/corpus.py`).**

**C5. Schema docs (`schema/corpus.md`)** — replace the OnHitEffect
section with a reference to `CheckResolution`; update the `CombatBlock`
table; document `StatCheck.proficiency` (5e-specific, `"save"`) and
`CheckResolution.tag`; add a cross-reference from the FollowUp section.

**C6. Combat/scenario docs (`doc/combat.md`,
`schema/scenario-generation.md`)** — update examples and tables.

### Phase D: Engine — on-hit resolution in the combat manager

**D1. Strip on-hit from the 5e system (`mgmai/engine/systems/five_e.py`)**
— delete `_resolve_on_hit_effects`; `resolve_npc_attack` returns base
attack only (base damage in `player_hp_delta`, base-death in
`game_over`); remove the `OnHitEffect` type-checking import.

**D2. Remove `resolve_save` (`mgmai/engine/systems/base.py`,
`mgmai/engine/systems/five_e.py`)** — dead after D1. Keep
`compute_save_modifier` (reused by the proficiency hook).

**D3. On-hit resolution in the combat manager
(`mgmai/engine/combat.py`)** — in both `enter_combat` and
`resolve_combat_turn`, after `resolve_npc_attack`, iterate
`combat_block.on_hit_effects` and call `_resolve_checkable` for each
with `changes=hard_changes`, `soft`, `state_manager`,
`room_id=hard.player.location`, `source_id=npc_id`,
`source_type="combat"`, and the shared narrative/revealed_hints/rolls
lists.

**D4. Plumb context (`mgmai/engine/combat.py`,
`mgmai/engine/resolver.py`)** — add `soft` and `state_manager` params
to `enter_combat`/`resolve_combat_turn`; pass them at the call sites
(`resolver.py:1716, 1740`).

**D5. On-hit death detection (`mgmai/engine/combat.py`)** — after each
on-hit effect, if `hard.player.current_hp + hard_changes.player_hp_delta
<= 0`, append a death log entry and set `game_over`; stop resolving
further on-hit effects for that attacker.

**D6. On-hit log entries (`mgmai/engine/combat.py`)** — build the
structured dict from the `CheckResolution.check` (stat/target), the
resolved save outcome (raw_roll/total/success), the resolved
`player_damage` (expression + applied damage), and `tag`; append to the
attack's `CombatLogEntry.on_hit_effects`.

**D7. `game_over` from on-hit `Result`s** — `_apply_result` sets
`hard.game_over` (`resolver.py:1416`); the manager checks for it after
each on-hit resolution and sets its `game_over` flag (consistent with
non-combat resolution).

**D8. `stat_checks.py` (`mgmai/engine/stat_checks.py:142`)** — verify
the `on_hit_effects` log-rendering still works with the new entry shape.

### Phase E: Tests

**E1.** `half(expr)` unit + integration (Phase A2).

**E2.** Proficiency marker unit + integration (Phase B4).

**E3. Corpus validation** — a `CombatBlock` with valid
`CheckResolution` entries passes; prohibited fields on an on-hit
`Result` (including inside `then_check`) are rejected; `tag` is
accepted; `proficiency: "save"` is accepted on a `StatCheck`.

**E4. Combat resolution** —
- `on_save: "half"`: failed save → full `player_damage`; made save →
  `half(expr)` damage.
- `on_save: "none"`: made save → no damage.
- `on_save: "full"`: both outcomes → full damage.
- Multiple on-hit effects trigger independently; damage sums.
- On-hit effect sets a flag on failure → flag in `hard_changes.flags_set`.
- On-hit effect alters a stat → reflected in `hard_changes.stat_modifiers`.
- On-hit save-or-die → `game_over` set.
- Proficiency bonus applied when the player is save-proficient.
- Nested `then_check` resolves up to the depth cap.
- On-hit damage that drops the player to 0 HP → death log entry +
  `game_over`.

**E5. Combat-log entries** — contain `save_stat`, `save_dc`,
`save_roll`, `save_total`, `save_success`, `damage_expr`, `damage`,
`damage_type` (from `tag`); multiple effects produce multiple entries.

**E6. Update existing tests** — remove `OnHitEffect`/`OnHitSave` usage
(`tests/helpers.py:38-39`, `tests/test_systems.py`); remove
`resolve_save` tests (`tests/test_systems.py:241-251`); keep/update
`compute_save_modifier` tests (`tests/test_systems.py:261-283`).

### Phase F: Documentation

**F1. `doc/combat.md`** — rewrite the OnHitEffect section and example
to the `CheckResolution` form; note flags/stat-drain/save-or-die/nesting
are now available; document the combat-safe subset.

**F2. `schema/corpus.md`** — replace the OnHitEffect section with a
cross-reference to `CheckResolution`; update the `CombatBlock` table and
example; document `StatCheck.proficiency` and `CheckResolution.tag`.

**F3. `schema/hard-state.md`** — note that `on_hit_effects` log entries
are now derived from `CheckResolution` outcomes (and that `on_save` is
gone, `damage_type` comes from `tag`).

**F4. `schema/scenario-generation.md`** — update any on-hit examples.

## Files touched

| File | Phase | Nature of change |
|------|-------|------------------|
| `mgmai/models/corpus.py` | B1, C1-C4 | `StatCheck.proficiency`; `CombatBlock.on_hit_effects` → `list[CheckResolution]` + combat-safe validator; `CheckResolution.tag`; remove `OnHitEffect`, `OnHitSave` |
| `mgmai/engine/systems/five_e.py` | A1, B2, D1, D2 | `half(expr)` in `roll_damage`; `proficiency_bonus` impl; strip on-hit from `resolve_npc_attack`; delete `_resolve_on_hit_effects`, `resolve_save` |
| `mgmai/engine/systems/base.py` | B2, D2 | `proficiency_bonus` abstract; remove `resolve_save` abstract |
| `mgmai/engine/systems/dice.py` | A1 | Optional `half(...)` strip helper (or keep in `five_e.py`) |
| `mgmai/engine/resolver.py` | B3, D4 | `_resolve_checkable` uses `proficiency_bonus`; pass `soft`/`state_manager` to combat calls |
| `mgmai/engine/combat.py` | D3-D7 | On-hit resolution in `enter_combat`/`resolve_combat_turn`; plumb `soft`/`state_manager`; death detection; log-entry building |
| `mgmai/engine/stat_checks.py` | D8 | Verify `on_hit_effects` log rendering |
| `schema/corpus.md` | C5, F2 | Replace OnHitEffect section; document `proficiency`, `tag` |
| `doc/combat.md` | C6, F1 | Rewrite OnHitEffect section |
| `schema/hard-state.md` | F3 | Log entry derivation note |
| `schema/scenario-generation.md` | C6, F4 | Update examples |
| `tests/test_systems.py` | A2, E6 | `half(expr)` tests; remove `resolve_save`/`OnHitEffect` usage; keep `compute_save_modifier` tests |
| `tests/helpers.py` | E6 | Remove `OnHitEffect`/`OnHitSave` imports |
| `tests/test_resolver.py` | E2, E4 | Proficiency + on-hit integration via `CheckResolution` |
| `tests/test_state_manager.py` | E3 | Validation tests |
| `tests/test_corpus.py` | E3 | Corpus validation for `CheckResolution` in `CombatBlock` |
| `tests/test_combat.py` | E4, E5 | Combat resolution and log-entry tests |
| `plan.md` | — | This document |

## Open questions / deferred

- **`repeatable` on on-hit checks.** `StatCheck.repeatable` is required,
  so on-hit checks must set `repeatable: false`. The attempt-tracking in
  `_resolve_checkable` (`resolver.py:1502`) is gated on `track_attempts`,
  which combat will not pass, so the field has no effect for on-hit
  effects — it is cosmetic noise. Document the convention; optionally
  default it for combat-originated checks later.
- **`skip_check_if` on on-hit effects.** New capability (e.g. skip the
  save if the player has poison immunity). Available automatically via
  `CheckResolution`; worth documenting as a use case.
- **Player-attack / NPC-vs-NPC on-hit effects.** Today on-hit effects
  fire only for NPC attacks on the player. The generic mechanism could
  extend to other attacker/target pairs. Out of scope; the schema now
  supports it naturally.
- **Routing `game_over` into `HardStateChanges`.** `_apply_result`
  mutates `hard.game_over` directly (`resolver.py:1416`); all other
  on-hit effects flow through `HardStateChanges`. Routing `game_over`
  into a `HardStateChanges.game_over` field would make the flow uniform
  and is a worthwhile cleanup, but it touches non-combat game-over
  handling and is deferred.
- **General proficiency keys beyond `"save"`.** Skill/tool proficiency
  (e.g. `proficiency: "athletics"`) requires player state to model
  skill/tool proficiencies, which it does not yet. The field is designed
  to extend without a schema change once that exists.
