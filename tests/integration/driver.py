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
  "I drink a healing potion.", "I unleash a gout of flame on the bugbear.",
  "I flee through the northern corridor."
- Do NOT use slash commands (e.g. /quit, /save).  Play in-character.
- Do NOT narrate the outcome — the GM will do that.  Just say what
  your character does.
- During combat, pick a specific enemy or ally by name.  Switch
  targets when your current target is dead.
- If you are badly hurt, drink a healing potion or use a healing
  ability.
- Keep your command short (one sentence, under 200 characters).

If the game has gone badly off the rails — the GM narrates something
impossible or contradictory, the state clearly contradicts recent
narration, or you are stuck in a loop repeating the same failed action
— you may bail out by replying with the single word

ABORT: <a short reason>

instead of a game command.  Use this only when continuing is pointless.

## Current situation

{situation}

## Transcript (turn by turn)

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
        temperature: float | None = None,
        max_tokens: int = 200,
    ) -> None:
        self._llm = llm_client
        self._directive = directive
        self._max_history = max_history
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._raw_outputs: list[str] = []
        self._command_history: list[str] = []

    def next_command(self, session: HeadlessSession) -> str:
        """Produce the next command given the current session state."""
        situation = _format_situation(session)
        transcript = _format_transcript(session, self._max_history, self._command_history)
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
            json_mode=False,
        )
        self._raw_outputs.append(raw)
        cmd = sanitize_command(raw, self._command_history)
        self._command_history.append(cmd)
        return cmd

    @property
    def raw_outputs(self) -> list[str]:
        """Raw LLM responses, for the transcript artifact."""
        return list(self._raw_outputs)


# ------------------------------------------------------------------
# ABORT detection (called by the runner, not by the driver)
# ------------------------------------------------------------------


def is_abort(command: str) -> str | None:
    """Return the abort reason if *command* signals the driver is giving up.

    The driver may reply ``ABORT: <reason>`` when the game is
    irreparably broken.  Returns the reason string, or ``None`` if this
    is a normal command.
    """
    upper = command.strip().upper()
    if upper.startswith("ABORT:"):
        return command.split(":", 1)[1].strip() if ":" in command else "no reason given"
    if upper == "ABORT":
        return "no reason given"
    return None


def sanitize_command(raw: str, recent: list[str] | None = None) -> str:
    """Sanitise the driver LLM's raw output to a single game command.

    - Take the first non-empty line.
    - Strip surrounding quotes and whitespace.
    - Reject ``/`` meta-commands (return ``"wait"`` instead).
    - If the exact same command appears as the most recent entry in
      *recent*, the driver is stuck — return ``"wait"`` so the runner
      can detect a string of fallbacks.
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
    # Guard against exact repetition of the most recent command.
    if recent and recent and line == recent[-1]:
        return "wait"
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

    # Inventory: only show consumables the driver should know about
    # (not weapons/armour).
    corpus = session.corpus
    if corpus and hard.player.inventory:
        usable: list[str] = []
        for item_id, count in hard.player.inventory.items():
            if count <= 0:
                continue
            ent = corpus.entities.get(item_id)
            if ent is None:
                continue
            if ent.consumable:
                usable.append(f"{ent.name} x{count}")
        if usable:
            parts.append("Usable items: " + ", ".join(usable) + ".")

    # Ability uses remaining this combat (only when in combat).
    combat = hard.combat
    if snap.in_combat and combat is not None and corpus:
        for aid in hard.player.abilities:
            ability = corpus.abilities.get(aid)
            if ability is None or ability.uses_per_combat < 0:
                continue
            used = combat.ability_uses.get("player", {}).get(aid, 0)
            remaining = ability.uses_per_combat - used
            parts.append(f"{ability.name}: {remaining}/{ability.uses_per_combat} uses left.")

    return " ".join(parts)


def _format_transcript(
    session: HeadlessSession,
    max_history: int,
    past_commands: list[str],
) -> str:
    """Format the last N turns as a chronological transcript.

    Each turn pairs the driver's command with the GM's narration so the
    driver can see what it tried and what happened.  The i‑th command
    produced the i‑th narration (one-to-one).
    """
    display = session.display
    narrations = display.narrations[-max_history:]
    if not narrations:
        return "(no history yet — this is the first turn)"
    cmds = past_commands[-len(narrations):]
    lines: list[str] = []
    for i, (cmd, narration) in enumerate(zip(cmds, narrations), 1):
        c_snippet = cmd if len(cmd) <= 200 else cmd[:200] + "..."
        n_snippet = narration if len(narration) <= 500 else narration[:500] + "..."
        lines.append(f"Turn {i}: You ⇒ {c_snippet}\nTurn {i}: GM ⇒ {n_snippet}")
    return "\n\n".join(lines)
