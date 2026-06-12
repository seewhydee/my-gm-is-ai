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

import getpass
from pathlib import Path
from typing import Any, Callable

from mgmai.llm.model_config import get_model_config, list_known_models


class Commands:
    def __init__(
        self,
        state_loader: Any,
        render: Callable[[str], None],
        exit_fn: Callable[[], None],
        debug: bool = False,
        on_load: Callable[[], None] | None = None,
        config_dir: str | Path | None = None,
    ):
        self._state = state_loader
        self._render = render
        self._exit = exit_fn
        self._debug = debug
        self._on_load = on_load
        self._config_dir = Path(config_dir) if config_dir else None

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
            "models": self._cmd_models,
        }.get(cmd)

        if handler is None:
            return False

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
  /models               Configure model and API key

[bold]Tips[/bold]
  Type natural language to describe what your character does.
  The GM will interpret your intent and narrate the outcome.
  e.g. "look around", "check my inventory", "what happened?"
"""
        self._render(text)

    def _cmd_exit(self, _: str) -> None:
        self._exit()

    def _resolve_save_path(self, filename: str) -> Path:
        """Resolve a save filename to a path.

        Absolute paths are returned as-is.  Relative paths are placed in
        the config directory's ``saves/<adventure>/`` folder.
        """
        path = Path(filename)
        if path.is_absolute():
            return path
        return self._get_saves_dir() / filename

    def _get_saves_dir(self) -> Path:
        from mgmai.config import get_saves_dir

        adv_name = self._adventure_name()
        return get_saves_dir(adv_name, self._config_dir)

    def _adventure_name(self) -> str:
        if getattr(self._state, "_adventure_dir", None):
            return self._state._adventure_dir.name
        return "game"

    def _cmd_save(self, arg: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game to save.[/red]")
            return
        filename = arg.strip() or "save.json"
        try:
            save_path = self._resolve_save_path(filename)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            self._state.save(str(save_path))
            self._render(f"[green]Game saved to {save_path}[/green]")
        except Exception as e:
            self._render(f"[red]Save failed: {e}[/red]")

    def _cmd_load(self, arg: str) -> None:
        filename = arg.strip()
        if not filename:
            self._render("[red]Usage: /load <filename>[/red]")
            return

        load_path = Path(filename)
        if not load_path.is_absolute():
            load_path = self._get_saves_dir() / filename

        try:
            adv_path = self._state.load_save(str(load_path))
            self._render(
                f"[green]Game loaded from {load_path} "
                f"(adventure: {adv_path})[/green]"
            )
            if self._on_load is not None:
                self._on_load()
        except FileNotFoundError:
            self._render(f"[red]Save file not found: {load_path}[/red]")
        except Exception as e:
            self._render(f"[red]Load failed: {e}[/red]")

    def _cmd_debug(self, _: str) -> None:
        self._debug = not self._debug
        state = "ON" if self._debug else "OFF"
        self._render(f"[yellow]Debug mode: {state}[/yellow]")

    def _cmd_models(self, _: str) -> None:
        self._render("\n[bold]Model Configuration[/bold]\n")

        from mgmai.config import (
            load_app_config,
            load_credentials,
            save_app_config,
            save_credentials,
        )

        app_config = load_app_config(self._config_dir)
        credentials = load_credentials(self._config_dir)

        current_model = app_config.model_name or "deepseek-v4-flash"
        current_api = credentials.api_key or "(not set)"
        if current_api and current_api != "(not set)":
            current_api = current_api[:4] + "..." + current_api[-4:] if len(current_api) > 8 else "***"

        self._render(f"  Current model:    [cyan]{current_model}[/cyan]")
        self._render(f"  Current API key:  [dim]{current_api}[/dim]")
        if app_config.base_url:
            self._render(f"  Current base URL: [dim]{app_config.base_url}[/dim]")
        self._render("")

        # --- Model selection ---
        known = list_known_models()
        self._render("[bold]Known models:[/bold]")
        for i, name in enumerate(known, 1):
            cfg = get_model_config(name)
            marker = " [dim](current)[/dim]" if name == current_model else ""
            self._render(f"  {i}. [cyan]{name}[/cyan]{marker} — {cfg.base_url}")
        self._render(f"  {len(known) + 1}. [yellow]Custom model...[/yellow]")

        try:
            choice = input("\n  Select model number (or Enter to keep current): ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        if choice:
            try:
                idx = int(choice)
                if 1 <= idx <= len(known):
                    new_model = known[idx - 1]
                elif idx == len(known) + 1:
                    new_model = input("  Enter model name: ").strip()
                    if not new_model:
                        self._render("[red]Model name cannot be empty.[/red]")
                        return
                else:
                    self._render("[red]Invalid selection.[/red]")
                    return
            except ValueError:
                new_model = choice
        else:
            new_model = current_model

        # --- API key ---
        self._render(f"\n[bold]API Key[/bold]")
        self._render("  (leave blank to keep current)")
        try:
            new_key = getpass.getpass("  Enter API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        if new_key:
            credentials.api_key = new_key
            try:
                save_credentials(credentials, self._config_dir)
                self._render("  [green]API key saved.[/green]")
            except OSError as e:
                self._render(f"  [yellow]Could not save API key: {e}[/yellow]")
        else:
            self._render("  [dim]API key unchanged.[/dim]")

        # --- Base URL ---
        model_cfg = get_model_config(new_model)
        default_url = model_cfg.base_url
        self._render(f"\n[bold]Base URL[/bold]")
        self._render(f"  Default: [dim]{default_url}[/dim]")
        self._render("  (leave blank to use default)")
        try:
            new_url = input("  Enter base URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        # --- Save config ---
        app_config.model_name = new_model
        app_config.base_url = new_url if new_url else None
        try:
            save_app_config(app_config, self._config_dir)
            self._render(f"\n[green]Config saved.[/green]")
            self._render(
                f"  Model: [cyan]{new_model}[/cyan]"
                + (f"  Base URL: {new_url if new_url else default_url}" if new_url else "")
            )
            self._render("  [dim]Changes take effect on next game start.[/dim]")
        except OSError as e:
            self._render(f"\n[red]Could not save config: {e}[/red]")
