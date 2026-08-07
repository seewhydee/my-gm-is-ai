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

"""Rich terminal implementation of the GameView contract."""

from __future__ import annotations

from typing import Any

from mgmai.engine.utils import is_exit_visible
from mgmai.game.status import build_combat_view
from mgmai.game.status import (
    format_exits as _format_exits,
)

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class RichView:
    def __init__(self):
        if RICH_AVAILABLE:
            self._console = Console(highlight=False)

    # --- generic output ---

    def print(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print(text)
        else:
            print(text)

    # --- game screens ---

    def render_intro(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        adv = corpus.adventure

        title = adv.title
        intro = adv.introduction

        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(Rule(characters="="))
            self._console.print()
            panel = Panel(
                f"[bold italic]{title}[/bold italic]\n\n{intro}",
                border_style="bold cyan",
                padding=(1, 2),
            )
            self._console.print(panel)
            self._console.print()
            if adv.credits:
                c = adv.credits
                parts = []
                if c.author:
                    parts.append(f"Author: {c.author}")
                if c.source:
                    parts.append(f"Source: {c.source}")
                if c.license:
                    parts.append(f"License: {c.license}")
                self._console.print(
                    Text(" | ".join(parts), style="dim italic")
                )
            self._console.print()
            self._console.print(Rule(characters="="))
            self._console.print()
            self._render_room(state_loader)
        else:
            print()
            print("=" * 60)
            print(title)
            print()
            print(intro)
            print()
            print("=" * 60)
            print()
            self._render_room(state_loader)

    def render_narration(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print()
            panel = Panel(
                Markdown(text),
                border_style="magenta",
                padding=(0, 1),
            )
            self._console.print(panel)
            self._console.print()
        else:
            print()
            print(text)
            print()

    def render_goodbye(self) -> None:
        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(
                Panel(
                    "Thanks for playing!",
                    border_style="dim cyan",
                )
            )
        else:
            print()
            print("Thanks for playing!")

    def render_error(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print(f"[bold red]Error:[/bold red] {text}")
        else:
            print(f"Error: {text}")

    def render_rest_menu(self, text: str) -> None:
        """Render rest-mode menu text (bookkeeping, not narration)."""
        if RICH_AVAILABLE:
            self._console.print(text)
        else:
            print(text)

    def render_status(self, state_loader: Any) -> None:
        hard = state_loader.hard_state
        if hard is None:
            return

        # Combat status takes priority
        if hard.combat is not None and hard.combat.active:
            self._render_combat_status(hard, state_loader)
            return

        loc = hard.player.location
        turn = hard.turn_count
        active_flags = [k for k, v in hard.flags.items() if v]

        if RICH_AVAILABLE:
            parts = [f"[dim]Turn {turn}[/dim]"]
            parts.append(f"[dim]Location:[/dim] [cyan]{loc}[/cyan]")
            if active_flags:
                parts.append(f"[dim]Flags:[/dim] {', '.join(active_flags)}")
            self._console.print(f"  {' | '.join(parts)}")
        else:
            parts = [f"Turn {turn}", f"Location: {loc}"]
            if active_flags:
                parts.append(f"Flags: {', '.join(active_flags)}")
            print(f"  {' | '.join(parts)}")

    def _render_combat_status(self, hard: Any, state_loader: Any) -> None:
        """Render a compact combat status panel between turns.

        Layout adapts to the terminal width: narrow terminals get a
        single stacked column; wide ones (>= 100 cols) get a two-column
        Party-vs-Enemies layout with a wider HP bar.  Rows show active
        status effects and, for enemies, damage mitigations the party has
        already discovered by landing hits (derived from the combat log,
        so nothing the player hasn't learned is leaked).

        The panel data comes from the shared ``CombatView`` builder
        (``mgmai.game.status``); only the terminal-specific rendering
        (bar width, columns, Rich markup) lives here.
        """
        view_model = build_combat_view(hard, state_loader.corpus)

        if RICH_AVAILABLE:
            width = self._console.width
        else:
            import shutil
            width = shutil.get_terminal_size().columns
        wide = width >= 100
        bar_width = 14 if wide else 10

        def _hp_bar(current: int, max_hp: int) -> str:
            if max_hp <= 0:
                return " " * bar_width
            filled = max(0, min(bar_width, round(current / max_hp * bar_width)))
            empty = bar_width - filled
            return "█" * filled + "░" * empty

        def _status_tag(row: Any) -> str:
            if row.fled:
                return "(fled)"
            if row.dead:
                return "†"
            return ""

        def _positioning_text(row: Any) -> str:
            """e.g. '⚔ Goblin, Wolf (impeded)' — engagement partners and
            the pending impede flag."""
            parts: list[str] = []
            if row.engaged_with:
                parts.append(f"⚔ {', '.join(row.engaged_with)}")
            if row.impeded:
                parts.append("(impeded)")
            return " ".join(parts)

        if RICH_AVAILABLE:
            from rich.console import Group
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text

            init_parts: list[str] = []
            for c in view_model.initiative_order:
                label = c
                if c == view_model.current_cid:
                    label = f"[bold underline]{label}[/bold underline]"
                if c == "player":
                    label = f"[cyan]{label}[/cyan]"
                init_parts.append(label)
            initiative_str = " → ".join(init_parts)

            def _rich_row(row: Any) -> str:
                name = f"{row.name} {_status_tag(row)}".strip()
                padded = f"{name:<18}"
                if row.cid == "player":
                    padded = f"[bold bright_white]{padded}[/bold bright_white]"
                line = (
                    f"{padded} HP {_hp_bar(row.hp, row.max_hp)} "
                    f"{row.hp}/{row.max_hp}"
                )
                if row.status_effects:
                    line += f" [yellow]\\[{row.status_effects_text}][/yellow]"
                if row.mitigation_text:
                    line += f" [dim]({row.mitigation_text})[/dim]"
                pos = _positioning_text(row)
                if pos:
                    line += f" [dim]{pos}[/dim]"
                if row.dead or row.fled:
                    line = f"[dim]{line}[/dim]"
                return line

            header = Text.from_markup(
                f"[bold]Combat: Round {view_model.round_number}[/bold]\n"
                f"[dim]Initiative:[/dim] {initiative_str}"
            )
            footer_text = Text.from_markup(
                f"[dim]{view_model.footer}[/dim]\n[dim italic]It's your turn.[/dim italic]"
            )
            party_lines = ["[bold]Party[/bold]"] + [_rich_row(r) for r in view_model.party]
            enemy_lines = ["[bold]Enemies[/bold]"] + [_rich_row(r) for r in view_model.enemies]
            if wide:
                grid = Table.grid(padding=(0, 0, 0, 4))
                grid.add_column()
                grid.add_column()
                grid.add_row(
                    Text.from_markup("\n".join(party_lines)),
                    Text.from_markup("\n".join(enemy_lines)),
                )
                body: Any = grid
            else:
                lines = party_lines + [""] + enemy_lines
                body = Text.from_markup("\n".join(lines))

            self._console.print()
            self._console.print(
                Panel(
                    Group(header, "", body, "", footer_text),
                    border_style="red",
                    padding=(0, 1),
                )
            )
            self._console.print()
        else:
            print()
            print(f"=== Combat: Round {view_model.round_number} ===")
            initiative_str = " -> ".join(
                f"»{c}«" if c == view_model.current_cid else c
                for c in view_model.initiative_order
            )
            print(f"Initiative: {initiative_str}")
            print()

            def _plain_row(row: Any) -> str:
                name = f"{row.name} {_status_tag(row)}".strip()
                line = (
                    f"  {name:<18} HP {_hp_bar(row.hp, row.max_hp)} "
                    f"{row.hp}/{row.max_hp}"
                )
                if row.status_effects:
                    line += f" [{row.status_effects_text}]"
                if row.mitigation_text:
                    line += f" ({row.mitigation_text})"
                pos = _positioning_text(row)
                if pos:
                    line += f" {pos}"
                return line

            print("Party:")
            for row in view_model.party:
                print(_plain_row(row))
            print()
            print("Enemies:")
            for row in view_model.enemies:
                print(_plain_row(row))
            print()
            print(f"  {view_model.footer}")
            print("  It's your turn.")
            print()

    def render_game_over(self, result: Any) -> None:
        go_type = getattr(result, "type", "unknown")
        narrative = getattr(result, "narrative", None) or ""
        trigger = getattr(result, "trigger", "")

        if go_type == "win":
            title = "🎉 Victory!"
            style = "bold green"
            border = "green"
        elif go_type == "lose":
            title = "💀 Defeat"
            style = "bold red"
            border = "red"
        else:
            title = f"Game Over ({go_type})"
            style = "bold yellow"
            border = "yellow"

        text_parts = [f"[{style}]{title}[/{style}]"]
        if trigger:
            text_parts.append(f"[dim]Trigger:[/dim] {trigger}")
        if narrative:
            text_parts.append(f"\n{narrative}")

        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(
                Panel(
                    "\n".join(text_parts),
                    border_style=border,
                    padding=(1, 2),
                )
            )
            self._console.print()
        else:
            print()
            print(title)
            if trigger:
                print(f"Trigger: {trigger}")
            if narrative:
                print(narrative)
            print()

    # --- helpers ---

    @staticmethod
    def format_exits(room: Any, indent: int = 0) -> str:
        """Format a room's visible exits (delegates to the shared
        front-end-agnostic helper in ``mgmai.game.status``)."""
        return _format_exits(room, indent)

    def _render_room(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        hs = state_loader.hard_state
        room = corpus.rooms.get(hs.player.location)
        if room is None:
            self.print(f"[Unknown room: {hs.player.location}]")
            return

        visible_exits = []
        for e in room.exits:
            if not is_exit_visible(e, hs, state_loader.soft_state, corpus):
                continue
            visible_exits.append(e)

        if RICH_AVAILABLE:
            lines = [f"[bold bright_white]{room.name}[/bold bright_white]", ""]
            lines.append(room.description)
            lines.append("")

            if visible_exits:
                exit_lines = [
                    f"* {e.direction}" + (" [dim](one-way)[/dim]" if e.one_way else "")
                    for e in visible_exits
                ]
                lines.append("[bold]Exits:[/bold]")
                lines.extend(exit_lines)
            else:
                lines.append("[bold]Exits:[/bold] (none visible)")

            self._console.print()
            panel = Panel(
                "\n".join(lines),
                border_style="green",
                padding=(0, 1),
            )
            self._console.print(panel)
            self._console.print()
        else:
            print()
            print(f"--- {room.name} ---")
            print()
            print(room.description)
            print()
            if visible_exits:
                print("Exits:")
                for e in visible_exits:
                    parts = [f"  {e.direction}"]
                    if e.one_way:
                        parts.append("(one-way)")
                    print("  ".join(parts))
            print()


# Back-compat alias: the class was introduced under this name and
# existing imports/tests keep using it.
Display = RichView
