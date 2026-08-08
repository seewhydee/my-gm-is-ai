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

"""Shared artifact schema for the integration harnesses.

Holds the data types and builders used by both harnesses
(``runner.py`` and ``indicator_runner.py``), the tests, and the
prewritten query scripts (``inspect_artifact.py`` etc.).

**Stdlib-only at import time.**  The scripts must run under any
Python without pulling in project internals (``openai``, pydantic,
...), so this module never imports ``mgmai.*`` or the harness
modules.  In-memory results are read by duck-typing (attribute-or-dict
accessors), never by ``isinstance`` against harness classes.

Artifact envelope (``schema_version`` 2)::

    {
      "schema_version": 2,
      "harness": "scenario" | "indicator",
      "scenario_name": "...",
      "directive": "...",
      "created_utc": "...",
      "turn_count": 7,
      "metadata": {...},
      "summary": {...},
      "judge": {...} | null,
      "data": { /* harness-specific payload */ },
      "error": null
    }

Artifacts written before schema version 2 have a flat shape (no
``schema_version`` key; harness inferred from ``turns`` vs
``indicators``).  All readers here tolerate both shapes and missing
keys.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

INDEX_FILENAME = "index.json"


# ------------------------------------------------------------------
# Metadata
# ------------------------------------------------------------------


@dataclass
class Metadata:
    """Which models / settings / code version produced a run."""

    gm_model: str | None = None
    driver_model: str | None = None
    judge_model: str | None = None
    max_turns: int | None = None
    seed: int | None = None
    git_commit: str | None = None
    git_dirty: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Metadata:
        d = d or {}
        known = {k: d.get(k) for k in (
            "gm_model", "driver_model", "judge_model",
            "max_turns", "seed", "git_commit", "git_dirty",
        )}
        return cls(**known)


def build_git_metadata(cwd: Path | None = None) -> tuple[str | None, bool | None]:
    """Best-effort ``(short_commit, dirty)`` for the working tree.

    Swallows every failure (non-repo, no git binary, timeout) and
    returns ``(None, None)`` instead.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
            check=False,
        )
        if commit.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
            check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return commit.stdout.strip(), dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


# ------------------------------------------------------------------
# Judge record
# ------------------------------------------------------------------


@dataclass
class JudgeRecord:
    """Full evidence from an advisory judge call.

    ``verdict`` is the parsed verdict dict (``None`` on parse
    failure); ``payload`` is exactly what the judge was shown;
    ``raw_output`` is the verbatim model response; ``error`` is set
    (``"JudgeError: ..."``) when the output could not be parsed.
    """

    verdict: dict[str, Any] | None
    raw_output: str | None
    payload: dict[str, Any]
    judge_model: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> JudgeRecord | None:
        if d is None:
            return None
        return cls(
            verdict=d.get("verdict"),
            raw_output=d.get("raw_output"),
            payload=d.get("payload") or {},
            judge_model=d.get("judge_model"),
            error=d.get("error"),
        )


def judge_digest(judge_block: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact digest of a judge block (or a bare legacy verdict).

    Accepts the schema-2 ``judge`` block, a legacy top-level
    ``judge_verdict`` dict, or ``None``.  Returns ``None`` when there
    is no judge data at all.
    """
    if not judge_block:
        return None
    if "verdict" in judge_block or "raw_output" in judge_block:
        verdict = judge_block.get("verdict")
        error = judge_block.get("error")
    else:  # legacy bare verdict
        verdict = judge_block
        error = None
    if not isinstance(verdict, dict):
        return {"pass": None, "overall_score": None, "criteria": {}, "error": error}
    criteria = {
        name: (info.get("score") if isinstance(info, dict) else info)
        for name, info in (verdict.get("criteria") or {}).items()
    }
    return {
        "pass": verdict.get("pass"),
        "overall_score": verdict.get("overall_score"),
        "criteria": criteria,
        "error": error,
    }


# ------------------------------------------------------------------
# Naming and writing
# ------------------------------------------------------------------


def new_timestamp() -> str:
    """Microsecond-resolution timestamp for collision-free filenames."""
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S_%f")


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def artifact_filename(scenario_name: str, ts: str) -> str:
    return f"{scenario_name}_{ts}.json"


def write_artifact(
    artifacts_dir: Path,
    scenario_name: str,
    ts: str,
    payload: dict[str, Any],
) -> Path:
    """Write the artifact JSON and update ``index.json``.

    Single write path used for both the initial write and the
    post-judge rewrite, so the index always reflects the final state.
    Raises ``OSError`` on write failure (callers log and continue).
    """
    path = artifacts_dir / artifact_filename(scenario_name, ts)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _update_index(artifacts_dir, scenario_name, path.name, payload)
    return path


def _update_index(
    artifacts_dir: Path,
    scenario_name: str,
    filename: str,
    payload: dict[str, Any],
) -> None:
    """Insert/refresh this run's entry in ``index.json`` (newest first)."""
    index_path = artifacts_dir / INDEX_FILENAME
    index: dict[str, Any] = {}
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Ignoring unreadable %s", index_path)
            index = {}

    judge = judge_digest(payload.get("judge")) or {}
    summary = payload.get("summary") or {}
    data = payload.get("data") or {}
    entry = {
        "file": filename,
        "created_utc": payload.get("created_utc"),
        "harness": payload.get("harness"),
        "turn_count": payload.get("turn_count"),
        "judge_pass": judge.get("pass"),
        "overall_score": judge.get("overall_score"),
        "aborted": summary.get("aborted", data.get("aborted", False)),
        "error": payload.get("error"),
        "warnings": summary.get("warnings") or [],
    }
    entries = [
        e for e in index.get(scenario_name, [])
        if isinstance(e, dict) and e.get("file") != filename
    ]
    entries.insert(0, entry)
    index[scenario_name] = entries
    try:
        index_path.write_text(
            json.dumps(index, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Failed to update %s: %s", index_path, exc)


# ------------------------------------------------------------------
# Duck-typed readers (in-memory result OR parsed artifact dict)
# ------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {}


def split_artifact(d: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Split a parsed artifact into ``(harness, data, judge_block)``.

    Handles both the schema-2 envelope and the legacy flat shape.
    """
    if "schema_version" in d:
        return (
            d.get("harness") or "scenario",
            d.get("data") or {},
            d.get("judge"),
        )
    harness = "scenario" if "turns" in d else "indicator"
    return harness, d, d.get("judge_verdict")


def normalize_artifact(d: dict[str, Any]) -> dict[str, Any]:
    """Unified read view over a parsed artifact (schema-2 or legacy).

    Returns a dict with stable keys — ``harness``, ``scenario_name``,
    ``directive``, ``created_utc``, ``turn_count``, ``metadata``,
    ``summary``, ``judge`` (digest), ``judge_block`` (full schema-2
    judge block, ``None`` for legacy), ``data``, ``error`` — so
    scripts never branch on artifact shape themselves.
    """
    if "schema_version" in d:
        harness = d.get("harness") or "scenario"
        summary = d.get("summary")
        if not summary:
            summary = (
                summarize_scenario(d) if harness == "scenario"
                else summarize_indicator(d)
            )
        return {
            "schema_version": d.get("schema_version"),
            "harness": harness,
            "scenario_name": d.get("scenario_name"),
            "directive": d.get("directive"),
            "created_utc": d.get("created_utc"),
            "turn_count": d.get("turn_count"),
            "metadata": d.get("metadata") or {},
            "summary": summary,
            "judge": judge_digest(d.get("judge")),
            "judge_block": d.get("judge"),
            "data": d.get("data") or {},
            "error": d.get("error"),
            "error_traceback": d.get("error_traceback"),
        }
    harness, data, judge_block = split_artifact(d)
    summary = (
        summarize_scenario(d) if harness == "scenario"
        else summarize_indicator(d)
    )
    return {
        "schema_version": None,
        "harness": harness,
        "scenario_name": d.get("scenario_name"),
        "directive": d.get("directive"),
        "created_utc": None,
        "turn_count": summary.get("turn_count"),
        "metadata": {},
        "summary": summary,
        "judge": judge_digest(judge_block),
        "judge_block": None,
        "data": data,
        "error": d.get("error"),
        "error_traceback": d.get("error_traceback"),
    }


def summarize_scenario(result_or_dict: Any) -> dict[str, Any]:
    """Compute the scenario summary block from a run or artifact.

    Accepts an in-memory ``ScenarioResult`` (duck-typed) or a parsed
    artifact dict (schema-2 envelope or legacy flat shape).
    """
    if isinstance(result_or_dict, dict):
        _, data, judge_block = split_artifact(result_or_dict)
        error = result_or_dict.get("error")
    else:
        data = result_or_dict
        judge_block = _get(data, "judge_record")
        judge_block = judge_block.to_dict() if judge_block else None
        err = _get(data, "error")
        error = f"{type(err).__name__}: {err}" if err is not None else None

    turns = [_to_dict(t) for t in (_get(data, "turns") or [])]
    statuses = [_to_dict(t.get("status")) for t in turns]
    final_status = _get(data, "final_status") or {}

    combat_rounds = [
        s.get("combat_round") for s in statuses if s.get("combat_round")
    ]
    entered = any(s.get("in_combat") for s in statuses)
    concluded = bool(entered and statuses and not statuses[-1].get("in_combat"))

    milestones: set[str] = set()
    for s in statuses:
        milestones.update((s.get("active_flags") or {}).keys())

    abilities: set[str] = set()
    items: set[str] = set()
    outcomes: dict[str, str] = {}
    for t in turns:
        for entry in t.get("combat_log") or []:
            action = entry.get("action")
            # "use_item" is the legacy action name (old artifacts);
            # consumables now resolve via InteractAction, with the
            # entry's target_is_item flag distinguishing a carried item
            # (potion, antidote) from a room feature (lever, cage).
            if action == "use_item":
                if entry.get("target"):
                    items.add(entry["target"])
            elif (
                action == "interact"
                and entry.get("target_is_item")
                and entry.get("target")
            ):
                items.add(entry["target"])
            elif action == "death":
                outcomes[entry.get("actor")] = "dead"
            elif action == "flee":
                outcomes[entry.get("actor")] = "fled"
            elif entry.get("attack_id"):
                abilities.add(entry["attack_id"])

    knowledge = final_status.get("player_knowledge") or []
    notes = final_status.get("entity_notes") or {}

    last = turns[-1] if turns else {}
    last_status = statuses[-1] if statuses else {}

    return {
        "turn_count": len(turns),
        "aborted": bool(_get(data, "aborted", False)),
        "abort_reason": _get(data, "abort_reason"),
        "error": error,
        "warnings": list(_get(data, "warnings") or []),
        "game_over": last.get("game_over", False),
        "game_over_type": last.get("game_over_type"),
        "player_hp": last_status.get("player_hp"),
        "player_max_hp": last_status.get("player_max_hp"),
        "combat": {
            "entered": entered,
            "concluded": concluded,
            "rounds": max(combat_rounds) if combat_rounds else None,
        },
        "milestones": sorted(milestones),
        "knowledge_topics": sorted(
            e.get("topic_id") for e in knowledge if isinstance(e, dict) and e.get("topic_id")
        ),
        "npc_notes_archived": sorted(k for k, v in notes.items() if v),
        "abilities_used": sorted(abilities),
        "items_used": sorted(items),
        "enemy_outcomes": outcomes,
        "hp_over_turns": [s.get("player_hp") for s in statuses],
        "judge": judge_digest(judge_block),
    }


def summarize_indicator(result_or_dict: Any) -> dict[str, Any]:
    """Compute the indicator-turn summary block from a run or artifact.

    Accepts an in-memory ``IndicatorTurnResult`` (duck-typed) or a
    parsed artifact dict (schema-2 envelope or legacy flat shape).
    """
    if isinstance(result_or_dict, dict):
        _, data, judge_block = split_artifact(result_or_dict)
        error = result_or_dict.get("error")
    else:
        data = result_or_dict
        judge_block = _get(data, "judge_record")
        judge_block = judge_block.to_dict() if judge_block else None
        err = _get(data, "error")
        error = f"{type(err).__name__}: {err}" if err is not None else None

    indicators = _get(data, "indicators") or []
    placed = sum(1 for ind in indicators if ind.get("placed_inline"))
    raw = _get(data, "raw_narration") or ""
    final = _get(data, "final_narration") or ""
    engine = _get(data, "engine_result") or {}

    return {
        "placed_count": placed,
        "total_indicators": len(indicators),
        "markers_placed_inline": f"{placed}/{len(indicators)}",
        "engine_success": engine.get("success"),
        "raw_narration_len": len(raw),
        "final_narration_len": len(final),
        "leftover_markers": final.count("[MECH:"),
        "error": error,
        "warnings": list(_get(data, "warnings") or []),
        "judge": judge_digest(judge_block),
    }
