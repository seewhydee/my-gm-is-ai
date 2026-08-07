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

"""Per-chat session registry for the Telegram front-end.

Owns the lifecycle of live sessions (start / load / end) and a
persisted index (``config_dir/telegram/sessions.json``) mapping
``chat_id → {adventure_path, last_save}`` so the bot can offer
Continue / resume after a process restart.  PTB-free and unit-testable;
the blocking methods (``start_new`` / ``load_save``) are synchronous —
call them via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from mgmai.game.session import GameSession
from mgmai.state.manager import StateManager
from mgmai.telegram.view import TelegramView

log = logging.getLogger(__name__)


@dataclass
class SaveInfo:
    """One save file in a chat's sandbox (for the save browser)."""

    path: Path
    name: str
    mtime: float
    # Short excerpt of the save's latest_narration, if present.
    snippet: str | None = None
    # Adventure subdirectory the save lives in (None for stray files
    # directly in the sandbox root, e.g. pre-scoping saves).
    adventure: str | None = None


@dataclass
class ChatSession:
    """One chat's live game session."""

    chat_id: int
    adventure_path: Path | None
    session: GameSession
    view: TelegramView
    lock: asyncio.Lock
    # In-place-updated status panel (Phase 3).
    status_message_id: int | None = None


class SessionRegistry:
    """Live sessions plus the persisted chat → save index."""

    INDEX_FILENAME = "sessions.json"

    def __init__(
        self,
        *,
        config_dir: str | Path,
        llm_client,
        prose_validation_enabled: bool = True,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.llm_client = llm_client
        self.prose_validation_enabled = prose_validation_enabled
        self.sessions: dict[int, ChatSession] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._telegram_dir = self.config_dir / "telegram"
        self._index_path = self._telegram_dir / self.INDEX_FILENAME
        self._index: dict[int, dict] = self._load_index()

    # --- locks ---

    def get_lock(self, chat_id: int) -> asyncio.Lock:
        """The per-chat serializer.  Shared by the chat's sessions, so
        it survives session replacement (restart/new/load) and also
        guards callback queries for chats with no live session."""
        chat = self.sessions.get(chat_id)
        if chat is not None:
            return chat.lock
        return self._locks.setdefault(chat_id, asyncio.Lock())

    # --- paths ---

    def saves_dir_for(self, chat_id: int,
                      adventure: str | None = None) -> Path:
        """The chat's save sandbox, adventure-scoped like the CLI's
        ``saves/<adventure>/`` scheme: autosaves and /save files of two
        chats (or of one chat playing two adventures) never collide.
        With *adventure* omitted, returns the sandbox root."""
        base = self._telegram_dir / str(chat_id) / "saves"
        return base / adventure if adventure else base

    @staticmethod
    def _adventure_name(adventure_path: Path | None) -> str:
        """Sandbox subdirectory for an adventure: the directory name,
        matching how the CLI scopes saves."""
        return adventure_path.name if adventure_path else "game"

    # --- live sessions ---

    def get(self, chat_id: int) -> ChatSession | None:
        return self.sessions.get(chat_id)

    def start_new(self, chat_id: int, adventure_path: str | Path) -> ChatSession:
        """Start *adventure_path* from the beginning (blocking; run via
        ``asyncio.to_thread``).  Replaces any live session.  Renders the
        intro into the view buffer."""
        adventure_path = Path(adventure_path)
        self.end(chat_id)
        state_manager = StateManager(config_dir=self.config_dir)
        state_manager.load_all(adventure_path)
        chat = self._build_session(chat_id, state_manager, adventure_path)
        chat.session.begin()
        self.sessions[chat_id] = chat
        log.info("Chat %d: started new game (%s)", chat_id, adventure_path)
        self._update_index(chat_id,
                           adventure_path=str(adventure_path.resolve()),
                           last_save=None)
        return chat

    def load_save(self, chat_id: int, save_path: str | Path) -> ChatSession:
        """Resume a session from *save_path* (blocking; run via
        ``asyncio.to_thread``).  Replaces any live session.  No intro is
        rendered."""
        save_path = Path(save_path)
        self.end(chat_id)
        state_manager = StateManager(config_dir=self.config_dir)
        adv_path = state_manager.load_save(save_path)
        chat = self._build_session(
            chat_id, state_manager,
            Path(adv_path) if adv_path else None,
        )
        self.sessions[chat_id] = chat
        log.info("Chat %d: loaded save %s", chat_id, save_path)
        self._update_index(
            chat_id,
            adventure_path=str(chat.adventure_path.resolve())
            if chat.adventure_path else None,
            last_save=str(save_path.resolve()),
        )
        return chat

    def end(self, chat_id: int) -> None:
        """Drop the live session (state is autosaved every turn, plus
        game-over turns and rest-mode steps).  The index entry stays, so
        Continue keeps working."""
        self.sessions.pop(chat_id, None)

    def _build_session(
        self,
        chat_id: int,
        state_manager: StateManager,
        adventure_path: Path | None,
    ) -> ChatSession:
        saves_dir = self.saves_dir_for(
            chat_id, self._adventure_name(adventure_path))
        view = TelegramView(scrub_prefixes=[
            # Longest first (the view also sorts): the adventure-scoped
            # dir scrubs "/save" output down to the bare filename, the
            # sandbox root covers other adventures' subdirs, and the
            # config dir is the catch-all.
            saves_dir,
            self.saves_dir_for(chat_id),
            self.config_dir,
        ])
        session = GameSession(
            state_manager,
            self.llm_client,
            view=view,
            config_dir=self.config_dir,
            saves_dir=saves_dir,
            interactive=False,
            prose_validation_enabled=self.prose_validation_enabled,
        )
        return ChatSession(
            chat_id=chat_id,
            adventure_path=adventure_path,
            session=session,
            view=view,
            lock=self.get_lock(chat_id),
        )

    # --- saves and the persisted index ---

    def list_saves(self, chat_id: int) -> list[SaveInfo]:
        """All save files in the chat's sandbox, across adventure
        subdirectories (loading another adventure's save switches
        adventures), newest first (autosaves included)."""
        saves_dir = self.saves_dir_for(chat_id)
        try:
            paths = [p for p in saves_dir.rglob("*.json") if p.is_file()]
        except OSError:
            return []
        saves: list[SaveInfo] = []
        for path in paths:
            snippet = None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                snippet = data.get("latest_narration")
            except (OSError, json.JSONDecodeError):
                pass
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            saves.append(SaveInfo(
                path=path,
                name=path.name,
                mtime=mtime,
                snippet=snippet,
                adventure=(path.parent.name
                           if path.parent != saves_dir else None),
            ))
        saves.sort(key=lambda s: s.mtime, reverse=True)
        return saves

    def saved_session(self, chat_id: int) -> dict | None:
        """The chat's index entry when it points at an existing save
        (i.e. Continue has something to load), else None."""
        entry = self._index.get(chat_id)
        if not entry:
            return None
        last_save = entry.get("last_save")
        if not last_save or not Path(last_save).is_file():
            return None
        return entry

    def indexed_adventure_path(self, chat_id: int) -> Path | None:
        """The adventure the chat last played (live or from the index)."""
        chat = self.sessions.get(chat_id)
        if chat is not None:
            return chat.adventure_path
        entry = self._index.get(chat_id) or {}
        raw = entry.get("adventure_path")
        return Path(raw) if raw else None

    def note_save(self, chat_id: int) -> None:
        """Point the chat's ``last_save`` at its (adventure-scoped)
        autosave (written every turn).  Called after each submit."""
        adventure = self._adventure_name(
            self.indexed_adventure_path(chat_id))
        autosave = self.saves_dir_for(chat_id, adventure) / "autosave.json"
        if autosave.is_file():
            self._update_index(chat_id, last_save=str(autosave.resolve()))

    def clear_last_save(self, chat_id: int) -> None:
        """Forget the chat's ``last_save`` (e.g. after game over, where
        the autosave captured a finished game that must not be offered
        as Continue).  Keeps the adventure_path for restart buttons."""
        self._update_index(chat_id, last_save=None)

    def _update_index(self, chat_id: int, **fields) -> None:
        entry = dict(self._index.get(chat_id) or {})
        entry.update(fields)
        self._index[chat_id] = entry
        self._write_index()

    def _load_index(self) -> dict[int, dict]:
        """Read the persisted index; a missing or corrupt index is
        tolerated (treated as empty)."""
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        index: dict[int, dict] = {}
        for key, value in data.items():
            try:
                cid = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                index[cid] = value
        return index

    def _write_index(self) -> None:
        """Persist the index atomically (tmp file + rename)."""
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_name(self._index_path.name + ".tmp")
        tmp.write_text(
            json.dumps({str(k): v for k, v in sorted(self._index.items())},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self._index_path)
