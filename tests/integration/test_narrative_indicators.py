# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
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

"""LLM integration tests for marker-based inline mechanical indicators.

Each scenario runs ONE fixed turn: a hand-written PlayerAction is
resolved by the real engine (Call 1 ruling is bypassed so the
engine-generated text is controlled), the engine's indicators are
passed to the real GM prose call, and the marker-replaced narration is
checked.

Hard assertions (the gate) cover player-facing output correctness:

- the expected indicators were produced by the engine;
- the final player-facing narration contains no leftover marker
  syntax (a mangled, paraphrased, or duplicated marker would survive
  replacement and leak to the player);
- each indicator's canonical text appears exactly once (nothing
  dropped, no duplicated mechanical summaries) — and so does each
  indicator's plain description, which catches the narrator writing
  out the mechanical text itself in addition to placing the marker.

Marker *placement* (how many markers the narrator placed inline, and
where) is model-quality behaviour that varies between runs; it is
recorded in the artifact and surfaced as a warning, never a gate —
the fallback keeps the player-facing output correct regardless.  An
advisory LLM judge (``indicator_judge.py``) scores marker placement
quality, mechanical fidelity, cleanliness, and narration quality; its
verdict is likewise recorded in the artifact and surfaced as a
warning, never a test failure.

Scenarios use the ``indicator_hall`` fixture, whose checks are
authored with unreachable/pass-everything targets so their outcomes
(and thus the indicator sets) are deterministic:

- ``pillar shove``: STR check with target 3 vs STR 16 — always
  succeeds; exactly one ``check`` indicator.
- ``bridge cross``: DEX then CON checks with target 30 vs stat 10 —
  both always fail, the second dealing damage; two ``check``
  indicators plus one ``hp`` indicator in a single turn.
- ``attack golem``: mid-combat round (preset combat state) — the
  player's attack and the golem's retaliation yield multiple ``combat``
  indicators in one turn.
- ``attack dummy``: mid-combat attack on a 1-HP dummy (seeded dice) —
  an attack entry plus a death entry in one turn, ending combat.
"""

from __future__ import annotations

import warnings
from collections import Counter

import pytest

from mgmai.models.combat import CombatState
from mgmai.state.manager import StateManager

from tests.integration.indicator_judge import judge_indicator_turn
from tests.integration.indicator_runner import run_indicator_turn
from tests.integration.judge import JudgeError, format_verdict_for_failure

pytestmark = pytest.mark.llm

# Pinned dice for the two combat scenarios (see module docstring).
_COMBAT_SEED = 7


def _sm(indicator_hall_dir) -> StateManager:
    return StateManager(adventure_dir=str(indicator_hall_dir))


def _sm_in_combat(indicator_hall_dir, enemy: str) -> StateManager:
    """Load the fixture with the player mid-combat in the sparring
    chamber, acting first against the given enemy."""
    sm = _sm(indicator_hall_dir)
    sm.hard_state.player.location = "sparring"
    sm.hard_state.combat = CombatState(
        active=True,
        combatants=["player", enemy],
        initiative_order=["player", enemy],
        current_index=0,
        round_number=1,
    )
    return sm


def _assert_indicator_turn(
    result,
    *,
    expected_categories: dict[str, int],
) -> None:
    """Hard assertions shared by all indicator scenarios.

    ``expected_categories`` maps category -> exact count, e.g.
    ``{"check": 2, "hp": 1}``.
    """
    assert result.error is None, (
        f"Turn raised {result.error!r}; see artifact: {result.artifacts_path}"
    )

    # Engine produced the expected indicator set.
    counts = Counter(ind["category"] for ind in result.indicators)
    assert counts == Counter(expected_categories), (
        f"Expected indicators {expected_categories}, got {dict(counts)}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert len(result.indicators) >= 1

    # The narrator produced something at all.
    assert result.raw_narration and result.raw_narration.strip(), (
        f"Narrator produced empty narration; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.final_narration and result.final_narration.strip()

    # Marker placement is advisory, not a gate: whether the narrator
    # places markers inline is model-quality behaviour that varies
    # between runs (the fallback keeps the player-facing output
    # correct either way).  Record it and warn so that systematic
    # non-use is visible without making the red/green signal flaky.
    placed = result.placed_count
    if placed == 0:
        warnings.warn(
            f"Narrator placed no markers inline (0/{len(result.indicators)}); "
            f"the interleaving mechanism went unused this turn; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
    elif placed < len(result.indicators):
        warnings.warn(
            f"Narrator placed {placed}/{len(result.indicators)} markers "
            f"inline; the rest fell back to prepending; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )

    # No leftover marker syntax in the player-facing text (a mangled
    # or duplicated marker would survive replacement).
    assert "[MECH" not in result.final_narration, (
        f"Residual marker syntax in final narration:\n"
        f"{result.final_narration}\nsee artifact: {result.artifacts_path}"
    )

    # Each indicator's canonical text appears exactly once (no dropped
    # indicators, no duplicated mechanical summaries).  The plain
    # description must appear exactly once too — it is a substring of
    # the canonical text, so a count above 1 means the narrator wrote
    # out the mechanical text itself in addition to placing the
    # marker (an observed failure mode).
    for ind in result.indicators:
        count = result.final_narration.count(ind["formatted"])
        assert count == 1, (
            f"{ind['formatted']!r} appears {count} times in final narration "
            f"(expected exactly 1):\n{result.final_narration}\n"
            f"see artifact: {result.artifacts_path}"
        )
        plain = ind["plain_description"]
        plain_count = result.final_narration.count(plain)
        assert plain_count == 1, (
            f"{plain!r} appears {plain_count} times in final narration "
            f"(expected exactly 1 — the narrator may have duplicated the "
            f"mechanical text next to the marker):\n"
            f"{result.final_narration}\nsee artifact: {result.artifacts_path}"
        )


def _record_judge_verdict(judge_client, result) -> None:
    """Run the advisory LLM judge and record its verdict in the artifact.

    The judge does not gate the test: deterministic assertions decide
    pass/fail.  An unparseable verdict or a judge "fail" verdict only
    produces a warning, so the test signal stays stable across reruns.
    """
    try:
        verdict = judge_indicator_turn(judge_client, result)
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
            "Advisory judge rejected the turn.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}",
            stacklevel=2,
        )


# ------------------------------------------------------------------
# Scenario 1: a single stat check indicator
# ------------------------------------------------------------------

@pytest.mark.llm
def test_single_check_indicator(
    gm_client,
    judge_client,
    indicator_hall_dir,
    artifacts_dir,
    tmp_path,
):
    """One guaranteed-success STR check → one [MECH:check:0] marker."""
    result = run_indicator_turn(
        scenario_name="indicator_single_check",
        gm_client=gm_client,
        state_manager=_sm(indicator_hall_dir),
        action={
            "action_type": "interact",
            "target": "cracked_pillar",
            "interaction_id": "shove",
            "detail": "Shove the cracked pillar over.",
        },
        player_input="shove the cracked pillar",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_indicator_turn(result, expected_categories={"check": 1})

    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 2: multiple indicators in one turn (checks + HP change)
# ------------------------------------------------------------------

@pytest.mark.llm
def test_multiple_check_and_hp_indicators(
    gm_client,
    judge_client,
    indicator_hall_dir,
    artifacts_dir,
    tmp_path,
):
    """Guaranteed DEX fail → CON fail with damage → two check markers
    ([MECH:check:0], [MECH:check:1]) plus [MECH:hp] in one turn."""
    sm = _sm(indicator_hall_dir)
    hp_before = sm.hard_state.player.current_hp
    result = run_indicator_turn(
        scenario_name="indicator_multi_check_hp",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "interact",
            "target": "rickety_bridge",
            "interaction_id": "cross",
            "detail": "Cross the rickety bridge.",
        },
        player_input="cross the rickety bridge",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_indicator_turn(result, expected_categories={"check": 2, "hp": 1})

    # The HP indicator reflects real damage taken this turn.
    assert sm.hard_state.player.current_hp < hp_before

    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 3: a combat round with multiple combat indicators
# ------------------------------------------------------------------

@pytest.mark.llm
def test_combat_round_indicators(
    gm_client,
    judge_client,
    indicator_hall_dir,
    artifacts_dir,
    tmp_path,
):
    """Mid-combat attack vs the golem → player attack + golem
    retaliation markers ([MECH:combat:0], [MECH:combat:1]) in one turn."""
    sm = _sm_in_combat(indicator_hall_dir, "sparring_golem")
    result = run_indicator_turn(
        scenario_name="indicator_combat_round",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "sparring_golem",
            "detail": "Attack the sparring golem.",
        },
        player_input="attack the sparring golem",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_COMBAT_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Both combatants act this round and both survive: exactly two
    # combat indicators (one per combat log entry); the seeded golem
    # hit also yields an hp indicator.
    _assert_indicator_turn(
        result, expected_categories={"combat": 2, "hp": 1}
    )

    # Combat is still ongoing (the golem is far from dead).
    assert sm.hard_state.combat is not None and sm.hard_state.combat.active

    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 4: attack + death indicators in one turn
# ------------------------------------------------------------------

@pytest.mark.llm
def test_attack_and_death_indicators(
    gm_client,
    judge_client,
    indicator_hall_dir,
    artifacts_dir,
    tmp_path,
):
    """Mid-combat attack on the 1-HP dummy → attack marker plus a
    death marker ([MECH:combat:1] → '**Battered Dummy is dead!**')."""
    sm = _sm_in_combat(indicator_hall_dir, "battered_dummy")
    result = run_indicator_turn(
        scenario_name="indicator_attack_death",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "battered_dummy",
            "detail": "Strike the battered dummy.",
        },
        player_input="strike the battered dummy",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_COMBAT_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_indicator_turn(result, expected_categories={"combat": 2})

    # A death entry was produced and combat ended with the kill.
    assert any("is dead!" in ind["formatted"] for ind in result.indicators), (
        f"No death indicator produced; see artifact: {result.artifacts_path}"
    )
    assert sm.hard_state.combat is None or not sm.hard_state.combat.active

    _record_judge_verdict(judge_client, result)
