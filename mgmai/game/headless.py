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

``HeadlessSession`` composes a ``StateManager`` + ``GameLoop`` +
``RecordingDisplay`` and exposes a single-turn ``submit()`` entry point
that returns the narration, a combat-status snapshot, and the game-over
flag.  It bypasses the interactive REPL entirely (no ``input()``,
no terminal rendering), making it suitable for:

- LLM-driven integration tests (a "driver" LLM acts as the player).
- Replay/automation scripts that feed a scripted command list.
- Programmatic smoke tests of the full two-call LLM pipeline.

The interactive REPL is untouched; this module is a sibling composition
layer, not a refactor of it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mgmai.game.display import Display
from mgmai.game.loop import GameLoop
from mgmai.llm.client import LLMClient
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.models.corpus import ModuleCorpus
from mgmai.state.manager import StateManager

try:
    from rich.console import Console

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


@dataclass
class StatusSnapshot:
    """Compact, JSON-serialisable view of the post-turn game status."""

    turn_count: int
    location: str
    in_combat: bool
    combat_round: Optional[int]
    player_hp: Optional[int]
    player_max_hp: Optional[int]
    # {combatant_id: {"hp", "max_hp", "side": "party"|"enemy", "alive",
    #                 "status_effects": {status_effect: rounds},
    #                 "status_effect_names": {status_effect: display name},
    #                 "fled": bool}}
    combatants: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_flags: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_count": self.turn_count,
            "location": self.location,
            "in_combat": self.in_combat,
            "combat_round": self.combat_round,
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "combatants": self.combatants,
            "active_flags": self.active_flags,
        }


@dataclass
class TurnTranscript:
    """Result of a single ``HeadlessSession.submit()`` call."""

    command: str
    narration: Optional[str]
    status: StatusSnapshot
    game_over: bool
    game_over_type: Optional[str]
    errors: list[str] = field(default_factory=list)
    # Serialized combat-log entries for this turn (list of dicts), used
    # by the LLM judge to cross-reference narration against engine truth.
    combat_log: list[dict[str, Any]] = field(default_factory=list)
    # Exception raised during the turn, if any (so callers can record
    # artifacts even when the harness blows up).
    exception: Optional[BaseException] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "narration": self.narration,
            "status": self.status.to_dict(),
            "game_over": self.game_over,
            "game_over_type": self.game_over_type,
            "errors": list(self.errors),
            "combat_log": list(self.combat_log),
            "exception": (
                f"{type(self.exception).__name__}: {self.exception}"
                if self.exception is not None
                else None
            ),
        }


class RecordingDisplay(Display):
    """A ``Display`` that suppresses terminal output and records events.

    Output is redirected to an in-memory buffer (so rich formatting
    still runs, just nowhere visible).  Each ``render_*`` call is
    recorded into a typed list so the harness can inspect what was
    shown to a real player.
    """

    def __init__(self) -> None:
        super().__init__()
        # Replace the rich Console with one writing to a sink so that
        # super().render_*() calls produce no terminal output.
        if _RICH_AVAILABLE:
            self._console = Console(
                file=io.StringIO(),
                highlight=False,
                width=120,
                record=False,
            )
        self.narrations: list[str] = []
        self.status_snapshots: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.game_over_events: list[dict[str, Any]] = []
        self.intros: list[dict[str, Any]] = []

    # --- game screens (override: record + suppress output) ---

    def render_intro(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        adv = corpus.adventure if corpus else None
        self.intros.append({
            "title": getattr(adv, "title", None) if adv else None,
            "introduction": getattr(adv, "introduction", None) if adv else None,
        })
        # Skip super().render_intro() — it would dump the room panel,
        # which we don't want in headless mode.

    def render_narration(self, text: str) -> None:
        self.narrations.append(text)
        # Deliberately do NOT call super(): we want zero terminal output.

    def render_status(self, state_loader: Any) -> None:
        snapshot = _snapshot_status(state_loader)
        self.status_snapshots.append(snapshot.to_dict() if isinstance(snapshot, StatusSnapshot) else snapshot)
        # Skip super(): no terminal output.

    def render_error(self, text: str) -> None:
        self.errors.append(text)

    def render_game_over(self, result: Any) -> None:
        self.game_over_events.append({
            "type": getattr(result, "type", None),
            "trigger": getattr(result, "trigger", None),
            "narrative": getattr(result, "narrative", None),
        })

    def render_goodbye(self) -> None:
        # Nothing to record; the game-over event above carries the
        # relevant info.  Suppress terminal output.
        pass


def _snapshot_status(state_manager: StateManager) -> StatusSnapshot:
    """Build a ``StatusSnapshot`` from a ``StateManager``."""
    hard = state_manager.hard_state
    corpus = state_manager.corpus
    if hard is None:
        return StatusSnapshot(
            turn_count=0, location="", in_combat=False,
            combat_round=None, player_hp=None, player_max_hp=None,
        )

    combat = hard.combat
    combatants: dict[str, dict[str, Any]] = {}
    if combat is not None:
        effect_defs = corpus.effective_status_effects() if corpus else {}

        def _effect_label(c: str) -> str:
            cdef = effect_defs.get(c)
            return cdef.name if cdef is not None and cdef.name else c

        allies = set(combat.allies)
        for cid in combat.combatants:
            if cid == "player":
                hp = hard.player.current_hp or 0
                max_hp = hard.player.max_hp or 0
                side = "party"
                status_effects = dict(hard.player.status_effects or {})
                fled = False
            else:
                state = hard.entity_states.get(cid, {})
                hp = int(state.get("current_hp") or 0)
                ent = corpus.entities.get(cid) if corpus else None
                max_hp = (ent.combat.hp if ent and ent.combat else 0)
                side = "party" if cid in allies else "enemy"
                status_effects = dict(state.get("status_effects") or {})
                fled = bool(state.get("fled"))
            combatants[cid] = {
                "hp": hp,
                "max_hp": max_hp,
                "side": side,
                "alive": hp > 0,
                "status_effects": status_effects,
                "status_effect_names": {c: _effect_label(c) for c in status_effects},
                "fled": fled,
                # Positioning: engagement partners (combatant ids) and
                # the pending impede flag.
                "engaged_with": sorted(
                    p[1] if p[0] == cid else p[0]
                    for p in (combat.engagement or [])
                    if cid in p
                ),
                "impeded": cid in (combat.impeded or []),
            }

    return StatusSnapshot(
        turn_count=hard.turn_count,
        location=hard.player.location,
        in_combat=combat is not None and combat.active,
        combat_round=combat.round_number if combat is not None else None,
        player_hp=hard.player.current_hp,
        player_max_hp=hard.player.max_hp,
        combatants=combatants,
        active_flags={k: v for k, v in hard.flags.items() if v},
    )


class HeadlessSession:
    """Programmatic, single-turn entry point around ``GameLoop``.

    Composes ``StateManager`` + ``GameLoop`` + ``RecordingDisplay``.
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

        self._display = RecordingDisplay()
        self._state = state_manager if state_manager is not None else StateManager()
        if adventure_dir is not None and state_manager is None:
            self._state.load_all(adventure_dir)
        # Sandbox the autosave path so it never lands in the CWD.
        self._state._config_dir = Path(config_dir)

        self._loop = GameLoop(
            self._state,
            llm_client,
            debug=debug,
            display=self._display,
            config_dir=config_dir,
        )
        # Render the intro so the recording captures the adventure title
        # and starting room — same UX as a real game start.
        self._loop._display.render_intro(self._state)

    # --- properties ---

    @property
    def state_manager(self) -> StateManager:
        return self._state

    @property
    def hard_state(self) -> Optional[HardGameState]:
        return self._state.hard_state

    @property
    def soft_state(self) -> Optional[SoftGameState]:
        return self._state.soft_state

    @property
    def corpus(self) -> Optional[ModuleCorpus]:
        return self._state.corpus

    @property
    def display(self) -> RecordingDisplay:
        return self._display

    @property
    def loop(self) -> GameLoop:
        return self._loop

    @property
    def is_over(self) -> bool:
        """True if the game has ended (win or lose)."""
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
        """Run one player-input turn end to end and return a transcript.

        Any exception raised during the turn is caught, recorded in the
        transcript, and then re-raised so the caller can still access
        the partial transcript after catching the exception.
        """
        errors_before = len(self._display.errors)

        exception: Optional[BaseException] = None
        narration: Optional[str] = None
        try:
            narration = self._loop._run_turn(command)
        except BaseException as exc:  # noqa: BLE001 — record + reraise
            exception = exc

        hard = self._state.hard_state
        status = _snapshot_status(self._state)
        new_errors = self._display.errors[errors_before:]

        # Capture the combat log from the last engine result so the
        # judge can cross-reference narration against mechanical truth.
        combat_log: list[dict[str, Any]] = []
        last_result = getattr(self._loop, "_last_result", None)
        if last_result is not None and getattr(last_result, "combat_log", None):
            for entry in last_result.combat_log:
                if hasattr(entry, "model_dump"):
                    combat_log.append(entry.model_dump())
                elif isinstance(entry, dict):
                    combat_log.append(entry)

        game_over = hard is not None and hard.game_over is not None
        game_over_type = hard.game_over.type if game_over and hard else None

        transcript = TurnTranscript(
            command=command,
            narration=narration,
            status=status,
            game_over=game_over,
            game_over_type=game_over_type,
            errors=new_errors,
            combat_log=combat_log,
            exception=exception,
        )
        if exception is not None:
            raise exception
        return transcript

    def status_snapshot(self) -> StatusSnapshot:
        """Build a status snapshot without running a turn."""
        return _snapshot_status(self._state)
