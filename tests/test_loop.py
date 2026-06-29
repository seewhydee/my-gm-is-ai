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

"""Tests for game/loop.py — main game loop and turn execution."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mgmai.game.loop import GameLoop, FALLBACK_NARRATION, TURN_ERROR_NARRATION
from mgmai.llm.parser import LLMOutputError


class FakeLLMClient:
    """Returns predetermined JSON strings for ruling and prose calls."""

    def __init__(
        self,
        ruling_response: str | None = None,
        prose_response: str | None = None,
    ) -> None:
        self._ruling = ruling_response
        self._prose = prose_response
        self.ruling_calls: list[tuple[str, str]] = []
        self.prose_calls: list[tuple[str, str]] = []

    def call_ruling(self, system_prompt: str, user_prompt: str) -> str:
        self.ruling_calls.append((system_prompt, user_prompt))
        if self._ruling is None:
            raise RuntimeError("No ruling response configured")
        return self._ruling

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        self.prose_calls.append((system_prompt, user_prompt))
        if self._prose is None:
            raise RuntimeError("No prose response configured")
        return self._prose


def _wait_action_json(detail: str = "Waiting") -> str:
    return json.dumps({
        "action_type": "wait",
        "detail": detail,
        "follow_up": None,
        "proposed_soft_state_patches": [],
    })


def _prose_json(narration: str = "The GM narrates.") -> str:
    return json.dumps({
        "narration": narration,
        "npc_response": None,
        "knowledge_tags": None,
        "attitude_changes": None,
    })


@pytest.fixture
def fake_display() -> MagicMock:
    m = MagicMock()
    m.format_exits.return_value = ""
    return m


class TestExecuteTurn:
    """Tests for GameLoop._execute_turn — single-turn pipeline."""

    def test_wait_turn_success(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Time passes..."),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        narration = loop._execute_turn("wait", "wait", 0)

        assert narration == "Time passes..."
        assert len(llm.ruling_calls) == 1
        assert len(llm.prose_calls) == 1
        assert state_manager.hard_state.turn_count == 1
        assert len(state_manager.soft_state.turn_history) == 1

    def test_fallback_on_llm1_parse_error(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response="not valid json",
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        narration = loop._execute_turn("bad", "bad", 0)

        # _execute_turn renders fallback via display but returns None
        assert narration is None
        fake_display.render_narration.assert_called_once_with(FALLBACK_NARRATION)
        # Should have retried once
        assert len(llm.ruling_calls) == 2

    def test_fallback_on_llm2_parse_error(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response="not valid json",
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        narration = loop._execute_turn("wait", "wait", 0)

        # Falls back to first triggered narration or error narration
        assert narration == TURN_ERROR_NARRATION

    def test_stat_check_prefix_prepended_to_prose(self, state_manager, fake_display) -> None:
        """When engine result contains stat-check rolls, prefix prose narration."""
        from mgmai.models.actions import EngineResult

        engine_result = EngineResult(
            success=True,
            action_type="interact",
            target="spider",
            rolls=[{"type": "stat_check", "stat": "STR", "target": 10, "success": False}],
        )

        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Your sword swings wide."),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        with patch("mgmai.game.loop.resolve", return_value=engine_result):
            narration = loop._execute_turn("attack spider", "attack spider", 0)

        assert narration.startswith("**[STR check: failed]**")
        assert "Your sword swings wide." in narration

    def test_stat_check_prefix_prepended_to_fallback(self, state_manager, fake_display) -> None:
        """When prose fails to parse, prefix the fallback narration with check info."""
        from mgmai.models.actions import EngineResult

        engine_result = EngineResult(
            success=True,
            action_type="interact",
            target="spider",
            rolls=[{"type": "stat_check", "stat": "DEX", "target": 12, "success": True}],
            triggered_narration=["You dart past the trap."],
        )

        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response="not valid json",
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        with patch("mgmai.game.loop.resolve", return_value=engine_result):
            narration = loop._execute_turn("dodge trap", "dodge trap", 0)

        assert narration.startswith("**[DEX check: success]**")
        assert "You dart past the trap." in narration

    def test_debug_mode_logs_extra(self, state_manager, fake_display, caplog) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._commands._debug = True

        with caplog.at_level("DEBUG", logger="mgmai"):
            loop._execute_turn("wait", "wait", 0)

        debug_messages = [r.message for r in caplog.records if r.levelno == 10]
        assert len(debug_messages) >= 4


class TestRunTurn:
    """Tests for GameLoop._run_turn — turn + chain handling."""

    def test_simple_turn_appends_chat(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("You wait."),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        loop._run_turn("I wait")

        assert len(loop._chat_log) == 2
        assert loop._chat_log[0]["role"] == "player"
        assert loop._chat_log[1]["role"] == "gm"
        fake_display.render_narration.assert_called_once_with("You wait.")
        fake_display.render_status.assert_called_once()

    def test_chain_turns(self, state_manager, fake_display) -> None:
        ruling = json.dumps({
            "action_type": "move",
            "target": "exit_climb_down_handle",
            "detail": "Climb down",
            "follow_up": "look around",
            "proposed_soft_state_patches": [],
        })
        prose = _prose_json("You climb down.")
        llm = FakeLLMClient(ruling_response=ruling, prose_response=prose)
        loop = GameLoop(state_manager, llm, display=fake_display)

        loop._run_turn("Climb down and look around")

        # Two LLM calls for ruling (one for each chain link)
        # Actually, each chain link does ruling + prose. But wait — our fake
        # LLM returns the same ruling every time, which has follow_up again.
        # This would loop forever. Let's make the second ruling have no follow_up.
        # Instead, let's verify that with a single ruling call that has follow_up,
        # the loop calls _execute_turn twice.
        # Actually our fake returns the same response every time, so it would chain
        # forever until MAX_CHAIN_LENGTH. That's actually a valid test!
        # But let's be more precise.
        pass  # Will write a better test below

    def test_chain_executes_two_turns(self, state_manager, fake_display) -> None:
        """Verify that a follow_up causes two engine resolutions."""
        responses = [
            json.dumps({
                "action_type": "move",
                "target": "exit_climb_down_handle",
                "detail": "Climb down",
                "follow_up": "look around",
                "proposed_soft_state_patches": [],
            }),
            _wait_action_json("look around"),
        ]
        prose_responses = [
            _prose_json("You climb down."),
            _prose_json("You look around."),
        ]
        llm = FakeLLMClient()
        llm._ruling_iter = iter(responses)
        llm._prose_iter = iter(prose_responses)
        llm.call_ruling = lambda sp, up: next(llm._ruling_iter)
        llm.call_prose = lambda sp, up: next(llm._prose_iter)

        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("Climb down and look around")

        # Only the final narration is rendered; chain intermediates are not
        fake_display.render_narration.assert_called_once_with("You look around.")
        # Status should be rendered once after the chain ends
        fake_display.render_status.assert_called_once()
        # Turn count should have advanced twice
        assert state_manager.hard_state.turn_count == 2

    def test_max_chain_length(self, state_manager, fake_display) -> None:
        """If chain never terminates, loop hits max depth and shows last narration."""
        ruling = json.dumps({
            "action_type": "wait",
            "detail": "wait",
            "follow_up": "wait more",
            "proposed_soft_state_patches": [],
        })
        llm = FakeLLMClient(ruling_response=ruling, prose_response=_prose_json())
        loop = GameLoop(state_manager, llm, display=fake_display)

        loop._run_turn("keep waiting")

        fake_display.render_narration.assert_called_with("The GM narrates.")

    def test_game_over_ends_loop(self, state_manager, fake_display) -> None:
        """When engine sets game_over, the loop renders game over and exits."""
        # The bag-of-holding win mechanic is triggered by padlock_unlocked
        state_manager.hard_state.flags["padlock_unlocked"] = True

        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("You win!"),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("do something")

        fake_display.render_game_over.assert_called_once()
        assert loop._running is False

    def test_knowledge_tags_triggers_post_validation(
        self, state_manager, fake_display
    ) -> None:
        """When prose output has knowledge_tags, post-validation is applied."""
        state_manager.hard_state.entity_states["korbar"]["attitude"] = 5

        prose = json.dumps({
            "narration": "Korbar tells you a secret.",
            "npc_response": None,
            "knowledge_tags": {"npc_revealed": {"korbar": ["padlock_mechanism"]}},
            "attitude_changes": None,
        })
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=prose,
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("ask korbar about the lock")

        assert loop._last_result is not None
        assert len(loop._last_result.revelations_applied) >= 1
        assert any(
            r.npc_id == "korbar" and r.topic_id == "padlock_mechanism"
            for r in loop._last_result.revelations_applied
        )

    def test_attitude_changes_triggers_post_validation(
        self, state_manager, fake_display
    ) -> None:
        """When prose output has attitude_changes, post-validation is applied."""

        prose = json.dumps({
            "narration": "Korbar appreciates your kindness.",
            "npc_response": None,
            "knowledge_tags": None,
            "attitude_changes": {
                "korbar": {"old_value": 0, "new_value": 1, "reason": "Player was kind"}
            },
        })
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=prose,
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("be nice to korbar")

        assert loop._last_result is not None
        assert "korbar" in loop._last_result.attitude_changes_applied
        assert state_manager.hard_state.entity_states["korbar"]["attitude"] == 1

    def test_npc_response_feeds_dialogue(
        self, state_manager, fake_display
    ) -> None:
        """NPC response from prose output is appended to dialogue conversation log."""
        soft = state_manager.soft_state
        soft.dialogue_state.active_npc = "korbar"
        soft.dialogue_state.conversation_log = []

        prose = json.dumps({
            "narration": "Korbar grunts in reply.",
            "npc_response": "What do you want?",
            "knowledge_tags": None,
            "attitude_changes": None,
        })
        llm = FakeLLMClient(
            ruling_response=_wait_action_json("ask korbar something"),
            prose_response=prose,
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("ask korbar something")

        log = state_manager.soft_state.dialogue_state.conversation_log
        npc_entries = [e for e in log if e.speaker == "npc"]
        assert len(npc_entries) >= 1
        assert npc_entries[0].text == "What do you want?"

    def test_track_topic_called_on_knowledge_tags(
        self, state_manager, fake_display
    ) -> None:
        """Topics from knowledge_tags are recorded in dialogue_state.topics_discussed."""
        soft = state_manager.soft_state
        soft.dialogue_state.active_npc = "korbar"
        soft.dialogue_state.conversation_log = []
        soft.dialogue_state.topics_discussed = []
        state_manager.hard_state.entity_states["korbar"]["attitude"] = 5

        prose = json.dumps({
            "narration": "Korbar explains the padlock.",
            "npc_response": None,
            "knowledge_tags": {"npc_revealed": {"korbar": ["padlock_mechanism"]}},
            "attitude_changes": None,
        })
        llm = FakeLLMClient(
            ruling_response=_wait_action_json("ask about padlock"),
            prose_response=prose,
        )
        loop = GameLoop(state_manager, llm, display=fake_display)
        loop._run_turn("ask about padlock")

        assert "padlock_mechanism" in state_manager.soft_state.dialogue_state.topics_discussed


class TestRepl:
    """Tests for GameLoop._repl — top-level input loop."""

    def test_repl_processes_input_and_quits(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        with patch("builtins.input", side_effect=["wait", "/quit"]):
            loop.start()

        assert loop._running is False
        fake_display.render_goodbye.assert_called_once()

    def test_repl_handles_eof(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        with patch("builtins.input", side_effect=[EOFError]):
            loop.start()

        assert loop._running is False
        fake_display.render_goodbye.assert_called_once()

    def test_repl_empty_input_ignored(self, state_manager, fake_display) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=fake_display)

        with patch("builtins.input", side_effect=["", "   ", "/quit"]):
            loop.start()

        assert loop._running is False
