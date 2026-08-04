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

"""List integration-test runs grouped by scenario, newest first.

Usage:
    python tests/integration/list_runs.py <artifacts_dir> [--scenario NAME] [--latest] [--json]

Uses ``index.json`` when present, otherwise scans artifact filenames
(legacy runs without an index entry).  Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.integration.artifact import INDEX_FILENAME, judge_digest  # noqa: E402

_TS_RE = re.compile(r"_\d{8}_\d{6}(_\d+)?\.json$")


def _scenario_from_filename(name: str) -> str:
    return _TS_RE.sub("", name)


def _scan_entries(artifacts_dir: Path) -> dict[str, list[dict]]:
    """Group artifacts by scenario from filenames, newest first."""
    groups: dict[str, list[dict]] = {}
    for path in sorted(artifacts_dir.glob("*.json"), reverse=True):
        if path.name == INDEX_FILENAME:
            continue
        scenario = _scenario_from_filename(path.name)
        entry = {"file": path.name, "created_utc": None}
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entry["error"] = "unreadable artifact"
            groups.setdefault(scenario, []).append(entry)
            continue
        if "schema_version" in d:
            judge = judge_digest(d.get("judge")) or {}
            summary = d.get("summary") or {}
            entry.update({
                "created_utc": d.get("created_utc"),
                "harness": d.get("harness"),
                "turn_count": d.get("turn_count"),
                "judge_pass": judge.get("pass"),
                "overall_score": judge.get("overall_score"),
                "aborted": summary.get("aborted", False),
                "error": d.get("error"),
            })
        else:
            judge = judge_digest(d.get("judge_verdict")) or {}
            turns = d.get("turns")
            entry.update({
                "harness": "scenario" if turns is not None else "indicator",
                "turn_count": len(turns) if turns is not None else 1,
                "judge_pass": judge.get("pass"),
                "overall_score": judge.get("overall_score"),
                "aborted": d.get("aborted", False),
                "error": d.get("error"),
            })
        groups.setdefault(scenario, []).append(entry)
    return groups


def load_runs(artifacts_dir: Path) -> dict[str, list[dict]]:
    """``{scenario: [run entries, newest first]}``."""
    index_path = artifacts_dir / INDEX_FILENAME
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(index, dict) and index:
                return {k: v for k, v in index.items() if isinstance(v, list)}
        except (OSError, json.JSONDecodeError):
            pass  # fall through to filename scan
    return _scan_entries(artifacts_dir)


def _fmt_entry(scenario: str, e: dict) -> str:
    date = e.get("created_utc")
    if not date:
        m = re.search(r"(\d{8})_(\d{6})", e.get("file", ""))
        date = f"{m.group(1)}_{m.group(2)}" if m else "?"
    judge = e.get("judge_pass")
    judge_s = "n/a" if judge is None else ("pass" if judge else "FAIL")
    score = e.get("overall_score")
    return (
        f"{date}  {scenario:<32} turns={e.get('turn_count', '?'):<3} "
        f"judge={judge_s}({score if score is not None else '—'})  "
        f"aborted={str(e.get('aborted', False)).lower()}  "
        f"error={'yes' if e.get('error') else 'no'}  {e.get('file')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts_dir", type=Path)
    parser.add_argument("--scenario", help="only this scenario")
    parser.add_argument("--latest", action="store_true",
                        help="only the newest run per scenario")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if not args.artifacts_dir.is_dir():
        print(f"error: no such directory: {args.artifacts_dir}", file=sys.stderr)
        return 2

    runs = load_runs(args.artifacts_dir)
    if args.scenario:
        runs = {args.scenario: runs.get(args.scenario, [])}
    if args.latest:
        runs = {k: v[:1] for k, v in runs.items()}

    if args.json:
        json.dump(runs, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        if not any(runs.values()):
            print("no runs found")
            return 1
        for scenario in sorted(runs):
            for entry in runs[scenario]:
                print(_fmt_entry(scenario, entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
