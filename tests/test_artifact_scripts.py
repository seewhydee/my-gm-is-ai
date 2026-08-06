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

"""Unit tests for the prewritten artifact scripts (no LLM calls).

Runs ``inspect_artifact.py``, ``list_runs.py``, and ``compare_runs.py``
as subprocesses against the committed golden artifacts (one legacy
flat artifact, two schema-2 envelopes) and asserts on key output
lines and exit codes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "tests" / "integration"
GOLDENS = SCRIPTS / "fixtures" / "golden_artifacts"

LEGACY = GOLDENS / "legacy_fight_20260720_102224.json"
V2_SCENARIO = GOLDENS / "golden_fight_20260804_100000_123456.json"
V2_INDICATOR = GOLDENS / "golden_check_20260804_100001_123456.json"


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, timeout=30,
        check=False,
    )


class TestInspectArtifact:
    def test_legacy_text(self):
        proc = _run("inspect_artifact.py", LEGACY)
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "Scenario: legacy_fight" in out
        assert "Schema: legacy" in out
        assert 'abilities_used: ["flame_strike"]' in out
        assert 'items_used: ["health_potion"]' in out
        assert 'enemy_outcomes: {"goblin_grunt": "dead"}' in out
        assert "Judge: pass=true overall=4" in out
        assert "You ⇒ I attack the goblin grunt" in out

    def test_v2_indicator_text(self):
        proc = _run("inspect_artifact.py", V2_INDICATOR)
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "Models: gm=gm-test-model" in out
        assert "markers_placed_inline: 1/1" in out
        assert "leftover_markers: 0" in out
        assert "Judge: pass=true overall=5" in out

    def test_json_mode(self):
        proc = _run("inspect_artifact.py", V2_SCENARIO, "--json")
        assert proc.returncode == 0, proc.stderr
        view = json.loads(proc.stdout)
        assert view["metadata"]["gm_model"] == "gm-test-model"
        assert view["judge"]["pass"] is False
        assert view["turns_preview"][0]["command"] == "I attack the bugbear."

    def test_missing_file(self):
        proc = _run("inspect_artifact.py", GOLDENS / "nope.json")
        assert proc.returncode == 2
        assert "no such file" in proc.stderr


class TestListRuns:
    def test_groups_by_scenario(self):
        proc = _run("list_runs.py", GOLDENS)
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "golden_check" in out
        assert "golden_fight" in out
        assert "legacy_fight" in out
        assert "judge=pass(5)" in out  # golden_check
        assert "judge=FAIL(2)" in out  # golden_fight
        assert "judge=pass(4)" in out  # legacy_fight (no index needed)

    def test_latest_and_scenario_filter(self):
        proc = _run("list_runs.py", GOLDENS, "--scenario", "golden_check",
                    "--latest")
        assert proc.returncode == 0, proc.stderr
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert len(lines) == 1
        assert "golden_check" in lines[0]

    def test_unknown_scenario(self):
        proc = _run("list_runs.py", GOLDENS, "--scenario", "nope")
        assert proc.returncode == 1
        assert "no runs found" in proc.stdout

    def test_missing_dir(self):
        proc = _run("list_runs.py", GOLDENS / "nope")
        assert proc.returncode == 2

    def test_uses_index_when_present(self, tmp_path):
        # Copy two goldens and write a fake index marking one as judged.
        import shutil

        shutil.copy(V2_SCENARIO, tmp_path)
        shutil.copy(V2_INDICATOR, tmp_path)
        index = {
            "golden_fight": [{
                "file": V2_SCENARIO.name,
                "created_utc": "2026-08-04T10:00:00Z",
                "harness": "scenario",
                "turn_count": 99,
                "judge_pass": True,
                "overall_score": 5,
                "aborted": False,
                "error": None,
            }]
        }
        (tmp_path / "index.json").write_text(json.dumps(index))
        proc = _run("list_runs.py", tmp_path)
        assert proc.returncode == 0, proc.stderr
        # Index wins over the on-disk content (turn_count=99, pass(5)).
        assert "turns=99" in proc.stdout
        assert "judge=pass(5)" in proc.stdout
        # Scenarios absent from the index are not scanned when an
        # index exists.
        assert "golden_check" not in proc.stdout


class TestCompareRuns:
    def test_text_diff(self):
        proc = _run("compare_runs.py", LEGACY, V2_SCENARIO)
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "warning: different scenarios" in out
        assert "gm-test-model" in out
        assert "overall_score" in out
        assert "hp_over_turns" in out
        assert 'A: ["flame_strike"]' in out

    def test_identical_files(self):
        proc = _run("compare_runs.py", V2_SCENARIO, V2_SCENARIO)
        assert proc.returncode == 0, proc.stderr
        assert "pass: same" in proc.stdout

    def test_json_mode(self):
        proc = _run("compare_runs.py", LEGACY, V2_SCENARIO, "--json")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["judge_overall"] == [4, 2]
        assert report["hp_over_turns"][0] == [24, 20]

    def test_missing_file(self):
        proc = _run("compare_runs.py", LEGACY, GOLDENS / "nope.json")
        assert proc.returncode == 2
