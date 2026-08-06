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

Phase 1 skeleton: one configured adventure, text in → turn → narration
out, typing indicator, allow-list.  Lifecycle commands (/new, /load,
/restart…), the persistent session registry, keyboards, and markup
conversion are later phases.

Importing this module requires python-telegram-bot (the ``telegram``
extra); the PTB import is deferred to ``main()`` so the rest of the
package stays importable without it.  The turn-driving core
(``BotRuntime``) is PTB-free and unit-testable with plain fakes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mgmai.game.session import GameSession
from mgmai.logging import setup_logging
from mgmai.state.manager import StateManager
from mgmai.telegram.textutil import chunk_message
from mgmai.telegram.view import TelegramView

log = logging.getLogger(__name__)

REFUSAL_TEXT = "Sorry, this is a private bot — you're not on the guest list."

WELCOME_TEXT = (
    "Welcome to My GM is AI! Send any message to begin your adventure. "
    "In-game commands like /help, /inv, and /char work as they do in "
    "the CLI."
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


@dataclass
class ChatSession:
    """One chat's live game session."""

    chat_id: int
    session: GameSession
    view: TelegramView
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BotRuntime:
    """Per-chat sessions and the turn pipeline, independent of PTB.

    The PTB handlers are thin adapters over this class; unit tests drive
    it directly with fake ``reply``/``typing`` callables.
    """

    def __init__(
        self,
        *,
        config_dir: Path,
        adventure_path: Path,
        llm_client: Any,
        allowed_chat_ids: set[int],
        prose_validation_enabled: bool = True,
    ) -> None:
        self.config_dir = config_dir
        self.adventure_path = adventure_path
        self.llm_client = llm_client
        self.allowed_chat_ids = allowed_chat_ids
        self.prose_validation_enabled = prose_validation_enabled
        self.sessions: dict[int, ChatSession] = {}

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.allowed_chat_ids

    def start_session(self, chat_id: int) -> ChatSession:
        """Create a fresh session for *chat_id* (blocking; run via
        ``asyncio.to_thread``).  Each chat gets its own saves sandbox;
        ``config_dir`` stays the real one so model config resolves
        globally."""
        state_manager = StateManager(config_dir=self.config_dir)
        state_manager.load_all(self.adventure_path)
        view = TelegramView()
        session = GameSession(
            state_manager,
            self.llm_client,
            view=view,
            config_dir=self.config_dir,
            saves_dir=self.config_dir / "telegram" / str(chat_id) / "saves",
            interactive=False,
            prose_validation_enabled=self.prose_validation_enabled,
        )
        session.begin()
        log.info("Started session for chat %d (adventure: %s)",
                 chat_id, self.adventure_path)
        return ChatSession(chat_id=chat_id, session=session, view=view)

    async def handle_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply: Callable[[str], Awaitable[Any]],
        typing: Callable[[], Awaitable[Any]],
    ) -> None:
        """Process one incoming game message end to end.

        *reply* sends a text chunk to the chat; *typing* sends one
        typing indicator.  A session is created lazily on the chat's
        first game message; the per-chat lock serializes turns so a
        queued second message waits rather than interleaving.
        """
        chat = self.sessions.get(chat_id)
        if chat is None:
            chat = await asyncio.to_thread(self.start_session, chat_id)
            self.sessions[chat_id] = chat
        async with chat.lock:
            heartbeat = asyncio.create_task(self._typing_loop(typing))
            try:
                await asyncio.to_thread(chat.session.submit, text)
            except Exception:
                log.exception("Turn failed for chat %d", chat_id)
                await reply(TURN_FAILURE_TEXT)
                return
            finally:
                heartbeat.cancel()
            for event in chat.view.drain():
                for chunk in chunk_message(event.text):
                    await reply(chunk)

    @staticmethod
    async def _typing_loop(typing: Callable[[], Awaitable[Any]]) -> None:
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
        from telegram.ext import (
            Application,
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
    adventures = find_adventures(Path(adventures_dir).expanduser())
    if not adventures:
        _abort(f"No adventures found in {adventures_dir}.")
    adventure_path = adventures[0]
    log.info("Using adventure: %s", adventure_path)

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
        adventure_path=adventure_path,
        llm_client=llm_client,
        allowed_chat_ids=allowed_chat_ids,
        prose_validation_enabled=app_config.prose_validation_enabled,
    )

    async def _on_start(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None or not runtime.is_allowed(chat_id):
            if update.message is not None:
                await update.message.reply_text(REFUSAL_TEXT)
            return
        await update.message.reply_text(WELCOME_TEXT)

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

        async def _typing() -> None:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        await runtime.handle_message(
            chat_id, message.text,
            reply=message.reply_text,
            typing=_typing,
        )

    app = Application.builder().token(token).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", _on_start))
    # Command-inclusive: in-game slash commands (/help, /save, …) arrive
    # as ordinary text and route through session.submit, exactly like
    # the CLI.  Registered after /start's CommandHandler, which matches
    # first within the same group.
    app.add_handler(MessageHandler(filters.TEXT, _on_text))
    log.info("Starting Telegram bot (long polling); allowed chats: %d",
             len(allowed_chat_ids))
    app.run_polling()
