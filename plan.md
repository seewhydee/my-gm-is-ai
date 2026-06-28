# Plan: Replace `ChainedCheck` with `CheckResolution` + unify the resolver

This is a coding and schema-change plan, not a design audit. Pre-alpha: no
backward-compatibility shims, no aliases, no migration code. Rename
everywhere.

## Motivation

`ChainedCheck` (`{skip_check_if, check, success, failure}`, carried as
`Result.chain_check`) is used 5× in the sole adventure, in two patterns:

- **Pattern A — genuine follow-up (2×):** fail STR to turn the key → roll DEX
  to catch it before it falls into the Astral. A synchronous complication
  chained to a failure branch.
- **Pattern B — standalone check inside a `Result` (3×):** a reaction whose
  `result` contains *only* a `chain_check` — not chained to anything. This
  exists because `Result` has a `chain_check` field but no `check` field, so
  `chain_check` is the single entry point for "a check inside a Result."

Four problems follow:

1. **The name lies for Pattern B.** "Chained" implies a follow-up, but the
   construct is also the reaction's primary check. The overloading — not the
   type itself — is what makes it look redundant.
2. **Five near-duplicate resolver functions.** `_resolve_roll_check` /
   `_resolve_stat_check` (interaction path) and `_resolve_roll_check_chain` /
   `_resolve_stat_check_chain` (chain path) are ~90% identical; plus
   `_resolve_chained_check` as a dispatcher.
3. **Nine boilerplate call sites.** Every `Result` consumer repeats
   `if result.chain_check: _resolve_chained_check(...)`.
4. **Hacky source attribution.** Chain functions default `source_type` to
   `"reaction" if source_id else "unknown"`, so a follow-up inside an
   interaction's failure branch is mislabeled.

The other two disposal options were considered and rejected:

- **Merge with `Check` (`RollCheck`/`StatCheck`)?** No — `Check` is a pure
  check *definition* reused in `EncounterRule.check`, where branches live on
  the rule. `ChainedCheck` is check *plus branches* (a resolution, not a
  definition). Different layers; not merge candidates.
- **Replace with reactions?** No — Pattern A cannot move to the event bus:
  `check.failed` is not an `IMMEDIATE_ALLOWED_EVENTS` event (it fires
  *deferred* at end-of-turn, after the action's narration is delivered),
  state-change events don't cascade during dispatch, and source attribution
  would break. The synchronous fail-forward drama requires inline resolution.

**Verdict:** keep the construct (a self-contained check-resolution unit that
fits inside a `Result`), fix the seams — rename it, unify the resolver.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Rename type `ChainedCheck` → `CheckResolution`; rename `Result.chain_check` field → `Result.then_check`. | "Chained" implies a follow-up, but the construct is also used standalone (Pattern B: a reaction whose result is only a check). `then_check` conveys ordering ("apply this result, *then* resolve this check") without the chaining misnomer. |
| D2 | Introduce a shared `Checkable` Pydantic base carrying `(skip_check_if, check, success, failure)`. `Interaction`, `DialoguePath`, `OnExamineEvent`, `TraversalCheck`, `TakeCheck`, `CheckResolution` all inherit it. | Six models duplicate the quartet today. A shared base ends field-level duplication and makes the unified resolver signature natural. |
| D3 | Unify the resolver: one `_resolve_checkable()` + one `_apply_result_with_check()` helper. Delete `_resolve_chained_check`, `_resolve_roll_check_chain`, `_resolve_stat_check_chain`, `_resolve_roll_check`, `_resolve_stat_check`. | These five functions are ~90% parallel copies. The synthetic-`Interaction` delegation precedent (`resolver.py:1396`, `resolver.py:1631`) already shows the pattern. |
| D4 | `then_check` recursion and event emission always use an explicitly-threaded `source_type` (inherited from the parent resolution). Remove the `source_type = "reaction" if source_id else "unknown"` hack (`resolver.py:994`, `1041`, `1095`). | Source attribution becomes coherent: a then_check inside an interaction's failure branch is `source_type="interaction"`, not silently relabeled "reaction". |
| D5 | Keep `skip_check_if` on `CheckResolution` (inherited from `Checkable`). | **Revises audit point 4.** `skip_check_if` is unused *on chains specifically*, but it is used 8× elsewhere in the family (`adventures/bag-of-holding/corpus.json` L776, L1053, L1075, L1176, L1216, L1264, L1457, L1683). Removing it from one `Checkable` consumer breaks the symmetry for no gain. Keep it inherited and uniformly available. |
| D6 | Do **not** add a first-class `check` field to `ReactionEffects`. | **Revises audit point 3.** The rename (D1) already resolves Pattern B's "overloading" — `then_check` is a legitimate standalone-in-`Result` construct, no longer pretending to be chained. A separate `effects.check` shortcut would re-introduce two ways to do one thing. Deferred as YAGNI. |
| D7 | Preserve `MAX_CHAIN_CHECK_DEPTH = 3` and current depth accounting. Add a test that exercises it (no test does today). | The cap is currently untested. Keep the limit; pin it with a test. |

## End-state design

### Model (`mgmai/models/corpus.py`)

New shared base, placed after `Result` and `CheckType` are defined:

```python
class Checkable(BaseModel):
    """A probabilistic check with success/failure branches.

    Shared by Interaction, DialoguePath, OnExamineEvent, TraversalCheck,
    TakeCheck, and CheckResolution. Subclasses add their own fields
    (condition, result, gating, using_results, id, label, rigorous_only, ...)
    and validators that tighten optionality per their semantics.
    """
    skip_check_if: Optional[ConditionExpression] = None
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None
```

`CheckResolution` replaces `ChainedCheck` (currently L117). `check` and
`success` are required (override the base's `Optional`); `skip_check_if` and
`failure` stay optional:

```python
class CheckResolution(Checkable):
    """A self-contained check resolution: a check plus its outcome branches.

    Carried by Result.then_check, resolved immediately after the parent
    result's own effects. Used both as a follow-up (fail STR -> roll DEX to
    catch the key) and as the sole content of a result (a reaction whose
    effect is just a check).
    """
    check: CheckType
    success: Result

    @model_validator(mode="after")
    def require_check_and_success(self) -> "CheckResolution":
        if self.check is None:
            raise ValueError("CheckResolution requires 'check'")
        if self.success is None:
            raise ValueError("CheckResolution requires 'success'")
        return self
```

`Result` (L124): rename field `chain_check` → `then_check` (L134). Update
`has_any_effect`'s field list (L143): replace `"chain_check"` with
`"then_check"`.

Make the five other check-bearing models inherit `Checkable` and **delete
their duplicated declarations** of `skip_check_if`, `check`, `success`,
`failure`:

| Model | Line | Notes |
|---|---|---|
| `Interaction` | L204 | keep `id, label, description, condition, result, using_results`; override `check`/`success`/`failure` stay optional; keep existing validator. |
| `DialoguePath` | L339 | keep `description, condition, result`; keep validator. |
| `OnExamineEvent` | L245 | keep `id, condition, rigorous_only, result`; keep validator. |
| `TraversalCheck` | L227 | override `check: CheckType` (required); keep `gating, using_results`. |
| `TakeCheck` | L188 | override `check: CheckType` (required); keep `gating`; keep validator. |

`from __future__ import annotations` (L17) is already present, so forward
references to `Result`/`CheckType` in `Checkable` resolve fine regardless of
definition order.

### Resolver (`mgmai/engine/resolver.py`)

Two new functions replace five old ones.

**`_apply_result_with_check`** — applies a `Result` and, if it carries a
`then_check`, recurses. This is the single place that fires a result's
follow-up check. Replaces the 9 inline `if result.chain_check:
_resolve_chained_check(...)` blocks.

```python
def _apply_result_with_check(
    result: Result,
    *,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    rolls: list[dict[str, Any]],
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
    then_check_depth: int = 0,
    item_origin: str = "interaction",
) -> None:
    _apply_result(result, changes, narrative, revealed_hints,
                  hard, corpus, soft, state_manager, resolution,
                  source_id, item_origin)
    if result.then_check:
        _resolve_checkable(
            result.then_check,
            hard=hard, soft=soft, corpus=corpus, room_id=room_id,
            changes=changes, narrative=narrative,
            revealed_hints=revealed_hints, rolls=rolls,
            depth=then_check_depth,
            state_manager=state_manager, resolution=resolution,
            source_id=source_id, source_type=source_type,
        )
```

**`_resolve_checkable`** — the unified roller. Accepts any `Checkable`
(duck-typed: has `.skip_check_if, .check, .success, .failure`). Handles
`skip_check_if`, rolls (stat or roll), picks the branch, emits
`check.passed`/`check.failed`, and applies the branch via
`_apply_result_with_check` (which recurses into the branch's own `then_check`).

```python
def _resolve_checkable(
    chk: Checkable,
    *,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    rolls: list[dict[str, Any]],
    depth: int = 0,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
    track_attempts: bool = False,
    attempt_key: str | None = None,
) -> bool:
    """Resolve a Checkable's check, apply the chosen branch, recurse into
    any then_check. Returns the success flag."""
```

Behavior, in order:

1. **Depth guard.** `if depth >= MAX_CHAIN_CHECK_DEPTH: return False` (only
   reachable via then_check recursion; primary checks call at depth 0).
2. **`skip_check_if`.** If present and `evaluate(...)` is true, apply
   `chk.success` via `_apply_result_with_check(success, then_check_depth=depth+1, ...)`
   and return `True`. (Preserves current `_resolve_chained_check` L996-1005
   semantics.)
3. **Repeatable gating** (only when `track_attempts` and `not check.repeatable`):
   if `attempt_key` already in `soft.checks_attempted` for `room_id`, return
   early with a `ResolutionResult`-level error signal. (Moved verbatim from
   `_resolve_interaction_check` L1230-1237.)
4. **Roll.** `StatCheck` → `system.roll_check(...)`; `RollCheck` →
   `random.random() < threshold`. Append to `rolls`.
5. **Emit event.** `check.passed`/`check.failed` with `check_type`, `stat`/`dc`
   or `threshold`, `source_id`, `source_type` (all explicit — no defaulting
   hack).
6. **Record attempt** (when `track_attempts`): append to
   `soft.checks_attempted[attempt_key]`. (Moved from L1293-1296 / L1365-1368.)
7. **Apply branch.** `branch = chk.success if passed else chk.failure`. If
   `branch` is not None, call
   `_apply_result_with_check(branch, then_check_depth=depth+1, source_id=source_id, source_type=source_type, ...)`.
8. Return the success flag.

**Missing-stats error handling:** Currently, `_resolve_stat_check` (interaction path) returns an error `ResolutionResult` when `corpus.stats` or player stats are absent, but `_resolve_stat_check_chain` silently returns `None`. After unification, `_resolve_checkable` returns `bool` — use the optional `resolution: ResolutionResult` parameter to carry the error (`resolution.error = "Stats system not available"`) when stats are missing, while still returning `False`. This unifies the handling and gives all callers a consistent error signal.

**Surviving call sites** (rewired to the new helpers):

| Call site | Line | Change |
|---|---|---|
| `_resolve_interaction_check` | L1215 | Delete the dispatch to `_resolve_roll_check`/`_resolve_stat_check`. Call `_resolve_checkable(inter, track_attempts=True, attempt_key=inter.id, source_id=inter.id, source_type=source_type)` into local accumulators, then wrap into `ResolutionResult` as today. Keep the post-roll `check.passed`/`check.failed` emit at L1250-1266 (it carries the interaction-level `check_id` context) — or fold into `_resolve_checkable` and drop the duplicate; pick one, do not emit twice. |
| `_resolve_using_override` | L1396 | Unchanged: already builds a synthetic `Interaction` and delegates to `_resolve_interaction_check`. |
| `_fire_on_examine_events` | L1618-1658 | The `event.check` path keeps building a synthetic `Interaction` → `_resolve_interaction_check` (its `then_check` is now handled internally). The `event.result` (deterministic) path replaces `_apply_result` + the L1654 boilerplate with `_apply_result_with_check(event.result, source_id=f"_on_examine_{event.id}", source_type="examine", ...)`. The `skip_check_if` short-circuit at L1620 collapses into `_resolve_checkable`. |
| `_resolve_interaction_result` (result-only) | L1427 | Replace `_apply_result` + L1444 boilerplate with `_apply_result_with_check(result, source_id=source_id, source_type=source_type, ...)`. |
| `dispatch_reactions` (`event_bus.py`) | L214-231 | Replace the manual `_apply_result` + `_resolve_chained_check` block with `_apply_result_with_check(resolved.result, source_id=reaction.id, source_type="reaction", ...)`. Drop the `resolution_for_chain = ResolutionResult(success=True)` scaffolding (L214-215) — no longer needed; `_resolve_checkable` emits events directly when `resolution` is passed. |
| `_resolve_traversal_check` | L1142 | **Required fix:** traversal rolls and returns `bool`; its `success`/`failure` `Result`s are applied by the caller. Verify and fix the caller routes those `Result`s through `_apply_result_with_check` so their `then_check` fires (today it is unclear whether traversal `then_check`s dispatch at all — if broken, this is a bugfix, not a refactor). If the caller uses bare `_apply_result`, upgrade it to `_apply_result_with_check`. Optionally refactor `_resolve_traversal_check` itself to call `_resolve_checkable(..., apply_branch=False)` — secondary, not required for this pass. |

**Deleted functions:** `_resolve_chained_check` (L976),
`_resolve_roll_check_chain` (L1023), `_resolve_stat_check_chain` (L1077),
`_resolve_roll_check` (L1271), `_resolve_stat_check` (L1326). Also drop the
`ChainedCheck` import at `resolver.py:38`.

**Import in `event_bus.py`:** update
`from mgmai.engine.resolver import _apply_result, _resolve_chained_check, ResolutionResult`
(`event_bus.py:211`) to `from mgmai.engine.resolver import _apply_result_with_check, ResolutionResult`.

### Roll-dict shape

Rationalize in one pass: every roll dict gets `source_id`, `source_type`,
`check_type`, plus type-specific `stat`/`dc` or `threshold`. Drop the
chain-vs-interaction distinction (`check_id` present vs absent). Update test
assertions on roll dict keys. This is enabled by D4 (explicit `source_type`
threading).

## Schema changes (`schema/corpus.md`)

| Location | Change |
|---|---|
| L38 | "conditions, checks, results, and chained checks" → "...results, and follow-up checks". |
| L201 | `"chain_check": { /* chained check (optional) */ }` → `"then_check": { /* follow-up check (optional) */ }`. |
| L217 | Result table row: `chain_check` → `then_check`; rename link target. |
| L220-257 | Rewrite the "#### Chained check (`chain_check`)" section as "#### Follow-up check (`then_check`)". Rename the type to `CheckResolution`. Update the example JSON keys (`chain_check` → `then_check`). Update the field table (`check`, `skip_check_if`, `success`, `failure` — now inherited from `Checkable`). Update the nesting note: "Nested follow-ups are supported — a `then_check`'s `Result` may itself contain a `then_check`, up to a maximum depth of 3." |
| L438 | "Results may carry `set_flag`, `alter_stat`, `add_item`, and `chain_check` like any other result." → `...and `then_check`...`. |
| L567 | Reaction-effects `result` row: update the field list to use `then_check`. |
| L961 | Dialogue path results: update the field list to use `then_check`. |

Add a short "Common check-bearing types" note near the `Checkable` definition
explaining that `Interaction`, `DialoguePath`, `OnExamineEvent`,
`TraversalCheck`, `TakeCheck`, and `CheckResolution` all share the
`(skip_check_if, check, success, failure)` quartet via `Checkable`.

## Adventure data migration (`adventures/bag-of-holding/corpus.json`)

Mechanical rename only — `chain_check` → `then_check` at 5 sites. No
structural change. Pattern A (L863, L897) and Pattern B (L972, L999, L1317)
both remain valid as-is.

| Line | Pattern | Content |
|---|---|---|
| L863 | A | `insert_key_into_padlock` failure → DEX save to catch key |
| L897 | A | same, inside `using_results.korbar` override |
| L972 | B | reaction on `flag.set: rip_examined` → INT check to recognize Astral Plane |
| L999 | B | reaction on `flag.set: astral_plane_recognized` → INT check to realize Bag of Holding |
| L1317 | B | reaction on `room.entered` → WIS check to notice spider |

## Test changes

Only `tests/test_event_bus.py` references `ChainedCheck` / `chain_check`
directly (3 tests):

| Line | Test | Change |
|---|---|---|
| L735 | `test_chain_check_in_reaction_emits_event` | Rename to `test_then_check_in_reaction_emits_event`; `from ... import ChainedCheck` → `CheckResolution`; `chain_check=ChainedCheck(...)` → `then_check=CheckResolution(...)`. |
| L839 | (recursive dispatch test) | Same rename; verify the depth/recursion assertion still holds. |
| L964 | `test_dialogue_path_result_chain_check_emits_event` | Rename to `..._then_check_...`; same import/field rename. |

**New tests to add** (in `tests/test_resolver.py` or `tests/test_event_bus.py`):

1. **Depth cap.** A `then_check` nested 4 deep stops at depth 3 and logs a
   warning (no test exercises this today — D7).
2. **`source_type` inheritance.** A `then_check` inside an interaction's
    failure branch emits `check.passed`/`check.failed` with
    `source_type="interaction"` and the interaction's `source_id`. Also:
    verify a `then_check` inside a **reaction** result retains
    `source_type="reaction"`, and inside an **examine** event result retains
    `source_type="examine"` (verifies D4 for all parent types — currently
    some paths would default to `"reaction"`/`"unknown"`).
3. **`then_check` on a deterministic `result`-only interaction** fires
   (covers the `_resolve_interaction_result` path).
4. **`then_check` on an on-examine `result`** fires (covers the L1654 path).

**Test-assertion updates:** any assertion on roll-dict keys (`check_id`
present/absent) must match the rationalized roll-dict shape from the
"Roll-dict shape" section. Grep `tests/` for `"check_id"` and `"rolls"`
assertions.

## Doc changes

| File | Lines | Change |
|---|---|---|
| `schema/events.md` | L81 | "`source_type: "reaction"` is used when a `chain_check` inside a reaction result produces the event" → "...when a `then_check` inside a reaction result produces the event". Note `source_type` is now inherited from the parent resolution context (D4), so a `then_check` inside an interaction emits `source_type="interaction"`. |
| `schema/events.md` | L125 | "check.passed/check.failed from `chain_check`" → "from `then_check`". |
| `schema/scenario-generation.md` | L1873, L1896, L2000, L2007 | Rename `chain_check` → `then_check`, "Chained check" → "Follow-up check". Update the depth-limit note (L2000) and the "does not trigger game-over directly" note (L2007). |

## Verification

The project configures only `pytest` (`pyproject.toml` L29-30; no ruff/mypy).
Run from the repo root:

```
pytest
```

Specifically:
- Full suite green after each phase.
- The 3 renamed `test_event_bus.py` tests pass.
- The 4 new tests pass.
- `adventures/bag-of-holding` loads cleanly (corpus validation) — covered by
  the existing corpus/asm tests; run `pytest tests/test_corpus.py
  tests/test_assembler.py tests/test_bag_of_holding_webs.py`.
- Manually sanity-play the `insert_key_into_padlock` interaction (Pattern A)
  and the `notice_spider_on_entry` reaction (Pattern B) to confirm `then_check`
  resolution and event emission behave as before.

If a lint/typecheck command exists later, add it here and to `AGENTS.md`.

## Task ordering

**Phase 1 — Pure rename (low risk, lands first).**
1. `models/corpus.py`: `ChainedCheck` → `CheckResolution`; `Result.chain_check` → `then_check`; update `has_any_effect`.
2. `resolver.py` + `event_bus.py`: rename all references (`chain_check` → `then_check`, `ChainedCheck` → `CheckResolution`, `MAX_CHAIN_CHECK_DEPTH` → `MAX_THEN_CHECK_DEPTH`). Keep logic identical.
3. `adventures/bag-of-holding/corpus.json`: rename the 5 sites.
4. `tests/test_event_bus.py`: rename the 3 tests' references.
5. `schema/corpus.md`, `schema/events.md`, `schema/scenario-generation.md`: rename.
6. Rename internal code comments referencing "chain_check" or "chained check" in `mgmai/` and `tests/`.
7. `pytest` green.

**Phase 2 — Resolver unification (the big win).**
7. Add `_apply_result_with_check` and `_resolve_checkable`.
8. Rewire the 6 call sites per the table above; delete the 5 old functions.
9. Rationalize roll-dict shape; fix roll-dict test assertions.
10. Add the 4 new tests (depth cap, source_type inheritance, result-only interaction then_check, on-examine result then_check).
11. Verify/fix the traversal `then_check` latent gap.
12. `pytest` green.

**Phase 3 — Shared `Checkable` base (polish).**
13. Add `Checkable` to `models/corpus.py`; make the six models inherit it; delete duplicated field declarations; tighten `check`/`success` optionality per model.
14. Add the "Common check-bearing types" note to `schema/corpus.md`.
15. `pytest` green.

Phases are independently shippable. Phase 1 is mechanical and should land
first to shrink the diff of Phase 2. Phase 3 is optional polish that can be
deferred without affecting Phase 1+2 correctness.
