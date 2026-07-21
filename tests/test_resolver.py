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
import random
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
    _apply_result_with_check,
)
from mgmai.engine.conditions import evaluate_condition_string
from mgmai.models.actions import (
    MoveAction,
    ExamineAction,
    InteractAction,
    TalkAction,
    TransferAction,
    WaitAction,
    OocDiscussionAction,
    EquipAction,
    HardStateChanges,
)
from mgmai.models.corpus import (
    CheckResolution,
    ConditionExpression,
    Exit,
    GameOverTrigger,
    GatedCheck,
    Interaction,
    Result,
    RollCheck,
    StatCheck,
    StatModifier,
)
from mgmai.state.manager import StateManager
from tests.helpers import (
    build_state_manager,
    make_char_sheet_corpus,
    make_char_sheet_state,
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
        assert result.success is True
        assert len(result.soft_item_proposals) == 1
        assert result.soft_item_proposals[0].item_name == "nonexistent"
        assert result.soft_item_proposals[0].action == "examine"

    def test_examine_with_using_not_in_inventory(self, state_manager):
        action = ExamineAction(action_type="examine", target="padlock", using="rusty_key", detail="Poking with key")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is False
        assert "not in your inventory" in (result.error or "")

    def test_examine_with_using_in_inventory(self, state_manager):
        state_manager.hard_state.player.inventory["rusty_key"] = 1
        action = ExamineAction(action_type="examine", target="padlock", using="rusty_key", detail="Poking with key")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True

    def test_examine_soft_item(self, state_manager):
        action = ExamineAction(action_type="examine", target="loose stone", detail="Looking at stone")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True

    def test_examine_soft_item_surfaces_on_room(self, state_manager):
        """Soft items belonging to the room are proposed for adjudication on the room ID."""
        action = ExamineAction(action_type="examine", target="loose stone", detail="Looking at stone")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "loose stone"
        assert proposal.action == "examine"
        assert proposal.source_id == "axe_head"

    def test_examine_soft_item_surfaces_on_entity(self, state_manager):
        """Soft items exclusive to an entity are proposed with the current room as source."""
        state_manager.hard_state.player.location = "bag_floor"
        action = ExamineAction(action_type="examine", target="stale sandwich", detail="Looking at sandwich")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "stale sandwich"
        assert proposal.action == "examine"
        assert proposal.source_id == "bag_floor"

    def test_examine_room_soft_item_surfaces_on_room(self, state_manager):
        """Soft items listed on the room surface as proposals on the room ID."""
        state_manager.hard_state.player.location = "axe_handle_lower"
        action = ExamineAction(action_type="examine", target="rock", detail="Looking at rock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "rock"
        assert proposal.action == "examine"
        assert proposal.source_id == "axe_handle_lower"

    def test_examine_soft_item_surfaces_on_room_when_shared(self, state_manager):
        """When a soft item exists on both room and entity, room wins."""
        state_manager.hard_state.player.location = "axe_handle_upper"
        action = ExamineAction(action_type="examine", target="sticky webbing", detail="Looking at webbing")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "sticky webbing"
        assert proposal.action == "examine"
        assert proposal.source_id == "axe_handle_upper"

    def test_examine_non_soft_item_no_surfacing(self, state_manager):
        """Examining an entity (not a soft item) does not populate soft-item proposals."""
        action = ExamineAction(action_type="examine", target="padlock", detail="Looking at padlock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {}

    def test_non_rigorous_examine_costs_no_turn(self, state_manager):
        """A default (non-rigorous) examine does not cost a turn."""
        action = ExamineAction(action_type="examine", target="padlock", detail="Looking at padlock")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.costs_turn is False

    def test_rigorous_examine_costs_turn(self, state_manager):
        """A rigorous examine costs a turn."""
        action = ExamineAction(
            action_type="examine", target="padlock", rigorous=True, detail="Searching padlock"
        )
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.costs_turn is True

    def test_failed_examine_costs_no_turn(self, state_manager):
        """A non-rigorous examine of an unknown target costs no turn."""
        action = ExamineAction(action_type="examine", target="nonexistent", detail="Looking")
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.costs_turn is False

    def test_rigorous_examine_of_unknown_costs_turn(self, state_manager):
        """A rigorous examine of an unknown target costs a turn and produces a proposal."""
        action = ExamineAction(
            action_type="examine", target="nonexistent", rigorous=True, detail="Searching"
        )
        result = resolve_examine(action, state_manager.hard_state, state_manager.soft_state, state_manager.corpus)
        assert result.success is True
        assert result.costs_turn is True
        assert len(result.soft_item_proposals) == 1
        assert result.soft_item_proposals[0].item_name == "nonexistent"


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

    def test_traversal_roll_dict_has_unified_keys(self, state_manager, monkeypatch):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        corpus.rooms["axe_head"].exits.append(
            Exit(
                id="exit_test_unified",
                direction="A test exit",
                target_room="axe_handle_upper",
                traversal_check=GatedCheck(
                    check=RollCheck(threshold=0.5, repeatable=True),
                    failure=Result(narrative="You cannot pass."),
                ),
            )
        )
        monkeypatch.setattr("random.random", lambda: 0.9)
        action = MoveAction(
            action_type="move", target="exit_test_unified", detail="Trying exit"
        )
        result = resolve_move(action, hard, state_manager.soft_state, corpus)
        assert result.hard_changes.player_location is None
        assert "You cannot pass." in result.triggered_narration
        assert len(result.rolls) == 1
        roll = result.rolls[0]
        assert roll["source_id"] == "exit_test_unified"
        assert roll["source_type"] == "traversal"
        assert roll["check_type"] == "roll"
        assert "traversal_check" in roll

    def test_traversal_gating_first_precedence(self, state_manager, monkeypatch):
        """When gating is false and skip_check_if is true, the check is inactive
        (gating-first), so success is not applied and traversal proceeds."""
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        hard.flags["gate_open"] = False
        hard.flags["skip_ready"] = True
        corpus.rooms["axe_head"].exits.append(
            Exit(
                id="exit_gating_first",
                direction="A gated exit",
                target_room="axe_handle_upper",
                traversal_check=GatedCheck(
                    gating=ConditionExpression(require="flag:gate_open == true"),
                    skip_check_if=ConditionExpression(require="flag:skip_ready == true"),
                    check=RollCheck(threshold=0.5, repeatable=True),
                    success=Result(narrative="Success branch applied."),
                    failure=Result(narrative="Failure branch applied."),
                ),
            )
        )
        monkeypatch.setattr("random.random", lambda: 0.9)
        action = MoveAction(
            action_type="move", target="exit_gating_first", detail="Trying gated exit"
        )
        result = resolve_move(action, hard, state_manager.soft_state, corpus)
        assert result.success is True
        assert result.hard_changes.player_location == "axe_handle_upper"
        assert "Success branch applied." not in result.triggered_narration
        assert "Failure branch applied." not in result.triggered_narration
        assert len(result.rolls) == 0


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
        hard.player.inventory["toenail_sword"] = 1
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_items=["toenail_sword"],
            detail="Giving sword to Korbar",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_removed.get("toenail_sword") == 1

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
        assert result.hard_changes.inventory_added.get("rusty_key") == 1

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
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "cork"
        assert proposal.action == "give"
        assert proposal.source_id == "player"
        assert proposal.target_id == "korbar"
        assert proposal.count == 1

    def test_give_soft_item_surfaces_on_target(self, state_manager):
        """Given soft items are proposed for adjudication on the transfer target."""
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
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "cork"
        assert proposal.action == "give"
        assert proposal.source_id == "player"
        assert proposal.target_id == "korbar"

    def test_take_soft_item_surfaces_on_entity_source(self, state_manager):
        """Taken soft items exclusive to an entity are proposed on that entity."""
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
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "stale sandwich"
        assert proposal.action == "take"
        assert proposal.source_id == "rubbish_pile"

    def test_take_soft_item_surfaces_on_entity_when_shared(self, state_manager):
        """When target is an entity, soft items are proposed on that entity."""
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
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "cork"
        assert proposal.action == "take"
        assert proposal.source_id == "rubbish_pile"

    def test_take_soft_item_surfaces_on_room_when_target_is_room(self, state_manager):
        """When transfer target is the room itself, propose on the room."""
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
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "cork"
        assert proposal.action == "take"
        assert proposal.source_id == "bag_floor"


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
        assert result.hard_changes.inventory_added.get("rusty_key") == 1

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

    def test_attack_dead_npc_without_aggro_returns_error(self, state_manager):
        """A dead stat-blocked NPC without aggro is rejected before combat entry."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_handle_lower"
        hard.entity_states["spider"]["alive"] = False
        action = InteractAction(
            action_type="interact", target="spider",
            interaction_id="attack",
            detail="Attacking dead spider",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False
        assert "dead" in result.error.lower()

    def test_attack_on_combat_group_member_pulls_band(self, state_manager):
        """Direct attack on a combat_group member enters combat with the band."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        # Give korbar and spider combat blocks and a shared combat_group.
        from mgmai.models.corpus import CombatBlock
        corpus.entities["korbar"].combat = CombatBlock(hp=10, ac=10, atk=2, dmg="1d6")
        corpus.entities["korbar"].combat_group = "bad_guys"
        corpus.entities["spider"].combat = CombatBlock(hp=15, ac=14, atk=5, dmg="1d4+3")
        corpus.entities["spider"].combat_group = "bad_guys"
        # Move spider to bag_floor for the test.
        hard.room_contains["bag_floor"]["spider"] = 1
        hard.entity_states["spider"] = {"alive": True, "current_hp": 15, "attitude": -5}
        hard.entity_states["korbar"]["current_hp"] = 10
        action = InteractAction(
            action_type="interact", target="korbar",
            interaction_id="attack",
            detail="Attacking Korbar",
        )
        result = resolve_interact(action, hard, soft, corpus, state_manager)
        assert result.combat_triggered is True
        assert hard.combat is not None
        assert "korbar" in hard.combat.combatants
        assert "spider" in hard.combat.combatants

    def test_using_in_inventory(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        hard.player.inventory["rusty_key"] = 1
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

    def test_non_repeatable_interaction_returns_error_on_second_attempt(
        self, state_manager, monkeypatch
    ):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        monkeypatch.setattr("random.random", lambda: 0.1)
        corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="once_only",
                description="Test: non-repeatable check",
                check=RollCheck(threshold=0.5, repeatable=False),
                success=Result(narrative="Done."),
                failure=Result(narrative="Failed."),
            )
        )
        action = InteractAction(
            action_type="interact", target="padlock",
            interaction_id="once_only",
            detail="Try once",
        )
        first = resolve_interact(action, hard, soft, corpus)
        assert first.success is True
        second = resolve_interact(action, hard, soft, corpus)
        assert second.success is False
        assert "already been attempted" in (second.error or "")

    def test_stat_check_without_stats_returns_error(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        hard.player.stats = None
        corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="stat_gate",
                description="Test: stat check without stats",
                check=StatCheck(stat="STR", target=10, repeatable=True),
                success=Result(narrative="Passed."),
                failure=Result(narrative="Failed."),
            )
        )
        action = InteractAction(
            action_type="interact", target="padlock",
            interaction_id="stat_gate",
            detail="Try stat gate",
        )
        result = resolve_interact(action, hard, soft, corpus)
        assert result.success is False
        assert "stat" in (result.error or "").lower()


class TestSkillChecks:
    """Skill stat checks (e.g. "stat": "acrobatics") via the resolver."""

    def _manager_with_skills(self, skills):
        corpus = make_char_sheet_corpus()
        manager = build_state_manager(corpus, hard_state=make_char_sheet_state())
        manager.hard_state.room_contains["axe_head"] = {"toenail_sword": 1}
        manager.hard_state.player.skill_proficiencies = skills
        return manager

    def _add_acrobatics_interaction(self, corpus, target=12):
        corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="tumble",
                description="Test: acrobatics check",
                check=StatCheck(stat="acrobatics", target=target, repeatable=True),
                success=Result(narrative="You tumble through."),
                failure=Result(narrative="You stumble."),
            )
        )

    def _interact(self, manager):
        action = InteractAction(
            action_type="interact", target="toenail_sword",
            interaction_id="tumble",
            detail="Tumble past",
        )
        return resolve_interact(
            action, manager.hard_state, manager.soft_state, manager.corpus
        )

    def test_skill_check_proficient_succeeds(self, monkeypatch):
        manager = self._manager_with_skills(["acrobatics"])
        self._add_acrobatics_interaction(manager.corpus, target=12)
        # DEX 10 -> +0, proficiency +2; roll 10 -> total 12 >= 12
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        result = self._interact(manager)
        assert result.success is True
        roll = result.rolls[0]
        assert roll["stat"] == "acrobatics"
        assert roll["computed_mod"] == 0
        assert roll["flat_mod"] == 2
        assert roll["total"] == 12

    def test_skill_check_not_proficient_fails(self, monkeypatch):
        manager = self._manager_with_skills([])
        self._add_acrobatics_interaction(manager.corpus, target=12)
        # No proficiency: roll 10 + 0 = 10 < 12
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        result = self._interact(manager)
        roll = result.rolls[0]
        assert roll["stat"] == "acrobatics"
        assert roll["flat_mod"] == 0
        assert roll["total"] == 10
        assert roll["success"] is False
        assert "You stumble." in result.triggered_narration

    def test_skill_check_case_insensitive(self, monkeypatch):
        manager = self._manager_with_skills(["Acrobatics"])
        self._add_acrobatics_interaction(manager.corpus, target=12)
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        result = self._interact(manager)
        assert result.success is True
        assert result.rolls[0]["flat_mod"] == 2

    def test_unknown_stat_key_errors(self):
        manager = self._manager_with_skills([])
        manager.corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="luck_check",
                description="Test: unknown stat",
                check=StatCheck(stat="luck", target=10, repeatable=True),
                success=Result(narrative="Lucky."),
                failure=Result(narrative="Unlucky."),
            )
        )
        action = InteractAction(
            action_type="interact", target="toenail_sword",
            interaction_id="luck_check",
            detail="Push luck",
        )
        result = resolve_interact(
            action, manager.hard_state, manager.soft_state, manager.corpus
        )
        assert result.success is False
        assert "luck" in (result.error or "")

    def test_traversal_skill_check(self, monkeypatch):
        corpus = make_char_sheet_corpus()
        manager = build_state_manager(corpus, hard_state=make_char_sheet_state())
        manager.hard_state.player.skill_proficiencies = ["acrobatics"]
        corpus.rooms["axe_head"].exits.append(
            Exit(
                id="exit_tumble",
                direction="A narrow ledge",
                target_room="bag_floor",
                traversal_check=GatedCheck(
                    check=StatCheck(stat="acrobatics", target=12, repeatable=True),
                    failure=Result(narrative="You cannot cross."),
                ),
            )
        )
        # Proficient: 10 + 0 + 2 = 12 >= 12 -> traverse
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        action = MoveAction(action_type="move", target="exit_tumble", detail="Cross")
        result = resolve_move(
            action, manager.hard_state, manager.soft_state, corpus
        )
        assert result.hard_changes.player_location == "bag_floor"
        roll = result.rolls[0]
        assert roll["check_type"] == "stat_check"
        assert roll["stat"] == "acrobatics"
        assert roll["flat_mod"] == 2

    def test_traversal_unknown_stat_passes(self, monkeypatch):
        corpus = make_char_sheet_corpus()
        manager = build_state_manager(corpus, hard_state=make_char_sheet_state())
        corpus.rooms["axe_head"].exits.append(
            Exit(
                id="exit_luck",
                direction="A strange exit",
                target_room="bag_floor",
                traversal_check=GatedCheck(
                    check=StatCheck(stat="luck", target=30, repeatable=True),
                    failure=Result(narrative="You cannot pass."),
                ),
            )
        )
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        action = MoveAction(action_type="move", target="exit_luck", detail="Go")
        result = resolve_move(
            action, manager.hard_state, manager.soft_state, corpus
        )
        # Unknown stat keys are skipped (legacy behavior): traversal proceeds.
        assert result.hard_changes.player_location == "bag_floor"
        assert len(result.rolls) == 0

    def test_status_effect_disadvantage_applies_to_checks(self, monkeypatch):
        manager = self._manager_with_skills(["acrobatics"])
        manager.hard_state.player.status_effects = {"poisoned": 2}
        self._add_acrobatics_interaction(manager.corpus, target=12)
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        result = self._interact(manager)
        roll = result.rolls[0]
        assert roll["stat"] == "acrobatics"
        assert roll["disadvantage"] is True
        assert roll["advantage"] is False

    def test_status_effect_disadvantage_skips_saves(self, monkeypatch):
        manager = self._manager_with_skills([])
        manager.hard_state.player.status_effects = {"poisoned": 2}
        manager.corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="resist_toxin",
                description="Test: CON save",
                check=StatCheck(stat="CON", target=12, save=True, repeatable=True),
                success=Result(narrative="You resist."),
                failure=Result(narrative="It courses through you."),
            )
        )
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        action = InteractAction(
            action_type="interact", target="toenail_sword",
            interaction_id="resist_toxin",
            detail="Resist",
        )
        result = resolve_interact(
            action, manager.hard_state, manager.soft_state, manager.corpus
        )
        roll = result.rolls[0]
        assert roll["disadvantage"] is False
        assert roll["advantage"] is False

    def test_authored_advantage_and_status_disadvantage_cancel(self, monkeypatch):
        manager = self._manager_with_skills([])
        manager.hard_state.player.status_effects = {"poisoned": 2}
        manager.corpus.rooms["axe_head"].interactions.append(
            Interaction(
                id="lift",
                description="Test: authored advantage",
                check=StatCheck(
                    stat="STR", target=12, repeatable=True, advantage=True,
                ),
                success=Result(narrative="Lifted."),
                failure=Result(narrative="Too heavy."),
            )
        )
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        action = InteractAction(
            action_type="interact", target="toenail_sword",
            interaction_id="lift",
            detail="Lift",
        )
        result = resolve_interact(
            action, manager.hard_state, manager.soft_state, manager.corpus
        )
        roll = result.rolls[0]
        assert roll["advantage"] is True
        assert roll["disadvantage"] is True


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

    def test_set_player_location_applied(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges
        from mgmai.models.corpus import Result

        result = Result(set_player_location="bag_floor")
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert changes.player_location == "bag_floor"
        assert hard.player.location == "bag_floor"

    def test_apply_result_with_start_combat_no_crash(self, state_manager):
        """A Result with start_combat set flows through _apply_result safely."""
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges

        result = Result(narrative="Hello", start_combat=[])
        changes = HardStateChanges()
        narrative: list[str] = []
        _apply_result(result, changes, narrative, [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert narrative == ["Hello"]

    def test_apply_result_with_game_over_no_crash(self, state_manager):
        """A Result with game_over set propagates to hard state via _apply_result."""
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges

        result = Result(
            narrative="You die.",
            game_over=GameOverTrigger(type="lose", trigger_id="test"),
        )
        changes = HardStateChanges()
        narrative: list[str] = []
        _apply_result(result, changes, narrative, [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert narrative == ["You die."]
        assert changes.player_hp_delta is None  # game_over didn't leak into state
        assert hard.game_over is not None
        assert hard.game_over.type == "lose"
        assert hard.game_over.trigger == "test"

    def test_apply_result_with_both_dispatch_fields_no_crash(self, state_manager):
        """A Result with both start_combat and game_over combined with effects."""
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges

        result = Result(
            narrative="Combat and death!",
            start_combat=[],
            game_over=GameOverTrigger(type="lose", trigger_id="boss"),
            set_flag={"boss_defeated": True},
        )
        changes = HardStateChanges()
        narrative: list[str] = []
        _apply_result(result, changes, narrative, [], hard, corpus)
        state_manager.apply_hard_changes(changes)
        assert narrative == ["Combat and death!"]
        assert changes.flags_set.get("boss_defeated") is True
        assert changes.player_hp_delta is None
        assert hard.game_over is not None
        assert hard.game_over.type == "lose"
        assert hard.game_over.trigger == "boss"

    def test_apply_result_with_check_with_start_combat_no_crash(self, state_manager):
        """_apply_result_with_check handles Result with start_combat set."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges

        result = Result(narrative="Done.", start_combat=[])
        changes = HardStateChanges()
        narrative: list[str] = []
        rolls: list[dict] = []
        _apply_result_with_check(
            result,
            changes=changes, narrative=narrative,
            revealed_hints=[], hard=hard, corpus=corpus,
            soft=soft, room_id=hard.player.location or "start",
            rolls=rolls,
        )
        assert narrative == ["Done."]

    def test_apply_result_with_check_with_game_over_no_crash(self, state_manager):
        """_apply_result_with_check propagates a Result's game_over to hard state."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.models.actions import HardStateChanges

        result = Result(
            narrative="Game over.",
            game_over=GameOverTrigger(type="win", trigger_id="escape"),
        )
        changes = HardStateChanges()
        narrative: list[str] = []
        rolls: list[dict] = []
        _apply_result_with_check(
            result,
            changes=changes, narrative=narrative,
            revealed_hints=[], hard=hard, corpus=corpus,
            soft=soft, room_id=hard.player.location or "start",
            rolls=rolls,
        )
        assert narrative == ["Game over."]
        assert hard.game_over is not None
        assert hard.game_over.type == "win"
        assert hard.game_over.trigger == "escape"


class TestResolveTalkPaths:
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
        corpus = state_manager.corpus.model_copy(deep=True)
        hard.player.location = "bag_floor"
        from mgmai.models.corpus import Resolvable, ConditionExpression

        path = Resolvable(
            description="Test path with an impossible condition.",
            condition=ConditionExpression.model_validate({"require": "flag:impossible_flag == true"}),
            result=Result(narrative="Should not happen."),
        )
        path.id = "test_path"
        corpus.entities["korbar"].dialogue.dialogue_paths["test_path"] = path
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
        from mgmai.models.corpus import Resolvable, Result

        path = Resolvable(
            description="Compliment Korbar on her armor.",
            result=Result(
                narrative="Korbar seems pleased.",
                adjust_attitude={"korbar": 1},
            )
        )
        corpus.entities["korbar"].dialogue.dialogue_paths["compliment"] = path
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


class TestResolveTransferTake:
    def test_take_check_success_adds_item(self, state_manager, monkeypatch):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        key = corpus.entities["rusty_key"]
        key.take_check = GatedCheck(
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
        key.take_check = GatedCheck(
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
        key.take_check = GatedCheck(
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
        key.take_check = GatedCheck(
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

    def test_take_check_skip_check_if_fires_then_check(self, state_manager):
        """A GatedCheck take_check whose skip_check_if bypasses the check still
        resolves success.then_check and emits the check event with source_type 'take'."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        hard.flags["skip_take"] = True
        key = corpus.entities["rusty_key"]
        key.take_check = GatedCheck(
            skip_check_if=ConditionExpression(require="flag:skip_take == true"),
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(
                narrative="You lift the key effortlessly.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(set_flag={"skip_then_check_fired": True}),
                ),
            ),
            failure=Result(narrative="The key slips from your grasp."),
        )
        action = TransferAction(
            action_type="transfer",
            target="secret_compartment",
            taken_items=["rusty_key"],
            detail="Taking the rusty key",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.flags_set.get("skip_then_check_fired") is True
        assert "source_id" in result.rolls[0]
        assert result.rolls[0]["source_type"] == "take"

    def test_take_check_gating_first_precedence(self, state_manager, monkeypatch):
        """When gating is false and skip_check_if is true, the take check is
        inactive (gating-first), so success is not applied and the item is taken."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        hard.flags["take_gate_open"] = False
        hard.flags["take_skip_ready"] = True
        key = corpus.entities["rusty_key"]
        key.take_check = GatedCheck(
            gating=ConditionExpression(require="flag:take_gate_open == true"),
            skip_check_if=ConditionExpression(require="flag:take_skip_ready == true"),
            check=RollCheck(threshold=0.5, repeatable=True),
            success=Result(narrative="Success branch applied."),
            failure=Result(narrative="Failure branch applied."),
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
        assert "rusty_key" in result.hard_changes.inventory_added
        assert "Success branch applied." not in result.triggered_narration
        assert "Failure branch applied." not in result.triggered_narration
        assert len(result.rolls) == 0


class TestResolveTransferCounts:
    """Quantity-aware give/take behavior."""

    def test_take_300_coins(self, state_manager):
        """Taking a large stackable quantity records the full count."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        # Add a stackable coin entity to the room
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A shiny coin.", tags=["stackable"]
        )
        corpus.rooms["bag_floor"].contains.append("gold_coin")
        hard.room_contains.setdefault("bag_floor", {})["gold_coin"] = 300
        action = TransferAction(
            action_type="transfer", target="bag_floor",
            taken_counts={"gold_coin": 300},
            detail="Taking a pile of coins",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_added.get("gold_coin") == 300
        assert result.hard_changes.room_contains_removed.get("bag_floor", {}).get("gold_coin") == 300

    def test_give_300_coins_shortfall(self, state_manager):
        """Giving more than available fails without removing anything."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        hard.player.inventory["gold_coin"] = 100
        action = TransferAction(
            action_type="transfer", target="korbar",
            given_counts={"gold_coin": 300},
            detail="Giving more coins than owned",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False
        assert "Not enough" in (result.error or "")
        assert result.hard_changes.inventory_removed == {}

    def test_take_2_non_stackable_sword_rejected(self, state_manager):
        """Taking more than one non-stackable item is rejected."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "secret_compartment"
        action = TransferAction(
            action_type="transfer", target="secret_compartment",
            taken_counts={"rusty_key": 2},
            detail="Trying to take two rusty keys",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False
        assert "Cannot take 2 of non-stackable" in (result.error or "")

    def test_non_stackable_duplicate_add_skipped(self, state_manager):
        """_apply_result skips adding a duplicate non-stackable item."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.inventory["toenail_sword"] = 1
        from mgmai.engine.resolver import _apply_result
        result = Result(add_item=["toenail_sword"])
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard=hard, corpus=corpus)
        assert changes.inventory_added.get("toenail_sword") is None

    def test_remove_shortfall_skipped(self, state_manager):
        """_apply_result skips removing more than currently held."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.inventory["rusty_key"] = 1
        from mgmai.engine.resolver import _apply_result
        result = Result(remove_item_count={"rusty_key": 5})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard=hard, corpus=corpus)
        assert changes.inventory_removed.get("rusty_key") is None

    def test_equip_one_from_stack(self, state_manager):
        """Equipping removes only one copy from a stack."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.inventory["toenail_sword"] = 3
        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            detail="Equipping one sword",
        )
        from mgmai.engine.resolver import resolve_equip
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_removed.get("toenail_sword") == 1
        assert result.hard_changes.equipped_added == ["toenail_sword"]


class TestMoneyScenario:
    """End-to-end money/stackable scenario (plan item 39)."""

    def test_full_money_flow(self, state_manager):
        """Walk through the full stackable-item lifecycle."""
        from tests.helpers import _mk_item_entity

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        # Set up a stackable gold_coin entity in the room
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A shiny gold coin.", tags=["stackable"]
        )
        corpus.rooms["axe_head"].contains.append("gold_coin")
        hard.room_contains.setdefault("axe_head", {})["gold_coin"] = 300

        # Step 1: Start with 50 coins
        hard.player.inventory["gold_coin"] = 50

        # Step 2: Grant 30 via add_item_count → 80
        result = Result(add_item_count={"gold_coin": 30})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard=hard, corpus=corpus)
        state_manager.apply_hard_changes(changes)
        assert hard.player.inventory["gold_coin"] == 80

        # Step 3: Check conditions
        assert evaluate_condition_string("inventory:gold_coin >= 30", hard, soft, None)
        assert not evaluate_condition_string("inventory:gold_coin >= 81", hard, soft, None)
        assert evaluate_condition_string("inventory:gold_coin >= 80", hard, soft, None)

        # Step 4: Pick up 300 via taken_counts in one transfer → 380
        action = TransferAction(
            action_type="transfer", target="axe_head",
            taken_counts={"gold_coin": 300},
            detail="Picking up a pile of coins",
        )
        xfer_result = resolve_transfer(action, hard, soft, corpus)
        assert xfer_result.success is True
        state_manager.apply_hard_changes(xfer_result.hard_changes)
        assert hard.player.inventory["gold_coin"] == 380

        # Step 5: Spend 30 via remove_item_count → 350
        result = Result(remove_item_count={"gold_coin": 30})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard=hard, corpus=corpus)
        state_manager.apply_hard_changes(changes)
        assert hard.player.inventory["gold_coin"] == 350

        # Step 6: Spend 1000 → manager raises (shortfall)
        changes = HardStateChanges(inventory_removed={"gold_coin": 1000})
        with pytest.raises(ValueError, match="Cannot remove"):
            state_manager.apply_hard_changes(changes)
        # Inventory unchanged after failed apply
        assert hard.player.inventory["gold_coin"] == 350

        # Step 7: Resolver path skips on shortfall (fuzzy-LLM path)
        result = Result(remove_item_count={"gold_coin": 1000})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard=hard, corpus=corpus)
        # No removal recorded because count > current
        assert changes.inventory_removed.get("gold_coin") is None

        # Step 8: max_stack cap raises
        corpus.entities["gold_coin"].max_stack = 500
        hard.player.inventory["gold_coin"] = 400
        changes = HardStateChanges(inventory_added={"gold_coin": 200})
        with pytest.raises(ValueError, match="max_stack"):
            state_manager.apply_hard_changes(changes)


class TestResolveTransferContainment:
    """Take/give mutations update the runtime world containment maps."""

    def test_take_removes_from_room_contains(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.rooms["bag_floor"].contains.append("gold_coin")
        hard.room_contains.setdefault("bag_floor", {})["gold_coin"] = 50

        action = TransferAction(
            action_type="transfer", target="bag_floor",
            taken_counts={"gold_coin": 30},
            detail="Taking coins",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_added.get("gold_coin") == 30
        assert result.hard_changes.room_contains_removed.get("bag_floor", {}).get("gold_coin") == 30

    def test_take_more_than_available_fails(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.rooms["bag_floor"].contains.append("gold_coin")
        hard.room_contains.setdefault("bag_floor", {})["gold_coin"] = 50

        action = TransferAction(
            action_type="transfer", target="bag_floor",
            taken_counts={"gold_coin": 60},
            detail="Taking too many coins",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False
        assert "not available" in (result.error or "").lower()

    def test_give_adds_to_room_contains(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        hard.player.inventory["gold_coin"] = 100

        action = TransferAction(
            action_type="transfer", target="bag_floor",
            given_counts={"gold_coin": 40},
            detail="Dropping coins",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_removed.get("gold_coin") == 40
        assert result.hard_changes.room_contains_added.get("bag_floor", {}).get("gold_coin") == 40

    def test_give_to_entity_adds_to_entity_contains(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        hard.player.inventory["gold_coin"] = 100

        action = TransferAction(
            action_type="transfer", target="korbar",
            given_counts={"gold_coin": 25},
            detail="Giving coins to Korbar",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_removed.get("gold_coin") == 25
        assert result.hard_changes.entity_contains_added.get("korbar", {}).get("gold_coin") == 25

    def test_take_from_nested_container(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.entities["rubbish_pile"].contains = ["gold_coin"]
        hard.entity_contains["rubbish_pile"] = {"gold_coin": 15}

        action = TransferAction(
            action_type="transfer", target="bag_floor",
            taken_counts={"gold_coin": 10},
            detail="Taking coins from rubbish pile",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.inventory_added.get("gold_coin") == 10
        assert result.hard_changes.entity_contains_removed.get("rubbish_pile", {}).get("gold_coin") == 10


class TestResolveExamineWithStackedItems:
    """Regression: examine soft item in room that also has stacked items."""

    def test_examine_soft_item_with_stacked_room_item(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.rooms["axe_head"].contains.append("gold_coin")
        hard.room_contains.setdefault("axe_head", {})["gold_coin"] = 50

        action = ExamineAction(
            action_type="examine", target="loose stone", detail="Looking at stone"
        )
        result = resolve_examine(action, hard, soft, corpus)
        assert result.success is True
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.item_name == "loose stone"
        assert proposal.action == "examine"
        assert proposal.source_id == "axe_head"


class TestResolveTalkWithStackedItems:
    """Regression: talk to NPC in room with stacked items."""

    def test_talk_npc_with_stacked_room_item(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.rooms["bag_floor"].contains.append("gold_coin")
        hard.room_contains.setdefault("bag_floor", {})["gold_coin"] = 100

        action = TalkAction(
            action_type="talk", target="korbar", detail="Talking to Korbar"
        )
        result = resolve_talk(action, hard, soft, corpus)
        assert result.success is True


class TestResolveRoomChangeDialogueExit:
    """Regression: room-change dialogue exit with stacked items."""

    def test_room_change_exit_with_stacked_item(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        soft.dialogue_state.active_npc = "korbar"
        from tests.helpers import _mk_item_entity
        corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        corpus.rooms["axe_head"].contains.append("gold_coin")
        hard.room_contains.setdefault("axe_head", {})["gold_coin"] = 50

        from mgmai.engine.dialogue import check_room_change_exit
        result = check_room_change_exit(soft, "bag_floor", "axe_head", corpus, hard)
        # Korbar is not in axe_head, so dialogue should exit.
        assert result is not None
        assert result["npc_id"] == "korbar"



class TestSoftContentRetrieval:
    """resolve_transfer consults soft_contents before ambient proposals."""

    def test_mechanical_retrieval_from_feature(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_contents["rubbish_pile"] = {"stone": 1}
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            taken_items=["stone"], detail="Taking the stone back",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {"rubbish_pile": {"stone": 1}}
        # Applying the retrieval to state is the engine's job.
        assert soft.soft_contents == {"rubbish_pile": {"stone": 1}}
        assert soft.soft_inventory == []

    def test_multi_count_retrieval_fully_mechanical(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_contents["rubbish_pile"] = {"stone": 3}
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            taken_counts={"stone": 2}, detail="Taking two stones",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {"rubbish_pile": {"stone": 2}}

    def test_multi_count_ambient_take_not_blocked(self, state_manager):
        """Soft names are exempt from the stackable guard: count-2 ambient
        takes reach the proposal stage."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            taken_counts={"cork": 2}, detail="Taking two corks",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_content_takes == {}
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        assert proposal.action == "take"
        assert proposal.source_id == "rubbish_pile"
        assert proposal.count == 2

    def test_room_targeted_take_finds_placed_item_on_entity(self, state_manager):
        """Ambiguous source: a room-targeted take searches entities in the room."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_contents["rubbish_pile"] = {"stone": 1}
        action = TransferAction(
            action_type="transfer", target="bag_floor",
            taken_items=["stone"], detail="Taking the stone",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {"rubbish_pile": {"stone": 1}}

    def test_retrieval_from_npc_defers_to_call2(self, state_manager):
        """NPC-held soft items need consent: proposal, not mechanical retrieval."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_contents["korbar"] = {"cork": 1}
        action = TransferAction(
            action_type="transfer", target="korbar",
            taken_items=["cork"], detail="Taking the cork back",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_content_takes == {}
        assert len(result.soft_item_proposals) == 1
        assert result.soft_item_proposals[0].source_id == "korbar"

    def test_retrieval_name_normalization(self, state_manager):
        """Stored keys are verbatim; lookup normalizes articles and case."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        soft.soft_contents["rubbish_pile"] = {"Stone": 1}
        action = TransferAction(
            action_type="transfer", target="rubbish_pile",
            taken_items=["the stone"], detail="Taking the stone",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {"rubbish_pile": {"Stone": 1}}

    def test_retrieval_from_closed_container_fails(self, state_manager):
        from tests.helpers import _mk_item_entity
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        chest = _mk_item_entity("chest", description="A wooden chest.", tags=["container"])
        chest.state_fields = {"open": {"type": "boolean", "description": "Open?"}}
        corpus.entities["chest"] = chest
        hard.room_contains["bag_floor"]["chest"] = 1
        hard.entity_states["chest"] = {"open": False}
        soft.soft_contents["chest"] = {"stone": 1}

        action = TransferAction(
            action_type="transfer", target="chest",
            taken_items=["stone"], detail="Taking the stone from the chest",
        )
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is False
        assert "closed" in result.error.lower()
        assert result.soft_content_takes == {}
        assert soft.soft_contents == {"chest": {"stone": 1}}

        # Once open, the same take succeeds mechanically.
        hard.entity_states["chest"]["open"] = True
        result = resolve_transfer(action, hard, soft, corpus)
        assert result.success is True
        assert result.soft_content_takes == {"chest": {"stone": 1}}
