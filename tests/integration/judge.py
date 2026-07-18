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

"""LLM judge for integration-test transcripts.

Feeds the full transcript plus the engine combat log to a judge model
with a rubric, returning structured JSON.  The judge verifies
narration quality and consistency — things the hard assertions can't
check.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mgmai.llm.client import LLMClient

from tests.integration.runner import ScenarioResult

log = logging.getLogger(__name__)


_JUDGE_SYSTEM_PROMPT = """\
You are a QA judge evaluating a transcript of an AI Game Master session.

You will receive a JSON transcript of a combat scenario: each turn's
player command, the GM's narration, the engine's combat log (ground
truth for what mechanically happened), and the post-turn status.

## Rubric

Evaluate the transcript against these criteria.  For each, assign a
score from 1 (worst) to 5 (best) and write a one-sentence note.

1. **mechanical_fidelity**: Every hit/miss/KO in the combat log is
   reflected in the narration.  The narration does not describe
   attacks that didn't happen or omit major combat events.

2. **consistency**: No contradictions — dead enemies do not act, HP
   values in narration match the status, characters do not appear
   after being removed.

3. **narration_quality**: No verbatim repetition of narration across
   turns, no degenerate text (loops, garbage, empty-seeming
   filler).  Narration is readable and varied.

4. **coherent_arc**: The fight has a coherent arc and conclusion.
   The narrative flows logically from start to finish.

5. **command_appropriateness**: The player's commands are reasonable
   for the scenario (attacking enemies, using items when hurt, etc.).
   The driver does not issue nonsense or get stuck.

## Output

Output a single JSON object (no markdown, no prose) with this shape:

```
{
  "pass": true | false,
  "overall_score": <1-5>,
  "criteria": {
    "mechanical_fidelity": {"score": <1-5>, "note": "..."},
    "consistency": {"score": <1-5>, "note": "..."},
    "narration_quality": {"score": <1-5>, "note": "..."},
    "coherent_arc": {"score": <1-5>, "note": "..."},
    "command_appropriateness": {"score": <1-5>, "note": "..."}
  },
  "summary": "One-paragraph summary of the run's quality."
}
```

Set ``pass`` to ``false`` if any criterion scores 2 or below, or if
the run is fundamentally broken (no combat, immediate game-over,
infinite loop).  Otherwise set ``pass`` to ``true``.
"""


class JudgeError(RuntimeError):
    """Raised when the judge LLM produces unparseable output."""


def judge_scenario(
    judge_client: LLMClient,
    result: ScenarioResult,
    *,
    temperature: float | None = 0.2,
    max_tokens: int = 1000,
) -> dict[str, Any]:
    """Run the judge LLM over a scenario result.

    Returns the parsed verdict dict (with ``pass``, ``overall_score``,
    ``criteria``, ``summary``).  Raises ``JudgeError`` if the output
    can't be parsed as JSON.
    """
    transcript_json = _build_transcript_for_judge(result)
    raw = judge_client.call(
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        user_prompt=transcript_json,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_judge_output(raw)


def parse_judge_output(raw: str) -> dict[str, Any]:
    """Parse the judge LLM's raw output into a verdict dict.

    Tolerates markdown code fences and leading/trailing prose.
    Raises ``JudgeError`` on unparseable output.
    """
    if not raw or not raw.strip():
        raise JudgeError("Empty judge output")

    text = raw.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove the opening fence (and optional language tag).
        if lines:
            lines = lines[1:]
        # Remove the closing fence if present.
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try to extract a JSON object (tolerate leading/trailing prose).
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to finding the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JudgeError(
                f"Judge output contained a JSON-like block but failed to parse: {exc}"
            ) from exc

    raise JudgeError(
        f"Judge output is not valid JSON (first 200 chars): {raw[:200]!r}"
    )


def _build_transcript_for_judge(result: ScenarioResult) -> str:
    """Build the JSON transcript the judge will score.

    Compact form: one entry per turn with command, narration, and
    combat log.  Status snapshots are summarised to HP values to keep
    the prompt small.
    """
    turns: list[dict[str, Any]] = []
    for i, t in enumerate(result.turns, 1):
        combatants_summary: dict[str, Any] = {}
        for cid, info in t.status.combatants.items():
            combatants_summary[cid] = {
                "hp": info["hp"],
                "max_hp": info["max_hp"],
                "side": info["side"],
                "alive": info["alive"],
            }
        turns.append({
            "turn": i,
            "command": t.command,
            "narration": t.narration,
            "combat_log": t.combat_log,
            "post_turn": {
                "in_combat": t.status.in_combat,
                "round": t.status.combat_round,
                "player_hp": t.status.player_hp,
                "player_max_hp": t.status.player_max_hp,
                "combatants": combatants_summary,
            },
            "errors": t.errors,
            "exception": (
                f"{type(t.exception).__name__}: {t.exception}"
                if t.exception is not None
                else None
            ),
        })

    payload = {
        "scenario": result.scenario_name,
        "turn_count": result.turn_count,
        "final_status": result.final_status,
        "run_error": (
            f"{type(result.error).__name__}: {result.error}"
            if result.error is not None
            else None
        ),
        "turns": turns,
    }
    return json.dumps(payload, indent=2, default=str)


def format_verdict_for_failure(verdict: dict[str, Any]) -> str:
    """Format a failing verdict for inclusion in a pytest failure message."""
    lines = [
        f"Judge verdict: pass={verdict.get('pass')}",
        f"Overall score: {verdict.get('overall_score')}",
    ]
    criteria = verdict.get("criteria") or {}
    for name, info in criteria.items():
        if isinstance(info, dict):
            lines.append(f"  {name}: {info.get('score')}/5 — {info.get('note', '')}")
        else:
            lines.append(f"  {name}: {info}")
    if verdict.get("summary"):
        lines.append(f"Summary: {verdict['summary']}")
    return "\n".join(lines)
