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

"""Integration tests for the bag-of-holding axe-handle-lower webbing logic."""

from pathlib import Path

import pytest

from mgmai.engine.engine import resolve
from mgmai.models.actions import InteractAction, MoveAction
from mgmai.state.manager import StateManager

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


@pytest.fixture
def bag_state_manager():
    """A StateManager loaded from the actual bag-of-holding adventure."""
    manager = StateManager()
    manager.load_all(BAG_OF_HOLDING)
    return manager


class TestAxeHandleLowerWebbing:
    def _exit_ids(self, result):
        return {e.id for e in result.room_after.exits_available}

    def test_enter_from_upper_shows_back_up_and_force_down(self, bag_state_manager):
        hard = bag_state_manager.hard_state
        hard.player.location = "axe_handle_upper"

        action = MoveAction(
            action_type="move",
            target="exit_down_handle_to_lower",
            detail="Climb down to the lower handle",
        )
        result = resolve(action, bag_state_manager)
        assert result.success is True
        assert hard.player.location == "axe_handle_lower"
        assert hard.room_states["axe_handle_lower"]["_entered_from"] == "axe_handle_upper"

        # After entering from above, the player can go back up freely or force down.
        exit_ids = self._exit_ids(result)
        assert "exit_up_handle_from_lower" in exit_ids
        assert "exit_through_webs_down" in exit_ids
        assert "exit_drop_from_lower" in exit_ids
        assert "exit_through_webs_up" not in exit_ids
        assert "exit_down_handle_to_floor" not in exit_ids

    def test_enter_from_floor_shows_back_down_and_force_up(self, bag_state_manager):
        hard = bag_state_manager.hard_state
        hard.player.location = "bag_floor"

        action = MoveAction(
            action_type="move",
            target="exit_climb_up_handle_from_floor",
            detail="Climb up the axe handle",
        )
        result = resolve(action, bag_state_manager)
        assert result.success is True
        assert hard.player.location == "axe_handle_lower"
        assert hard.room_states["axe_handle_lower"]["_entered_from"] == "bag_floor"

        exit_ids = self._exit_ids(result)
        assert "exit_down_handle_to_floor" in exit_ids
        assert "exit_through_webs_up" in exit_ids
        assert "exit_drop_from_lower" in exit_ids
        assert "exit_through_webs_down" not in exit_ids
        assert "exit_up_handle_from_lower" not in exit_ids

    def test_cleared_webs_shows_normal_exits_both_ways(self, bag_state_manager):
        hard = bag_state_manager.hard_state
        hard.player.location = "axe_handle_lower"
        hard.flags["webs_cleared"] = True

        action = MoveAction(
            action_type="move",
            target="exit_drop_from_lower",
            detail="Drop down",
        )
        result = resolve(action, bag_state_manager)
        assert result.success is True

        # Now move back into the lower handle from the floor with webs already cleared.
        hard.player.location = "bag_floor"
        action = MoveAction(
            action_type="move",
            target="exit_climb_up_handle_from_floor",
            detail="Climb up the axe handle",
        )
        result = resolve(action, bag_state_manager)
        assert result.success is True
        assert hard.player.location == "axe_handle_lower"

        exit_ids = self._exit_ids(result)
        assert "exit_up_handle_from_lower" in exit_ids
        assert "exit_down_handle_to_floor" in exit_ids
        assert "exit_drop_from_lower" in exit_ids

    def test_cut_webbing_with_sword_succeeds_and_clears_webs(
        self, bag_state_manager, monkeypatch
    ):
        hard = bag_state_manager.hard_state
        soft = bag_state_manager.soft_state
        hard.player.location = "axe_handle_lower"
        hard.player.inventory = ["toenail_sword"]

        # STR 10 + roll 15 = total 15, beating DC 10.
        monkeypatch.setattr("mgmai.engine.stat_checks.random.randint", lambda a, b: 15)

        action = InteractAction(
            action_type="interact",
            target="dense_webbing",
            interaction_id="cut_webbing",
            using="toenail_sword",
            detail="Player slashes through the dense webbing with the toenail sword.",
        )
        result = resolve(action, bag_state_manager)

        assert result.success is True
        assert hard.flags["webs_cleared"] is True
        # Two rolls: cut_webbing + spider encounter
        assert len(result.rolls) == 2
        cut_roll = result.rolls[0]
        assert cut_roll["type"] == "stat_check"
        assert cut_roll["stat"] == "STR"
        assert cut_roll["dc"] == 10
        assert cut_roll["success"] is True
        # Encounter outcome: spider attack with weapon -> stat_check STR DC 10 -> success -> flee
        assert result.encounter_outcome is not None
        assert result.encounter_outcome.outcome == "flee"
        assert hard.flags["spider_fled"] is True

    def test_cut_webbing_with_sword_fails_but_triggers_spider(
        self, bag_state_manager, monkeypatch
    ):
        hard = bag_state_manager.hard_state
        hard.player.location = "axe_handle_lower"
        hard.player.inventory = ["toenail_sword"]

        # STR 10 + roll 5 = total 5, failing DC 10 for both cut and spider attack.
        monkeypatch.setattr("mgmai.engine.stat_checks.random.randint", lambda a, b: 5)

        action = InteractAction(
            action_type="interact",
            target="dense_webbing",
            interaction_id="cut_webbing",
            using="toenail_sword",
            detail="Player slashes through the dense webbing with the toenail sword.",
        )
        result = resolve(action, bag_state_manager)

        # Action succeeds (interaction resolved), but the check itself fails.
        assert result.success is True
        assert hard.flags["webs_cleared"] is False
        # Two rolls: cut_webbing (fail) + spider encounter (fail -> death)
        assert len(result.rolls) == 2
        cut_roll = result.rolls[0]
        assert cut_roll["type"] == "stat_check"
        assert cut_roll["stat"] == "STR"
        assert cut_roll["dc"] == 10
        assert cut_roll["success"] is False
        # Spider encounter: armed, but failed STR check -> game over
        assert result.encounter_outcome is not None
        assert result.encounter_outcome.outcome == "death"
        assert result.game_over is not None
        assert result.game_over.type == "lose"

    def test_cut_webbing_not_usable_without_weapon(self, bag_state_manager):
        hard = bag_state_manager.hard_state
        hard.player.location = "axe_handle_lower"
        hard.player.inventory = []

        action = InteractAction(
            action_type="interact",
            target="dense_webbing",
            interaction_id="cut_webbing",
            detail="Player tries to tear through the webbing bare-handed.",
        )
        result = resolve(action, bag_state_manager)

        # Interaction condition fails (no weapon), but spider encounter still triggers
        assert "condition" in result.error.lower() or "not found" in result.error.lower()
        # Spider encounter: bare-handed -> death
        assert result.game_over is not None
        assert result.game_over.type == "lose"
