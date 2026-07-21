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

"""Tests for llm/ruling_validation.py — semantic validation of rulings."""

from __future__ import annotations

from mgmai.llm.ruling_validation import validate_ruling_action
from mgmai.models.actions import (
    CombatAction,
    MoveAction,
    WaitAction,
)
from mgmai.models.briefing import (
    BriefingExit,
    BriefingRoom,
    CombatBriefing,
    GMBriefing,
    PlayerStateBriefing,
)


def _combat_briefing(
    usable_items: list[dict] | None = None,
    abilities: list[dict] | None = None,
) -> GMBriefing:
    return GMBriefing(
        adventure_title="Test",
        setting="test",
        tone="neutral",
        turn=1,
        current_room=BriefingRoom(
            id="arena",
            name="Arena",
            description="A fighting pit.",
            exits_available=[
                BriefingExit(
                    id="exit_north", direction="north", target_room="hall"
                ),
            ],
        ),
        player_state=PlayerStateBriefing(location="arena"),
        player_input="I act.",
        combat_state=CombatBriefing(
            round_number=1,
            initiative_order=["player", "goblin"],
            current_actor="player",
            combatants=[
                {"id": "player", "name": "Player", "side": "party",
                 "current_hp": 10, "max_hp": 10, "status_effects": []},
                {"id": "korbar", "name": "Korbar", "side": "party",
                 "current_hp": 20, "max_hp": 20, "status_effects": []},
                {"id": "goblin", "name": "Goblin", "side": "enemy",
                 "current_hp": 7, "max_hp": 7, "status_effects": []},
            ],
            usable_items=(
                [{"id": "health_potion", "name": "Healing Potion",
                  "effects": "Heals 2d4+2 HP"}]
                if usable_items is None else usable_items
            ),
            abilities=(
                [
                    {"id": "second_wind", "name": "Second Wind",
                     "description": "Catch your breath.", "target": "self",
                     "uses_remaining": 1, "effect": "Heal 1d10 HP"},
                    {"id": "smite", "name": "Smite",
                     "description": "A holy strike.", "target": "enemy",
                     "uses_remaining": 2, "effect": "2d6 radiant damage"},
                    {"id": "rally", "name": "Rally",
                     "description": "Bolster an ally.", "target": "ally",
                     "uses_remaining": 1, "effect": "Ally gains 1d4 HP"},
                ]
                if abilities is None else abilities
            ),
        ),
    )


def _peaceful_briefing() -> GMBriefing:
    briefing = _combat_briefing()
    return briefing.model_copy(update={"combat_state": None})


def _combat(combat_action: str, target: str, ability_id: str | None = None):
    return CombatAction(
        action_type="combat",
        combat_action=combat_action,
        target=target,
        ability_id=ability_id,
        detail="test",
    )


def _move(target: str):
    return MoveAction(action_type="move", target=target, detail="test")


class TestUseItem:
    def test_valid_item_target_passes(self):
        assert validate_ruling_action(
            _combat("use_item", "health_potion"), _combat_briefing()
        ) is None

    def test_player_as_target_flagged(self):
        error = validate_ruling_action(
            _combat("use_item", "player"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid use_item target 'player'" in error
        assert "health_potion (Healing Potion)" in error
        assert '"player"' in error and "never a valid" in error

    def test_unknown_item_flagged(self):
        error = validate_ruling_action(
            _combat("use_item", "invisibility_potion"), _combat_briefing()
        )
        assert error is not None
        assert "invisibility_potion" in error

    def test_empty_usable_items_flagged(self):
        error = validate_ruling_action(
            _combat("use_item", "health_potion"),
            _combat_briefing(usable_items=[]),
        )
        assert error is not None
        assert "no usable items" in error


class TestAttack:
    def test_valid_enemy_target_passes(self):
        assert validate_ruling_action(
            _combat("attack", "goblin"), _combat_briefing()
        ) is None

    def test_party_target_flagged(self):
        error = validate_ruling_action(
            _combat("attack", "korbar"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid attack target 'korbar'" in error
        assert "goblin" in error

    def test_unknown_target_flagged(self):
        error = validate_ruling_action(
            _combat("attack", "bugbear"), _combat_briefing()
        )
        assert error is not None
        assert "bugbear" in error


class TestUseAbility:
    def test_valid_self_ability_passes(self):
        assert validate_ruling_action(
            _combat("use_ability", "player", "second_wind"),
            _combat_briefing(),
        ) is None

    def test_valid_enemy_ability_passes(self):
        assert validate_ruling_action(
            _combat("use_ability", "goblin", "smite"), _combat_briefing()
        ) is None

    def test_valid_ally_ability_passes(self):
        assert validate_ruling_action(
            _combat("use_ability", "korbar", "rally"), _combat_briefing()
        ) is None

    def test_unknown_ability_flagged(self):
        error = validate_ruling_action(
            _combat("use_ability", "goblin", "fireball"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid ability_id 'fireball'" in error
        assert "second_wind" in error and "smite" in error

    def test_empty_abilities_flagged(self):
        error = validate_ruling_action(
            _combat("use_ability", "player", "second_wind"),
            _combat_briefing(abilities=[]),
        )
        assert error is not None
        assert "no abilities" in error

    def test_self_ability_with_enemy_target_flagged(self):
        error = validate_ruling_action(
            _combat("use_ability", "goblin", "second_wind"),
            _combat_briefing(),
        )
        assert error is not None
        assert "second_wind" in error
        assert '"self"' in error and '"player"' in error

    def test_enemy_ability_with_player_target_flagged(self):
        error = validate_ruling_action(
            _combat("use_ability", "player", "smite"), _combat_briefing()
        )
        assert error is not None
        assert "smite" in error and "goblin" in error

    def test_ally_ability_with_enemy_target_flagged(self):
        error = validate_ruling_action(
            _combat("use_ability", "goblin", "rally"), _combat_briefing()
        )
        assert error is not None
        assert "rally" in error and "korbar" in error


class TestMove:
    def test_exit_target_passes(self):
        assert validate_ruling_action(
            _move("exit_north"), _combat_briefing()
        ) is None

    def test_non_exit_target_flagged(self):
        error = validate_ruling_action(
            _move("goblin"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid move target 'goblin'" in error
        assert "FLEEING" in error
        assert "exit_north" in error
        assert "flanking" in error


class TestConservative:
    """Cases where the validator must stay silent (return None)."""

    def test_no_combat_state_anything_passes(self):
        briefing = _peaceful_briefing()
        assert validate_ruling_action(
            _combat("use_item", "player"), briefing
        ) is None
        assert validate_ruling_action(_move("goblin"), briefing) is None

    def test_wait_in_combat_passes(self):
        assert validate_ruling_action(
            WaitAction(action_type="wait", detail="persuade the goblin"),
            _combat_briefing(),
        ) is None
