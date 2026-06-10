import pytest
from pydantic import ValidationError

from mgmai.models.soft_state import (
    ConversationLogEntry,
    DialogueState,
    KnowledgeEntry,
    SoftGameState,
    SoftStatePatch,
    TurnHistoryEntry,
)


class TestSoftStatePatch:
    def test_room_note(self) -> None:
        p = SoftStatePatch.model_validate({
            "entity_id": None,
            "field": "room_note",
            "target_id": "axe_handle_lower",
            "old_value": None,
            "new_value": "The webs here are partially cleared.",
            "reason": "Player hacked through the webs with the iron sword.",
        })
        assert p.field == "room_note"
        assert p.target_id == "axe_handle_lower"
        assert p.entity_id is None

    def test_entity_note(self) -> None:
        p = SoftStatePatch.model_validate({
            "entity_id": "spider",
            "field": "entity_note",
            "target_id": None,
            "old_value": None,
            "new_value": "The spider's left legs are covered in ichor.",
            "reason": "Player wounded the spider with the toenail sword.",
        })
        assert p.entity_id == "spider"
        assert p.field == "entity_note"

    def test_soft_inventory_add(self) -> None:
        p = SoftStatePatch.model_validate({
            "field": "soft_inventory_add",
            "new_value": "rock",
            "reason": "Player picks up a rock from the floor.",
        })
        assert p.field == "soft_inventory_add"
        assert p.new_value == "rock"

    def test_soft_inventory_remove(self) -> None:
        p = SoftStatePatch.model_validate({
            "field": "soft_inventory_remove",
            "new_value": "rock",
            "reason": "Player throws the rock away.",
        })
        assert p.field == "soft_inventory_remove"
        assert p.new_value == "rock"

    def test_invalid_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "field": "invalid_field",
                "new_value": "x",
                "reason": "y",
            })

    def test_with_old_value(self) -> None:
        p = SoftStatePatch.model_validate({
            "field": "room_note",
            "target_id": "room1",
            "old_value": "The room is messy.",
            "new_value": "The room is tidy.",
            "reason": "Player cleaned the room.",
        })
        assert p.old_value == "The room is messy."
        assert p.new_value == "The room is tidy."

    def test_missing_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "new_value": "x",
                "reason": "y",
            })

    def test_missing_new_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "field": "room_note",
                "reason": "y",
            })

    def test_missing_reason_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "field": "room_note",
                "new_value": "x",
            })

    def test_room_note_with_entity_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "entity_id": "spider",
                "field": "room_note",
                "target_id": "axe_handle_lower",
                "new_value": "The webs are cleared.",
                "reason": "Player cleared webs.",
            })

    def test_room_note_missing_target_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "field": "room_note",
                "new_value": "Cleared webs.",
                "reason": "Player cleared webs.",
            })

    def test_entity_note_with_target_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "entity_id": "spider",
                "field": "entity_note",
                "target_id": "axe_handle_lower",
                "new_value": "The spider is wounded.",
                "reason": "Player attacked.",
            })

    def test_entity_note_missing_entity_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch.model_validate({
                "field": "entity_note",
                "new_value": "Wounded.",
                "reason": "Player attacked.",
            })


class TestConversationLogEntry:
    def test_basic(self) -> None:
        e = ConversationLogEntry.model_validate({
            "turn": 4,
            "speaker": "korbar",
            "text": "Arr, name's Korbar.",
        })
        assert e.turn == 4
        assert e.speaker == "korbar"
        assert e.text == "Arr, name's Korbar."

    def test_missing_turn_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConversationLogEntry.model_validate({"speaker": "player", "text": "hi"})


class TestDialogueState:
    def test_default(self) -> None:
        d = DialogueState.model_validate({})
        assert d.active_npc is None
        assert d.conversation_log == []
        assert d.topics_discussed == []
        assert d.entered_turn == 0
        assert d.stall_counter == 0

    def test_active(self) -> None:
        d = DialogueState.model_validate({
            "active_npc": "korbar",
            "conversation_log": [
                {"turn": 4, "speaker": "player", "text": "Who are you?"},
                {"turn": 4, "speaker": "korbar", "text": "Arr, name's Korbar."},
            ],
            "topics_discussed": ["origin"],
            "entered_turn": 4,
            "stall_counter": 1,
        })
        assert d.active_npc == "korbar"
        assert len(d.conversation_log) == 2
        assert d.stall_counter == 1


class TestTurnHistoryEntry:
    def test_basic(self) -> None:
        e = TurnHistoryEntry.model_validate({
            "turn": 3,
            "player_input": "I push through the webs.",
            "ruled_action": {"action_type": "move", "target": "exit_through_webs"},
            "engine_result_summary": "Player moved to bag_floor.",
            "flags_changed": ["spider_fled"],
            "location_after": "bag_floor",
        })
        assert e.turn == 3
        assert e.location_after == "bag_floor"
        assert e.flags_changed == ["spider_fled"]

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValidationError):
            TurnHistoryEntry.model_validate({
                "turn": 1,
                "player_input": "hi",
            })

    def test_ooc_discussion_action_type(self) -> None:
        e = TurnHistoryEntry.model_validate({
            "turn": 5,
            "player_input": "Is the spider still there?",
            "ruled_action": {"action_type": "ooc_discussion", "detail": "Clarification question."},
            "engine_result_summary": "GM clarified spider status.",
            "flags_changed": [],
            "location_after": "axe_handle_lower",
        })
        assert e.ruled_action["action_type"] == "ooc_discussion"
        assert e.flags_changed == []

    def test_empty_flags_changed(self) -> None:
        e = TurnHistoryEntry.model_validate({
            "turn": 2,
            "player_input": "Look around.",
            "ruled_action": {"action_type": "examine", "target": "room"},
            "engine_result_summary": "Player examined the room.",
            "flags_changed": [],
            "location_after": "axe_head",
        })
        assert e.flags_changed == []


class TestKnowledgeEntry:
    def test_basic(self) -> None:
        r = KnowledgeEntry.model_validate({
            "topic_id": "padlock_mechanism",
            "description": "How the exterior padlock can be opened from inside",
            "source_type": "npc_dialogue",
            "source_id": "korbar",
            "turn_learned": 3,
        })
        assert r.topic_id == "padlock_mechanism"
        assert r.source_type == "npc_dialogue"
        assert r.source_id == "korbar"
        assert r.turn_learned == 3

    def test_missing_topic_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeEntry.model_validate({
                "description": "x",
                "source_type": "npc_dialogue",
                "turn_learned": 1,
            })

    def test_source_id_optional(self) -> None:
        r = KnowledgeEntry.model_validate({
            "topic_id": "some_fact",
            "description": "A fact learned through interaction",
            "source_type": "interaction",
            "turn_learned": 5,
        })
        assert r.source_id is None


class TestSoftGameState:
    def test_default(self) -> None:
        s = SoftGameState.model_validate({})
        assert s.soft_inventory == []
        assert s.room_notes == {}
        assert s.entity_notes == {}
        assert s.player_knowledge == []
        assert s.turn_history == []
        assert s.dialogue_state.active_npc is None

    def test_full(self) -> None:
        s = SoftGameState.model_validate({
            "soft_inventory": ["rock"],
            "room_notes": {
                "axe_handle_lower": ["Webs partially cleared."],
            },
            "entity_notes": {
                "spider": ["Left legs covered in ichor."],
            },
            "player_knowledge": [
                {
                    "topic_id": "padlock_mechanism",
                    "description": "How to open from inside",
                    "source_type": "npc_dialogue",
                    "source_id": "korbar",
                    "turn_learned": 4,
                },
            ],
            "turn_history": [
                {
                    "turn": 1,
                    "player_input": "Look around.",
                    "ruled_action": {"action_type": "examine", "target": "axe_head"},
                    "engine_result_summary": "Player examined the room.",
                    "flags_changed": [],
                    "location_after": "axe_head",
                },
            ],
            "dialogue_state": {
                "active_npc": "korbar",
                "conversation_log": [
                    {"turn": 2, "speaker": "player", "text": "Hello?"},
                ],
                "topics_discussed": ["greeting"],
                "entered_turn": 2,
                "stall_counter": 0,
            },
        })
        assert s.soft_inventory == ["rock"]
        assert len(s.turn_history) == 1
        assert s.dialogue_state.active_npc == "korbar"

    def test_surfaced_soft_items_default(self) -> None:
        s = SoftGameState.model_validate({})
        assert s.surfaced_soft_items == {}

    def test_surfaced_soft_items_populated(self) -> None:
        s = SoftGameState.model_validate({
            "surfaced_soft_items": {
                "axe_head": ["loose stone"],
                "rubbish_pile": ["cork", "lint"],
            },
        })
        assert s.surfaced_soft_items["axe_head"] == ["loose stone"]
        assert s.surfaced_soft_items["rubbish_pile"] == ["cork", "lint"]

    def test_load_sample_soft_state(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fixtures" / "soft-state.json"
        data = json.loads(path.read_text())
        s = SoftGameState.model_validate(data)
        assert s.soft_inventory == []
        assert s.dialogue_state.active_npc is None
        assert s.dialogue_state.stall_counter == 0
