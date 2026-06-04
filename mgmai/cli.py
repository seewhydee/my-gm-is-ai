#!/usr/bin/env python3
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
        help="Enable debug mode (shows GMBriefing/EngineResult per turn)",
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

    if not api_key:
        api_key = _prompt_for_api_key(display, config_dir, credentials)

    # Resolve model name: CLI arg > env var > config file > default
    env_model = os.environ.get("MGMAI_MODEL")
    model_name = args.model or env_model or app_config.model_name or "deepseek-v4-flash"
    config = get_model_config(model_name)

    # Resolve base URL: CLI arg > env var > config file > registry default
    env_url = os.environ.get("MGMAI_BASE_URL")
    base_url = args.base_url or env_url or app_config.base_url
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
        debug=args.debug,
        display=display,
        config_dir=config_dir,
    )
    loop.start()


def _prompt_for_api_key(
    display: Display,
    config_dir: Path,
    credentials: Credentials,
) -> str:
    """Prompt the user for an API key and save it to credentials.json.

    Falls back to a non-interactive error message when stdin is not a TTY
    (e.g. in tests or CI environments).
    """
    if not sys.stdin.isatty():
        display.render_error(
            "MGMAI_API_KEY environment variable is not set and no "
            "credentials were found. Set MGMAI_API_KEY, pass --api-key, "
            "or run interactively to be prompted."
        )
        sys.exit(1)

    display.print("\n[yellow]No API key found from environment or saved credentials.[/yellow]")
    display.print(
        "You can set the [bold]MGMAI_API_KEY[/bold] environment variable to skip this prompt.\n"
        "You can also run [bold]/models[/bold] in-game to manage model and API key settings.\n"
    )

    while True:
        api_key = getpass.getpass("Enter your API key: ").strip()
        if api_key:
            break
        display.print("[red]API key cannot be empty.[/red]")

    credentials.api_key = api_key
    try:
        save_credentials(credentials, config_dir)
        display.print("[green]API key saved.[/green]\n")
    except OSError as e:
        display.print(f"[yellow]Could not save API key: {e}[/yellow]\n")

    return api_key


if __name__ == "__main__":
    main()
