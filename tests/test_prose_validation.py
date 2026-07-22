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

"""Unit tests for prose_validation.py."""

from __future__ import annotations

import pytest

from mgmai.engine.narrative_indicators import NarrativeIndicator
from mgmai.llm.prose_validation import validate_prose_output
from mgmai.models.actions import EngineResult
from mgmai.models.narration import NarrationOutput


def _make_engine_result(success: bool = True) -> EngineResult:
    return EngineResult(success=success, action_type="move")


class TestValidateProseOutput:
    """Tests for the top-level validate_prose_output function."""

    def test_empty_narration(self) -> None:
        prose = NarrationOutput(narration="")
        error = validate_prose_output(prose, [], _make_engine_result())
        assert error is not None
        assert "empty" in error.lower()

    def test_whitespace_only_narration(self) -> None:
        prose = NarrationOutput(narration="   \n\t  ")
        error = validate_prose_output(prose, [], _make_engine_result())
        assert error is not None
        assert "empty" in error.lower()

    def test_valid_narration_no_indicators(self) -> None:
        prose = NarrationOutput(narration="You walk down the corridor.")
        error = validate_prose_output(prose, [], _make_engine_result())
        assert error is None

    def test_all_markers_placed(self) -> None:
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        prose = NarrationOutput(
            narration="You try to lift the boulder.\n\n[MECH:check:0]\n\nIt does not budge."
        )
        error = validate_prose_output(prose, [ind], _make_engine_result(success=False))
        assert error is None

    def test_marker_duplicated(self) -> None:
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        prose = NarrationOutput(
            narration="You try.\n\n[MECH:check:0]\n\nNope.\n\n[MECH:check:0]\n\nStill nope."
        )
        error = validate_prose_output(prose, [ind], _make_engine_result())
        assert error is not None
        assert "exactly once" in error

    def test_mangled_marker(self) -> None:
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        prose = NarrationOutput(
            narration="You try.\n\n[MECH: check:0]\n\nNope."
        )
        error = validate_prose_output(prose, [ind], _make_engine_result())
        assert error is not None
        assert "mangled" in error.lower()

    def test_plain_description_leakage(self) -> None:
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        prose = NarrationOutput(
            narration="You try to lift. STR check: failed. It does not budge."
        )
        error = validate_prose_output(prose, [ind], _make_engine_result())
        assert error is not None
        assert "mechanical text" in error.lower()

    def test_plain_description_short_allowed(self) -> None:
        """Short descriptions (≤5 chars) should not trigger false positives."""
        ind = NarrativeIndicator(
            marker="[MECH:x]",
            formatted="**[HP]**",
            category="hp",
        )
        # Place the marker so the "all unplaced" check doesn't fire.
        prose = NarrationOutput(narration="Your HP is low.\n\n[MECH:x]\n\nYou recover.")
        error = validate_prose_output(prose, [ind], _make_engine_result())
        assert error is None  # "HP" is only 2 chars, so it should be allowed


    def test_no_markers_placed(self) -> None:
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        prose = NarrationOutput(narration="You try to lift the boulder. It does not budge.")
        error = validate_prose_output(prose, [ind], _make_engine_result())
        assert error is not None
        assert "did not place" in error.lower()

    def test_success_contradiction(self) -> None:
        prose = NarrationOutput(narration="You succeeded in picking the lock.")
        error = validate_prose_output(
            prose, [], _make_engine_result(success=False)
        )
        assert error is not None
        assert "contradict" in error.lower()

    def test_success_contradiction_no_false_positive(self) -> None:
        """Success words in a success context should not be flagged."""
        prose = NarrationOutput(narration="You succeeded in picking the lock.")
        error = validate_prose_output(
            prose, [], _make_engine_result(success=True)
        )
        assert error is None

    def test_failure_contradiction(self) -> None:
        prose = NarrationOutput(narration="You failed to open the door.")
        error = validate_prose_output(
            prose, [], _make_engine_result(success=True)
        )
        assert error is not None
        assert "contradict" in error.lower()

    def test_failure_contradiction_miss_allowed(self) -> None:
        """'miss' in combat narration on success should not be flagged."""
        prose = NarrationOutput(narration="You dodge his attack and strike back.")
        error = validate_prose_output(
            prose, [], _make_engine_result(success=True)
        )
        assert error is None

    def test_multiple_indicators_all_placed(self) -> None:
        inds = [
            NarrativeIndicator(
                marker="[MECH:check:0]",
                formatted="**[STR check: success]**",
                category="check",
            ),
            NarrativeIndicator(
                marker="[MECH:combat:0]",
                formatted="**You attack golem: hit for 5 damage.**",
                category="combat",
            ),
        ]
        prose = NarrationOutput(
            narration=(
                "You heave.\n\n[MECH:check:0]\n\nThe door gives way. "
                "You swing at the golem.\n\n[MECH:combat:0]\n\nIt staggers."
            )
        )
        error = validate_prose_output(prose, inds, _make_engine_result())
        assert error is None
