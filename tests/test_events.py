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

"""Tests for the condition.* event family: context keys and dispatch
timing relative to turn.end and combat.ended.

Recording reactions gate on ``event:`` context keys (so a missing or
misnamed key silently fails the condition) and append marker narratives
to ``triggered_narration`` in dispatch order.
"""

import random

from mgmai.engine.engine import resolve
from mgmai.engine.event_bus import reset_disabled_once
from mgmai.models.actions import CombatAction, InteractAction, WaitAction
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from tests.helpers import build_state_manager


# ------------------------------------------------------------------
# Persistent-condition fixtures: a slime whose touch applies a
# persistent burn that ticks (and damages) on turn.end.
# ------------------------------------------------------------------


def _recorder_reactions() -> list[dict]:
    return [
        {
            "id": "rec_applied",
            "on": "status_effect.applied",
            "condition": {"all": [
                {"require": "event:target_id == player"},
                {"require": "event:status_effect_id == slime_burn"},
                {"require": "event:rounds == 2"},
                {"require": "event:source == result"},
            ]},
            "effect": {"result": {"narrative": "EVENT applied"}},
        },
        {
            "id": "rec_ticked",
            "on": "status_effect.ticked",
            "condition": {"all": [
                {"require": "event:target_id == player"},
                {"require": "event:status_effect_id == slime_burn"},
                {"require": "event:expired == false"},
            ]},
            "effect": {"result": {"narrative": "EVENT ticked"}},
        },
        {
            "id": "rec_cleared",
            "on": "status_effect.cleared",
            "condition": {"all": [
                {"require": "event:target_id == player"},
                {"require": "event:status_effect_id == slime_burn"},
                {"require": "event:reason == expired"},
            ]},
            "effect": {"result": {"narrative": "EVENT cleared"}},
        },
        {
            "id": "rec_turn_end",
            "on": "turn.end",
            "effect": {"result": {"narrative": "EVENT turn.end"}},
        },
    ]


def _persistent_corpus() -> ModuleCorpus:
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Condition Events", "introduction": "Test."},
        "rooms": {
            "start": {
                "name": "Start Room",
                "description": "A room.",
                "contains": ["slime"],
                "is_start_room": True,
            },
        },
        "entities": {
            "slime": {
                "type": "feature",
                "description": "A glistening slime mold.",
                "interactions": [{
                    "id": "touch",
                    "description": "Touch the slime.",
                    "result": {
                        "narrative": "It burns!",
                        "apply_status_effect": {"id": "slime_burn", "rounds": 2},
                    },
                }],
            },
        },
        "status_effects": {
            "slime_burn": {
                "scope": "persistent",
                "duration": "rounds",
                "tick_effect": {"player_damage": "1"},
            },
        },
        "mechanics": {
            "recorder": {"reactions": _recorder_reactions()},
        },
    })


def _hard(**overrides) -> HardGameState:
    data = {
        "player": {"location": "start", "inventory": {}, "current_hp": 10, "max_hp": 10},
        "flags": {},
        "room_states": {"start": {"visited": True}},
        "entity_states": {},
        "turn_count": 0,
        "game_over": None,
    }
    data.update(overrides)
    return HardGameState.model_validate(data)


def _sm(corpus, hard):
    reset_disabled_once()
    return build_state_manager(corpus, hard_state=hard)


def _touch() -> InteractAction:
    return InteractAction(
        action_type="interact", target="slime",
        interaction_id="touch", detail="Touch the slime.",
    )


def _markers(result) -> list[str]:
    return [n for n in (result.triggered_narration or []) if n.startswith("EVENT")]


class TestPersistentConditionEvents:
    def test_applied_event_context_keys(self):
        """status_effect.applied carries target_id, status_effect_id, rounds, source."""
        sm = _sm(_persistent_corpus(), _hard())
        result = resolve(_touch(), sm)
        assert "EVENT applied" in _markers(result)

    def test_ticked_event_context_keys_and_turn_end_timing(self):
        """status_effect.ticked carries remaining_rounds/expired and is
        dispatched before turn.end of the same turn."""
        sm = _sm(_persistent_corpus(), _hard())
        result = resolve(_touch(), sm)
        markers = _markers(result)
        assert "EVENT ticked" in markers
        assert "EVENT turn.end" in markers
        assert markers.index("EVENT ticked") < markers.index("EVENT turn.end")

    def test_cleared_event_on_expiry(self):
        """status_effect.cleared fires with reason 'expired' on the final tick."""
        sm = _sm(_persistent_corpus(), _hard())
        resolve(_touch(), sm)
        result = resolve(WaitAction(action_type="wait", detail="wait"), sm)
        markers = _markers(result)
        assert "EVENT cleared" in markers
        assert sm.hard_state.player.status_effects == {}


# ------------------------------------------------------------------
# Combat-end fixtures: status_effect.cleared (reason combat_end) must
# dispatch before combat.ended.
# ------------------------------------------------------------------


def _combat_corpus() -> ModuleCorpus:
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Combat Events", "introduction": "Test."},
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
        "mechanics": {
            "recorder": {
                "reactions": [
                    {
                        "id": "rec_cleared",
                        "on": "status_effect.cleared",
                        "condition": {"all": [
                            {"require": "event:target_id == player"},
                            {"require": "event:status_effect_id == poisoned"},
                            {"require": "event:reason == combat_end"},
                        ]},
                        "effect": {"result": {"narrative": "EVENT cleared"}},
                    },
                    {
                        "id": "rec_combat_ended",
                        "on": "combat.ended",
                        "effect": {"result": {"narrative": "EVENT combat.ended"}},
                    },
                ],
            },
        },
        "stats": {
            "definitions": {
                "STR": {"name": "Strength"},
                "DEX": {"name": "Dexterity"},
                "CON": {"name": "Constitution"},
                "INT": {"name": "Intelligence"},
                "WIS": {"name": "Wisdom"},
                "CHA": {"name": "Charisma"},
            },
            "system": "5e",
        },
    })


def _combat_hard() -> HardGameState:
    return _hard(
        player={
            "location": "room1",
            "inventory": {},
            "stats": {
                "STR": 16, "DEX": 14, "CON": 12,
                "INT": 10, "WIS": 8, "CHA": 10,
            },
            "level": 1,
            "current_hp": 10,
            "max_hp": 10,
            "ac": 14,
            "proficiency_bonus": 2,
            "status_effects": {"poisoned": 9},
        },
        entity_states={
            "goblin": {
                "alive": True, "current_hp": 7,
                # Advantage against the stunned goblin cancels the player's
                # poisoned disadvantage, so a single attack roll is used.
                "status_effects": {"stunned": 9},
            },
        },
        combat={
            "active": True,
            "combatants": ["player", "goblin"],
            "initiative_order": ["player", "goblin"],
            "current_index": 0,
            "round_number": 1,
        },
    )


class TestCombatEndConditionEvents:
    def test_cleared_precedes_combat_ended(self, monkeypatch):
        """status_effect.cleared (reason combat_end) is dispatched before
        combat.ended when the last enemy dies."""
        sm = _sm(_combat_corpus(), _combat_hard())
        # player crits: 2*(1d6)+3 = 15 -> goblin dead -> combat ends
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Swing!",
        )
        result = resolve(action, sm)
        markers = _markers(result)
        assert "EVENT cleared" in markers
        assert "EVENT combat.ended" in markers
        assert markers.index("EVENT cleared") < markers.index("EVENT combat.ended")
        assert sm.hard_state.player.status_effects == {}
