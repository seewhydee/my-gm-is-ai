# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stainlesschicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""LLM integration test: fight to completion in the combat arena.

A driver LLM plays the player against the real GM LLM, fighting all
four enemies until combat ends.  Hard assertions verify the engine ran
the fight to a clean conclusion (victory or a gracefully handled
loss); an advisory LLM judge records a narration-quality verdict in
the artifact (it does not gate the test).
"""

from __future__ import annotations


import warnings

import pytest

from tests.integration.judge import judge_scenario, format_verdict_for_failure, JudgeError
from tests.integration.runner import run_scenario

pytestmark = pytest.mark.llm


FIGHT_DIRECTIVE = """\
You are fighting a battle in a gladiatorial arena.  Four enemies face
you and your ally Korbar: a goblin grunt, a goblin runner, a goblin
shaman, and a bugbear.

Your objective: DEFEAT ALL ENEMIES.  Fight until combat ends.

Tactics:
- Attack enemies with your longsword.  Switch targets when your
  current target dies.
- The bugbear is vulnerable to fire — use your flame strike ability on
  it when you can.
- The goblin shaman heals its allies — consider prioritising it.
- If your HP drops below half, drink a healing potion.
- Do NOT flee.  Fight to the end.
"""

_ENEMIES_FIGHT = {"goblin_grunt", "goblin_runner", "goblin_shaman", "bugbear"}


def _enemy_dead_or_fled(
    result: ScenarioResult,
    enemy_id: str,
    *,
    accept_fled: bool = False,
) -> bool:
    """Check whether *enemy_id* was killed (and optionally fled) from
    the combat log across all turns.
    """
    for t in result.turns:
        for entry in t.combat_log:
            if entry.get("actor") == enemy_id:
                if entry.get("action") == "death":
                    return True
                if accept_fled and entry.get("action") == "flee":
                    return True
    return False


def _assert_combat_concluded(result):
    """Hard assertions on a finished combat run (engine correctness).

    Victory is NOT required: the arena fight is swingy by design, so the
    player may legitimately die.  What is asserted is that combat started
    and ended cleanly, with no exceptions or empty narrations, and that
    the ending was handled gracefully:

    - Player alive at the end (won): every enemy has a death entry in
      the combat log (or a flee entry for the runner, which has flee AI),
      and the game did not end in a loss.
    - Player dead (lost): game-over is recorded as a loss and the
      player's death is logged.
    """
    last = result.last_turn
    assert last is not None, "No turns were recorded"

    # Run was not aborted mid-stream.
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; "
        f"see artifact: {result.artifacts_path}"
    )

    # Combat was entered at some point during the run.
    any_in_combat = any(t.status.in_combat for t in result.turns)
    assert any_in_combat, (
        "Combat never started; see artifact: " + str(result.artifacts_path)
    )

    # Combat ended within the turn cap; combat_state cleared.
    assert not last.status.in_combat, (
        f"Combat still active after {result.turn_count} turns; "
        f"see artifact: {result.artifacts_path}"
    )

    # No unhandled exceptions.
    assert result.error is None, (
        f"Unhandled exception during run: {result.error!r}; "
        f"see artifact: {result.artifacts_path}"
    )
    for i, t in enumerate(result.turns, 1):
        assert t.exception is None, (
            f"Turn {i} raised {t.exception!r}; "
            f"see artifact: {result.artifacts_path}"
        )

    # No empty narrations.
    for i, t in enumerate(result.turns, 1):
        assert t.narration, (
            f"Turn {i} produced empty narration; "
            f"see artifact: {result.artifacts_path}"
        )

    # turn_count advanced each turn (no turn regressed).
    prev = -1
    for i, t in enumerate(result.turns, 1):
        assert t.status.turn_count > prev, (
            f"Turn {i}: turn_count regressed ({prev} -> {t.status.turn_count}); "
            f"see artifact: {result.artifacts_path}"
        )
        prev = t.status.turn_count

    player_hp = last.status.player_hp or 0
    if player_hp > 0:
        # Player won: each enemy must have a death entry in the combat
        # log (or a flee entry for the runner, which has flee AI).
        for eid in _ENEMIES_FIGHT:
            accept_fled = (eid == "goblin_runner")
            assert _enemy_dead_or_fled(result, eid, accept_fled=accept_fled), (
                f"Player survived but enemy '{eid}' is neither dead nor "
                f"fled in the combat log; see artifact: {result.artifacts_path}"
            )
        assert player_hp <= (last.status.player_max_hp or 999), (
            f"Player HP exceeds max: {player_hp}/{last.status.player_max_hp}; "
            f"see artifact: {result.artifacts_path}"
        )
        assert not last.game_over or last.game_over_type == "win", (
            f"Game ended with type={last.game_over_type} (expected no game-over "
            f"or 'win'); see artifact: {result.artifacts_path}"
        )
    else:
        # Player lost: the loss must have been handled gracefully —
        # game-over recorded as a loss, player death logged.
        assert last.game_over and last.game_over_type == "lose", (
            f"Player at {player_hp} HP but game-over is "
            f"{last.game_over_type!r} (expected 'lose'); "
            f"see artifact: {result.artifacts_path}"
        )
        player_death_logged = any(
            entry.get("actor") == "player" and entry.get("action") == "death"
            for t in result.turns
            for entry in t.combat_log
        )
        assert player_death_logged, (
            "Player died but no 'death' combat-log entry for the player; "
            f"see artifact: {result.artifacts_path}"
        )


def _stop_when_combat_ended(session, turns):
    """Stop early once combat has been active and has since ended."""
    combat_was_active = any(t.status.in_combat for t in turns)
    return combat_was_active and not session.in_combat


def _record_judge_verdict(judge_client, result) -> None:
    """Run the advisory LLM judge and record its verdict in the artifact.

    The judge does not gate the test: deterministic assertions decide
    pass/fail.  An unparseable verdict or a judge "fail" verdict only
    produces a warning, so the test signal stays stable across reruns.
    """
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        warnings.warn(
            f"Judge LLM produced unparseable output: {exc}; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
        return
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        warnings.warn(
            "Advisory judge rejected the run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}",
            stacklevel=2,
        )


@pytest.mark.llm
def test_fight_to_completion(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver LLM fights all enemies until combat ends."""
    result = run_scenario(
        scenario_name="fight_to_completion",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=combat_arena_dir,
        artifacts_dir=artifacts_dir,
        directive=FIGHT_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    # The artifact must exist regardless of pass/fail.
    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Hard assertions (engine correctness; win or graceful loss).
    _assert_combat_concluded(result)

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 2: flee mid-fight
# ------------------------------------------------------------------

FLEE_DIRECTIVE = """\
You are surrounded by four enemies and badly outmatched.  Your goal
is to ESCAPE, not to win.

- On your first turn, attack the goblin grunt to start the fight.
- Once combat has started, FLEE through the northern corridor.
  Keep trying to flee until you succeed.
- Do not try to defeat all enemies — just escape alive.
"""


def _stop_when_fled(session, turns):
    """Stop early when the player has fled to the corridor."""
    snap = session.status_snapshot()
    return snap.location == "corridor" and not snap.in_combat


@pytest.mark.llm
def test_flee_scenario(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver LLM attempts to flee combat through the northern corridor."""
    result = run_scenario(
        scenario_name="flee_scenario",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=combat_arena_dir,
        artifacts_dir=artifacts_dir,
        directive=FLEE_DIRECTIVE,
        max_turns=15,
        config_dir=tmp_path,
        stop_when=_stop_when_fled,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.error is None, (
        f"Run errored: {result.error!r}; see artifact: {result.artifacts_path}"
    )

    last = result.last_turn
    assert last is not None

    # Combat was entered at some point.
    any_in_combat = any(t.status.in_combat for t in result.turns)
    assert any_in_combat, (
        "Combat never started — driver may have fled pre-combat; "
        f"see artifact: {result.artifacts_path}"
    )

    # Player successfully fled: combat ended, in the corridor.
    assert not last.status.in_combat, (
        f"Combat still active after flee attempt; "
        f"see artifact: {result.artifacts_path}"
    )

    assert last.status.location == "corridor", (
        f"Player did not reach corridor (location={last.status.location}); "
        f"see artifact: {result.artifacts_path}"
    )

    # A successful "flee" entry for the player exists in the combat log.
    has_flee = any(
        entry.get("actor") == "player" and entry.get("action") == "flee"
        for t in result.turns
        for entry in t.combat_log
    )
    assert has_flee, (
        "No 'flee' combat-log entry for the player; "
        f"see artifact: {result.artifacts_path}"
    )

    # Player survived.
    assert last.status.player_hp and last.status.player_hp > 0, (
        f"Player died while fleeing; see artifact: {result.artifacts_path}"
    )

    # No game-over.
    assert not last.game_over, (
        f"Game ended unexpectedly (type={last.game_over_type}); "
        f"see artifact: {result.artifacts_path}"
    )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 3: consumable + ability focus
# ------------------------------------------------------------------

CONSUMABLE_DIRECTIVE = """\
You are fighting a battle and must demonstrate your full arsenal.

- On your first turn, attack the goblin grunt to start the fight.
- Once combat is active, use your flame strike ability on the bugbear
  — it is vulnerable to fire.
- If your HP drops below 14, drink a healing potion.  You start with 2.
- Keep fighting until all enemies are defeated.  Switch to regular
  attacks when your abilities are exhausted.
"""


@pytest.mark.llm
def test_consumable_ability_scenario(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver LLM uses Flame Strike and a healing potion during the fight."""
    result = run_scenario(
        scenario_name="consumable_ability",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=combat_arena_dir,
        artifacts_dir=artifacts_dir,
        directive=CONSUMABLE_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Hard assertions: combat concluded (win or graceful loss).
    _assert_combat_concluded(result)

    # The combat log across all turns must contain at least one
    # ability use for flame_strike (by the player) and at least one
    # use_item for a health potion (by the player).
    #
    # Flame strike is a save ability → engine logs action="ability_save"
    # with attack_id="flame_strike" (or attack_name="Flame Strike").
    # Health potion is a consumable → engine logs action="use_item"
    # with actor="player".
    _PLAYER_ABILITY_ACTIONS = {"ability_save", "attack"}
    has_ability_use = any(
        entry.get("actor") == "player"
        and entry.get("action") in _PLAYER_ABILITY_ACTIONS
        and (entry.get("attack_id") == "flame_strike"
             or entry.get("attack_name") == "Flame Strike")
        for t in result.turns
        for entry in t.combat_log
    )

    assert has_ability_use, (
        "Driver never used flame_strike (expected action='ability_save' or "
        "'attack' with actor='player' and attack_id='flame_strike' or "
        "attack_name='Flame Strike'); "
        f"see artifact: {result.artifacts_path}"
    )

    has_heal = any(
        entry.get("actor") == "player"
        and entry.get("action") == "use_item"
        for t in result.turns
        for entry in t.combat_log
    )
    if not has_heal:
        warnings.warn(
            "Driver did not use a healing potion (HP may not have dropped "
            "low enough); see artifact: " + str(result.artifacts_path),
            stacklevel=2,
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 4: ally death (fragile Korbar)
# ------------------------------------------------------------------

ALLY_DEATH_DIRECTIVE = """\
You are fighting a battle.  Your ally Korbar is badly wounded and may
not survive.  Fight on regardless.

- On your first turn, attack the goblin grunt to start the fight.
- Keep attacking enemies until all are defeated.  Switch targets
  when your current target dies.
- Do not waste time mourning Korbar if she falls — keep fighting.
- If your own HP drops below half, drink a healing potion.
"""


def _build_fragile_allies_state_manager(combat_arena_dir):
    """Load the arena with Korbar at 1 HP (so she likely dies early)."""
    from mgmai.state.manager import StateManager

    sm = StateManager(adventure_dir=str(combat_arena_dir))
    # Drop Korbar to 1 HP so a single hit will KO her.
    sm.hard_state.entity_states["korbar"]["current_hp"] = 1
    return sm


@pytest.mark.llm
def test_ally_death_scenario(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Korbar starts at 1 HP; verify follower KO is handled gracefully."""
    sm = _build_fragile_allies_state_manager(combat_arena_dir)
    result = run_scenario(
        scenario_name="ally_death",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=ALLY_DEATH_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    last = result.last_turn
    assert last is not None
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.error is None, (
        f"Run errored: {result.error!r}; see artifact: {result.artifacts_path}"
    )

    # Combat ran and concluded; the ending (win or a gracefully
    # handled loss) was processed correctly.  Korbar's 1-HP start makes
    # this fight especially swingy, so survival is not required.
    _assert_combat_concluded(result)

    # Korbar must be dead by end of fight (she started at 1 HP).
    # Since combat is cleared when it ends, check the final status's
    # entity_states if available; otherwise verify the death log.
    final = result.final_status or {}
    entity_states = final.get("entity_states", {})
    korbar_state = entity_states.get("korbar", {})
    if korbar_state:
        assert not korbar_state.get("alive", True), (
            f"Korbar survived despite starting at 1 HP: {korbar_state}; "
            f"see artifact: {result.artifacts_path}"
        )

    # The combat log must contain a "death" entry for Korbar at some
    # point during the fight.
    korbar_died = any(
        entry.get("actor") == "korbar" and entry.get("action") == "death"
        for t in result.turns
        for entry in t.combat_log
    )
    assert korbar_died, (
        "No 'death' combat-log entry for Korbar; follower KO may not be "
        f"logged correctly; see artifact: {result.artifacts_path}"
    )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)
