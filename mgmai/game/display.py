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

from __future__ import annotations

from typing import Any

from mgmai.engine.conditions import evaluate

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule

    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class Display:
    def __init__(self):
        if RICH_AVAILABLE:
            self._console = Console(highlight=False)

    # --- generic output ---

    def print(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print(text)
        else:
            print(text)

    def rule(self, title: str = "") -> None:
        if RICH_AVAILABLE:
            self._console.print(Rule(title))
        elif title:
            print(f"--- {title} ---")

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
        """Render a compact combat status panel between turns."""
        corpus = state_loader.corpus
        combat = hard.combat

        hp_bar_width = 10

        def _hp_bar(current: int, max_hp: int) -> str:
            if max_hp <= 0:
                return " " * hp_bar_width
            filled = max(0, min(hp_bar_width, round(current / max_hp * hp_bar_width)))
            empty = hp_bar_width - filled
            return "\u2588" * filled + "\u2591" * empty

        if RICH_AVAILABLE:
            from rich.panel import Panel
            from rich.text import Text

            lines: list[str] = []
            lines.append(f"[bold]Combat: Round {combat.round_number}[/bold]")
            lines.append("")

            initiative_str = " \u2192 ".join(
                f"[cyan]{c}[/cyan]" if c == "player" else c
                for c in combat.initiative_order
            )
            lines.append(f"[dim]Initiative:[/dim] {initiative_str}")
            lines.append("")

            for cid in combat.combatants:
                if cid == "player":
                    display_name = "Player"
                    name = f"[bold bright_white]{display_name:<15}[/bold bright_white]"
                    current = hard.player.current_hp or 0
                    max_hp = hard.player.max_hp or 0
                else:
                    entity = corpus.entities.get(cid) if corpus else None
                    display_name = (entity.name or cid) if entity else cid
                    name = f"{display_name:<15}"
                    state = hard.entity_states.get(cid, {})
                    current = state.get("current_hp") or 0
                    max_hp = (entity.combat.hp if entity and entity.combat else 0)

                bar = _hp_bar(current, max_hp)
                lines.append(
                    f"{name} HP {bar} {current}/{max_hp}"
                )

            lines.append("")
            lines.append("[dim italic]It's your turn.[/dim italic]")

            self._console.print()
            self._console.print(
                Panel("\n".join(lines), border_style="red", padding=(0, 1))
            )
            self._console.print()
        else:
            print()
            print(f"=== Combat: Round {combat.round_number} ===")
            initiative_str = " -> ".join(combat.initiative_order)
            print(f"Initiative: {initiative_str}")
            print()
            for cid in combat.combatants:
                if cid == "player":
                    name = "Player"
                    current = hard.player.current_hp or 0
                    max_hp = hard.player.max_hp or 0
                else:
                    entity = corpus.entities.get(cid) if corpus else None
                    name = (entity.name or cid) if entity else cid
                    state = hard.entity_states.get(cid, {})
                    current = state.get("current_hp") or 0
                    max_hp = (entity.combat.hp if entity and entity.combat else 0)
                bar = _hp_bar(current, max_hp)
                print(f"  {name:<15} HP {bar} {current}/{max_hp}")
            print()
            print("  It's your turn.")
            print()

    def _render_character_sheet(self, state_loader: Any) -> None:
        hard = state_loader.hard_state
        corpus = state_loader.corpus
        if hard is None or corpus is None:
            return
        stats = hard.player.stats
        if stats is None or corpus.stats is None:
            return

        from mgmai.engine.stat_checks import compute_modifier

        stat_entries = sorted(stats.items())
        lines: list[str] = []

        # Layout: 3 columns -> 2 rows for 6 stats
        for i in range(0, len(stat_entries), 3):
            row_stats = stat_entries[i : i + 3]
            pair_parts = []
            for key, val in row_stats:
                mod = compute_modifier(val, corpus.stats.system)
                sign = "+" if mod >= 0 else ""
                pair_parts.append(f"{key} {val:>2} ({sign}{mod})")
            lines.append("   ".join(pair_parts))

        if RICH_AVAILABLE:
            body = "\n".join(lines)
            panel = Panel(
                body,
                title="Character Sheet",
                border_style="cyan",
                padding=(0, 1),
            )
            self._console.print(panel)
        else:
            print()
            print("┌─ Character Sheet ───────────────────────┐")
            for line in lines:
                print(f"│ {line.ljust(30)}│")
            print("└───────────────────────────────────┘")
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
        """Format a room's visible exits as a string suitable for appending
        to narration.  ``room`` is a BriefingRoom or a corpus Room.

        Returns an empty string if there are no visible exits.
        """
        exits: list = getattr(room, "exits_available", None)
        if exits is None:
            exits = getattr(room, "exits", [])

        visible: list = []
        for e in exits:
            hidden = getattr(e, "hidden", False)
            if hidden:
                continue
            direction = getattr(e, "direction", "")
            one_way = getattr(e, "one_way", False)
            label = f"* {direction}"
            if one_way:
                label += " (one-way)"
            visible.append(label)

        if not visible:
            return ""

        prefix = " " * indent
        lines = [f"\n\n{prefix}**Exits:**"]
        for v in visible:
            lines.append(f"{prefix}{v}")
        return "\n".join(lines)

    def _render_room(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        hs = state_loader.hard_state
        room = corpus.rooms.get(hs.player.location)
        if room is None:
            self.print(f"[Unknown room: {hs.player.location}]")
            return

        visible_exits = []
        for e in room.exits:
            if e.hidden:
                if e.conditions:
                    all_met = True
                    for cond in e.conditions:
                        if not evaluate(cond, hs, state_loader.soft_state, corpus):
                            all_met = False
                            break
                    if not all_met:
                        continue
                else:
                    continue
            elif e.conditions:
                all_met = True
                for cond in e.conditions:
                    if not evaluate(cond, hs, state_loader.soft_state, corpus):
                        all_met = False
                        break
                if not all_met:
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
