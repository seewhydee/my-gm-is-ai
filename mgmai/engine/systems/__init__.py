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

"""Resolution-system registry.

The engine obtains its :class:`ResolutionSystem` exclusively through
:func:`get_system` / :func:`get_system_for_corpus`.  Registering a new
system is additive and requires no changes to the combat loop or
resolvers.
"""

from __future__ import annotations

from mgmai.engine.systems.base import CheckResult, ResolutionSystem, SaveResult
from mgmai.engine.systems.five_e import FiveESystem

_REGISTRY: dict[str, type[ResolutionSystem]] = {
    "5e": FiveESystem,
}
_INSTANCES: dict[str, ResolutionSystem] = {}


def get_system(name: str | None = None) -> ResolutionSystem:
    """Return the (cached) system instance for ``name``.

    ``name`` defaults to ``"5e"`` when ``None`` or empty, matching the
    engine's pre-abstraction behaviour.  Unknown systems raise
    ``ValueError``.
    """
    name = name or "5e"
    inst = _INSTANCES.get(name)
    if inst is None:
        cls = _REGISTRY.get(name)
        if cls is None:
            raise ValueError(f"Unknown system: {name!r}")
        inst = cls()
        _INSTANCES[name] = inst
    return inst


def get_system_for_corpus(corpus: object | None) -> ResolutionSystem:
    """Return the system declared by a corpus's ``stats.system`` field.

    Falls back to ``"5e"`` when the corpus has no stats block, preserving
    the engine's long-standing default for stat-less adventures.
    """
    stats = getattr(corpus, "stats", None)
    name = stats.system if stats is not None else None
    return get_system(name)


def register_system(name: str, cls: type[ResolutionSystem]) -> None:
    """Register a new resolution system.

    Intended for third-party / future systems (Pathfinder, GURPS, ...).
    Drops any cached instance so subsequent :func:`get_system` calls return
    an instance of the new class.
    """
    _REGISTRY[name] = cls
    _INSTANCES.pop(name, None)


__all__ = [
    "ResolutionSystem",
    "CheckResult",
    "SaveResult",
    "FiveESystem",
    "get_system",
    "get_system_for_corpus",
    "register_system",
]
