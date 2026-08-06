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

"""The front-end rendering contract.

``GameSession`` renders exclusively through an injected ``GameView``;
it never touches a terminal directly.  The Rich terminal renderer
(``mgmai.game.display.RichView``), the recording view used by the
headless harness, and the Telegram front-end each implement this
protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GameView(Protocol):
    """Rendering surface for a game session.

    ``print`` receives command output that may contain Rich markup
    (``[bold]…``); the other methods receive plain text or structured
    state.  Implementations decide how (or whether) to present each
    event — a buffering view (Telegram) flushes them as chat messages,
    the recording view (headless) stores them for inspection.
    """

    def render_intro(self, state: Any) -> None:
        """Render the adventure intro (title, credits, starting room)."""
        ...

    def render_narration(self, text: str) -> None:
        """Render turn narration (markdown prose)."""
        ...

    def render_status(self, state: Any) -> None:
        """Render the post-turn status / combat panel."""
        ...

    def render_error(self, text: str) -> None:
        ...

    def render_rest_menu(self, text: str) -> None:
        """Render rest-mode menu text (bookkeeping, not narration)."""
        ...

    def render_game_over(self, result: Any) -> None:
        ...

    def render_goodbye(self) -> None:
        ...

    def print(self, text: str) -> None:
        """Print command output (may contain Rich markup)."""
        ...
