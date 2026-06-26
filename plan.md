# Plan: Unified GatedCheck Pattern

## Problem

The schema has seven features that all express "conditionally fire a check,
with different outcomes on success vs failure," but each does it differently:

| Feature | Gate field | `skip_check_if`? | Success key | Failure key | Failure shape |
|---|---|---|---|---|---|
| `traversal_check` | `gating` | yes | implicit / `success` | `failure_narrative` | bare string |
| `take_check` | `gating` | **no** | `success` | `failure` | Result |
| `interaction` | `condition` | **no** | `success` | `failure` | Result |
| `on_examine` | `condition` | **no** | `success` | `failure` | Result |
| `dialogue_path` | `condition` | **no** | `success` | `failure` | Result |
| Encounter rule | `condition` | **no** | `on_success` | `on_failure` | BranchOutcome |
| `chain_check` | (none) | **no** | `success` | `failure` | Result |

Three root causes:

1. `skip_check_if` was added to traversal_check (the first place that needed it)
   but never propagated to later features. The clearable-obstacle pattern is
   generic; it applies equally to "STR check to pull sword from stone" as
   "STR check to force through webs."

2. `traversal_check` uses `failure_narrative` (bare string) while everything
   else uses `failure` (Result object). A failed traversal can't set flags,
   deal damage, chain a check, or modify state.

3. Encounter rules use `on_success`/`on_failure` while everything else uses
   `success`/`failure`. Also: `set_flags` (plural) vs `set_flag` (singular).

The trigger was the inability to cancel a `take_check` once a condition is met
(cf. scenario-generation.md line 646).

---

## Unified Primitive: GatedCheck

```json
{
  "gating":         <ConditionObject>,   // optional — gates whether check is required (take_check, traversal_check)
  "condition":      <ConditionObject>,   // optional — gates action/event eligibility (interaction, on_examine, dialogue_path)
  "skip_check_if":  <ConditionObject>,   // optional — bypass check, proceed to success
  "check":          <CheckType>,         // the roll or stat_check
  "success":        <Outcome>,           // result on success (or when skip_check_if met)
  "failure":        <Outcome>            // result on failure
}
```

- `gating` gates whether the check fires (take_check, traversal_check).
  When false, the action proceeds normally without a check.
- `condition` gates whether the action/event is available at all (interaction,
  on_examine, dialogue_path). When false, the action is hidden or the event
  does not fire.
- `skip_check_if`: if met, the check is skipped entirely and execution
  proceeds as if `success` occurred.
- `<Outcome>` is a `Result` object for `take_check`, `interaction`,
  `on_examine`, `dialogue_path`, `traversal_check`, and `chain_check`.
  For encounter rules it is a `BranchOutcome`.

### Evaluation order

Every gated check resolves in this order:

1. If `skip_check_if` is present and true → apply `success`, skip the roll.
2. Else if the gate field (`gating` or `condition`) is present and false →
   context-specific no-check behavior (see Contextual semantics below).
3. Else → roll `check`, apply `success` or `failure`.

---

## Per-Feature Changes

### 1. `take_check` — add `gating`, `skip_check_if`

Currently:
```json
"take_check": {
  "check": { "type": "stat_check", "stat": "STR", "dc": 17, "repeatable": true },
  "success": { "narrative": "You pull the sword from the stone." },
  "failure": { "narrative": "It won't budge." }
}
```

After:
```json
"take_check": {
  "gating": { "require": "flag:sword_claimed == false" },
  "skip_check_if": { "require": "inventory:gauntlets_of_strength" },
  "check": { "type": "stat_check", "stat": "STR", "dc": 17, "repeatable": true },
  "success": { "narrative": "...", "set_flag": { "sword_claimed": true } },
  "failure": { "narrative": "..." }
}
```

- `gating`: optional. When present and not met, the check does not fire
  (item is taken freely, as if there were no `take_check`).
- `skip_check_if`: optional. When met, the check is bypassed and the item is
  taken with the `success` Result applied.

### 2. `take_check` — NO `using_results`

The `transfer` action has no `using` parameter. Tool-gated taking is better
expressed as a two-step interaction flow (interaction reveals + take_check
handles pickup) or via `skip_check_if` with `inventory:` / `tag:` conditions.

### 3. `traversal_check` — replace `failure_narrative` with `failure` (Result)

`traversal_check.gating` is the field name for consistency with `take_check.gating`. It gates whether the check is required, not traversability.

Currently:
```json
"traversal_check": {
  "condition": { "unless": "flag:webs_cleared == true" },
  "check": { "type": "stat_check", "stat": "STR", "dc": 14 },
  "skip_check_if": { "require": "flag:webs_cleared == true" },
  "failure_narrative": "You strain against the sticky webs."
}
```

After:
```json
"traversal_check": {
  "gating": { "unless": "flag:webs_cleared == true" },
  "check": { "type": "stat_check", "stat": "STR", "dc": 14 },
  "skip_check_if": { "require": "flag:webs_cleared == true" },
  "failure": { "narrative": "You strain against the sticky webs." }
}
```

- `gating` is optional. When present and false, traversal proceeds without
  a check and without applying any Result.
- `failure` is now a full Result object. All existing adventures convert
  `"failure_narrative": "..."` to `"failure": { "narrative": "..." }`.
- Optional `success` Result for traversal-success narrative (e.g., first-time
  flavor text). Richer traversal effects still use `traversal.succeeded`
  reactions — don't overload the traversal_check with game logic.

### 4. `interaction` — add `skip_check_if`

Already has `condition`, `check`, `success`, `failure`. Add `skip_check_if`
as an optional field that bypasses the check when met.

### 5. `on_examine` — add `skip_check_if`

Already has `condition`, `check`, `success`, `failure`. Add `skip_check_if`
as an optional field that bypasses the check when met.

### 6. `dialogue_path` — add `skip_check_if`

Already has `condition`, `check`, `success`, `failure`. Add `skip_check_if`
as an optional field that bypasses the check when met.

### 7. Encounter rules — rename `on_success`/`on_failure` to `success`/`failure`

- Entity-level `behavior.encounter_rules[].on_success` → `success`
- Entity-level `behavior.encounter_rules[].on_failure` → `failure`
- Mechanic-level `rules[].on_success` → `success`
- Mechanic-level `rules[].on_failure` → `failure`
- Also: `set_flags` → `set_flag` (consistent with Result objects)

**Risk:** This is the most invasive change. It touches the `EncounterRule` and
`BranchOutcome` models, `encounters.py`, the callers in `engine.py` and
`event_bus.py`, every existing encounter corpus, and the encounter tests. The
project is pre-1.0, so a hard rename is acceptable, but it requires a global
find/replace and test updates.

Encounter rules do NOT get `skip_check_if`: their top-to-bottom evaluation by
`condition` already handles conditional bypass naturally (add a prior rule
with a catch-all condition).

### 8. `chain_check` — add `skip_check_if`

Already has `check`, `success`, `failure`. Add `skip_check_if` as optional.

---

## Contextual Gate Semantics

The gate field (`gating`) has context-specific meaning.
This table must be included in `schema/corpus.md`:

| Feature | Gate field | Gate false means... | `skip_check_if` true means... |
|---|---|---|---|
| `take_check` | `gating` | Item taken freely, no Result applied | Item taken, `success` Result applied |
| `interaction` | `condition` | Interaction unavailable | `success` Result applied without roll |
| `on_examine` | `condition` | Event does not fire | `success` Result applied without roll |
| `dialogue_path` | `condition` | Path unavailable | `success` Result applied without roll |
| `traversal_check` | `gating` | Traversal succeeds without check | Traversal succeeds, `success` Result applied |
| `chain_check` | (none) | Chain skipped | `success` Result applied without roll |
| Encounter rule | `condition` | Rule skipped, next rule evaluated | N/A (not added) |

## What Does NOT Change (Intentionally)

- **`traversal_check` and `take_check` use `gating`, not `condition`.** Their
  semantics ("only require the check when true, otherwise allow the action
  without a check") differ from `condition` on interactions ("hide the
  interaction"). Distinct naming avoids author confusion.

- **Encounter branches remain `BranchOutcome`** (not `Result`), because they
  carry `outcome: "death" | "flee" | "combat"` as a mechanical resolution,
  not just narrative effects.

- **`using_results` stays on `traversal_check` and `interaction` only.** Not
  added to `take_check`, `on_examine`, or `dialogue_path`. `take_check` in
  particular does not get `using_results` because the `transfer` action has no
  `using` parameter.

- **`will_reveal.conditions` stays as bare strings.** This is a separate
  structure for LLM-surfaced data, not a checked outcome pattern.

---

## Files Affected

| File | Changes |
|---|---|
| `mgmai/models/corpus.py` | **Primary source of truth.** Add `gating`/`skip_check_if` to `TakeCheck`; rename `TraversalCheck.condition`→`gating`, `failure_narrative`→`failure`; add optional `success`; add `skip_check_if` to `Interaction`, `OnExamineEvent`, `DialoguePath`, `ChainedCheck`; rename `EncounterRule`/`BranchOutcome` `on_success`→`success`, `on_failure`→`failure`, `set_flags`→`set_flag`. |
| `mgmai/engine/resolver.py` | Evaluate `skip_check_if`/`condition`/`gating` for `take_check`, `traversal_check`, `interaction`, `on_examine`, `dialogue_path`, `chain_check`; handle `TraversalCheck.failure` Result and optional `success` Result. |
| `mgmai/engine/encounters.py` | Update `EncounterRule`/`BranchOutcome` field access (`success`, `failure`, `set_flag`). |
| `mgmai/engine/engine.py` | Update encounter result dict consumption (`set_flag`, branch keys). |
| `mgmai/engine/event_bus.py` | Update encounter result dict consumption (`set_flag`, branch keys). |
| `schema/corpus.md` | Update type definitions and field tables for all affected types; add contextual gate semantics table. |
| `schema/scenario-generation.md` | Update all examples and prose: `traversal_check.condition`→`gating`, `failure_narrative`→`failure`, `on_success`→`success`, `on_failure`→`failure`, `set_flags`→`set_flag`. Add `skip_check_if` examples. |
| `schema/events.md` | Update `encounter.branched` context prose if it references `on_success`/`on_failure`. |
| `tests/test_encounters.py` | Update `EncounterRule`/`BranchOutcome` construction and assertions. |
| `tests/test_resolver.py` | Update `TakeCheck`/`TraversalCheck` construction; add skip/gate tests. |
| `tests/helpers.py` | Update `_mk_encounter_rule` and traversal helpers. |
| `tests/test_bag_of_holding_webs.py` | Update assertions for `failure_narrative`→`failure`. |
| `tests/test_corpus.py` | Update any model-shape validation. |
| `adventures/bag-of-holding/corpus.json` | Convert `failure_narrative`→`failure`, `condition`→`gating` on traversal checks, `on_success`/`on_failure`/`set_flags` on encounter rules. |
| All other adventure modules | Same conversions as above. |

---

## Implementation Order

1. Update `mgmai/models/corpus.py` — add new fields and renames; this is the
   runtime source of truth and surfaces every caller that must change.
2. Update engine resolvers (`resolver.py`, `encounters.py`, `engine.py`,
   `event_bus.py`) — implement the new evaluation order and field names.
3. Update tests and helpers (`test_encounters.py`, `test_resolver.py`,
   `helpers.py`, `test_bag_of_holding_webs.py`, `test_corpus.py`).
4. Update existing adventure JSON modules (`bag-of-holding/corpus.json`, etc.).
5. Update schema documentation (`schema/corpus.md`, `schema/scenario-generation.md`,
   `schema/events.md`) to match the final code.
6. Run the full test suite: `pytest`
7. Run `python scripts/validate_adventure.py` on each adventure module.

### New tests to add

- `take_check.gating` false → item taken without check and without Result.
- `take_check.skip_check_if` true → `success` Result applied, no roll.
- `traversal_check.gating` false → traversal succeeds without check.
- `traversal_check.skip_check_if` true → traversal succeeds, `success` Result applied.
- `traversal_check.failure` Result can set flags, deal damage, chain checks.
- `interaction.skip_check_if` / `on_examine.skip_check_if` / `dialogue_path.skip_check_if`.
- `chain_check.skip_check_if`.
- Encounter rules with renamed `success`/`failure`/`set_flag` branches.
