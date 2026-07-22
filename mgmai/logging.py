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

Provides ``setup_logging()`` to configure the Python logging system.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def setup_logging(level: str = "INFO",
                  log_file: str | Path | None = None) -> None:
    """Configure the root logger for MGMAI.

    Parameters
    ----------
    level:
        One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
    log_file:
        Optional path to a log file.  When provided, all log messages
        (at *level* and above) are written to this file.
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
        fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s"))
        root.addHandler(fh)


def get_level() -> int:
    """Return the current numeric log level."""
    return logging.getLogger("mgmai").level


def set_level(level: str) -> None:
    """Change the console handler level at runtime."""
    numeric_level = LOG_LEVELS.get(level.upper(), logging.INFO)
    root = logging.getLogger("mgmai")
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(numeric_level)


def format_state_snapshot(hard: Any, soft: Any) -> dict[str, Any]:
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
