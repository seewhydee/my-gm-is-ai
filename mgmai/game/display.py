from __future__ import annotations

from mgmai.game.state_loader import StateLoader

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

    def render_intro(self, state_loader: StateLoader) -> None:
        corpus = state_loader.corpus
        adv = corpus.adventure

        title = adv.title
        intro = adv.introduction

        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(Rule(characters="="))
            self._console.print()
            panel = Panel(
                f"[bold italic]{title}[/bold italic]\n\n[intro]",
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

    # --- helpers ---

    def _render_room(self, state_loader: StateLoader) -> None:
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
