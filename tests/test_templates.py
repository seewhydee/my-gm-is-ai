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

from __future__ import annotations

from mgmai.templates.renderer import render_ruling, render_prose


class TestRulingTemplate:
    """Smoke tests to verify the templates render without errors."""

    def test_renders_without_error(self) -> None:
        output = render_ruling()
        assert isinstance(output, str)
        assert len(output) > 100

    def test_contains_required_sections(self) -> None:
        output = render_ruling()
        assert "Game State Context" in output
        assert "Output Format" in output
        assert "action_type" in output
        assert "move" in output
        assert "examine" in output
        assert "interact" in output
        assert "talk" in output
        assert "transfer" in output
        assert "wait" in output
        assert "ooc_discussion" in output
        assert "Critical Constraints" in output

    def test_contains_invalid_movement_fallback_examples(self) -> None:
        output = render_ruling()
        assert "Invalid or ambiguous movement" in output
        assert "no exit to the north" in output
        assert "unclear which door" in output

    def test_renders_multiple_times(self) -> None:
        out1 = render_ruling()
        out2 = render_ruling()
        assert out1 == out2  # static template


class TestProseTemplate:
    """Smoke tests to verify the templates render without errors."""

    def test_renders_without_error(self) -> None:
        output = render_prose()
        assert isinstance(output, str)
        assert len(output) > 100

    def test_contains_required_sections(self) -> None:
        output = render_prose()
        assert "Narrator GM" in output
        assert "narration" in output
        assert "npc_response" in output
        assert "knowledge_tags" in output
        assert "attitude_changes" in output
        assert "Narration Rules" in output

    def test_renders_multiple_times(self) -> None:
        out1 = render_prose()
        out2 = render_prose()
        assert out1 == out2  # static with same flags


class TestProseTemplateConditional:
    """Test dynamic inclusion/exclusion of narrator instruction sections.

    Uses section headings (structural markers) and EngineResult JSON
    field names (tied to Pydantic model, stable against prose rephrasing)
    rather than exact wording, so template phrasing can be refined without
    breaking these tests.
    """

    _COMBAT_HEADING = "## Narration During Combat"
    _DIALOGUE_HEADING = "## Dialogue with NPCs"
    _SOFT_ITEMS_HEADING = "## Soft Item Adjudication"
    _COMBAT_FIELDS = ("combat_triggered", "combat_log")
    _DIALOGUE_FIELDS = ("dialogue_exited", "npc_attitude_limits")
    _SOFT_ITEMS_FIELDS = ("soft_item_proposals", "soft_item_adjudications")

    # -- default mode (neither combat nor dialogue) --

    def test_combat_excluded_by_default(self) -> None:
        output = render_prose()
        assert self._COMBAT_HEADING not in output
        for field in self._COMBAT_FIELDS:
            assert field not in output, f"'{field}' should be absent"

    def test_dialogue_excluded_by_default(self) -> None:
        output = render_prose()
        assert self._DIALOGUE_HEADING not in output
        for field in self._DIALOGUE_FIELDS:
            assert field not in output, f"'{field}' should be absent"

    def test_soft_items_excluded_by_default(self) -> None:
        output = render_prose()
        assert self._SOFT_ITEMS_HEADING not in output
        for field in self._SOFT_ITEMS_FIELDS:
            assert field not in output, f"'{field}' should be absent"

    # -- combat mode --

    def test_combat_included_when_requested(self) -> None:
        output = render_prose(include_combat=True)
        assert self._COMBAT_HEADING in output
        for field in self._COMBAT_FIELDS:
            assert field in output, f"'{field}' should be present"

    # -- dialogue mode --

    def test_dialogue_included_when_requested(self) -> None:
        output = render_prose(include_dialogue=True)
        assert self._DIALOGUE_HEADING in output
        for field in self._DIALOGUE_FIELDS:
            assert field in output, f"'{field}' should be present"

    # -- soft items mode --

    def test_soft_items_included_when_requested(self) -> None:
        output = render_prose(include_soft_items=True)
        assert self._SOFT_ITEMS_HEADING in output
        for field in self._SOFT_ITEMS_FIELDS:
            assert field in output, f"'{field}' should be present"

    # -- both modes --

    def test_both_included_when_both_requested(self) -> None:
        output = render_prose(include_combat=True, include_dialogue=True)
        assert self._COMBAT_HEADING in output
        assert self._DIALOGUE_HEADING in output

    # -- cross-cutting properties --

    def test_idempotent(self) -> None:
        out1 = render_prose(include_combat=True, include_dialogue=True)
        out2 = render_prose(include_combat=True, include_dialogue=True)
        assert out1 == out2

    def test_default_smaller_than_full(self) -> None:
        default = render_prose()
        full = render_prose(
            include_combat=True, include_dialogue=True, include_soft_items=True
        )
        assert len(default) < len(full)

    def test_core_sections_always_present(self) -> None:
        output = render_prose()
        assert "## Adventure Context" in output
        assert "## Output Format" in output
        assert "## Important Narration Rules" in output
        assert "## General Style Guidelines" in output
