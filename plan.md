# LLM-Assisted Integration Testing Plan

This plan lays out the design and phased implementation of
**LLM-assisted integration tests**: end-to-end play sessions where a
"driver" LLM acts as the player against the real game (real GM LLM
calls, real engine), with outcomes verified by hard state assertions
plus an LLM judge.

## Motivation

The pytest unit suite exercises the engine deterministically with fake
LLM clients.  What it cannot cover:

- The full two-call LLM pipeline (ruling → engine → prose) against a
  real model, with real parse/retry behavior.
- Whether combat *plays well* over multiple rounds: coherent narration,
  consistent hit/miss reporting, sensible initiative flow, no
  contradictions or repeated text.
- Regressions in prompt templates (`mgmai/templates/*.j2`) that only
  manifest with a live model.

## Current architecture assessment

Mostly ready — clean seams already exist:

- `LLMClient` is constructor-injected into `GameLoop`
  (`mgmai/cli.py:201-204`); the GM side needs no changes and uses the
  normal API key resolution.
- `Display` is injectable (`mgmai/game/loop.py:111`).
- `GameLoop._run_turn(line)` (`loop.py:160`) is a clean single-turn
  entry point; the REPL is a thin wrapper around it.
- In-memory/JSON adventure loading is proven
  (`tests/helpers.py:build_state_manager`,
  `tests/fixtures/mini_adventure/`).

Gaps to close:

1. `input()` is hardwired in `_repl()` (`loop.py:141`) — but we bypass
   the REPL entirely rather than refactor it.
2. `_run_turn()` sends narration to `Display` and returns `None`; the
   driver LLM needs the narration text back.
3. Game-over calls `_do_exit()` (`loop.py:385`) instead of signaling
   the caller; harness must observe `hard_state.game_over` directly.
4. Autosave falls back to `./autosave.json` without a `config_dir`
   (`loop.py:408`); harness must pass a temp config dir.
5. No fixture adventure covering the new combat breadth (allies, NPC AI
   targeting, flee thresholds, cooldown abilities, conditions,
   resistances, consumables).

## Design principles

- **Minimal refactor, no REPL inversion.**  Keep interactive I/O as-is;
  add a headless composition layer alongside it.
- **Out of the default suite, but pytest as the runner.**  Integration
  tests live in `tests/integration/`, excluded from default
  `testpaths`, marked `@pytest.mark.llm`, auto-skipped unless an API
  key is available.  Run explicitly: `pytest tests/integration`.
- **Cost and runaway control.**  Hard turn cap (~25), per-call
  timeouts, driver output sanitized to a single command line.
- **Fuzzy failures need artifacts.**  Every run dumps a full transcript
  (commands, narration, combat log, state snapshots, judge verdict) to
  a artifacts dir for human review.
- **Two-layer verification.**  Deterministic assertions catch engine
  bugs; an LLM judge catches narration/prompt regressions.

## Phase 1 — Headless harness

1. Change `GameLoop._run_turn()` to return the final narration string
   (REPL ignores the return value; no behavior change).
2. Add `RecordingDisplay` (subclass of `Display`) that suppresses
   terminal rendering and records narration, status snapshots, errors,
   and game-over events.
3. Add `mgmai/game/headless.py` with `HeadlessSession`:
   - Composes `StateManager` + `GameLoop` + `RecordingDisplay`; takes
     an adventure dir (or pre-built state manager), an `LLMClient`, and
     a temp `config_dir`.
   - `submit(command) -> TurnTranscript` — runs one turn; returns
     narration, combat status snapshot, `game_over` flag.
   - Properties exposing `hard_state` / `soft_state` / `corpus` for
     assertions; `is_over` derived from `game_over` and combat state.
4. Unit tests for the harness itself (with `FakeLLMClient`) in the
   regular suite, verifying narration return, recording, and game-over
   signaling.

## Phase 2 — Fixture adventure: "combat arena"

`tests/integration/fixtures/combat_arena/` — handcrafted JSON
(`corpus.json`, `soft-state.json`, `hard-state.json`,
`default-player.json`), validated with `scripts/validate_adventure.py`.

- **Two rooms**: the arena plus an exit corridor (gives flee a
  destination).
- **Party**: player (attack, one ability, healing potions) + 1-2
  follower allies with combat blocks.
- **Enemies** chosen to span mechanics:
  - Plain melee goblin (baseline attack/damage).
  - Goblin with `flee_below_hp_pct` (tests NPC flee).
  - Shaman with cooldown ability and heal (tests NPC ability AI,
    `lowest_hp`-style targeting).
  - One enemy with damage resistance/vulnerability.
- Written so a complete fight resolves in ~6-15 rounds.

## Phase 3 — Player driver + first scenario

1. `tests/integration/driver.py` — `PlayerDriver` class reusing
   `LLMClient` with a playtester persona prompt: given the rolling
   transcript and a scenario directive, reply with exactly one game
   command.  Sanitize: first line only, strip quotes, reject `/` meta
   commands.  Configurable model via the existing model registry /
   `MGMAI_MODEL` env conventions.
2. First scenario: **fight to completion** ("attack enemies, use your
   potion when badly hurt, keep fighting until combat ends").
3. Hard assertions after the run:
   - Combat ended within the turn cap; `combat_state` cleared.
   - Defeated enemies dead/removed; survivors' HP in `[0, max]`.
   - Player/ally HP within bounds; `turn_count` advanced each turn.
   - No unhandled exceptions; no empty narrations.
4. Transcript artifact written regardless of pass/fail.

## Phase 4 — LLM judge

1. `tests/integration/judge.py` — feed the full transcript plus the
   engine combat log to a judge model with a rubric, returning
   structured JSON (`pass`, per-criterion scores, notes):
   - Every hit/miss/KO in the combat log is reflected in narration.
   - No contradictions (dead enemies acting, HP inconsistencies).
   - No verbatim repetition or degenerate text.
   - Fight has a coherent arc and conclusion.
2. Judge verdict recorded in the artifact; test fails on `pass: false`
   with notes surfaced in the pytest failure message.

## Phase 5 — More scenarios + runner hygiene

1. Additional driver directives over the same arena:
   - **Flee scenario**: attempt to escape mid-fight.
   - **Consumable/ability focus**: force potion + ability usage.
   - **Ally death**: outnumbered variant, verify follower KO handling.
2. Pytest wiring: `llm` marker registered in `pyproject.toml`;
   `tests/integration` excluded from default `testpaths`; skip cleanly
   without `MGMAI_API_KEY`; optional `--driver-model` / `--judge-model`
   options.
3. Document usage in `README.md` (cost expectations: each game turn =
   2 GM calls + 1 driver call; a 15-turn run ≈ 45 calls + 1 judge
   call).

## Build order and status

- [ ] Phase 1: headless harness (`_run_turn` return, `RecordingDisplay`,
      `HeadlessSession`, unit tests)
- [ ] Phase 2: combat arena fixture adventure
- [ ] Phase 3: player driver + fight-to-completion scenario with hard
      assertions
- [ ] Phase 4: LLM judge
- [ ] Phase 5: extra scenarios, pytest/marker wiring, README docs

Each phase is independently mergeable with the regular test suite
green.
