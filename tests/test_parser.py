from __future__ import annotations

import json

import pytest

from mgmai.llm.parser import (
    LLMOutputError,
    parse_player_action,
    parse_prose_output,
)
from mgmai.models.actions import (
    ExamineAction,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    TalkAction,
    TransferAction,
    WaitAction,
)
from mgmai.models.narration import NarrationOutput


# ------------------------------------------------------------------
# parse_player_action
# ------------------------------------------------------------------

class TestParsePlayerAction:
    def test_move_action(self) -> None:
        raw = json.dumps({
            "action_type": "move",
            "target": "exit_north",
            "detail": "Player heads north",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, MoveAction)
        assert action.target == "exit_north"

    def test_move_with_style(self) -> None:
        raw = json.dumps({
            "action_type": "move",
            "target": "exit_north",
            "detail": "Crawling through the tunnel",
            "follow_up": None,
            "style": "crawling",
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, MoveAction)
        assert action.style == "crawling"

    def test_examine_action(self) -> None:
        raw = json.dumps({
            "action_type": "examine",
            "target": "rusty_key",
            "detail": "Inspecting the key",
            "rigorous": True,
            "using": None,
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, ExamineAction)
        assert action.rigorous is True

    def test_interact_action(self) -> None:
        raw = json.dumps({
            "action_type": "interact",
            "target": "spider",
            "interaction_id": "attack",
            "using": "sword",
            "detail": "Attack the spider",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, InteractAction)
        assert action.interaction_id == "attack"

    def test_talk_action(self) -> None:
        raw = json.dumps({
            "action_type": "talk",
            "target": "korbar",
            "utterance": "Hello there!",
            "ends_dialogue": False,
            "detail": "Greeting Korbar",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, TalkAction)
        assert action.utterance == "Hello there!"

    def test_transfer_action(self) -> None:
        raw = json.dumps({
            "action_type": "transfer",
            "target": "korbar",
            "given_items": ["rusty_key"],
            "taken_items": None,
            "detail": "Give key to Korbar",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, TransferAction)
        assert action.given_items == ["rusty_key"]

    def test_wait_action(self) -> None:
        raw = json.dumps({
            "action_type": "wait",
            "detail": "Looking around",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, WaitAction)

    def test_ooc_discussion_action(self) -> None:
        raw = json.dumps({
            "action_type": "ooc_discussion",
            "detail": "What room am I in?",
            "follow_up": None,
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert isinstance(action, OocDiscussionAction)

    def test_invalid_json(self) -> None:
        with pytest.raises(LLMOutputError, match="Invalid JSON"):
            parse_player_action("not json")

    def test_not_a_dict(self) -> None:
        with pytest.raises(LLMOutputError, match="JSON object"):
            parse_player_action("[1, 2, 3]")

    def test_missing_action_type(self) -> None:
        with pytest.raises(LLMOutputError, match="missing required field"):
            parse_player_action('{"detail": "test"}')

    def test_unknown_action_type(self) -> None:
        with pytest.raises(LLMOutputError, match="validation failed"):
            parse_player_action(json.dumps({
                "action_type": "dance",
                "detail": "dancing",
                "follow_up": None,
                "proposed_soft_state_patches": [],
            }))

    def test_follow_up_chain(self) -> None:
        raw = json.dumps({
            "action_type": "transfer",
            "target": "axe_head",
            "taken_items": ["rusty_key"],
            "detail": "Pick up key",
            "follow_up": "unlock the door with the rusty key",
            "proposed_soft_state_patches": [],
        })
        action = parse_player_action(raw)
        assert action.follow_up == "unlock the door with the rusty key"

    def test_with_soft_patches(self) -> None:
        raw = json.dumps({
            "action_type": "wait",
            "detail": "Pick up a rock",
            "follow_up": None,
            "proposed_soft_state_patches": [
                {
                    "field": "soft_inventory_add",
                    "new_value": "rock",
                    "reason": "Player picked up loose rock from cavern floor",
                }
            ],
        })
        action = parse_player_action(raw)
        assert isinstance(action, WaitAction)
        assert len(action.proposed_soft_state_patches) == 1

    def test_empty_object_rejected(self) -> None:
        with pytest.raises(LLMOutputError):
            parse_player_action("{}")


# ------------------------------------------------------------------
# parse_prose_output
# ------------------------------------------------------------------

class TestParseProseOutput:
    def test_basic_narration(self) -> None:
        raw = json.dumps({
            "narration": "You step through the doorway into a dusty chamber.",
            "npc_response": None,
            "knowledge_tags": None,
            "attitude_changes": None,
        })
        output = parse_prose_output(raw)
        assert isinstance(output, NarrationOutput)
        assert output.narration == "You step through the doorway into a dusty chamber."
        assert output.npc_response is None
        assert output.knowledge_tags is None
        assert output.attitude_changes is None

    def test_with_npc_response(self) -> None:
        raw = json.dumps({
            "narration": "Korbar looks at you.",
            "npc_response": "Hello, stranger.",
            "knowledge_tags": None,
            "attitude_changes": None,
        })
        output = parse_prose_output(raw)
        assert output.npc_response == "Hello, stranger."

    def test_with_knowledge_tags(self) -> None:
        raw = json.dumps({
            "narration": "Korbar reveals the secret.",
            "npc_response": "The lich is weak to sunlight.",
            "knowledge_tags": {"npc_revealed": {"korbar": ["lich_weakness"]}},
            "attitude_changes": None,
        })
        output = parse_prose_output(raw)
        assert output.knowledge_tags is not None
        assert output.knowledge_tags.npc_revealed == {"korbar": ["lich_weakness"]}

    def test_with_attitude_changes(self) -> None:
        raw = json.dumps({
            "narration": "Korbar appreciates the gift.",
            "npc_response": "Thank you.",
            "knowledge_tags": None,
            "attitude_changes": {
                "korbar": {
                    "old_value": 0,
                    "new_value": 1,
                    "reason": "Player gave a thoughtful gift",
                }
            },
        })
        output = parse_prose_output(raw)
        assert output.attitude_changes is not None
        assert "korbar" in output.attitude_changes
        assert output.attitude_changes["korbar"].old_value == 0

    def test_narration_only_with_extra_fields(self) -> None:
        raw = json.dumps({
            "narration": "Simple output.",
        })
        output = parse_prose_output(raw)
        assert output.narration == "Simple output."

    def test_invalid_json(self) -> None:
        with pytest.raises(LLMOutputError, match="Invalid JSON"):
            parse_prose_output("not valid {{json")

    def test_not_a_dict(self) -> None:
        with pytest.raises(LLMOutputError, match="JSON object"):
            parse_prose_output('"just a string"')

    def test_missing_narration(self) -> None:
        with pytest.raises(LLMOutputError, match="missing required field"):
            parse_prose_output('{"npc_response": "hello"}')

    def test_empty_object(self) -> None:
        with pytest.raises(LLMOutputError, match="missing required field"):
            parse_prose_output("{}")
