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

"""Telegram bot front-end: PTB application setup and message handlers.

Phase 3: menu-driven session lifecycle (Phase 2) plus UI polish —
persistent in-place-edited status/combat panel, rest-mode inline
keyboards, and Rich-markup → Telegram-HTML conversion of command
output.

Importing this module does not require python-telegram-bot; the PTB
import is deferred to ``main()``.  The turn-driving core
(``BotRuntime``) is PTB-free and unit-testable with plain fakes: all
outbound traffic flows through a ``ChatOutbox``.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Protocol

from mgmai.logging import setup_logging
from mgmai.telegram.keyboards import (
    Keyboard,
    adventure_picker_keyboard,
    back_to_menu_keyboard,
    confirm_keyboard,
    game_over_keyboard,
    main_menu_keyboard,
    rest_menu_keyboard,
    save_browser_keyboard,
)
from mgmai.telegram.sessions import ChatSession, SessionRegistry
from mgmai.telegram.textutil import (
    chunk_message,
    md_to_telegram_html,
    rich_to_telegram_html,
)

log = logging.getLogger(__name__)

REFUSAL_TEXT = "Sorry, this is a private bot — you're not on the guest list."

WELCOME_TEXT = (
    "Welcome to <b>My GM is AI</b> — an AI game master for tabletop "
    "adventures.\n\nWhat would you like to do?"
)

MAIN_MENU_TEXT = "What would you like to do?"

GAME_OVER_MENU_TEXT = "The adventure is over. What next?"

HELP_TEXT = (
    "<b>How to play</b>\n"
    "Type what your character does in natural language — each message "
    "is one turn.  Classic shortcuts work unchanged: n, s, e, w, "
    "x spider, i, c, z, …\n"
    "\n"
    "<b>Session commands</b>\n"
    "/new — start a new adventure\n"
    "/load — load a saved game\n"
    "/save [name] — save the game\n"
    "/restart — restart the current adventure\n"
    "/quit — end the session\n"
    "\n"
    "<b>In-game commands</b>\n"
    "/status, /inv, /char, /help — status, inventory, character, help\n"
    "/model — show model config (switching stays in the config files)"
)

TURN_FAILURE_TEXT = (
    "Sorry, something went wrong while processing that turn. "
    "Please try again."
)

# Interval between typing-indicator heartbeats (Telegram's indicator
# lasts ~5 s; a turn is typically 5–30 s).
_TYPING_INTERVAL = 4.0


def find_adventures(adventures_dir: Path) -> list[Path]:
    """Adventures under *adventures_dir* (subdirectories with corpus.json),
    sorted by name.  Returns an empty list if the directory is unusable."""
    try:
        entries = list(adventures_dir.iterdir())
    except OSError:
        return []
    return sorted(
        p for p in entries
        if p.is_dir() and (p / "corpus.json").is_file()
    )


def adventure_title(adventure_path: Path) -> str:
    """The adventure's display title (corpus.adventure.title), falling
    back to the directory name."""
    try:
        data = json.loads(
            (adventure_path / "corpus.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return adventure_path.name
    title = data.get("adventure", {}).get("title")
    return title if isinstance(title, str) and title else adventure_path.name


class ChatOutbox(Protocol):
    """What ``BotRuntime`` needs from a chat connection.

    All text passed to ``reply``/``menu``/``edit`` is Telegram HTML —
    the runtime converts game output with ``md_to_telegram_html`` and
    authors menu text with explicit tags (escaping dynamic parts); the
    PTB adapter sends everything with HTML parse mode.  Keyboards are
    the PTB-free ``Keyboard`` rows from ``keyboards.py``.
    """

    async def reply(self, text: str) -> None:
        """Send a plain message."""
        ...

    async def menu(self, text: str, keyboard: Keyboard) -> None:
        """Send a new message with an inline keyboard."""
        ...

    async def edit(self, text: str, keyboard: Keyboard | None = None) -> None:
        """Replace the menu message a button was pressed on (for
        message-driven flows: send a new message)."""
        ...

    async def answer(self, text: str = "") -> None:
        """Acknowledge a callback query (no-op for messages)."""
        ...

    async def typing(self) -> None:
        """Send one typing indicator."""
        ...

    async def send_panel(self, text: str,
                         keyboard: Keyboard | None = None) -> int:
        """Send a persistent panel message; returns its message id."""
        ...

    async def edit_panel(self, message_id: int, text: str,
                         keyboard: Keyboard | None = None) -> bool:
        """Edit a persistent panel in place.  Returns False when the
        message can no longer be edited (too old / deleted), so the
        caller falls back to sending a new one; an unchanged-content
        edit is treated as success."""
        ...


class BotRuntime:
    """Session lifecycle and turn pipeline, independent of PTB.

    The PTB handlers are thin adapters over this class; unit tests
    drive it directly with a fake ``ChatOutbox``.  Lifecycle (live
    sessions, the persisted index, per-chat save sandboxes and locks)
    is owned by the ``SessionRegistry``.
    """

    def __init__(
        self,
        *,
        config_dir: Path,
        adventures: list[tuple[Path, str]],
        llm_client: Any,
        allowed_chat_ids: set[int],
        prose_validation_enabled: bool = True,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.adventures = list(adventures)
        self.allowed_chat_ids = set(allowed_chat_ids)
        self.registry = SessionRegistry(
            config_dir=self.config_dir,
            llm_client=llm_client,
            prose_validation_enabled=prose_validation_enabled,
        )

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.allowed_chat_ids

    # --- menus ---

    async def send_main_menu(
        self,
        chat_id: int,
        outbox: ChatOutbox,
        *,
        welcome: bool = False,
        edit: bool = False,
    ) -> None:
        text = WELCOME_TEXT if welcome else MAIN_MENU_TEXT
        keyboard = main_menu_keyboard(
            has_save=self.registry.saved_session(chat_id) is not None)
        if edit:
            await outbox.edit(text, keyboard)
        else:
            await outbox.menu(text, keyboard)

    async def send_picker(
        self, chat_id: int, outbox: ChatOutbox, *, edit: bool = False
    ) -> None:
        send = outbox.edit if edit else outbox.menu
        if not self.adventures:
            await send("No adventures are configured.",
                       back_to_menu_keyboard())
            return
        titles = [title for _, title in self.adventures]
        await send("Choose an adventure:", adventure_picker_keyboard(titles))

    # --- lifecycle commands ---

    async def cmd_new(
        self, chat_id: int, outbox: ChatOutbox, *, edit: bool = False
    ) -> None:
        """New game: confirm when a session is live, then the picker."""
        send = outbox.edit if edit else outbox.menu
        if self.registry.get(chat_id) is not None:
            await send(
                "End the current game and start a new one?",
                confirm_keyboard("Yes, end it", "pick"),
            )
            return
        await self.send_picker(chat_id, outbox, edit=edit)

    async def cmd_restart(self, chat_id: int, outbox: ChatOutbox) -> None:
        adventure_path = self.registry.indexed_adventure_path(chat_id)
        if adventure_path is None:
            await self.send_main_menu(chat_id, outbox)
            return
        await outbox.menu(
            f"Restart <b>{html.escape(adventure_path.name)}</b> from the "
            "beginning?\nUnsaved progress will be lost.",
            confirm_keyboard("Yes, restart", "confirm:restart"),
        )

    async def cmd_load(
        self, chat_id: int, outbox: ChatOutbox, *, edit: bool = False
    ) -> None:
        send = outbox.edit if edit else outbox.menu
        saves = self.registry.list_saves(chat_id)
        if not saves:
            await send("No saves found.", back_to_menu_keyboard())
            return
        await send("Load a save:", save_browser_keyboard(saves))

    async def cmd_quit(self, chat_id: int, outbox: ChatOutbox) -> None:
        if self.registry.get(chat_id) is None:
            await self.send_main_menu(chat_id, outbox)
            return
        # Route through the session so /quit's own logic (final autosave
        # + goodbye) runs exactly as in the CLI.
        await self.handle_message(chat_id, "/quit", outbox)

    # --- message flow ---

    async def handle_message(
        self, chat_id: int, text: str, outbox: ChatOutbox
    ) -> None:
        """Process one incoming game message end to end.

        Without a live session the chat gets the main menu (sessions are
        created through the menu flow, never lazily).  The per-chat lock
        serializes turns so a queued second message waits rather than
        interleaving.
        """
        chat = self.registry.get(chat_id)
        if chat is None:
            await self.send_main_menu(chat_id, outbox)
            return
        async with chat.lock:
            heartbeat = asyncio.create_task(self._typing_loop(outbox.typing))
            try:
                result = await asyncio.to_thread(chat.session.submit, text)
            except Exception:
                log.exception("Turn failed for chat %d", chat_id)
                await outbox.reply(TURN_FAILURE_TEXT)
                return
            finally:
                heartbeat.cancel()
            # Point the index's last_save at the autosave (written every
            # turn; also covers /save submits).
            self.registry.note_save(chat_id)
            await self._flush(chat, outbox)
            if chat.session.finished:
                self.registry.end(chat_id)
                if result.game_over:
                    # The autosave captured a finished game; it must not
                    # be offered as Continue.
                    self.registry.clear_last_save(chat_id)
                    await outbox.menu(GAME_OVER_MENU_TEXT, game_over_keyboard())
                else:
                    # /quit: back to the main menu.
                    await self.send_main_menu(chat_id, outbox)

    async def handle_callback(
        self, chat_id: int, data: str, outbox: ChatOutbox
    ) -> None:
        """Process one inline-button press, under the same per-chat lock
        as turns (plan §5.4 step 5).  The query is always answered."""
        try:
            async with self.registry.get_lock(chat_id):
                await self._dispatch_callback(chat_id, data, outbox)
        except Exception:
            log.exception("Callback %r failed for chat %d", data, chat_id)
            try:
                await outbox.reply(TURN_FAILURE_TEXT)
            except Exception:
                log.debug("Callback error reply failed", exc_info=True)
        try:
            await outbox.answer()
        except Exception:
            log.debug("answer_callback_query failed", exc_info=True)

    async def _dispatch_callback(
        self, chat_id: int, data: str, outbox: ChatOutbox
    ) -> None:
        if data == "menu:main":
            await self.send_main_menu(chat_id, outbox, edit=True)
        elif data == "menu:new":
            await self.cmd_new(chat_id, outbox, edit=True)
        elif data == "menu:continue":
            await self._continue_saved(chat_id, outbox)
        elif data == "menu:help":
            await outbox.edit(HELP_TEXT, back_to_menu_keyboard())
        elif data == "pick":
            await self.send_picker(chat_id, outbox, edit=True)
        elif data.startswith("adv:"):
            await self._start_adventure(chat_id, data[len("adv:"):], outbox)
        elif data in ("confirm:restart", "go:restart"):
            await self._restart_current(chat_id, outbox)
        elif data == "go:load":
            await self.cmd_load(chat_id, outbox, edit=True)
        elif data == "go:choose":
            await self.send_picker(chat_id, outbox, edit=True)
        elif data.startswith("save:"):
            await self._load_save_index(chat_id, data[len("save:"):], outbox)
        elif data.startswith("rest:"):
            await self._rest_action(chat_id, data[len("rest:"):], outbox)
        else:
            log.warning("Unknown callback data: %r", data)

    # --- callback actions ---

    async def _start_adventure(
        self, chat_id: int, index: str, outbox: ChatOutbox
    ) -> None:
        try:
            adventure_path, title = self.adventures[int(index)]
        except (ValueError, IndexError):
            await outbox.edit("That adventure is no longer available.",
                              back_to_menu_keyboard())
            return
        chat = await asyncio.to_thread(
            self.registry.start_new, chat_id, adventure_path)
        await outbox.edit(f"Starting <b>{html.escape(title)}</b>…")
        await self._flush(chat, outbox)

    async def _continue_saved(self, chat_id: int, outbox: ChatOutbox) -> None:
        saved = self.registry.saved_session(chat_id)
        if saved is None:
            await self.send_main_menu(chat_id, outbox, edit=True)
            return
        try:
            chat = await asyncio.to_thread(
                self.registry.load_save, chat_id, saved["last_save"])
        except (OSError, ValueError) as e:
            log.warning("Chat %d: failed to load save: %s", chat_id, e)
            await outbox.edit(f"Could not load the save: {e}",
                              back_to_menu_keyboard())
            return
        await self._resume(chat_id, chat, outbox)

    async def _restart_current(self, chat_id: int, outbox: ChatOutbox) -> None:
        adventure_path = self.registry.indexed_adventure_path(chat_id)
        if adventure_path is None:
            await self.send_main_menu(chat_id, outbox, edit=True)
            return
        chat = await asyncio.to_thread(
            self.registry.start_new, chat_id, adventure_path)
        await outbox.edit(
            f"Restarted <b>{html.escape(adventure_path.name)}</b> "
            "from the beginning.")
        await self._flush(chat, outbox)

    async def _load_save_index(
        self, chat_id: int, index: str, outbox: ChatOutbox
    ) -> None:
        saves = self.registry.list_saves(chat_id)
        try:
            save = saves[int(index)]
        except (ValueError, IndexError):
            await outbox.edit("That save is no longer available.",
                              back_to_menu_keyboard())
            return
        try:
            chat = await asyncio.to_thread(
                self.registry.load_save, chat_id, save.path)
        except (OSError, ValueError) as e:
            log.warning("Chat %d: failed to load save: %s", chat_id, e)
            await outbox.edit(f"Could not load the save: {e}",
                              back_to_menu_keyboard())
            return
        await outbox.edit(f"Loaded <b>{html.escape(save.name)}</b>.")
        chat.view.render_status(chat.session.state_manager)
        await self._flush(chat, outbox)

    async def _resume(
        self, chat_id: int, chat: ChatSession, outbox: ChatOutbox
    ) -> None:
        corpus = chat.session.corpus
        title = corpus.adventure.title if corpus else "the adventure"
        await outbox.edit(f"Resumed <b>{html.escape(title)}</b>.")
        chat.view.render_status(chat.session.state_manager)
        await self._flush(chat, outbox)

    async def _rest_action(
        self, chat_id: int, arg: str, outbox: ChatOutbox
    ) -> None:
        """A rest-menu button press: the index maps to
        ``RestMode.handle(str(index))``, driven through
        ``session.submit`` so rest-mode steps keep their autosave."""
        chat = self.registry.get(chat_id)
        if chat is None or not chat.session.in_rest_mode:
            await outbox.edit("That rest menu is no longer active.")
            return
        await asyncio.to_thread(chat.session.submit, arg)
        self.registry.note_save(chat_id)
        await self._flush(chat, outbox)

    # --- helpers ---

    async def _flush(self, chat: ChatSession, outbox: ChatOutbox) -> None:
        """Send the view's buffered events to the chat, in order.

        Markup split: narration-style events carry minimal Markdown
        (``md_to_telegram_html``); command output (kind ``print``)
        carries Rich markup (``rich_to_telegram_html``).  Status and
        rest-menu events go to their persistent panels (edited in
        place) rather than being reposted.
        """
        for event in chat.view.drain():
            if event.kind == "status":
                await self._flush_status(chat, outbox, event.text,
                                         pre=event.pre)
            elif event.kind == "rest_menu":
                await self._flush_rest_menu(chat, outbox, event.text)
            else:
                for chunk in chunk_message(event.text):
                    await outbox.reply(self._event_html(event.kind, chunk))

    @staticmethod
    def _event_html(kind: str, text: str) -> str:
        if kind == "print":
            return rich_to_telegram_html(text)
        return md_to_telegram_html(text)

    async def _flush_status(
        self, chat: ChatSession, outbox: ChatOutbox, text: str, *,
        pre: bool,
    ) -> None:
        """The status/combat panel: one persistent message per chat,
        edited in place between turns.  Combat panels are wrapped in a
        ``<pre>`` block so the HP bars align; the out-of-combat status
        line is plain text (edited into the same message when combat
        ends, so no stale battle panel lingers)."""
        if pre:
            html_text = f"<pre>{html.escape(text, quote=False)}</pre>"
        else:
            html_text = md_to_telegram_html(text)
        if (chat.status_message_id is not None
                and chat.status_message_text == html_text):
            return  # unchanged: skip the no-op edit
        if chat.status_message_id is not None and await outbox.edit_panel(
                chat.status_message_id, html_text):
            chat.status_message_text = html_text
            return
        chat.status_message_id = await outbox.send_panel(html_text)
        chat.status_message_text = html_text

    async def _flush_rest_menu(
        self, chat: ChatSession, outbox: ChatOutbox, text: str
    ) -> None:
        """The rest-mode menu: a persistent message with an inline
        keyboard while rest mode is active; edited to the farewell text
        (keyboard removed) when rest mode exits."""
        rest_mode = chat.session.rest_mode
        if chat.session.in_rest_mode and rest_mode is not None:
            keyboard = rest_menu_keyboard(rest_mode.menu())
        else:
            keyboard = None
        html_text = md_to_telegram_html(text)
        if chat.rest_message_id is None:
            if keyboard is None:
                # No menu message to update (e.g. rest menu text
                # rendered before any keyboard was shown).
                await outbox.reply(html_text)
                return
            chat.rest_message_id = await outbox.send_panel(
                html_text, keyboard)
            chat.rest_message_text = html_text
            chat.rest_message_keyboard = keyboard
            return
        if (chat.rest_message_text == html_text
                and chat.rest_message_keyboard == keyboard):
            return  # unchanged: skip the no-op edit
        if await outbox.edit_panel(
                chat.rest_message_id, html_text, keyboard):
            chat.rest_message_text = html_text
            chat.rest_message_keyboard = keyboard
        else:
            chat.rest_message_id = await outbox.send_panel(
                html_text, keyboard)
            chat.rest_message_text = html_text
            chat.rest_message_keyboard = keyboard
        if keyboard is None:
            # Rest mode exited: tear the panel tracking down (the
            # message stays, edited to the farewell text).
            chat.rest_message_id = None
            chat.rest_message_text = None
            chat.rest_message_keyboard = None

    @staticmethod
    async def _typing_loop(typing) -> None:
        """Send typing indicators until cancelled."""
        while True:
            try:
                await typing()
            except Exception:
                log.debug("Typing indicator failed", exc_info=True)
                return
            await asyncio.sleep(_TYPING_INTERVAL)


def _abort(message: str) -> None:
    """Abort bot startup with a clear message."""
    print(f"mgmai-telegram: error: {message}", file=sys.stderr)
    sys.exit(1)


def _resolve_token(credentials: Any) -> str:
    token = os.environ.get("MGMAI_TELEGRAM_BOT_TOKEN")
    if token:
        return token
    return credentials.telegram_bot_token or ""


def main(argv: list[str] | None = None) -> None:
    try:
        from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.error import BadRequest
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        _abort(
            "python-telegram-bot is not installed. "
            "Install it with: pip install 'mgmai[telegram]'"
        )

    from dataclasses import replace

    from mgmai.config import (
        get_config_dir,
        load_app_config,
        load_credentials,
        resolve_api_key,
    )
    from mgmai.llm.client import LLMClient
    from mgmai.llm.model_config import (
        get_model_config,
        get_provider,
        load_custom_models,
    )

    setup_logging(level="INFO")
    # Keep PTB/httpx chatter out of the logs (and the token out of DEBUG
    # request dumps).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    config_dir = get_config_dir()
    app_config = load_app_config(config_dir)
    credentials = load_credentials(config_dir)
    custom_models = load_custom_models(config_dir)

    token = _resolve_token(credentials)
    if not token:
        _abort(
            "No bot token. Set MGMAI_TELEGRAM_BOT_TOKEN, or add a "
            f'"telegram": {{"bot_token": ...}} section to '
            f"{get_config_dir() / 'credentials.json'}."
        )

    allowed_chat_ids = set(app_config.telegram_allowed_chat_ids)
    if not allowed_chat_ids:
        _abort(
            "telegram_allowed_chat_ids is empty or missing in config.json. "
            "An allow-list is mandatory — a public bot is an open proxy "
            "to the LLM API budget."
        )

    adventures_dir = app_config.telegram_adventures_dir
    if not adventures_dir:
        _abort(
            "telegram_adventures_dir is not set in config.json. "
            "Point it at a directory containing adventures "
            "(subdirectories with corpus.json), e.g. ./adventures."
        )
    adventures = [
        (path, adventure_title(path))
        for path in find_adventures(Path(adventures_dir).expanduser())
    ]
    if not adventures:
        _abort(f"No adventures found in {adventures_dir}.")
    log.info("Adventures: %s",
             ", ".join(title for _, title in adventures))

    # LLM config, resolved once via the CLI's resolution chain (env →
    # config file).  No interactive prompting: missing config aborts.
    model_name = os.environ.get("MGMAI_MODEL") or app_config.model_name
    base_url = os.environ.get("MGMAI_BASE_URL") or app_config.base_url
    provider = get_provider(model_name, base_url=base_url,
                            custom_models=custom_models)
    api_key = resolve_api_key(env_var=os.environ.get("MGMAI_API_KEY"),
                              credentials=credentials, provider=provider)
    if not api_key:
        _abort(
            "Missing LLM API key. Set MGMAI_API_KEY, or add a key for "
            f"provider '{provider}' to credentials.json."
        )
    try:
        model_config = get_model_config(model_name, base_url=base_url,
                                        custom_models=custom_models)
    except ValueError as e:
        _abort(str(e))
    if not model_config.base_url:
        _abort(
            f"No base URL for model '{model_name}'. Set MGMAI_BASE_URL, "
            "or base_url in config.json."
        )
    if app_config.ruling_temperature is not None:
        model_config = replace(
            model_config, ruling_temperature=app_config.ruling_temperature)
    if app_config.prose_temperature is not None:
        model_config = replace(
            model_config, prose_temperature=app_config.prose_temperature)

    llm_client = LLMClient(api_key=api_key, config=model_config)

    runtime = BotRuntime(
        config_dir=config_dir,
        adventures=adventures,
        llm_client=llm_client,
        allowed_chat_ids=allowed_chat_ids,
        prose_validation_enabled=app_config.prose_validation_enabled,
    )

    def _markup(keyboard: Keyboard | None) -> Any:
        if not keyboard:
            return None
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(label, callback_data=data)
             for label, data in row]
            for row in keyboard
        ])

    async def _edit_message(bot: Any, chat_id: int, message_id: int,
                            text: str, keyboard: Keyboard | None) -> bool:
        """edit_message_text with the panel semantics: unchanged content
        counts as success; an uneditable message returns False."""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text,
                parse_mode="HTML", reply_markup=_markup(keyboard))
            return True
        except BadRequest as e:
            msg = str(e).lower()
            if "not modified" in msg:
                return True
            if "not found" in msg or "can't be edited" in msg \
                    or "too old" in msg:
                return False
            raise

    class _MessageOutbox:
        """ChatOutbox over an incoming message (nothing to edit/answer)."""

        def __init__(self, message: Any, bot: Any) -> None:
            self._message = message
            self._bot = bot

        async def reply(self, text: str) -> None:
            await self._message.reply_text(text, parse_mode="HTML")

        async def menu(self, text: str, keyboard: Keyboard) -> None:
            await self._message.reply_text(
                text, parse_mode="HTML", reply_markup=_markup(keyboard))

        async def edit(self, text: str, keyboard: Keyboard | None = None) -> None:
            await self.menu(text, keyboard or [])

        async def answer(self, text: str = "") -> None:
            return None

        async def typing(self) -> None:
            await self._bot.send_chat_action(
                chat_id=self._message.chat_id, action="typing")

        async def send_panel(self, text: str,
                             keyboard: Keyboard | None = None) -> int:
            sent = await self._message.reply_text(
                text, parse_mode="HTML", reply_markup=_markup(keyboard))
            return sent.message_id

        async def edit_panel(self, message_id: int, text: str,
                             keyboard: Keyboard | None = None) -> bool:
            return await _edit_message(
                self._bot, self._message.chat_id, message_id, text, keyboard)

    class _CallbackOutbox:
        """ChatOutbox over a callback query: edits the menu message."""

        def __init__(self, query: Any, bot: Any) -> None:
            self._query = query
            self._bot = bot

        async def reply(self, text: str) -> None:
            await self._query.message.reply_text(text, parse_mode="HTML")

        async def menu(self, text: str, keyboard: Keyboard) -> None:
            await self._query.message.reply_text(
                text, parse_mode="HTML", reply_markup=_markup(keyboard))

        async def edit(self, text: str, keyboard: Keyboard | None = None) -> None:
            await self._query.edit_message_text(
                text, parse_mode="HTML", reply_markup=_markup(keyboard))

        async def answer(self, text: str = "") -> None:
            await self._query.answer(text=text or None)

        async def typing(self) -> None:
            await self._bot.send_chat_action(
                chat_id=self._query.message.chat_id, action="typing")

        async def send_panel(self, text: str,
                             keyboard: Keyboard | None = None) -> int:
            sent = await self._query.message.reply_text(
                text, parse_mode="HTML", reply_markup=_markup(keyboard))
            return sent.message_id

        async def edit_panel(self, message_id: int, text: str,
                             keyboard: Keyboard | None = None) -> bool:
            return await _edit_message(
                self._bot, self._query.message.chat_id, message_id,
                text, keyboard)

    def _allowed_chat_id(update: Any) -> int | None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None or not runtime.is_allowed(chat_id):
            return None
        return chat_id

    async def _on_start(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = _allowed_chat_id(update)
        if chat_id is None:
            if update.message is not None:
                await update.message.reply_text(REFUSAL_TEXT)
            return
        await runtime.send_main_menu(
            chat_id, _MessageOutbox(update.message, context.bot), welcome=True)

    async def _on_new(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = _allowed_chat_id(update)
        if chat_id is not None:
            await runtime.cmd_new(
                chat_id, _MessageOutbox(update.message, context.bot))

    async def _on_load(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = _allowed_chat_id(update)
        if chat_id is not None:
            await runtime.cmd_load(
                chat_id, _MessageOutbox(update.message, context.bot))

    async def _on_restart(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = _allowed_chat_id(update)
        if chat_id is not None:
            await runtime.cmd_restart(
                chat_id, _MessageOutbox(update.message, context.bot))

    async def _on_quit(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = _allowed_chat_id(update)
        if chat_id is not None:
            await runtime.cmd_quit(
                chat_id, _MessageOutbox(update.message, context.bot))

    async def _on_text(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or not message.text or update.effective_chat is None:
            return
        chat_id = update.effective_chat.id
        if not runtime.is_allowed(chat_id):
            await message.reply_text(REFUSAL_TEXT)
            return
        # /debug flips the process-global logger level and would affect
        # every chat, so it is refused here (plan §4.6/§5.5).
        if message.text.strip().lower().startswith("/debug"):
            await message.reply_text("/debug is disabled on Telegram.")
            return
        await runtime.handle_message(
            chat_id, message.text,
            _MessageOutbox(message, context.bot),
        )

    async def _on_callback(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        chat_id = _allowed_chat_id(update)
        if chat_id is None:
            await query.answer()
            return
        await runtime.handle_callback(
            chat_id, query.data or "",
            _CallbackOutbox(query, context.bot),
        )

    async def _post_init(app: Any) -> None:
        await app.bot.set_my_commands([
            BotCommand("start", "Welcome and main menu"),
            BotCommand("new", "Start a new adventure"),
            BotCommand("load", "Load a saved game"),
            BotCommand("save", "Save the game (/save [name])"),
            BotCommand("restart", "Restart the current adventure"),
            BotCommand("quit", "End the session"),
            BotCommand("status", "Show game status"),
            BotCommand("inv", "Show inventory"),
            BotCommand("char", "Show character sheet"),
            BotCommand("help", "Show help"),
            BotCommand("model", "Show model configuration"),
        ])

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CommandHandler("new", _on_new))
    app.add_handler(CommandHandler("load", _on_load))
    app.add_handler(CommandHandler("restart", _on_restart))
    app.add_handler(CommandHandler("quit", _on_quit))
    app.add_handler(CallbackQueryHandler(_on_callback))
    # Command-inclusive: in-game slash commands (/help, /save, …) arrive
    # as ordinary text and route through session.submit, exactly like
    # the CLI.  Registered after the lifecycle CommandHandlers, which
    # match first within the same group.
    app.add_handler(MessageHandler(filters.TEXT, _on_text))
    log.info("Starting Telegram bot (long polling); allowed chats: %d",
             len(allowed_chat_ids))
    app.run_polling()
