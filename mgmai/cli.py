#!/usr/bin/env python3
"""MGMAI: My GM is AI — an AI-driven Game Master for tabletop RPG adventures.

Usage:
    python -m mgmai.cli <adventure_path>          Start a new game
    python -m mgmai.cli <adventure_path> --load save.json  Resume a saved game
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mgmai.state.manager import StateManager
from mgmai.llm.client import LLMClient
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
        help="API key (overrides MGMAI_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (overrides MGMAI_BASE_URL env var)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (overrides MGMAI_MODEL env var)",
    )
    args = parser.parse_args(argv)

    display = Display()

    if args.adventure is None:
        display.print(
            "[bold]Usage:[/bold] python -m mgmai.cli <adventure_path> [--load FILE]\n\n"
            "Example:\n"
            "  python -m mgmai.cli adventures/bag-of-holding\n"
            "  python -m mgmai.cli adventures/bag-of-holding --load save.json"
        )
        sys.exit(0)

    adventure_path = Path(args.adventure)

    api_key = args.api_key or os.environ.get("MGMAI_API_KEY")
    if not api_key:
        display.render_error(
            "MGMAI_API_KEY environment variable is not set. "
            "Set it or pass --api-key."
        )
        sys.exit(1)

    base_url = args.base_url or os.environ.get(
        "MGMAI_BASE_URL", "https://api.deepseek.com"
    )
    model = args.model or os.environ.get("MGMAI_MODEL", "deepseek-v4-flash")
    ruling_temp = float(
        os.environ.get("MGMAI_RULING_TEMPERATURE", "0.9")
    )
    prose_temp = float(
        os.environ.get("MGMAI_PROSE_TEMPERATURE", "1.1")
    )

    state_manager = StateManager()

    try:
        if args.load_file:
            if not Path(args.load_file).is_file():
                display.render_error(f"Save file not found: {args.load_file}")
                sys.exit(1)
            adv_path = state_manager.load_save(args.load_file)
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

    llm_client = LLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        ruling_temperature=ruling_temp,
        prose_temperature=prose_temp,
    )

    loop = GameLoop(
        state_manager,
        llm_client,
        debug=args.debug,
        display=display,
    )
    loop.start()


if __name__ == "__main__":
    main()
