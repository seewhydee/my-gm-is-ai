import pytest
from pydantic import ValidationError

from mgmai.models.soft_state import (
    ConversationLogEntry,
    DialogueState,
    NpcRevelation,
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


class TestNpcRevelation:
    def test_basic(self) -> None:
        r = NpcRevelation.model_validate({
            "topic_id": "padlock_mechanism",
            "description": "How the exterior padlock can be opened from inside",
        })
        assert r.topic_id == "padlock_mechanism"
        assert "padlock" in r.description

    def test_missing_topic_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            NpcRevelation.model_validate({"description": "x"})


class TestSoftGameState:
    def test_default(self) -> None:
        s = SoftGameState.model_validate({})
        assert s.soft_inventory == []
        assert s.room_notes == {}
        assert s.entity_notes == {}
        assert s.npc_attitudes == {}
        assert s.npc_revelations == {}
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
            "npc_attitudes": {"korbar": 2},
            "npc_revelations": {
                "korbar": [
                    {"topic_id": "padlock_mechanism", "description": "How to open from inside"},
                ],
            },
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
        assert s.npc_attitudes["korbar"] == 2
        assert len(s.turn_history) == 1
        assert s.dialogue_state.active_npc == "korbar"

    def test_load_sample_soft_state(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "adventures" / "bag-of-holding" / "soft-state.json"
        data = json.loads(path.read_text())
        s = SoftGameState.model_validate(data)
        assert s.soft_inventory == []
        assert s.npc_attitudes.get("korbar") == 0
        assert s.dialogue_state.active_npc is None
        assert s.dialogue_state.stall_counter == 0
