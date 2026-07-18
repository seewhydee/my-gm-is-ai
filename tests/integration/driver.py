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

"""Player-driver LLM for integration tests.

The driver acts as the player: given the rolling transcript and a
scenario directive, it replies with exactly one game command.  Output
is sanitised to a single line; ``/`` meta-commands are rejected (the
driver must play the game, not poke the REPL).
"""

from __future__ import annotations

import logging

from mgmai.game.headless import HeadlessSession
from mgmai.llm.client import LLMClient

log = logging.getLogger(__name__)


_DRIVER_SYSTEM_PROMPT = """\
You are a playtester driving a tabletop RPG adventure via text commands.

You are NOT the GM.  Another LLM is the GM; you are the player.  Your
job is to play the game naturally, pursuing the scenario objective.

## Scenario directive
{directive}

## How to play

- Reply with EXACTLY ONE game command, as a natural-language sentence.
  Examples: "I attack the goblin grunt with my longsword.",
  "I drink a healing potion.", "I use Flame Strike on the bugbear.",
  "I flee through the northern corridor."
- Do NOT use slash commands (e.g. /quit, /save).  Play in-character.
- Do NOT narrate the outcome — the GM will do that.  Just say what
  your character does.
- During combat, pick a specific enemy or ability target by name.
  Switch targets when your current target is dead.
- If you are badly hurt, drink a healing potion or use a healing
  ability.
- Keep your command short (one sentence, under 200 characters).

## Current situation

{situation}

## Rolling transcript (most recent first)

{transcript}

Reply with your next command (one sentence, no quotes, no slash commands):
"""


class PlayerDriver:
    """LLM-driven player that issues one command per turn."""

    def __init__(
        self,
        llm_client: LLMClient,
        directive: str,
        *,
        max_history: int = 10,
        temperature: float | None = 0.7,
        max_tokens: int = 200,
    ) -> None:
        self._llm = llm_client
        self._directive = directive
        self._max_history = max_history
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._raw_outputs: list[str] = []

    def next_command(self, session: HeadlessSession) -> str:
        """Produce the next command given the current session state."""
        situation = _format_situation(session)
        transcript = _format_transcript(session, self._max_history)
        prompt = _DRIVER_SYSTEM_PROMPT.format(
            directive=self._directive,
            situation=situation,
            transcript=transcript,
        )
        raw = self._llm.call(
            system_prompt="You are a tabletop RPG playtester.",
            user_prompt=prompt,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        self._raw_outputs.append(raw)
        return sanitize_command(raw)

    @property
    def raw_outputs(self) -> list[str]:
        """Raw LLM responses, for the transcript artifact."""
        return list(self._raw_outputs)


def sanitize_command(raw: str) -> str:
    """Sanitise the driver LLM's raw output to a single game command.

    - Take the first non-empty line.
    - Strip surrounding quotes and whitespace.
    - Reject ``/`` meta-commands (return ``"wait"`` instead).
    - Truncate to a reasonable length.
    """
    if not raw:
        return "wait"
    # First non-empty line.
    line = ""
    for candidate in raw.splitlines():
        stripped = candidate.strip().strip('"').strip("'").strip()
        if stripped:
            line = stripped
            break
    if not line:
        return "wait"
    # Reject slash commands — the driver must play, not poke the REPL.
    if line.startswith("/"):
        return "wait"
    # Strip a leading "Player:" or similar label if present.
    if ":" in line and line.split(":", 1)[0].strip().lower() in {
        "player", "i", "action", "command",
    }:
        line = line.split(":", 1)[1].strip()
    # Truncate to a reasonable length.
    if len(line) > 300:
        line = line[:300]
    return line


def _format_situation(session: HeadlessSession) -> str:
    """Compact one-paragraph summary of the current game state."""
    hard = session.hard_state
    if hard is None:
        return "Game state unavailable."
    snap = session.status_snapshot()
    parts: list[str] = []
    parts.append(f"Turn {snap.turn_count}, location: {snap.location}.")
    if snap.in_combat:
        parts.append(f"In combat, round {snap.combat_round}.")
        party = [
            f"{cid} {c['hp']}/{c['max_hp']}"
            for cid, c in snap.combatants.items()
            if c["side"] == "party" and c["alive"]
        ]
        enemies = [
            f"{cid} {c['hp']}/{c['max_hp']}"
            for cid, c in snap.combatants.items()
            if c["side"] == "enemy" and c["alive"]
        ]
        if party:
            parts.append("Party: " + ", ".join(party) + ".")
        if enemies:
            parts.append("Enemies: " + ", ".join(enemies) + ".")
    else:
        parts.append(f"Not in combat. Player HP {snap.player_hp}/{snap.player_max_hp}.")
    if snap.active_flags:
        parts.append("Flags: " + ", ".join(snap.active_flags.keys()) + ".")
    return " ".join(parts)


def _format_transcript(session: HeadlessSession, max_history: int) -> str:
    """Format the last N turns of the session as a transcript."""
    display = session.display
    narrations = display.narrations[-max_history:]
    if not narrations:
        return "(no history yet — this is the first turn)"
    lines: list[str] = []
    for i, narration in enumerate(narrations, 1):
        # Truncate long narrations for the prompt.
        snippet = narration if len(narration) <= 500 else narration[:500] + "..."
        lines.append(f"Turn {i}: {snippet}")
    return "\n\n".join(lines)
