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

"""Smoke tests for mgmai/telegram/bot.py — the PTB-independent
``BotRuntime`` core, driven with plain fakes (no PTB, no network)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mgmai.telegram.bot import (
    TURN_FAILURE_TEXT,
    BotRuntime,
    find_adventures,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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


def _make_runtime(tmp_path, llm=None, chat_ids=(123,)) -> BotRuntime:
    return BotRuntime(
        config_dir=tmp_path,
        adventure_path=FIXTURES_DIR,
        llm_client=llm or _wait_llm(),
        allowed_chat_ids=set(chat_ids),
    )


class _FakeChat:
    """Collects replies and typing heartbeats."""

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.typing_count = 0

    async def reply(self, text: str) -> None:
        self.replies.append(text)

    async def typing(self) -> None:
        self.typing_count += 1


def _send(runtime: BotRuntime, chat_id: int, text: str, chat: _FakeChat) -> None:
    asyncio.run(runtime.handle_message(
        chat_id, text, reply=chat.reply, typing=chat.typing))


class TestFindAdventures:
    def test_finds_corpus_dirs(self, tmp_path):
        adv = tmp_path / "b-adventure"
        adv.mkdir()
        (adv / "corpus.json").write_text("{}")
        (tmp_path / "a-adventure").mkdir()
        ((tmp_path / "a-adventure") / "corpus.json").write_text("{}")
        (tmp_path / "not-an-adventure").mkdir()
        assert [p.name for p in find_adventures(tmp_path)] == [
            "a-adventure", "b-adventure"]

    def test_missing_dir_returns_empty(self, tmp_path):
        assert find_adventures(tmp_path / "nope") == []


class TestAllowList:
    def test_is_allowed(self, tmp_path):
        runtime = _make_runtime(tmp_path, chat_ids=(1, 2))
        assert runtime.is_allowed(1)
        assert runtime.is_allowed(2)
        assert not runtime.is_allowed(3)


class TestHandleMessage:
    def test_first_message_starts_session_and_replies(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        chat = _FakeChat()
        _send(runtime, 123, "I wait", chat)

        assert 123 in runtime.sessions
        assert chat.typing_count >= 1
        # Intro (from begin()) comes first, then narration, then status.
        joined = "\n".join(chat.replies)
        assert "You're Trapped in a Bag of Holding!" in chat.replies[0]
        assert "Time passes." in joined
        assert any(r.startswith("  Turn 1") for r in chat.replies)

    def test_per_chat_saves_sandbox_autosave(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        chat = _FakeChat()
        _send(runtime, 123, "I wait", chat)
        autosave = tmp_path / "telegram" / "123" / "saves" / "autosave.json"
        assert autosave.is_file()

    def test_second_message_reuses_session(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        chat = _FakeChat()
        _send(runtime, 123, "I wait", chat)
        n_replies = len(chat.replies)
        session = runtime.sessions[123].session
        _send(runtime, 123, "I wait again", chat)
        assert runtime.sessions[123].session is session
        # No intro is re-sent on the second message.
        new = chat.replies[n_replies:]
        assert not any("You're Trapped" in r for r in new)
        assert any("Time passes." in r for r in new)

    def test_turn_failure_replies_generic_error(self, tmp_path):
        runtime = _make_runtime(tmp_path, llm=FakeLLMClient())
        chat = _FakeChat()
        _send(runtime, 123, "I wait", chat)
        assert TURN_FAILURE_TEXT in chat.replies

    def test_chats_have_independent_sessions(self, tmp_path):
        runtime = _make_runtime(tmp_path, chat_ids=(1, 2))
        c1, c2 = _FakeChat(), _FakeChat()
        _send(runtime, 1, "I wait", c1)
        _send(runtime, 2, "I wait", c2)
        assert runtime.sessions[1].session is not runtime.sessions[2].session
        # Each chat autosaves into its own sandbox.
        assert (tmp_path / "telegram" / "1" / "saves" / "autosave.json").is_file()
        assert (tmp_path / "telegram" / "2" / "saves" / "autosave.json").is_file()
