from __future__ import annotations

import sys
from typing import Any

from mgmai.game.commands import _Commands
from mgmai.game.display import Display
from mgmai.game.state_loader import StateLoader


class GameLoop:
    def __init__(self, state_loader: StateLoader, llm_client: Any = None, *, debug: bool = False):
        self._state = state_loader
        self._llm = llm_client
        self._display = Display()
        self._running = False
        self._commands = _Commands(
            state_loader=state_loader,
            render=self._display.print,
            exit_fn=self._do_exit,
            debug=debug,
        )

    @property
    def debug(self) -> bool:
        return self._commands.debug

    def start(self) -> None:
        self._display.render_intro(self._state)
        self._running = True
        self._repl()

    # --- REPL ---

    def _repl(self) -> None:
        while self._running:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                self._display.print()
                self._do_exit()
                return

            if not line.strip():
                continue

            if self._commands.handle(line):
                continue

            self._run_turn(line)

    # --- turn running ---

    def _run_turn(self, player_input: str) -> None:
        """Execute one game turn.

        Currently a stub — the engine / LLM integration (Phases 2-6) is not
        yet implemented.  Slash commands are handled before this point.
        """
        narration = (
            "[bold yellow]Engine not yet implemented.[/bold yellow]\n\n"
            "The game loop is running, but the LLM / engine phases (2-6) "
            "have not been connected yet.  "
            f"You typed: [italic]\"{player_input}\"[/italic]\n\n"
            "Use [bold]/help[/bold] to see available commands."
        )
        self._display.render_narration(narration)

    # --- internal ---

    def _do_exit(self) -> None:
        self._running = False
        self._display.render_goodbye()
        sys.exit(0)
