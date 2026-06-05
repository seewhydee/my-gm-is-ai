# Player Stats Extension — Coding Plan

This plan derives from `plan.md` § "To Be Done: Player Stats Extension" (lines 372–777).  Sections are grouped by module; each section lists file changes, schema details, and test plans.

## 1. Models (`mgmai/models/`)

### 1.1 `corpus.py`

**Delete the old `Check` class** (lines 65-69). Replace it with two discriminated models:

```python
class RollCheck(BaseModel):
    type: Literal["roll"] = "roll"
    threshold: float = Field(ge=0.0, le=1.0)
    repeatable: bool
    note: Optional[str] = None


class StatCheck(BaseModel):
    type: Literal["stat_check"] = "stat_check"
    stat: str
    dc: int
    modifier: int = 0
    resolution_params: Optional[Dict[str, Any]] = None
    opposed_by: Optional[str] = None   # reserved for future NPC opposed checks
    repeatable: bool
    note: Optional[str] = None
    skill: Optional[str] = None        # reserved for future skill checks


CheckType = RollCheck | StatCheck   # Union; discriminated by Literal["type"]
```

**Add new models** (at end of file or after the Check block):

```python
class StatDefinition(BaseModel):
    name: str
    description: str


class StatsBlock(BaseModel):
    definitions: Dict[str, StatDefinition]
    resolution_system: str = "d20"

    @model_validator(mode="after")
    def check_resolution_system(self) -> StatsBlock:
        supported = {"d20"}
        if self.resolution_system not in supported:
            raise ValueError(
                f"Unknown resolution_system: {self.resolution_system!r}. "
                f"Supported: {supported}"
            )
        return self
```

**Modify `Interaction.check`:**

```python
class Interaction(BaseModel):
    # ... existing fields ...
    check: Optional[CheckType] = None   # was Optional[Check]; update sample adventure JSON
    # ... rest unchanged ...
```

**Modify `ModuleCorpus`:**

```python
class ModuleCorpus(BaseModel):
    # ... existing fields ...
    stats: Optional[StatsBlock] = None   # new; absent = no stat system
```

**Code updates needed for the Check union:** Every site that accesses `check.threshold` must first guard on `check.type == "roll"` or use `isinstance(check, RollCheck)`. Search references: `resolver.py` line 497 (`check.threshold`) and line 513 (`check.threshold`). Update the sample adventure's `corpus.json` if it uses `Check` objects — though in practice the existing adventures may not use checks at all; verify.

### 1.2 `hard_state.py`

**Add `stats` to `PlayerState`:**

```python
class PlayerState(BaseModel):
    location: str
    inventory: list[str] = Field(default_factory=list)
    stats: Optional[Dict[str, int]] = None   # NEW
```

The engine must validate at startup that every key in `player.stats` has a matching entry in `corpus.stats.definitions` if corpus.stats is present. This validation belongs in `state/manager.py`'s load path (or a dedicated validator called after loading).

### 1.3 `briefing.py`

**Add a new model and extend `GMBriefing`:**

First, add a new model for a single stat entry (value + precomputed modifier):

```python
class PlayerStatEntry(BaseModel):
    value: int
    modifier: int
```

Then extend `GMBriefing`:

```python
class GMBriefing(BaseModel):
    # ... existing fields ...
    player_stats: Optional[Dict[str, PlayerStatEntry]] = None   # NEW
```

`player_stats` is `None` when the adventure has no stats system. The modifier is pre-computed by the Context Assembler using the resolution system's formula (see §3).

### 1.4 `actions.py`

No schema changes needed — `EngineResult.rolls` is already `List[Dict[str, Any]]` and accepts the new stat-check dictionary format. But verify that the `WillRevealReadinessEntry` conditions evaluation in `_build_will_reveal_readiness` already handles the new `stat` condition domain (it calls `evaluate()` → `evaluate_condition_string()` which will gain the `stat` branch; see §2.1).

### 1.5 `narration.py`

No changes needed. Stat checks do not affect narration output schema.

---

## 2. Engine (`mgmai/engine/`)

### 2.1 `conditions.py`

**Add `stat` to the DOMAINS regex:**

```python
DOMAINS = "flag|inventory|tag|entity|room|attitude|topic|item|stat"
```

**Add a `stat` branch in `evaluate_condition_string`** (after the `item` branch, before `raise ValueError`):

```python
if domain == "stat":
    if op is None or value is None:
        raise ValueError(
            f"stat condition requires operator and value: {raw!r}"
        )
    stats = hard_state.player.stats
    if stats is None:
        return False
    stat_val = stats.get(key)
    if stat_val is None:
        return False
    return _compare(stat_val, op, value)
```

Note: `stat` uses a simple key (just the stat abbreviation like "STR"), no `entity.field` format. The existing `CONDITION_RE` already handles `[\w.-]+` keys so "STR" matches fine.

**Reserved `npc_stat`:** Per issue #3 above, do not add to the regex yet. It will fail with "Could not parse condition string" until a future phase adds it.

### 2.2 `resolver.py`

**When `Check` becomes a discriminated union**, `_resolve_interaction_check` (line 477) must dispatch on `check.type`. Refactor as:

```python
def _resolve_interaction_check(inter, hard, soft, corpus, room_id):
    check = inter.check
    if check is None:
        return ResolutionResult(success=False, error="Check defined but missing")

    # Non-repeatable gating (shared by both check types)
    if not check.repeatable:
        attempted = soft.checks_attempted.get(inter.id, [])
        if room_id in attempted:
            return ResolutionResult(
                success=False,
                error=f"Interaction '{inter.id}' has already been attempted and is not repeatable",
            )

    if check.type == "stat_check":
        return _resolve_stat_check(inter, check, hard, soft, corpus, room_id)
    else:
        return _resolve_roll_check(inter, check, hard, soft, corpus, room_id)
```

Rename the current body of `_resolve_interaction_check` (lines 496–529) into `_resolve_roll_check(inter, check: RollCheck, hard, soft, corpus, room_id)`.

**Add new function `_resolve_stat_check`:**

```python
def _resolve_stat_check(
    inter: Interaction,
    check: StatCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
) -> ResolutionResult:
    stats_block = corpus.stats
    if stats_block is None:
        return ResolutionResult(
            success=False, error="Adventure has no stats system defined"
        )

    player_stats = hard.player.stats
    if player_stats is None or check.stat not in player_stats:
        return ResolutionResult(
            success=False,
            error=f"Player has no '{check.stat}' stat",
        )

    stat_value = player_stats[check.stat]
    res_system = stats_block.resolution_system

    if res_system != "d20":
        return ResolutionResult(
            success=False,
            error=f"Unsupported resolution system: {res_system!r}",
        )

    # d20 modifier
    computed_mod = _compute_d20_modifier(stat_value)
    total_mod = computed_mod + check.modifier

    # advantage / disadvantage
    params = (check.resolution_params or {}).get("d20", {})
    advantage = params.get("advantage", False)
    disadvantage = params.get("disadvantage", False)

    import random
    raw_roll: int
    if advantage and not disadvantage:
        raw_roll = max(random.randint(1, 20), random.randint(1, 20))
    elif disadvantage and not advantage:
        raw_roll = min(random.randint(1, 20), random.randint(1, 20))
    else:
        raw_roll = random.randint(1, 20)

    total = raw_roll + total_mod
    success_flag = total >= check.dc

    branch = inter.success if success_flag else inter.failure
    result = branch if branch else inter.result

    if not check.repeatable:
        if inter.id not in soft.checks_attempted:
            soft.checks_attempted[inter.id] = []
        soft.checks_attempted[inter.id].append(room_id)

    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []

    rolls: list[dict[str, Any]] = [{
        "check_id": inter.id,
        "type": "stat_check",
        "stat": check.stat,
        "dc": check.dc,
        "modifier": total_mod,
        "computed_mod": computed_mod,
        "flat_mod": check.modifier,
        "raw_roll": raw_roll,
        "total": total,
        "margin": total - check.dc,
        "success": success_flag,
        "advantage": advantage,
        "disadvantage": disadvantage,
    }]

    if result:
        _apply_result(result, changes, narrative, revealed_hints)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls,
    )
```

**Add stat modifier utility** (top-level function in `resolver.py` or in a new `engine/stat_checks.py`):

```python
def _compute_d20_modifier(stat_value: int) -> int:
    """D&D 5e modifier: (stat - 10) // 2, rounded down."""
    return (stat_value - 10) // 2
```

Expose as `compute_d20_modifier` (without underscore) for use by the Context Assembler (§3).

### 2.3 `engine.py` (main engine)

No changes needed. The engine calls `resolve_action()` → `resolve_interact()` → `_resolve_interaction_check()` which now dispatches to the stat check path. Stat check roll results flow through the existing `rolls` aggregation in `engine.py:148,263`.

The startup validation (player.stats keys match corpus.stats.definitions) should happen in `state/manager.py` after both corpus and hard state are loaded. Add a validator:

```python
def _validate_player_stats(corpus: ModuleCorpus, hard: HardGameState) -> None:
    if corpus.stats is None:
        if hard.player.stats is not None:
            raise ValueError(
                "player.stats is present but corpus has no stats block"
            )
        return
    if hard.player.stats is None:
        raise ValueError(
            "corpus defines stats but player.stats is missing"
        )
    for stat_key in hard.player.stats:
        if stat_key not in corpus.stats.definitions:
            raise ValueError(
                f"Player stat '{stat_key}' is not defined in corpus.stats.definitions"
            )
```

### 2.4 `enums` or new `stat_checks.py`

Option A: Keep `_compute_d20_modifier` in `resolver.py` and import from `assembler.py`.
Option B: Create `mgmai/engine/stat_checks.py` with public functions:
- `compute_modifier(stat_value: int, system: str) -> int`
- `stat_check_detail(stat_value: int, dc: int, modifier: int, system: str, ...)` (optional)

**Recommendation:** Option B — a small dedicated module for testability and clean imports.

```python
# mgmai/engine/stat_checks.py

def compute_d20_modifier(stat_value: int) -> int:
    return (stat_value - 10) // 2


def compute_modifier(stat_value: int, resolution_system: str) -> int:
    if resolution_system == "d20":
        return compute_d20_modifier(stat_value)
    raise ValueError(f"Unknown resolution system: {resolution_system!r}")
```

---

## 3. Context Assembler (`mgmai/context/assembler.py`)

**Modify `_build_player_state`** to include player stats in the briefing. The `PlayerStateBriefing` model needs a `player_stats` field first (see §1.3 above), then:

```python
def _build_player_state(hard: HardGameState, soft: SoftGameState) -> PlayerStateBriefing:
    # ... existing code ...

    player_stats: Optional[Dict[str, Dict[str, int]]] = None
    if hard.player.stats is not None:
        player_stats = {}
        for stat_key, stat_value in hard.player.stats.items():
            modifier = _compute_modifier_for_briefing(stat_key, stat_value, corpus_hint)
            player_stats[stat_key] = {"value": stat_value, "modifier": modifier}

    return PlayerStateBriefing(
        # ... existing fields ...
        player_stats=player_stats,
    )
```

**Problem:** The assembler doesn't currently have access to `corpus.stats.resolution_system` for modifier computation — the `assemble()` function receives `corpus` but `_build_player_state` doesn't. **Solution:** Pass `corpus` to `_build_player_state` or pass the resolution system string. Since the modifier is pre-computed and put into the briefing for LLM consumption, the assembler needs the resolution system. Change the signature of `_build_player_state`:

```python
def _build_player_state(
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> PlayerStateBriefing:
```

Update the call in `assemble()` accordingly.

The modifier computation uses the utility from §2.4:

```python
from mgmai.engine.stat_checks import compute_modifier

# inside _build_player_state:
for stat_key, stat_value in hard.player.stats.items():
    mod = compute_modifier(stat_value, corpus.stats.resolution_system)
    player_stats[stat_key] = PlayerStatEntry(value=stat_value, modifier=mod)
```

---

## 4. State Manager (`mgmai/state/manager.py`)

Add startup validation after loading corpus and hard state (call `_validate_player_stats` from §2.3). The exact location depends on the current load flow — likely in the `load()` or `new_game()` method, after both corpus and hard_state are set.

---

## 5. Display (`mgmai/game/display.py`)

**In `render_status`**, after the existing status line and before `render_game_over`, add a character sheet panel when stats are present:

```python
def render_status(self, state_loader: Any) -> None:
    # ... existing status line ...

    # Character sheet
    self._render_character_sheet(state_loader)
```

New helper:

```python
def _render_character_sheet(self, state_loader: Any) -> None:
    hard = state_loader.hard_state
    corpus = state_loader.corpus
    if hard is None or corpus is None:
        return
    stats = hard.player.stats
    if stats is None or corpus.stats is None:
        return

    from mgmai.engine.stat_checks import compute_modifier

    lines: list[str] = []
    stat_entries = sorted(stats.items())
    # Layout: 3 columns → 2 rows for 6 stats
    pairs = []
    for i in range(0, len(stat_entries), 3):
        row_stats = stat_entries[i:i+3]
        pair_parts = []
        for key, val in row_stats:
            mod = compute_modifier(val, corpus.stats.resolution_system)
            sign = "+" if mod >= 0 else ""
            pair_parts.append(f"{key} {val:>2} ({sign}{mod})")
        pairs.append("   ".join(pair_parts))

    if RICH_AVAILABLE:
        body = "\n".join(pairs)
        panel = Panel(
            body,
            title="Character Sheet",
            border_style="cyan",
            padding=(0, 1),
        )
        self._console.print(panel)
    else:
        print("┌─ Character Sheet ──────────────┐")
        for line in pairs:
            print(f"│ {line.ljust(30)}│")
        print("└────────────────────────────────┘")
```

---

## 6. LLM Templates

The ruling template (`templates/ruling.j2`) should include the `player_stats` block when present. The prose template (`templates/prose.j2`) may also benefit from having player stats available for narration (e.g., describing how strong/weak the character is when they succeed/fail a check).

Check existing templates for how `npc_attitudes` and similar optional blocks are conditionally rendered, and follow that pattern.

---

## 7. Test Plan

All test files live in `tests/`. Follow existing conventions: `make_hard_state()`, `make_soft_state()`, `make_corpus()` builder helpers; pytest classes grouping related tests; `sample_corpus` fixture for integration tests.

### 7.1 `tests/test_corpus.py` — new tests

**Class: `TestStatsBlock`**
- `test_stats_block_valid`: `StatsBlock(definitions={"STR": StatDefinition(name="Strength", description="...")}, resolution_system="d20")` validates.
- `test_stats_block_default_system`: omitting `resolution_system` defaults to `"d20"`.
- `test_stats_block_unsupported_system`: `resolution_system="gurps"` raises `ValueError`.

**Class: `TestStatCheck`**
- `test_stat_check_minimal`: `StatCheck(stat="STR", dc=12, repeatable=False)` validates.
- `test_stat_check_full`: all fields including `resolution_params={"d20": {"advantage": True}}`.
- `test_stat_check_modifier_defaults_to_zero`: `modifier` defaults to 0.
- `test_stat_check_resolution_params_optional`: `resolution_params` can be `None`.
- `test_stat_check_opposed_by_reserved`: `opposed_by="entity:spider.DEX"` validates (reserved, not used).
- `test_stat_check_skill_reserved`: `skill="athletics"` validates (reserved).

**Class: `TestInteractionWithCheck`**
- `test_interaction_with_roll_check`: `Interaction(..., check={"type": "roll", "threshold": 0.5, "repeatable": True}, success=..., failure=...)` validates.
- `test_interaction_with_stat_check`: `Interaction(..., check={"type": "stat_check", "stat": "STR", "dc": 12, "repeatable": True}, success=..., failure=...)` validates.
- `test_interaction_with_check_and_result_mutually_exclusive`: stat_check + result still raises.

**Class: `TestModuleCorpusWithStats`**
- `test_corpus_without_stats`: `ModuleCorpus(...)` without `stats` block validates (`stats=None`).
- `test_corpus_with_stats`: `ModuleCorpus(..., stats=StatsBlock(...))` validates.
- `test_corpus_stats_definitions`: the `definitions` dict handles all six standard stats.

### 7.2 `tests/test_hard_state.py` — new tests

**Class: `TestPlayerStats`**
- `test_player_no_stats`: `PlayerState(location="room", inventory=[])` validates with `stats=None`.
- `test_player_with_stats`: `PlayerState(location="room", inventory=[], stats={"STR": 14, "DEX": 12})` validates.
- `test_player_stats_empty_dict`: `stats={}` validates (empty but present).

### 7.3 `tests/test_conditions.py` — new tests

**Add `stat` to DOMAINS parsing test** in `TestParseConditionString`:
- `test_stat_with_op`: `parse_condition_string("stat:STR >= 12")` → `("stat", "STR", ">=", "12")`.
- `test_stat_no_op_raises`: `parse_condition_string("stat:STR")` raises `ValueError` (stat requires operator).

**Class: `TestEvaluateConditionStringStat`**
- `test_stat_gte_true`: player.stats has `{"STR": 14}`, `"stat:STR >= 12"` → `True`.
- `test_stat_gte_false`: 14 is not >= 16 → `False`.
- `test_stat_lt_true`: `"stat:STR < 20"` → `True`.
- `test_stat_eq`: `"stat:STR == 14"` → `True`.
- `test_stat_nonexistent_key`: player.stats has `{"STR": 14}`, `"stat:DEX >= 12"` → `False` (key missing, not None).
- `test_stat_no_player_stats`: `player.stats is None`, `"stat:STR >= 12"` → `False`.
- `test_stat_missing_operator_raises`: `"stat:STR"` raises `ValueError`.
- `test_stat_with_decimal`: `player.stats = {"STR": 14.5}`, `"stat:STR >= 14"` → `True` (following existing _compare float handling).
- `test_stat_in_condition_expression`: `ConditionExpression(require="stat:STR >= 13")` works.
- `test_stat_all_of`: `ConditionExpression(all=["stat:STR >= 10", "stat:DEX >= 10"])` works.
- `test_stat_with_attitude`: mixed condition `all=["stat:CHA >= 15", "attitude:korbar >= 2"]` works (demonstrates the scenario integration example from plan.md).

### 7.4 `tests/test_resolver.py` — new tests or new file `tests/test_stat_checks.py`

**New file: `tests/test_stat_checks.py`**

**Class: `TestComputeD20Modifier`**
- `test_10_yields_0`: `compute_d20_modifier(10)` → `0`.
- `test_12_yields_1`: `compute_d20_modifier(12)` → `1`.
- `test_14_yields_2`: `compute_d20_modifier(14)` → `2`.
- `test_8_yields_neg1`: `compute_d20_modifier(8)` → `-1`.
- `test_9_yields_neg1`: `compute_d20_modifier(9)` → `-1` (rounds down).
- `test_3_yields_neg4`: `compute_d20_modifier(3)` → `-4`.
- `test_18_yields_4`: `compute_d20_modifier(18)` → `4`.

**Class: `TestResolveStatCheck`** (integration-style, using `state_manager` with stats)
- `test_stat_check_success_when_roll_high_enough`: Mock `random.randint` to return 20, verify success.
- `test_stat_check_failure_when_roll_low`: Mock `random.randint` to return 1, verify failure.
- `test_stat_check_with_advantage`: Mock two rolls, verify max is used.
- `test_stat_check_with_disadvantage`: Mock two rolls, verify min is used.
- `test_stat_check_advantage_and_disadvantage_cancel`: Both set, verify single roll.
- `test_stat_check_no_stats_system`: corpus without stats block → error.
- `test_stat_check_player_missing_stat`: player.stats without the required key → error.
- `test_stat_check_non_repeatable_second_attempt`: first attempt succeeds, second attempt with same interaction in same room → blocked.
- `test_stat_check_flat_modifier_added`: `check.modifier = 2` contributes to total.
- `test_stat_check_result_applied_on_success`: success branch narrative, set_flag applied.
- `test_stat_check_result_applied_on_failure`: failure branch narrative applied.
- `test_stat_check_roll_details_format`: verify roll dict has `check_id`, `type`, `stat`, `dc`, `modifier`, `raw_roll`, `total`, `margin`, `success`, `advantage`, `disadvantage`.

### 7.5 `tests/test_briefing.py` — new tests

- `test_briefing_includes_player_stats_when_present`: `GMBriefing` with `player_stats` dict validates.
- `test_briefing_player_stats_none_when_absent`: `GMBriefing` with `player_stats=None` works.
- `test_player_stat_entry`: `PlayerStatEntry(value=14, modifier=2)` validates.

### 7.6 `tests/test_assembler.py` — new tests

**Requires:** Fixtures for corpus with stats and hard_state with player.stats.

- `test_assemble_includes_player_stats`: Assembling with stats present → GMBriefing.player_stats contains modifiers.
- `test_assemble_no_stats_when_absent`: Assembling without stats → GMBriefing.player_stats is None.
- `test_modifier_precomputed_correctly`: player has STR 14, d20 system → modifier is `+2` in briefing.

### 7.7 `tests/test_display.py` — new tests

- `test_character_sheet_renders_when_stats_present`: Verify character sheet panel appears.
- `test_character_sheet_not_rendered_when_stats_absent`: No stats → no character sheet panel.

---

## 8. File Changes Summary

| File | Change | Description |
|---|---|---|
| `schema/corpus.md` | Add | Document `stats` block, `stat_check` type, `stat` condition domain |
| `schema/hard-state.md` | Add | Document `player.stats` |
| `schema/actions.md` | Add | Document `stat_check` in EngineResult.rolls |
| `schema/scenario-generation.md` | Add | Stats section in generation instructions |
| `mgmai/models/corpus.py` | Modify | Delete old `Check`, add `RollCheck` + `StatCheck` + `CheckType` union. Add `StatDefinition`, `StatsBlock`, `stats` field on `ModuleCorpus`. |
| `mgmai/models/hard_state.py` | Add | `stats: Optional[Dict[str, int]]` to `PlayerState`. |
| `mgmai/models/briefing.py` | Add | `PlayerStatEntry` model. `player_stats: Optional[Dict[str, PlayerStatEntry]]` to `GMBriefing`. |
| `mgmai/engine/conditions.py` | Modify | Add `stat` to `DOMAINS` regex. Add `stat` branch in `evaluate_condition_string`. |
| `mgmai/engine/stat_checks.py` | New | `compute_d20_modifier()`, `compute_modifier()` public functions. |
| `mgmai/engine/resolver.py` | Modify | Refactor `_resolve_interaction_check` → dispatch on `check.type`. Add `_resolve_stat_check()`. Add `_resolve_roll_check()` (extracted body). Add import of `stat_checks`. |
| `mgmai/engine/engine.py` | No change | Stat checks flow through existing `resolve()` pipeline. |
| `mgmai/context/assembler.py` | Modify | Pass `corpus` to `_build_player_state`. Compute and include `player_stats` in briefing. |
| `mgmai/state/manager.py` | Modify | Add `_validate_player_stats()` call on load/new-game. |
| `mgmai/game/display.py` | Add | `_render_character_sheet()` + call from `render_status()`. |
| `templates/ruling.j2` | Modify | Add `player_stats` block to ruling prompt (templating). |
| `templates/prose.j2` | Modify | Optionally add `player_stats` to prose prompt. |
| `tests/test_corpus.py` | Add | `TestStatsBlock`, `TestStatCheck`, `TestInteractionWithCheck`, `TestModuleCorpusWithStats`. |
| `tests/test_hard_state.py` | Add | `TestPlayerStats`. |
| `tests/test_conditions.py` | Add | `stat` parsing test, `TestEvaluateConditionStringStat`. |
| `tests/test_stat_checks.py` | New | `TestComputeD20Modifier`, `TestResolveStatCheck` (mocked dice). |
| `tests/test_briefing.py` | Add | PlayerStatEntry and GMBriefing.player_stats validation. |
| `tests/test_assembler.py` | Add | Stats in briefing assembly. |
| `tests/test_display.py` | Add | Character sheet rendering. |
| `tests/conftest.py` | Modify | Optionally add fixtures for corpus-with-stats and hard-state-with-stats. |

---

## 9. Implementation Order

Recommended sequence to minimize blocked work:

1. **Models first:** `StatDefinition`, `StatsBlock`, `RollCheck`, `StatCheck`, `PlayerState.stats`, `PlayerStatEntry`, `GMBriefing.player_stats`. All additive until `Check` union refactor.
2. **`Check` union refactor:** Change `Interaction.check` type, refactor `_resolve_interaction_check` into dispatch + two sub-functions. Update any callers that reference `check.threshold`.
3. **`stat_checks.py`:** `compute_d20_modifier` and `compute_modifier` standalone utilities. Unit-testable in isolation.
4. **`stat` condition domain:** Add to DOMAINS regex, add branch in `evaluate_condition_string`. Tests.
5. **`_resolve_stat_check`:** Implement stat check resolution in resolver. Tests with mocked dice.
6. **Assembler:** Pass corpus, compute player_stats in briefing. Tests.
7. **State manager validation:** Startup check that player.stats matches corpus.stats.definitions. Tests.
8. **Display:** Character sheet panel. Tests.
9. **Templates:** Add player_stats to ruling.j2 and prose.j2 prompts.


