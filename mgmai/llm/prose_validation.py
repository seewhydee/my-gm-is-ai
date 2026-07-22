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

"""Semantic validation of prose (LLM Call 2) outputs.

``parse_prose_output`` guarantees syntactic/schema validity only.  A
narration can be well-formed JSON and still be semantically broken —
e.g. mangled markers, duplicated mechanical text, or contradiction of
the engine result.  This module checks the parsed :class:`NarrationOutput`
against the engine result and indicators, returning a short,
model-addressed error string when the output is clearly invalid.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mgmai.engine.narrative_indicators import NarrativeIndicator
    from mgmai.models.actions import EngineResult
    from mgmai.models.narration import NarrationOutput


# Regex that catches near-miss marker syntax: anything that looks like
# [MECH:...] but isn't an exact valid marker.
_MANGLED_MARKER_RE = re.compile(r"\[\s*MECH\s*[: ]", re.IGNORECASE)

# Words that suggest success when the engine said failure (and vice versa).
_SUCCESS_WORDS = frozenset({
    "succeed", "succeeded", "success", "successful", "successfully",
    "works", "worked", "working",
    "manage", "managed", "manages",
    "accomplish", "accomplished",
})
_FAILURE_WORDS = frozenset({
    "fail", "failed", "fails", "failure",
    "unsuccessful", "unsuccessfully",
    "miss", "missed", "misses",
})


def validate_prose_output(
    prose: NarrationOutput,
    indicators: list[NarrativeIndicator],
    engine_result: EngineResult,
) -> str | None:
    """Check a parsed NarrationOutput for semantic problems.

    Returns ``None`` when the output passes all checks (or when there
    are no indicators and no obvious contradiction).  Otherwise returns
    a short error string addressed to the model, suitable for a
    corrective retry prompt.
    """
    narration = prose.narration or ""

    # 1. Narration must not be empty.
    if not narration.strip():
        return (
            "Your narration is empty. "
            "You must provide a non-empty 'narration' string."
        )

    # 2. Indicator checks (only if indicators were provided).
    if indicators:
        marker_error = _validate_indicators(narration, indicators)
        if marker_error:
            return marker_error

    # 3. Lightweight mechanical-contradiction heuristic.
    contradiction_error = _validate_mechanical_contradiction(narration, engine_result)
    if contradiction_error:
        return contradiction_error

    return None


def _validate_indicators(
    narration: str,
    indicators: list[NarrativeIndicator],
) -> str | None:
    """Check marker placement rules.

    - Each marker must appear at most once (no duplication).
    - No mangled/near-miss marker syntax.
    - The plain description of each indicator must not appear verbatim
      in the narration (the narrator wrote out the mechanical text
      instead of using the marker).
    - At least one marker should be placed if indicators exist (all
      falling back is a degraded experience and suggests the model
      ignored the instruction).
    """
    # 2a. Duplication check.
    for ind in indicators:
        count = narration.count(ind.marker)
        if count > 1:
            return (
                f"You placed the marker '{ind.marker}' {count} times. "
                f"Each marker must appear exactly once. "
                f"Place it once at the narratively appropriate point."
            )

    # 2b. Mangled marker check.
    for match in _MANGLED_MARKER_RE.finditer(narration):
        matched_text = match.group(0)
        # Is this an exact match for any known marker?
        start = match.start()
        end = match.end()
        # Heuristic: look ahead to find the closing bracket.
        close_bracket = narration.find("]", end)
        if close_bracket == -1:
            close_bracket = len(narration)
        candidate = narration[start:close_bracket + 1]
        if candidate not in {ind.marker for ind in indicators}:
            return (
                f"You used a mangled marker '{candidate}'. "
                f"Copy each marker verbatim — do not retype, renumber, or paraphrase it."
            )

    # 2c. Plain-description leakage check.
    for ind in indicators:
        desc = ind.plain_description
        # Allow short descriptions (≤5 chars) to avoid false positives.
        if len(desc) > 5 and desc in narration:
            return (
                f"You wrote out the mechanical text '{desc}' in your narration. "
                f"Do NOT write out the mechanical text yourself. "
                f"Place the marker '{ind.marker}' instead, and the engine will substitute it."
            )

    # 2d. All-indicators-unplaced check.
    placed_any = any(ind.marker in narration for ind in indicators)
    if not placed_any:
        return (
            f"You did not place any of the {len(indicators)} required marker(s). "
            f"Place each marker inside your narration at the narratively appropriate point. "
            f"Do not leave them all for the fallback."
        )

    return None


def _validate_mechanical_contradiction(
    narration: str,
    engine_result: EngineResult,
) -> str | None:
    """Lightweight heuristic: detect narration contradicting engine result.

    Only flags obvious mismatches (success words when engine said
    failure, or failure words when engine said success).  This is
    intentionally conservative to avoid false positives.
    """
    text = narration.lower()
    # Strip punctuation for word-boundary checks.
    words = set(re.findall(r"\b\w+\b", text))

    if not engine_result.success:
        # Engine said failure; check for strong success words.
        hits = words & _SUCCESS_WORDS
        if hits:
            return (
                f"The engine result says the action failed, but your narration "
                f"uses success words ({', '.join(sorted(hits))}). "
                f"Narrate the failure naturally — do not contradict the engine outcome."
            )
    else:
        # Engine said success; check for strong failure words.
        # Be more conservative here — "miss" can appear in combat narration
        # even on success (e.g. "you dodge but still strike"). Only flag
        # if clear failure words are present.
        failure_hits = words & _FAILURE_WORDS
        # Filter out "miss" / "missed" / "misses" in combat contexts to reduce FPs.
        filtered = {w for w in failure_hits if w not in ("miss", "missed", "misses")}
        if filtered:
            return (
                f"The engine result says the action succeeded, but your narration "
                f"uses failure words ({', '.join(sorted(filtered))}). "
                f"Narrate the success naturally — do not contradict the engine outcome."
            )

    return None
