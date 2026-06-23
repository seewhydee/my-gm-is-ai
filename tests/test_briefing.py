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

from mgmai.models.briefing import (
    BriefingContainedEntity,
    BriefingEntity,
    BriefingExit,
    BriefingHistoryEntry,
    BriefingRoom,
    DialogueContext,
    GMBriefing,
    PlayerStateBriefing,
)


class TestBriefingContainedEntity:
    def test_basic(self) -> None:
        c = BriefingContainedEntity.model_validate({
            "id": "toenail_sword",
            "name": "toenail_sword",
            "type": "item",
            "description": "A giant toenail clipping.",
        })
        assert c.id == "toenail_sword"
        assert c.type == "item"
        assert c.description == "A giant toenail clipping."

    def test_default_type_is_item(self) -> None:
        c = BriefingContainedEntity.model_validate({
            "id": "rusty_key",
            "name": "rusty_key",
            "description": "A rusty key.",
        })
        assert c.type == "item"

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            BriefingContainedEntity.model_validate({
                "name": "sword",
                "type": "item",
                "description": "A sword.",
            })


class TestBriefingEntity:
    def test_basic(self) -> None:
        e = BriefingEntity.model_validate({
            "id": "spider",
            "name": "Huge Spider",
            "type": "npc",
            "description": "A huge, hungry spider.",
            "state": {"alive": True, "fled": False},
            "entity_notes": [],
            "soft_items": [],
        })
        assert e.id == "spider"
        assert e.state["alive"] is True
        assert e.contained_entities == []

    def test_with_contained_entities(self) -> None:
        e = BriefingEntity.model_validate({
            "id": "rubbish_pile",
            "name": "rubbish_pile",
            "type": "feature",
            "description": "A pile of rubbish.",
            "contained_entities": [
                {"id": "toenail_sword", "name": "toenail_sword", "type": "item", "description": "A toenail."},
            ],
        })
        assert len(e.contained_entities) == 1
        assert e.contained_entities[0].id == "toenail_sword"

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            BriefingEntity.model_validate({
                "name": "Spider",
                "type": "npc",
                "description": "A spider.",
            })


class TestBriefingExit:
    def test_basic(self) -> None:
        e = BriefingExit.model_validate({
            "id": "exit_through_webs",
            "direction": "Push through the dense webs downward",
            "target_room": "bag_floor",
            "hidden": False,
        })
        assert e.id == "exit_through_webs"
        assert e.target_room == "bag_floor"

    def test_hidden_exit(self) -> None:
        e = BriefingExit.model_validate({
            "id": "secret_passage",
            "direction": "Slip through the crack",
            "target_room": "hidden_vault",
            "hidden": True,
        })
        assert e.hidden is True
        assert e.id == "secret_passage"


class TestBriefingRoom:
    def test_basic(self) -> None:
        r = BriefingRoom.model_validate({
            "id": "axe_handle_lower",
            "name": "Axe Handle (Lower)",
            "description": "You are on the lower section of the axe handle.",
            "soft_items": ["rock", "loose stone"],
            "entities_visible": [
                {
                    "id": "spider",
                    "name": "Huge Spider",
                    "type": "npc",
                    "description": "A huge spider.",
                },
            ],
            "exits_available": [
                {
                    "id": "exit_up",
                    "direction": "Walk up",
                    "target_room": "axe_handle_upper",
                },
            ],
            "interactions_available": [],
            "room_notes": ["Webs partially cleared."],
        })
        assert r.id == "axe_handle_lower"
        assert len(r.entities_visible) == 1
        assert len(r.exits_available) == 1
        assert r.room_notes == ["Webs partially cleared."]

    def test_empty_soft_items_and_room_notes(self) -> None:
        r = BriefingRoom.model_validate({
            "id": "simple_room",
            "name": "Simple Room",
            "description": "A plain room.",
        })
        assert r.soft_items == []
        assert r.room_notes == []
        assert r.entities_visible == []
        assert r.exits_available == []
        assert r.interactions_available == []


class TestPlayerStateBriefing:
    def test_basic(self) -> None:
        p = PlayerStateBriefing.model_validate({
            "location": "axe_handle_lower",
            "hard_inventory": ["iron_sword"],
            "soft_inventory": ["rock"],
            "active_flags": {"injured": False},
            "entity_notes": [],
        })
        assert p.location == "axe_handle_lower"
        assert p.hard_inventory == ["iron_sword"]
        assert p.active_flags["injured"] is False


class TestBriefingHistoryEntry:
    def test_basic(self) -> None:
        h = BriefingHistoryEntry.model_validate({
            "turn": 2,
            "summary": "Player climbed down.",
            "location_after": "axe_handle_lower",
        })
        assert h.turn == 2
        assert h.location_after == "axe_handle_lower"

    @pytest.mark.parametrize("missing_field", ["turn", "summary", "location_after"])
    def test_missing_required_field_raises(self, missing_field) -> None:
        data = {"turn": 1, "summary": "x", "location_after": "room1"}
        del data[missing_field]
        with pytest.raises(ValidationError):
            BriefingHistoryEntry.model_validate(data)


class TestDialogueContext:
    def test_basic(self) -> None:
        from mgmai.models.corpus import DialogueGuidelines

        d = DialogueContext.model_validate({
            "active_npc": {
                "id": "korbar",
                "name": "Korbar the Dwarf",
                "attitude": 2,
                "dialogue_guidelines": {
                    "personality": "Gruff but kind.",
                    "attitude_limits": {"min": -5, "max": 10, "step_per_turn": 3, "initial": 0},
                },
            },
            "recent_exchanges": [
                {"turn": 4, "speaker": "player", "text": "Who are you?"},
            ],
            "topics_discussed": ["origin"],
            "revealed_topics": ["padlock_mechanism"],
        })
        assert d.active_npc.id == "korbar"
        assert d.active_npc.attitude == 2
        assert isinstance(d.active_npc.dialogue_guidelines, DialogueGuidelines)
        assert d.revealed_topics == ["padlock_mechanism"]

    def test_missing_active_npc_raises(self) -> None:
        with pytest.raises(ValidationError):
            DialogueContext.model_validate({
                "recent_exchanges": [],
                "topics_discussed": [],
                "revealed_topics": [],
            })


class TestGMBriefing:
    def test_minimal(self) -> None:
        b = GMBriefing.model_validate({
            "adventure_title": "Test Adventure",
            "setting": "A test setting.",
            "tone": "Whimsical.",
            "turn": 1,
            "current_room": {
                "id": "room1",
                "name": "Room 1",
                "description": "A room.",
            },
            "player_state": {
                "location": "room1",
            },
            "player_input": "Look around.",
        })
        assert b.adventure_title == "Test Adventure"
        assert b.turn == 1
        assert b.dialogue_context is None

    def test_full(self) -> None:
        b = GMBriefing.model_validate({
            "adventure_title": "You're Trapped in a Bag of Holding!",
            "setting": "You are trapped inside a magical Bag of Holding.",
            "tone": "Whimsical and slightly dark.",
            "turn": 3,
            "current_room": {
                "id": "axe_handle_lower",
                "name": "Axe Handle (Lower)",
                "description": "You are on the lower section of the axe handle.",
                "soft_items": ["rock"],
                "entities_visible": [
                    {
                        "id": "spider",
                        "name": "Huge Spider",
                        "type": "npc",
                        "description": "A huge spider.",
                        "state": {"alive": True},
                    },
                ],
                "exits_available": [
                    {
                        "id": "exit_drop",
                        "direction": "Drop down",
                        "target_room": "bag_floor",
                    },
                ],
                "room_notes": [],
            },
            "player_state": {
                "location": "axe_handle_lower",
                "hard_inventory": ["iron_sword"],
                "soft_inventory": ["rock"],
                "active_flags": {"injured": False},
            },
            "player_knowledge_topics": [],
            "recent_history": [
                {
                    "turn": 2,
                    "summary": "Player climbed down.",
                    "location_after": "axe_handle_lower",
                },
            ],
            "player_input": "I look at the spider.",
        })
        assert b.current_room.id == "axe_handle_lower"
        assert len(b.recent_history) == 1
        assert b.dialogue_context is None

    def test_with_dialogue_context(self) -> None:
        b = GMBriefing.model_validate({
            "adventure_title": "Test",
            "setting": "A setting.",
            "tone": "Dark.",
            "turn": 5,
            "current_room": {
                "id": "bag_floor",
                "name": "Bag Floor",
                "description": "The floor of the bag.",
            },
            "player_state": {"location": "bag_floor"},
            "dialogue_context": {
                "active_npc": {
                    "id": "korbar",
                    "name": "Korbar",
                    "attitude": 2,
                    "dialogue_guidelines": {
                        "personality": "Gruff.",
                        "attitude_limits": {"min": -5, "max": 10, "step_per_turn": 3, "initial": 0},
                    },
                },
                "recent_exchanges": [
                    {"turn": 4, "speaker": "player", "text": "Hello?"},
                ],
                "topics_discussed": ["greeting"],
                "revealed_topics": [],
            },
            "player_input": "Who are you?",
        })
        assert b.dialogue_context is not None
        assert b.dialogue_context.active_npc.id == "korbar"
        assert b.dialogue_context.topics_discussed == ["greeting"]

    @pytest.mark.parametrize("missing_field", [
        "player_input", "adventure_title", "setting", "tone",
        "turn", "current_room", "player_state",
    ])
    def test_missing_required_field_raises(self, missing_field) -> None:
        data = {
            "adventure_title": "Test",
            "setting": "A setting.",
            "tone": "Dark.",
            "turn": 1,
            "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
            "player_state": {"location": "room1"},
            "player_input": "Look.",
        }
        del data[missing_field]
        with pytest.raises(ValidationError):
            GMBriefing.model_validate(data)


class TestPlayerStatEntry:
    def test_basic(self) -> None:
        from mgmai.models.briefing import PlayerStatEntry
        e = PlayerStatEntry.model_validate({"value": 14, "modifier": 2})
        assert e.value == 14
        assert e.modifier == 2

    def test_negative_modifier(self) -> None:
        from mgmai.models.briefing import PlayerStatEntry
        e = PlayerStatEntry.model_validate({"value": 8, "modifier": -1})
        assert e.modifier == -1


class TestGMBriefingPlayerStats:
    def test_includes_player_stats_when_present(self) -> None:
        b = GMBriefing.model_validate({
            "adventure_title": "Test",
            "setting": "A setting.",
            "tone": "Test tone.",
            "turn": 1,
            "current_room": {
                "id": "room1",
                "name": "Room 1",
                "description": "A test room.",
            },
            "player_state": {
                "location": "room1",
                "player_stats": {
                    "STR": {"value": 14, "modifier": 2},
                    "DEX": {"value": 12, "modifier": 1},
                },
            },
            "player_input": "Hello.",
        })
        assert b.player_state.player_stats is not None
        assert b.player_state.player_stats["STR"].value == 14
        assert b.player_state.player_stats["STR"].modifier == 2

    def test_player_stats_none_when_absent(self) -> None:
        b = GMBriefing.model_validate({
            "adventure_title": "Test",
            "setting": "A setting.",
            "tone": "Test tone.",
            "turn": 1,
            "current_room": {
                "id": "room1",
                "name": "Room 1",
                "description": "A test room.",
            },
            "player_state": {"location": "room1"},
            "player_input": "Hello.",
        })
        assert b.player_state.player_stats is None
