import pytest
from pydantic import ValidationError

from mgmai.models.actions import EngineResult, PlayerAction
from mgmai.models.soft_state import SoftStatePatch


class TestPlayerAction:
    def test_move(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "move",
            "target": "exit_through_webs",
            "style": "crawling",
            "detail": "The player crawls through the narrow tunnel.",
        })
        assert a.action_type == "move"
        assert a.target == "exit_through_webs"
        assert a.style == "crawling"
        assert a.rigorous is False

    def test_examine(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "examine",
            "target": "spider",
            "rigorous": True,
            "using": "torch",
            "detail": "The player peers closely at the spider.",
        })
        assert a.action_type == "examine"
        assert a.rigorous is True
        assert a.using == "torch"

    def test_interact(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "interact",
            "target": "spider",
            "interaction_id": "attack",
            "using": "iron_sword",
            "detail": "The player slashes at the spider.",
        })
        assert a.interaction_id == "attack"
        assert a.using == "iron_sword"

    def test_talk(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "talk",
            "target": "korbar",
            "utterance": "Who are you?",
            "detail": "The player approaches the dwarf openly.",
            "ends_dialogue": False,
        })
        assert a.utterance == "Who are you?"
        assert a.ends_dialogue is False

    def test_transfer(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "transfer",
            "target": "korbar",
            "given_items": ["rusty_key"],
            "taken_items": ["rock"],
            "detail": "The player hands over the key and takes the rock.",
        })
        assert a.given_items == ["rusty_key"]
        assert a.taken_items == ["rock"]

    def test_wait(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "wait",
            "detail": "The player pauses to think.",
        })
        assert a.target is None

    def test_ooc_discussion(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "ooc_discussion",
            "detail": "Is the spider still visible?",
        })
        assert a.action_type == "ooc_discussion"

    def test_with_soft_state_patches(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "wait",
            "detail": "The player picks up a rock.",
            "proposed_soft_state_patches": [
                {
                    "field": "soft_inventory_add",
                    "new_value": "rock",
                    "reason": "Player picks up a rock from the floor.",
                },
            ],
        })
        assert len(a.proposed_soft_state_patches) == 1
        assert a.proposed_soft_state_patches[0].field == "soft_inventory_add"

    def test_follow_up(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "transfer",
            "target": "bag_floor",
            "taken_items": ["rusty_key"],
            "detail": "The player picks up the rusty key.",
            "follow_up": "Unlock the padlock using the rusty key.",
        })
        assert a.follow_up == "Unlock the padlock using the rusty key."

    def test_invalid_action_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            PlayerAction.model_validate({
                "action_type": "cast_spell",
                "detail": "The player casts fireball.",
            })

    def test_missing_detail_raises(self) -> None:
        with pytest.raises(ValidationError):
            PlayerAction.model_validate({
                "action_type": "move",
                "target": "exit1",
            })


class TestEngineResult:
    def test_success_move(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "move",
            "target": "exit_through_webs",
            "hard_state_changes": {
                "player_location": "bag_floor",
                "flags_set": {"spider_fled": True},
            },
            "triggered_narration": [
                "You push through the sticky webs.",
                "You emerge onto the floor of the bag.",
            ],
        })
        assert r.success is True
        assert r.action_type == "move"
        assert len(r.triggered_narration) == 2
        assert r.hard_state_changes is not None

    def test_failure(self) -> None:
        r = EngineResult.model_validate({
            "success": False,
            "action_type": "move",
            "target": "secret_exit",
            "error": "invalid_target",
            "message": "Exit 'secret_exit' is hidden.",
            "player_input_echo": "I go through the secret exit.",
        })
        assert r.success is False
        assert r.error == "invalid_target"
        assert r.message == "Exit 'secret_exit' is hidden."

    def test_with_soft_patches(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "wait",
            "soft_state_patches_applied": [
                {
                    "field": "room_note",
                    "target_id": "axe_head",
                    "new_value": "Webs cleared.",
                    "reason": "Player cleared the webs.",
                },
            ],
            "soft_state_patches_rejected": [
                {
                    "field": "entity_note",
                    "entity_id": "spider",
                    "new_value": "The spider is dead.",
                    "reason": "Player killed it.",
                    "rejection_reason": "Contradicts hard state: spider is alive.",
                },
            ],
        })
        assert len(r.soft_state_patches_applied) == 1
        assert len(r.soft_state_patches_rejected) == 1
        assert r.soft_state_patches_applied[0].field == "room_note"

    def test_game_over(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "move",
            "game_over": {"type": "win", "trigger": "escape_bag", "narrative": "You are free!"},
        })
        assert r.game_over is not None
        assert r.game_over["type"] == "win"

    def test_chain_info(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "transfer",
            "chain_info": {
                "follow_up": "Unlock the padlock.",
                "termination_reason": None,
            },
        })
        assert r.chain_info is not None
        assert r.chain_info["follow_up"] == "Unlock the padlock."

    def test_default_lists(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "wait",
        })
        assert r.rolls == []
        assert r.triggered_narration == []
        assert r.warnings == []
        assert r.soft_state_patches_applied == []
        assert r.soft_state_patches_rejected == []

    def test_missing_success_raises(self) -> None:
        with pytest.raises(ValidationError):
            EngineResult.model_validate({
                "action_type": "move",
            })

    def test_missing_action_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            EngineResult.model_validate({
                "success": True,
            })
