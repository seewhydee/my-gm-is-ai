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

"""Stat check computation utilities."""

from typing import Any


def compute_d20_modifier(stat_value: int) -> int:
    """D&D 5e-style ability modifier: (stat - 10) // 2, floored."""
    return (stat_value - 10) // 2


def compute_modifier(stat_value: int, system: str) -> int:
    """Compute a stat modifier given a resolution system identifier."""
    if system == "d20":
        return compute_d20_modifier(stat_value)
    raise ValueError(f"Unknown system: {system!r}")


def format_stat_check_prefix(rolls: list[dict[str, Any]]) -> str:
    """Return a markdown-formatted prefix summarizing any stat checks.

    The prefix is intended to be prepended to the narration shown to the
    player after a player action that involved one or more stat checks.
    Only rolls with ``type == "stat_check"`` are summarised.  If no such
    rolls exist, an empty string is returned.

    Example output::

        **[STR check: failed]**

        **[DEX check: success]**

    """
    summaries: list[str] = []
    for roll in rolls:
        if roll.get("type") != "stat_check":
            continue
        stat = roll.get("stat")
        success = roll.get("success")
        if stat is None or success is None:
            continue
        outcome = "success" if success else "failed"
        summaries.append(f"**[{stat} check: {outcome}]**")

    if not summaries:
        return ""

    return "\n\n".join(summaries) + "\n\n"
