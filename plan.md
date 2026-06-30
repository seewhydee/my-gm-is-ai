# Plan: Unify Take Check and Traversal Check into `GatedCheck`

## Rationale

The schema currently has two nearly identical constructs for gated,
check-based resolution in non-interaction contexts:

| Trait | `TakeCheck` (Item, line 916) | `TraversalCheck` (Exit, line 411) |
|---|---|---|
| `gating` | yes | yes |
| `check` | yes (required) | yes (required) |
| `skip_check_if` | yes | yes |
| `success` | yes (validator requires it when `check` present) | optional (no validator) |
| `failure` | yes | yes |
| `using_results` | — | yes (item→alternate-check overrides) |

Field-wise, `TakeCheck` is a subset of `TraversalCheck` — the only
field difference is `using_results`.  However, the two currently differ
in two non-field ways that this plan must address:

1. **Validator**: `TakeCheck` has a `check_success_on_check` validator
   that requires `success` when `check` is present.
   `TraversalCheck` has no such validator — `success` is optional (and
   none of the 8 traversal checks in the real corpus define one).

2. **Resolution precedence**: The two engine code paths evaluate
   `gating` and `skip_check_if` in *opposite order*.  The take path
   (`resolve_transfer`) checks `gating` first; the traversal path
   (`resolve_move`) checks `skip_check_if` first.  This only matters
   when both are present and their evaluations conflict (`gating` false
   + `skip_check_if` true), but it is a real divergence.

This plan unifies both under one `GatedCheck` type **and** aligns the
resolution logic to a single precedence (gating-first), so that the
unified type is resolved consistently regardless of call site.

The new **`GatedCheck`** primitive is distinct from
**`FollowUpCheck`** (the `then_check` embedded in a Result), which
deliberately omits `gating` and `using_results` — a follow-up check
fires automatically from its parent result, so an extra gate layer is
redundant and `using_results` makes no sense in that context.

### Chosen precedence: gating-first

`gating` and `skip_check_if` form a hierarchy, not parallel checks:

- `gating` — *"Does this check exist right now?"* (activation)
- `skip_check_if` — *"Given the check exists, should we skip rolling?"*
  (bypass)

You cannot bypass a check that does not exist.  `skip_check_if` is
logically nested inside `gating`.  This matches the take path's current
behavior, the semantics note below, and the existing schema prose for
traversal checks (corpus.md line 458: "True means proceed to do the
check (with `skip_check_if`).  False means traversal proceeds.").  The
traversal *engine code* is the outlier and must be reordered to match.

In every scenario where the two diverge (gating false + skip_check_if
true), gating-first gives the intuitive result: when the obstacle is
gone (gating false), the check is dormant and neither `success` nor
`failure` should fire — the action proceeds with default behavior.  The
real corpus confirms this intent: `gating` conditions are more
comprehensive than their paired `skip_check_if` conditions, and no
traversal check defines a `success` result, so the reordering is
behavior-preserving for all existing data.

## End-state primitives

| Primitive | Has gate? | Has `using_results`? | `success` | Where used |
|---|---|---|---|---|
| **GatedCheck** | yes (`gating`) | optional | optional | Item `take_check`, Exit `traversal_check` |
| **FollowUpCheck** | no (parent result gates it) | no | required | Result `then_check` |

## Schema changes (`schema/corpus.md`)

### 1. Define the `GatedCheck` primitive

Add a new subsection under `## Common Primitives` (alongside `Check`,
`Result`, `Follow-up check`), before or after `Follow-up check`:

```
### Gated Check

A Gated Check wraps a [Check](#check) with a condition that determines
whether the check is active (`gating`), an optional bypass condition
(`skip_check_if`), and success/failure [Results](#result).  It is used
for item take checks and exit traversal checks.

| Field             | Type      | Description                              |
|-------------------|-----------|------------------------------------------|
| `gating` (*)      | Condition | Whether the check is active at all       |
| `check`           | Check     | The Check to resolve (required)          |
| `skip_check_if`(*)| Condition | If present and true, bypass the check    |
| `success` (*)     | Result    | Result if check succeeds or is bypassed  |
| `failure` (*)     | Result    | Result if check fails                    |
| `using_results`(*)| object    | Item ID → alternate Check override map   |
> (*) optional
```

Include a JSON example (from the traversal check example, now
generalized).

Semantics note: if `gating` evaluates to false, the check is silently
inactive — the action proceeds with default behavior and *no* Result
from the check is applied (neither `success` nor `failure`).  If
`gating` evaluates to true (or is absent) and `skip_check_if` evaluates
to true, the check is bypassed and `success` is applied.  Otherwise the
check is rolled normally.

For the two accepted `using_results` override shapes (a `result`-keyed
Result, or a `check`/`success`/`failure` triple), see
[Interaction](#interaction) and [Traversal Check](#traversal-check);
the semantics are identical in all contexts that use it.

### 2. Replace `take_check` field description (line 907/916)

The `take_check` row in the Item field table stays — its type becomes
`GatedCheck`.  Remove the dedicated `take_check` sub-table (lines
919-926) and replace with a cross-reference, but **preserve the
take-specific notes** (lines 928-932), which describe behavior not
covered by the generic GatedCheck primitive:

```
- `take_check` (*): GatedCheck — gated check for taking the item.
  See [Gated Check](#gated-check).

  The check is *not* automatically disabled after a successful take.
  For a one-time success gate (pass once, then freely take thereafter),
  use `gating` with a flag that `success` sets.  For a permanent
  one-attempt gate (failure locks you out), set `check.repeatable` to
  `false`.
```

### 3. Replace `Traversal Check` subsection (lines 411-481)

Replace the entire `#### Traversal Check` subsection — heading,
description, JSON example, field table, **and** notes (lines 411
through 481, not just 411-443) — with a cross-reference plus the
traversal-specific notes that must be preserved:

```
#### Traversal Check

The optional `traversal_check` field on an Exit is a [Gated
Check](#gated-check) that gates non-automatic traversal.  The Exit's
own `condition` field controls *visibility* of the exit;
`traversal_check` controls whether traversal requires a check (and
which check).

(Keep the existing JSON example, updated to use the unified schema.)

Traversal-specific behavior:

- Success has the side-effect of moving to the destination Room; no
  need to specify that in `success`.
- Failure has the side-effect of canceling the traversal; no need to
  specify that in `failure`.
- The `using_results` field accommodates player commands of the form
  "[USE EXIT] using [ITEM]".  It is keyed by item entity IDs (or the
  `"*"` wildcard); when the player uses an item matching a key, the
  value replaces the traversal check entirely.  The mapped value can
  be one of these two:
  - a dict with `result` keyed to a [Result](#result)
  - a dict with `check` (a [Check](#check)), `success` (a Result)
    and optionally `failure` (a Result), with the same semantics as
    [Interaction](#interaction).
```

The existing notes describing `gating` and `skip_check_if` behavior
(lines 458-464) are subsumed by the GatedCheck primitive's semantics
note and need not be repeated here.

## Model changes (`mgmai/models/corpus.py`)

### 4. Create `GatedCheck` class

Add after `Checkable` (line 165), replacing `TakeCheck` (line 216) and
`TraversalCheck` (line 249):

```python
class GatedCheck(Checkable):
    """A check gated by a condition. Used for take checks and traversal checks."""
    check: CheckType
    gating: Optional[ConditionExpression] = None
    using_results: Optional[Dict[str, UsingResultOverride]] = None
```

This is exactly `TraversalCheck`'s current definition — it's the
superset.  The `take_check` use site simply won't populate
`using_results`.

**No validator requiring `success`.**  `success` is optional on
`GatedCheck` because traversal checks legitimately omit it (none of the
8 traversal checks in the real corpus define one; the engine falls
through to default traversal behavior).  This has a consequence for the
take-check engine path — see step 9.

### 5. Remove `TakeCheck` and `TraversalCheck`

Delete lines 216-228 (`TakeCheck` class + validator) and lines 249-253
(`TraversalCheck` class).  The `Checkable` base class (line 165) is
kept as the shared base for both `GatedCheck` and `CheckResolution`
(FollowUpCheck).

Update the `Checkable` docstring (lines 168-169): replace
"TraversalCheck, TakeCheck" with "GatedCheck".

### 6. Update `Entity.take_check` field (line 422)

```python
# Before:
take_check: Optional[TakeCheck] = None
# After:
take_check: Optional[GatedCheck] = None
```

### 7. Update `Exit.traversal_check` field (line 261)

```python
# Before:
traversal_check: Optional[TraversalCheck] = None
# After:
traversal_check: Optional[GatedCheck] = None
```

### 8. Validator handling

The `TakeCheck.check_success_on_check` validator (requires `success`
when `check` is present) is **removed, not relocated**.  `success` is
optional on `GatedCheck` (step 4).

This is safe only because the take-check engine path is refactored to
not construct a synthetic `Interaction` (step 9).  The current take
path builds `Interaction(check=tc.check, success=tc.success, ...)`, and
`Interaction`'s validator rejects `check` without `success` — so simply
removing the `TakeCheck` validator without the engine refactor would
crash at runtime.  After the refactor (step 9), the take path calls
`_resolve_checkable` directly, which handles a missing `success`
gracefully (applies nothing on a passed check with no `success`
branch).

A per-site validator cannot enforce "success required for take,
optional for traversal" on `GatedCheck` itself, because there is no
field that reliably discriminates the two contexts (`using_results` is
optional in both).  The constraint is therefore enforced at the engine
level: both resolution paths treat a missing `success` as "apply
nothing."

No corpus migration is needed — the JSON field names are identical
across the old types, and `success` was already absent from all
traversal checks.

## Engine changes (`mgmai/engine/resolver.py`)

### 9. `resolve_transfer()` — take check path (line 735)

**Logic change required** (not just a type annotation change).  The
current code constructs a synthetic `Interaction` to roll the take
check, which requires `success` via `Interaction`'s validator.  Since
`success` is now optional on `GatedCheck`, the take path must call
`_resolve_checkable` directly with the `GatedCheck` (a `Checkable`
subclass), which handles missing `success`/`failure` gracefully.

The three-branch structure becomes:

```python
if tc.gating and not evaluate(tc.gating, hard, soft, corpus):
    pass  # inactive — item taken freely, no result applied
else:
    # _resolve_checkable handles skip_check_if (apply success) and the
    # roll (apply success/failure).  Returns True if passed/bypassed.
    # Clear any stale error so an unresolvable check can be detected.
    if result.error is not None:
        result.error = None
    passed = _resolve_checkable(
        tc,
        hard=hard, soft=soft, corpus=corpus, room_id=room_id,
        changes=changes, narrative=triggered_narration,
        revealed_hints=revealed_hints, rolls=rolls,
        state_manager=state_manager, resolution=result,
        source_id=f"take_{item}", source_type="take",
    )
    if not passed:
        if result.error:
            # Unresolvable check (missing stats, etc.) — abort transfer
            return ResolutionResult(
                success=False, error=result.error,
                hard_changes=changes, room_after_id=room_id,
                rolls=rolls, triggered_narration=triggered_narration,
                revealed_hints=revealed_hints,
            )
        continue  # check failed — item not taken
```

This eliminates the synthetic `Interaction`, the
`_resolve_interaction_check` indirection, and the manual
`check_succeeded` roll inspection.  Changes, narration, hints, and
rolls are accumulated directly into the passed-in lists.  The
gating-first precedence matches the traversal path (after step 10).

### 10. `resolve_move()` — traversal check path (line 328)

**Logic change required.**  Reorder the `skip_check_if` / `gating`
evaluation from skip_check_if-first to **gating-first**, matching the
take path and the semantics note in step 1.

```python
# Before (skip_check_if-first):
should_check = True
if trav_check.skip_check_if and evaluate(trav_check.skip_check_if, ...):
    should_check = False
    if trav_check.success:
        _apply_result_with_check(trav_check.success, ...)
elif trav_check.gating:
    should_check = evaluate(trav_check.gating, ...)

# After (gating-first):
should_check = True
if trav_check.gating and not evaluate(trav_check.gating, ...):
    should_check = False  # inactive — no result applied
elif trav_check.skip_check_if and evaluate(trav_check.skip_check_if, ...):
    should_check = False  # bypassed — apply success
    if trav_check.success:
        _apply_result_with_check(trav_check.success, ...)
```

The `using_results` handling and `_resolve_traversal_check` call (lines
346-400) are unchanged.  No traversal check in the real corpus has a
`success` result, so this reordering is behavior-preserving for all
existing data.

### 11. `_resolve_checkable()` type annotation (line 1330)

```python
# Before:
chk: CheckResolution | Interaction | OnExamineEvent | TraversalCheck,
# After:
chk: CheckResolution | Interaction | OnExamineEvent | GatedCheck,
```

After step 9, this annotation is now exercised: the take path passes a
`GatedCheck` directly.  (Previously, `TraversalCheck` appeared in the
annotation but was never actually passed to `_resolve_checkable` — the
annotation was vestigial.)

### 12. Update imports

Update the import at line 47: replace `TraversalCheck` with
`GatedCheck`.

### 13. Consider a shared helper (recommended, optional)

Both paths now implement the same gating-first three-branch decision
(gating → skip_check_if → roll).  To prevent future drift, consider
extracting a shared helper that evaluates `gating` and `skip_check_if`
and returns whether the caller should proceed to roll:

```python
def _evaluate_gate(
    gc: GatedCheck, hard, soft, corpus, *,
    changes, narrative, revealed_hints, rolls,
    state_manager, resolution, source_id, source_type, room_id,
) -> bool:
    """Evaluate gating and skip_check_if.

    Returns True if the caller should roll.  Returns False if the check
    is inactive (gating false) or bypassed (skip_check_if true); in the
    bypassed case, success is applied here.
    """
    if gc.gating is not None and not evaluate(gc.gating, hard, soft, corpus):
        return False  # inactive
    if gc.skip_check_if is not None and evaluate(gc.skip_check_if, hard, soft, corpus):
        if gc.success:
            _apply_result_with_check(gc.success, ...)
        return False  # bypassed
    return True  # roll
```

The take path would call `_resolve_checkable` only when the helper
returns True; the traversal path would do its `using_results` + roll
only when the helper returns True.  This is optional for correctness
(steps 9-10 already align the logic) but recommended for
maintainability.

## Test changes

### 14. `tests/helpers.py`

- `_mk_exit()` (line 113): change `traversal_check: TraversalCheck |
  None = None` → `traversal_check: GatedCheck | None = None`.
- Corpus fixture construction (lines 369, 410): change
  `TraversalCheck.model_validate(...)` to `GatedCheck.model_validate(...)`.
- Import: replace `TraversalCheck` with `GatedCheck`.

### 15. `tests/test_resolver.py`

- Import (lines 54-55): replace `TakeCheck` and `TraversalCheck` with
  `GatedCheck`.
- `TestResolveTransferTakeCheck` (line 850): update all
  `TakeCheck(...)` constructor calls (lines 857, 881, 906, 932, 959) to
  `GatedCheck(...)`.  Field names are identical — no other changes.
- `test_traversal_roll_dict_has_unified_keys` (line 289): update the
  `TraversalCheck(...)` constructor call (line 298) to `GatedCheck(...)`.

### 16. Add precedence tests

Add tests verifying the gating-first precedence for both paths,
specifically the divergence case (gating false + skip_check_if true +
`success` present):

- **Traversal**: when `gating` is false and `skip_check_if` is true,
  `success` is NOT applied (check is inactive).  This is the behavior
  change from the old skip_check_if-first ordering.
- **Take**: same — item taken freely, `success` not applied.

Without these tests, the precedence is unobservable (no corpus data
triggers the divergence), so a future regression could slip in
undetected.

### 17. Grep for remaining references

After changes, run:

```
rg 'TakeCheck|TraversalCheck' tests/ mgmai/ schema/ --type py --type md
```

to catch any stragglers (e.g., the `Checkable` docstring if not
updated in step 5).

## What does NOT change

- **The three-branch resolution *semantics*** (gating→inactive /
  skip_check_if→bypass / check→roll) — the semantics are unchanged,
  but the traversal path's *implementation* is reordered to
  gating-first to match.  After this change, both paths follow the
  same precedence for the first time.
- `CheckResolution` / FollowUpCheck — no `gating` field is added; it
  remains a separate primitive.
- `Interaction` — no changes; it uses `condition` (not `gating`) and
  has a `result` path for check-less interactions.
- `UsingResultOverride` — unchanged; it's shared between `GatedCheck`
  and `Interaction` already.
- The `Checkable` base class — structurally unchanged (docstring
  updated only).
- The adventure corpus JSON files — no migration needed.  The field
  names (`gating`, `check`, `skip_check_if`, `success`, `failure`,
  `using_results`) are identical.  The reordering of the traversal
  path is behavior-preserving because no traversal check in the corpus
  has a `success` result.

## File-change inventory

| File | Change |
|---|---|
| `schema/corpus.md` | Add `GatedCheck` primitive section; replace `take_check` sub-table with cross-reference (preserve take-specific notes); replace `Traversal Check` subsection (lines 411-481) with cross-reference (preserve traversal-specific notes) |
| `mgmai/models/corpus.py` | New `GatedCheck` class; delete `TakeCheck` and `TraversalCheck`; update `Entity.take_check` and `Exit.traversal_check` type annotations; remove `TakeCheck` validator; update `Checkable` docstring |
| `mgmai/engine/resolver.py` | Reorder traversal path to gating-first; refactor take path to call `_resolve_checkable` directly (eliminate synthetic `Interaction`); update `_resolve_checkable` annotation; update imports; (optionally) extract shared helper |
| `tests/helpers.py` | Update `TraversalCheck` → `GatedCheck` references |
| `tests/test_resolver.py` | Update `TakeCheck`/`TraversalCheck` → `GatedCheck` constructor calls; add gating-first precedence tests |

## Task ordering

1. **Model** — `mgmai/models/corpus.py`: create `GatedCheck`, delete
   old classes, update field types, update docstring.
2. **Engine** — `mgmai/engine/resolver.py`: reorder traversal path to
   gating-first; refactor take path (eliminate synthetic
   `Interaction`); update annotations and imports.
3. **Tests/helpers** — update all references to old class names; add
   precedence tests.
4. **Schema** — `schema/corpus.md`: add GatedCheck primitive, update
   Item/Exit sections (preserve context-specific notes).
5. `pytest` green.
6. `rg 'TakeCheck|TraversalCheck'` clean.
