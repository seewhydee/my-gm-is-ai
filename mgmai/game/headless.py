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

"""Headless composition layer for programmatic play and integration tests.

``HeadlessSession`` composes a ``StateManager`` + ``GameSession`` +
``RecordingView`` and exposes a single-turn ``submit()`` entry point
that returns the narration, a combat-status snapshot, and the game-over
flag.  It bypasses the interactive REPL entirely (no ``input()``,
no terminal rendering), making it suitable for:

- LLM-driven integration tests (a "driver" LLM acts as the player).
- Replay/automation scripts that feed a scripted command list.
- Programmatic smoke tests of the full two-call LLM pipeline.

Everything runs through the public ``GameSession`` API — no private
access — so this harness exercises exactly the surface the CLI and
Telegram front-ends use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mgmai.game.session import GameSession
from mgmai.game.status import (  # noqa: F401  (re-exported for compat)
    StatusSnapshot,
    _snapshot_status,
    snapshot_status,
)
from mgmai.llm.client import LLMClient
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.state.manager import StateManager


@dataclass
class TurnTranscript:
    """Result of a single ``HeadlessSession.submit()`` call."""

    command: str
    narration: str | None
    status: StatusSnapshot
    game_over: bool
    game_over_type: str | None
    errors: list[str] = field(default_factory=list)
    # Serialized combat-log entries for this turn (list of dicts), used
    # by the LLM judge to cross-reference narration against engine truth.
    combat_log: list[dict[str, Any]] = field(default_factory=list)
    # Engine outcome for this turn: whether resolution succeeded, its
    # error string if not, and the ruled PlayerAction.  A turn can fail
    # silently (narration still flows), so these are the only reliable
    # way to spot it in an artifact.
    success: bool | None = None
    engine_error: str | None = None
    ruled_action: dict[str, Any] | None = None
    # Validation errors that triggered a corrective ruling retry (LLM
    # Call 1) during this turn — e.g. over-budget rulings rejected by
    # budget validation.  Empty when the first ruling passed (or the
    # retry is what failed, in which case the first error is recorded).
    ruling_retries: list[str] = field(default_factory=list)
    # EngineResult warnings surfaced during the turn (e.g. stripped
    # embellishments the ruling model should learn from).
    warnings: list[str] = field(default_factory=list)
    # Exception raised during the turn, if any (so callers can record
    # artifacts even when the harness blows up).
    exception: BaseException | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "narration": self.narration,
            "status": self.status.to_dict(),
            "game_over": self.game_over,
            "game_over_type": self.game_over_type,
            "errors": list(self.errors),
            "combat_log": list(self.combat_log),
            "success": self.success,
            "engine_error": self.engine_error,
            "ruled_action": self.ruled_action,
            "ruling_retries": list(self.ruling_retries),
            "warnings": list(self.warnings),
            "exception": (
                f"{type(self.exception).__name__}: {self.exception}"
                if self.exception is not None
                else None
            ),
        }


class RecordingView:
    """A ``GameView`` that records events instead of rendering them.

    Produces no terminal output and has no Rich dependency; each
    ``render_*`` call is recorded into a typed list so the harness can
    inspect what was shown to a real player.  Command output (``print``)
    and the goodbye screen carry no assertions, so they are discarded.
    """

    def __init__(self) -> None:
        self.narrations: list[str] = []
        self.status_snapshots: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.game_over_events: list[dict[str, Any]] = []
        self.intros: list[dict[str, Any]] = []
        self.rest_menus: list[str] = []

    def print(self, text: str) -> None:
        pass

    def render_intro(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        adv = corpus.adventure if corpus else None
        self.intros.append({
            "title": getattr(adv, "title", None) if adv else None,
            "introduction": getattr(adv, "introduction", None) if adv else None,
        })

    def render_narration(self, text: str) -> None:
        self.narrations.append(text)

    def render_status(self, state_loader: Any) -> None:
        snapshot = snapshot_status(state_loader)
        self.status_snapshots.append(snapshot.to_dict())

    def render_error(self, text: str) -> None:
        self.errors.append(text)

    def render_rest_menu(self, text: str) -> None:
        self.rest_menus.append(text)

    def render_game_over(self, result: Any) -> None:
        self.game_over_events.append({
            "type": getattr(result, "type", None),
            "trigger": getattr(result, "trigger", None),
            "narrative": getattr(result, "narrative", None),
        })

    def render_goodbye(self) -> None:
        pass


# Back-compat alias: the class was introduced under this name and
# existing imports/tests keep using it.
RecordingDisplay = RecordingView


class HeadlessSession:
    """Programmatic, single-turn entry point around ``GameSession``.

    Composes ``StateManager`` + ``GameSession`` + ``RecordingView``.
    Callers provide either an adventure directory (loaded via
    ``StateManager.load_all``) or a pre-built ``StateManager``, plus an
    ``LLMClient`` and a temp ``config_dir`` (so autosaves land in a
    sandbox instead of ``./autosave.json``).
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        state_manager: StateManager | None = None,
        adventure_dir: str | Path | None = None,
        config_dir: str | Path,
        debug: bool = False,
    ) -> None:
        if state_manager is None and adventure_dir is None:
            raise ValueError(
                "HeadlessSession requires either state_manager or adventure_dir"
            )

        self._display = RecordingView()
        self._state = state_manager if state_manager is not None else StateManager()
        if adventure_dir is not None and state_manager is None:
            self._state.load_all(adventure_dir)
        # Sandbox the autosave path so it never lands in the CWD.
        self._state.config_dir = Path(config_dir)

        self._session = GameSession(
            self._state,
            llm_client,
            view=self._display,
            config_dir=config_dir,
            debug=debug,
            interactive=False,
        )
        # Render the intro so the recording captures the adventure title
        # and starting room — same UX as a real game start.
        self._session.begin()

    # --- properties ---

    @property
    def session(self) -> GameSession:
        return self._session

    @property
    def state_manager(self) -> StateManager:
        return self._state

    @property
    def hard_state(self) -> HardGameState | None:
        return self._state.hard_state

    @property
    def soft_state(self) -> SoftGameState | None:
        return self._state.soft_state

    @property
    def corpus(self) -> ModuleCorpus | None:
        return self._state.corpus

    @property
    def display(self) -> RecordingView:
        return self._display

    @property
    def is_over(self) -> bool:
        """True when the game has ended (win or lose)."""
        hard = self._state.hard_state
        return hard is not None and hard.game_over is not None

    @property
    def in_combat(self) -> bool:
        hard = self._state.hard_state
        return (
            hard is not None
            and hard.combat is not None
            and hard.combat.active
        )

    # --- single-turn entry point ---

    def submit(self, command: str) -> TurnTranscript:
        """Run one player input end to end and return a transcript.

        Any exception raised during the turn is recorded in the
        transcript and then re-raised, so the caller can still inspect
        the partial transcript after catching the exception.
        """
        exception: BaseException | None = None
        try:
            result = self._session.submit(command)
        except BaseException as exc:  # noqa: BLE001 — record + reraise
            exception = exc
            result = None

        if result is not None:
            narration = result.narration
            status = result.status
            game_over = result.game_over
            game_over_type = result.game_over_type
            errors = list(result.errors)
            combat_log = list(result.combat_log)
            success = result.success
            engine_error = result.engine_error
            ruled_action = result.ruled_action
            ruling_retries = list(result.ruling_retries)
            warnings = list(result.warnings)
        else:
            # The turn blew up before producing a result: still derive
            # the post-turn state so callers inspecting the partial
            # transcript get a usable snapshot.
            hard = self._state.hard_state
            status = snapshot_status(self._state)
            game_over = hard is not None and hard.game_over is not None
            game_over_type = hard.game_over.type if game_over and hard else None
            narration = None
            errors = []
            combat_log = []
            success = None
            engine_error = None
            ruled_action = None
            ruling_retries = []
            warnings = []

        transcript = TurnTranscript(
            command=command,
            narration=narration,
            status=status,
            game_over=game_over,
            game_over_type=game_over_type,
            errors=errors,
            combat_log=combat_log,
            success=success,
            engine_error=engine_error,
            ruled_action=ruled_action,
            ruling_retries=ruling_retries,
            warnings=warnings,
            exception=exception,
        )
        if exception is not None:
            raise exception
        return transcript

    def status_snapshot(self) -> StatusSnapshot:
        """Build a status snapshot without running a turn."""
        return snapshot_status(self._state)
