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

"""LLM integration test: encounter-driven combat entry, targeting AI,
HP-gated NPC abilities, passive NPCs, and turn passing in Ambush Alley.

A driver LLM plays the player against the real GM LLM on the
``ambush_alley`` fixture, where combat starts via an encounter (the
cutpurse's whistle) rather than a direct player attack.  Hard
assertions verify the engine mechanics; an advisory LLM judge records
a narration-quality verdict in the artifact (it does not gate the
test).
"""

from __future__ import annotations

import warnings

import pytest

from tests.integration.helpers import assert_combat_concluded, combat_log_entries
from tests.integration.runner import run_scenario
from tests.integration.test_combat_arena import (
    _record_judge_verdict,
    _stop_when_combat_ended,
)

pytestmark = pytest.mark.llm

_ENEMIES = {"cutpurse", "hired_thug", "frenzied_howler"}


def _assert_ambush_started_combat(result) -> None:
    """Assert the encounter path fired: the ambush flag is set and all
    three gang members joined as enemies on the combat-start turn."""
    start_turn = None
    for t in result.turns:
        if t.status.in_combat:
            start_turn = t
            break
    assert start_turn is not None, (
        "Combat never started; see artifact: " + str(result.artifacts_path)
    )
    assert "ambush_triggered" in start_turn.status.active_flags, (
        "Combat started without the 'ambush_triggered' flag — the driver "
        "probably attacked directly instead of triggering the encounter; "
        f"see artifact: {result.artifacts_path}"
    )
    for eid in _ENEMIES:
        info = start_turn.status.combatants.get(eid)
        assert info is not None and info.get("side") == "enemy", (
            f"'{eid}' not an enemy combatant on the combat-start turn; "
            f"see artifact: {result.artifacts_path}"
        )


# ------------------------------------------------------------------
# Scenario 5: encounter-driven combat entry
# ------------------------------------------------------------------

AMBUSH_DIRECTIVE = """\
The cutpurse loitering ahead stole your coin purse an hour ago.  Your
pack mule trails behind you.

- Physically grab the cutpurse by the collar to take back your purse.
  Do NOT attack him with your sword and do NOT talk to him — just
  grab him by the collar.
- Once his crew jumps in and the fight starts, defend yourself: fight
  them with your longsword until they are all defeated.
- If your HP drops below half, drink a healing potion.
"""


@pytest.mark.llm
def test_ambush_trigger(
    gm_client,
    driver_client,
    judge_client,
    ambush_alley_dir,
    artifacts_dir,
    tmp_path,
):
    """Combat starts via the cutpurse's encounter, not a player attack."""
    result = run_scenario(
        scenario_name="ambush_trigger",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=ambush_alley_dir,
        artifacts_dir=artifacts_dir,
        directive=AMBUSH_DIRECTIVE,
        max_turns=20,
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

    # Combat started via the encounter: flag set, gang joined as enemies.
    _assert_ambush_started_combat(result)

    # Combat concluded (win or graceful loss).
    assert_combat_concluded(result, _ENEMIES)

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 6: targeting AI + HP-gated NPC ability + passive NPC
# ------------------------------------------------------------------

TARGETING_DIRECTIVE = """\
The cutpurse ahead stole your coin purse.  Physically grab him by the
collar to take it back (do not attack him, do not talk to him) — his
crew will jump in.

- When the fight starts, focus your attacks on the frenzied howler
  first, then the hired thug, then the cutpurse.
- Keep fighting until all enemies are defeated.
- Your pack mule will not fight — ignore it.
- If your HP drops below half, drink a healing potion.
"""


@pytest.mark.llm
def test_targeting_and_frenzy(
    gm_client,
    driver_client,
    judge_client,
    ambush_alley_dir,
    artifacts_dir,
    tmp_path,
):
    """Thug always targets the player; frenzy only when bloodied; mule passive."""
    result = run_scenario(
        scenario_name="targeting_and_frenzy",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=ambush_alley_dir,
        artifacts_dir=artifacts_dir,
        directive=TARGETING_DIRECTIVE,
        max_turns=20,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat started via the encounter and concluded (win or graceful loss).
    _assert_ambush_started_combat(result)
    assert_combat_concluded(result, _ENEMIES)

    # The hired thug's 'player' targeting: every attack it makes aims at
    # the player, and it attacks at least once.
    thug_attacks = list(
        combat_log_entries(result, actor="hired_thug", action="attack")
    )
    assert thug_attacks, (
        "Hired thug never attacked; see artifact: " + str(result.artifacts_path)
    )
    for e in thug_attacks:
        assert e.get("target") == "player", (
            f"Thug (targeting='player') attacked {e.get('target')}; "
            f"see artifact: {result.artifacts_path}"
        )

    # The frenzied howler's ability is HP-gated: every frenzy entry must
    # come in a turn at or after the howler first dropped below half HP
    # (7 of 14) in the per-turn status snapshots.
    first_low_turn = None
    for ti, t in enumerate(result.turns):
        howler = t.status.combatants.get("frenzied_howler")
        if howler and howler.get("alive") and (howler.get("hp") or 999) < 7:
            first_low_turn = ti
            break
    frenzy_turns = [
        ti for ti, t in enumerate(result.turns)
        for e in t.combat_log
        if e.get("attack_id") == "frenzy"
    ]
    if frenzy_turns:
        assert first_low_turn is not None and first_low_turn <= frenzy_turns[0], (
            f"Frenzy used in turn {frenzy_turns[0] + 1} before the howler "
            f"was ever bloodied (first low-HP turn: "
            f"{None if first_low_turn is None else first_low_turn + 1}); "
            f"see artifact: {result.artifacts_path}"
        )
    else:
        warnings.warn(
            "Howler never frenzied (died before acting while bloodied, or "
            "never bloodied); HP-gated ability path untested this run; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )

    # The pack mule is a passive ally: it joins combat on the player's
    # side but never attacks.
    mule_joined = any(
        (t.status.combatants.get("pack_mule") or {}).get("side") == "party"
        for t in result.turns
        if t.status.in_combat
    )
    assert mule_joined, (
        "Pack mule never appeared as a party combatant; "
        f"see artifact: {result.artifacts_path}"
    )
    mule_attacks = list(
        combat_log_entries(result, actor="pack_mule", action="attack")
    )
    assert not mule_attacks, (
        f"Passive pack mule attacked {len(mule_attacks)} time(s); "
        f"see artifact: {result.artifacts_path}"
    )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 7: wait (pass turn) + out-of-bounds talk handled gracefully
# ------------------------------------------------------------------

HOLD_DIRECTIVE = """\
The cutpurse ahead stole your coin purse.  Physically grab him by the
collar to take it back (do not attack him, do not talk to him) — his
crew will jump in.

- When the fight starts, on your FIRST combat turn just stand there
  catching your breath — do not attack, do not use an item or ability,
  do not look around, do not flee.  Pass the turn completely.
- On your next turn, try to talk the hired thug into standing down —
  offer to let them all walk away.  (The GM will likely rule that
  talking is not possible in the middle of a fight.)
- After that, fight them with your longsword until all are defeated.
- If your HP drops below half, drink a healing potion.
"""


@pytest.mark.llm
def test_hold_and_talk_rejected(
    gm_client,
    driver_client,
    judge_client,
    ambush_alley_dir,
    artifacts_dir,
    tmp_path,
):
    """A combat turn is passed via wait; a mid-combat talk attempt is
    handled gracefully (the ruling model refuses or the engine copes)."""
    result = run_scenario(
        scenario_name="hold_and_talk_rejected",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=ambush_alley_dir,
        artifacts_dir=artifacts_dir,
        directive=HOLD_DIRECTIVE,
        max_turns=22,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat started via the encounter and concluded (win or graceful
    # loss).  This also asserts no exceptions and no empty narrations,
    # which is the graceful-handling check for the talk attempt: the
    # engine has no hard rejection of talk during combat, so the ruling
    # model is expected to refuse or redirect it — either way the run
    # must continue cleanly.
    _assert_ambush_started_combat(result)
    assert_combat_concluded(result, _ENEMIES)

    # The driver was told to hold its ground on the first combat turn —
    # a 'wait' entry must be in the log.
    has_wait = (
        next(combat_log_entries(result, actor="player", action="wait"), None)
        is not None
    )
    assert has_wait, (
        "No 'wait' combat-log entry for the player; the hold-your-ground "
        f"turn was not passed via wait; see artifact: {result.artifacts_path}"
    )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)
