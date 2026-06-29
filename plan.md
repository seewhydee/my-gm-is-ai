# Plan: Flatten and rename the stat check schema

Pre-alpha: no backward-compatibility shims, no aliases, no migration code.
Change everywhere.

## Motivation

The `StatCheck` model suffers from three design problems:

### 1. `resolution_params` is wordy and adds pointless nesting

The field name "resolution params" is engine jargon that means nothing to a
content author writing JSON. Worse, its value is **structurally
double-bookkeeping**: every check wraps system-specific flags under the system
name key (`{"5e": {"advantage": true}}`), but the system is already chosen
globally at `stats.system = "5e"`. The inner `"5e"` key is pure syntactic
noise — the engine has to reach through it with
`(params or {}).get(self.name, {})`, and a content author has to type it on
every single check.

### 2. `dc`, `opposed_by`, `skill` leak 5e concepts into the generic model

- `dc` (Difficulty Class) is D&D terminology. Other systems use "target
  number", "threshold", or no numeric target at all (PbtA result bands). The
  generic model should use a neutral name.
- `opposed_by` and `skill` are listed as "for future use" and are **always
  `null`** — everywhere in the adventure data and at every runtime call site.
  They add 2 null-fields to every stat check without ever being consumed.
  YAGNI.

### 3. The resulting JSON is ugly and full of dead weight

Every stat check in `corpus.json` serializes 9 fields (including `type`);
only 4 carry actual data. The rest are `null` or zero-default placeholders.
Example from the log (showing 8 of the 9 — `type` is omitted):

```json
{"stat": "CHA", "dc": 9, "modifier": 0, "resolution_params": null,
 "opposed_by": null, "repeatable": true, "note": null, "skill": null}
```

Five of nine fields convey nothing. The actual payload (`type`, `stat`,
`dc`, `repeatable`) is buried in noise. (`modifier` and `note` are
intentionally retained in the new model — they are legitimate optionals,
not dead weight.)

### What we're doing about it

Flatten the model entirely. Eliminate `resolution_params`, `opposed_by`, and
`skill`. Rename `dc` to `target`. Use Pydantic `extra="allow"` to let
system-specific flags (like `advantage`) live as clean top-level siblings
alongside `stat` and `target`. System-specific fields are documented per
system in the schema, not baked into the generic model.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Rename `dc` → `target` in `StatCheck`, `CheckResult`, the roll-dict shape, event contexts, and all documentation. | System-neutral. Just as descriptive. |
| D2 | Delete `resolution_params` from `StatCheck`. System-specific fields go flat at the check's top level via `extra="allow"`. | Eliminates the redundant `"5e"` inner key and the abstract wrapper name. Content authors write `"advantage": true` directly. |
| D3 | Delete `opposed_by` and `skill` from `StatCheck`. | YAGNI. Both are always `null`. Add back when actually implemented. |
| D4 | Add `model_config = ConfigDict(extra="allow")` to `StatCheck`. System-specific fields (e.g. `advantage`, `disadvantage`) are accepted as extra top-level keys. | Allows per-system extensions without bloating the model. The engine reads them from `model_extra`. |
| D5 | In `FiveESystem.roll_check()`, remove the `params.get(self.name, {})` layer and read `advantage`/`disadvantage` directly from `params`. | The system key was redundant. |
| D6 | Rename `roll_check()` parameter `dc` → `target` in the `ResolutionSystem` ABC and `FiveESystem`. | Consistency with D1. |
| D7 | Rename `CheckResult.dc` → `CheckResult.target`. Rename the `"dc"` key in `CheckResult.to_dict()` to `"target"`. | The result object should match the model's naming. |
| D8 | The `resolution_params` nested structure `{"5e": {"advantage": true}}` is not used in the adventure data at all — 0 occurrences in `corpus.json`. Migration is a no-op on adventure data. | Any migration scope is limited to tests and schema docs. |
| D9 | Defer flattening `resolve_save()`'s `sys_params = (params or {}).get(self.name, {})` nesting in `five_e.py`. Add a code comment instead, noting it is inconsistent with D5 and should be flattened when saves grow corpus-driven params. | `resolve_save` is only ever called with `params=None` today, so the nesting is dead code. `SaveResult.dc`/`OnHitSave.dc` are a separate (saving-throw) concept and are not renamed. Avoids scope creep. |

## End-state design

### Model (`mgmai/models/corpus.py`)

```python
class StatCheck(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["stat_check"] = "stat_check"
    stat: str
    target: int
    modifier: int = 0
    repeatable: bool
    note: Optional[str] = None
```

### JSON examples

**5e (current primary system):**
```json
{"type": "stat_check", "stat": "STR", "target": 12,
 "advantage": true, "repeatable": false,
 "note": "Bend the iron bars."}
```

**Hypothetical PbtA system:**
```json
{"type": "stat_check", "stat": "COOL", "target": 0,
 "move": "act_under_pressure", "repeatable": false}
```

### Engine flow

**Before:**
```
StatCheck.dc / .modifier / .resolution_params
    → system.roll_check(stat, value, dc, flat_modifier, params=resolution_params)
        → params.get("5e", {}).get("advantage")
```

**After:**
```
StatCheck.target / .modifier / .model_extra
    → system.roll_check(stat, value, target, flat_modifier, params=model_extra)
        → params.get("advantage")
```

The resolver extracts `check.model_extra` (or `{}`) and passes it as `params`.
The system reads `advantage`/`disadvantage` directly — one nesting layer
removed.

### `CheckResult` dataclass

```python
@dataclass
class CheckResult:
    stat: str
    target: int
    computed_mod: int
    flat_mod: int
    modifier: int
    raw_roll: int
    total: int
    margin: int              # total - target
    success: bool
    advantage: bool
    disadvantage: bool

    def to_dict(self) -> dict:
        return {
            "type": "stat_check",
            "stat": self.stat,
            "target": self.target,
            "modifier": self.modifier,
            "computed_mod": self.computed_mod,
            "flat_mod": self.flat_mod,
            "raw_roll": self.raw_roll,
            "total": self.total,
            "margin": self.margin,
            "success": self.success,
            "advantage": self.advantage,
            "disadvantage": self.disadvantage,
        }
```

### `roll_check()` signatures

**ABC (`base.py`):**
```python
def roll_check(self, stat: str, stat_value: int, target: int,
               flat_modifier: int = 0, params: dict | None = None) -> CheckResult:
```

**FiveE (`five_e.py`):**
```python
def roll_check(self, stat, stat_value, target, flat_modifier=0, params=None):
    computed_mod = self.compute_modifier(stat_value)
    total_mod = computed_mod + flat_modifier
    advantage = (params or {}).get("advantage", False)
    disadvantage = (params or {}).get("disadvantage", False)
    raw_roll = self.roll_die(20, advantage=advantage, disadvantage=disadvantage)
    total = raw_roll + total_mod
    success = total >= target
    return CheckResult(..., target=target, margin=total - target, ...)
```

## File-change inventory

### `mgmai/models/corpus.py`
- `StatCheck` (L149–158): delete `resolution_params`, `opposed_by`, `skill`;
  rename `dc` → `target`; add `model_config = ConfigDict(extra="allow")`.

### `mgmai/engine/systems/base.py`
- `CheckResult` (L46–81): rename `dc` → `target` in field list and
  `to_dict()`. Update `margin` docstring.
- `roll_check()` ABC (L203–211): rename `dc` → `target`; update docstring.

### `mgmai/engine/systems/five_e.py`
- `roll_check()` (L76–107): rename parameter `dc` → `target`; replace
  `sys_params = (params or {}).get(self.name, {})` with direct
  `advantage = (params or {}).get("advantage", False)` /
  `disadvantage = (params or {}).get("disadvantage", False)`.
- `CheckResult(...)` construction call (L95–107): rename `dc=dc` → `target=target`, `margin=total - dc` → `margin=total - target`.
- `resolve_save()` (L512–541): leave the logic unchanged, but add a code
  comment at the `sys_params = (params or {}).get(self.name, {})` line
  noting it is inconsistent with D5 and should be flattened when saves grow
  corpus-driven params (see D9). Do **not** rename `SaveResult.dc` or the
  `dc` parameter — saving throws are a separate concept.

### `mgmai/engine/resolver.py`
- Interaction path (L1391–1446): `check.dc` → `check.target`;
  `params=check.resolution_params` → `params=check.model_extra or {}`;
  `roll_dict["dc"]` → `roll_dict["target"]`; `ctx["dc"]` → `ctx["target"]`.
  (This path also resolves `then_check`s via `_apply_result_with_check`.)
- Traversal-check path (L1020–1057): same renames (`.dc` → `.target`,
  `.resolution_params` → `.model_extra`, `"dc"` → `"target"`). This is the
  `_resolve_traversal_check` function, not a "then-check" path.

### `mgmai/engine/encounters.py`
- `_resolve_encounter_stat_check()` (L340–371): `check.dc` → `check.target`;
  `params=check.resolution_params` → `params=check.model_extra or {}`.

### `adventures/bag-of-holding/corpus.json`
- All 30 `stat_check` objects: rename `"dc"` → `"target"`.
- **WARNING: there are 31 `"dc"` occurrences in this file, not 30.** The
  31st, at L211 (`"dc": 11`), is the `dc` of an `OnHitSave` inside the
  spider's `on_hit_effects` block — a saving-throw DC, NOT a stat check.
  It must NOT be renamed. Do **not** blind find/replace `"dc"` → `"target"`;
  scope each replacement to objects whose `"type"` is `"stat_check"`.
- `resolution_params`, `opposed_by`, `skill`, `modifier`, `note` are already
  absent from the adventure data — no deletions needed.

### `schema/corpus.md`
- L153–185: rewrite the stat check section. Updated JSON example (flat
  fields, `target` instead of `dc`, `advantage` at top level). Updated field
  table (remove `resolution_params`, `opposed_by`, `skill`; rename `dc` →
  `target`). Updated prose about system-specific fields via `extra="allow"`.
- Update all stat check JSON snippets throughout the file: rename `"dc"` →
  `"target"`. Confirmed occurrences (all stat checks): L161, L239, L339,
  L422, L941, L1018, L1047, L1082.
- L504 and L556: the `check.passed`/`check.failed` context-key table rows
  (`dc?` and `dc | The difficulty class...`) — rename to `target`. (These
  duplicate the table in `events.md`; both must be updated.)

### `schema/scenario-generation.md`
- All stat check JSON snippets: rename `"dc"` → `"target"`.
- Stat check field descriptions: update to match new model.

### `schema/events.md`
- L59–60: `dc?` → `target?` in check.passed/check.failed context table.
- L76: `dc` → `target` in context key table row.
- (L168 references stat_check resolution but does not mention `dc`; no
  change needed there.)

### `schema/actions.md`
- L716: `dc` → `target` in rolls description.

### `doc/player-stats.md`
- L68–82: rewrite the stat_check field table to match new model. Drop
  `resolution_params`, `opposed_by`, `skill`; rename `dc` → `target`.
- L90–92: update resolution system table (DC → target).

### Test files

**`tests/test_corpus.py`:**
- L868 (`test_with_alter_stat`): `"dc": 10` → `"target": 10` in the
  `EncounterRule.model_validate` stat_check payload. (Outside the
  `TestStatCheck` block — easy to miss.)
- L945–975 (`TestStatCheck`): rename `dc` → `target` and `resolution_params`
  assertions.
  - `test_minimal` (L947): `"dc": 12` → `"target": 12`; `sc.dc` → `sc.target`.
  - `test_full` (L953–967): rewrite. Replace `resolution_params: {"5e": {"advantage": True}}` with flat `"advantage": True`. Delete `opposed_by` and `skill` assertions. Rename `dc` → `target`.
  - `test_modifier_defaults_to_zero` (L969–971): `"dc"` → `"target"`.
  - `test_resolution_params_optional` (L973–975): rename to `test_extra_fields_allow_advantage` — validate that `"advantage": true` is accepted via `extra="allow"` and accessible in `model_extra`.
- L991–998 (`TestInteractionWithCheck.test_with_stat_check`): `"dc"` → `"target"`.

**`tests/test_systems.py`:**
- L84–85 (fake `ResolutionSystem` stub): rename the `roll_check` parameter
  `dc` → `target` for consistency with the ABC (D6), and update the
  positional `CheckResult(stat, dc, ...)` construction and `1 - dc` margin
  computation to use `target`. (The stub survives positionally even without
  this, but leaving it is inconsistent with the renamed ABC and
  `CheckResult`.)
- L172–206 (`TestFiveEChecks`): rename `dc=` → `target=` in `roll_check()`
  calls.
  - L175: `dc=10` → `target=10`.
  - L185: `dc=20` → `target=20`.
  - L189–197: `dc=15` → `target=15`; `params={"5e": {"advantage": True}}`
    → `params={"advantage": True}`.
  - L199–205: `"dc"` → `"target"` in key assertion list.
- L409: `assert result.dc == 10` → `result.target == 10`.
- (L98–99 fake `resolve_save` and L116 `FleeResult(dc=...)` are unchanged —
  `SaveResult.dc` and `FleeResult.dc` are not being renamed.)

**`tests/test_stat_checks.py`:**
- L125, L129, L134, L135: roll-dicts use `"dc"`. `format_stat_check_prefix`
  ignores this key so the tests pass regardless, but D1 renames the
  roll-dict shape — update to `"target"` for consistency with the canonical
  engine output.

**`tests/test_encounters.py`:**
- 6 `StatCheck(..., dc=...)` constructions (L197, L217, L242, L266, L332,
  L356): rename `dc=` → `target=`. Mandatory — `target` is required, so
  leaving `dc=` fails validation.

**`tests/helpers.py`:**
- 4 stat_check JSON payloads in `make_webs_test_corpus` (L370, L376, L380,
  L412): rename `"dc"` → `"target"`. Mandatory for the same reason.

## What does NOT change
- `EncounterRule.check: Optional[StatCheck]` — the field type is the same
  (just the model changed).
- `SaveResult.dc`, `attack_effect.save.dc` — these are saving throw DCs, a
  separate D&D-specific concept, not part of the stat check system.
- `FiveESystem.resolve_save()` (`five_e.py:512–541`): the
  `sys_params = (params or {}).get(self.name, {})` nesting is left as-is
  (deferred — see D9); only a code comment is added. `SaveResult.dc` and the
  `dc` parameter are not renamed.
- `Checkable`, `CheckResolution`, and the rest of the check inheritance
  hierarchy.
- The `roll_check()` signature in `stat_checks.py` shims (they don't
  reference these fields).

## Verification

Run from the repo root:

```
pytest
```

Specific checks:
- `tests/test_corpus.py::TestStatCheck` — model validation with new field names.
- `tests/test_systems.py::TestFiveEChecks` — roll_check() with renamed params.
- `tests/test_corpus.py::TestInteractionWithCheck` — stat_check inside
  interactions with `target` field.
- `tests/test_corpus.py::test_with_alter_stat` — EncounterRule stat_check
  payload (the easy-to-miss one at L868).
- `tests/test_encounters.py` — encounter stat checks.
- `tests/test_stat_checks.py` — roll-dict shape consistency.
- `tests/test_parser.py` / `tests/test_actions.py` — action parser
  `target` field is unrelated; should still pass.
- The adventure bag-of-holding loads cleanly: `pytest
  tests/test_corpus.py tests/test_assembler.py tests/test_bag_of_holding_webs.py`.

## Task ordering

All changes are a single mechanical pass — one rename, one deletion of dead
fields, one flattening of `resolution_params`. No phases needed.

1. **Model** — `mgmai/models/corpus.py`: `StatCheck` → remove 3 fields,
   rename 1, add `extra="allow"`.
2. **Engine core** — `base.py`: `CheckResult` dataclass + `roll_check()`
   ABC. `five_e.py`: `roll_check()` implementation.
3. **Engine call sites** — `resolver.py` (2 sites: interaction path +
   traversal-check path) + `encounters.py` (1 site): rewire `.dc` →
   `.target`, `.resolution_params` → `.model_extra`.
4. **Adventure data** — `corpus.json`: 30 replacements of `"dc"` → `"target"`.
5. **Schema docs** — `corpus.md`, `scenario-generation.md`, `events.md`,
   `actions.md`: rename `dc` → `target`, update stat check field tables,
   update JSON examples.
6. **User docs** — `doc/player-stats.md`: update stat check field table.
7. **Tests** — update assertions per inventory above.
8. `pytest` green.
