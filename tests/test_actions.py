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

from mgmai.models.actions import (
    AttitudeLimitsCurrent,
    ChainInfo,
    DialogueExitedResult,
    EncounterOutcome,
    EngineResult,
    GameOverResult,
    HardStateChanges,
    PlayerAction,
    RevelationApplied,
    WillRevealReadinessEntry,
)
from mgmai.models.narration import AttitudeChange
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

    def test_examine_using_null(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "examine",
            "target": "spider",
            "rigorous": False,
            "using": None,
            "detail": "The player looks at the spider.",
        })
        assert a.using is None

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
            "given_counts": {"rusty_key": 1},
            "taken_counts": {"rock": 2},
            "detail": "The player hands over the key and takes two rocks.",
        })
        assert a.given_counts == {"rusty_key": 1}
        assert a.taken_counts == {"rock": 2}

    def test_transfer_with_legacy_lists(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "transfer",
            "target": "korbar",
            "given_items": ["rusty_key"],
            "taken_items": ["rock"],
            "detail": "The player hands over the key and takes the rock.",
        })
        assert a.given_items == ["rusty_key"]
        assert a.taken_items == ["rock"]

    def test_transfer_count_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 1"):
            PlayerAction.model_validate({
                "action_type": "transfer",
                "target": "korbar",
                "given_counts": {"rusty_key": 0},
                "detail": "Invalid zero count.",
            })

    def test_transfer_count_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 1"):
            PlayerAction.model_validate({
                "action_type": "transfer",
                "target": "korbar",
                "taken_counts": {"rock": -1},
                "detail": "Invalid negative count.",
            })

    def test_transfer_empty_all_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            PlayerAction.model_validate({
                "action_type": "transfer",
                "target": "korbar",
                "detail": "Nothing given or taken.",
            })

    def test_wait(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "wait",
            "detail": "The player pauses to think.",
        })
        assert a.action_type == "wait"
        assert isinstance(a.detail, str)

    def test_ooc_discussion(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "ooc_discussion",
            "detail": "Is the spider still visible?",
        })
        assert a.action_type == "ooc_discussion"

    def test_with_soft_state_patches(self) -> None:
        a = PlayerAction.model_validate({
            "action_type": "wait",
            "detail": "The player notes the rock.",
            "soft_state_patches": [
                {
                    "field": "appearance_note_add",
                    "new_value": "A loose rock catches the player's eye.",
                    "reason": "Player notices a rock on the floor.",
                },
            ],
        })
        assert len(a.soft_state_patches) == 1
        assert a.soft_state_patches[0].field == "appearance_note_add"

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
        assert r.game_over.type == "win"

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
        assert r.chain_info.follow_up == "Unlock the padlock."

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

    def test_with_room_after(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "move",
            "room_after": {
                "id": "bag_floor",
                "name": "Bag Floor",
                "description": "The floor of the bag.",
                "soft_items": ["cork", "copper"],
                "entities_visible": [
                    {
                        "id": "korbar",
                        "name": "Korbar the Dwarf",
                        "type": "npc",
                        "description": "A drunk dwarf.",
                        "state": {"alive": True},
                        "entity_notes": [],
                        "soft_items": [],
                    },
                ],
                "exits_available": [
                    {
                        "id": "exit_climb",
                        "direction": "Climb up",
                        "target_room": "axe_handle_lower",
                    },
                ],
                "interactions_available": [],
                "room_notes": ["A faint trail leads north."],
            },
        })
        assert r.room_after is not None
        assert r.room_after.id == "bag_floor"

    def test_with_encounter_outcome(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "move",
            "encounter_outcome": {
                "encounter_id": "spider_encounter",
                "combat": False,
                "narrative_brief": "The spider fled into the shadows.",
            },
        })
        assert r.encounter_outcome is not None
        assert r.encounter_outcome.encounter_id == "spider_encounter"
        assert r.encounter_outcome.combat is False

    def test_with_dialogue_exited(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "dialogue_exited": {
                "npc_id": "korbar",
                "exit_narrative": "Korbar turns and walks away.",
            },
        })
        assert r.dialogue_exited is not None
        assert r.dialogue_exited.npc_id == "korbar"

    def test_with_will_reveal_readiness(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "will_reveal_readiness": {
                "korbar": {
                    "padlock_mechanism": {"conditions_met": True, "description": "How to open the padlock."},
                    "secret_compartment": {"conditions_met": False, "description": "A hidden cache."},
                },
            },
        })
        assert r.will_reveal_readiness is not None
        assert r.will_reveal_readiness["korbar"]["padlock_mechanism"].conditions_met is True

    def test_with_npc_attitude_limits(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "npc_attitude_limits": {
                "korbar": {"min": -5, "max": 10, "step_per_turn": 3, "current": 2},
            },
        })
        assert r.npc_attitude_limits is not None
        assert r.npc_attitude_limits["korbar"].current == 2

    def test_with_attitude_changes_applied(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "attitude_changes_applied": {
                "korbar": {"old_value": 0, "new_value": 2, "reason": "Player was kind."},
            },
        })
        assert len(r.attitude_changes_applied) == 1
        assert r.attitude_changes_applied["korbar"].new_value == 2

    def test_with_attitude_changes_rejected(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "attitude_changes_rejected": {
                "grum": {
                    "old_value": 0,
                    "new_value": 2,
                    "reason": "Attitude step exceeded",
                },
            },
        })
        assert len(r.attitude_changes_rejected) == 1

    def test_with_revelations_applied(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "talk",
            "revelations_applied": [
                {
                    "npc_id": "korbar",
                    "topic_id": "padlock_mechanism",
                    "side_effects_applied": ["set_flag"],
                },
            ],
        })
        assert len(r.revelations_applied) == 1
        assert r.revelations_applied[0].npc_id == "korbar"

    def test_with_warnings(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "wait",
            "warnings": [
                "Korbar is present but has not been introduced.",
                "The secret exit remains hidden.",
            ],
        })
        assert len(r.warnings) == 2
        assert "Korbar" in r.warnings[0]

    def test_full_hard_state_changes(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "interact",
            "hard_state_changes": {
                "player_location": "bag_floor",
                "inventory_added": {"rusty_key": 1},
                "inventory_removed": {"iron_sword": 1},
                "flags_set": {"spider_fled": True, "door_opened": True},
                "flags_cleared": ["stunned"],
                "room_state_changes": {
                    "bag_floor": {"visited": True, "searched": True},
                },
                "entity_state_changes": {
                    "spider": {"alive": False, "wounded": True},
                    "korbar": {"told_secret": True},
                },
            },
        })
        assert r.hard_state_changes is not None
        assert r.hard_state_changes.inventory_added == {"rusty_key": 1}
        assert r.hard_state_changes.inventory_removed == {"iron_sword": 1}
        assert r.hard_state_changes.flags_cleared == ["stunned"]
        assert r.hard_state_changes.room_state_changes["bag_floor"]["visited"] is True
        assert r.hard_state_changes.entity_state_changes["spider"]["wounded"] is True

    def test_rolls_with_actual_data(self) -> None:
        r = EngineResult.model_validate({
            "success": True,
            "action_type": "interact",
            "rolls": [
                {"roll_id": "search_roll", "threshold": 0.5, "result": 0.3, "success": True},
                {"roll_id": "attack_roll", "threshold": 0.7, "result": 0.8, "success": False},
            ],
        })
        assert len(r.rolls) == 2
        assert r.rolls[0]["roll_id"] == "search_roll"
        assert r.rolls[0]["success"] is True
        assert r.rolls[1]["success"] is False
