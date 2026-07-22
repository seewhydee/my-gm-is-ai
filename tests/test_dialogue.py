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

"""Tests for engine/dialogue.py."""



from mgmai.engine.dialogue import (
    enter_dialogue,
    append_player_turn,
    append_npc_response,
    increment_stall,
    exit_dialogue,
    check_room_change_exit,
    track_topic,
)


class TestEnterDialogue:
    def test_enters_dialogue_mode(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        assert soft.dialogue_state.active_npc == "korbar"
        assert soft.dialogue_state.entered_turn == 1
        assert soft.dialogue_state.stall_counter == 0
        assert len(soft.dialogue_state.conversation_log) == 1
        assert soft.dialogue_state.conversation_log[0].speaker == "player"

    def test_enters_with_no_utterance(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "stuck_fly", 2, None, "Looking at the fly")
        assert soft.dialogue_state.active_npc == "stuck_fly"
        assert len(soft.dialogue_state.conversation_log) == 1
        assert "Looking at the fly" in soft.dialogue_state.conversation_log[0].text

    def test_clears_previous_dialogue(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        enter_dialogue(soft, "stuck_fly", 2, None, "Hi fly")
        assert soft.dialogue_state.active_npc == "stuck_fly"
        assert soft.dialogue_state.entered_turn == 2
        assert len(soft.dialogue_state.conversation_log) == 1


class TestAppendPlayerTurn:
    def test_appends_to_log(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        append_player_turn(soft, "korbar", 2, "How are you?", "Question")
        assert len(soft.dialogue_state.conversation_log) == 2
        assert soft.dialogue_state.stall_counter == 0

    def test_ignores_when_npc_mismatch(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        append_player_turn(soft, "stuck_fly", 2, "Hi", "To fly")
        assert len(soft.dialogue_state.conversation_log) == 1


class TestAppendNpcResponse:
    def test_appends_npc_response(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        append_npc_response(soft, "korbar", 1, "Oh, a new arrival.")
        assert len(soft.dialogue_state.conversation_log) == 2
        assert soft.dialogue_state.conversation_log[1].speaker == "npc"

    def test_ignores_when_npc_mismatch(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        append_npc_response(soft, "stuck_fly", 1, "Buzz")
        assert len(soft.dialogue_state.conversation_log) == 1


class TestIncrementStall:
    def test_increments_counter(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        assert increment_stall(soft) is False
        assert soft.dialogue_state.stall_counter == 1

    def test_returns_true_at_limit(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        increment_stall(soft)
        assert increment_stall(soft) is False
        assert increment_stall(soft) is True
        assert soft.dialogue_state.stall_counter == 3

    def test_noop_when_no_dialogue(self, state_manager):
        soft = state_manager.soft_state
        assert increment_stall(soft) is False


class TestExitDialogue:
    def test_archives_conversation(self, state_manager):
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        append_npc_response(soft, "korbar", 1, "Hello stranger")
        result = exit_dialogue(soft, corpus, hard)
        assert result is not None
        assert result["npc_id"] == "korbar"
        assert result["archival_fallback"] is not None
        assert "Conversation summary" in result["archival_fallback"]
        assert "2 exchanges" in result["archival_fallback"]
        assert soft.dialogue_state.active_npc is None
        # entity_notes are now written by _execute_turn after LLM Call 2,
        # not by exit_dialogue. The fallback is passed through the result.
        assert "korbar" not in soft.entity_notes

    def test_noop_when_no_active_dialogue(self, state_manager):
        soft = state_manager.soft_state
        result = exit_dialogue(soft, state_manager.corpus, state_manager.hard_state)
        assert result is None

    def test_exit_dialogue_returns_npc_id(self, state_manager):
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        enter_dialogue(soft, "stuck_fly", 1, None, "Approaching")
        result = exit_dialogue(soft, corpus, hard)
        assert result is not None
        assert result["npc_id"] == "stuck_fly"


class TestCheckRoomChangeExit:
    def test_no_exit_when_npc_in_both_rooms(self, state_manager):
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        enter_dialogue(soft, "battleaxe", 1, "Hello", "Greeting")
        result = check_room_change_exit(
            soft, "axe_head", "axe_handle_upper", corpus, hard
        )
        assert result is None

    def test_no_exit_when_no_dialogue(self, state_manager):
        soft = state_manager.soft_state
        result = check_room_change_exit(
            soft, "axe_head", "bag_floor", state_manager.corpus,
            state_manager.hard_state,
        )
        assert result is None

    def test_exits_when_npc_not_in_new_room(self, state_manager):
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        result = check_room_change_exit(
            soft, "bag_floor", "axe_head", corpus, hard
        )
        assert result is not None

    def test_no_exit_when_npc_in_new_room(self, state_manager):
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard = state_manager.hard_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        result = check_room_change_exit(
            soft, "bag_floor", "bag_floor", corpus, hard
        )
        assert result is None


class TestTrackTopic:
    def test_adds_topic(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        track_topic(soft, "escape_plan")
        assert "escape_plan" in soft.dialogue_state.topics_discussed

    def test_no_duplicate(self, state_manager):
        soft = state_manager.soft_state
        enter_dialogue(soft, "korbar", 1, "Hello", "Greeting")
        track_topic(soft, "escape_plan")
        track_topic(soft, "escape_plan")
        assert soft.dialogue_state.topics_discussed == ["escape_plan"]

    def test_noop_when_no_dialogue(self, state_manager):
        soft = state_manager.soft_state
        track_topic(soft, "escape_plan")
        assert len(soft.dialogue_state.topics_discussed) == 0
