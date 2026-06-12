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

"""Logging infrastructure for MGMAI.

Provides ``setup_logging()`` to configure the Python logging system, and
``TurnLogger`` to accumulate structured per-turn data that can be saved
to a JSON file for post-hoc analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
) -> None:
    """Configure the root logger for MGMAI.

    Parameters
    ----------
    level:
        One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
    log_file:
        Optional path to a log file.  When provided, all log messages
        (at *level* and above) are written to this file in addition to
        the console.
    """
    numeric_level = LOG_LEVELS.get(level.upper(), logging.INFO)

    root = logging.getLogger("mgmai")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
        )
        root.addHandler(fh)


def get_level() -> int:
    """Return the current numeric log level of the ``mgmai`` logger."""
    return logging.getLogger("mgmai").level


def set_level(level: str) -> None:
    """Change the console handler level at runtime."""
    numeric_level = LOG_LEVELS.get(level.upper(), logging.INFO)
    root = logging.getLogger("mgmai")
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setLevel(numeric_level)


class TurnLogger:
    """Accumulates structured per-turn data for JSON log saving.

    Usage::

        turn_log = TurnLogger()
        turn_log.begin_turn(1, "look around")
        turn_log.log_step("briefing", briefing_dict)
        turn_log.end_turn()
        turn_log.save(Path("turns.json"))
    """

    def __init__(self) -> None:
        self._turns: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def begin_turn(self, turn_num: int, player_input: str) -> None:
        self._current = {
            "turn": turn_num,
            "player_input": player_input,
            "chain_steps": [],
        }

    def log_step(self, key: str, data: Any) -> None:
        if self._current is None:
            return
        step = self._current["chain_steps"]
        if step and key not in step[-1]:
            step[-1][key] = data
        else:
            step.append({key: data})

    def end_turn(self) -> None:
        if self._current is not None:
            self._turns.append(self._current)
            self._current = None

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"turns": self._turns}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def format_state_snapshot(
    hard: Any,
    soft: Any,
) -> dict[str, Any]:
    """Build a lightweight state snapshot dict for logging."""
    return {
        "player_location": hard.player.location,
        "hard_inventory": hard.player.inventory,
        "soft_inventory": soft.soft_inventory,
        "flags": hard.flags,
        "turn_count": hard.turn_count,
        "entity_attitudes": {
            eid: s.get("attitude")
            for eid, s in hard.entity_states.items()
            if "attitude" in s
        },
    }
