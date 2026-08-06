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

"""Telegram message text utilities.

Pure functions, no PTB imports, so they stay unit-testable without the
optional ``telegram`` dependency installed.  The real Rich-markup →
Telegram-HTML converter is a later phase; for now command output simply
gets its Rich tags stripped.
"""

from __future__ import annotations

import re

TELEGRAM_MESSAGE_LIMIT = 4096

# Rich markup tags: ``[bold]``, ``[/bold]``, ``[dim cyan]``,
# ``[#ff0000]``…  The tag body must start with a letter (or ``/`` for a
# closing tag) so literal square brackets such as ``[3]`` in game text
# are left alone.
_RICH_TAG_RE = re.compile(r"\[/?[a-zA-Z][^\[\]]*\]")


def strip_rich_markup(text: str) -> str:
    """Remove Rich markup tags from *text*, leaving the content."""
    return _RICH_TAG_RE.sub("", text)


def chunk_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split *text* into chunks of at most *limit* characters.

    Splits on paragraph boundaries (``\\n\\n``); a single paragraph that
    exceeds the limit is hard-split at *limit* characters.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        piece = current + "\n\n" + para if current else para
        if len(piece) <= limit:
            current = piece
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(para) > limit:
            chunks.append(para[:limit])
            para = para[limit:]
        current = para
    if current:
        chunks.append(current)
    return chunks
