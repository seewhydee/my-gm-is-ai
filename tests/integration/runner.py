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

"""Scenario runner for LLM-driven integration tests.

Runs a ``PlayerDriver`` against a ``HeadlessSession`` for a bounded
number of turns, recording every turn's transcript and writing a JSON
artifact regardless of pass/fail.  Hard assertions live in the test
functions; this module just runs and records.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mgmai.game.headless import HeadlessSession, TurnTranscript
from mgmai.llm.client import LLMClient

from tests.integration.driver import PlayerDriver, is_abort

log = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    """Outcome of a single scenario run."""

    scenario_name: str
    directive: str = ""
    turns: list[TurnTranscript] = field(default_factory=list)
    driver_raw_outputs: list[str] = field(default_factory=list)
    final_status: dict[str, Any] | None = None
    artifacts_path: Path | None = None
    judge_verdict: dict[str, Any] | None = None
    error: BaseException | None = None
    aborted: bool = False
    abort_reason: str | None = None

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def last_turn(self) -> TurnTranscript | None:
        return self.turns[-1] if self.turns else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "directive": self.directive,
            "turns": [t.to_dict() for t in self.turns],
            "driver_raw_outputs": list(self.driver_raw_outputs),
            "final_status": self.final_status,
            "judge_verdict": self.judge_verdict,
            "error": (
                f"{type(self.error).__name__}: {self.error}"
                if self.error is not None
                else None
            ),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
        }

    def rewrite_artifact(self) -> None:
        """Re-write the artifact file with the current state.

        Called after the judge updates ``judge_verdict`` so the artifact
        on disk reflects the final, complete result.
        """
        if self.artifacts_path is None:
            return
        try:
            self.artifacts_path.write_text(
                json.dumps(self.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Failed to re-write artifact %s: %s", self.artifacts_path, exc)


def run_scenario(
    *,
    scenario_name: str,
    gm_client: LLMClient,
    driver_client: LLMClient,
    adventure_dir: Path | None = None,
    artifacts_dir: Path,
    directive: str,
    max_turns: int = 25,
    config_dir: Path | None = None,
    state_manager: Any | None = None,
    stop_when: Callable[[HeadlessSession, list[TurnTranscript]], bool] | None = None,
) -> ScenarioResult:
    """Run a driver-vs-GM scenario and record the full transcript.

    Either ``adventure_dir`` (to load fresh) or ``state_manager`` (to
    reuse a pre-built state, e.g. with modified HP) must be provided.

    *stop_when*, if given, is called at the start of each turn with the
    current session and the list of turns so far.  Return ``True`` to
    stop early (e.g. after combat ends).  Stopping via *stop_when* is
    a normal result, not an error or abort.

    The artifact is written to ``artifacts_dir/<scenario_name>_<ts>.json``
    regardless of pass/fail.  The caller is responsible for hard
    assertions on the returned ``ScenarioResult``.
    """
    import tempfile

    _MAX_CONSECUTIVE_FALLBACKS = 3

    if config_dir is None:
        config_dir = Path(tempfile.mkdtemp(prefix="mgmai_scenario_"))

    if state_manager is not None:
        session = HeadlessSession(
            llm_client=gm_client,
            state_manager=state_manager,
            config_dir=config_dir,
        )
    elif adventure_dir is not None:
        session = HeadlessSession(
            llm_client=gm_client,
            adventure_dir=adventure_dir,
            config_dir=config_dir,
        )
    else:
        raise ValueError("run_scenario requires adventure_dir or state_manager")

    driver = PlayerDriver(driver_client, directive)

    result = ScenarioResult(scenario_name=scenario_name, directive=directive)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    consecutive_fallbacks = 0

    try:
        for i in range(max_turns):
            if session.is_over:
                break

            # Early stop via predicate (e.g. combat ended, objective
            # achieved).  Check before calling the driver so we don't
            # burn an LLM call on a done run.
            if stop_when is not None and stop_when(session, result.turns):
                break

            try:
                command = driver.next_command(session)
            except Exception as exc:  # noqa: BLE001 — record + abort
                result.error = exc
                log.exception("Driver LLM call failed on turn %d", i + 1)
                break

            # Driver asked to abort (game is broken).
            abort_reason = is_abort(command)
            if abort_reason is not None:
                result.aborted = True
                result.abort_reason = abort_reason
                log.warning("Driver aborted on turn %d: %s", i + 1, abort_reason)
                break

            # Guard against consecutive sanitize fallbacks (driver is
            # stuck in a "wait" loop).  A single "wait" is fine — the
            # LLM might just produce a poorly formatted line.
            if command == "wait":
                consecutive_fallbacks += 1
                if consecutive_fallbacks >= _MAX_CONSECUTIVE_FALLBACKS:
                    result.aborted = True
                    result.abort_reason = (
                        f"driver produced {consecutive_fallbacks} consecutive "
                        "unusable commands (sanitized to 'wait')"
                    )
                    log.warning("Consecutive fallback limit reached on turn %d", i + 1)
                    break
            else:
                consecutive_fallbacks = 0

            try:
                transcript = session.submit(command)
            except Exception as exc:  # noqa: BLE001 — record + abort
                # Build a partial transcript for the failed turn.
                transcript = TurnTranscript(
                    command=command,
                    narration=None,
                    status=session.status_snapshot(),
                    game_over=session.is_over,
                    game_over_type=(
                        session.hard_state.game_over.type
                        if session.hard_state and session.hard_state.game_over
                        else None
                    ),
                    errors=[],
                    exception=exc,
                )
                result.turns.append(transcript)
                result.error = exc
                log.exception("Game loop failed on turn %d", i + 1)
                break

            result.turns.append(transcript)

            if transcript.game_over:
                break
    finally:
        result.driver_raw_outputs = list(driver.raw_outputs)
        final_snapshot = session.status_snapshot().to_dict()
        # Augment with entity states so the artifact and tests can
        # inspect post-combat HP/alive/fled without relying on
        # combatants (which are cleared when combat ends).
        hard = session.hard_state
        if hard is not None:
            final_snapshot["entity_states"] = {
                eid: dict(state) for eid, state in hard.entity_states.items()
            }
        result.final_status = final_snapshot

        # Write the artifact regardless of pass/fail.
        artifact_path = artifacts_dir / f"{scenario_name}_{timestamp}.json"
        try:
            artifact_path.write_text(
                json.dumps(result.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            result.artifacts_path = artifact_path
        except OSError as exc:
            log.warning("Failed to write artifact to %s: %s", artifact_path, exc)

    return result
