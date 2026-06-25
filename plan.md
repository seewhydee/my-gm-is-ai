# Plan: Make Non-Rigorous Examine a Zero-Turn Action

## Evaluation

**Verdict: Good idea, implemented.** The previous "every action costs exactly one
turn" rule was too blunt for `examine`. In combat it punished the player for
orienting themselves, and outside combat it made a simple "look around" feel
costly.

The existing `rigorous` / non-rigorous distinction is the right lever:
non-rigorous examine is a cursory glance (0 turns), rigorous examine is a
physical search (1 turn). This matches player intuition and required only a
small, localized change.

**Alternative considered and rejected:** A generic "free action" flag open to
all action types. Too broad; the request was examine-specific.

## Critical Notes / Minor Issues

1. **Turn-start events still fire.** The engine dispatches `turn.start` *before*
   it knows the resolution cost. Only `turn.end` and the `turn_count` increment
   are skipped for zero-turn actions. For the current corpus this is harmless,
   but a module that hooks `turn.start` for time-based effects (poison, NPC
   schedules, etc.) will apply them on free examines. If that becomes a problem,
   the clean fix is to pre-compute whether an action costs a turn (e.g. from
   `action_type` + `rigorous`) and guard `turn.start` the same way.

2. **Failed actions already did not consume turns.** The engine returns early on
   validation failure before incrementing `turn_count`. To keep `EngineResult`
   honest, those early returns now set `costs_turn=False`.

3. **OOC discussion and chain-limit errors do not consume turns.** They also
   return early, so `costs_turn=False` was added there.

## Implementation

### Core engine

- `mgmai/engine/resolver.py`
  - Added `costs_turn: bool = True` to `ResolutionResult`.
  - `resolve_examine()` now sets:
    - `costs_turn=action.rigorous` on every success path (room, entity, soft item).
    - `costs_turn=False` on every failure path (invalid `using`, target not found,
      current room missing).

- `mgmai/engine/engine.py`
  - The `turn.end` dispatch and `hard.turn_count += 1` are now wrapped in
    `if resolution.costs_turn:`.
  - `turn_history` is still appended for zero-turn actions (using the current
    `turn_count`), preserving the audit trail.
  - Added `costs_turn` to all `EngineResult` constructions, including the early
    returns for OOC discussion, chain-depth limit, and validation failure.

### Data models

- `mgmai/models/actions.py`
  - Added `costs_turn: bool = True` to `EngineResult`.

### LLM prompts

- `mgmai/templates/ruling.j2`
  - Examination rule now explains that `rigorous: true` costs a turn and
    non-rigorous is free.
  - Combat rules now allow non-rigorous `examine` as a free cursory look;
    rigorous examine is disallowed in combat.

- `mgmai/templates/prose.j2`
  - `examine` reference updated to note turn cost and brief narration for
    cursory glances.

### Documentation

- `doc/combat.md`
  - Action table now lists `examine` (non-rigorous only) as valid in combat.

- `schema/actions.md`
  - `examine` section documents the 0-turn / 1-turn behavior.

### Tests

- `tests/test_resolver.py`
  - Added assertions for `costs_turn` on non-rigorous success, rigorous success,
    and failed examine.

- `tests/test_engine.py`
  - Replaced `test_resolve_examine` with:
    - `test_resolve_examine_non_rigorous` — verifies `turn_count` does not
      advance.
    - `test_resolve_examine_rigorous_advances_turn` — verifies rigorous examine
      still advances the turn.

## Test Results

```
1102 passed, 1 skipped
```

## Impact Summary

| Area | Change |
|------|--------|
| Core engine | `resolver.py` (+1 field, examine paths set `costs_turn`); `engine.py` (conditional turn increment) |
| Data models | `actions.py`: `costs_turn` added to `EngineResult` |
| LLM prompts | `ruling.j2`, `prose.j2` updated |
| Documentation | `doc/combat.md`, `schema/actions.md` updated |
| Tests | `test_resolver.py`, `test_engine.py` updated/extended |
| Adventure corpus | No changes needed |

**Backward compatibility:** Fully backward-compatible. Existing adventures that
use `rigorous_only: true` on `OnExamineEvent` still require a rigorous (turn-costing)
search to reveal hidden details. Adventures that omit `rigorous_only` can already
be discovered by a free cursory glance.

**Risk:** Low. The change is a conditional skip of `turn.end` + `turn_count += 1`.
All other engine processing (immediate/deferred reactions, state changes,
encounters, history logging) proceeds normally.
