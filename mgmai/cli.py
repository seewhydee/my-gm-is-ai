#!/usr/bin/env python3
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

"""MGMAI: My GM is AI — an AI-driven Game Master for tabletop RPG adventures.

Usage:
    python -m mgmai.cli <adventure_path>          Start a new game
    python -m mgmai.cli <adventure_path> --load save.json  Resume a saved game
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from dataclasses import replace
from pathlib import Path

from mgmai.config import (
    AppConfig,
    Credentials,
    get_autosave_path,
    get_config_dir,
    load_app_config,
    load_credentials,
    resolve_api_key,
    save_app_config,
    save_credentials,
)
from mgmai.logging import setup_logging
from mgmai.state.manager import StateManager
from mgmai.llm.client import LLMClient
from mgmai.llm.model_config import get_model_config, list_known_models
from mgmai.game.display import Display
from mgmai.game.loop import GameLoop


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mgmai",
        description="My GM is AI — an AI-driven Game Master for tabletop RPG adventures")

    ## Adventure settings
    parser.add_argument(
        "adventure", nargs="?",
        help="Path to adventure directory (must contain corpus.json, hard-state.json, soft-state.json)")

    parser.add_argument(
        "--load", dest="load_file", default=None, metavar="FILE",
        help="Load a saved game instead of starting fresh")

    parser.add_argument(
        "--char-sheet", dest="char_sheet", default=None, metavar="FILE",
        help="Path to a custom player character sheet")

    ## Not sure we need this, but...
    parser.add_argument(
        "--config-dir", default=None, metavar="DIR",
        help="Path to config directory, overriding user default")

    ## Logging and debugging
    parser.add_argument("--debug", action="store_true", default=False,
                        help=argparse.SUPPRESS)
    parser.add_argument("--log-level", default=None,
                        metavar="LEVEL",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR",
                                 "debug", "info", "warning", "error"],
                        help=argparse.SUPPRESS)
    parser.add_argument("--log-file", default=None, metavar="FILE",
                        help="Write log output to FILE")

    parser.add_argument("--version", action="version",
                        version="mgmai 0.1.0")

    ## LLM settings
    parser.add_argument(
        "--api-key", default=None,
        help="API key (overrides MGMAI_API_KEY and saved credentials)")
    parser.add_argument(
        "--base-url", default=None,
        help="API base URL (overrides MGMAI_BASE_URL and saved config)")
    parser.add_argument(
        "--model", default=None,
        help="Model name (overrides MGMAI_MODEL and saved config)")
    args = parser.parse_args(argv)

    log_level = (args.log_level or ("DEBUG" if args.debug else "INFO")).upper()
    setup_logging(level=log_level, log_file=args.log_file)
    debug = log_level == "DEBUG"

    display = Display()

    if args.adventure is None:
        display.print(
            "[bold]Usage:[/bold] python -m mgmai.cli [OPTIONS] <adventure_path>\n"
            "Try --help for more information\n"
        )
        sys.exit(0)

    config_dir = get_config_dir(args.config_dir)
    app_config = load_app_config(config_dir)
    credentials = load_credentials(config_dir)

    # Resolve API key: CLI arg > env var > credentials file
    env_key = os.environ.get("MGMAI_API_KEY")
    api_key = resolve_api_key(cli_arg=args.api_key,
                              env_var=env_key,
                              credentials=credentials)

    # Resolve model name preliminarily: CLI arg > env var > config file
    env_model = os.environ.get("MGMAI_MODEL")
    model_name = args.model or env_model or app_config.model_name

    # Resolve base URL preliminarily: CLI arg > env var > config file
    env_url = os.environ.get("MGMAI_BASE_URL")
    base_url = args.base_url or env_url or app_config.base_url

    if not api_key:
        api_key, model_name, base_url = _prompt_for_credentials(
            display, config_dir, credentials, app_config)

    config = get_model_config(model_name)
    if base_url:
        config = replace(config, base_url=base_url)

    ## Read model temperatures from config
    if app_config.ruling_temperature is not None:
        config = replace(config, ruling_temperature=app_config.ruling_temperature)
    if app_config.prose_temperature is not None:
        config = replace(config, prose_temperature=app_config.prose_temperature)

    adventure_path = Path(args.adventure)

    state_manager = StateManager()
    state_manager._config_dir = config_dir

    if args.load_file and args.char_sheet:
        display.render_error("Cannot specify both --char-sheet and --load")
        sys.exit(1)

    try:
        if args.load_file:
            load_path = Path(args.load_file)
            if not load_path.is_file():
                display.render_error(f"Save file not found: {args.load_file}")
                sys.exit(1)
            adv_path = state_manager.load_save(load_path)
            display.print(f"[green]Resuming from {args.load_file} (adventure: {adv_path})[/green]")
        else:
            state_manager.load_all(adventure_path)
            if args.char_sheet:
                char_sheet_path = Path(args.char_sheet)
                if not char_sheet_path.is_file():
                    display.render_error(f"Character sheet file not found: {args.char_sheet}")
                    sys.exit(1)
                state_manager.apply_char_sheet(char_sheet_path)
    except FileNotFoundError as e:
        display.render_error(str(e))
        sys.exit(1)
    except ValueError as e:
        display.render_error(str(e))
        sys.exit(1)
    except Exception as e:
        display.render_error(f"Failed to load state: {e}")
        sys.exit(1)

    # Persist last-used adventure path
    app_config.adventure_path = str(adventure_path.resolve())
    save_app_config(app_config, config_dir)

    llm_client = LLMClient(api_key=api_key, config=config)

    loop = GameLoop(state_manager, llm_client, debug=debug,
                    display=display, config_dir=config_dir)
    loop.start()


def _prompt_for_credentials(
    display: Display,
    config_dir: Path,
    credentials: Credentials,
    app_config: AppConfig,
) -> tuple[str, str, str]:
    """Prompt for LLM credentials when no API key is found.

    Return ``(api_key, model_name, base_url)``.
    Print a non-interactive error message if stdin is not a TTY
    """
    if not sys.stdin.isatty():
        display.render_error(
            "No model credentials found.  Set the MGMAI_BASE_URL,"
            " MGMAI_MODEL, and MGMAI_API_KEY env vars, or pass"
            " --base-url, --model, and --api-key, or run interactively"
            " to be prompted."
        )
        sys.exit(1)

    default_model = app_config.model_name
    default_url = app_config.base_url or "https://api.deepseek.com"

    display.print("\n[yellow]No API key found from environment or saved credentials.[/yellow]")
    display.print(
        "Please enter your LLM configuration below. Press Enter to accept defaults.\n"
    )

    base_url = input(f"Base URL [{default_url}]: ").strip()
    if not base_url:
        base_url = default_url

    model_name = input(f"Model name [{default_model}]: ").strip()
    if not model_name:
        model_name = default_model

    while True:
        api_key = getpass.getpass("API key: ").strip()
        if api_key:
            break
        display.print("[red]API key cannot be empty.[/red]")

    credentials.api_key = api_key
    try:
        save_credentials(credentials, config_dir)
    except OSError as e:
        display.print(f"[yellow]Could not save API key: {e}[/yellow]")

    app_config.model_name = model_name
    app_config.base_url = base_url
    try:
        save_app_config(app_config, config_dir)
    except OSError as e:
        display.print(f"[yellow]Could not save configuration: {e}[/yellow]")

    display.print("[green]Configuration saved.[/green]\n")
    return api_key, model_name, base_url


if __name__ == "__main__":
    main()
