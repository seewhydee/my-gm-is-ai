"""Tests for engine/encounters.py."""

import copy
import json
from pathlib import Path

import pytest

from mgmai.engine.encounters import (
    resolve_encounter,
    should_trigger_behavior,
    apply_flee_effects,
)
from mgmai.models.corpus import (
    Behavior,
    EncounterRule,
    ConditionExpression,
    ModuleCorpus,
)
from mgmai.models.hard_state import HardGameState, GameOverState
from mgmai.models.soft_state import SoftGameState

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_hard():
    return HardGameState.model_validate(
        json.loads((FIXTURES_DIR / "hard-state.json").read_text())
    )


def _load_soft():
    return SoftGameState.model_validate(
        json.loads((FIXTURES_DIR / "soft-state.json").read_text())
    )


class TestResolveEncounter:
    def test_death_rule_sets_game_over(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="death",
                narrative="You die horribly.",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["outcome"] == "death"
        assert result["game_over"] is not None
        assert result["game_over"]["type"] == "lose"
        assert result["narrative"] == "You die horribly."

    def test_flee_rule_applies_flee_effects(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        hard.flags["spider_fled"] = False
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="flee",
                narrative="The spider flees!",
                set_flags={"spider_fled": True},
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["outcome"] == "flee"
        assert result["set_flags"]["spider_fled"] is True
        assert result["flee_effects"] is not None

    def test_roll_success_branch(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("mgmai.engine.encounters.random.random", lambda: 0.1)
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="roll",
                threshold=0.5,
                narrative="Lunging...",
                on_success={
                    "outcome": "flee",
                    "narrative": "You win!",
                    "set_flags": {"spider_fled": True},
                },
                on_failure={
                    "outcome": "death",
                    "narrative": "You die.",
                },
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["outcome"] == "flee"
        assert result["narrative"] == "You win!"
        assert result["set_flags"]["spider_fled"] is True

    def test_roll_failure_branch(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("mgmai.engine.encounters.random.random", lambda: 0.9)
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="roll",
                threshold=0.5,
                narrative="Lunging...",
                on_success={
                    "outcome": "flee",
                    "narrative": "You win!",
                },
                on_failure={
                    "outcome": "death",
                    "narrative": "You die.",
                },
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["outcome"] == "death"
        assert result["narrative"] == "You die."

    def test_no_rules_match_returns_none(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="flag:nonexistent == true"),
                outcome="death",
                narrative="Should not fire.",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["outcome"] == "none"
        assert result["narrative"] is None

    def test_first_matching_rule_wins(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="flee",
                narrative="First rule fires.",
            ),
            EncounterRule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="death",
                narrative="Second rule should not fire.",
            ),
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["outcome"] == "flee"
        assert result["narrative"] == "First rule fires."


class TestShouldTriggerBehavior:
    def test_trigger_by_action_type(self, sample_corpus):
        rules = should_trigger_behavior("spider", "attack", None, sample_corpus)
        assert rules is not None
        assert len(rules) > 0

    def test_no_trigger_for_non_behavior_entity(self, sample_corpus):
        rules = should_trigger_behavior("player", "attack", None, sample_corpus)
        assert rules is None

    def test_trigger_by_exit_id(self, sample_corpus):
        rules = should_trigger_behavior(
            "spider", "move", "exit_through_webs", sample_corpus
        )
        assert rules is not None
        assert len(rules) > 0

    def test_no_trigger_for_unknown_entity(self, sample_corpus):
        rules = should_trigger_behavior("nonexistent", "attack", None, sample_corpus)
        assert rules is None


class TestApplyFleeEffects:
    def test_applies_flags(self, sample_corpus):
        hard = _load_hard()
        flee_data = {
            "set_flags": {"spider_fled": True, "test_flag": False},
            "set_entity_state": None,
            "effect": "It fled.",
        }
        apply_flee_effects(flee_data, hard)
        assert hard.flags["spider_fled"] is True
        assert hard.flags["test_flag"] is False

    def test_applies_entity_state(self, sample_corpus):
        hard = _load_hard()
        flee_data = {
            "set_flags": {"spider_fled": True},
            "set_entity_state": {"spider": {"alive": False}},
            "effect": "It fled.",
        }
        apply_flee_effects(flee_data, hard)
        assert hard.entity_states["spider"]["alive"] is False

    def test_none_is_noop(self, sample_corpus):
        hard = _load_hard()
        original = hard.flags.get("spider_fled")
        apply_flee_effects(None, hard)
        assert hard.flags.get("spider_fled") == original
