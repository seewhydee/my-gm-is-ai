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
        description="My GM is AI — an AI-driven Game Master for tabletop RPG adventures",
    )
    parser.add_argument(
        "adventure",
        nargs="?",
        help="Path to adventure directory (must contain corpus.json, hard-state.json, soft-state.json)",
    )
    parser.add_argument(
        "--load",
        dest="load_file",
        default=None,
        metavar="FILE",
        help="Load a saved game instead of starting fresh",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        metavar="DIR",
        help="Override the config directory (default: platform-appropriate user config dir)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--log",
        default=None,
        metavar="LEVEL",
        choices=["DEBUG", "INFO", "WARNING", "ERROR",
                 "debug", "info", "warning", "error"],
        help="Set log level (DEBUG, INFO, WARNING, ERROR; default: INFO)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="FILE",
        help="Write log output to FILE in addition to the console",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="mgmai 0.1.0",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (overrides MGMAI_API_KEY env var and saved credentials)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (overrides MGMAI_BASE_URL env var and saved config)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (overrides MGMAI_MODEL env var and saved config)",
    )
    args = parser.parse_args(argv)

    log_level = (args.log or ("DEBUG" if args.debug else "INFO")).upper()
    setup_logging(level=log_level, log_file=args.log_file)
    debug = log_level == "DEBUG"

    display = Display()

    if args.adventure is None:
        display.print(
            "[bold]Usage:[/bold] python -m mgmai.cli <adventure_path> [--load FILE]\n\n"
            "Example:\n"
            "  python -m mgmai.cli adventures/bag-of-holding\n"
            "  python -m mgmai.cli adventures/bag-of-holding --load save.json\n"
        )
        sys.exit(0)

    config_dir = get_config_dir(args.config_dir)
    app_config = load_app_config(config_dir)
    credentials = load_credentials(config_dir)

    # Resolve API key: CLI arg > env var > credentials file
    env_key = os.environ.get("MGMAI_API_KEY")
    api_key = resolve_api_key(
        cli_arg=args.api_key,
        env_var=env_key,
        credentials=credentials,
    )

    # Resolve model name preliminarily: CLI arg > env var > config file
    env_model = os.environ.get("MGMAI_MODEL")
    model_name = args.model or env_model or app_config.model_name

    # Resolve base URL preliminarily: CLI arg > env var > config file
    env_url = os.environ.get("MGMAI_BASE_URL")
    base_url = args.base_url or env_url or app_config.base_url

    if not api_key:
        api_key, model_name, base_url = _prompt_for_credentials(
            display, config_dir, credentials, app_config,
        )

    config = get_model_config(model_name)
    if base_url:
        config = replace(config, base_url=base_url)

    # Environment variables can still override individual temperatures for
    # quick experimentation, but the registry is the authoritative source.
    ruling_temp = os.environ.get("MGMAI_RULING_TEMPERATURE")
    prose_temp = os.environ.get("MGMAI_PROSE_TEMPERATURE")
    if ruling_temp is not None:
        config = replace(config, ruling_temperature=float(ruling_temp))
    elif app_config.ruling_temperature is not None:
        config = replace(config, ruling_temperature=app_config.ruling_temperature)
    if prose_temp is not None:
        config = replace(config, prose_temperature=float(prose_temp))
    elif app_config.prose_temperature is not None:
        config = replace(config, prose_temperature=app_config.prose_temperature)

    adventure_path = Path(args.adventure)

    state_manager = StateManager()
    state_manager._config_dir = config_dir

    try:
        if args.load_file:
            load_path = Path(args.load_file)
            if not load_path.is_file():
                display.render_error(f"Save file not found: {args.load_file}")
                sys.exit(1)
            adv_path = state_manager.load_save(load_path)
            display.print(
                f"[green]Resuming from {args.load_file} (adventure: {adv_path})[/green]"
            )
        else:
            state_manager.load_all(adventure_path)
    except FileNotFoundError as e:
        display.render_error(str(e))
        sys.exit(1)
    except Exception as e:
        display.render_error(f"Failed to load state: {e}")
        sys.exit(1)

    # Persist last-used adventure path
    app_config.adventure_path = str(adventure_path.resolve())
    save_app_config(app_config, config_dir)

    llm_client = LLMClient(
        api_key=api_key,
        config=config,
    )

    loop = GameLoop(
        state_manager,
        llm_client,
        debug=debug,
        display=display,
        config_dir=config_dir,
    )
    loop.start()


def _prompt_for_credentials(
    display: Display,
    config_dir: Path,
    credentials: Credentials,
    app_config: AppConfig,
) -> tuple[str, str, str]:
    """Prompt for LLM credentials when no API key is found.

    Returns ``(api_key, model_name, base_url)``.
    Falls back to a non-interactive error message when stdin is not a TTY
    (e.g. in tests or CI environments).
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
