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

from mgmai.models.corpus import (
    EncounterRule,
    ModuleCorpus,
    StatCheck,
    StatModifier,
)
from mgmai.models.hard_state import HardGameState, GameOverState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate
from mgmai.engine.systems import get_system_for_corpus


def resolve_encounter(
    encounter_rules: list[EncounterRule],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    npc_id: str | None = None,
) -> dict:
    """Evaluate encounter rules top-to-bottom. First matching condition wins.

    Returns a dict with keys:
        outcome: str ("death", "flee", "roll_success", "roll_failure", "none")
        narrative: str | None
        set_flags: dict[str, bool]
        game_over: dict | None  -- {type: str, trigger: str}
        flee_effects: dict | None  -- set_flags + set_entity_state + effect string
    """
    for rule in encounter_rules:
        if evaluate(rule.condition, hard, soft, corpus):
            return _apply_encounter_rule(rule, hard, soft, corpus, npc_id)

    return {
        "outcome": "none",
        "narrative": None,
        "set_flags": {},
        "alter_stat": {},
        "game_over": None,
        "flee_effects": None,
        "rolls": [],
    }


def _apply_encounter_rule(
    rule: EncounterRule,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    npc_id: str | None,
) -> dict:
    outcome = rule.outcome

    if outcome == "death":
        return {
            "outcome": "death",
            "narrative": rule.narrative,
            "set_flags": rule.set_flags or {},
            "alter_stat": rule.alter_stat or {},
            "game_over": {
                "type": "lose",
                "trigger": npc_id or "encounter",
            },
            "flee_effects": None,
            "rolls": [],
        }

    if outcome == "combat":
        return {
            "outcome": "combat",
            "narrative": rule.narrative,
            "set_flags": rule.set_flags or {},
            "alter_stat": rule.alter_stat or {},
            "game_over": None,
            "flee_effects": None,
            "rolls": [],
        }

    if outcome == "flee":
        flee_data = None
        set_flags = dict(rule.set_flags or {})
        if npc_id:
            npc = corpus.entities.get(npc_id)
            if npc and npc.behavior and npc.behavior.on_flee:
                flee = npc.behavior.on_flee
                for flag, val in flee.set_flags.items():
                    set_flags[flag] = val
                flee_data = {
                    "set_flags": flee.set_flags,
                    "set_entity_state": flee.set_entity_state,
                    "effect": flee.effect,
                }
        return {
            "outcome": "flee",
            "narrative": rule.narrative,
            "set_flags": set_flags,
            "alter_stat": rule.alter_stat or {},
            "game_over": None,
            "flee_effects": flee_data,
            "rolls": [],
        }

    if outcome == "stat_check":
        if rule.check is None:
            return {
                "outcome": "none",
                "narrative": None,
                "set_flags": {},
                "alter_stat": {},
                "game_over": None,
                "flee_effects": None,
                "rolls": [],
            }

        encounter_rolls: list = []
        success = _resolve_encounter_stat_check(rule, hard, corpus, encounter_rolls)
        branch = rule.on_success if success else rule.on_failure

        if branch is None:
            return {
                "outcome": f"stat_check_{'success' if success else 'failure'}",
                "narrative": rule.narrative,
                "set_flags": rule.set_flags or {},
                "alter_stat": rule.alter_stat or {},
                "game_over": None,
                "flee_effects": None,
                "rolls": encounter_rolls,
            }

        sub_outcome = branch.outcome if branch else "none"
        result: dict = {
            "outcome": sub_outcome,
            "narrative": branch.narrative if branch else rule.narrative,
            "set_flags": {},
            "alter_stat": {},
            "game_over": None,
            "flee_effects": None,
            "rolls": encounter_rolls,
        }

        if rule.set_flags:
            for flag, val in rule.set_flags.items():
                result["set_flags"][flag] = val
        if branch.set_flags:
            for flag, val in branch.set_flags.items():
                result["set_flags"][flag] = val

        if rule.alter_stat:
            result["alter_stat"].update(rule.alter_stat)
        if branch.alter_stat:
            result["alter_stat"].update(branch.alter_stat)

        if sub_outcome == "death":
            result["game_over"] = {
                "type": "lose",
                "trigger": npc_id or "encounter",
            }
        elif sub_outcome == "flee":
            flee_data = None
            if npc_id:
                npc = corpus.entities.get(npc_id)
                if npc and npc.behavior and npc.behavior.on_flee:
                    flee_obj = npc.behavior.on_flee
                    for flag, val in flee_obj.set_flags.items():
                        result["set_flags"][flag] = val
                    flee_data = {
                        "set_flags": flee_obj.set_flags,
                        "set_entity_state": flee_obj.set_entity_state,
                        "effect": flee_obj.effect,
                    }
            result["flee_effects"] = flee_data

        return result

    if outcome == "roll":
        if rule.threshold is None:
            return {
                "outcome": "none",
                "narrative": None,
                "set_flags": {},
                "alter_stat": {},
                "game_over": None,
                "flee_effects": None,
                "rolls": [],
            }
        roll = random.random()
        success = roll < rule.threshold
        branch = rule.on_success if success else rule.on_failure

        if branch is None:
            return {
                "outcome": f"roll_{'success' if success else 'failure'}",
                "narrative": rule.narrative,
                "set_flags": rule.set_flags or {},
                "alter_stat": rule.alter_stat or {},
                "game_over": None,
                "flee_effects": None,
                "rolls": [{
                    "encounter_id": npc_id or "encounter",
                    "threshold": rule.threshold,
                    "result": roll,
                    "success": success,
                }],
            }

        sub_outcome = branch.outcome if branch else "none"
        result: dict = {
            "outcome": sub_outcome,
            "narrative": branch.narrative if branch else rule.narrative,
            "set_flags": {},
            "alter_stat": {},
            "game_over": None,
            "flee_effects": None,
            "rolls": [{
                "encounter_id": npc_id or "encounter",
                "threshold": rule.threshold,
                "result": roll,
                "success": success,
            }],
        }

        if rule.set_flags:
            for flag, val in rule.set_flags.items():
                result["set_flags"][flag] = val
        if branch.set_flags:
            for flag, val in branch.set_flags.items():
                result["set_flags"][flag] = val

        if rule.alter_stat:
            result["alter_stat"].update(rule.alter_stat)
        if branch.alter_stat:
            result["alter_stat"].update(branch.alter_stat)

        if sub_outcome == "death":
            result["game_over"] = {
                "type": "lose",
                "trigger": npc_id or "encounter",
            }
        elif sub_outcome == "flee":
            flee_data = None
            if npc_id:
                npc = corpus.entities.get(npc_id)
                if npc and npc.behavior and npc.behavior.on_flee:
                    flee = npc.behavior.on_flee
                    for flag, val in flee.set_flags.items():
                        result["set_flags"][flag] = val
                    flee_data = {
                        "set_flags": flee.set_flags,
                        "set_entity_state": flee.set_entity_state,
                        "effect": flee.effect,
                    }
            result["flee_effects"] = flee_data

        return result

    return {
        "outcome": "none",
        "narrative": None,
        "set_flags": {},
        "alter_stat": {},
        "game_over": None,
        "flee_effects": None,
        "rolls": [],
    }


def should_trigger_behavior(
    entity_id: str,
    action_type: str,
    action_target: str | None,
    corpus: ModuleCorpus,
) -> list[EncounterRule] | None:
    """Check if an action triggers an NPC's behavior block.

    Returns the encounter rules if triggered, None otherwise.
    """
    entity = corpus.entities.get(entity_id)
    if entity is None or entity.behavior is None:
        return None

    behavior = entity.behavior
    triggers = behavior.triggers_on or []

    if action_type in triggers:
        return behavior.encounter_rules

    if action_target and action_target in triggers:
        return behavior.encounter_rules

    return None


def apply_flee_effects(
    flee_data: dict | None,
    hard: HardGameState,
) -> None:
    """Apply on_flee effects to hard state."""
    if flee_data is None:
        return

    set_flags = flee_data.get("set_flags") or {}
    for flag, val in set_flags.items():
        hard.flags[flag] = val

    set_entity_state = flee_data.get("set_entity_state") or {}
    for entity_id, state_changes in set_entity_state.items():
        if entity_id not in hard.entity_states:
            hard.entity_states[entity_id] = {}
        hard.entity_states[entity_id].update(state_changes)


def _resolve_encounter_stat_check(
    rule: EncounterRule,
    hard: HardGameState,
    corpus: ModuleCorpus,
    rolls: list,
) -> bool:
    """Resolve a stat_check outcome for an encounter rule. Returns True if passed."""
    if rule.check is None:
        return True

    check = rule.check
    stats_block = corpus.stats
    if stats_block is None:
        return True

    player_stats = hard.player.stats
    if player_stats is None or check.stat not in player_stats:
        return True

    system = get_system_for_corpus(corpus)
    cr = system.roll_check(
        check.stat,
        player_stats[check.stat],
        check.dc,
        flat_modifier=check.modifier,
        params=check.resolution_params,
    )
    rolls.append({
        "encounter_id": getattr(rule, "id", "encounter"),
        **cr.to_dict(),
    })
    return cr.success
