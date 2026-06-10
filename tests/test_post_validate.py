"""Tests for engine/post_validate.py."""

import json
from pathlib import Path

import pytest

from mgmai.engine.post_validate import (
    post_validate_knowledge_tags,
    post_validate_attitude_changes,
    apply_post_validation,
)
from mgmai.models.actions import EngineResult, HardStateChanges
from mgmai.models.narration import AttitudeChange
from mgmai.models.soft_state import KnowledgeEntry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_hard():
    from mgmai.models.hard_state import HardGameState
    return HardGameState.model_validate(
        json.loads((FIXTURES_DIR / "hard-state.json").read_text())
    )


def _load_soft():
    from mgmai.models.soft_state import SoftGameState
    return SoftGameState.model_validate(
        json.loads((FIXTURES_DIR / "soft-state.json").read_text())
    )


class TestPostValidateKnowledgeTags:
    def test_valid_tag_applies_side_effects(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["attitude"] = 5
        tags = {"korbar": ["secret_compartment"]}
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 1
        assert revelations[0].npc_id == "korbar"
        assert revelations[0].topic_id == "secret_compartment"
        # Direct mutation is preserved for condition-evaluation ordering
        assert hard.flags.get("handkerchief_noticed") is True
        assert hard.entity_states["korbar"]["told_secret"] is True
        # Structured delta is also returned
        assert hard_changes.flags_set.get("handkerchief_noticed") is True
        assert hard_changes.entity_state_changes["korbar"]["told_secret"] is True
        assert len(soft.player_knowledge) == 1
        entry = soft.player_knowledge[0]
        assert entry.topic_id == "secret_compartment"
        assert entry.source_type == "npc_dialogue"
        assert entry.source_id == "korbar"

    def test_conditions_not_met_silently_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["attitude"] = 0
        tags = {"korbar": ["padlock_mechanism"]}
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 0
        assert not hard_changes.has_changes()

    def test_unknown_topic_silently_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        tags = {"korbar": ["nonexistent_topic"]}
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 0
        assert not hard_changes.has_changes()

    def test_unknown_npc_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        tags = {"nonexistent": ["padlock_mechanism"]}
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 0
        assert not hard_changes.has_changes()

    def test_dead_npc_skipped(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["alive"] = False
        tags = {"korbar": ["padlock_mechanism"]}
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 0
        assert not hard_changes.has_changes()

    def test_no_duplicate_revelations(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["attitude"] = 5
        tags = {"korbar": ["secret_compartment"]}
        post_validate_knowledge_tags(tags, hard, soft, corpus)
        revelations, hard_changes = post_validate_knowledge_tags(tags, hard, soft, corpus)
        assert len(revelations) == 0
        assert not hard_changes.has_changes()
        assert len(soft.player_knowledge) == 1


class TestPostValidateAttitudeChanges:
    def test_valid_change_applied(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=2, reason="Friendly chat")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" in applied
        assert "korbar" not in rejected
        assert hard.entity_states["korbar"]["attitude"] == 2
        assert "korbar" in hard_changes.entity_state_changes
        assert hard_changes.entity_state_changes["korbar"]["attitude"] == 2

    def test_old_value_mismatch_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=5, new_value=7, reason="Test")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected
        assert "mismatch" in rejected["korbar"]["reason"]

    def test_step_limit_exceeded_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=10, reason="Big jump")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected
        assert "step_per_turn" in rejected["korbar"]["reason"]

    def test_bounds_violation_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=100, reason="OOB")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_dead_npc_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["alive"] = False
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="Dead NPC")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_empty_reason_rejected(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "korbar" not in applied
        assert "korbar" in rejected

    def test_step_zero_rejects_all(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["spider"]["attitude"] = -5
        changes = {
            "spider": AttitudeChange(old_value=-5, new_value=-4, reason="Feed spider")
        }
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
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
        applied, rejected, hard_changes = post_validate_attitude_changes(changes, hard, soft, corpus)
        assert "nonexistent" not in applied
        assert "nonexistent" in rejected

    def test_prior_mechanical_adjustment_rejects_llm_proposal(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="Friendly chat")
        }
        prior = HardStateChanges()
        prior.entity_state_changes["korbar"] = {"attitude": 1}
        applied, rejected, hard_changes = post_validate_attitude_changes(
            changes, hard, soft, corpus, prior_changes=prior
        )
        assert "korbar" not in applied
        assert "korbar" in rejected
        assert "mechanically adjusted" in rejected["korbar"]["reason"]

    def test_prior_changes_without_attitude_allows_llm_proposal(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        changes = {
            "korbar": AttitudeChange(old_value=0, new_value=1, reason="Friendly chat")
        }
        prior = HardStateChanges()
        prior.entity_state_changes["korbar"] = {"following": True}
        applied, rejected, hard_changes = post_validate_attitude_changes(
            changes, hard, soft, corpus, prior_changes=prior
        )
        assert "korbar" in applied
        assert "korbar" not in rejected


class TestApplyPostValidation:
    def test_full_post_validation(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["attitude"] = 5

        knowledge_tags = {"korbar": ["secret_compartment"]}
        attitude_changes = {
            "korbar": AttitudeChange(old_value=5, new_value=6, reason="Great conversation")
        }

        base = EngineResult(success=True, action_type="talk")
        result = apply_post_validation(
            knowledge_tags, attitude_changes, state_manager, base_result=base
        )

        assert isinstance(result, EngineResult)
        assert len(result.revelations_applied) == 1
        assert "korbar" in result.attitude_changes_applied
        assert len(result.attitude_changes_rejected) == 0
        # Post-validation hard changes merged into base result
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.flags_set.get("handkerchief_noticed") is True
        assert result.hard_state_changes.entity_state_changes["korbar"]["told_secret"] is True
        # Attitude change applied to entity_states
        assert result.hard_state_changes.entity_state_changes["korbar"]["attitude"] == 6
        assert hard.entity_states["korbar"]["attitude"] == 6

    def test_none_inputs_are_noop(self, state_manager):
        base = EngineResult(success=True, action_type="talk")
        result = apply_post_validation(None, None, state_manager, base_result=base)
        assert isinstance(result, EngineResult)
        assert result.revelations_applied == []
        assert result.attitude_changes_applied == {}
        assert result.attitude_changes_rejected == {}

    def test_without_base_result_returns_minimal_engine_result(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        hard.entity_states["korbar"]["attitude"] = 5

        knowledge_tags = {"korbar": ["secret_compartment"]}
        result = apply_post_validation(knowledge_tags, None, state_manager)

        assert isinstance(result, EngineResult)
        assert result.success is True
        assert result.action_type == "post_validation"
        assert len(result.revelations_applied) == 1
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.flags_set.get("handkerchief_noticed") is True
