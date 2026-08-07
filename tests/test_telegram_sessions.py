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

"""Tests for mgmai/telegram/sessions.py — the SessionRegistry: live
session lifecycle, per-chat save sandboxes, and the persisted index
that drives resume-after-bot-restart."""

from __future__ import annotations

import json
from pathlib import Path

from mgmai.telegram.sessions import SessionRegistry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MINI_ADVENTURE_DIR = FIXTURES_DIR / "mini_adventure"


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


def _make_registry(config_dir, llm=None) -> SessionRegistry:
    return SessionRegistry(config_dir=config_dir, llm_client=llm or _wait_llm())


def _play_turn(registry: SessionRegistry, chat_id: int, text: str = "I wait"):
    return registry.get(chat_id).session.submit(text)


class TestStartNew:
    def test_start_new_renders_intro_and_registers(self, tmp_path):
        registry = _make_registry(tmp_path)
        chat = registry.start_new(123, FIXTURES_DIR)

        assert registry.get(123) is chat
        assert chat.adventure_path == FIXTURES_DIR
        events = chat.view.drain()
        assert [e.kind for e in events] == ["intro"]

    def test_start_new_replaces_live_session(self, tmp_path):
        registry = _make_registry(tmp_path)
        first = registry.start_new(123, FIXTURES_DIR)
        second = registry.start_new(123, FIXTURES_DIR)
        assert registry.get(123) is second
        assert first is not second

    def test_start_new_updates_index(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        index = json.loads(
            (tmp_path / "telegram" / "sessions.json").read_text())
        assert index["123"]["adventure_path"] == str(FIXTURES_DIR.resolve())
        assert index["123"]["last_save"] is None

    def test_per_chat_saves_sandbox(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(1, FIXTURES_DIR)
        registry.start_new(2, FIXTURES_DIR)
        _play_turn(registry, 1)
        _play_turn(registry, 2)
        assert (tmp_path / "telegram" / "1" / "saves" / "fixtures" / "autosave.json").is_file()
        assert (tmp_path / "telegram" / "2" / "saves" / "fixtures" / "autosave.json").is_file()

    def test_save_output_scrubs_absolute_path(self, tmp_path):
        """Commands._cmd_save prints the full save path (fine for the
        CLI); the Telegram view must scrub it down to the filename."""
        registry = _make_registry(tmp_path)
        chat = registry.start_new(123, FIXTURES_DIR)
        chat.view.drain()  # intro
        chat.session.submit("/save mysave.json")
        events = chat.view.drain()
        texts = [e.text for e in events]
        assert any("Game saved to mysave.json" in t for t in texts)
        assert not any(str(tmp_path) in t for t in texts)


class TestAdventureScopedSaves:
    def test_saves_are_scoped_per_adventure(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.start_new(123, MINI_ADVENTURE_DIR)
        _play_turn(registry, 123)
        sandbox = tmp_path / "telegram" / "123" / "saves"
        assert (sandbox / "fixtures" / "autosave.json").is_file()
        assert (sandbox / "mini_adventure" / "autosave.json").is_file()

    def test_list_saves_spans_adventures(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.start_new(123, MINI_ADVENTURE_DIR)
        _play_turn(registry, 123)

        saves = registry.list_saves(123)
        assert {(s.adventure, s.name) for s in saves} == {
            ("fixtures", "autosave.json"),
            ("mini_adventure", "autosave.json"),
        }

    def test_loading_other_adventures_save_switches_adventure(
            self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.start_new(123, MINI_ADVENTURE_DIR)
        assert registry.get(123).adventure_path == MINI_ADVENTURE_DIR

        fixtures_save = next(
            s for s in registry.list_saves(123)
            if s.adventure == "fixtures")
        chat = registry.load_save(123, fixtures_save.path)
        assert chat.adventure_path.resolve() == FIXTURES_DIR.resolve()
        assert chat.session.hard_state.turn_count == 1


class TestLoadSave:
    def test_load_save_restores_state(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        autosave = tmp_path / "telegram" / "123" / "saves" / "fixtures" / "autosave.json"

        chat = registry.load_save(123, autosave)
        assert chat.session.hard_state.turn_count == 1
        # Loading renders no intro.
        assert chat.view.drain() == []

    def test_load_save_replaces_live_session(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        autosave = tmp_path / "telegram" / "123" / "saves" / "fixtures" / "autosave.json"
        _play_turn(registry, 123)

        chat = registry.load_save(123, autosave)
        assert chat.session.hard_state.turn_count == 2

    def test_load_save_updates_index(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        autosave = tmp_path / "telegram" / "123" / "saves" / "fixtures" / "autosave.json"
        registry.load_save(123, autosave)
        entry = registry.saved_session(123)
        assert entry["last_save"] == str(autosave.resolve())

    def test_load_missing_save_raises(self, tmp_path):
        registry = _make_registry(tmp_path)
        import pytest
        with pytest.raises(FileNotFoundError):
            registry.load_save(123, tmp_path / "nope.json")


class TestEnd:
    def test_end_drops_session_but_keeps_index(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.note_save(123)
        registry.end(123)
        assert registry.get(123) is None
        assert registry.saved_session(123) is not None


class TestIndex:
    def test_resume_after_restart(self, tmp_path):
        """A second registry over the same config_dir (i.e. a bot
        restart) sees the persisted index and can resume the autosave."""
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.note_save(123)

        registry2 = _make_registry(tmp_path)
        assert registry2.get(123) is None  # no live session
        saved = registry2.saved_session(123)
        assert saved is not None  # Continue is offered
        assert saved["adventure_path"] == str(FIXTURES_DIR.resolve())

        chat = registry2.load_save(123, saved["last_save"])
        assert chat.session.hard_state.turn_count == 1

    def test_corrupt_index_tolerated(self, tmp_path):
        index_dir = tmp_path / "telegram"
        index_dir.mkdir()
        (index_dir / "sessions.json").write_text("not valid json{")
        registry = _make_registry(tmp_path)
        assert registry.saved_session(123) is None

    def test_wrong_shape_index_tolerated(self, tmp_path):
        index_dir = tmp_path / "telegram"
        index_dir.mkdir()
        (index_dir / "sessions.json").write_text(json.dumps([1, 2, 3]))
        registry = _make_registry(tmp_path)
        assert registry.saved_session(123) is None

    def test_saved_session_none_without_save_file(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)  # no turn → no autosave
        assert registry.saved_session(123) is None
        # ...but the adventure is still indexed (restart buttons work).
        assert registry.indexed_adventure_path(123) == FIXTURES_DIR.resolve()

    def test_note_save_points_at_autosave(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.note_save(123)
        autosave = tmp_path / "telegram" / "123" / "saves" / "fixtures" / "autosave.json"
        assert registry.saved_session(123)["last_save"] == str(autosave.resolve())

    def test_clear_last_save_keeps_adventure(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.note_save(123)
        registry.clear_last_save(123)
        assert registry.saved_session(123) is None
        assert registry.indexed_adventure_path(123) == FIXTURES_DIR.resolve()


class TestListSaves:
    def test_list_saves_newest_first_with_snippet(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.start_new(123, FIXTURES_DIR)
        _play_turn(registry, 123)
        registry.get(123).session.submit("/save mysave.json")

        saves = registry.list_saves(123)
        names = [s.name for s in saves]
        assert "autosave.json" in names
        assert "mysave.json" in names
        # The named save was written after the autosave.
        assert names[0] == "mysave.json"
        mysave = saves[0]
        assert mysave.snippet == "Time passes."
        assert mysave.mtime > 0

    def test_list_saves_empty_sandbox(self, tmp_path):
        registry = _make_registry(tmp_path)
        assert registry.list_saves(123) == []


class TestLocks:
    def test_session_lock_shared_with_registry(self, tmp_path):
        registry = _make_registry(tmp_path)
        chat = registry.start_new(123, FIXTURES_DIR)
        assert registry.get_lock(123) is chat.lock

    def test_lock_survives_session_replacement(self, tmp_path):
        registry = _make_registry(tmp_path)
        first = registry.start_new(123, FIXTURES_DIR)
        second = registry.start_new(123, FIXTURES_DIR)
        assert first.lock is second.lock
