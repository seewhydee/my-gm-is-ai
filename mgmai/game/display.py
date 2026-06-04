from __future__ import annotations

from typing import Any

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
        soft = state_loader.soft_state
        if hard is None:
            return

        loc = hard.player.location
        inv = hard.player.inventory
        turn = hard.turn_count
        active_flags = [k for k, v in hard.flags.items() if v]
        soft_inv = soft.soft_inventory if soft else []

        if RICH_AVAILABLE:
            parts = [f"[dim]Turn {turn}[/dim]"]
            parts.append(f"[dim]Location:[/dim] [cyan]{loc}[/cyan]")
            if inv:
                parts.append(f"[dim]Inventory:[/dim] {', '.join(inv)}")
            if soft_inv:
                parts.append(f"[dim]Misc:[/dim] {', '.join(soft_inv)}")
            if active_flags:
                parts.append(f"[dim]Flags:[/dim] {', '.join(active_flags)}")
            self._console.print(f"  {' | '.join(parts)}")
        else:
            parts = [f"Turn {turn}", f"Location: {loc}"]
            if inv:
                parts.append(f"Inventory: {', '.join(inv)}")
            if soft_inv:
                parts.append(f"Misc: {', '.join(soft_inv)}")
            if active_flags:
                parts.append(f"Flags: {', '.join(active_flags)}")
            print(f"  {' | '.join(parts)}")

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

    def _render_room(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        hs = state_loader.hard_state
        room = corpus.rooms.get(hs.player.location)
        if room is None:
            self.print(f"[Unknown room: {hs.player.location}]")
            return

        if RICH_AVAILABLE:
            lines = [f"[bold bright_white]{room.name}[/bold bright_white]", ""]
            lines.append(room.description)
            lines.append("")

            visible_exits = [e for e in room.exits if not e.hidden]
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
            visible_exits = [e for e in room.exits if not e.hidden]
            if visible_exits:
                print("Exits:")
                for e in visible_exits:
                    parts = [f"  {e.direction}"]
                    if e.one_way:
                        parts.append("(one-way)")
                    print("  ".join(parts))
            print()
