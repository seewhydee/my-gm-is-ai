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

"""LLM judge for narrative-indicator integration tests.

Feeds a single indicator turn — the mechanical events, the markers
offered to the narrator, the narrator's raw output, and the final
player-facing narration — to a judge model with a rubric focused on
marker interpretation.  The verdict is advisory only: deterministic
assertions are the gate.  Callers record the verdict in the run
artifact and may surface a failing verdict as a warning, never as a
test failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mgmai.llm.client import LLMClient

from tests.integration.indicator_runner import IndicatorTurnResult
from tests.integration.judge import JudgeError, parse_judge_output

log = logging.getLogger(__name__)


_INDICATOR_JUDGE_SYSTEM_PROMPT = """\
You are a QA judge evaluating ONE turn of an AI Game Master session,
focusing on how the GM narrator handled **mechanical indicators**.

Background: the engine produces mechanical events for the turn (stat
checks, HP changes, combat log entries).  Each event is offered to the
narrator as a unique marker (e.g. `[MECH:check:0]`) together with a
plain-text description (e.g. `STR check: failed`).  The narrator is
instructed to place each marker inside its narration at the
narratively appropriate point — typically immediately before
describing the consequence of that event.  After the narrator
responds, the engine replaces each placed marker with canonical
formatted text (e.g. `**[STR check: failed]**`); markers the narrator
did not place are prepended to the narration as a fallback.

You will receive a JSON object with:

- **scenario**: the scenario name.
- **player_command**: what the player did.
- **mechanical_events**: ground truth — the engine's rolls, combat
  log, and state changes for the turn.
- **indicators**: every marker offered to the narrator, its plain
  description, and whether the narrator placed it inline
  (`placed_inline`) or left it to the fallback.
- **narrator_output_with_markers**: the narrator's raw response, with
  markers as it placed them.
- **final_player_facing_narration**: what the player actually sees,
  after marker replacement and fallback prepending.

## Rubric

Evaluate against these criteria.  For each, assign a score from 1
(worst) to 5 (best) and write a one-sentence note.

1. **marker_interpretation**: The narrator understood the marker
   mechanism.  Markers are placed inline at narratively appropriate
   points (each right before the text describing that event's
   consequence), each used at most once, none mangled or altered.  A
   narrator that ignored all markers (all fell back to prepending)
   scores low; partial placement scores in the middle.  With multiple
   markers, they appear in an order that matches the narration's
   chronology.

2. **mechanical_fidelity**: The narration is consistent with the
   mechanical events: check outcomes (success/failure), damage amounts
   and HP, hits/misses, and deaths are all correctly reflected.  No
   contradictions, no invented mechanical events.

3. **cleanliness**: The final player-facing narration contains no
   leftover raw marker syntax, no duplicated mechanical summaries
   (e.g. the narrator writing its own "STR check: failed" text in
   addition to placing the marker), and reads as a coherent whole
   rather than a mechanical dump stapled onto unrelated prose.

4. **narration_quality**: The prose is immersive, readable, and
   integrates the mechanical events naturally — no degenerate text,
   no contradiction of earlier events in the turn, no empty filler.

## Output

Output a single JSON object (no markdown, no prose) with this shape:

```
{
  "pass": true | false,
  "overall_score": <1-5>,
  "criteria": {
    "marker_interpretation": {"score": <1-5>, "note": "..."},
    "mechanical_fidelity": {"score": <1-5>, "note": "..."},
    "cleanliness": {"score": <1-5>, "note": "..."},
    "narration_quality": {"score": <1-5>, "note": "..."}
  },
  "summary": "One-paragraph summary of the turn's quality."
}
```

Set ``pass`` to ``false`` if any criterion scores 2 or below, or if
the turn is fundamentally broken (raw markers visible to the player,
narration contradicting the mechanical events, empty or degenerate
narration).  Otherwise set ``pass`` to ``true``.
"""


def judge_indicator_turn(
    judge_client: LLMClient,
    result: IndicatorTurnResult,
    *,
    temperature: float | None = 0.2,
    max_tokens: int = 1000,
) -> dict[str, Any]:
    """Run the judge LLM over a single indicator turn.

    Returns the parsed verdict dict (with ``pass``, ``overall_score``,
    ``criteria``, ``summary``).  Raises ``JudgeError`` if the output
    can't be parsed as JSON.
    """
    payload = _build_payload_for_judge(result)
    raw = judge_client.call(
        system_prompt=_INDICATOR_JUDGE_SYSTEM_PROMPT,
        user_prompt=payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_judge_output(raw)


def _build_payload_for_judge(result: IndicatorTurnResult) -> str:
    """Build the JSON payload the judge will score.

    The engine result is trimmed to the mechanically relevant fields
    (rolls, combat log, state changes, triggered narration) to keep
    the prompt small.
    """
    engine = result.engine_result or {}
    mechanical_events = {
        "success": engine.get("success"),
        "rolls": engine.get("rolls"),
        "combat_log": engine.get("combat_log"),
        "hard_state_changes": engine.get("hard_state_changes"),
        "triggered_narration": engine.get("triggered_narration"),
        "game_over": engine.get("game_over"),
    }
    payload = {
        "scenario": result.scenario_name,
        "player_command": result.player_input,
        "mechanical_events": mechanical_events,
        "indicators": [
            {
                "marker": ind["marker"],
                "description": ind["plain_description"],
                "category": ind["category"],
                "placed_inline": ind["placed_inline"],
            }
            for ind in result.indicators
        ],
        "narrator_output_with_markers": result.raw_narration,
        "final_player_facing_narration": result.final_narration,
        "run_error": (
            f"{type(result.error).__name__}: {result.error}"
            if result.error is not None
            else None
        ),
    }
    return json.dumps(payload, indent=2, default=str)


__all__ = [
    "JudgeError",
    "judge_indicator_turn",
]
