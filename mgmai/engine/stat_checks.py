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


def compute_d20_modifier(stat_value: int) -> int:
    """D&D 5e-style ability modifier: (stat - 10) // 2, floored."""
    return (stat_value - 10) // 2


def compute_modifier(stat_value: int, resolution_system: str) -> int:
    """Compute a stat modifier given a resolution system identifier."""
    if resolution_system == "d20":
        return compute_d20_modifier(stat_value)
    raise ValueError(f"Unknown resolution system: {resolution_system!r}")
