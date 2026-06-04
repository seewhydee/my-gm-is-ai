"""Tests for engine/post_validate.py."""

import json
from pathlib import Path

import pytest

from mgmai.engine.post_validate import (
    post_validate_knowledge_tags,
    post_validate_attitude_changes,
    apply_post_validation,
)
from mgmai.models.narration import AttitudeChange

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


def _load_hard():
    from mgmai.models.hard_state import HardGameState
    return HardGameState.model_validate(
        json.loads((BAG_OF_HOLDING / "hard-state.json").read_text())
    )


def _load_soft():
    from mgmai.models.soft_state import SoftGameState
    return SoftGameState.model_validate(
        json.loads((BAG_OF_HOLDING / "soft-state.json").read_text())
    )


class TestPostValidateKnowledgeTags:
    def test_valid_tag_applies_side_effects(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.npc_attitudes["korbar"] = 5
        tags = {"korbar": ["secret_compartment"]}
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 1
        assert result[0].npc_id == "korbar"
        assert result[0].topic_id == "secret_compartment"
        assert hard.flags.get("handkerchief_noticed") is True
        assert hard.entity_states["korbar"]["told_secret"] is True
        assert "korbar" in soft.npc_revelations
        assert len(soft.npc_revelations["korbar"]) == 1
        assert soft.npc_revelations["korbar"][0].topic_id == "secret_compartment"

    def test_conditions_not_met_silently_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.npc_attitudes["korbar"] = 0
        tags = {"korbar": ["padlock_mechanism"]}
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 0

    def test_unknown_topic_silently_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        tags = {"korbar": ["nonexistent_topic"]}
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 0

    def test_unknown_npc_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        tags = {"nonexistent": ["padlock_mechanism"]}
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 0

    def test_dead_npc_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["alive"] = False
        tags = {"korbar": ["padlock_mechanism"]}
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 0

    def test_no_duplicate_revelations(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.npc_attitudes["korbar"] = 5
        tags = {"korbar": ["secret_compartment"]}
        post_validate_knowledge_tags(tags, hard, soft, corpus)
        result = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(result) == 0
        assert len(soft.npc_revelations["korbar"]) == 1


class TestPostValidateAttitudeChanges:
    def test_valid_change_applied(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=2, reason="Friendly chat")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" in applied
        assert "korbar" not in rejected
        assert soft.npc_attitudes["korbar"] == 2

    def test_old_value_mismatch_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=5, new_value=7, reason="Test")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected
        assert "mismatch" in rejected["korbar"]["reason"]

    def test_step_limit_exceeded_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=10, reason="Big jump")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected
        assert "step_per_turn" in rejected["korbar"]["reason"]

    def test_bounds_violation_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=100, reason="OOB")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_dead_npc_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["alive"] = False
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="Dead NPC")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_empty_reason_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["korbar"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_step_zero_rejects_all(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.npc_attitudes["spider"] = -5
        changes = {
            "spider": AttitudeChange(old_value=-5, new_value=-4, reason="Feed spider")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "spider" not in applied
        assert "spider" in rejected
        assert "step_per_turn is 0" in rejected["spider"]["reason"]

    def test_unknown_npc_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        changes = {
            "nonexistent": AttitudeChange(old_value=0, new_value=1, reason="Test")
        }
        applied, rejected = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "nonexistent" not in applied
        assert "nonexistent" in rejected


class TestApplyPostValidation:
    def test_full_post_validation(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.npc_attitudes["korbar"] = 5

        knowledge_tags = {"korbar": ["secret_compartment"]}
        attitude_changes = {
            "korbar": AttitudeChange(old_value=5, new_value=6, reason="Great conversation")
        }

        result = apply_post_validation(
            knowledge_tags, attitude_changes, hard, soft, corpus
        )

        assert len(result["revelations_applied"]) == 1
        assert "korbar" in result["attitude_changes_applied"]
        assert len(result["attitude_changes_rejected"]) == 0

    def test_none_inputs_are_noop(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        result = apply_post_validation(None, None, hard, soft, corpus)
        assert result["revelations_applied"] == []
        assert result["attitude_changes_applied"] == {}
        assert result["attitude_changes_rejected"] == {}
