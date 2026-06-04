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
