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

"""The CLI front-end: a terminal REPL over a GameSession.

Everything front-end-agnostic (turn pipeline, dispatch, rest mode,
autosave, game-over detection) lives in ``mgmai.game.session``; this
module only owns the terminal concerns — ``input()``, readline
history, and the REPL loop.
"""

from __future__ import annotations

import atexit
import logging
import os

from mgmai.config import get_config_dir
from mgmai.game.display import Display
from mgmai.game.session import (  # noqa: F401  (re-exported for compat)
    FALLBACK_NARRATION,
    TURN_ERROR_NARRATION,
    GameSession,
    TurnResult,
)
from mgmai.llm.client import LLMClient
from mgmai.state.manager import StateManager

try:
    import readline

    _HISTORY_FILE = str(get_config_dir() / "history")
    _HISTORY_LENGTH = 1000
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

log = logging.getLogger(__name__)


def _setup_readline() -> None:
    if not _HAS_READLINE:
        return
    readline.parse_and_bind("set editing-mode emacs")
    readline.parse_and_bind("Control-d: delete-char")
    readline.parse_and_bind('"\\e[3~": delete-char')
    readline.parse_and_bind("Control-h: backward-delete-char")


def _load_history() -> None:
    if not _HAS_READLINE:
        return
    _setup_readline()
    try:
        readline.read_history_file(_HISTORY_FILE)
    except (FileNotFoundError, PermissionError):
        pass
    readline.set_history_length(_HISTORY_LENGTH)


def _save_history() -> None:
    if not _HAS_READLINE:
        return
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        readline.write_history_file(_HISTORY_FILE)
    except (OSError, PermissionError):
        pass


atexit.register(_save_history)


class GameLoop:
    """Thin CLI REPL wrapper around ``GameSession``.

    Kept (under its historical name, for one release) so existing
    imports and tests keep working; new front-ends should compose
    ``GameSession`` directly.  The compat properties/methods below
    delegate to the session and exist solely for pre-refactor tests —
    they will be removed once those tests are migrated.
    """

    def __init__(
        self,
        state_manager: StateManager,
        llm_client: LLMClient,
        *,
        debug: bool = False,
        display: Display | None = None,
        config_dir: str | None = None,
        prose_validation_enabled: bool = True,
        interactive: bool | None = None,
    ):
        self._display = display if display is not None else Display()
        self._session = GameSession(
            state_manager,
            llm_client,
            view=self._display,
            config_dir=config_dir,
            debug=debug,
            interactive=interactive,
            prose_validation_enabled=prose_validation_enabled,
        )

    @property
    def debug(self) -> bool:
        return self._session.debug

    def start(self) -> None:
        self._session.begin()
        self._repl()

    # --- REPL ---

    def _repl(self) -> None:
        _load_history()
        while not self._session.finished:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                self._display.print("")
                self._session.submit("/quit")
                return

            if not line.strip():
                continue

            if _HAS_READLINE:
                readline.add_history(line)

            self._session.submit(line)

    # --- compat delegates (pre-refactor test surface) ---

    @property
    def _state(self):
        return self._session._state

    @property
    def _commands(self):
        return self._session._commands

    @property
    def _chat_log(self):
        return self._session._chat_log

    @property
    def _last_result(self):
        return self._session._last_result

    @property
    def _last_action(self):
        return self._session._last_action

    @property
    def _rest_mode(self):
        return self._session._rest_mode

    @property
    def _running(self) -> bool:
        return not self._session.finished

    @property
    def ruling_retries(self):
        return self._session.ruling_retries

    @property
    def turn_combat_log(self):
        return self._session.turn_combat_log

    def _run_turn(self, player_input: str):
        return self._session._run_turn(player_input)

    def _execute_turn(self, current_input, original_input, chain_depth):
        return self._session._execute_turn(
            current_input, original_input, chain_depth
        )

    def _dispatch_input(self, line: str):
        return self._session._dispatch_input(line)

    def _call_prose(self, *args, **kwargs):
        return self._session.call_prose(*args, **kwargs)

    def _get_autosave_path(self):
        return self._session.get_autosave_path()

    def _do_exit(self) -> None:
        self._session._do_exit()
