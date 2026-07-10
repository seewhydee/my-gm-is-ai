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

import pytest
from pydantic import ValidationError

from mgmai.models.hard_state import GameOverState, HardGameState, PlayerState


class TestPlayerState:
    def test_basic(self) -> None:
        p = PlayerState.model_validate({
            "location": "axe_head",
            "inventory": {"iron_sword": 1},
        })
        assert p.location == "axe_head"
        assert p.inventory == {"iron_sword": 1}

    def test_empty_inventory(self) -> None:
        p = PlayerState.model_validate({"location": "room1"})
        assert p.inventory == {}

    def test_missing_location_raises(self) -> None:
        with pytest.raises(ValidationError):
            PlayerState.model_validate({"inventory": {}})


class TestGameOverState:
    def test_win(self) -> None:
        g = GameOverState.model_validate({
            "type": "win",
            "trigger": "escape_bag",
        })
        assert g.type == "win"
        assert g.trigger == "escape_bag"

    def test_lose(self) -> None:
        g = GameOverState.model_validate({
            "type": "lose",
            "trigger": "death_spider",
        })
        assert g.type == "lose"
        assert g.trigger == "death_spider"

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            GameOverState.model_validate({"trigger": "x"})

    def test_missing_trigger_raises(self) -> None:
        with pytest.raises(ValidationError):
            GameOverState.model_validate({"type": "win"})


class TestHardGameState:
    def test_minimal(self) -> None:
        h = HardGameState.model_validate({
            "player": {"location": "axe_head"},
        })
        assert h.player.location == "axe_head"
        assert h.flags == {}
        assert h.room_states == {}
        assert h.entity_states == {}
        assert h.turn_count == 0
        assert h.game_over is None

    def test_full(self) -> None:
        h = HardGameState.model_validate({
            "player": {
                "location": "bag_floor",
                "inventory": {"rusty_key": 1},
            },
            "flags": {
                "injured": False,
                "spider_fled": True,
            },
            "room_states": {
                "axe_head": {"visited": True},
                "bag_floor": {"visited": True},
            },
            "entity_states": {
                "spider": {"alive": True, "wounded": True},
                "korbar": {"alive": True, "told_secret": False},
            },
            "turn_count": 5,
            "game_over": None,
        })
        assert h.player.inventory == {"rusty_key": 1}
        assert h.flags["spider_fled"] is True
        assert h.room_states["axe_head"]["visited"] is True
        assert h.entity_states["spider"]["wounded"] is True
        assert h.turn_count == 5
        assert h.game_over is None

    def test_with_game_over(self) -> None:
        h = HardGameState.model_validate({
            "player": {"location": "axe_head"},
            "game_over": {"type": "lose", "trigger": "death_spider"},
        })
        assert h.game_over is not None
        assert h.game_over.type == "lose"
        assert h.game_over.trigger == "death_spider"

    def test_negative_turn_count_raises(self) -> None:
        with pytest.raises(ValidationError):
            HardGameState.model_validate({
                "player": {"location": "room1"},
                "turn_count": -1,
            })

    def test_load_sample_hard_state(self, sample_corpus: object) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fixtures" / "hard-state.json"
        data = json.loads(path.read_text())
        h = HardGameState.model_validate(data)
        assert h.player.location == "axe_head"
        assert h.turn_count == 0
        assert h.game_over is None
        assert "stuck_fly" in h.entity_states
        assert h.entity_states["stuck_fly"]["alive"] is True
        assert "spider" in h.entity_states
        assert h.entity_states["spider"]["alive"] is True


class TestPlayerStats:
    def test_no_stats(self) -> None:
        p = PlayerState.model_validate({"location": "room1"})
        assert p.stats is None

    def test_with_stats(self) -> None:
        p = PlayerState.model_validate({
            "location": "room1",
            "stats": {"STR": 14, "DEX": 12},
        })
        assert p.stats == {"STR": 14, "DEX": 12}

    def test_empty_dict(self) -> None:
        p = PlayerState.model_validate({
            "location": "room1",
            "stats": {},
        })
        assert p.stats == {}
