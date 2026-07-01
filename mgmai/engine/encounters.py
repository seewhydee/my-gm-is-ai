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

from __future__ import annotations

import random
from typing import Any

from mgmai.models.corpus import (
    EncounterRule,
    ModuleCorpus,
    Result,
    RollCheck,
    StatCheck,
)
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate
from mgmai.engine.systems import get_system_for_corpus


def resolve_encounter(
    encounter_rules: list[EncounterRule],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    npc_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate encounter rules top-to-bottom. First matching condition wins.

    Returns a dict with keys:
        narrative: str | None
        set_flags: dict[str, bool]
        alter_stat: dict[str, StatModifier]
        player_damage: str | None
        trigger_combat: bool
        game_over: dict | None  -- {type: str, trigger: str}
        rolls: list[dict]
        branch_taken: str | None
    """
    for rule in encounter_rules:
        if evaluate(rule.condition, hard, soft, corpus):
            return _apply_encounter_rule(rule, hard, soft, corpus, npc_id)

    return _empty_result()


def _empty_result(rolls: list[dict] | None = None) -> dict[str, Any]:
    return {
        "narrative": None,
        "set_flags": {},
        "alter_stat": {},
        "player_damage": None,
        "trigger_combat": False,
        "game_over": None,
        "rolls": rolls or [],
        "branch_taken": None,
    }


def _game_over_dict(
    go_trigger: Any | None,
    npc_id: str | None,
) -> dict[str, str] | None:
    if go_trigger is None:
        return None
    return {"type": go_trigger.type, "trigger": go_trigger.trigger_id}


def _apply_encounter_rule(
    rule: EncounterRule,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    npc_id: str | None,
) -> dict[str, Any]:
    encounter_rolls: list[dict] = []
    firing_result: Result | None = None
    branch_taken: str | None = None

    if rule.check is not None:
        # Check-bearing rule: resolve the check, pick success/failure
        check = rule.check

        if isinstance(check, StatCheck):
            stats_block = corpus.stats
            player_stats = hard.player.stats
            if stats_block is None or player_stats is None or check.stat not in player_stats:
                # No stats system or player stat: auto-pass (preserves legacy behavior)
                passed = True
            else:
                system = get_system_for_corpus(corpus)
                cr = system.roll_check(
                    check.stat,
                    player_stats[check.stat],
                    check.target,
                    flat_modifier=check.modifier,
                    params=check.model_extra or {},
                )
                encounter_rolls.append({
                    "encounter_id": npc_id or "encounter",
                    **cr.to_dict(),
                })
                passed = cr.success
        else:
            # RollCheck
            roll = random.random()
            passed = roll < check.threshold
            encounter_rolls.append({
                "encounter_id": npc_id or "encounter",
                "threshold": check.threshold,
                "result": roll,
                "success": passed,
            })

        firing_result = rule.success if passed else rule.failure
        branch_taken = "success" if passed else "failure"
    else:
        # Result-bearing rule: apply directly
        firing_result = rule.result

    if firing_result is None:
        return _empty_result(rolls=encounter_rolls)

    return {
        "narrative": firing_result.narrative,
        "set_flags": firing_result.set_flag or {},
        "alter_stat": firing_result.alter_stat or {},
        "player_damage": firing_result.player_damage,
        "trigger_combat": firing_result.trigger_combat,
        "game_over": _game_over_dict(firing_result.game_over, npc_id),
        "rolls": encounter_rolls,
        "branch_taken": branch_taken,
    }
