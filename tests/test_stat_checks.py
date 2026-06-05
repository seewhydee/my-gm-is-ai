"""Tests for engine/stat_checks.py."""

from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from mgmai.engine.stat_checks import compute_d20_modifier, compute_modifier
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
