#!/usr/bin/env python3
"""MGMAI: My GM is AI — an AI-driven Game Master for tabletop RPG adventures.

Usage:
    python -m mgmai.cli <adventure_path>          Start a new game
    python -m mgmai.cli <adventure_path> --load save.json  Resume a saved game
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mgmai.game.display import Display
from mgmai.game.loop import GameLoop
from mgmai.game.state_loader import StateLoader


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

    state_loader = StateLoader(adventure_path)

    try:
        if args.load_file:
            if not Path(args.load_file).is_file():
                display.render_error(f"Save file not found: {args.load_file}")
                sys.exit(1)
            adv_path = state_loader.load_save(args.load_file)
            display.print(
                f"[green]Resuming from {args.load_file} (adventure: {adv_path})[/green]"
            )
        else:
            state_loader.load()
    except FileNotFoundError as e:
        display.render_error(str(e))
        sys.exit(1)
    except Exception as e:
        display.render_error(f"Failed to load state: {e}")
        sys.exit(1)

    loop = GameLoop(state_loader, debug=args.debug)
    loop.start()


if __name__ == "__main__":
    main()
