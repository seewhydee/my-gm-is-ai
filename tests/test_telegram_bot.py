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
``BotRuntime`` core (menus, callbacks, turns), driven with plain fakes
(no PTB, no network)."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from mgmai.telegram.bot import (
    TURN_FAILURE_TEXT,
    BotRuntime,
    adventure_title,
    find_adventures,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MINI_ADVENTURE_DIR = FIXTURES_DIR / "mini_adventure"

ADVENTURES = [
    (FIXTURES_DIR, "You're Trapped in a Bag of Holding!"),
    (MINI_ADVENTURE_DIR, "Mini Test Adventure"),
]


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
        adventures=ADVENTURES,
        llm_client=llm or _wait_llm(),
        allowed_chat_ids=set(chat_ids),
    )


class FakeOutbox:
    """Collects everything BotRuntime sends (ChatOutbox protocol)."""

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.menus: list[tuple[str, list]] = []
        self.edits: list[tuple[str, list | None]] = []
        # Persistent panels: (message_id, text, keyboard) per call.
        self.panel_sends: list[tuple[int, str, list | None]] = []
        self.panel_edits: list[tuple[int, str, list | None]] = []
        self.edit_ok = True  # False simulates an uneditable message
        self._next_panel_id = 0
        self.answered = 0
        self.typing_count = 0

    async def reply(self, text: str) -> None:
        self.replies.append(text)

    async def menu(self, text: str, keyboard: list) -> None:
        self.menus.append((text, keyboard))

    async def edit(self, text: str, keyboard: list | None = None) -> None:
        self.edits.append((text, keyboard))

    async def answer(self, text: str = "") -> None:
        self.answered += 1

    async def typing(self) -> None:
        self.typing_count += 1

    async def send_panel(self, text: str, keyboard: list | None = None) -> int:
        self._next_panel_id += 1
        self.panel_sends.append((self._next_panel_id, text, keyboard))
        return self._next_panel_id

    async def edit_panel(self, message_id: int, text: str,
                         keyboard: list | None = None) -> bool:
        if not self.edit_ok:
            return False
        self.panel_edits.append((message_id, text, keyboard))
        return True

    def panel_texts(self) -> list[str]:
        return ([t for _, t, _ in self.panel_sends]
                + [t for _, t, _ in self.panel_edits])

    def all_text(self) -> str:
        parts = list(self.replies)
        parts += [t for t, _ in self.menus]
        parts += [t for t, _ in self.edits]
        parts += self.panel_texts()
        return "\n".join(parts)

    def all_callback_data(self) -> list[str]:
        return [
            data
            for _, keyboard in [*self.menus, *self.edits]
            for row in (keyboard or [])
            for _, data in row
        ]


def _send(runtime: BotRuntime, chat_id: int, text: str, outbox: FakeOutbox) -> None:
    asyncio.run(runtime.handle_message(chat_id, text, outbox))


def _press(runtime: BotRuntime, chat_id: int, data: str, outbox: FakeOutbox) -> None:
    asyncio.run(runtime.handle_callback(chat_id, data, outbox))


def _start_game(runtime: BotRuntime, chat_id: int, outbox: FakeOutbox,
                adventure: int = 0) -> None:
    """Start a session through the menu flow."""
    _press(runtime, chat_id, f"adv:{adventure}", outbox)


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


class TestAdventureTitle:
    def test_title_from_corpus(self):
        assert adventure_title(FIXTURES_DIR) == \
            "You're Trapped in a Bag of Holding!"

    def test_fallback_to_dir_name(self, tmp_path):
        (tmp_path / "corpus.json").write_text("not json")
        assert adventure_title(tmp_path) == tmp_path.name


class TestAllowList:
    def test_is_allowed(self, tmp_path):
        runtime = _make_runtime(tmp_path, chat_ids=(1, 2))
        assert runtime.is_allowed(1)
        assert runtime.is_allowed(2)
        assert not runtime.is_allowed(3)


class TestMainMenu:
    def test_start_shows_welcome_menu(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        asyncio.run(runtime.send_main_menu(123, outbox, welcome=True))
        (text, keyboard), = outbox.menus
        assert "Welcome" in text
        labels = [label for row in keyboard for label, _ in row]
        assert labels == ["New game", "Help"]  # no Continue without a save

    def test_plain_message_without_session_shows_menu(self, tmp_path):
        """Sessions are created through the menu flow, never lazily."""
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _send(runtime, 123, "I wait", outbox)
        assert runtime.registry.get(123) is None
        (text, _keyboard), = outbox.menus
        assert "What would you like to do?" in text
        assert not outbox.replies

    def test_continue_button_only_with_save(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        _send(runtime, 123, "/quit", outbox)
        # The post-quit main menu offers Continue (autosave exists).
        _text, keyboard = outbox.menus[-1]
        labels = [label for row in keyboard for label, _ in row]
        assert "Continue" in labels


class TestNewGameFlow:
    def test_picker_lists_adventures(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        asyncio.run(runtime.cmd_new(123, outbox))
        (text, keyboard), = outbox.menus
        assert "Choose an adventure" in text
        data = [d for row in keyboard for _, d in row]
        assert data == ["adv:0", "adv:1"]
        labels = [label for row in keyboard for label, _ in row]
        assert labels[0] == "You're Trapped in a Bag of Holding!"
        assert labels[1] == "Mini Test Adventure"

    def test_picking_adventure_delivers_intro(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _press(runtime, 123, "adv:0", outbox)
        assert runtime.registry.get(123) is not None
        assert outbox.answered == 1
        assert any("You're Trapped in a Bag of Holding!" in r
                   for r in outbox.replies)
        # The picker message was edited into a "starting" notice.
        assert any("Starting" in text for text, _ in outbox.edits)

    def test_new_with_live_session_asks_confirmation(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        asyncio.run(runtime.cmd_new(123, outbox))
        text, _keyboard = outbox.menus[-1]
        assert "End the current game" in text
        assert outbox.all_callback_data().count("pick") == 1
        # Confirming shows the picker.
        _press(runtime, 123, "pick", outbox)
        assert any("Choose an adventure" in text for text, _ in outbox.edits)

    def test_second_adventure_starts(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox, adventure=1)
        chat = runtime.registry.get(123)
        assert chat.adventure_path == MINI_ADVENTURE_DIR
        assert any("Mini Test Adventure" in r for r in outbox.replies)


class TestTurns:
    def test_turn_replies_narration_and_status(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        assert "Time passes." in outbox.all_text()
        assert any(r.startswith("  Turn 1") for r in outbox.panel_texts())
        assert outbox.typing_count >= 1

    def test_turn_failure_replies_generic_error(self, tmp_path):
        runtime = _make_runtime(tmp_path, llm=FakeLLMClient())
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        assert TURN_FAILURE_TEXT in outbox.replies

    def test_in_game_slash_commands_route_through_session(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "/help", outbox)
        assert "Available Commands" in outbox.all_text()


class TestQuit:
    def test_quit_ends_session_and_shows_menu(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        asyncio.run(runtime.cmd_quit(123, outbox))
        assert runtime.registry.get(123) is None
        assert "Thanks for playing!" in outbox.all_text()
        # Back at the main menu, with Continue available.
        _text, keyboard = outbox.menus[-1]
        labels = [label for row in keyboard for label, _ in row]
        assert "Continue" in labels

    def test_quit_without_session_shows_menu(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        asyncio.run(runtime.cmd_quit(123, outbox))
        assert runtime.registry.get(123) is None
        assert outbox.menus


class TestContinueResume:
    def test_continue_resumes_autosave(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        _send(runtime, 123, "/quit", outbox)

        outbox2 = FakeOutbox()
        _press(runtime, 123, "menu:continue", outbox2)
        chat = runtime.registry.get(123)
        assert chat is not None
        assert chat.session.hard_state.turn_count == 1
        assert any("Resumed" in text for text, _ in outbox2.edits)
        # A status line follows the resume notice.
        assert any(r.startswith("  Turn 1") for r in outbox2.panel_texts())

    def test_resume_after_bot_restart(self, tmp_path):
        """Phase 2 exit criterion: kill/restart the bot, then continue."""
        runtime1 = _make_runtime(tmp_path)
        outbox1 = FakeOutbox()
        _start_game(runtime1, 123, outbox1)
        _send(runtime1, 123, "I wait", outbox1)

        # New process: fresh runtime over the same config dir.
        runtime2 = _make_runtime(tmp_path)
        assert runtime2.registry.get(123) is None
        outbox2 = FakeOutbox()
        # A bare message offers Continue (from the persisted index).
        _send(runtime2, 123, "hello?", outbox2)
        (_text, keyboard), = outbox2.menus
        labels = [label for row in keyboard for label, _ in row]
        assert "Continue" in labels

        _press(runtime2, 123, "menu:continue", outbox2)
        chat = runtime2.registry.get(123)
        assert chat.session.hard_state.turn_count == 1


class TestRestart:
    def test_restart_flow(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)

        asyncio.run(runtime.cmd_restart(123, outbox))
        text, _keyboard = outbox.menus[-1]
        assert "Restart" in text
        assert "confirm:restart" in outbox.all_callback_data()

        _press(runtime, 123, "confirm:restart", outbox)
        chat = runtime.registry.get(123)
        assert chat.session.hard_state.turn_count == 0
        # The intro is delivered again (once per start).
        intros = [r for r in outbox.replies
                  if "You're Trapped in a Bag of Holding!" in r]
        assert len(intros) == 2


class TestLoadBrowser:
    def test_load_lists_saves_and_loads_one(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        _send(runtime, 123, "/save mysave.json", outbox)

        asyncio.run(runtime.cmd_load(123, outbox))
        text, keyboard = outbox.menus[-1]
        assert "Load a save" in text
        labels = [label for row in keyboard for label, _ in row]
        assert any("autosave.json" in label for label in labels)
        assert any("mysave.json" in label for label in labels)
        # Newest first, and the snippet comes from latest_narration.
        assert "mysave.json" in labels[0]
        assert "Time passes." in labels[0]
        data = [d for row in keyboard for _, d in row]
        assert data == [f"save:{i}" for i in range(len(labels))]

        _press(runtime, 123, "save:0", outbox)
        chat = runtime.registry.get(123)
        assert chat.session.hard_state.turn_count == 1
        assert any("Loaded" in text for text, _ in outbox.edits)

    def test_load_with_no_saves(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        asyncio.run(runtime.cmd_load(123, outbox))
        (text, _), = outbox.menus
        assert "No saves" in text

    def test_browser_labels_include_adventure_when_spanning(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox, adventure=0)
        _send(runtime, 123, "I wait", outbox)
        _start_game(runtime, 123, outbox, adventure=1)
        _send(runtime, 123, "I wait", outbox)

        asyncio.run(runtime.cmd_load(123, outbox))
        _text, keyboard = outbox.menus[-1]
        labels = [label for row in keyboard for label, _ in row]
        assert any(label.startswith("fixtures/autosave.json")
                   for label in labels)
        assert any(label.startswith("mini_adventure/autosave.json")
                   for label in labels)

    def test_stale_save_index(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _press(runtime, 123, "save:9", outbox)
        assert any("no longer available" in text for text, _ in outbox.edits)


class TestGameOver:
    def _win_game(self, runtime: BotRuntime, chat_id: int,
                  outbox: FakeOutbox) -> None:
        # The bag-of-holding win mechanic fires when padlock_unlocked.
        chat = runtime.registry.get(chat_id)
        chat.session.state_manager.hard_state.flags["padlock_unlocked"] = True
        _send(runtime, chat_id, "do something", outbox)

    def test_game_over_sends_final_panel_and_ends_session(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        self._win_game(runtime, 123, outbox)

        assert "Victory" in outbox.all_text()
        assert runtime.registry.get(123) is None
        # Final panel with the three lifecycle buttons.
        _text, keyboard = outbox.menus[-1]
        data = [d for row in keyboard for _, d in row]
        assert data == ["go:restart", "go:load", "go:choose"]
        # The finished game's autosave is not offered as Continue.
        assert runtime.registry.saved_session(123) is None

    def test_game_over_restart_button(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        self._win_game(runtime, 123, outbox)

        _press(runtime, 123, "go:restart", outbox)
        chat = runtime.registry.get(123)
        assert chat is not None
        assert chat.session.hard_state.turn_count == 0

    def test_game_over_choose_adventure_button(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        self._win_game(runtime, 123, outbox)

        _press(runtime, 123, "go:choose", outbox)
        assert any("Choose an adventure" in text for text, _ in outbox.edits)


class TestTwoChats:
    def test_chats_play_independently(self, tmp_path):
        """Phase 2 exit criterion: two chats, one bot process."""
        runtime = _make_runtime(tmp_path, chat_ids=(1, 2))
        o1, o2 = FakeOutbox(), FakeOutbox()
        _start_game(runtime, 1, o1)
        _start_game(runtime, 2, o2)
        _send(runtime, 1, "I wait", o1)
        _send(runtime, 1, "I wait", o1)
        _send(runtime, 2, "I wait", o2)

        c1 = runtime.registry.get(1)
        c2 = runtime.registry.get(2)
        assert c1.session is not c2.session
        assert c1.session.hard_state.turn_count == 2
        assert c2.session.hard_state.turn_count == 1
        # Separate save sandboxes.
        assert (tmp_path / "telegram" / "1" / "saves" / "fixtures" / "autosave.json").is_file()
        assert (tmp_path / "telegram" / "2" / "saves" / "fixtures" / "autosave.json").is_file()

    def test_once_reactions_do_not_leak_across_chats(self, tmp_path):
        """Firing a once-reaction in one chat must not disable it in
        another (cribbed from tests/test_session.py)."""
        from mgmai.engine.event_bus import (
            dispatch_reactions,
            find_matching_reactions,
        )
        from mgmai.models.corpus import Reaction, ReactionEffects, Result

        runtime = _make_runtime(tmp_path, chat_ids=(1, 2))
        o1, o2 = FakeOutbox(), FakeOutbox()
        _start_game(runtime, 1, o1)
        _start_game(runtime, 2, o2)
        m1 = runtime.registry.get(1).session.state_manager
        m2 = runtime.registry.get(2).session.state_manager

        for m in (m1, m2):
            room = m.corpus.rooms[m.hard_state.player.location]
            room.reactions.append(Reaction(
                id="once_react",
                on="flag.set",
                once=True,
                effect=ReactionEffects(result=Result(narrative="once")),
            ))

        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, m1.hard_state, m1.soft_state,
            m1.corpus, disabled_once=m1.disabled_once,
        )
        dispatch_reactions(matches, m1.hard_state, m1.soft_state, m1.corpus, m1)

        assert "once_react" in m1.disabled_once
        assert "once_react" not in m2.disabled_once


class TestCallbackSerialization:
    def test_callback_waits_for_turn_lock(self, tmp_path):
        """Callback queries are handled under the same per-chat lock as
        turns (plan §5.4 step 5)."""
        release = threading.Event()

        class SlowLLM(FakeLLMClient):
            def call_ruling(self, system_prompt, user_prompt):
                release.wait(5)
                return super().call_ruling(system_prompt, user_prompt)

        runtime = _make_runtime(tmp_path, llm=SlowLLM(
            ruling_response=json.dumps({
                "action_type": "wait",
                "detail": "Waiting",
                "follow_up": None,
                "soft_state_patches": [],
            }),
            prose_response=json.dumps({
                "narration": "Time passes.",
                "npc_response": None,
                "knowledge_tags": None,
                "attitude_changes": None,
            }),
        ))
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)

        async def main() -> None:
            turn = asyncio.create_task(
                runtime.handle_message(123, "I wait", outbox))
            await asyncio.sleep(0.2)  # let the turn reach the LLM call
            callback = asyncio.create_task(
                runtime.handle_callback(123, "menu:help", outbox))
            await asyncio.sleep(0.2)
            assert not callback.done()  # blocked on the chat lock
            release.set()
            await asyncio.gather(turn, callback)
            assert callback.done()

        asyncio.run(main())
        # Both button presses were answered (adv:0 and menu:help).
        assert outbox.answered == 2


# ------------------------------------------------------------------
# Phase 3: persistent status/combat panel
# ------------------------------------------------------------------


def _flush_view(runtime: BotRuntime, chat, outbox: FakeOutbox) -> None:
    asyncio.run(runtime._flush(chat, outbox))


class TestStatusPanel:
    def test_first_status_sends_then_edits_in_place(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        chat = runtime.registry.get(123)

        assert len(outbox.panel_sends) == 1
        assert chat.status_message_id == outbox.panel_sends[0][0]
        assert "  Turn 1" in outbox.panel_sends[0][1]

        _send(runtime, 123, "I wait", outbox)
        # Second turn edits the same message; nothing new is sent.
        assert len(outbox.panel_sends) == 1
        (mid, text, _kb), = outbox.panel_edits
        assert mid == chat.status_message_id
        assert "  Turn 2" in text

    def test_identical_status_skips_the_edit(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        chat = runtime.registry.get(123)

        # Re-render the unchanged status and flush again: no API call.
        chat.view.render_status(chat.session.state_manager)
        _flush_view(runtime, chat, outbox)
        assert not outbox.panel_edits
        assert len(outbox.panel_sends) == 1

    def test_combat_panel_pre_block_and_transition(self, tmp_path):
        from mgmai.models.combat import CombatState

        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        chat = runtime.registry.get(123)
        hard = chat.session.state_manager.hard_state
        mid = chat.status_message_id

        # Combat starts: the same message is edited into a <pre> panel.
        hard.combat = CombatState(
            round_number=1,
            initiative_order=["player", "spider"],
            combatants=["player", "spider"],
            active=True,
        )
        chat.view.render_status(chat.session.state_manager)
        _flush_view(runtime, chat, outbox)
        assert len(outbox.panel_sends) == 1  # no new message
        edit_mid, edit_text, _ = outbox.panel_edits[-1]
        assert edit_mid == mid
        assert edit_text.startswith("<pre>")
        assert "Combat" in edit_text

        # Combat ends: the same message becomes the plain status line.
        hard.combat = None
        chat.view.render_status(chat.session.state_manager)
        _flush_view(runtime, chat, outbox)
        assert len(outbox.panel_sends) == 1
        edit_mid, edit_text, _ = outbox.panel_edits[-1]
        assert edit_mid == mid
        assert "<pre>" not in edit_text
        assert "Turn" in edit_text

    def test_uneditable_message_falls_back_to_new_panel(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        chat = runtime.registry.get(123)
        old_mid = chat.status_message_id

        outbox.edit_ok = False  # message too old / deleted
        _send(runtime, 123, "I wait", outbox)
        assert not outbox.panel_edits
        assert len(outbox.panel_sends) == 2
        assert chat.status_message_id != old_mid

    def test_resumed_session_sends_fresh_panel(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "I wait", outbox)
        _send(runtime, 123, "/quit", outbox)

        outbox2 = FakeOutbox()
        _press(runtime, 123, "menu:continue", outbox2)
        # A loaded session has no status message: first render sends one.
        assert len(outbox2.panel_sends) == 1
        assert "  Turn 1" in outbox2.panel_sends[0][1]


# ------------------------------------------------------------------
# Phase 3: rest-mode inline keyboards
# ------------------------------------------------------------------


def _make_rest_chat(runtime: BotRuntime, tmp_path):
    """A chat whose session has a spellbook and hit dice, so rest mode
    offers Prepare spells / Spend hit dice / Done."""
    from mgmai.game.session import GameSession
    from mgmai.models.hard_state import HardGameState, HitDice, PlayerState
    from mgmai.models.soft_state import SoftGameState
    from mgmai.telegram.sessions import ChatSession
    from mgmai.telegram.view import TelegramView
    from tests.helpers import build_state_manager, make_char_sheet_corpus

    player = PlayerState(
        location="axe_head",
        current_hp=4, max_hp=11,
        stats={s: 10 for s in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
        spell_slots={1: 0, 2: 1},
        max_spell_slots={1: 4, 2: 2},
        hit_dice=HitDice(die="d8", current=2, max=5),
        spellbook=["fire_bolt", "mage_armor", "magic_missile"],
        abilities=["fire_bolt", "mage_armor", "magic_missile"],
    )
    sm = build_state_manager(
        make_char_sheet_corpus(), HardGameState(player=player),
        SoftGameState())
    llm = FakeLLMClient(
        ruling_response=json.dumps({
            "action_type": "rest", "kind": "short", "detail": "camp",
            "follow_up": None, "soft_state_patches": [],
        }),
        prose_response=json.dumps({
            "narration": "You take a short rest.",
            "npc_response": None,
            "knowledge_tags": None,
            "attitude_changes": None,
        }),
    )
    view = TelegramView()
    session = GameSession(
        sm, llm, view=view, config_dir=tmp_path,
        saves_dir=runtime.registry.saves_dir_for(123, "game"),
    )
    chat = ChatSession(
        chat_id=123, adventure_path=None, session=session, view=view,
        lock=runtime.registry.get_lock(123),
    )
    runtime.registry.sessions[123] = chat
    return chat


def _rest_keyboard(outbox: FakeOutbox):
    """The keyboard of the most recent rest-panel send/edit."""
    for _mid, _text, keyboard in reversed(
            [*outbox.panel_sends, *outbox.panel_edits]):
        if keyboard is not None:
            return keyboard
    return None


def _labels(keyboard) -> list[str]:
    return [label for row in keyboard for label, _ in row]


class TestRestKeyboards:
    def test_rest_entry_sends_menu_with_keyboard(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        chat = _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)

        assert chat.session.in_rest_mode
        keyboard = _rest_keyboard(outbox)
        assert _labels(keyboard) == [
            "Prepare spells", "Spend hit dice", "Done"]
        assert [d for row in keyboard for _, d in row] == [
            "rest:1", "rest:2", "rest:3"]
        assert chat.rest_message_id is not None

    def test_prepare_toggle_confirm_back(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)

        _press(runtime, 123, "rest:1", outbox)  # Prepare spells
        keyboard = _rest_keyboard(outbox)
        labels = _labels(keyboard)
        assert labels[:3] == ["✅ fire_bolt", "✅ mage_armor",
                              "✅ magic_missile"]
        assert labels[3:] == ["Confirm", "Back"]

        _press(runtime, 123, "rest:2", outbox)  # toggle mage_armor off
        labels = _labels(_rest_keyboard(outbox))
        assert labels[1] == "▫️ mage_armor"

        # Back discards the working selection and returns to the top.
        _press(runtime, 123, "rest:back", outbox)
        labels = _labels(_rest_keyboard(outbox))
        assert labels == ["Prepare spells", "Spend hit dice", "Done"]

        # Re-enter: the toggle was discarded, all prepared again.
        _press(runtime, 123, "rest:1", outbox)
        assert _labels(_rest_keyboard(outbox))[1] == "✅ mage_armor"
        # Confirm applies and returns to the top menu.
        _press(runtime, 123, "rest:2", outbox)  # toggle mage_armor off
        _press(runtime, 123, "rest:0", outbox)
        chat = runtime.registry.get(123)
        assert chat.session.hard_state.player.abilities == [
            "fire_bolt", "magic_missile"]
        assert _labels(_rest_keyboard(outbox)) == [
            "Prepare spells", "Spend hit dice", "Done"]

    def test_spend_and_done_exits(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        chat = _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)
        hard = chat.session.hard_state

        _press(runtime, 123, "rest:2", outbox)  # Spend hit dice
        assert hard.player.hit_dice.current == 1
        assert _labels(_rest_keyboard(outbox)) == [
            "Spend another hit die", "Done"]

        _press(runtime, 123, "rest:2", outbox)  # Done → top menu
        assert _labels(_rest_keyboard(outbox)) == [
            "Prepare spells", "Spend hit dice", "Done"]

        _press(runtime, 123, "rest:3", outbox)  # Done → exit rest mode
        assert not chat.session.in_rest_mode
        # Keyboard torn down, menu message edited to the farewell text,
        # tracking cleared (a future rest sends a fresh menu message).
        _mid, text, keyboard = outbox.panel_edits[-1]
        assert "ready yourself" in text
        assert keyboard is None
        assert chat.rest_message_id is None

    def test_typed_numbers_still_work(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        chat = _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)
        _send(runtime, 123, "1", outbox)  # typed: Prepare spells
        labels = _labels(_rest_keyboard(outbox))
        assert labels[0].startswith("✅")
        assert chat.session.rest_mode.menu().state == "prepare"

    def test_stale_rest_button(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        chat = _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)
        _press(runtime, 123, "rest:3", outbox)  # exit rest mode
        outbox.edits.clear()
        _press(runtime, 123, "rest:1", outbox)  # stale button
        assert any("no longer active" in text for text, _ in outbox.edits)
        assert not chat.session.in_rest_mode

    def test_rest_steps_autosave(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _make_rest_chat(runtime, tmp_path)
        _send(runtime, 123, "rest short", outbox)
        _press(runtime, 123, "rest:2", outbox)  # spend one hit die
        autosave = (tmp_path / "telegram" / "123" / "saves" / "game"
                    / "autosave.json")
        saved = json.loads(autosave.read_text())
        assert saved["hard"]["player"]["hit_dice"]["current"] == 1
        entry = runtime.registry.saved_session(123)
        assert entry is not None


class TestCommandOutputMarkup:
    def test_help_output_is_converted_to_html(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        outbox = FakeOutbox()
        _start_game(runtime, 123, outbox)
        _send(runtime, 123, "/help", outbox)
        assert any("<b>Available Commands</b>" in r for r in outbox.replies)
        assert not any("[bold]" in r for r in outbox.replies)
