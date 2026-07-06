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

"""Tests for logging.py — logging infrastructure."""

from __future__ import annotations

import logging

import pytest

from mgmai.logging import (
    format_state_snapshot,
    get_level,
    set_level,
    setup_logging,
)


class TestSetupLogging:
    def test_creates_console_handler(self) -> None:
        setup_logging(level="DEBUG")
        root = logging.getLogger("mgmai")
        assert len(root.handlers) >= 1

    def test_creates_file_handler(self, tmp_path) -> None:
        log_file = tmp_path / "test.log"
        setup_logging(level="INFO", log_file=str(log_file))
        root = logging.getLogger("mgmai")
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1

    def test_file_handler_writes(self, tmp_path) -> None:
        log_file = tmp_path / "test.log"
        setup_logging(level="DEBUG", log_file=str(log_file))
        logger = logging.getLogger("mgmai.test")
        logger.debug("hello debug")
        logger.info("hello info")

        content = log_file.read_text()
        assert "hello debug" in content
        assert "hello info" in content

    def test_console_handler_respects_level(self, capsys) -> None:
        setup_logging(level="WARNING")
        logger = logging.getLogger("mgmai.test2")
        logger.info("should not appear")
        logger.warning("should appear")

        captured = capsys.readouterr()
        assert "should not appear" not in captured.err
        assert "should appear" in captured.err

    def test_clears_previous_handlers(self) -> None:
        setup_logging(level="INFO")
        first_count = len(logging.getLogger("mgmai").handlers)
        setup_logging(level="INFO")
        second_count = len(logging.getLogger("mgmai").handlers)
        assert second_count == first_count


class TestGetSetLevel:
    def test_set_level_changes_handler(self) -> None:
        setup_logging(level="INFO")
        set_level("DEBUG")
        root = logging.getLogger("mgmai")
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert console_handlers[0].level == logging.DEBUG

    def test_set_level_unknown_defaults_to_info(self) -> None:
        setup_logging(level="INFO")
        set_level("BOGUS")
        root = logging.getLogger("mgmai")
        console = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ][0]
        assert console.level == logging.INFO

    def test_get_level_returns_root_level(self) -> None:
        root = logging.getLogger("mgmai")
        root.setLevel(logging.WARNING)
        assert get_level() == logging.WARNING


class TestFormatStateSnapshot:
    def test_basic_keys(self, state_manager) -> None:
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        snap = format_state_snapshot(hard, soft)
        assert snap["player_location"] == "axe_head"
        assert isinstance(snap["hard_inventory"], dict)
        assert isinstance(snap["flags"], dict)
        assert "turn_count" in snap

    def test_entity_attitudes(self, state_manager) -> None:
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.entity_states["korbar"]["attitude"] = 5
        snap = format_state_snapshot(hard, soft)
        assert snap["entity_attitudes"]["korbar"] == 5
