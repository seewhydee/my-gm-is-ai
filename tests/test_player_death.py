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

"""Tests for unified player-death handling: the ``player.died`` event and
rescue reactions.

Dropping to 0 HP from any source (combat, traps, falls) fires the
``player.died`` reaction trigger; corpus reactions may avert the death by
restoring HP above 0 (alongside other effects).  If the player is still
at 0 HP after the dispatch, the game ends (lose / player_death).
"""

import random

from mgmai.engine.engine import resolve
from mgmai.engine.event_bus import reset_disabled_once
from mgmai.models.actions import CombatAction, WaitAction
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from tests.helpers import build_state_manager


# ------------------------------------------------------------------
# Out-of-combat fixtures: a lethal turn.end trap, plus an optional
# life-ward rescue mechanic.
# ------------------------------------------------------------------


def _trap_corpus(*, rescue: bool = False, rescue_heals: bool = True) -> ModuleCorpus:
    """A two-room corpus with a lethal turn.end trap in ``start``.

    With ``rescue``, a reaction mechanic on ``player.died`` fires once:
    it teleports the player to ``safe`` and, when ``rescue_heals``,
    restores 10 HP.
    """
    rescue_result = {
        "narrative": "Your ward flares and pulls you to safety.",
        "set_player_location": "safe",
    }
    if rescue_heals:
        rescue_result["player_heal"] = "10"
    mechanics = {}
    if rescue:
        mechanics = {
            "life_ward": {
                "reactions": [
                    {
                        "id": "life_ward_fires",
                        "on": "player.died",
                        "once": True,
                        "effect": {"result": rescue_result},
                    }
                ]
            }
        }
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Death Test", "introduction": "Test."},
        "rooms": {
            "start": {
                "name": "Trap Room",
                "description": "A trapped room.",
                "reactions": [
                    {
                        "id": "trap_damage",
                        "on": "turn.end",
                        "effect": {"result": {"player_damage": "8"}},
                    }
                ],
            },
            "safe": {"name": "Safe Room", "description": "Safe."},
        },
        "entities": {},
        "mechanics": mechanics,
    })


def _hard_state(hp: int = 5, location: str = "start") -> HardGameState:
    return HardGameState.model_validate({
        "player": {
            "location": location,
            "inventory": {},
            "stats": {
                "STR": 10, "DEX": 10, "CON": 10,
                "INT": 10, "WIS": 10, "CHA": 10,
            },
            "level": 1,
            "current_hp": hp,
            "max_hp": 10,
            "ac": 10,
            "proficiency_bonus": 2,
        },
        "flags": {},
        "room_states": {},
        "entity_states": {},
        "turn_count": 0,
        "game_over": None,
    })


def _sm(corpus, hard):
    reset_disabled_once()
    return build_state_manager(corpus, hard_state=hard)


class TestOutOfCombatDeath:
    def test_lethal_out_of_combat_damage_ends_game(self):
        """HP <= 0 from a trap (no combat) triggers game over via the
        player.died poll, with no corpus-authored game-over entry."""
        sm = _sm(_trap_corpus(), _hard_state(hp=5))
        result = resolve(
            WaitAction(action_type="wait", detail="wait"), sm
        )
        assert result.game_over is not None
        assert result.game_over.type == "lose"
        assert result.game_over.trigger == "player_death"

    def test_rescue_heals_and_teleports(self):
        """A player.died reaction that restores HP above 0 averts the
        game-over; its other effects (teleport) still apply."""
        sm = _sm(_trap_corpus(rescue=True), _hard_state(hp=5))
        result = resolve(
            WaitAction(action_type="wait", detail="wait"), sm
        )
        assert result.game_over is None
        # 5 - 8 = -3, then the ward heals 10 -> 7.
        assert sm.hard_state.player.current_hp == 7
        assert sm.hard_state.player.location == "safe"

    def test_rescue_without_healing_still_dies(self):
        """A player.died reaction that fires but leaves HP at <= 0 does
        not avert the game-over (its effects still apply)."""
        sm = _sm(
            _trap_corpus(rescue=True, rescue_heals=False),
            _hard_state(hp=5),
        )
        result = resolve(
            WaitAction(action_type="wait", detail="wait"), sm
        )
        assert result.game_over is not None
        assert result.game_over.type == "lose"
        assert sm.hard_state.player.location == "safe"


# ------------------------------------------------------------------
# Combat fixtures: one goblin, player already in combat, plus an
# optional life-ward rescue mechanic.
# ------------------------------------------------------------------


def _combat_corpus(*, rescue: bool = False) -> ModuleCorpus:
    mechanics = {}
    if rescue:
        mechanics = {
            "life_ward": {
                "reactions": [
                    {
                        "id": "life_ward_fires",
                        "on": "player.died",
                        "once": True,
                        "effect": {"result": {
                            "narrative": "Your ward flares.",
                            "player_heal": "10",
                        }},
                    }
                ]
            }
        }
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Combat Death Test", "introduction": "Test."},
        "rooms": {
            "room1": {
                "name": "Test Room",
                "description": "A test room.",
                "contains": ["goblin"],
            },
        },
        "entities": {
            "goblin": {
                "type": "npc",
                "description": "A scrawny goblin.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Is alive"},
                    "current_hp": {"type": "number", "description": "Current HP"},
                },
                "combat": {
                    "hp": 7, "ac": 12, "atk": 4, "dmg": "1d6+2",
                    "initiative_mod": 2, "flee_dc": 10,
                },
            },
        },
        "mechanics": mechanics,
    })


def _combat_hard(hp: int = 3) -> HardGameState:
    return HardGameState.model_validate({
        "player": {
            "location": "room1",
            "inventory": {},
            "stats": {
                "STR": 16, "DEX": 14, "CON": 12,
                "INT": 10, "WIS": 8, "CHA": 10,
            },
            "level": 1,
            "current_hp": hp,
            "max_hp": 10,
            "ac": 14,
            "proficiency_bonus": 2,
        },
        "flags": {},
        "room_states": {},
        "entity_states": {"goblin": {"alive": True, "current_hp": 7}},
        "turn_count": 0,
        "game_over": None,
        "combat": {
            "active": True,
            "combatants": ["player", "goblin"],
            "initiative_order": ["player", "goblin"],
            "current_index": 0,
            "round_number": 1,
        },
    })


class TestCombatDeath:
    def test_combat_death_ends_game(self, monkeypatch):
        """Combat death without a rescue ends the game via the
        player.died poll (previously set directly by the engine)."""
        sm = _sm(_combat_corpus(), _combat_hard(hp=3))
        # player misses (1); goblin hits (15+4 vs AC 14) for 6+2=8 -> -5 HP
        rand_vals = iter([1, 15, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Swing!",
        )
        result = resolve(action, sm)
        assert result.game_over is not None
        assert result.game_over.type == "lose"
        assert result.game_over.trigger == "player_death"
        assert sm.hard_state.combat is None

    def test_combat_death_rescued(self, monkeypatch):
        """A player.died rescue during combat averts the game-over;
        combat still ends the moment the player dropped."""
        sm = _sm(_combat_corpus(rescue=True), _combat_hard(hp=3))
        rand_vals = iter([1, 15, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Swing!",
        )
        result = resolve(action, sm)
        assert result.game_over is None
        # 3 - 8 = -5, then the ward heals 10 -> 5.
        assert sm.hard_state.player.current_hp == 5
        assert sm.hard_state.combat is None
