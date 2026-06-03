from __future__ import annotations

from typing import Callable

from mgmai.game.state_loader import StateLoader


class _Commands:
    def __init__(
        self,
        state_loader: StateLoader,
        render: Callable[[str], None],
        exit_fn: Callable[[], None],
        debug: bool = False,
    ):
        self._state = state_loader
        self._render = render
        self._exit = exit_fn
        self._debug = debug

    @property
    def debug(self) -> bool:
        return self._debug

    def handle(self, raw: str) -> bool:
        stripped = raw.strip()
        if not stripped.startswith("/"):
            return False

        parts = stripped[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handler = {
            "help": self._cmd_help,
            "h": self._cmd_help,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
            "q": self._cmd_exit,
            "save": self._cmd_save,
            "load": self._cmd_load,
            "status": self._cmd_status,
            "look": self._cmd_look,
            "l": self._cmd_look,
            "inventory": self._cmd_inventory,
            "inv": self._cmd_inventory,
            "history": self._cmd_history,
            "debug": self._cmd_debug,
        }.get(cmd)

        if handler is None:
            return False  # not a command; treat as game input

        handler(arg)
        return True

    # --- command implementations ---

    def _cmd_help(self, _: str) -> None:
        text = """\
[bold]Available Commands[/bold]

  /help, /h             Show this help
  /exit, /quit, /q      Exit the game
  /save [filename]      Save game (default: save.json)
  /load <filename>      Load a saved game
  /status               Show player status
  /look, /l             Look at the current room
  /inventory, /inv      Show your inventory
  /history              Show recent turn history
  /debug                Toggle debug mode (shows GMBriefing/EngineResult)

[bold]Tips[/bold]
  Type natural language to describe what your character does.
  The GM will interpret your intent and narrate the outcome.
"""
        self._render(text)

    def _cmd_exit(self, _: str) -> None:
        self._exit()

    def _cmd_save(self, arg: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game to save.[/red]")
            return
        filename = arg.strip() or "save.json"
        try:
            self._state.save(filename)
            self._render(f"[green]Game saved to {filename}[/green]")
        except Exception as e:
            self._render(f"[red]Save failed: {e}[/red]")

    def _cmd_load(self, arg: str) -> None:
        filename = arg.strip()
        if not filename:
            self._render("[red]Usage: /load <filename>[/red]")
            return
        try:
            adv_path = self._state.load_save(filename)
            self._render(
                f"[green]Game loaded from {filename} "
                f"(adventure: {adv_path})[/green]"
            )
            self._cmd_look("")
        except FileNotFoundError:
            self._render(f"[red]Save file not found: {filename}[/red]")
        except Exception as e:
            self._render(f"[red]Load failed: {e}[/red]")

    def _cmd_status(self, _: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game loaded.[/red]")
            return
        hs = self._state.hard_state
        ss = self._state.soft_state

        lines = ["[bold]Player Status[/bold]", ""]
        lines.append(f"  Location: {hs.player.location}")
        lines.append(f"  Turn:     {hs.turn_count}")

        if hs.game_over:
            lines.append(
                f"  [red]Game Over: {hs.game_over.type} — {hs.game_over.trigger}[/red]"
            )

        lines.append("")
        lines.append("[bold]Hard Inventory[/bold]")
        if hs.player.inventory:
            for item in hs.player.inventory:
                lines.append(f"  * {item}")
        else:
            lines.append("  (empty)")

        lines.append("")
        lines.append("[bold]Soft Inventory[/bold]")
        if ss.soft_inventory:
            for item in ss.soft_inventory:
                lines.append(f"  * {item}")
        else:
            lines.append("  (empty)")

        lines.append("")
        lines.append("[bold]Flags[/bold]")
        active = {k: v for k, v in hs.flags.items() if v}
        if active:
            for k, v in active.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append("  (none)")

        self._render("\n".join(lines))

    def _cmd_look(self, _: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game loaded.[/red]")
            return
        hs = self._state.hard_state
        corpus = self._state.corpus

        room = corpus.rooms.get(hs.player.location)
        if room is None:
            self._render(f"[red]Unknown room: {hs.player.location}[/red]")
            return

        lines = [
            f"[bold]{room.name}[/bold]",
            "",
            room.description,
            "",
            "[bold]Exits[/bold]",
        ]
        if room.exits:
            for ex in room.exits:
                hidden = " [dim](hidden)[/dim]" if ex.hidden else ""
                oneway = " [dim](one-way)[/dim]" if ex.one_way else ""
                lines.append(f"  * {ex.direction}{hidden}{oneway}")
        else:
            lines.append("  (none)")
        self._render("\n".join(lines))

    def _cmd_inventory(self, _: str) -> None:
        self._cmd_status(_)

    def _cmd_history(self, _: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game loaded.[/red]")
            return
        ss = self._state.soft_state

        entries = ss.turn_history[-10:]
        if not entries:
            self._render("[dim]No turn history yet.[/dim]")
            return

        lines = ["[bold]Recent History[/bold]", ""]
        for entry in entries:
            lines.append(
                f"  [bold]Turn {entry.turn}[/bold]: "
                f"{entry.engine_result_summary[:120]}"
            )
        self._render("\n".join(lines))

    def _cmd_debug(self, _: str) -> None:
        self._debug = not self._debug
        state = "ON" if self._debug else "OFF"
        self._render(f"[yellow]Debug mode: {state}[/yellow]")
