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
optional ``telegram`` dependency installed.

The markup split: narration prose carries minimal Markdown
(``**bold**``) and goes through ``md_to_telegram_html``; ``Commands``
output carries Rich markup (``[bold]…``) and goes through
``rich_to_telegram_html``.  Both run at flush time (in
``BotRuntime._flush``), per event kind, after chunking — the view
buffers raw text.
"""

from __future__ import annotations

import html
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


# ------------------------------------------------------------------
# Rich markup → Telegram HTML
# ------------------------------------------------------------------

# Rich style words that have a Telegram HTML equivalent.
_RICH_STYLE_TAGS = {
    "bold": "b", "b": "b",
    "italic": "i", "i": "i",
    "underline": "u", "u": "u",
    "strike": "s", "s": "s",
    "code": "code",
}

# Rich style words with no Telegram HTML equivalent: unwrapped to
# their content (dim is de-emphasis; colors don't exist in Telegram).
_RICH_IGNORE_WORDS = {
    "dim", "reverse", "blink", "conceal", "on", "not",
    "black", "red", "green", "yellow", "blue", "magenta", "cyan",
    "white", "grey", "gray", "default",
    "bright_black", "bright_red", "bright_green", "bright_yellow",
    "bright_blue", "bright_magenta", "bright_cyan", "bright_white",
}

_RICH_TOKEN_RE = re.compile(r"\[(/?)([^\[\]]*)\]")


def _rich_open_tags(body: str) -> list[str] | None:
    """Map a Rich opening-tag body to HTML tags.

    Returns the list of HTML tag names (empty for pure color/dim
    styles, which are unwrapped), or None when the body contains an
    unknown word — the caller strips the tag entirely.
    """
    tags: list[str] = []
    for word in body.split():
        if word in _RICH_STYLE_TAGS:
            tag = _RICH_STYLE_TAGS[word]
            if tag not in tags:
                tags.append(tag)
        elif word in _RICH_IGNORE_WORDS or word.startswith("#"):
            continue
        else:
            return None
    return tags


def rich_to_telegram_html(text: str) -> str:
    """Convert Rich markup (``[bold]…``) to Telegram HTML.

    Styles with an HTML equivalent become tags; colors and ``dim``
    unwrap to their content; unknown tags are stripped.  Content is
    HTML-escaped, and the result always has balanced tags: a closing
    tag closes everything up to its matching opener (unmatched closers
    are dropped), and openers left open at the end are closed in
    reverse order.
    """
    out: list[str] = []
    # Stack of (key, html_tags) for open Rich tags; the key is the
    # tag body's first word, matched by closing tags.
    stack: list[tuple[str, list[str]]] = []
    pos = 0
    for match in _RICH_TOKEN_RE.finditer(text):
        out.append(html.escape(text[pos:match.start()], quote=False))
        pos = match.end()
        closing, body = match.group(1) == "/", match.group(2).strip()
        if closing:
            key = body.split()[0] if body else ""
            # Find the matching opener; [/] (empty key) closes the
            # most recent one.
            idx = next(
                (i for i in range(len(stack) - 1, -1, -1)
                 if not key or stack[i][0] == key),
                None,
            )
            if idx is None:
                continue  # unmatched closer: drop it
            for _, tags in reversed(stack[idx:]):
                out.extend(f"</{t}>" for t in reversed(tags))
            del stack[idx:]
            continue
        if not body or not body[0].isalpha():
            out.append(html.escape(match.group(0), quote=False))
            continue  # literal bracket text like "[3]"
        tags = _rich_open_tags(body)
        if tags is None:
            continue  # unknown tag: strip it
        if tags:
            out.extend(f"<{t}>" for t in tags)
            stack.append((body.split()[0], tags))
        # Pure color/dim tags emit nothing and are not stacked.
    out.append(html.escape(text[pos:], quote=False))
    for _, tags in reversed(stack):
        out.extend(f"</{t}>" for t in reversed(tags))
    return "".join(out)


def md_to_telegram_html(text: str) -> str:
    """Convert the narration's minimal Markdown to Telegram HTML.

    Narration prose uses ``**bold**`` (the CLI renders it via
    ``rich.Markdown``); Telegram messages are sent with HTML parse
    mode, so ``**bold**`` becomes ``<b>bold</b>`` and everything else
    is HTML-escaped.  If the ``**`` delimiters are unbalanced (possible
    when a message was split mid-span), they are stripped rather than
    risking a malformed-HTML rejection from Telegram.
    """
    escaped = html.escape(text, quote=False)
    parts = escaped.split("**")
    if len(parts) % 2 == 0:
        return escaped.replace("**", "")
    return "".join(
        f"<b>{part}</b>" if i % 2 else part for i, part in enumerate(parts)
    )


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
