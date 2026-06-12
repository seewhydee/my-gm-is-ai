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

"""Tests for engine/stat_checks.py."""

from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from mgmai.engine.stat_checks import compute_d20_modifier, compute_modifier, format_stat_check_prefix
from mgmai.models.corpus import ModuleCorpus, StatCheck, StatsBlock, StatDefinition, RollCheck, CheckType


class TestComputeD20Modifier:
    """Stat modifier computation for d20 system."""

    def test_10_yields_0(self) -> None:
        assert compute_d20_modifier(10) == 0

    def test_12_yields_1(self) -> None:
        assert compute_d20_modifier(12) == 1

    def test_14_yields_2(self) -> None:
        assert compute_d20_modifier(14) == 2

    def test_8_yields_neg1(self) -> None:
        assert compute_d20_modifier(8) == -1

    def test_9_yields_neg1(self) -> None:
        assert compute_d20_modifier(9) == -1

    def test_3_yields_neg4(self) -> None:
        assert compute_d20_modifier(3) == -4

    def test_18_yields_4(self) -> None:
        assert compute_d20_modifier(18) == 4

    def test_20_yields_5(self) -> None:
        assert compute_d20_modifier(20) == 5

    def test_1_yields_neg5(self) -> None:
        assert compute_d20_modifier(1) == -5


class TestComputeModifier:
    def test_d20_delegates(self) -> None:
        assert compute_modifier(14, "d20") == 2

    def test_unknown_system_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown resolution system"):
            compute_modifier(14, "gurps")


class TestFormatStatCheckPrefix:
    def test_empty_when_no_rolls(self) -> None:
        assert format_stat_check_prefix([]) == ""

    def test_empty_when_no_stat_checks(self) -> None:
        rolls = [{"type": "roll_check", "threshold": 0.5, "result": 0.3, "success": True}]
        assert format_stat_check_prefix(rolls) == ""

    def test_single_success(self) -> None:
        rolls = [{"type": "stat_check", "stat": "STR", "dc": 10, "success": True}]
        assert format_stat_check_prefix(rolls) == "**[STR check: success]**\n\n"

    def test_single_failure(self) -> None:
        rolls = [{"type": "stat_check", "stat": "DEX", "dc": 12, "success": False}]
        assert format_stat_check_prefix(rolls) == "**[DEX check: failed]**\n\n"

    def test_multiple_checks(self) -> None:
        rolls = [
            {"type": "stat_check", "stat": "STR", "dc": 10, "success": True},
            {"type": "stat_check", "stat": "DEX", "dc": 12, "success": False},
        ]
        assert format_stat_check_prefix(rolls) == (
            "**[STR check: success]**\n\n**[DEX check: failed]**\n\n"
        )

    def test_ignores_incomplete_entries(self) -> None:
        rolls = [
            {"type": "stat_check", "stat": "STR", "success": True},
            {"type": "stat_check", "success": False},
            {"type": "stat_check", "stat": "CON", "success": True},
        ]
        assert format_stat_check_prefix(rolls) == (
            "**[STR check: success]**\n\n**[CON check: success]**\n\n"
        )
