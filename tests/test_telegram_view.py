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

"""Tests for mgmai/telegram/view.py — the buffering TelegramView.

Driven by a real ``GameSession`` with a fake LLM client where practical
(project convention: no network in unit tests).
"""

from __future__ import annotations

import json
from pathlib import Path

from mgmai.game.session import GameSession
from mgmai.models.combat import CombatState
from mgmai.models.corpus import CombatBlock
from mgmai.telegram.view import TelegramView, ViewEvent

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeLLMClient:
    """Returns predetermined JSON strings for ruling and prose calls."""

    def __init__(
        self,
        ruling_response: str | None = None,
        prose_response: str | None = None,
    ) -> None:
        self._ruling = ruling_response
        self._prose = prose_response

    def call_ruling(self, system_prompt: str, user_prompt: str) -> str:
        if self._ruling is None:
            raise RuntimeError("No ruling response configured")
        return self._ruling

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        if self._prose is None:
            raise RuntimeError("No prose response configured")
        return self._prose


def _wait_llm(narration: str = "Time passes.") -> FakeLLMClient:
    return FakeLLMClient(
        ruling_response=json.dumps({
            "action_type": "wait",
            "detail": "Waiting",
            "follow_up": None,
            "soft_state_patches": [],
        }),
        prose_response=json.dumps({
            "narration": narration,
            "npc_response": None,
            "knowledge_tags": None,
            "attitude_changes": None,
        }),
    )


def _make_session(state_manager, tmp_path, view=None, llm=None) -> GameSession:
    return GameSession(
        state_manager,
        llm or _wait_llm(),
        view=view or TelegramView(),
        config_dir=tmp_path,
    )


class TestBuffering:
    def test_drain_returns_events_in_order_and_clears(self):
        view = TelegramView()
        view.render_narration("first")
        view.render_error("oops")
        view.render_narration("second")
        events = view.drain()
        assert [(e.kind, e.text) for e in events] == [
            ("narration", "first"),
            ("error", "Error: oops"),
            ("narration", "second"),
        ]
        assert view.drain() == []

    def test_print_strips_rich_markup(self):
        view = TelegramView()
        view.print("[bold]Inventory[/bold]\n[dim]empty[/dim]")
        (event,) = view.drain()
        assert event.kind == "print"
        assert event.text == "Inventory\nempty"

    def test_render_goodbye(self):
        view = TelegramView()
        view.render_goodbye()
        (event,) = view.drain()
        assert event.kind == "goodbye"


class TestSessionDriven:
    def test_begin_buffers_intro(self, state_manager, tmp_path):
        view = TelegramView()
        _make_session(state_manager, tmp_path, view=view).begin()
        (event,) = view.drain()
        assert event.kind == "intro"
        assert "You're Trapped in a Bag of Holding!" in event.text
        # Starting room + exits are part of the intro.
        assert "Exits:" in event.text

    def test_submit_buffers_narration_then_status(self, state_manager, tmp_path):
        view = TelegramView()
        session = _make_session(state_manager, tmp_path, view=view)
        result = session.submit("I wait")
        kinds = [e.kind for e in view.drain()]
        assert kinds == ["narration", "status"]
        assert result.narration == "Time passes."

    def test_status_line_content(self, state_manager, tmp_path):
        view = TelegramView()
        session = _make_session(state_manager, tmp_path, view=view)
        session.submit("I wait")
        events = view.drain()
        status = next(e for e in events if e.kind == "status")
        assert "Turn 1" in status.text
        assert "Location:" in status.text

    def test_slash_command_output_is_buffered(self, state_manager, tmp_path):
        view = TelegramView()
        session = _make_session(state_manager, tmp_path, view=view)
        session.submit("/help")
        events = view.drain()
        assert events
        assert all(e.kind == "print" for e in events)
        # Rich markup stripped.
        assert not any("[bold]" in e.text for e in events)


class TestStatusRendering:
    def test_combat_panel(self, state_manager):
        state_manager.corpus.entities["spider"].combat = CombatBlock(
            hp=15, ac=12, atk=4, dmg="1d4+2",
        )
        hard = state_manager.hard_state
        hard.player.current_hp = 8
        hard.player.max_hp = 10
        hard.player.status_effects = {"poisoned": 2}
        hard.entity_states["spider"] = {"current_hp": 5}
        hard.combat = CombatState(
            round_number=2,
            initiative_order=["player", "spider"],
            combatants=["player", "spider"],
            active=True,
        )
        view = TelegramView()
        view.render_status(state_manager)
        (event,) = view.drain()
        assert event.kind == "status"
        assert "Combat — Round 2" in event.text
        assert "Initiative: player → spider" in event.text
        assert "8/10" in event.text
        assert "5/15" in event.text
        assert "It's your turn." in event.text

    def test_no_hard_state_buffers_nothing(self):
        from mgmai.state.manager import StateManager

        view = TelegramView()
        view.render_status(StateManager())
        assert view.drain() == []


class TestGameOver:
    def test_render_game_over_win(self):
        view = TelegramView()
        view.render_game_over(type("R", (), {
            "type": "win", "trigger": "final_door", "narrative": "You escape!",
        })())
        (event,) = view.drain()
        assert event.kind == "game_over"
        assert "Victory" in event.text
        assert "You escape!" in event.text

    def test_render_game_over_lose(self):
        view = TelegramView()
        view.render_game_over(type("R", (), {
            "type": "lose", "trigger": "spider", "narrative": None,
        })())
        (event,) = view.drain()
        assert "Defeat" in event.text

    def test_exit_command_buffers_goodbye(self, state_manager, tmp_path):
        view = TelegramView()
        session = _make_session(state_manager, tmp_path, view=view)
        session.submit("/exit")
        assert session.finished
        (event,) = view.drain()
        assert event.kind == "goodbye"


class TestViewEventDataclass:
    def test_fields(self):
        e = ViewEvent("narration", "text")
        assert e.kind == "narration"
        assert e.text == "text"
