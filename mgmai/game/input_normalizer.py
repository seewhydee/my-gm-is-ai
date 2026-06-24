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

"""Deterministic expansion of common interactive-fiction shortcuts.

Player inputs that match a recognized shortcut form exactly are rewritten
into canonical natural-language phrases before they are passed to the
ruling LLM.  Inputs that do not match are returned unchanged.
"""

from __future__ import annotations


# Shortcuts that expand only when the entire input is exactly this token.
_SINGLE_TOKEN_SHORTCUTS: dict[str, str] = {
    "n": "go north",
    "s": "go south",
    "e": "go east",
    "w": "go west",
    "u": "go up",
    "d": "go down",
    "l": "look around",
    "z": "wait",
    "x": "look around",
}


# Shortcuts that expand when the first token matches and a non-empty
# argument follows.  The replacement must contain ``{rest}``.
_PREFIX_SHORTCUTS: dict[str, str] = {
    "x": "examine {rest}",
    "t": "talk to {rest}",
}


def normalize_player_input(text: str) -> str:
    """Expand IF shortcuts in *text* to full natural-language phrases.

    The normalization is conservative: only exact matches and simple
    ``<shortcut> <argument>`` forms are rewritten.  Anything else,
    including the shortcut embedded inside a larger sentence, is returned
    unchanged.

    Examples:
        ``"n"`` → ``"go north"``
        ``"x spider"`` → ``"examine spider"``
        ``"I mark the door with an x"`` → unchanged
    """
    stripped = text.strip()
    if not stripped:
        return text

    lowered = stripped.lower()
    if lowered in _SINGLE_TOKEN_SHORTCUTS:
        return _SINGLE_TOKEN_SHORTCUTS[lowered]

    tokens = stripped.split(None, 1)
    first = tokens[0].lower()
    if first in _PREFIX_SHORTCUTS and len(tokens) == 2:
        rest = tokens[1].strip()
        if rest:
            return _PREFIX_SHORTCUTS[first].format(rest=rest)

    return text
