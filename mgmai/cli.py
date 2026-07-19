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
from mgmai.llm.model_config import (
    get_known_model_labels,
    get_model_config,
    get_provider,
    load_custom_models,
)
from mgmai.game.display import Display
from mgmai.game.loop import GameLoop


def _invocation_name() -> str:
    """Return the command name to show in usage messages.

    When the module is executed with ``python -m mgmai.cli``, report that
    form. Otherwise fall back to the basename of the executable/script.
    """
    if __spec__ is not None:
        return f"python -m {__spec__.name}"
    return os.path.basename(sys.argv[0])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mgmai",
        description="My GM is AI: a Game Master for tabletop-style RPG adventures")

    ## Adventure settings
    parser.add_argument(
        "adventure", nargs="?",
        help="Path to adventure directory (must contain corpus.json and soft-state.json; hard-state.json is optional)")

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
            f"[bold]Usage:[/bold] {_invocation_name()} [OPTIONS] <adventure_path>\n"
            "Try --help for more information\n"
        )
        sys.exit(0)

    config_dir = get_config_dir(args.config_dir)
    app_config = load_app_config(config_dir)
    credentials = load_credentials(config_dir)
    custom_models = load_custom_models(config_dir)

    # Resolve model name preliminarily: CLI arg > env var > config file
    env_model = os.environ.get("MGMAI_MODEL")
    model_name = args.model or env_model or app_config.model_name

    # Resolve base URL preliminarily: CLI arg > env var > config file.
    # Must happen before API key resolution so we can determine the
    # provider for per-provider keys in credentials.json.
    env_url = os.environ.get("MGMAI_BASE_URL")
    base_url = args.base_url or env_url or app_config.base_url

    # Resolve API key: CLI arg > env var > credentials file (per-provider
    # if we can determine the model, otherwise generic fallback).
    env_key = os.environ.get("MGMAI_API_KEY")
    provider = get_provider(model_name, base_url=base_url,
                            custom_models=custom_models)
    api_key = resolve_api_key(cli_arg=args.api_key,
                              env_var=env_key,
                              credentials=credentials,
                              provider=provider)

    api_key, model_name, base_url = _prompt_for_llm_config(
        display, config_dir, credentials, app_config,
        api_key, model_name, base_url, provider, custom_models)

    config = get_model_config(model_name, base_url=base_url,
                              custom_models=custom_models)

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


def _prompt_for_llm_config(
    display: Display,
    config_dir: Path,
    credentials: Credentials,
    app_config: AppConfig,
    api_key: str,
    model_name: str,
    base_url: str | None,
    provider: str | None,
    custom_models: dict[str, object] | None = None,
) -> tuple[str, str, str]:
    """Prompt for any missing LLM configuration.

    Returns ``(api_key, model_name, base_url)`` with defaults applied.
    Print a non-interactive error message if stdin is not a TTY.
    """
    # Resolve what we have. A known model supplies its own base URL.
    model_cfg = None
    resolved_base_url = base_url
    if model_name:
        try:
            model_cfg = get_model_config(model_name, base_url=base_url,
                                         custom_models=custom_models)
            resolved_base_url = model_cfg.base_url
        except ValueError:
            pass

    missing_api_key = not api_key
    missing_model = not model_name
    missing_base_url = model_cfg is None and not resolved_base_url

    if not (missing_api_key or missing_model or missing_base_url):
        return api_key, model_name, resolved_base_url or ""

    if not sys.stdin.isatty():
        missing: list[str] = []
        if missing_api_key:
            missing.append("MGMAI_API_KEY or --api-key")
        if missing_model:
            missing.append("MGMAI_MODEL or --model")
        if missing_base_url:
            missing.append("MGMAI_BASE_URL or --base-url")
        display.render_error(
            "Missing LLM configuration: " + ", ".join(missing) + ". "
            "Set the corresponding env vars, pass the CLI options, "
            "or run interactively to be prompted."
        )
        sys.exit(1)

    display.print("\n[yellow]Some LLM configuration is missing.[/yellow]")
    display.print("Please select a model or enter a custom configuration.\n")

    labels = get_known_model_labels(custom_models=custom_models)
    names = list(labels.keys())
    for i, (name, label) in enumerate(labels.items(), 1):
        marker = " [dim](current)[/dim]" if name == model_name else ""
        display.print(f"  {i}. {label}{marker}")
    custom_idx = len(labels) + 1
    display.print(f"  {custom_idx}. Custom model...")

    while True:
        choice = input("\nSelect model number: ").strip()
        if not choice:
            display.print("[red]Please enter a number.[/red]")
            continue
        try:
            idx = int(choice)
        except ValueError:
            display.print("[red]Please enter a number.[/red]")
            continue
        if 1 <= idx <= len(labels):
            model_cfg = get_model_config(names[idx - 1],
                                         custom_models=custom_models)
            model_name = model_cfg.name
            base_url = model_cfg.base_url
            break
        if idx == custom_idx:
            default = model_name or app_config.model_name or ""
            prompt = f"Model name [{default}]: " if default else "Model name: "
            while True:
                value = input(prompt).strip()
                if value:
                    model_name = value
                    break
                if model_name:
                    break
                display.print("[red]Model name cannot be empty.[/red]")

            default = base_url or app_config.base_url or ""
            prompt = f"Base URL [{default}]: " if default else "Base URL: "
            while True:
                value = input(prompt).strip()
                if value:
                    base_url = value
                    break
                if base_url:
                    break
                display.print("[red]Base URL cannot be empty for a custom model.[/red]")
            break
        display.print("[red]Invalid selection.[/red]")

    # Prompt for API key if missing; allow Enter to keep an existing key.
    if missing_api_key or not api_key:
        while True:
            hint = "keep current" if api_key else "required"
            new_key = getpass.getpass(f"API key [{hint}]: ").strip()
            if new_key:
                api_key = new_key
                break
            if api_key:
                break
            display.print("[red]API key cannot be empty.[/red]")

    if api_key:
        provider = get_provider(model_name, base_url=base_url,
                                custom_models=custom_models)
        if provider:
            credentials.api_keys[provider] = api_key
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
