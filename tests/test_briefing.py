import pytest
from pydantic import ValidationError

from mgmai.models.briefing import (
    BriefingEntity,
    BriefingExit,
    BriefingHistoryEntry,
    BriefingRoom,
    DialogueContext,
    GMBriefing,
    PlayerStateBriefing,
)


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

    def test_missing_turn_raises(self) -> None:
        with pytest.raises(ValidationError):
            BriefingHistoryEntry.model_validate({
                "summary": "x",
                "location_after": "room1",
            })

    def test_missing_summary_raises(self) -> None:
        with pytest.raises(ValidationError):
            BriefingHistoryEntry.model_validate({
                "turn": 1,
                "location_after": "room1",
            })

    def test_missing_location_after_raises(self) -> None:
        with pytest.raises(ValidationError):
            BriefingHistoryEntry.model_validate({
                "turn": 1,
                "summary": "x",
            })


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
            "npc_attitudes": {"korbar": 2},
            "npc_revelations": {
                "korbar": [
                    {"topic_id": "padlock_mechanism", "description": "How to open from inside"},
                ],
            },
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
        assert b.npc_attitudes["korbar"] == 2
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

    def test_missing_player_input_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "setting": "A setting.",
                "tone": "Dark.",
                "turn": 1,
                "current_room": {
                    "id": "room1",
                    "name": "Room 1",
                    "description": "A room.",
                },
                "player_state": {"location": "room1"},
            })

    def test_missing_adventure_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "setting": "A setting.",
                "tone": "Dark.",
                "turn": 1,
                "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
                "player_state": {"location": "room1"},
                "player_input": "Look.",
            })

    def test_missing_setting_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "tone": "Dark.",
                "turn": 1,
                "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
                "player_state": {"location": "room1"},
                "player_input": "Look.",
            })

    def test_missing_tone_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "setting": "A setting.",
                "turn": 1,
                "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
                "player_state": {"location": "room1"},
                "player_input": "Look.",
            })

    def test_missing_turn_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "setting": "A setting.",
                "tone": "Dark.",
                "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
                "player_state": {"location": "room1"},
                "player_input": "Look.",
            })

    def test_missing_current_room_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "setting": "A setting.",
                "tone": "Dark.",
                "turn": 1,
                "player_state": {"location": "room1"},
                "player_input": "Look.",
            })

    def test_missing_player_state_raises(self) -> None:
        with pytest.raises(ValidationError):
            GMBriefing.model_validate({
                "adventure_title": "Test",
                "setting": "A setting.",
                "tone": "Dark.",
                "turn": 1,
                "current_room": {"id": "room1", "name": "Room 1", "description": "A room."},
                "player_input": "Look.",
            })
