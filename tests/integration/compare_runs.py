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

"""Compare two runs of a scenario side by side.

Usage:
    python tests/integration/compare_runs.py <fileA> <fileB> [--json]

Diffs metadata (models, commit), judge scores per criterion, HP
trajectory, milestones, abilities/items used, enemy outcomes, and
turn-by-turn commands.  Stdlib-only; tolerates legacy artifacts and
missing fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.integration.artifact import normalize_artifact


def _diff_lines(label: str, a, b) -> list[str]:
    if a == b:
        return [f"{label}: same ({_short(a)})"]
    return [
        f"{label}:",
        f"  A: {_short(a)}",
        f"  B: {_short(b)}",
    ]


def _short(value, limit: int = 120) -> str:
    text = json.dumps(value, default=str) if isinstance(value, (list, dict)) else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def compare(path_a: Path, path_b: Path) -> dict:
    """Structured comparison of two artifact files."""
    view_a = normalize_artifact(json.loads(path_a.read_text(encoding="utf-8")))
    view_b = normalize_artifact(json.loads(path_b.read_text(encoding="utf-8")))

    def commands(view):
        return [
            t.get("command")
            for t in (view["data"].get("turns") or [])
        ]

    def criteria(view):
        return (view["judge"] or {}).get("criteria") or {}

    all_criteria = sorted(set(criteria(view_a)) | set(criteria(view_b)))

    return {
        "file_a": path_a.name,
        "file_b": path_b.name,
        "scenario_a": view_a["scenario_name"],
        "scenario_b": view_b["scenario_name"],
        "metadata_a": view_a["metadata"],
        "metadata_b": view_b["metadata"],
        "judge_overall": [
            (view_a["judge"] or {}).get("overall_score"),
            (view_b["judge"] or {}).get("overall_score"),
        ],
        "judge_pass": [
            (view_a["judge"] or {}).get("pass"),
            (view_b["judge"] or {}).get("pass"),
        ],
        "judge_criteria": {
            name: [criteria(view_a).get(name), criteria(view_b).get(name)]
            for name in all_criteria
        },
        "hp_over_turns": [
            view_a["summary"].get("hp_over_turns"),
            view_b["summary"].get("hp_over_turns"),
        ],
        "milestones": [
            view_a["summary"].get("milestones"),
            view_b["summary"].get("milestones"),
        ],
        "abilities_used": [
            view_a["summary"].get("abilities_used"),
            view_b["summary"].get("abilities_used"),
        ],
        "items_used": [
            view_a["summary"].get("items_used"),
            view_b["summary"].get("items_used"),
        ],
        "enemy_outcomes": [
            view_a["summary"].get("enemy_outcomes"),
            view_b["summary"].get("enemy_outcomes"),
        ],
        "commands": [commands(view_a), commands(view_b)],
    }


def render_text(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"A: {report['file_a']}  (scenario={report['scenario_a']})")
    lines.append(f"B: {report['file_b']}  (scenario={report['scenario_b']})")
    if report["scenario_a"] != report["scenario_b"]:
        lines.append("warning: different scenarios — comparison may be meaningless")
    lines.append("")

    lines.append("Metadata:")
    keys = sorted(set(report["metadata_a"]) | set(report["metadata_b"]))
    for key in keys:
        lines.extend(
            "  " + line for line in _diff_lines(
                key, report["metadata_a"].get(key), report["metadata_b"].get(key)
            )
        )
    if not keys:
        lines.append("  (no metadata in either artifact)")

    lines.append("")
    lines.append("Judge:")
    lines.extend("  " + line for line in _diff_lines(
        "pass", *report["judge_pass"]))
    lines.extend("  " + line for line in _diff_lines(
        "overall_score", *report["judge_overall"]))
    for name, (a, b) in report["judge_criteria"].items():
        lines.extend("  " + line for line in _diff_lines(name, a, b))

    lines.append("")
    lines.append("Run:")
    for key in ("hp_over_turns", "milestones", "abilities_used",
                "items_used", "enemy_outcomes"):
        lines.extend("  " + line for line in _diff_lines(key, *report[key]))

    lines.append("")
    lines.append("Commands:")
    cmds_a, cmds_b = report["commands"]
    for i in range(max(len(cmds_a), len(cmds_b))):
        ca = cmds_a[i] if i < len(cmds_a) else None
        cb = cmds_b[i] if i < len(cmds_b) else None
        marker = " " if ca == cb else "*"
        lines.append(f" {marker} [{i + 1}] A: {ca}")
        if ca != cb:
            lines.append(f"    [{i + 1}] B: {cb}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_a", type=Path)
    parser.add_argument("file_b", type=Path)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    for path in (args.file_a, args.file_b):
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2

    report = compare(args.file_a, args.file_b)
    if args.json:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
