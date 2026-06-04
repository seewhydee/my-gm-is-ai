from __future__ import annotations

from typing import Callable

from mgmai.game.state_loader import StateLoader


class Commands:
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
  /debug                Toggle debug mode (shows GMBriefing/EngineResult)

[bold]Tips[/bold]
  Type natural language to describe what your character does.
  The GM will interpret your intent and narrate the outcome.
  e.g. "look around", "check my inventory", "what happened?"
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
        except FileNotFoundError:
            self._render(f"[red]Save file not found: {filename}[/red]")
        except Exception as e:
            self._render(f"[red]Load failed: {e}[/red]")

    def _cmd_debug(self, _: str) -> None:
        self._debug = not self._debug
        state = "ON" if self._debug else "OFF"
        self._render(f"[yellow]Debug mode: {state}[/yellow]")
