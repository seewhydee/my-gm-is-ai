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
four enemies until combat ends.  Hard assertions verify the engine
handled the full fight correctly; an LLM judge verifies narration
quality.
"""

from __future__ import annotations


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
- The bugbear is vulnerable to fire — use your Flame Strike ability
  (use_ability with ability_id "flame_strike") on it when you can.
- The goblin shaman heals its allies — consider prioritising it.
- If your HP drops below half, drink a healing potion (use_item with
  target "health_potion").
- Do NOT flee.  Fight to the end.
"""


def _assert_combat_resolved(result):
    """Hard assertions on the post-fight state (engine correctness)."""
    last = result.last_turn
    assert last is not None, "No turns were recorded"

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

    # Defeated enemies dead; the snapshot lists survivors only, so any
    # enemy absent from the final combatants map is confirmed dead.
    final_combatants = last.status.combatants
    for eid in ["goblin_grunt", "goblin_runner", "goblin_shaman", "bugbear"]:
        if eid in final_combatants:
            info = final_combatants[eid]
            assert not info["alive"], (
                f"Enemy '{eid}' still alive in final combatants: {info}; "
                f"see artifact: {result.artifacts_path}"
            )
            hp = info.get("hp", 0)
            assert hp <= 0, (
                f"Enemy '{eid}' is dead but hp={hp} (expected <= 0); "
                f"see artifact: {result.artifacts_path}"
            )

    # Player HP within bounds (player must have survived).
    player_hp = last.status.player_hp
    player_max = last.status.player_max_hp
    assert player_hp is not None and player_hp > 0, (
        f"Player HP out of bounds (dead): {player_hp}/{player_max}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert player_hp <= (player_max or 999), (
        f"Player HP exceeds max: {player_hp}/{player_max}; "
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

    # Game did not end in a loss (player won the fight).
    assert not last.game_over or last.game_over_type == "win", (
        f"Game ended with type={last.game_over_type} (expected no game-over "
        f"or 'win'); see artifact: {result.artifacts_path}"
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
    )

    # The artifact must exist regardless of pass/fail.
    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Hard assertions (engine correctness).
    _assert_combat_resolved(result)

    # LLM judge: narration quality + consistency.
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        pytest.fail(
            f"Judge LLM produced unparseable output: {exc}\n"
            f"See artifact: {result.artifacts_path}"
        )
    result.judge_verdict = verdict
    result.rewrite_artifact()

    if not verdict.get("pass"):
        pytest.fail(
            "LLM judge rejected the run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}"
        )


# ------------------------------------------------------------------
# Scenario 2: flee mid-fight
# ------------------------------------------------------------------

FLEE_DIRECTIVE = """\
You are surrounded by four enemies and badly outmatched.  Your goal
is to ESCAPE, not to win.

- On your first turn, attack the goblin grunt to start the fight.
- Once combat has started, FLEE through the northern corridor
  ("North to the exit corridor").  Keep trying to flee until you
  succeed.
- Do not try to defeat all enemies — just escape alive.
"""


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
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()
    assert result.error is None, (
        f"Run errored: {result.error!r}; see artifact: {result.artifacts_path}"
    )

    last = result.last_turn
    assert last is not None

    # Combat ended (player is no longer in combat).
    assert not last.status.in_combat, (
        f"Combat still active after flee attempt; "
        f"see artifact: {result.artifacts_path}"
    )

    # Player escaped to the corridor.
    assert last.status.location == "corridor", (
        f"Player did not reach corridor (location={last.status.location}); "
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

    # Judge verdict.
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        pytest.fail(f"Judge LLM unparseable: {exc}\nSee artifact: {result.artifacts_path}")
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        pytest.fail(
            "LLM judge rejected the flee run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}"
        )


# ------------------------------------------------------------------
# Scenario 3: consumable + ability focus
# ------------------------------------------------------------------

CONSUMABLE_DIRECTIVE = """\
You are fighting a battle and must demonstrate your full arsenal.

- On your first turn, attack the goblin grunt to start the fight.
- Once combat is active, use your Flame Strike ability (use_ability
  with ability_id "flame_strike") on the bugbear — it is vulnerable
  to fire.
- If your HP drops below 14, drink a healing potion (use_item with
  target "health_potion").  You start with 2 potions.
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
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Hard assertions: combat resolved, all enemies dead.
    _assert_combat_resolved(result)

    # The combat log across all turns must contain at least one
    # use_ability entry (Flame Strike) and at least one heal entry
    # (health potion).  These verify the driver exercised both mechanics.
    has_ability_use = False
    has_heal = False
    for t in result.turns:
        for entry in t.combat_log:
            action = entry.get("action", "")
            if action == "use_ability":
                has_ability_use = True
            if action == "heal" or action == "use_item":
                has_heal = True

    assert has_ability_use, (
        "Driver never used an ability (flame_strike); "
        f"see artifact: {result.artifacts_path}"
    )
    # Healing potion use is encouraged but not strictly required —
    # the driver might not get hurt enough.  We assert softly.
    if not has_heal:
        import warnings
        warnings.warn(
            "Driver did not use a healing potion (HP may not have dropped "
            "low enough); see artifact: " + str(result.artifacts_path),
            stacklevel=2,
        )

    # Judge verdict.
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        pytest.fail(f"Judge LLM unparseable: {exc}\nSee artifact: {result.artifacts_path}")
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        pytest.fail(
            "LLM judge rejected the consumable/ability run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}"
        )


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
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    last = result.last_turn
    assert last is not None
    assert result.error is None, (
        f"Run errored: {result.error!r}; see artifact: {result.artifacts_path}"
    )

    # Combat resolved (all enemies dead, player survived).
    _assert_combat_resolved(result)

    # Korbar must be dead by end of fight (she started at 1 HP).
    korbar_info = last.status.combatants.get("korbar")
    if korbar_info is not None:
        assert not korbar_info["alive"], (
            f"Korbar survived despite starting at 1 HP: {korbar_info}; "
            f"see artifact: {result.artifacts_path}"
        )
    # If korbar is absent from combatants, she was removed after death
    # — that's also acceptable and confirms KO handling.

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

    # Judge verdict.
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        pytest.fail(f"Judge LLM unparseable: {exc}\nSee artifact: {result.artifacts_path}")
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        pytest.fail(
            "LLM judge rejected the ally-death run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}"
        )
