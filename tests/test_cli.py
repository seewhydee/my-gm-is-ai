"""Tests for cli.py — argument parsing and boot sequence."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mgmai.cli import main

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


class TestCliArguments:
    """Tests for CLI argument parsing and validation."""

    def test_no_args_shows_usage(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "")
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Usage" in captured.out or "usage" in captured.out.lower()

    def test_missing_api_key(self, monkeypatch, capsys) -> None:
        monkeypatch.delenv("MGMAI_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            main([str(BAG_OF_HOLDING)])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "MGMAI_API_KEY" in captured.out

    def test_load_nonexistent_file(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        with pytest.raises(SystemExit) as exc_info:
            main([str(BAG_OF_HOLDING), "--load", "nonexistent.json"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_version_flag(self, monkeypatch, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "mgmai" in captured.out


class TestCliBoot:
    """Tests for the CLI boot sequence with mocked dependencies."""

    def test_start_new_game(self, monkeypatch) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop):
            with patch("mgmai.cli.LLMClient"):
                main([str(BAG_OF_HOLDING)])

        mock_loop.start.assert_called_once()

    def test_resume_from_save(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        save_file = tmp_path / "save.json"
        save_file.write_text(
            f'{{"adventure_path": "{BAG_OF_HOLDING}", '
            f'"hard": {{"player": {{"location": "axe_head", "inventory": []}}, '
            f'"flags": {{}}, "room_states": {{}}, "entity_states": {{}}, "turn_count": 0}}, '
            f'"soft": {{"soft_inventory": [], "room_notes": {{}}, "entity_notes": {{}}, '
            f'"npc_revelations": {{}}, "turn_history": [], '
            f'"dialogue_state": {{"active_npc": null, "conversation_log": [], '
            f'"topics_discussed": [], "entered_turn": 0, "stall_counter": 0}}}}}}'
        )
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop):
            with patch("mgmai.cli.LLMClient"):
                main([str(BAG_OF_HOLDING), "--load", str(save_file)])

        mock_loop.start.assert_called_once()

    def test_api_key_from_arg(self, monkeypatch) -> None:
        monkeypatch.delenv("MGMAI_API_KEY", raising=False)
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop):
            with patch("mgmai.cli.LLMClient") as mock_llm_cls:
                main([str(BAG_OF_HOLDING), "--api-key", "arg-key"])

        mock_llm_cls.assert_called_once()
        _, kwargs = mock_llm_cls.call_args
        assert kwargs["api_key"] == "arg-key"

    def test_model_override(self, monkeypatch) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop):
            with patch("mgmai.cli.LLMClient") as mock_llm_cls:
                main([str(BAG_OF_HOLDING), "--model", "gpt-4o"])

        _, kwargs = mock_llm_cls.call_args
        assert kwargs["config"].name == "gpt-4o"

    def test_base_url_override(self, monkeypatch) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        monkeypatch.delenv("MGMAI_BASE_URL", raising=False)
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop):
            with patch("mgmai.cli.LLMClient") as mock_llm_cls:
                main([str(BAG_OF_HOLDING), "--base-url", "https://example.com"])

        _, kwargs = mock_llm_cls.call_args
        assert kwargs["config"].base_url == "https://example.com"

    def test_debug_flag_passed_to_loop(self, monkeypatch) -> None:
        monkeypatch.setenv("MGMAI_API_KEY", "fake-key")
        mock_loop = MagicMock()

        with patch("mgmai.cli.GameLoop", return_value=mock_loop) as mock_loop_cls:
            with patch("mgmai.cli.LLMClient"):
                main([str(BAG_OF_HOLDING), "--debug"])

        _, kwargs = mock_loop_cls.call_args
        assert kwargs["debug"] is True
