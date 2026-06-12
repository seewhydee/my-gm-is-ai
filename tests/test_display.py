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

"""Tests for game/display.py — console output rendering."""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import pytest

from mgmai.game.display import Display


class FakeStateLoader:
    def __init__(self, corpus: Any, hard_state: Any, soft_state: Any):
        self.corpus = corpus
        self.hard_state = hard_state
        self.soft_state = soft_state


class TestDisplaySmoke:
    """Smoke tests ensuring display methods do not crash."""

    def test_render_intro(self, state_manager) -> None:
        d = Display()
        d.render_intro(state_manager)

    def test_render_narration(self) -> None:
        d = Display()
        d.render_narration("You enter a dark room.")

    def test_render_error(self) -> None:
        d = Display()
        d.render_error("Something went wrong")

    def test_render_goodbye(self) -> None:
        d = Display()
        d.render_goodbye()

    def test_render_status(self, state_manager) -> None:
        d = Display()
        d.render_status(state_manager)

    def test_render_game_over_win(self) -> None:
        d = Display()
        go = MagicMock()
        go.type = "win"
        go.trigger = "escaped"
        go.narrative = "You escaped the bag!"
        d.render_game_over(go)

    def test_render_game_over_lose(self) -> None:
        d = Display()
        go = MagicMock()
        go.type = "lose"
        go.trigger = "spider_death"
        go.narrative = None
        d.render_game_over(go)

    def test_render_game_over_unknown(self) -> None:
        d = Display()
        go = MagicMock()
        go.type = "draw"
        go.trigger = "timeout"
        go.narrative = "Time ran out."
        d.render_game_over(go)


class TestDisplayNoRich:
    """Tests for the fallback path when Rich is unavailable."""

    def test_render_intro_no_rich(self, state_manager, monkeypatch, capsys) -> None:
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        d = Display()
        d.render_intro(state_manager)
        captured = capsys.readouterr()
        assert state_manager.corpus.adventure.title in captured.out

    def test_render_narration_no_rich(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        d = Display()
        d.render_narration("Hello world")
        captured = capsys.readouterr()
        assert "Hello world" in captured.out

    def test_render_status_no_rich(self, state_manager, monkeypatch, capsys) -> None:
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        d = Display()
        d.render_status(state_manager)
        captured = capsys.readouterr()
        assert "Turn" in captured.out
        assert state_manager.hard_state.player.location in captured.out

    def test_render_game_over_no_rich(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        d = Display()
        go = MagicMock()
        go.type = "win"
        go.trigger = "test"
        go.narrative = "Victory!"
        d.render_game_over(go)
        captured = capsys.readouterr()
        assert "Victory" in captured.out

    def test_render_error_no_rich(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        d = Display()
        d.render_error("oops")
        captured = capsys.readouterr()
        assert "oops" in captured.out
