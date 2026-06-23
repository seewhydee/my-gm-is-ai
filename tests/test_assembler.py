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

"""Tests for context/assembler.py — Context Assembler."""

import copy

import pytest

from mgmai.context.assembler import assemble
from mgmai.models.briefing import (
    BriefingContainedEntity,
    BriefingEntity,
    BriefingExit,
    BriefingHistoryEntry,
    BriefingInteraction,
    BriefingRoom,
    DialogueActiveNpc,
    DialogueContext,
    GMBriefing,
    PlayerStateBriefing,
)
from mgmai.engine.utils import build_contained_entities
from mgmai.models.soft_state import (
    ConversationLogEntry,
    DialogueState,
    KnowledgeEntry,
    TurnHistoryEntry,
)


class TestAssembleBasic:
    """Basic assembly from sample adventure data."""

    def test_returns_gm_briefing(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look around",
        )
        assert isinstance(result, GMBriefing)

    def test_adventure_metadata(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look around",
        )
        assert result.adventure_title == "You're Trapped in a Bag of Holding!"
        assert "Bag of Holding" in result.setting
        assert result.tone != ""

    def test_turn_count(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look around",
        )
        assert result.turn == 0

        state_manager.hard_state.turn_count = 5
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look around",
        )
        assert result.turn == 5

    def test_player_input_passthrough(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "I examine the padlock carefully",
        )
        assert result.player_input == "I examine the padlock carefully"

    def test_current_room_is_start_room(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.current_room.id == "axe_head"
        assert result.current_room.name == "Axe Head"


class TestEntityVisibility:
    """Entity filtering: dead entities omitted, state and notes included."""

    def test_entities_present_in_start_room(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        # axe_head has: battleaxe, canvas_walls, rip_in_canvas, padlock
        assert "battleaxe" in entity_ids
        assert "canvas_walls" in entity_ids
        assert "rip_in_canvas" in entity_ids
        assert "padlock" in entity_ids

    def test_dead_entity_still_visible(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.entity_states["korbar"]["alive"] = False
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        assert "korbar" in entity_ids

    def test_entity_state_included(self, state_manager):
        state_manager.hard_state.player.location = "axe_handle_lower"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        spider = next(
            e for e in result.current_room.entities_visible if e.id == "spider"
        )
        assert spider.state["alive"] is True
        assert spider.state["fled"] is False

    def test_entity_notes_included(self, state_manager):
        state_manager.soft_state.entity_notes["padlock"] = [
            "Scratched surface",
            "Rusty mechanism",
            "Recently oiled",
            "Very old",
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        padlock = next(
            e for e in result.current_room.entities_visible if e.id == "padlock"
        )
        # Capped at 5 most recent (all 4 fit)
        assert padlock.entity_notes == [
            "Scratched surface",
            "Rusty mechanism",
            "Recently oiled",
            "Very old",
        ]

    def test_entity_soft_items_no_longer_populated(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        rubbish = next(
            e for e in result.current_room.entities_visible if e.id == "rubbish_pile"
        )
        assert rubbish.soft_items == []

    def test_entity_type_included(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        korbar = next(
            e for e in result.current_room.entities_visible if e.id == "korbar"
        )
        assert korbar.type == "npc"

    def test_dialogue_paths_included_for_npc(self, state_manager):
        from mgmai.models.corpus import DialoguePath, Result
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.corpus.entities["korbar"].dialogue_guidelines.dialogue_paths[
            "test_path"
        ] = DialoguePath(
            description="Test path description for the assembler.",
            result=Result(narrative="Test"),
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        korbar = next(
            e for e in result.current_room.entities_visible if e.id == "korbar"
        )
        assert korbar.dialogue_paths == {
            "test_path": "Test path description for the assembler."
        }

    def test_dialogue_paths_empty_for_non_npc(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        handkerchief = next(
            e for e in result.current_room.entities_visible if e.id == "handkerchief"
        )
        assert handkerchief.dialogue_paths == {}


class TestEntityHidden:
    """Hidden entity filtering: entities with `hidden: true` are omitted."""

    def test_hidden_entity_filtered_from_entities_visible(self, state_manager):
        state_manager.hard_state.player.location = "axe_handle_lower"
        state_manager.hard_state.entity_states["spider"]["hidden"] = True
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        assert "spider" not in entity_ids

    def test_hidden_entity_appears_when_revealed(self, state_manager):
        state_manager.hard_state.player.location = "axe_handle_lower"
        # Entity starts hidden, then is revealed
        state_manager.hard_state.entity_states["spider"]["hidden"] = False
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        assert "spider" in entity_ids

    def test_entity_without_hidden_field_always_visible(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        # korbar has no 'hidden' state field — should always be visible
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        assert "korbar" in entity_ids


class TestExitFiltering:
    """Exit filtering: hidden omitted, conditions checked."""

    def test_visible_exits_in_start_room(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        exit_ids = [e.id for e in result.current_room.exits_available]
        assert "exit_climb_down_handle" in exit_ids
        assert "exit_drop_from_head" in exit_ids

    def test_hidden_exit_omitted(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        exit_ids = [e.id for e in result.current_room.exits_available]
        # secret compartment exit is hidden
        assert "exit_enter_secret_flap" not in exit_ids

    def test_condition_gated_exit_included_when_met(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.flags["handkerchief_moved"] = True
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        exit_ids = [e.id for e in result.current_room.exits_available]
        # Hidden exit appears in briefing once its conditions are met
        assert "exit_enter_secret_flap" in exit_ids

    def test_condition_gated_exit_omitted_when_not_met(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.flags["handkerchief_moved"] = False
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        exit_ids = [e.id for e in result.current_room.exits_available]
        assert "exit_enter_secret_flap" not in exit_ids

    def test_exit_fields_populated(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        exit = next(
            e for e in result.current_room.exits_available if e.id == "exit_climb_down_handle"
        )
        assert exit.direction == "Climb carefully down the axe handle"
        assert exit.target_room == "axe_handle_upper"
        assert exit.hidden is False


class TestInteractions:
    """Interaction filtering by condition."""

    def test_no_condition_always_available(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        inter_ids = [i.id for i in result.current_room.interactions_available]
        # rummage_for_weapon has a condition (unless injured)
        assert "rummage_for_weapon" in inter_ids

    def test_condition_gated_interaction_excluded(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.flags["injured"] = True
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        inter_ids = [i.id for i in result.current_room.interactions_available]
        assert "rummage_for_weapon" not in inter_ids

    def test_interaction_fields_populated(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        inter = next(
            i for i in result.current_room.interactions_available if i.id == "rummage_for_weapon"
        )
        assert inter.label == "Rummage for a weapon"
        assert inter.description is not None


class TestRoomSoftItemsAndNotes:
    """Room-level soft items and room notes."""

    def test_room_soft_items_no_longer_populated(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.current_room.soft_items == []

    def test_surfaced_room_soft_items_appear(self, state_manager):
        state_manager.soft_state.surfaced_soft_items["axe_head"] = ["loose stone"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.current_room.soft_items == ["loose stone"]

    def test_surfaced_entity_soft_items_appear(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.soft_state.surfaced_soft_items["rubbish_pile"] = ["cork", "lint"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        rubbish = next(
            e for e in result.current_room.entities_visible if e.id == "rubbish_pile"
        )
        assert rubbish.soft_items == ["cork", "lint"]

    def test_surfaced_entity_soft_items_no_longer_empty(self, state_manager):
        """The 'no longer populated' test should now show surfaced items instead."""
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.soft_state.surfaced_soft_items["rubbish_pile"] = ["cork"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        rubbish = next(
            e for e in result.current_room.entities_visible if e.id == "rubbish_pile"
        )
        assert rubbish.soft_items == ["cork"]
        assert rubbish.soft_items != []

    def test_room_notes_included(self, state_manager):
        state_manager.soft_state.room_notes["axe_head"] = [
            "Scratches on the blade",
            "Dust disturbed recently",
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.current_room.room_notes == [
            "Scratches on the blade",
            "Dust disturbed recently",
        ]

    def test_room_notes_capped_at_5(self, state_manager):
        state_manager.soft_state.room_notes["axe_head"] = [
            "note1", "note2", "note3", "note4", "note5", "note6",
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert len(result.current_room.room_notes) == 5
        assert result.current_room.room_notes == [
            "note2", "note3", "note4", "note5", "note6",
        ]


class TestPlayerState:
    """Player state assembly."""

    def test_location(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.location == "axe_head"

    def test_hard_inventory(self, state_manager):
        state_manager.hard_state.player.inventory = ["rusty_key", "toenail_sword"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.hard_inventory == ["rusty_key", "toenail_sword"]

    def test_soft_inventory(self, state_manager):
        state_manager.soft_state.soft_inventory = ["rock", "cork"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.soft_inventory == ["rock", "cork"]

    def test_active_flags_only(self, state_manager):
        state_manager.hard_state.flags["injured"] = False
        state_manager.hard_state.flags["stunned"] = True
        state_manager.hard_state.flags["spider_fled"] = False
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.active_flags == {"stunned": True}

    def test_no_active_flags(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        # All flags are false in initial state
        assert result.player_state.active_flags == {}

    def test_entity_notes_on_player(self, state_manager):
        state_manager.soft_state.entity_notes["player"] = ["Marked with chalk"]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.entity_notes == ["Marked with chalk"]


class TestRecentHistory:
    """History filtering and capping."""

    def test_empty_history(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.recent_history == []

    def test_history_entries(self, state_manager):
        state_manager.soft_state.turn_history = [
            TurnHistoryEntry(
                turn=1,
                player_input="look around",
                ruled_action={"action_type": "examine", "target": "padlock"},
                engine_result_summary="Examined padlock",
                location_after="axe_head",
            ),
            TurnHistoryEntry(
                turn=2,
                player_input="climb down",
                ruled_action={"action_type": "move", "target": "exit_climb_down_handle"},
                engine_result_summary="Moved to axe_handle_upper",
                flags_changed=[],
                location_after="axe_handle_upper",
            ),
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert len(result.recent_history) == 2
        assert result.recent_history[0].turn == 1
        assert result.recent_history[0].summary == "Examined padlock"
        assert result.recent_history[0].location_after == "axe_head"
        assert result.recent_history[1].turn == 2

    def test_ooc_discussion_excluded(self, state_manager):
        state_manager.soft_state.turn_history = [
            TurnHistoryEntry(
                turn=1,
                player_input="look around",
                ruled_action={"action_type": "examine", "target": "padlock"},
                engine_result_summary="Examined padlock",
                location_after="axe_head",
            ),
            TurnHistoryEntry(
                turn=2,
                player_input="what am I seeing?",
                ruled_action={"action_type": "ooc_discussion"},
                engine_result_summary="OOC discussion",
                location_after="axe_head",
            ),
            TurnHistoryEntry(
                turn=3,
                player_input="climb down",
                ruled_action={"action_type": "move", "target": "exit_climb_down_handle"},
                engine_result_summary="Moved to axe_handle_upper",
                location_after="axe_handle_upper",
            ),
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert len(result.recent_history) == 2
        assert result.recent_history[0].turn == 1
        assert result.recent_history[1].turn == 3

    def test_history_capped_at_5(self, state_manager):
        state_manager.soft_state.turn_history = [
            TurnHistoryEntry(
                turn=i,
                player_input=f"action {i}",
                ruled_action={"action_type": "wait"},
                engine_result_summary=f"Turn {i}",
                location_after="axe_head",
            )
            for i in range(1, 8)
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert len(result.recent_history) == 5
        assert result.recent_history[0].turn == 3
        assert result.recent_history[4].turn == 7


class TestNpcAttitudes:
    """NPC attitude pass-through."""

    def test_attitudes_in_entity_state(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        korbar_entity = next(
            (e for e in result.current_room.entities_visible if e.id == "korbar"), None
        )
        assert korbar_entity is not None
        assert korbar_entity.state.get("attitude") == 0

    def test_attitudes_updated_in_entity_state(self, state_manager):
        state_manager.hard_state.player.location = "bag_floor"
        state_manager.hard_state.entity_states["korbar"]["attitude"] = 5
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "talk to korbar",
        )
        korbar_entity = next(
            (e for e in result.current_room.entities_visible if e.id == "korbar"), None
        )
        assert korbar_entity is not None
        assert korbar_entity.state.get("attitude") == 5


class TestPlayerKnowledge:
    """Player knowledge assembly."""

    def test_empty_knowledge(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_knowledge_topics == []

    def test_knowledge_topics_included(self, state_manager):
        state_manager.soft_state.player_knowledge = [
            KnowledgeEntry(
                topic_id="padlock_mechanism",
                description="Korbar explains that the padlock can be unlocked from inside.",
                source_type="npc_dialogue",
                source_id="korbar",
                turn_learned=3,
            ),
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert "padlock_mechanism" in result.player_knowledge_topics


class TestDialogueContext:
    """Dialogue context assembly."""

    def test_no_dialogue_when_inactive(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.dialogue_context is None

    def test_dialogue_context_when_active(self, state_manager):
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
            conversation_log=[
                ConversationLogEntry(turn=1, speaker="player", text="Hello Korbar"),
                ConversationLogEntry(turn=1, speaker="npc", text="Another one, eh?"),
            ],
            topics_discussed=["introductions"],
            entered_turn=1,
            stall_counter=0,
        )
        state_manager.hard_state.entity_states["korbar"]["attitude"] = 3

        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "tell me about the bag",
        )
        assert result.dialogue_context is not None
        assert result.dialogue_context.active_npc.id == "korbar"
        assert result.dialogue_context.active_npc.attitude == 3
        assert result.dialogue_context.topics_discussed == ["introductions"]

    def test_dialogue_guidelines_included(self, state_manager):
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "hello",
        )
        ctx = result.dialogue_context
        assert ctx is not None
        assert ctx.active_npc.dialogue_guidelines.personality != ""
        assert "cynical" in ctx.active_npc.dialogue_guidelines.personality.lower()

    def test_dialogue_recent_exchanges(self, state_manager):
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
            conversation_log=[
                ConversationLogEntry(turn=1, speaker="player", text="Hi"),
                ConversationLogEntry(turn=1, speaker="npc", text="Hello"),
                ConversationLogEntry(turn=2, speaker="player", text="How long?"),
                ConversationLogEntry(turn=2, speaker="npc", text="Three years"),
            ],
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "tell me more",
        )
        exchanges = result.dialogue_context.recent_exchanges
        assert len(exchanges) == 2
        assert exchanges[0]["player"] == "Hi"
        assert exchanges[0]["npc"] == "Hello"
        assert exchanges[1]["player"] == "How long?"
        assert exchanges[1]["npc"] == "Three years"

    def test_dialogue_revealed_topics(self, state_manager):
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
        )
        state_manager.soft_state.player_knowledge = [
            KnowledgeEntry(
                topic_id="padlock_mechanism",
                description="The padlock can be unlocked from inside.",
                source_type="npc_dialogue",
                source_id="korbar",
                turn_learned=2,
            ),
        ]
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "hello",
        )
        assert result.dialogue_context.revealed_topics == ["padlock_mechanism"]

    def test_dialogue_exchanges_capped_at_5(self, state_manager):
        log = []
        for i in range(1, 8):
            log.append(ConversationLogEntry(turn=i, speaker="player", text=f"Q{i}"))
            log.append(ConversationLogEntry(turn=i, speaker="npc", text=f"A{i}"))
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
            conversation_log=log,
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "another question",
        )
        exchanges = result.dialogue_context.recent_exchanges
        assert len(exchanges) == 5
        # Last 5 of 7 complete exchanges: turns 3-7
        assert exchanges[0]["player"] == "Q3"
        assert exchanges[0]["npc"] == "A3"
        assert exchanges[4]["player"] == "Q7"
        assert exchanges[4]["npc"] == "A7"

    def test_dialogue_with_dead_npc_returns_none(self, state_manager):
        state_manager.hard_state.entity_states["korbar"]["alive"] = False
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="korbar",
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "hello?",
        )
        assert result.dialogue_context is None

    def test_dialogue_with_non_npc_returns_none(self, state_manager):
        # padlock is a feature, not an NPC
        state_manager.soft_state.dialogue_state = DialogueState(
            active_npc="padlock",
        )
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "hello?",
        )
        assert result.dialogue_context is None


class TestErrorHandling:
    """Edge cases and error conditions."""

    def test_invalid_player_location_raises(self, state_manager):
        state_manager.hard_state.player.location = "nonexistent_room"
        with pytest.raises(ValueError, match="not found in corpus"):
            assemble(
                state_manager.corpus,
                state_manager.hard_state,
                state_manager.soft_state,
                "look",
            )

    def test_unknown_entity_in_room_skipped(self, state_manager):
        # Add an unknown entity ID to the room's entities_present
        state_manager.corpus.rooms["axe_head"].entities_present.append("ghost_entity")
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        entity_ids = [e.id for e in result.current_room.entities_visible]
        assert "ghost_entity" not in entity_ids
        # Cleanup
        state_manager.corpus.rooms["axe_head"].entities_present.pop()

    def test_empty_soft_state(self, state_manager):
        state_manager.soft_state.soft_inventory = []
        state_manager.soft_state.room_notes = {}
        state_manager.soft_state.entity_notes = {}
        state_manager.soft_state.player_knowledge = []
        state_manager.soft_state.turn_history = []
        state_manager.soft_state.dialogue_state = DialogueState()

        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        assert result.player_state.soft_inventory == []
        assert result.player_knowledge_topics == []
        assert result.recent_history == []
        assert result.dialogue_context is None


class TestBuildContainedEntities:
    """Unit tests for build_contained_entities() helper."""

    def test_returns_contained_entity_when_not_hidden(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        # Add a contained entity relationship to rubbish_pile
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": False}
        result = build_contained_entities(
            corpus.entities["rubbish_pile"], hard, corpus,
        )
        assert len(result) == 1
        assert result[0].id == "toenail_sword"
        assert result[0].type == "item"

    def test_hidden_contained_entity_excluded(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": True}
        result = build_contained_entities(
            corpus.entities["rubbish_pile"], hard, corpus,
        )
        assert len(result) == 0

    def test_item_in_inventory_excluded(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": False}
        hard.player.inventory = ["toenail_sword"]
        result = build_contained_entities(
            corpus.entities["rubbish_pile"], hard, corpus,
        )
        assert len(result) == 0

    def test_empty_when_no_contained_entities(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "axe_head"
        corpus.entities["battleaxe"].contained_entities = []
        result = build_contained_entities(
            corpus.entities["battleaxe"], hard, corpus,
        )
        assert result == []

    def test_missing_contained_entity_skipped(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["nonexistent"]
        result = build_contained_entities(
            corpus.entities["rubbish_pile"], hard, corpus,
        )
        assert len(result) == 0


class TestContainedEntitiesSurfacing:
    """Integration tests: contained_entities appear in the assembler briefing."""

    def test_contained_entity_in_briefing_when_unhidden(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": False}
        result = assemble(corpus, hard, state_manager.soft_state, "look")
        rubbish = _find_entity(result, "rubbish_pile")
        assert rubbish is not None
        assert len(rubbish.contained_entities) == 1
        assert rubbish.contained_entities[0].id == "toenail_sword"

    def test_hidden_contained_entity_not_in_briefing(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": True}
        result = assemble(corpus, hard, state_manager.soft_state, "look")
        rubbish = _find_entity(result, "rubbish_pile")
        assert rubbish is not None
        assert len(rubbish.contained_entities) == 0

    def test_contained_entity_appears_after_unhide(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": True}
        result1 = assemble(corpus, hard, state_manager.soft_state, "look")
        rubbish1 = _find_entity(result1, "rubbish_pile")
        assert len(rubbish1.contained_entities) == 0
        # Unhide and re-assemble
        hard.entity_states["toenail_sword"]["hidden"] = False
        result2 = assemble(corpus, hard, state_manager.soft_state, "look")
        rubbish2 = _find_entity(result2, "rubbish_pile")
        assert len(rubbish2.contained_entities) == 1
        assert rubbish2.contained_entities[0].id == "toenail_sword"

    def test_empty_contained_entities_when_none_defined(self, state_manager):
        result = assemble(
            state_manager.corpus,
            state_manager.hard_state,
            state_manager.soft_state,
            "look",
        )
        for entity in result.current_room.entities_visible:
            assert entity.contained_entities == []

    def test_contained_inventory_item_excluded_from_briefing(self, state_manager):
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        corpus.entities["rubbish_pile"].contained_entities = ["toenail_sword"]
        hard.entity_states["toenail_sword"] = {"hidden": False}
        hard.player.inventory = ["toenail_sword"]
        result = assemble(corpus, hard, state_manager.soft_state, "look")
        rubbish = _find_entity(result, "rubbish_pile")
        assert rubbish is not None
        assert len(rubbish.contained_entities) == 0


def _find_entity(briefing: GMBriefing, entity_id: str) -> BriefingEntity | None:
    for e in briefing.current_room.entities_visible:
        if e.id == entity_id:
            return e
    return None
