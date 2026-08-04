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

"""Unit tests for tests/integration/artifact.py (no LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

from mgmai.game.headless import StatusSnapshot, TurnTranscript
from tests.integration.artifact import (
    JudgeRecord,
    Metadata,
    build_git_metadata,
    judge_digest,
    normalize_artifact,
    summarize_indicator,
    summarize_scenario,
    write_artifact,
)
from tests.integration.runner import ScenarioResult

GOLDENS = Path(__file__).parent / "integration" / "fixtures" / "golden_artifacts"

LEGACY = json.loads(
    (GOLDENS / "legacy_fight_20260720_102224.json").read_text()
)
V2_SCENARIO = json.loads(
    (GOLDENS / "golden_fight_20260804_100000_123456.json").read_text()
)
V2_INDICATOR = json.loads(
    (GOLDENS / "golden_check_20260804_100001_123456.json").read_text()
)


def _turn(hp: int, in_combat: bool, combat_log: list[dict],
          flags: dict[str, bool] | None = None, game_over: bool = False):
    return TurnTranscript(
        command="cmd",
        narration="narration",
        status=StatusSnapshot(
            turn_count=1,
            location="arena",
            in_combat=in_combat,
            combat_round=1 if in_combat else None,
            player_hp=hp,
            player_max_hp=24,
            active_flags=flags or {},
        ),
        game_over=game_over,
        game_over_type=None,
        combat_log=combat_log,
    )


# ------------------------------------------------------------------
# summarize_scenario
# ------------------------------------------------------------------


class TestSummarizeScenario:
    def test_legacy_artifact(self):
        s = summarize_scenario(LEGACY)
        assert s["turn_count"] == 2
        assert s["aborted"] is False
        assert s["player_hp"] == 20
        assert s["player_max_hp"] == 24
        assert s["combat"] == {"entered": True, "concluded": True, "rounds": 1}
        assert s["milestones"] == ["fight_started", "first_blood"]
        assert s["knowledge_topics"] == ["night_crossings"]
        assert s["npc_notes_archived"] == ["fen"]
        assert s["abilities_used"] == ["flame_strike"]
        assert s["items_used"] == ["health_potion"]
        assert s["enemy_outcomes"] == {"goblin_grunt": "dead"}
        assert s["hp_over_turns"] == [24, 20]
        assert s["judge"]["pass"] is True
        assert s["judge"]["overall_score"] == 4
        assert s["judge"]["criteria"]["mechanical_fidelity"] == 5

    def test_in_memory_result(self):
        result = ScenarioResult(scenario_name="mem")
        result.turns.append(_turn(24, True, [
            {"actor": "player", "action": "attack", "attack_id": None},
        ], flags={"a": True}))
        result.turns.append(_turn(10, False, [
            {"actor": "player", "action": "ability_save", "attack_id": "flame_strike"},
            {"actor": "goblin", "action": "death", "attack_id": None},
            {"actor": "player", "action": "use_item", "target": "antidote"},
        ], flags={"a": True, "b": True}))
        result.judge_record = JudgeRecord(
            verdict={"pass": True, "overall_score": 5, "criteria": {}},
            raw_output="raw",
            payload={"scenario": "mem"},
            judge_model="j",
        )
        s = summarize_scenario(result)
        assert s["turn_count"] == 2
        assert s["combat"]["concluded"] is True
        assert s["milestones"] == ["a", "b"]
        assert s["abilities_used"] == ["flame_strike"]
        assert s["items_used"] == ["antidote"]
        assert s["enemy_outcomes"] == {"goblin": "dead"}
        assert s["hp_over_turns"] == [24, 10]
        assert s["judge"]["pass"] is True

    def test_empty_run_tolerated(self):
        s = summarize_scenario(ScenarioResult(scenario_name="empty"))
        assert s["turn_count"] == 0
        assert s["combat"] == {"entered": False, "concluded": False, "rounds": None}
        assert s["judge"] is None

    def test_v2_envelope_uses_stored_summary(self):
        # normalize_artifact prefers the stored summary block.
        view = normalize_artifact(V2_SCENARIO)
        assert view["summary"]["judge"]["overall_score"] == 2
        assert view["metadata"]["gm_model"] == "gm-test-model"
        # ...but recomputation from data also works (drift check).
        s = summarize_scenario(V2_SCENARIO)
        assert s["turn_count"] == 1
        assert s["judge"]["pass"] is False


# ------------------------------------------------------------------
# summarize_indicator
# ------------------------------------------------------------------


class TestSummarizeIndicator:
    def test_v2_indicator(self):
        s = summarize_indicator(V2_INDICATOR)
        assert s["placed_count"] == 1
        assert s["total_indicators"] == 1
        assert s["markers_placed_inline"] == "1/1"
        assert s["engine_success"] is True
        assert s["leftover_markers"] == 0
        assert s["judge"]["pass"] is True

    def test_missing_fields_tolerated(self):
        s = summarize_indicator({"scenario_name": "x", "indicators": []})
        assert s["total_indicators"] == 0
        assert s["engine_success"] is None


# ------------------------------------------------------------------
# judge_digest / normalize
# ------------------------------------------------------------------


class TestJudgeDigest:
    def test_none(self):
        assert judge_digest(None) is None

    def test_legacy_bare_verdict(self):
        d = judge_digest({"pass": False, "overall_score": 1, "criteria": {}})
        assert d["pass"] is False
        assert d["error"] is None

    def test_error_record(self):
        d = judge_digest({"verdict": None, "raw_output": "garbage",
                          "payload": {}, "judge_model": "j",
                          "error": "JudgeError: nope"})
        assert d["pass"] is None
        assert d["error"] == "JudgeError: nope"


class TestNormalizeArtifact:
    def test_legacy(self):
        view = normalize_artifact(LEGACY)
        assert view["schema_version"] is None
        assert view["harness"] == "scenario"
        assert view["metadata"] == {}
        assert view["judge"]["overall_score"] == 4
        assert view["data"]["turns"]

    def test_v2(self):
        view = normalize_artifact(V2_INDICATOR)
        assert view["schema_version"] == 2
        assert view["harness"] == "indicator"
        assert view["metadata"]["seed"] == 7
        assert view["judge_block"]["judge_model"] == "judge-test-model"


# ------------------------------------------------------------------
# write_artifact + index
# ------------------------------------------------------------------


class TestWriteArtifact:
    def _payload(self, judge_pass):
        return {
            "schema_version": 2,
            "harness": "scenario",
            "scenario_name": "sc",
            "created_utc": "2026-08-04T10:00:00Z",
            "turn_count": 3,
            "summary": {"aborted": False},
            "judge": (
                {"verdict": {"pass": judge_pass, "overall_score": 4},
                 "raw_output": "", "payload": {}, "judge_model": "j",
                 "error": None}
                if judge_pass is not None else None
            ),
            "data": {},
            "error": None,
        }

    def test_write_and_index(self, tmp_path):
        path = write_artifact(tmp_path, "sc", "20260804_100000_000001",
                              self._payload(None))
        assert path.name == "sc_20260804_100000_000001.json"
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["sc"][0]["file"] == path.name
        assert index["sc"][0]["judge_pass"] is None

        # Post-judge rewrite updates the same index entry.
        write_artifact(tmp_path, "sc", "20260804_100000_000001",
                       self._payload(True))
        index = json.loads((tmp_path / "index.json").read_text())
        assert len(index["sc"]) == 1
        assert index["sc"][0]["judge_pass"] is True

    def test_index_newest_first(self, tmp_path):
        write_artifact(tmp_path, "sc", "20260804_100000_000001", self._payload(None))
        write_artifact(tmp_path, "sc", "20260804_100000_000002", self._payload(None))
        write_artifact(tmp_path, "other", "20260804_100000_000003", self._payload(None))
        index = json.loads((tmp_path / "index.json").read_text())
        assert [e["file"] for e in index["sc"]] == [
            "sc_20260804_100000_000002.json",
            "sc_20260804_100000_000001.json",
        ]
        assert "other" in index


# ------------------------------------------------------------------
# metadata
# ------------------------------------------------------------------


class TestMetadata:
    def test_round_trip(self):
        m = Metadata(gm_model="g", seed=7, git_dirty=True)
        assert Metadata.from_dict(m.to_dict()) == m

    def test_from_dict_ignores_unknown_keys(self):
        m = Metadata.from_dict({"gm_model": "g", "future_field": 1})
        assert m.gm_model == "g"

    def test_git_metadata_swallows_failure(self, tmp_path):
        # A non-repo directory must not raise.
        commit, dirty = build_git_metadata(cwd=tmp_path)
        assert commit is None
        assert dirty is None
