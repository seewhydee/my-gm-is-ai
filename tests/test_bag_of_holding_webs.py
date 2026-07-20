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

"""Tests for web-traversal mechanics using an in-memory test corpus."""

import pytest

from mgmai.engine.engine import resolve
from mgmai.models.actions import MoveAction
from tests.helpers import (
    build_state_manager,
    make_webs_hard_state,
    make_webs_test_corpus,
)


class TestAxeHandleLowerWebbing:
    def _exit_ids(self, result):
        return {e.id for e in result.room_after.exits_available}

    def _suppress_spider(self, sm):
        """Suppress spider encounters so we can test traversal in isolation."""
        from mgmai.models.actions import HardStateChanges
        hard = sm.hard_state
        hard.entity_states["spider"]["hidden"] = True
        sm.apply_hard_changes(
            HardStateChanges(entity_state_changes={"spider": {"location": None}})
        )

    def test_enter_from_upper_shows_back_up_and_force_down(self):
        hard = make_webs_hard_state(location="axe_handle_upper")
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        action = MoveAction(
            action_type="move",
            target="exit_down_handle_upper",
            detail="Climb down to the lower handle",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "axe_handle_lower"

        exit_ids = self._exit_ids(result)
        assert "exit_up_handle_lower" in exit_ids
        assert "exit_force_through_web" in exit_ids
        assert "exit_drop_from_lower" in exit_ids

    def test_enter_from_floor_shows_back_down_and_force_up(self):
        hard = make_webs_hard_state(
            location="bag_floor", korbar_following=True
        )
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        action = MoveAction(
            action_type="move",
            target="exit_climb_up_handle_floor",
            detail="Climb up the axe handle",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "axe_handle_lower"

        exit_ids = self._exit_ids(result)
        assert "exit_up_handle_lower" in exit_ids
        assert "exit_force_through_web" in exit_ids
        assert "exit_drop_from_lower" in exit_ids

    def test_cleared_webs_shows_normal_exits_both_ways(self):
        hard = make_webs_hard_state(
            location="axe_handle_lower",
            flags={"webs_cleared": True},
        )
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        # Move down with cleared webs — traversal succeeds without check.
        action = MoveAction(
            action_type="move",
            target="exit_force_through_web",
            detail="Move through the cleared web path",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"

        # Move back up to the lower handle with webs cleared.
        sm.hard_state.player.location = "bag_floor"
        sm.hard_state.entity_states["korbar"]["following"] = True

        action = MoveAction(
            action_type="move",
            target="exit_climb_up_handle_floor",
            detail="Climb up the axe handle",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "axe_handle_lower"

        exit_ids = self._exit_ids(result)
        assert "exit_up_handle_lower" in exit_ids
        assert "exit_force_through_web" in exit_ids
        assert "exit_drop_from_lower" in exit_ids

    def test_force_through_web_with_sword_reduces_dc(self, monkeypatch):
        hard = make_webs_hard_state(
            location="axe_handle_lower",
            inventory={"toenail_sword": 1},
        )
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        # STR 10 + roll 12 = 22, beats DC 10 (weapon override).
        monkeypatch.setattr(
            "mgmai.engine.systems.five_e.random.randint", lambda a, b: 12
        )

        action = MoveAction(
            action_type="move",
            target="exit_force_through_web",
            using="toenail_sword",
            detail="Slash through the webs with the sword",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"

    def test_force_through_web_barehanded_higher_dc(self, monkeypatch):
        hard = make_webs_hard_state(location="axe_handle_lower")
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        # STR 10 + roll 3 = 13, fails DC 14 (bare-handed).
        monkeypatch.setattr(
            "mgmai.engine.systems.five_e.random.randint", lambda a, b: 3
        )

        action = MoveAction(
            action_type="move",
            target="exit_force_through_web",
            detail="Push through the webs bare-handed",
        )
        result = resolve(action, sm)
        assert result.success is True
        # Check failed — player stays in place.
        assert sm.hard_state.player.location == "axe_handle_lower"

    def test_force_through_web_triggers_spider_encounter(self, monkeypatch):
        hard = make_webs_hard_state(
            location="axe_handle_lower",
            inventory={"toenail_sword": 1},
            spider_hidden=False,
        )
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)

        # Roll fails the weapon DC 10 — traversal check fails, but
        # the traversal.attempted reaction still triggers the spider
        # encounter, starting multi-round combat.
        monkeypatch.setattr(
            "mgmai.engine.systems.five_e.random.randint", lambda a, b: 3
        )

        action = MoveAction(
            action_type="move",
            target="exit_force_through_web",
            using="toenail_sword",
            detail="Slash at the webs",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert result.combat_triggered is True

    def test_one_way_drop_can_be_repeated(self):
        """A one-way exit only lacks a reverse exit; the drop itself is repeatable."""
        hard = make_webs_hard_state(location="axe_handle_lower")
        sm = build_state_manager(make_webs_test_corpus(), hard_state=hard)
        self._suppress_spider(sm)

        action = MoveAction(
            action_type="move",
            target="exit_drop_from_lower",
            detail="Drop over the side",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"

        # Climb back up (simulated) and drop again.
        sm.hard_state.player.location = "axe_handle_lower"
        action = MoveAction(
            action_type="move",
            target="exit_drop_from_lower",
            detail="Drop over the side again",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"
