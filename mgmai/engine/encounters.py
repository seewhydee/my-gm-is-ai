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

from typing import Any

from mgmai.models.actions import HardStateChanges
from mgmai.models.corpus import (
    EncounterRule,
    GameOverTrigger,
    ModuleCorpus,
)
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate
from mgmai.engine.resolver import _apply_result, _resolve_checkable


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
        changes: HardStateChanges  -- applied effects (flags, stats, damage, items, etc.)
        start_combat: list[str] | None  -- extra combatants from the firing Result;
            None means no combat, [] means combat with the encounter source only
        game_over: dict | None  -- {type: str, trigger: str}
        rolls: list[dict]
        branch_taken: str | None
    """
    for rule in encounter_rules:
        if rule.condition is None or evaluate(rule.condition, hard, soft, corpus):
            return _apply_encounter_rule(rule, hard, soft, corpus, npc_id)

    return _empty_result()


def _empty_result(rolls: list[dict] | None = None) -> dict[str, Any]:
    return {
        "narrative": None,
        "changes": HardStateChanges(),
        "start_combat": None,
        "game_over": None,
        "rolls": rolls or [],
        "branch_taken": None,
    }


def _game_over_dict(go_trigger: GameOverTrigger | None) -> dict[str, str] | None:
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
    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []
    rolls: list[dict] = []
    branch_taken: str | None = None

    if rule.result is not None:
        # Result-bearing rule: apply directly
        _apply_result(
            rule.result,
            changes=changes, narrative=narrative,
            revealed_hints=revealed_hints,
            hard=hard, corpus=corpus, soft=soft,
        )
        firing_result = rule.result
    else:
        # Check-bearing rule: use shared resolution path (handles
        # skip_check_if, stat/roll checks, and then_check chaining)
        passed = _resolve_checkable(
            rule,
            hard=hard, soft=soft, corpus=corpus,
            room_id=hard.player.location,
            changes=changes, narrative=narrative,
            revealed_hints=revealed_hints, rolls=rolls,
            source_id=npc_id or "encounter",
            source_type="encounter",
        )
        firing_result = rule.success if passed else rule.failure
        if firing_result is not None:
            branch_taken = "success" if passed else "failure"

    if narrative:
        narrative_text = "\n".join(narrative)
    elif firing_result is not None:
        narrative_text = firing_result.narrative
    else:
        narrative_text = None

    return {
        "narrative": narrative_text,
        "changes": changes,
        "start_combat": firing_result.start_combat if firing_result else None,
        "game_over": _game_over_dict(firing_result.game_over) if firing_result else None,
        "rolls": rolls,
        "branch_taken": branch_taken,
    }
