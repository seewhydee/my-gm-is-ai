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

"""Tests for engine/engine.py — main orchestrator."""

import json
from pathlib import Path

import pytest

from mgmai.engine.engine import resolve
from mgmai.models.actions import (
    ExamineAction,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    TalkAction,
    TransferAction,
    WaitAction,
)
from mgmai.models.corpus import StatModifier
from mgmai.state.manager import StateManager

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


class TestEngineFullFlow:
    def test_resolve_move_success(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down the axe handle",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.action_type == "move"
        assert state_manager.hard_state.player.location == "axe_handle_upper"
        assert state_manager.hard_state.turn_count == 1
        assert result.room_after is not None
        assert result.room_after.id == "axe_handle_upper"

    def test_fall_damage_reduces_player_stats(self):
        manager = StateManager(BAG_OF_HOLDING)
        action = MoveAction(
            action_type="move",
            target="exit_drop_from_head",
            detail="Dropping from the axe head",
        )
        result = resolve(action, manager)
        assert result.success is True
        assert manager.hard_state.player.location == "bag_floor"
        assert manager.hard_state.player.stats == {
            "STR": 6, "DEX": 6, "CON": 6,
            "INT": 10, "WIS": 10, "CHA": 10,
        }
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.stat_modifiers == {
            "STR": StatModifier(value=-4), "DEX": StatModifier(value=-4), "CON": StatModifier(value=-4),
        }

    def test_resolve_move_fail(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_nonexistent",
            detail="Walking into nothing",
        )
        result = resolve(action, state_manager)
        assert result.success is False
        assert result.error is not None
        assert state_manager.hard_state.turn_count == 0

    def test_resolve_examine(self, state_manager):
        action = ExamineAction(
            action_type="examine",
            target="padlock",
            detail="Looking at the padlock",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.hard_state.turn_count == 1

    def test_resolve_wait(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Resting for a moment",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.hard_state.turn_count == 1

    def test_resolve_ooc_discussion(self, state_manager):
        action = OocDiscussionAction(
            action_type="ooc_discussion",
            detail="What am I seeing?",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.hard_state.turn_count == 0

    def test_resolve_interact(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        hard.flags["handkerchief_noticed"] = True
        action = InteractAction(
            action_type="interact",
            target="handkerchief",
            interaction_id="move_handkerchief",
            detail="Moving the handkerchief",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert hard.flags.get("handkerchief_moved") is True

    def test_on_enter_events_fire(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert any("sticky webs" in n for n in result.triggered_narration)

    def test_hard_state_changes_returned(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.player_location == "axe_handle_upper"

    def test_turn_history_appended(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Waiting",
        )
        resolve(action, state_manager)
        assert len(state_manager.soft_state.turn_history) == 1
        assert state_manager.soft_state.turn_history[0].turn == 1

    def test_soft_patches_validated(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
            proposed_soft_state_patches=[
                SoftStatePatch(
                    field="room_note",
                    target_id="axe_head",
                    new_value="The room seems dusty.",
                    reason="Perception",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_applied) == 1

    def test_soft_patch_rejected(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
            proposed_soft_state_patches=[
                SoftStatePatch(
                    field="room_note",
                    target_id="nonexistent_room",
                    new_value="Something",
                    reason="Test",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_rejected) == 1


class TestEngineGameOver:
    def test_win_condition(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "axe_head"
        hard.flags["padlock_unlocked"] = True
        action = WaitAction(
            action_type="wait",
            detail="Checking surroundings",
        )
        result = resolve(action, state_manager)
        assert result.game_over is not None
        assert result.game_over.type == "win"

    def test_no_game_over_when_not_met(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Checking surroundings",
        )
        result = resolve(action, state_manager)
        assert result.game_over is None


class TestEngineDialogueIntegration:
    def test_talk_enters_dialogue(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Hello!",
            detail="Greeting Korbar",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.soft_state.dialogue_state.active_npc == "korbar"

    def test_non_talk_action_exits_dialogue_on_stall(self, state_manager):
        """Regression test: non-talk action while in dialogue triggers stall exit.

        This used to raise UnboundLocalError because ``exit_dialogue`` was
        imported locally only inside combat branches, leaving the stall-exit
        path with an unbound local name.
        """
        from mgmai.engine.dialogue import enter_dialogue

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        enter_dialogue(soft, "korbar", hard.turn_count, "Hello", "Greeting")
        soft.dialogue_state.stall_counter = 2

        action = WaitAction(
            action_type="wait",
            detail="Standing awkwardly silent",
        )
        result = resolve(action, state_manager)

        assert result.success is True
        assert result.dialogue_exited is not None
        assert result.dialogue_exited.npc_id == "korbar"
        assert soft.dialogue_state.active_npc is None

    def test_talk_ends_dialogue(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        action1 = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Hello!",
            detail="Greeting Korbar",
        )
        resolve(action1, state_manager)
        action2 = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Goodbye",
            ends_dialogue=True,
            detail="Ending conversation",
        )
        result = resolve(action2, state_manager)
        assert result.success is True
        assert soft.dialogue_state.active_npc is None


class TestEngineChainHandling:
    def test_chain_depth_limit(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing",
            follow_up="Continue climbing",
        )
        result = resolve(action, state_manager, chain_depth=10)
        assert result.success is False
        assert result.chain_info is not None
        assert result.chain_info.termination_reason is not None

    def test_chain_info_in_result(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing",
            follow_up="Continue climbing",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.chain_info is not None
        assert result.chain_info.follow_up == "Continue climbing"


class TestEngineRoomAfter:
    def test_room_after_built_correctly(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.room_after is not None
        assert result.room_after.id == "axe_handle_upper"
        assert result.room_after.name == "Axe Handle (Upper)"
        assert len(result.room_after.entities_visible) > 0
        assert len(result.room_after.exits_available) > 0

    def test_will_reveal_readiness(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        assert result.will_reveal_readiness is not None
        assert "korbar" in result.will_reveal_readiness

    def test_surfaced_soft_items_persisted_after_examine(self, state_manager):
        """Examining a soft item persists it into soft.surfaced_soft_items."""
        action = ExamineAction(
            action_type="examine",
            target="loose stone",
            detail="Looking at stone",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert "axe_head" in state_manager.soft_state.surfaced_soft_items
        assert "loose stone" in state_manager.soft_state.surfaced_soft_items["axe_head"]

    def test_surfaced_soft_items_persisted_after_take(self, state_manager):
        """Taking a soft item persists it into soft.surfaced_soft_items."""
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer",
            target="rubbish_pile",
            taken_items=["stale sandwich"],
            detail="Taking a sandwich",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert "rubbish_pile" in state_manager.soft_state.surfaced_soft_items
        assert "stale sandwich" in state_manager.soft_state.surfaced_soft_items["rubbish_pile"]

    def test_surfaced_soft_items_in_room_after(self, state_manager):
        """Surfaced items appear in the EngineResult.room_after briefing."""
        state_manager.soft_state.surfaced_soft_items["axe_head"] = ["loose stone"]
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        assert result.room_after is not None
        assert "loose stone" in result.room_after.soft_items

    def test_surfaced_entity_soft_items_in_room_after(self, state_manager):
        """Entity-level surfaced items appear in the entity's soft_items in room_after."""
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        state_manager.soft_state.surfaced_soft_items["rubbish_pile"] = ["lint"]
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        rubbish = next(
            e for e in result.room_after.entities_visible
            if e.id == "rubbish_pile"
        )
        assert "lint" in rubbish.soft_items

    def test_npc_attitude_limits(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = WaitAction(
            action_type="wait",
            detail="Checking atmosphere",
        )
        result = resolve(action, state_manager)
        assert result.npc_attitude_limits is not None
        assert "korbar" in result.npc_attitude_limits
        limits = result.npc_attitude_limits["korbar"]
        assert limits.min == -5
        assert limits.max == 10
        assert limits.step_per_turn == 3
