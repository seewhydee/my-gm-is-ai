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

"""Buffering ``GameView`` implementation for the Telegram front-end.

``GameSession`` renders through the view while ``submit()`` runs (in a
worker thread); the bot layer then flushes the buffered events to the
chat, in order.  Rendering is deliberately simple for now: plain text
messages.  In-place-edited status panels, keyboards, and Rich→HTML
conversion are later phases.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mgmai.game.status import build_combat_view, format_exits, snapshot_status
from mgmai.telegram.textutil import strip_rich_markup

# Fixed HP-bar width for the combat panel (no terminal to measure).
_BAR_WIDTH = 10


@dataclass
class ViewEvent:
    """One buffered render event, in emission order."""

    kind: str  # intro | narration | status | error | rest_menu | game_over | goodbye | print
    text: str


class TelegramView:
    """Accumulates render events during a turn; the bot flushes them.

    *scrub_prefixes* are absolute path prefixes (the chat's saves dir,
    the config dir) that must never leak into chat messages — e.g.
    ``Commands._cmd_save`` prints the full save path, which is fine for
    the CLI but not for Telegram.  They are stripped from every
    buffered event, longest prefix first (so a nested dir wins over
    its parent), wherever they appear in the text.
    """

    def __init__(self, scrub_prefixes: Iterable[str | Path] = ()) -> None:
        self._events: list[ViewEvent] = []
        self._scrub_prefixes = sorted(
            (str(p).rstrip("/\\") + os.sep for p in scrub_prefixes if p),
            key=len,
            reverse=True,
        )

    def drain(self) -> list[ViewEvent]:
        """Return the buffered events in order and clear the buffer."""
        events, self._events = self._events, []
        return events

    def _add(self, kind: str, text: str) -> None:
        for prefix in self._scrub_prefixes:
            text = text.replace(prefix, "")
        self._events.append(ViewEvent(kind, text))

    # --- game screens ---

    def render_intro(self, state: Any) -> None:
        corpus = state.corpus
        adv = corpus.adventure
        lines = [adv.title, "", adv.introduction]
        if adv.credits:
            parts = []
            if adv.credits.author:
                parts.append(f"Author: {adv.credits.author}")
            if adv.credits.source:
                parts.append(f"Source: {adv.credits.source}")
            if adv.credits.license:
                parts.append(f"License: {adv.credits.license}")
            if parts:
                lines += ["", " | ".join(parts)]
        hard = state.hard_state
        if hard is not None:
            room = corpus.rooms.get(hard.player.location)
            if room is not None:
                lines += ["", room.name, "", room.description]
                exits = format_exits(room)
                if exits:
                    lines.append(exits.lstrip("\n"))
        self._add("intro", "\n".join(lines))

    def render_narration(self, text: str) -> None:
        self._add("narration", text)

    def render_status(self, state: Any) -> None:
        hard = state.hard_state
        if hard is None:
            return
        if hard.combat is not None and hard.combat.active:
            text = _format_combat(build_combat_view(hard, state.corpus))
        else:
            text = _format_status_line(snapshot_status(state))
        self._add("status", text)

    def render_error(self, text: str) -> None:
        self._add("error", f"Error: {text}")

    def render_rest_menu(self, text: str) -> None:
        self._add("rest_menu", text)

    def render_game_over(self, result: Any) -> None:
        go_type = getattr(result, "type", "unknown")
        narrative = getattr(result, "narrative", None) or ""
        trigger = getattr(result, "trigger", "")
        if go_type == "win":
            title = "🎉 Victory!"
        elif go_type == "lose":
            title = "💀 Defeat"
        else:
            title = f"Game Over ({go_type})"
        parts = [title]
        if trigger:
            parts.append(f"Trigger: {trigger}")
        if narrative:
            parts.append(f"\n{narrative}")
        self._add("game_over", "\n".join(parts))

    def render_goodbye(self) -> None:
        self._add("goodbye", "Thanks for playing!")

    def print(self, text: str) -> None:
        """Command output; Rich markup stripped (converter is Phase 3)."""
        self._add("print", strip_rich_markup(text))


# ------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------


def _format_status_line(snapshot: Any) -> str:
    parts = [f"Turn {snapshot.turn_count}", f"Location: {snapshot.location}"]
    if snapshot.player_hp is not None:
        parts.append(f"HP {snapshot.player_hp}/{snapshot.player_max_hp}")
    if snapshot.active_flags:
        parts.append(f"Flags: {', '.join(snapshot.active_flags)}")
    return "  " + " | ".join(parts)


def _hp_bar(current: int, max_hp: int) -> str:
    if max_hp <= 0:
        return " " * _BAR_WIDTH
    filled = max(0, min(_BAR_WIDTH, round(current / max_hp * _BAR_WIDTH)))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _format_combat(view: Any) -> str:
    """Plain-text combat panel from the shared CombatView view-model."""

    def _row(row: Any) -> str:
        tag = ""
        if row.fled:
            tag = " (fled)"
        elif row.dead:
            tag = " †"
        line = f"  {row.name + tag:<20} HP {_hp_bar(row.hp, row.max_hp)} {row.hp}/{row.max_hp}"
        if row.status_effects_text:
            line += f" [{row.status_effects_text}]"
        if row.mitigation_text:
            line += f" ({row.mitigation_text})"
        pos: list[str] = []
        if row.engaged_with:
            pos.append(f"⚔ {', '.join(row.engaged_with)}")
        if row.impeded:
            pos.append("(impeded)")
        if pos:
            line += " " + " ".join(pos)
        return line

    initiative = " → ".join(view.initiative_order)
    lines = [f"⚔ Combat — Round {view.round_number}", f"Initiative: {initiative}", ""]
    lines.append("Party")
    lines.extend(_row(r) for r in view.party)
    lines.append("Enemies")
    lines.extend(_row(r) for r in view.enemies)
    lines += ["", view.footer, "It's your turn."]
    return "\n".join(lines)
