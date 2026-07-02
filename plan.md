# Plan: Remove Game-Over Mechanic from the Mechanic type

## The problem with `Mechanic`

The `Mechanic` class (`mgmai/models/corpus.py:445`) is meant to be a named
bundle of game logic not tied to a specific room or entity. In practice it
conflates **three orthogonally different primitives** behind one undiscriminated
Pydantic model, distinguished only by which fields happen to be populated:

| Kind            | Discriminator       | Trigger model               | Purpose of `condition`       |
|-----------------|---------------------|-----------------------------|------------------------------|
| Game-Over       | `type` non-None     | **Poll-based** (every turn) | Termination predicate        |
| Encounter       | `rules` non-None    | **Event-driven**            | Gating: can encounter fire?  |
| Reaction-Only   | `reactions` present | **Event-driven** (always)   | (unused)                     |

The Game-Over kind does not belong with the other two. An Encounter or
Reaction-Only mechanic is **event-driven**: it sits idle until a reaction fires
`trigger_encounter`, or until its `on` event matches. A Game-Over mechanic is a
**passive predicate** — nothing triggers it. The engine polls it every turn in a
separate loop (`_check_game_over_mechanics`, `engine.py:839-855`), parallel to
and conceptually alien to the event system. One type, two execution models.

Three aggravating factors make this worse:

1. **The poll is mis-placed in the turn lifecycle.** It runs at `engine.py:377`,
   *before* deferred reactions, state-change events, and `turn.end` reactions
   (phases 7–9). So a game-over condition satisfied by a same-turn reaction —
   e.g. a `turn.end` poison that kills the player — is missed and only caught on
   the *next* turn. The predicate sees stale state.

2. **The schema documents a second game-over path that doesn't actually work.**
   `Result.game_over` is the natural, inline authoring idiom — a result declares
   "this outcome ends the game" right where the killing blow falls (documented at
   `corpus.md:224`, demonstrated in the aggro example at `corpus.md:1205`). But
   `_apply_result` (`resolver.py:1181-1270`) **silently drops `Result.game_over`**;
   only the encounter path extracts it (`encounters.py:123`). So for interactions
   and reactions, the inline idiom is broken — proven by
   `test_result_with_game_over_does_not_crash` (`test_event_bus.py:1321`), which
   asserts `engine_result.game_over is None`. This breakage has forced authors to
   fall back on the polled Game-Over Mechanic as a workaround, even for outcomes
   that have a perfectly natural inline home.

3. **Type confusion in the docs.** `corpus.md` types both `Result.game_over`
   (line 224) and `ReactionEffects.game_over` (line 807) as `Mechanic`, when
   both are actually `GameOverTrigger` (`corpus.py:282`). The polled
   `Mechanic.type`/`trigger_id`/`narrative` and the inline `GameOverTrigger`
   share field names but are different things.

The clean fix is to (a) remove the Game-Over kind from `Mechanic` entirely, (b)
repair the inline `Result.game_over` path so it works everywhere — making it the
primary authoring idiom — and (c) retain a small, optional top-level predicate
list for the residual cases (cross-cutting win/loss states with no single inline
home).

### Authoring model: inline vs. predicate

Not every game-over has the same shape, and the design must let the author pick
per-case rather than forcing one bucket:

- **Event-local outcomes** (a specific enemy's killing blow, a fatal choice):
  belong **inline** on the `Result` that causes them. The author writes
  `game_over` where the death happens — no separate registry to maintain. This is
  the natural idiom, and repairing it is the central enabler.
- **Cross-cutting / catch-all states** (a terminal flag reachable by several
  paths; "the player is dead" from any source): belong as a **top-level
  predicate**, because no single result owns them and duplicating `game_over`
  across N results is worse than one declaration.

There is a useful asymmetry: **wins are few and state-based** (often no single
result owns "you win"); **losses are many and event-local** (each enemy, each
trap). The corpus confirms this — see the per-entry migration in Work Item 3.

### Resolution

1. **`Mechanic` keeps `condition`.** It is the Encounter gating field, read at
   `engine.py:225` and `event_bus.py:405-407` when a `trigger_encounter` fires.
   Only the game-over-specific fields (`type`, `trigger_id`, `narrative`) leave
   `Mechanic`. After this, `Mechanic` has exactly two kinds: Encounter (`rules`)
   and Reaction-Only (`reactions`).

2. **Fix inline `Result.game_over`** to propagate from any result
   (interaction, reaction, encounter) by setting `hard.game_over` inside
   `_apply_result`, mirroring how `ReactionEffects.game_over` is already handled
   at `event_bus.py:276-278`. This makes the documented idiom actually work and
   becomes the primary authoring path.

3. **Add an optional top-level `game_over_conditions` list** for cross-cutting
   predicates, polled once at **end of turn** (after `turn.end` reactions
   settle), with a single reconciliation that also surfaces event-based
   game-overs (including those set by `turn.end` reactions) into
   `EngineResult.game_over`. This replaces and broadens today's mis-placed poll.

4. **Forbid `Result.game_over` and `ReactionEffects.game_over` from coexisting**
   on one effect, so authoring stays unambiguous.

---

## Work Items

### 1. Pydantic models — `mgmai/models/corpus.py`

**`Mechanic` (`line 445`)** — remove the game-over fields, keep `condition`:
- Delete `type: Optional[Literal["win", "lose"]] = None`
- Delete `narrative: Optional[str] = None`
- Delete `trigger_id: Optional[str] = None`
- **Keep** `condition: Optional[ConditionExpression] = None` (Encounter gating)
- **Keep** `rules` and `reactions`

**Simplify `check_shape` (`line 454`)** — drop all `is_game_over` branches.
The validator reduces to: a Mechanic must have at least one of `rules` or
`reactions` (else error). `condition` is now an optional Encounter gating field,
unchecked here.

**New model `GameOverCondition`** (place near `GameOverTrigger`, `line 282`):
```python
class GameOverCondition(BaseModel):
    id: str
    type: Literal["win", "lose"]
    condition: ConditionExpression
    trigger_id: str
    narrative: Optional[str] = None
    description: Optional[str] = None
```
This is the Game-Over Mechanic's fields, lifted to a dedicated top-level model.
`condition` and `trigger_id` are required (mirroring today's validator at
`corpus.py:463-467`). `description` is author-facing only (the existing
`Mechanic` silently dropped it since it had no such field; this model keeps it).

**`ModuleCorpus`** — add:
```python
game_over_conditions: List[GameOverCondition] = Field(default_factory=list)
```
The `mechanics` dict stays as-is.

**`ReactionEffects` (`line 287`)** — add a validator forbidding both
`result.game_over` and `game_over` being set on the same effect:
```python
@model_validator(mode="after")
def _no_double_game_over(self) -> ReactionEffects:
    if self.game_over is not None and self.result is not None \
            and self.result.game_over is not None:
        raise ValueError(
            "Specify either effect.game_over or effect.result.game_over, not both")
    return self
```

**`GameOverTrigger` (`line 282`)** — unchanged. Remains the type used by
`Result.game_over` and `ReactionEffects.game_over`.

### 2. Inline game-over propagation — `mgmai/engine/resolver.py`

**`_apply_result` (`line 1181`)** — handle `result.game_over`. After the existing
field handling (e.g. after the `reveals` block, ~`line 1269`), add:
```python
if result.game_over is not None and hard is not None:
    hard.game_over = GameOverState(
        type=result.game_over.type,
        trigger=result.game_over.trigger_id,
    )
```
This mirrors `event_bus.py:276-278`. It is the fix that makes inline
`Result.game_over` work for interactions and reactions.

**Note on the encounter path:** `encounters.py:89` calls `_apply_result` on the
firing result *and* separately extracts `firing_result.game_over` into the result
dict (`encounters.py:123`), which the engine sets again at `engine.py:241`. After
this fix that extraction is redundant (harmless double-set of the same value).
Removing `encounters.py:123` + the `engine.py:239-245` re-set is **optional
cleanup** — leave it if you want to minimize churn.

**Tests to update** (`tests/test_resolver.py`):
- `test_apply_result_with_game_over_*` (~`line 814`) and
  `test_apply_result_with_check_with_game_over_*` (~`line 871`) currently assert
  the game_over is "tolerated" (i.e. dropped). Re-state them to assert
  `hard.game_over` is now set.
- `tests/test_event_bus.py::TestReactionResultWithDispatchFields` (`line 1294`)
  documents the old "tolerated/ignored" behavior. In particular
  `test_result_with_game_over_does_not_crash` (`line 1321`) asserts
  `engine_result.game_over is None` — flip that to assert it is now set, and
  rename the class to reflect that dispatch fields on a reaction `Result` now
  take effect.

### 3. Engine: replace the poll — `mgmai/engine/engine.py`

**Delete `_check_game_over_mechanics` (`line 839`)** and add a replacement that
iterates `corpus.game_over_conditions`:
```python
def _check_game_over_conditions(hard, soft, corpus):
    for cond in corpus.game_over_conditions:
        if evaluate(cond.condition, hard, soft, corpus):
            return GameOverResult(
                type=cond.type,
                trigger=cond.trigger_id,
                narrative=cond.narrative,
            )
    return None
```

**Remove the mis-placed poll (`lines 377-381`)** and the now-redundant mid-turn
reconciliation (`lines 422-423`). The latter is safe to remove: the only consumer
of the local `game_over` after it is the main return at `line 543`, which the new
end-of-turn reconciliation (below) covers. (The explicit `game_over` sets at
`line 242` [encounter] and `line 275` [combat] must STAY — they feed the
early-return path at `line 311`.)

**Add end-of-turn poll + reconciliation** between the `turn.end` dispatch
(`line 486-496`) and the result construction (`line 505`):
```python
# 9.5 Condition-based game-over poll (after all reactions settle).
if hard.game_over is None:
    go = _check_game_over_conditions(hard, soft, corpus)  # carries narrative
    if go is not None:
        hard.game_over = GameOverState(type=go.type, trigger=go.trigger)
        game_over = go  # preserve the condition's ending narrative
# Final reconciliation: surface event-based game_overs (set by encounters,
# combat, or any reaction including turn.end) into EngineResult.game_over.
if hard.game_over is not None and game_over is None:
    game_over = GameOverResult(
        type=hard.game_over.type,
        trigger=hard.game_over.trigger,
    )
```
**On `narrative`:** the condition-based path keeps its `narrative` (assigned
directly from the poll result). The reconciliation branch — which only fires
for *event-based* game_overs that left the local `game_over` unset — does not
carry `narrative`, matching today's behavior (the encounter path at
`engine.py:242` and combat path at `engine.py:275` likewise build
`GameOverResult` without narrative). For inline `Result.game_over`, the ending
prose already reaches the GM through `triggered_narration` from `_apply_result`;
for the top-level conditions, the `narrative` field on the entry is the source.
This is consistent with the current engine; no new gap is introduced.

**Early-return path (`line 304-315`)** — add the same one-line reconciliation
before the `return` so `EngineResult.game_over` is consistent on failed
resolutions too:
```python
if hard.game_over is not None and game_over is None:
    game_over = GameOverResult(
        type=hard.game_over.type, trigger=hard.game_over.trigger)
```

### 4. Adventure corpus — `adventures/bag-of-holding/corpus.json`

The four game-over mechanics (`mechanics` block, `line 1632`) migrate by kind:

| Entry | Kind | Migration |
|---|---|---|
| `lost_to_astral_plane_rip` (`line 1734`) | event-local (single result) | **inline** on the `confirm_squeeze_through_rip` result (`line 765`): add `"game_over": {"type":"lose","trigger_id":"astral_plane"}`. Its narrative at `line 766` already *is* the loss prose. Remove the mechanic. |
| `player_escaped` (`line 1724`) | cross-cutting win (flag set at `line 797` AND `line 831`; distinct escape narrative ≠ padlock-open narrative) | **top-level predicate** → move to `game_over_conditions` as-is. |
| `lost_key_to_astral` (`line 1744`) | cross-cutting loss (flag set at 3 paths: `line 815`, `849`, `874`) | **top-level predicate** → move to `game_over_conditions` as-is. One declaration beats 3× inline duplication. |
| `spider_killed_player` (`line 1754`) | **dead code** | **remove.** Its condition `entity:player.alive == false` can never hold: nothing in the engine sets `player.alive = false` (combat kills NPCs' `alive`, not the player's). Combat death already ends the game directly at `engine.py:274` with the same `trigger_id` `"player_death"`. |

Add the top-level field:
```json
"game_over_conditions": [
  { "id": "player_escaped", "type": "win",
    "condition": { "require": "flag:padlock_unlocked == true" },
    "trigger_id": "escape_bag",
    "narrative": "<keep line 1731 narrative>",
    "description": "<keep line 1727 description>" },
  { "id": "lost_key_to_astral", "type": "lose",
    "condition": { "require": "flag:key_lost_to_astral == true" },
    "trigger_id": "key_lost",
    "narrative": "<keep line 1751 narrative>",
    "description": "<keep line 1747 description>" }
]
```
The `global_reactions` mechanic (`line 1764`) is Reaction-Only and stays
unchanged. After migration, `mechanics` contains only `global_reactions`.

**Known limitation (out of scope):** non-combat death (HP → 0 from a trap's
`player_damage`) is not handled by anything today — combat death is. If a future
adventure needs a trap-death catch-all, add a `game_over_conditions` entry whose
condition can actually hold (e.g. once the engine sets `player.alive = false` on
HP depletion), or add an inline `game_over` to the trap's result.

### 5. Test fixture — `tests/fixtures/corpus.json`

`win_escape_bag` (`line 695`) is a win predicate on `flag:padlock_unlocked ==
true` — move it verbatim from `mechanics` to a new top-level
`game_over_conditions` array. Keep its `type`, `condition`, `narrative`,
`trigger_id`. (If other tests in `test_engine.py` rely on it being a `Mechanic`,
update them per Work Item 7.)

### 6. Test code — `tests/test_corpus.py`

- **`TestMechanic`** — remove game-over-specific tests:
  `test_game_over_win` (`line 423`), `test_game_over_lose` (`line 436`),
  `test_game_over_missing_condition_raises` (`line 459`),
  `test_game_over_missing_trigger_id_raises` (`line 467`),
  `test_both_type_and_rules_raises` (`line 475`).
- Restate `test_neither_type_nor_rules_raises` (`line 485`) to verify rejection
  of a Mechanic with neither `rules` nor `reactions`.
- **New `TestGameOverCondition`** — cover valid construction, missing
  `condition`/`trigger_id` rejection, and both `win`/`lose` types.
- **`TestResult`** — no changes needed. `Result.game_over` is unchanged
  (still `Optional[GameOverTrigger]`); its validation is already covered at
  `line 363`/`390`.
- **New test for the `ReactionEffects` double-game-over validator** (Work Item 1).

### 7. Test code — `tests/test_engine.py`

**`TestEngineGameOver` (`line 368`):** the fixture's `win_escape_bag` is now a
top-level `game_over_condition` polled at end of turn. `test_win_condition`
(`line 369`) should still pass: setting `padlock_unlocked` and waiting fires the
end-of-turn poll → `result.game_over.type == "win"`. Verify; if the poll's new
end-of-turn placement changes timing for this test, adjust the assertion. Add a
test that a win condition satisfied by a `turn.end` reaction is caught **same
turn** (the old poll would have missed it until next turn).

### 8. Test code — `tests/test_reactions.py`

- `test_game_over_mechanic_still_works` (`line 147`) — remove (Game-Over kind
  gone). Replace with a reaction-only-mechanic construction test if not already
  covered.
- `test_game_over_and_encounter_both_rejected` (`line 167`) — remove (the
  constraint it tests no longer exists).

### 9. Validation script — `scripts/validate_adventure.py`

Remove the game-over-type block (`lines 194-198`). Optionally add a check that
each `game_over_conditions` entry has `type` in `("win","lose")` and a
`condition` + `trigger_id` (the model already enforces this, so this is
redundant — skip unless consistency with other corpus checks is desired).

### 10. Schema documentation — `schema/corpus.md`

**Rewrite the Mechanic section (`lines 1238-1363`):**
- Describe exactly two kinds: Encounter and Reaction-Only.
- Remove all Game-Over references; remove `type`/`trigger_id`/`narrative` from
  the field table. **Keep `condition`**, restated as "Encounter gating condition
  (optional; evaluated when a `trigger_encounter` targets this mechanic)".
- Replace the Game-Over JSON example with: (a) an inline `Result.game_over`
  example (the primary idiom), and (b) a top-level `game_over_conditions`
  example (the cross-cutting idiom).

**New `game_over_conditions` subsection** under Top-Level Structure: explain it
holds cross-cutting win/loss predicates polled once at end of turn, that
event-local game-overs should instead use inline `Result.game_over`, and that
inline is the preferred idiom when a single result owns the outcome.

**Fix type references:**
- `line 224` (`Result` table): `"game_over": Mechanic` → `"game_over": GameOverTrigger`.
- `line 807` (`ReactionEffect` table): `"game_over": Mechanic` → `"game_over": GameOverTrigger`.

**Document the `effect.game_over` vs `effect.result.game_over` exclusivity**
(Work Item 1) in the Reaction Effect section.

### 11. Verify

- `pytest` (full suite).
- Type-check and lint per the project's commands (check `AGENTS.md` / `pyproject.toml`;
  if absent, ask and record them in `AGENTS.md`).
- Play-test Bag of Holding: confirm the escape win, the key-lost loss, and the
  astral-plane loss (now inline) all still fire; confirm spider combat death
  still ends the game (via the combat path, now without the redundant mechanic).
