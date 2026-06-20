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

"""System-agnostic dice-expression parsing.

Kept separate from :mod:`mgmai.engine.systems.five_e` so that both the
system implementations and legacy call sites can share it without circular
imports.  ``parse_damage_dice`` understands the common ``NdM[+/-k]``
notation; system-specific crit handling is applied by the caller.
"""

from __future__ import annotations

import re


def parse_damage_dice(expr: str) -> tuple[int, int, int]:
    """Parse a damage expression like ``"1d6+2"``, ``"2d4"``, or ``"3"``.

    Returns ``(num_dice, die_size, modifier)``.  For a bare integer (flat
    damage, e.g. GURPS or unarmed strikes), ``num_dice`` and ``die_size``
    are both 0 and the value is stored in ``modifier``.
    """
    expr = expr.strip()
    m = re.fullmatch(r"(\d+)d(\d+)(?:([+-]\d+))?", expr)
    if m is not None:
        num_dice = int(m.group(1))
        die_size = int(m.group(2))
        modifier = int(m.group(3)) if m.group(3) else 0
        return num_dice, die_size, modifier
    # Bare integer: flat damage (no dice)
    m = re.fullmatch(r"(\d+)", expr)
    if m is not None:
        return 0, 0, int(m.group(1))
    raise ValueError(f"Invalid damage expression: {expr!r}")
