# Plan: Consolidate `EncounterRule` and `BranchOutcome` into `Checkable` and `Result`

## Preamble

The encounter system (`EncounterRule`, `BranchOutcome`) was designed before
the resolution primitives (`Checkable`, `Resolvable`, `CheckResolution`,
`Result`) were extracted and formalized.  As a result, it contains its own
ad-hoc versions of concepts that now have clean, shared abstractions
elsewhere in the codebase.

### The duplication

**`BranchOutcome`** (`corpus.py:368`) is a near-exact subset of **`Result`**
(`corpus.py:126`):

```
BranchOutcome                  Result
-----------                    ------
outcome: str = "none"          game_over / trigger_combat   (dispatch, see below)
narrative: str?                narrative: str?        ✓ same
set_flag: Dict?                set_flag: Dict?        ✓ same
alter_stat: Dict?              alter_stat: Dict?      ✓ same
player_damage: str?            player_damage: str?    ✓ same
                               add_item, remove_item, set_entity_state,
                               set_room_state, adjust_attitude, reveals,
                               then_check, set_player_location  (extra fields)
```

`BranchOutcome`'s only non-effect field is `outcome` — a string tag
(`"death"`, `"flee"`, `"combat"`, `"none"`) that tells the caller what to do.
This plan moves that dispatch role onto `Result` itself via two optional
fields (`game_over`, `trigger_combat`), so `Result` becomes a strict
superset of `BranchOutcome` and the latter can be deleted.

**`EncounterRule`** (`corpus.py:376`) duplicates much of **`Checkable`**
(`corpus.py:172`):

```
EncounterRule (current)        Checkable
-------------                  ---------
condition: ConditionExpr       (none — added by subclasses; Resolvable has it)
outcome: "death"|"flee"|...    (dispatch — moved to Result.game_over/trigger_combat)
check: StatCheck?              check: CheckType?          ✓ same role, wider type
threshold: float?              (folded into RollCheck.threshold)
success: BranchOutcome?        success: Result?           ✓ same role
failure: BranchOutcome?        failure: Result?           ✓ same role
narrative, set_flag,           (carried by Result — rule-level effect fields
 alter_stat, player_damage      move into `result`; see "Rule-level effects" below)
```

### The `outcome` tag's two roles

1. **Selects resolution strategy** — `"roll"` and `"stat_check"` mean "use a
   check."  This is already encoded by the *presence* of a `check` field:
   `Checkable` resolves the check when `check` is set, applies `result` when
   it isn't.  The separate `threshold` field for `"roll"` is folded into a
   `RollCheck` (so `EncounterRule.check` widens from `StatCheck` to the
   shared `CheckType = RollCheck | StatCheck`).

2. **Dispatch signal** — `"death"` and `"combat"` tell the engine what to do
   after the rule fires.  Tracing `engine.py:255-282` and `event_bus.py:385-469`,
   the engine acts on exactly two signals:
   - `"combat"` → enter combat mode (`engine.py:282`, `event_bus.py:457`),
     keyed on the string `enc_result["outcome"] == "combat"`.
   - `"death"` → impose game-over, keyed on the presence of the
     `enc_result["game_over"]` dict (populated by the resolver when the
     outcome is death) — *not* on the outcome string (`engine.py:255`,
     `event_bus.py:452`).
   - `"flee"` applies effects and continues (no special dispatch).

   Crucially, the current `outcome` tag lives on **both** the rule and the
   branch (`BranchOutcome.outcome`), so a *branch* can signal combat or
   death (e.g. `success.outcome="combat"` / `failure.outcome="death"`).  This
   is exercised by `TestEncounterBranchCombat` (`tests/test_encounters.py:334`)
   and by the fixtures spider rule #2 (`tests/fixtures/corpus.json:408-430`,
   `failure.outcome="death"`).  Any redesign must preserve branch-level
   dispatch — which is why the dispatch signals are put on `Result`, not on
   rule-level booleans (see Design).

### The cost

- `BranchOutcome` is a 6-line model + ~40 lines of test — dead weight once
  `Result` carries the dispatch fields.
- `EncounterRule` has its own check resolver (`_apply_encounter_rule`, 190
  lines) that hand-rolls a result dict for each of `death`/`flee`/`combat`/
  `stat_check`/`roll`, with the `stat_check` and `roll` arms being
  near-duplicates of each other.
- A separate `_resolve_encounter_stat_check` (31 lines) reimplements the
  `system.roll_check` wiring already present in `resolver.py`.
- The `outcome` enum adds conceptual overhead: adventure authors choose from
  5 literals instead of reasoning about one pattern (`check` → branches, or
  `result` → direct).
- When a check-bearing rule fires, the resolver *merges* the rule's own
  `narrative`/`set_flag`/`alter_stat`/`player_damage` with the branch's — an
  interaction the `Checkable` primitives don't have, because they don't need
  it once rule-level effects move into `result`.

## Design

### `Result` gains two optional dispatch fields

```python
class Result(BaseModel):
    ...existing effect fields...
    game_over: Optional[GameOverTrigger] = None   # reuses corpus.py:280
    trigger_combat: bool = False

    def has_any_effect(self) -> bool:
        # add game_over / trigger_combat so a dispatch-only Result counts
        return any(...) or self.game_over is not None or self.trigger_combat
```

`GameOverTrigger` (`corpus.py:280`, `type: Literal["win","lose"]`,
`trigger_id: str`) is the primitive already used by `ReactionEffects.game_over`
(`corpus.py:289`), so "a result ends the game" becomes one concept everywhere.
Both fields default off, so every existing `Result` instance (interactions,
dialogue paths, on_examine, traversal, take_check, reactions, `then_check`)
loads unchanged.

### `EncounterRule` becomes a `Checkable` subclass

```python
class EncounterRule(Checkable):
    """An ordered encounter resolution node.

    When condition matches:
    - If ``check`` is set, resolve it (roll or stat check) and apply the
      chosen branch's Result (success/failure).
    - Otherwise apply ``result`` directly.
    Either branch Result or the rule's ``result`` may carry ``trigger_combat``
    or ``game_over`` to dispatch combat / game-over to the engine.
    """
    condition: ConditionExpression            # required (Checkable has none)
    result: Optional[Result] = None
    # inherited from Checkable:
    #   skip_check_if: Optional[ConditionExpression]
    #   check: Optional[CheckType]            # RollCheck | StatCheck
    #   success: Optional[Result]
    #   failure: Optional[Result]

    @model_validator(mode="after")
    def check_xor_result(self) -> "EncounterRule":
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check == has_result:  # both or neither
            raise ValueError(
                "EncounterRule must have exactly one of 'check' or 'result'")
        return self
```

Notes:
- `Checkable` has **no** `condition` or `result` field (those first appear on
  `Resolvable`), so both are declared explicitly here.  `Resolvable` is *not*
  used as the base because its validator requires `success` whenever `check`
  is set and forbids `check`+`result` together with `success`-required
  semantics that don't fit encounters (an encounter may legitimately have a
  `check` with no `success` branch).  The custom validator above keeps just
  the check-XOR-result invariant.
- `BranchOutcome` is removed entirely — `success`/`failure` already accept
  `Result`, which is now a strict superset.
- `outcome`, `threshold`, and the rule-level `narrative`/`set_flag`/
  `alter_stat`/`player_damage` fields are removed (see below).

### Rule-level effect fields

The rule-level `narrative`/`set_flag`/`alter_stat`/`player_damage` on
check-bearing rules were a *fallback* used only when the matching branch was
absent (`encounters.py:128, 138, 191, 206`: `branch.narrative if branch else
rule.narrative`).  In every existing rule, both branches are present with
their own narratives, so the rule-level values were never shown — they are
effectively dead.  Migration therefore drops them (or folds them into the
relevant branch Result where a branch is genuinely absent).  For non-check
rules, the rule-level effects move into `result`.

### How dispatch propagates

The encounter resolver picks the **firing Result** — `success`/`failure`
when `check` is set, else `result` — applies its effects via the shared
`_apply_result` helper, and reads `result.trigger_combat` / `result.game_over`
off that same object to populate the engine-facing dict.  Because the signals
live on `Result`, they are naturally per-branch:

| Case | Shape |
|------|-------|
| Rule-level combat | `result: {narrative, trigger_combat: true}` |
| Rule-level death | `result: {narrative, game_over: {type: "lose", trigger_id: "spider"}}` |
| Branch-level death | `failure: {narrative, game_over: {type: "lose", trigger_id: "spider"}}` |
| Branch-level combat | `success: {narrative, trigger_combat: true}`, `failure: {narrative}` |

`trigger_id` is authored explicitly (as reactions already do); for migrated
encounter rules it is set to the npc_id, preserving the current resolver
behavior of defaulting the trigger to `npc_id or "encounter"`.

### JSON format changes

Before (flee, no check):
```json
{
  "condition": {"require": "flag:has_weapon == true"},
  "outcome": "flee",
  "narrative": "The creature flees!",
  "set_flag": {"creature_fled": true}
}
```
After:
```json
{
  "condition": {"require": "flag:has_weapon == true"},
  "result": {"narrative": "The creature flees!", "set_flag": {"creature_fled": true}}
}
```

Before (check-based, branch-level death — the fixtures spider #2 case):
```json
{
  "condition": {"require": "flag:injured == true"},
  "outcome": "roll",
  "threshold": 0.5,
  "narrative": "You struggle...",
  "success": {"outcome": "flee", "set_flag": {"spider_fled": true}, "narrative": "It flees."},
  "failure": {"outcome": "death", "narrative": "You die."}
}
```
After:
```json
{
  "condition": {"require": "flag:injured == true"},
  "check": {"type": "roll", "threshold": 0.5, "repeatable": true},
  "success": {"set_flag": {"spider_fled": true}, "narrative": "It flees."},
  "failure": {"narrative": "You die.", "game_over": {"type": "lose", "trigger_id": "spider"}}
}
```
(The rule-level `narrative` "You struggle..." is dropped — it was a fallback
never shown when both branches have narratives.  `repeatable` is now required
by `RollCheck`, so migrated roll rules must add it.)

Before (rule-level combat):
```json
{
  "condition": {"require": "entity:spider.alive == true"},
  "outcome": "combat",
  "narrative": "The spider drops from the shadows!"
}
```
After:
```json
{
  "condition": {"require": "entity:spider.alive == true"},
  "result": {"narrative": "The spider drops from the shadows!", "trigger_combat": true}
}
```

Before (branch-level combat — `TestEncounterBranchCombat`):
```json
{
  "condition": {"require": "entity:player.alive == true"},
  "outcome": "stat_check",
  "check": {"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": true},
  "success": {"outcome": "combat", "narrative": "It attacks!"},
  "failure": {"outcome": "flee", "narrative": "It flees."}
}
```
After:
```json
{
  "condition": {"require": "entity:player.alive == true"},
  "check": {"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": true},
  "success": {"narrative": "It attacks!", "trigger_combat": true},
  "failure": {"narrative": "It flees."}
}
```

### Resolver simplification

`_apply_encounter_rule` collapses to:

1. (Done by `resolve_encounter`'s loop.) Evaluate `condition`; first match wins.
2. Determine the firing `Result`: if `rule.check` is set, resolve the check
   and pick `rule.success` or `rule.failure` (either may be `None`); else
   `rule.result`.
3. Apply the firing Result's effects via the shared `_apply_result`
   (`_apply_result_with_check` if `then_check` recursion is desired for
   encounter branches — a newly available capability).
4. Read `result.trigger_combat` / `result.game_over` off the firing Result to
   set `enc_result["trigger_combat"]` / `enc_result["game_over"]`; record
   `branch_taken` when a check fired.
5. Return the dict.

`_resolve_encounter_stat_check` is deleted; the check is resolved by the same
`system.roll_check` path used in `resolver.py`.  To preserve current encounter
semantics, the encounter resolver calls the effect-application helpers
directly rather than the full `_resolve_checkable` dispatcher — i.e. **no
`check.passed`/`check.failed` events** and **no `repeatable` attempt-tracking**
(`track_attempts=False`), matching today's behavior where encounters ignore
`repeatable` and emit no check events.  `skip_check_if` is inherited from
`Checkable` and honored by the resolver (bypass check, apply `success`) — a
new, opt-in capability for encounter rules.

The returned dict changes shape: drop `outcome` (string); add
`trigger_combat: bool`; keep `game_over` (now sourced from
`Result.game_over`, mapped to `{"type", "trigger"}` so the existing
`GameOverState`/`GameOverResult` consumers — which read `go["trigger"]` —
need **no** change for death), `narrative`, `set_flags`, `alter_stat`,
`player_damage`, `rolls`, `branch_taken`.

### Scope note: `then_check` and non-encounter consumers

`game_over`/`trigger_combat` are honored on the **directly-firing** Result
(rule `result` or `success`/`failure` branch).  Signals on a *nested*
`then_check` Result are not yet surfaced by the encounter resolver, and
other `Resolvable` consumers (interact/talk/examine/traverse/transfer)
ignore these fields for now.  Closing either gap later means extending
`_apply_result` to propagate the signals onto `ResolutionResult` (which
already carries `combat_triggered` and `game_over_trigger`).  No existing
rule uses `then_check` inside an encounter, so this is forward-looking, not
a migration concern.

## File-change inventory

| File | Change |
|------|--------|
| `mgmai/models/corpus.py` | Add `game_over: Optional[GameOverTrigger]` and `trigger_combat: bool = False` to `Result` (`:126`); update `has_any_effect` to count them. Remove `BranchOutcome` (`:368`). Redefine `EncounterRule` (`:376`) as a `Checkable` subclass with `condition` (required), `result: Optional[Result]`, and a check-XOR-result validator; remove `outcome`, `threshold`, rule-level `narrative`/`set_flag`/`alter_stat`/`player_damage`; widen `check` from `StatCheck` to inherited `CheckType`. (`GameOverTrigger` at `:280` is reused as-is.) |
| `mgmai/engine/encounters.py` | Rewrite `_apply_encounter_rule` to pick firing Result, apply via shared `_apply_result`, surface `trigger_combat`/`game_over`/`branch_taken`. Delete `_resolve_encounter_stat_check`; resolve checks via shared `system.roll_check` path (`track_attempts=False`, no check events). Return dict: drop `outcome`, add `trigger_combat`; map `Result.game_over` → `{"type","trigger"}`. |
| `mgmai/engine/engine.py` | Replace `enc_result["outcome"] == "combat"` → `enc_result["trigger_combat"]` (`:282`, `:341`). Update `EncounterOutcome` construction (`:264-268`) and `encounter.branched` payload (`:276`). Death handling (`:255-262`) unchanged. |
| `mgmai/engine/event_bus.py` | Replace `enc_result["outcome"] == "combat"` → `enc_result["trigger_combat"]` (`:457`). Update encounter event payload (`:478`). Death handling (`:452-454`) unchanged. |
| `mgmai/models/actions.py` | `EncounterOutcome` (`:256`): replace `outcome: str` with `combat: bool = False` and `branch_taken: Optional[str] = None`; keep `encounter_id`, `narrative_brief`. |
| `schema/corpus.md` | Remove `BranchOutcome` table (`:1164-1173`). Rewrite `EncounterRule` docs in **both** the Aggro section (`:1127-1184`) and the Mechanic/Encounter section (`:1256-1279`): `Checkable` inheritance, `condition`+`result`, `check`/`success`/`failure`, and `Result.game_over`/`trigger_combat`. |
| `schema/actions.md` | Update `encounter_outcome` example/shape (`:665-715`). |
| `schema/scenario-generation.md` | Update `EncounterRule`/`BranchOutcome` examples and tables (`:990-1004`, `:1412-1446`). |
| `doc/npcs.md`, `doc/combat.md` | Update aggro `outcome` examples (`:370-380`, `:296`). |
| `mgmai/templates/prose.j2` | `encounter_outcome` row (`:38`) is field-level generic; verify wording still fits the structured shape (likely no code change). |
| `adventures/bag-of-holding/corpus.json` | Migrate the spider `aggro` rule (`:164-172`, `outcome: combat` → `result.trigger_combat`) **and** the three `Mechanic.rules` fall_damage rules (`:1634`, `:1671`, `:1704`, `outcome: roll`+`threshold` → `check: {type: roll, ...}` with `repeatable`). 4 rules total, not 1. |
| `tests/fixtures/corpus.json` | Migrate spider's 3 aggro rules (`:392-438`) and korbar's 2 aggro rules (`:609-626`): restructure into `result` / `check`+`success`+`failure`; move branch `outcome: death` → `failure.game_over`, branch `outcome: flee` → plain Result; rule-level `outcome: death` → `result.game_over`. No new mechanic or flag needed. 5 rules total across 2 NPCs. |
| `tests/helpers.py` | Update the encounter-outcome helper (`:249`, `:287`) from `encounter_outcome: str` to `combat: bool` (callers passing `"combat"` → `combat=True`, `"flee"`/`"roll"` → `combat=False`). |
| `tests/test_corpus.py` | Remove `BranchOutcome` import/tests (`:760-799`). Update `TestEncounterRule` (`:870-934`) for the new shape. |
| `tests/test_encounters.py` | Update all assertions: `result["outcome"]` → `result["trigger_combat"]` / `result["game_over"]` / `result["branch_taken"]`; `outcome="..."` and branch `outcome="..."` in rule construction → `result`/`trigger_combat`/`game_over`. `TestEncounterBranchCombat` (`:334`) now uses `success.trigger_combat`. |
| `tests/test_engine.py` | Update `encounter_outcome="roll"` helper usage (`:79`) and any `.outcome == "combat"` assertions. |
| `tests/test_event_bus.py` | Update encounter-outcome assertions. |
| `tests/test_resolver.py` | Update `encounter_outcome="flee"`/`"combat"` helper usage (`:265`, `:280`). |
| `tests/test_actions.py` | Update `test_with_encounter_outcome` (`:295-307`) to the structured `EncounterOutcome`. |
| `tests/test_bag_of_holding_webs.py` | Update if it references encounter outcomes. |

## Task ordering

1. **Model** — `mgmai/models/corpus.py`:
   - Add `game_over` + `trigger_combat` to `Result`; update `has_any_effect`.
   - Remove `BranchOutcome`.
   - Redefine `EncounterRule(Checkable)` with `condition`, `result`,
     check-XOR-result validator; remove `outcome`/`threshold`/rule-level
     effect fields; widen `check` to `CheckType`.
2. **Resolver** — `mgmai/engine/encounters.py`:
   - Rewrite `_apply_encounter_rule` (pick firing Result → apply via
     `_apply_result` → surface `trigger_combat`/`game_over`/`branch_taken`).
   - Delete `_resolve_encounter_stat_check`; use shared `system.roll_check`
     (`track_attempts=False`, no check events).
   - Return dict: drop `outcome`, add `trigger_combat`, map `game_over`.
3. **Consumers** — `engine.py`, `event_bus.py`, `actions.py`:
   - `outcome == "combat"` → `trigger_combat` (engine `:282`,`:341`; event_bus `:457`).
   - `EncounterOutcome`: `outcome: str` → `combat: bool` + `branch_taken`.
   - Update construction sites and `encounter.branched` payloads.
   - Death handling unchanged.
4. **JSON data** — migrate all `EncounterRule` instances:
   - `adventures/bag-of-holding/corpus.json` — 1 `aggro` rule + 3 `Mechanic.rules` fall_damage rules.
   - `tests/fixtures/corpus.json` — 5 `aggro` rules (spider 3, korbar 2).
5. **Schema/docs** — `schema/corpus.md` (Aggro + Mechanic/Encounter),
   `schema/actions.md`, `schema/scenario-generation.md`, `doc/npcs.md`,
   `doc/combat.md`; verify `prose.j2`.
6. **Tests** — update `test_corpus.py`, `test_encounters.py`, `test_engine.py`,
   `test_event_bus.py`, `test_resolver.py`, `test_actions.py`,
   `test_bag_of_holding_webs.py`, and `tests/helpers.py`.
7. `pytest` green.
