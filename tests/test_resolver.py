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

"""Tests for engine/resolver.py."""

import copy
import json
from pathlib import Path

import pytest

from mgmai.engine.resolver import (
    resolve_move,
    resolve_examine,
    resolve_interact,
    resolve_talk,
    resolve_transfer,
    resolve_wait,
    resolve_ooc,
    resolve_action,
    _apply_result,
)
from mgmai.models.actions import (
    MoveAction,
    ExamineAction,
    InteractAction,
    TalkAction,
    TransferAction,
    WaitAction,
    OocDiscussionAction,
)
from mgmai.models.corpus import (
    Result,
    RollCheck,
    StatCheck,
    StatModifier,
    TakeCheck,
)
from mgmai.state.manager import StateManager
from tests.helpers import (
    build_state_manager,
    make_encounter_trigger_corpus,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_hard():
    return HardGameState.model_validate(
        json.loads((FIXTURES_DIR / "hard-state.json").read_text())
    )


def _load_soft():
    return SoftGameState.model_validate(
        json.loads((FIXTURES_DIR / "soft-state.json").read_text())
    )


from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState


class TestResolveWait:
    def test_always_succeeds(self, state_manager):
        action = WaitAction(action_type="wait", detail="Looking around")
        result = resolve_wait(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.room_after_id == "axe_head"

    def test_no_state_changes(self, state_manager):
        action = WaitAction(action_type="wait", detail="Resting")
        hard = state_manager.hard_state
        result = resolve_wait(action, hard, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.hard_changes is not None
        assert result.hard_changes.player_location is None


class TestResolveOoc:
    def test_always_succeeds(self, state_manager):
        action = OocDiscussionAction(action_type="ooc_discussion", detail="What is that?")
        result = resolve_ooc(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.room_after_id == "axe_head"


class TestResolveExamine:
    def test_examine_entity_in_room(self, state_manager):
        action = ExamineAction(action_type="examine", target="padlock", detail="Examining the padlock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert any("padlock" in n for n in result.triggered_narration)

    def test_examine_room(self, state_manager):
        action = ExamineAction(action_type="examine", target="axe_head", detail="Looking around")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True

    def test_examine_nonexistent_target(self, state_manager):
        action = ExamineAction(action_type="examine", target="nonexistent", detail="Looking")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False
        assert "not found" in (result.error or "")

    def test_examine_with_using_not_in_inventory(self, state_manager):
        action = ExamineAction(action_type="examine", target="padlock", using="rusty_key", detail="Poking with key")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False
        assert "not in your inventory" in (result.error or "")

    def test_examine_with_using_in_inventory(self, state_manager):
        state_manager.hard_state.player.inventory.append("rusty_key")
        action = ExamineAction(action_type="examine", target="padlock", using="rusty_key", detail="Poking with key")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True

    def test_examine_soft_item(self, state_manager):
        action = ExamineAction(action_type="examine", target="loose stone", detail="Looking at stone")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True

    def test_examine_soft_item_surfaces_on_room(self, state_manager):
        """Soft items belonging to the room are surfaced on the room ID."""
        action = ExamineAction(action_type="examine", target="loose stone", detail="Looking at stone")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.surfaced_soft_items.get("axe_head") == ["loose stone"]

    def test_examine_soft_item_surfaces_on_entity(self, state_manager):
        """Soft items exclusive to an entity are surfaced on that entity ID."""
        state_manager.hard_state.player.location = "bag_floor"
        action = ExamineAction(action_type="examine", target="stale sandwich", detail="Looking at sandwich")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.surfaced_soft_items.get("rubbish_pile") == ["stale sandwich"]

    def test_examine_room_soft_item_surfaces_on_room(self, state_manager):
        """Soft items listed on the room surface on the room ID."""
        state_manager.hard_state.player.location = "axe_handle_lower"
        action = ExamineAction(action_type="examine", target="rock", detail="Looking at rock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.surfaced_soft_items.get("axe_handle_lower") == ["rock"]

    def test_examine_soft_item_surfaces_on_room_when_shared(self, state_manager):
        """When a soft item exists on both room and entity, room wins."""
        state_manager.hard_state.player.location = "axe_handle_upper"
        action = ExamineAction(action_type="examine", target="sticky webbing", detail="Looking at webbing")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.surfaced_soft_items.get("axe_handle_upper") == ["sticky webbing"]

    def test_examine_non_soft_item_no_surfacing(self, state_manager):
        """Examining an entity (not a soft item) does not populate surfaced_soft_items."""
        action = ExamineAction(action_type="examine", target="padlock", detail="Looking at padlock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.surfaced_soft_items == {}


class TestResolveMove:
    def test_valid_exit(self, state_manager):
        action = MoveAction(action_type="move", target="exit_climb_down_handle", detail="Climbing down")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.hard_changes.player_location == "axe_handle_upper"
        assert result.room_after_id == "axe_handle_upper"

    def test_invalid_exit(self, state_manager):
        action = MoveAction(action_type="move", target="exit_nonexistent", detail="Walking")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False
        assert "not found" in (result.error or "")

    def test_drop_exit_sets_flag(self, state_manager):
        action = MoveAction(action_type="move", target="exit_drop_from_head", detail="Dropping down")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus, state_manager)
        assert result.success is True
        assert result.hard_changes.player_location == "bag_floor"
        assert "injured" in result.immediate_changes.flags_set
        assert result.immediate_changes.flags_set["injured"] is True

    def test_drop_exit_generates_narrative(self, state_manager):
        action = MoveAction(action_type="move", target="exit_drop_from_head", detail="Dropping down")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus, state_manager)
        assert len(result.triggered_narration) > 0

    def test_hidden_exit_not_accessible(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        action = MoveAction(action_type="move", target="exit_enter_secret_flap", detail="Entering flap")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False
        assert "condition" in (result.error or "").lower() or "hidden" in (result.error or "").lower()

    def test_condition_gated_exit(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.flags["handkerchief_moved"] = True
        action = MoveAction(action_type="move", target="exit_enter_secret_flap", detail="Entering flap")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.hard_changes.player_location == "secret_compartment"

    def test_condition_gated_exit_fails(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        action = MoveAction(action_type="move", target="exit_enter_secret_flap", detail="Entering hidden flap")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False

    def test_traverse_skip_if(self, state_manager):
        state_manager.hard_state.flags["spider_fled"] = True
        state_manager.hard_state.player.location = "axe_handle_lower"
        action = MoveAction(action_type="move", target="exit_through_webs", detail="Pushing through webs")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.hard_changes.player_location == "bag_floor"

    def test_sets_visited_on_target_room(self, state_manager):
        action = MoveAction(action_type="move", target="exit_climb_down_handle", detail="Climbing down")
        result = resolve_move(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.hard_changes.room_state_changes.get("axe_handle_upper", {}).get("visited") is True

    def test_drop_exit_triggers_fall_damage_encounter_from_head(self):
        corpus = make_encounter_trigger_corpus(
            mechanic_id="fall_damage_test",
            exit_id="exit_drop",
            target_room_id="target",
            reaction_event="traversal.attempted",
            encounter_outcome="flee",
        )
        manager = build_state_manager(corpus)
        action = MoveAction(action_type="move", target="exit_drop", detail="Dropping")
        result = resolve_move(action, manager.hard_state, manager.soft_state, manager.corpus, manager)
        assert result.success is True
        assert result.encounter_trigger == "fall_damage_test"
        assert result.hard_changes.player_location == "target"

    def test_drop_exit_triggers_encounter_without_leaving_room(self):
        corpus = make_encounter_trigger_corpus(
            mechanic_id="ambush",
            exit_id="exit_forward",
            target_room_id="target",
            reaction_event="traversal.attempted",
            encounter_outcome="combat",
        )
        manager = build_state_manager(corpus)
        action = MoveAction(action_type="move", target="exit_forward", detail="Moving")
        result = resolve_move(action, manager.hard_state, manager.soft_state, manager.corpus, manager)
        assert result.success is True
        assert result.encounter_trigger == "ambush"


class TestResolveTalk:
    def test_talk_to_present_npc(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        action = TalkAction(action_type="talk", target="korbar", utterance="Hello!", detail="Greeting")
        result = resolve_talk(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert state_manager.soft_state.dialogue_state.active_npc == "korbar"

    def test_talk_to_npc_not_in_room(self, state_manager):
        action = TalkAction(action_type="talk", target="korbar", utterance="Hello!", detail="Greeting")
        result = resolve_talk(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False

    def test_talk_to_dead_npc(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.entity_states["korbar"]["alive"] = False
        action = TalkAction(action_type="talk", target="korbar", utterance="Hello?", detail="Greeting")
        result = resolve_talk(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False

    def test_ends_dialogue(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        soft = state_manager.soft_state
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        from mgmai.engine.dialogue import enter_dialogue
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        action = TalkAction(action_type="talk", target="korbar", utterance="Goodbye", ends_dialogue=True, detail="Farewell")
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is True
        assert soft.dialogue_state.active_npc is None

    def test_switches_npc(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from mgmai.engine.dialogue import enter_dialogue
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        action = TalkAction(action_type="talk", target="rubbish_pile", utterance="Hi?", detail="Talking to rubbish")
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is False


class TestResolveTransfer:
    def test_give_item_from_inventory(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.player.inventory.append("toenail_sword")
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_items=["toenail_sword"],
            detail="Giving sword to Korbar",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert "toenail_sword" in result.hard_changes.inventory_removed

    def test_give_item_not_in_inventory(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_items=["nonexistent_item"],
            detail="Giving nothing",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False
        assert "not in your inventory" in (result.error or "")

    def test_take_item_from_room(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        action = TransferAction(
            action_type="transfer", target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert "rusty_key" in result.hard_changes.inventory_added

    def test_transfer_target_not_found(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        action = TransferAction(
            action_type="transfer", target="nonexistent",
            given_items=["fictional_item"],
            taken_items=[],
            detail="Transferring",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False

    def test_give_soft_item(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_inventory.append("cork")
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_items=["cork"],
            taken_items=[],
            detail="Giving a cork",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert len(result.soft_patches) == 1
        assert result.soft_patches[0].field == "soft_inventory_remove"
        assert result.soft_patches[0].new_value == "cork"

    def test_give_soft_item_surfaces_on_target(self, state_manager):
        """Given soft items are surfaced on the transfer target."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_inventory.append("cork")
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_items=["cork"],
            taken_items=[],
            detail="Giving a cork",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.surfaced_soft_items.get("korbar") == ["cork"]

    def test_take_soft_item_surfaces_on_entity_source(self, state_manager):
        """Taken soft items exclusive to an entity are surfaced on that entity."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            given_items=[],
            taken_items=["stale sandwich"],
            detail="Taking a sandwich",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.surfaced_soft_items.get("rubbish_pile") == ["stale sandwich"]

    def test_take_soft_item_surfaces_on_entity_when_shared(self, state_manager):
        """When target is an entity, soft items surface on that entity."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            given_items=[],
            taken_items=["cork"],
            detail="Taking a cork",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        # cork is in rubbish_pile.soft_items; target_is_entity path checks target entity
        assert result.surfaced_soft_items.get("rubbish_pile") == ["cork"]

    def test_take_soft_item_surfaces_on_room_when_target_is_room(self, state_manager):
        """When transfer target is the room itself, surface on the room."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer", target="bag_floor",
            given_items=[],
            taken_items=["cork"],
            detail="Picking up a cork",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.surfaced_soft_items.get("bag_floor") == ["cork"]


class TestResolveInteract:
    def test_interact_with_entity_interaction(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = InteractAction(
            action_type="interact", target="handkerchief",
            interaction_id="search_handkerchief",
            detail="Searching the handkerchief",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is True

    def test_interact_not_found(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = InteractAction(
            action_type="interact", target="korbar",
            interaction_id="nonexistent_interaction",
            detail="Doing something",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False

    def test_interact_condition_not_met(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.flags["handkerchief_noticed"] = False
        action = InteractAction(
            action_type="interact", target="handkerchief",
            interaction_id="move_handkerchief",
            detail="Moving handkerchief",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False

    def test_interact_condition_met(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.flags["handkerchief_noticed"] = True
        action = InteractAction(
            action_type="interact", target="handkerchief",
            interaction_id="move_handkerchief",
            detail="Moving handkerchief",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.flags_set.get("handkerchief_moved") is True

    def test_transfer_take_item(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        action = TransferAction(
            action_type="transfer", target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the key",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert "rusty_key" in result.hard_changes.inventory_added

    def test_attack_on_npc_with_behavior(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = InteractAction(
            action_type="interact", target="korbar",
            interaction_id="attack",
            detail="Attacking Korbar",
        )
        result = resolve_interact(action, hard, soft, corpus, state_manager)
        assert result.encounter_trigger == "korbar"

    def test_attack_on_non_combatant(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        action = InteractAction(
            action_type="interact", target="padlock",
            interaction_id="attack",
            detail="Attacking padlock",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False

    def test_using_in_inventory(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        hard.player.inventory.append("rusty_key")
        action = InteractAction(
            action_type="interact", target="padlock",
            interaction_id="unlock_padlock",
            using="rusty_key",
            detail="Unlocking the padlock",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.flags_set.get("padlock_unlocked") is True

    def test_unlock_without_key_fails(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        action = InteractAction(
            action_type="interact", target="padlock",
            interaction_id="unlock_padlock",
            detail="Trying to unlock",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False

    def test_interact_target_not_found(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        action = InteractAction(
            action_type="interact", target="nonexistent",
            interaction_id="search",
            detail="Searching",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False


class TestResolveAction:
    def test_dispatches_correctly(self, state_manager):
        action = WaitAction(action_type="wait", detail="Waiting")
        result = resolve_action(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.room_after_id == "axe_head"

    def test_unknown_action_type(self, state_manager):
        class UnknownAction:
            action_type = "unknown"
        result = resolve_action(UnknownAction(), state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False


class TestApplyResult:
    def test_adjust_attitude_applies_delta(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        from mgmai.models.actions import HardStateChanges
        from mgmai.models.corpus import Result

        result = Result(adjust_attitude={"korbar": 2})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert changes.entity_state_changes["korbar"]["attitude"] == 2
        assert hard.entity_states["korbar"]["attitude"] == 2

    def test_adjust_attitude_clamps_to_limits(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 9
        from mgmai.models.actions import HardStateChanges
        from mgmai.models.corpus import Result

        result = Result(adjust_attitude={"korbar": 5})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert changes.entity_state_changes["korbar"]["attitude"] == 10
        assert hard.entity_states["korbar"]["attitude"] == 10  # clamped to max

    def test_adjust_attitude_respects_step_per_turn(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.entity_states["korbar"]["attitude"] = 0
        from mgmai.models.actions import HardStateChanges
        from mgmai.models.corpus import Result

        result = Result(adjust_attitude={"korbar": 10})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert changes.entity_state_changes["korbar"]["attitude"] == 3
        assert hard.entity_states["korbar"]["attitude"] == 3  # clamped to step_per_turn


class TestResolveTalkDialoguePaths:
    def test_dialogue_path_not_found(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Test",
            detail="Testing",
            dialogue_path="nonexistent",
        )
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is False
        assert "not found" in result.error

    def test_dialogue_path_condition_not_met(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from mgmai.models.corpus import DialoguePath, ConditionExpression

        path = DialoguePath(
            description="Test path with an impossible condition.",
            condition=ConditionExpression.model_validate({"require": "flag:impossible_flag == true"})
        )
        corpus.entities["korbar"].dialogue_guidelines.dialogue_paths["test_path"] = path
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Test",
            detail="Testing",
            dialogue_path="test_path",
        )
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is False
        assert "Conditions not met" in result.error

    def test_dialogue_path_result_applied(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from mgmai.models.corpus import DialoguePath, Result

        path = DialoguePath(
            description="Compliment Korbar on her armor.",
            result=Result(
                narrative="Korbar seems pleased.",
                adjust_attitude={"korbar": 1},
            )
        )
        corpus.entities["korbar"].dialogue_guidelines.dialogue_paths["compliment"] = path
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Nice armor!",
            detail="Complimenting Korbar",
            dialogue_path="compliment",
        )
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.entity_state_changes["korbar"]["attitude"] == 1
        assert "pleased" in result.triggered_narration[0]

    def test_plain_talk_no_path(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Hello there",
            detail="Greeting Korbar",
        )
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is True
        assert not result.hard_changes.has_changes()


class TestResolveTransferTakeCheck:
    def test_take_check_success_adds_item(self, state_manager, monkeypatch):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        key = corpus.entities["rusty_key"]
        key.take_check = TakeCheck(
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(narrative="You pry the key loose."),
            failure=Result(narrative="The key slips from your grasp."),
        )
        monkeypatch.setattr("random.random", lambda: 0.1)
        action = TransferAction(
            action_type="transfer",
            target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert "rusty_key" in result.hard_changes.inventory_added
        assert result.rolls[0]["success"] is True
        assert "You pry the key loose." in result.triggered_narration

    def test_take_check_failure_does_not_add_item(self, state_manager, monkeypatch):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        key = corpus.entities["rusty_key"]
        key.take_check = TakeCheck(
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(narrative="You pry the key loose."),
            failure=Result(narrative="The key slips from your grasp."),
        )
        monkeypatch.setattr("random.random", lambda: 0.9)
        action = TransferAction(
            action_type="transfer",
            target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert "rusty_key" not in result.hard_changes.inventory_added
        assert result.rolls[0]["success"] is False
        assert "The key slips from your grasp." in result.triggered_narration

    def test_take_check_emits_check_event(self, state_manager, monkeypatch):
        """Item 2: take_checks emit check.passed/check.failed with source_type 'take'."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        key = corpus.entities["rusty_key"]
        key.take_check = TakeCheck(
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(narrative="You pry the key loose."),
            failure=Result(narrative="The key slips from your grasp."),
        )
        monkeypatch.setattr("random.random", lambda: 0.1)
        action = TransferAction(
            action_type="transfer",
            target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus, state_manager)
        assert result.success is True
        check_events = [ev for ev in result.events if ev[0] == "check.passed"]
        assert len(check_events) == 1
        assert check_events[0][1]["source_type"] == "take"
        assert check_events[0][1]["source_id"] == "take_rusty_key"

    def test_take_check_failure_emits_check_failed(self, state_manager, monkeypatch):
        """Item 2: a failed take_check emits check.failed with source_type 'take'."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        key = corpus.entities["rusty_key"]
        key.take_check = TakeCheck(
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(narrative="You pry the key loose."),
            failure=Result(narrative="The key slips from your grasp."),
        )
        monkeypatch.setattr("random.random", lambda: 0.9)
        action = TransferAction(
            action_type="transfer",
            target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus, state_manager)
        assert result.success is True
        failed = [ev for ev in result.events if ev[0] == "check.failed"]
        assert len(failed) == 1
        assert failed[0][1]["source_type"] == "take"

