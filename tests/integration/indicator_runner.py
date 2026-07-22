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

"""Single-turn harness for narrative-indicator integration tests.

Unlike ``runner.py`` (which plays a driver LLM against the full
two-call GM pipeline over many turns), this harness runs exactly ONE
fixed turn:

1. A hand-written ``PlayerAction`` is resolved by the real engine, so
   the scenario's engine-generated text (stat checks, HP changes,
   combat log entries) is controlled — Call 1 (ruling) is bypassed by
   design: what is under test is the narrator's handling of the
   mechanical indicators, not the ruling's classification.
2. The real ``GameLoop._call_prose`` (Call 2) is invoked with the
   indicators built from the engine result, exactly as in production.
3. ``process_narration`` replaces any markers the narrator placed.

The result records the raw narration (markers as the narrator placed
them), the final player-facing narration, and per-indicator placement
info, and writes a JSON artifact regardless of pass/fail.  Hard
assertions live in the test functions; an advisory LLM judge
(``indicator_judge.py``) evaluates placement quality.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mgmai.context.assembler import assemble
from mgmai.engine.engine import resolve
from mgmai.engine.narrative_indicators import (
    NarrativeIndicator,
    build_indicators,
    process_narration,
)
from mgmai.game.headless import HeadlessSession
from mgmai.llm.client import LLMClient
from mgmai.models.actions import PlayerAction
from mgmai.models.combat import CombatState
from mgmai.state.manager import StateManager

log = logging.getLogger(__name__)


@dataclass
class IndicatorTurnResult:
    """Outcome of a single fixed-action indicator turn."""

    scenario_name: str
    player_input: str = ""
    action: dict[str, Any] = field(default_factory=dict)
    # One entry per indicator: {marker, category, formatted,
    # plain_description, placed_inline}.
    indicators: list[dict[str, Any]] = field(default_factory=list)
    raw_narration: str | None = None
    final_narration: str | None = None
    engine_result: dict[str, Any] | None = None
    judge_verdict: dict[str, Any] | None = None
    error: BaseException | None = None
    artifacts_path: Path | None = None

    @property
    def placed_count(self) -> int:
        return sum(1 for ind in self.indicators if ind["placed_inline"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "player_input": self.player_input,
            "action": self.action,
            "indicators": self.indicators,
            "markers_placed_inline": f"{self.placed_count}/{len(self.indicators)}",
            "raw_narration": self.raw_narration,
            "final_narration": self.final_narration,
            "engine_result": self.engine_result,
            "judge_verdict": self.judge_verdict,
            "error": (
                f"{type(self.error).__name__}: {self.error}"
                if self.error is not None
                else None
            ),
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


def run_indicator_turn(
    *,
    scenario_name: str,
    gm_client: LLMClient,
    state_manager: StateManager,
    action: dict[str, Any],
    player_input: str,
    config_dir: Path,
    artifacts_dir: Path,
    combat_preset: CombatState | None = None,
    seed: int | None = None,
) -> IndicatorTurnResult:
    """Run one fixed action through the engine and the real GM prose call.

    * ``action`` is a PlayerAction JSON dict (e.g. an ``interact`` or
      ``combat``/``attack`` action) — the fixed scenario input.
    * ``player_input`` is the natural-language command it stands for;
      it appears in the briefing and chat context as the player's
      command echo.
    * ``combat_preset``, if given, is installed on the hard state
      before the turn (for scenarios that start mid-combat).
    * ``seed``, if given, pins ``random.seed()`` immediately before
      engine resolution, making dice outcomes reproducible.

    The artifact is written to ``artifacts_dir/<scenario_name>_<ts>.json``
    regardless of pass/fail.  The caller is responsible for hard
    assertions on the returned ``IndicatorTurnResult``.
    """
    result = IndicatorTurnResult(
        scenario_name=scenario_name,
        player_input=player_input,
        action=action,
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        hard = state_manager.hard_state
        if hard is None:
            raise RuntimeError("state_manager has no hard state loaded")
        if combat_preset is not None:
            hard.combat = combat_preset

        session = HeadlessSession(
            llm_client=gm_client,
            state_manager=state_manager,
            config_dir=config_dir,
        )
        corpus = session.corpus
        soft = session.soft_state
        if corpus is None or soft is None:
            raise RuntimeError("state_manager has no corpus/soft state loaded")

        # 1. Briefing (same assembler the loop uses).
        briefing = assemble(corpus, hard, soft, player_input)

        # 2. Fixed action — Call 1 (ruling) is deliberately bypassed so
        #    the engine outcome is controlled by the scenario.
        action_obj = PlayerAction.model_validate(action)

        # 3. Real engine resolution (dice pinned if seeded).
        if seed is not None:
            random.seed(seed)
        engine_result = resolve(
            action_obj,
            session.state_manager,
            chain_depth=0,
            player_input_echo=player_input,
        )
        result.engine_result = json.loads(engine_result.model_dump_json())

        # 4. Indicators + real GM prose call (production code path).
        indicators: list[NarrativeIndicator] = build_indicators(
            engine_result, hard, corpus
        )
        prose = session.loop._call_prose(
            briefing, action_obj, engine_result, indicators=indicators
        )

        # Mirror GameLoop._execute_turn's narration selection.
        raw_narration = prose.narration
        if not raw_narration.strip() and prose.npc_response:
            raw_narration = prose.npc_response.strip()
        result.raw_narration = raw_narration

        # 5. Marker replacement (production post-processing).
        result.final_narration = process_narration(raw_narration, indicators)

        result.indicators = [
            {
                "marker": ind.marker,
                "category": ind.category,
                "formatted": ind.formatted,
                "plain_description": ind.plain_description,
                "placed_inline": ind.marker in raw_narration,
            }
            for ind in indicators
        ]
    except Exception as exc:  # noqa: BLE001 — record + write artifact
        result.error = exc
        log.exception("Indicator turn failed for scenario %s", scenario_name)
    finally:
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
