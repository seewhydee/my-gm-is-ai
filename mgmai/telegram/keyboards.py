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

"""Inline-keyboard construction for the Telegram front-end.

Keyboards are plain data — a list of rows of ``(label, callback_data)``
pairs — so the layout logic is PTB-free and unit-testable; the adapter
in ``bot.py`` turns them into ``InlineKeyboardMarkup``.  Callback data
must fit Telegram's 64-byte limit, so buttons carry short keys with an
index (``adv:0``, ``save:2``) that the bot resolves back to a path,
never an embedded path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mgmai.telegram.sessions import SaveInfo

# (label, callback_data) rows.
Keyboard = list[list[tuple[str, str]]]

_LABEL_LIMIT = 40


def _truncate(text: str, limit: int = _LABEL_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def main_menu_keyboard(*, has_save: bool) -> Keyboard:
    rows: Keyboard = [[("New game", "menu:new")]]
    if has_save:
        rows.append([("Continue", "menu:continue")])
    rows.append([("Help", "menu:help")])
    return rows


def adventure_picker_keyboard(titles: list[str]) -> Keyboard:
    """One button per adventure, indexed into the bot's adventure list."""
    return [[(_truncate(title), f"adv:{i}")] for i, title in enumerate(titles)]


def confirm_keyboard(yes_label: str, yes_data: str) -> Keyboard:
    return [[(yes_label, yes_data), ("Cancel", "menu:main")]]


def save_browser_keyboard(saves: list[SaveInfo]) -> Keyboard:
    """One button per save, indexed into the chat's save listing
    (recomputed when the callback arrives).  When the saves span more
    than one adventure, each label carries the adventure name."""
    adventures = {s.adventure for s in saves if s.adventure}
    show_adventure = len(adventures) > 1
    return [
        [(_save_label(s, show_adventure=show_adventure), f"save:{i}")]
        for i, s in enumerate(saves)
    ]


def game_over_keyboard() -> Keyboard:
    return [
        [("Restart adventure", "go:restart")],
        [("Load save", "go:load")],
        [("Choose adventure", "go:choose")],
    ]


def back_to_menu_keyboard() -> Keyboard:
    return [[("Back", "menu:main")]]


def _save_label(save: SaveInfo, *, show_adventure: bool = False) -> str:
    stamp = (datetime.fromtimestamp(save.mtime, tz=UTC)
             .astimezone().strftime("%Y-%m-%d %H:%M"))
    name = save.name
    if show_adventure and save.adventure:
        name = f"{save.adventure}/{name}"
    label = f"{name} · {stamp}"
    if save.snippet:
        label += f" — {_truncate(save.snippet, 40)}"
    return label
