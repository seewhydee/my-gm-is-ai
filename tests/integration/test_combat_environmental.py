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
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""LLM integration test: non-combat actions during combat in the Lever Room.

A driver LLM plays the player against the real GM LLM on the
``lever_room`` fixture, which holds a sentry golem (the fight), a winch
lever (an ``interact`` target), and a caged war hound whose cage release
triggers an encounter that merges it into the active combat as a
reinforcement.  Hard assertions verify the engine mechanics:

- pulling the lever mid-combat fires the interaction's Result (the
  ``lever_pulled`` flag) AND the enemies still take their turns (the
  golem attacks in the same or a later round; the round advances);
- opening the cage mid-combat merges the hound into the running fight
  (``reinforcement`` log entry, hound joins as an enemy combatant);
- a mid-combat talk attempt is handled gracefully (ruling-validation
  retry or engine rejection) and combat continues to a clean end.

An advisory LLM judge records a narration-quality verdict in the
artifact (it does not gate the test).
"""

from __future__ import annotations

import warnings

import pytest

from tests.integration.helpers import assert_combat_concluded, combat_log_entries
from tests.integration.judge import record_judge_verdict
from tests.integration.runner import run_scenario
from tests.integration.test_combat_arena import _stop_when_combat_ended

pytestmark = pytest.mark.llm

_ENEMIES = {"sentry_golem", "war_hound"}

LEVER_DIRECTIVE = """\
A sentry golem bars the gate ahead of you.  There is a heavy winch
lever on the wall and a snarling war hound locked in an iron cage.

- Attack the sentry golem with your longsword.
- Once the fight starts, on your FIRST combat turn do NOT attack —
  pull the winch lever on the wall instead.
- On your SECOND combat turn do NOT attack — lift the latch on the
  hound's cage and open the cage door.  (The hound will join the
  fight; that is expected.)
- On your THIRD combat turn, try to talk to the golem — order it to
  stand down.  (The GM will likely rule that talking is not possible
  in the middle of a fight.)
- After that, fight the golem and the hound with your longsword until
  all enemies are defeated.
- If your HP drops below half, drink a healing potion.
"""


@pytest.mark.llm
def test_environmental_actions_in_combat(
    gm_client,
    driver_client,
    judge_client,
    lever_room_dir,
    artifacts_dir,
    tmp_path,
):
    """Interact fires its Result mid-combat while enemies still act; a
    start_combat Result mid-combat merges a reinforcement; a talk
    attempt is rejected without breaking the fight."""
    result = run_scenario(
        scenario_name="environmental_actions_in_combat",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=lever_room_dir,
        artifacts_dir=artifacts_dir,
        directive=LEVER_DIRECTIVE,
        max_turns=24,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
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

    # Combat started with the golem alone — the hound must NOT be a
    # combatant until its cage is opened.
    start_turn = None
    for t in result.turns:
        if t.status.in_combat:
            start_turn = t
            break
    assert start_turn is not None, (
        "Combat never started; see artifact: " + str(result.artifacts_path)
    )
    golem = start_turn.status.combatants.get("sentry_golem")
    assert golem is not None and golem.get("side") == "enemy", (
        "'sentry_golem' not an enemy combatant on the combat-start turn; "
        f"see artifact: {result.artifacts_path}"
    )
    assert "war_hound" not in start_turn.status.combatants, (
        "War hound was a combatant before its cage was opened; "
        f"see artifact: {result.artifacts_path}"
    )

    # --- The lever pull: Result fired AND the enemies still acted. ---
    lever_turn = None
    for ti, t in enumerate(result.turns):
        if "lever_pulled" in t.status.active_flags:
            lever_turn = ti
            break
    assert lever_turn is not None, (
        "The 'lever_pulled' flag was never set — the mid-combat lever "
        f"interaction never fired; see artifact: {result.artifacts_path}"
    )
    # The pull cost the player's combat turn: a player 'interact' entry
    # is logged for that turn's round.
    lever_entries = [
        e for e in result.turns[lever_turn].combat_log
        if e.get("actor") == "player" and e.get("action") == "interact"
    ]
    assert lever_entries, (
        f"No player 'interact' combat-log entry on the lever turn "
        f"(turn {lever_turn + 1}); see artifact: {result.artifacts_path}"
    )
    lever_round = lever_entries[0].get("round")
    # The enemies still took their turns: the golem attacked in the
    # lever round or later.
    golem_attacks = [
        e
        for e in combat_log_entries(result, actor="sentry_golem", action="attack")
        if lever_round is None or (e.get("round") or 0) >= lever_round
    ]
    assert golem_attacks, (
        "The golem never attacked in or after the lever round — the "
        "lever pull froze the fight instead of costing the player's "
        f"turn; see artifact: {result.artifacts_path}"
    )
    # The round advanced past the lever round.
    later_entries = [
        e
        for t in result.turns
        for e in t.combat_log
        if lever_round is not None and (e.get("round") or 0) > lever_round
    ]
    assert later_entries, (
        f"No combat-log entries after round {lever_round} — the round "
        f"never advanced after the lever pull; "
        f"see artifact: {result.artifacts_path}"
    )

    # --- The cage release: the hound merged as a reinforcement. ---
    reinf = list(
        combat_log_entries(result, actor="war_hound", action="reinforcement")
    )
    assert reinf, (
        "No 'reinforcement' combat-log entry for the war hound — "
        "opening the cage mid-combat did not merge it into the active "
        f"fight; see artifact: {result.artifacts_path}"
    )
    hound_joined = any(
        (t.status.combatants.get("war_hound") or {}).get("side") == "enemy"
        for t in result.turns
        if t.status.in_combat
    )
    assert hound_joined, (
        "War hound never appeared as an enemy combatant; "
        f"see artifact: {result.artifacts_path}"
    )

    # --- Combat concluded cleanly (win or graceful loss).  This is
    # also the talk-attempt check: the driver was told to try talking
    # to the golem mid-fight; the ruling model's corrective retry (or
    # the engine backstop) must have kept the run going — no dialogue
    # mode, no exceptions, no empty narrations, combat ends cleanly.
    assert_combat_concluded(result, _ENEMIES)

    # The corrective retry instructs a 'wait' with the speech in
    # 'detail'; a player wait entry is the expected footprint.  Soft
    # check only — the ruling model may also have ruled the speech as
    # wait without a log-visible trace or redirected it differently.
    has_wait = (
        next(combat_log_entries(result, actor="player", action="wait"), None)
        is not None
    )
    if not has_wait:
        warnings.warn(
            "No player 'wait' combat-log entry; the mid-combat talk "
            "attempt was not ruled as a turn pass this run (combat "
            f"still concluded cleanly); see artifact: {result.artifacts_path}",
            stacklevel=2,
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    record_judge_verdict(judge_client, result)
