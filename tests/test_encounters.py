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

"""Tests for engine/encounters.py."""

import copy
import json
from pathlib import Path

import pytest

from mgmai.engine.encounters import resolve_encounter, _game_over_dict
from mgmai.models.corpus import (
    ConditionExpression,
    EncounterRule,
    GameOverTrigger,
    ModuleCorpus,
    Result,
    StatCheck,
    StatDefinition,
    StatsBlock,
    StatModifier
)
from mgmai.models.hard_state import HardGameState, GameOverState
from mgmai.models.soft_state import SoftGameState
from tests.helpers import _mk_encounter_rule

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
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="You die horribly."
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["game_over"] is not None
        assert result["game_over"] is not None
        assert result["game_over"]["type"] == "lose"
        assert result["narrative"] == "You die horribly."

    def test_flee_rule_applies_flee_effects(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        hard.flags["spider_fled"] = False
        rules = [
            _mk_encounter_rule(
                outcome="flee",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="The spider flees!",
                set_flag={"spider_fled": True}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["narrative"] is not None
        assert result["changes"].flags_set["spider_fled"] is True

    def test_roll_success_branch(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.1)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="Lunging...",
                threshold=0.5,
                success={
                    "narrative": "You win!",
                    "set_flag": {"spider_fled": True},
                },
                failure={
                    "game_over": {"type": "lose", "trigger_id": "spider"},
                    "narrative": "You die.",
                }
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["narrative"] is not None
        assert result["narrative"] == "You win!"
        assert result["changes"].flags_set["spider_fled"] is True

    def test_roll_failure_branch(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.9)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="Lunging...",
                threshold=0.5,
                success={
                    "narrative": "You win!",
                },
                failure={
                    "game_over": {"type": "lose", "trigger_id": "spider"},
                    "narrative": "You die.",
                }
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["game_over"] is not None
        assert result["narrative"] == "You die."

    def test_no_rules_match_returns_none(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="flag:nonexistent == true"),
                narrative="Should not fire."
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["branch_taken"] is None
        assert result["narrative"] is None

    def test_first_matching_rule_wins(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="flee",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="First rule fires."
            ),
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="Second rule should not fire."
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["narrative"] is not None
        assert result["narrative"] == "First rule fires."

    def test_rule_level_alter_stat_on_death(self, sample_corpus):
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="You die.",
                alter_stat={"CON": StatModifier(value=-4)}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["game_over"] is not None
        assert result["changes"].stat_modifiers == {"CON": StatModifier(value=-4)}

    def test_branch_alter_stat_on_stat_check(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e",
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 20)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
                success={
                    "alter_stat": {"DEX": StatModifier(value=-2)},
                    "narrative": "You dodge, but twist an ankle.",
                }
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["narrative"] is not None
        assert result["changes"].stat_modifiers == {"DEX": StatModifier(value=-2)}

    def test_branch_alter_stat_on_stat_check_success(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e",
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 20)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
                alter_stat={"CON": StatModifier(value=-2)},
                success={
                    "alter_stat": {"STR": StatModifier(value=-4), "CON": StatModifier(value=-4)},
                    "narrative": "You land badly despite rolling well.",
                }
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["narrative"] is not None
        assert result["changes"].stat_modifiers == {"CON": StatModifier(value=-4), "STR": StatModifier(value=-4)}

    def test_rule_level_trigger_combat(self, sample_corpus):
        """Result with trigger_combat=True (no check) propagates."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="combat",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="The spider drops from the shadows!",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is True
        assert result["game_over"] is None
        assert result["branch_taken"] is None
        assert result["narrative"] == "The spider drops from the shadows!"

    def test_rule_level_game_over_win(self, sample_corpus):
        """Result with game_over type=win maps to dict with trigger field."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="You won!",
                game_over_type="win",
                game_over_trigger="test_npc",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["game_over"] is not None
        assert result["game_over"]["type"] == "win"
        assert result["game_over"]["trigger"] == "test_npc"

    def test_flee_rule_triggers_no_combat_no_game_over(self, sample_corpus):
        """A flee rule should have trigger_combat=False and game_over=None."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="flee",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="The creature flees!",
                set_flag={"creature_fled": True},
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is False
        assert result["game_over"] is None
        assert result["changes"].flags_set["creature_fled"] is True

    def test_no_rules_match_returns_safe_defaults(self, sample_corpus):
        """When no rules match, result has trigger_combat=False, game_over=None."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="flag:nonexistent == true"),
                narrative="Should not fire.",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus)
        assert result["trigger_combat"] is False
        assert result["game_over"] is None
        assert result["branch_taken"] is None
        assert result["narrative"] is None

    def test_branch_with_trigger_combat_roll_fails_no_combat(self, sample_corpus, monkeypatch):
        """When a roll check fails and failure has no trigger_combat, it stays False."""
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.9)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                threshold=0.5,
                success={"trigger_combat": True, "narrative": "It attacks!"},
                failure={"narrative": "It flees."},
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is False
        assert result["branch_taken"] == "failure"
        assert result["narrative"] == "It flees."

    def test_result_with_player_damage_and_trigger_combat(self, sample_corpus):
        """A rule-level result can carry both player_damage and trigger_combat."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="combat",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="The spider bites you!",
                trigger_combat=True,
                player_damage="2d6",
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is True
        assert result["changes"].player_hp_delta is not None
        assert result["changes"].player_hp_delta < 0
        assert result["narrative"] == "The spider bites you!"


class TestEncounterBranchTaken:
    """Item 3a: branched encounters record which branch was taken."""

    def test_stat_check_branch_taken_success(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e",
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 20)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
                success={"narrative": "You dodge."},
                failure={"game_over": {"type": "lose", "trigger_id": "spider"}, "narrative": "You die."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["narrative"] is not None
        assert result["branch_taken"] == "success"

    def test_stat_check_branch_taken_failure(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        # Give the player a DEX stat and the corpus a stats block so the
        # stat check actually rolls (otherwise it short-circuits to True).
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e"
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 1)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
                success={"narrative": "You dodge."},
                failure={"game_over": {"type": "lose", "trigger_id": "spider"}, "narrative": "You die."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["game_over"] is not None
        assert result["branch_taken"] == "failure"

    def test_roll_branch_taken_success(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.1)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                threshold=0.5,
                success={"narrative": "You win!"},
                failure={"game_over": {"type": "lose", "trigger_id": "spider"}, "narrative": "You die."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["narrative"] is not None
        assert result["branch_taken"] == "success"

    def test_roll_branch_taken_failure(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.9)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                threshold=0.5,
                success={"narrative": "You win!"},
                failure={"game_over": {"type": "lose", "trigger_id": "spider"}, "narrative": "You die."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["game_over"] is not None
        assert result["branch_taken"] == "failure"

    def test_no_branch_taken_for_top_level_outcome(self, sample_corpus):
        """Top-level outcomes (death/flee/combat) don't set branch_taken."""
        hard = _load_hard()
        soft = _load_soft()
        rules = [
            _mk_encounter_rule(
                outcome="death",
                condition=ConditionExpression(require="entity:player.alive == true"),
                narrative="You die."
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result.get("branch_taken") is None

    def test_no_branch_taken_when_branch_is_none(self, sample_corpus, monkeypatch):
        """A stat_check with no success/failure doesn't set branch_taken."""
        hard = _load_hard()
        soft = _load_soft()
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e",
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 20)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result.get("branch_taken") is None


class TestEncounterBranchCombat:
    """Item 3b: BranchOutcome outcome='combat' is handled explicitly.

    The 'combat' outcome string propagates to the caller (engine.py /
    event_bus.py), which calls enter_combat().  These tests confirm the
    explicit arm preserves that behavior for both stat_check and roll
    branches: outcome stays 'combat', with no game_over.
    """

    def test_stat_check_branch_combat_propagates(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        hard.player.stats = {"DEX": 10}
        sample_corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="DEX", description="Dexterity")},
            system="5e",
        )
        monkeypatch.setattr("mgmai.engine.systems.five_e.random.randint", lambda a, b: 20)
        rules = [
            _mk_encounter_rule(
                outcome="stat_check",
                condition=ConditionExpression(require="entity:player.alive == true"),
                stat_check={"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
                success={"trigger_combat": True, "narrative": "It attacks!"},
                failure={"narrative": "It flees."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is True
        assert result["game_over"] is None
        assert result["branch_taken"] == "success"

    def test_roll_branch_combat_propagates(self, sample_corpus, monkeypatch):
        hard = _load_hard()
        soft = _load_soft()
        monkeypatch.setattr("random.random", lambda: 0.1)
        rules = [
            _mk_encounter_rule(
                outcome="roll",
                condition=ConditionExpression(require="entity:player.alive == true"),
                threshold=0.5,
                success={"trigger_combat": True, "narrative": "It attacks!"},
                failure={"narrative": "It flees."}
            )
        ]
        result = resolve_encounter(rules, hard, soft, sample_corpus, npc_id="spider")
        assert result["trigger_combat"] is True
        assert result["game_over"] is None
        assert result["branch_taken"] == "success"


class TestGameOverDict:
    """Direct unit tests for the _game_over_dict mapping function."""

    def test_lose_maps_correctly(self) -> None:
        go = _game_over_dict(GameOverTrigger(type="lose", trigger_id="spider"))
        assert go == {"type": "lose", "trigger": "spider"}

    def test_win_maps_correctly(self) -> None:
        go = _game_over_dict(GameOverTrigger(type="win", trigger_id="escape"))
        assert go == {"type": "win", "trigger": "escape"}

    def test_none_returns_none(self) -> None:
        assert _game_over_dict(None) is None
