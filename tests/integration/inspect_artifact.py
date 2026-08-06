# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stainlesschicken.com>
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

"""Print a digest of a single integration-test artifact.

Usage:
    python tests/integration/inspect_artifact.py <artifact.json> [--json] [--turns N]

Stdlib-only; works on both schema-2 envelopes and legacy flat
artifacts (missing fields are tolerated).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.integration.artifact import normalize_artifact


def _fmt_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _print_kv(lines: list[str], key: str, value) -> None:
    lines.append(f"{key}: {_fmt_value(value)}")


def build_digest(path: Path, turn_limit: int) -> dict:
    """Normalized, JSON-serialisable digest of one artifact file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    view = normalize_artifact(data)
    view["file"] = path.name
    view["log_file"] = path.with_suffix(".log").name
    view["log_exists"] = path.with_suffix(".log").is_file()
    if view["harness"] == "scenario":
        turns = view["data"].get("turns") or []
        view["turns_preview"] = [
            {
                "turn": i,
                "command": t.get("command"),
                "narration": t.get("narration"),
            }
            for i, t in enumerate(turns[:turn_limit], 1)
        ]
    return view


def render_text(view: dict) -> str:
    lines: list[str] = []
    lines.append(f"Artifact: {view['file']}")
    _print_kv(lines, "Scenario", view["scenario_name"])
    _print_kv(lines, "Harness", view["harness"])
    _print_kv(lines, "Schema", view["schema_version"] or "legacy")
    _print_kv(lines, "Created", view["created_utc"])

    meta = view["metadata"]
    if meta:
        models = ", ".join(
            f"{role}={meta.get(role + '_model') or '—'}"
            for role in ("gm", "driver", "judge")
        )
        _print_kv(lines, "Models", models)
        git = meta.get("git_commit") or "—"
        if meta.get("git_dirty") is True:
            git += " (dirty)"
        elif meta.get("git_dirty") is False:
            git += " (clean)"
        _print_kv(lines, "Git", git)
        if meta.get("max_turns") is not None:
            _print_kv(lines, "Max turns", meta["max_turns"])
        if meta.get("seed") is not None:
            _print_kv(lines, "Seed", meta["seed"])

    s = view["summary"]
    lines.append("")
    lines.append("Summary:")
    for key, value in s.items():
        if key == "judge":
            continue
        _print_kv(lines, f"  {key}", value)

    judge = view["judge"]
    lines.append("")
    if judge:
        lines.append(
            f"Judge: pass={_fmt_value(judge['pass'])} "
            f"overall={_fmt_value(judge['overall_score'])}"
        )
        for name, score in (judge.get("criteria") or {}).items():
            lines.append(f"  {name}: {_fmt_value(score)}")
        if judge.get("error"):
            _print_kv(lines, "  judge error", judge["error"])
    else:
        lines.append("Judge: no verdict recorded")

    if view["error"]:
        _print_kv(lines, "ERROR", view["error"])
        if view.get("error_traceback"):
            lines.append("")
            lines.append("Traceback:")
            lines.extend(f"  {ln}" for ln in view["error_traceback"].splitlines())

    preview = view.get("turns_preview")
    if preview:
        lines.append("")
        lines.append(f"Turns (first {len(preview)}):")
        for t in preview:
            lines.append(f"  [{t['turn']}] You ⇒ {t['command']}")
            narration = (t.get("narration") or "").replace("\n", " ")
            if len(narration) > 300:
                narration = narration[:300] + "..."
            lines.append(f"      GM ⇒ {narration}")

    lines.append("")
    log_note = view["log_file"] if view["log_exists"] else f"{view['log_file']} (missing)"
    _print_kv(lines, "Debug log", log_note)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="artifact JSON file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--turns", type=int, default=5, help="turns to preview (default 5)")
    args = parser.parse_args(argv)

    if not args.artifact.is_file():
        print(f"error: no such file: {args.artifact}", file=sys.stderr)
        return 2

    view = build_digest(args.artifact, args.turns)
    if args.json:
        json.dump(view, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(render_text(view))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
