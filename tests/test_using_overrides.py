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

"""Tests for using_results override semantics.

An override replaces what it specifies and inherits what it omits:
a check-bearing override resolves its own check, with success/failure
branches falling back to the parent's; a result-only override applies
its result outright (an automatic success on traversal checks).
"""

import pytest

from mgmai.engine.engine import resolve
from mgmai.engine.resolver import resolve_interact
from mgmai.models.actions import HardStateChanges, InteractAction, MoveAction
from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    Entity,
    ModuleCorpus,
    Result,
    StatCheck,
    UsingResultOverride,
)
from tests.helpers import (
    _STATS_5E,
    _mk_hard_state,
    _mk_item_entity,
    _mk_room,
    build_state_manager,
    make_webs_hard_state,
    make_webs_test_corpus,
)


def _web_traversal_check(corpus):
    return next(
        e
        for e in corpus.rooms["axe_handle_lower"].exits
        if e.id == "exit_force_through_web"
    ).traversal_check


def _suppress_spider(sm):
    """Suppress spider encounters so we can test traversal in isolation."""
    hard = sm.hard_state
    hard.entity_states["spider"]["hidden"] = True
    sm.apply_hard_changes(
        HardStateChanges(entity_state_changes={"spider": {"location": None}})
    )


def _webs_sm(corpus, **hard_kwargs):
    hard = make_webs_hard_state(location="axe_handle_lower", **hard_kwargs)
    sm = build_state_manager(corpus, hard_state=hard)
    _suppress_spider(sm)
    return sm


class TestTraversalUsingOverrides:
    def test_override_branches_replace_parent(self, monkeypatch):
        corpus = make_webs_test_corpus()
        tc = _web_traversal_check(corpus)
        tc.success = Result(set_flag={"webs_cleared": True})
        tc.using_results = {
            "toenail_sword": UsingResultOverride(
                check=StatCheck(type="stat_check", stat="STR", target=10, repeatable=True),
                success=Result(narrative="You slice through.", set_flag={"spider_fled": True}),
            )
        }
        sm = _webs_sm(corpus, inventory={"toenail_sword": 1})

        # STR 10 + roll 12 = 12: passes override DC 10, would fail parent DC 14.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 12)
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="toenail_sword", detail="Slash through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"
        # Override success applied; parent success NOT applied.
        assert sm.hard_state.flags["spider_fled"] is True
        assert sm.hard_state.flags["webs_cleared"] is False

    def test_check_only_override_inherits_parent_success(self, monkeypatch):
        corpus = make_webs_test_corpus()
        tc = _web_traversal_check(corpus)
        tc.success = Result(narrative="Through!", set_flag={"webs_cleared": True})
        tc.using_results = {
            "toenail_sword": UsingResultOverride(
                check=StatCheck(type="stat_check", stat="STR", target=10, repeatable=True),
            )
        }
        sm = _webs_sm(corpus, inventory={"toenail_sword": 1})

        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 12)
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="toenail_sword", detail="Slash through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"
        # Parent success inherited by the check-only override.
        assert sm.hard_state.flags["webs_cleared"] is True
        assert any("Through!" in n for n in result.triggered_narration)

    def test_check_only_override_inherits_parent_failure(self, monkeypatch):
        corpus = make_webs_test_corpus()
        tc = _web_traversal_check(corpus)
        tc.using_results = {
            "toenail_sword": UsingResultOverride(
                check=StatCheck(type="stat_check", stat="STR", target=10, repeatable=True),
            )
        }
        sm = _webs_sm(corpus, inventory={"toenail_sword": 1})

        # Roll 5 fails override DC 10.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 5)
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="toenail_sword", detail="Slash through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "axe_handle_lower"
        # Parent failure inherited by the check-only override.
        assert any("The webs hold fast." in n for n in result.triggered_narration)

    def test_result_only_override_auto_succeeds(self):
        corpus = make_webs_test_corpus()
        tc = _web_traversal_check(corpus)
        tc.using_results = {
            "toenail_sword": UsingResultOverride(
                result=Result(narrative="You glide through the webs.")
            )
        }
        sm = _webs_sm(corpus, inventory={"toenail_sword": 1})

        # No monkeypatching: no check is rolled at all.
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="toenail_sword", detail="Glide through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"
        assert any("You glide through the webs." in n for n in result.triggered_narration)

    def test_exact_match_takes_precedence_over_wildcard(self, monkeypatch):
        corpus = make_webs_test_corpus()
        tc = _web_traversal_check(corpus)
        tc.using_results = {
            "*": UsingResultOverride(
                check=StatCheck(type="stat_check", stat="STR", target=10, repeatable=True),
            ),
            "toenail_sword": UsingResultOverride(
                check=StatCheck(type="stat_check", stat="STR", target=16, repeatable=True),
            ),
        }
        sm = _webs_sm(corpus, inventory={"toenail_sword": 1})

        # Roll 12: fails the exact-match DC 16, would pass the wildcard DC 10.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 12)
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="toenail_sword", detail="Slash through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "axe_handle_lower"

        # An unlisted item falls through to the wildcard DC 10 and passes.
        action = MoveAction(
            action_type="move", target="exit_force_through_web",
            using="giant_key", detail="Pry through",
        )
        result = resolve(action, sm)
        assert result.success is True
        assert sm.hard_state.player.location == "bag_floor"


def _make_door_corpus() -> ModuleCorpus:
    door = Entity.model_validate({
        "type": "feature",
        "id": "door",
        "name": "door",
        "description": "A stout door.",
        "interactions": [
            {
                "id": "force_door",
                "description": "Shoulder the door open.",
                "check": {"type": "stat_check", "stat": "STR", "target": 18, "repeatable": True},
                "success": {"narrative": "The door bursts open.", "set_flag": {"door_open": True}},
                "failure": {"narrative": "The door holds firm."},
                "using_results": {
                    "crowbar": {
                        "check": {"type": "stat_check", "stat": "STR", "target": 12, "repeatable": True},
                    },
                    "*": {
                        "check": {"type": "stat_check", "stat": "STR", "target": 15, "repeatable": True},
                    },
                },
            }
        ],
    })
    hall = _mk_room("hall", "Hall", contains=["door"], is_start_room=True)
    return ModuleCorpus(
        adventure=Adventure(
            title="Door Test",
            introduction="A test.",
            atmosphere=Atmosphere(setting="test", tone="neutral"),
        ),
        rooms={"hall": hall},
        entities={
            "door": door,
            "crowbar": _mk_item_entity("crowbar"),
            "hammer": _mk_item_entity("hammer"),
        },
        stats=_STATS_5E,
        flags_declared=["door_open"],
    )


def _door_sm():
    corpus = _make_door_corpus()
    hard = _mk_hard_state(
        player_location="hall",
        flags={"door_open": False},
        inventory={"crowbar": 1, "hammer": 1},
    )
    return build_state_manager(corpus, hard_state=hard)


class TestInteractionUsingOverrides:
    def test_override_fires_when_parent_has_check(self, monkeypatch):
        sm = _door_sm()
        # Roll 13: passes override DC 12, would fail parent DC 18.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 13)
        action = InteractAction(
            action_type="interact", target="door", interaction_id="force_door",
            using="crowbar", detail="Pry the door open",
        )
        result = resolve_interact(action, sm.hard_state, sm.soft_state, sm.corpus, sm)
        assert result.success is True
        # Parent success branch inherited by the check-only override.
        assert result.hard_changes.flags_set.get("door_open") is True
        assert any("The door bursts open." in n for n in result.triggered_narration)

    def test_override_check_failure_inherits_parent_failure(self, monkeypatch):
        sm = _door_sm()
        # Roll 5: fails override DC 12.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 5)
        action = InteractAction(
            action_type="interact", target="door", interaction_id="force_door",
            using="crowbar", detail="Pry the door open",
        )
        result = resolve_interact(action, sm.hard_state, sm.soft_state, sm.corpus, sm)
        assert result.success is True
        assert not result.hard_changes.flags_set.get("door_open")
        assert any("The door holds firm." in n for n in result.triggered_narration)

    def test_exact_match_takes_precedence_over_wildcard(self, monkeypatch):
        sm = _door_sm()
        # Roll 14: passes exact-match DC 12, would fail wildcard DC 15.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 14)
        action = InteractAction(
            action_type="interact", target="door", interaction_id="force_door",
            using="crowbar", detail="Pry the door open",
        )
        result = resolve_interact(action, sm.hard_state, sm.soft_state, sm.corpus, sm)
        assert result.success is True
        assert result.hard_changes.flags_set.get("door_open") is True

    def test_wildcard_matches_unlisted_item(self, monkeypatch):
        sm = _door_sm()
        # Roll 14: fails exact... hammer is unlisted, so wildcard DC 15 applies;
        # 14 < 15 fails.  Then roll 16 passes.
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 16)
        action = InteractAction(
            action_type="interact", target="door", interaction_id="force_door",
            using="hammer", detail="Bash the door open",
        )
        result = resolve_interact(action, sm.hard_state, sm.soft_state, sm.corpus, sm)
        assert result.success is True
        assert result.hard_changes.flags_set.get("door_open") is True


class TestUsingResultOverrideModel:
    def test_check_only_override_is_valid(self):
        override = UsingResultOverride.model_validate({
            "check": {"type": "stat_check", "stat": "STR", "target": 10, "repeatable": True},
        })
        assert override.check is not None
        assert override.success is None

    def test_check_and_result_still_rejected(self):
        with pytest.raises(ValueError, match="either check or result"):
            UsingResultOverride.model_validate({
                "check": {"type": "stat_check", "stat": "STR", "target": 10, "repeatable": True},
                "result": {"narrative": "Done."},
            })
