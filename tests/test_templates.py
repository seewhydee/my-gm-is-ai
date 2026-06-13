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
        assert out1 == out2  # static template
