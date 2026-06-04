from __future__ import annotations

import json as _json
import re as _re

from mgmai.models.actions import validate_player_action
from mgmai.models.narration import NarrationOutput

_MARKDOWN_JSON_RE = _re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?```", _re.DOTALL
)


class LLMOutputError(Exception):
    """Raised when LLM output cannot be parsed into the expected Pydantic model."""


def _extract_json(raw: str) -> dict:
    """Extract a JSON dict from LLM output, with markdown-fence fallback.

    Attempts direct ``json.loads`` first.  If that fails and the string
    contains a `` ```json ... ``` `` (or plain `` ``` ``) fenced block,
    the content of the first such block is parsed instead.
    """
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        match = _MARKDOWN_JSON_RE.search(raw)
        if match:
            data = _json.loads(match.group(1))
        else:
            raise
    return data


def parse_player_action(raw: str):
    """Parse LLM Call 1 JSON output into a validated PlayerAction.

    Raises :exc:`LLMOutputError` on invalid JSON or schema mismatch.
    """
    try:
        data = _extract_json(raw)
    except _json.JSONDecodeError as exc:
        raise LLMOutputError(f"Invalid JSON from LLM Call 1: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMOutputError(
            "LLM Call 1 output must be a JSON object, "
            f"got {type(data).__name__}"
        )

    if "action_type" not in data:
        raise LLMOutputError(
            "LLM Call 1 output missing required field 'action_type'"
        )

    try:
        return validate_player_action(data)
    except Exception as exc:
        raise LLMOutputError(
            f"PlayerAction validation failed: {exc}"
        ) from exc


def parse_prose_output(raw: str) -> NarrationOutput:
    """Parse LLM Call 2 JSON output into NarrationOutput.

    Raises :exc:`LLMOutputError` on invalid JSON or schema mismatch.
    """
    try:
        data = _extract_json(raw)
    except _json.JSONDecodeError as exc:
        raise LLMOutputError(f"Invalid JSON from LLM Call 2: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMOutputError(
            "LLM Call 2 output must be a JSON object, "
            f"got {type(data).__name__}"
        )

    if "narration" not in data:
        raise LLMOutputError(
            "LLM Call 2 output missing required field 'narration'"
        )

    try:
        return NarrationOutput.model_validate(data)
    except Exception as exc:
        raise LLMOutputError(
            f"NarrationOutput validation failed: {exc}"
        ) from exc
