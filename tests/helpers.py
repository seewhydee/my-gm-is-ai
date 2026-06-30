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

"""Helpers for building in-memory test StateManager instances."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from mgmai.models.actions import HardStateChanges
from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    BranchOutcome,
    CombatBlock,
    ConditionExpression,
    EncounterRule,
    Entity,
    Exit,
    Interaction,
    Mechanic,
    ModuleCorpus,
    OnHitEffect,
    OnHitSave,
    Reaction,
    ReactionEffects,
    Result,
    Room,
    StatCheck,
    StatDefinition,
    StatModifier,
    StatsBlock,
    TraversalCheck,
    UsingResultOverride,
)
from mgmai.models.hard_state import HardGameState, PlayerState
from mgmai.models.soft_state import SoftGameState
from mgmai.state.manager import StateManager

TEST_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TEST_DIR / "fixtures"


# ------------------------------------------------------------------
# Shared 5e stat block
# ------------------------------------------------------------------

_STATS_5E = StatsBlock(
    definitions={
        "STR": StatDefinition(name="Strength", description="Physical power"),
        "DEX": StatDefinition(name="Dexterity", description="Agility"),
        "CON": StatDefinition(name="Constitution", description="Endurance"),
        "INT": StatDefinition(name="Intelligence", description="Reasoning"),
        "WIS": StatDefinition(name="Wisdom", description="Perception"),
        "CHA": StatDefinition(name="Charisma", description="Personality"),
    },
    system="5e",
)

_STATS_10 = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}


def _mk_cond(require: str | None = None, unless: str | None = None) -> ConditionExpression:
    kwargs: dict[str, Any] = {}
    if require is not None:
        kwargs["require"] = require
    if unless is not None:
        kwargs["unless"] = unless
    return ConditionExpression.model_validate(kwargs)


def _mk_room(
    rid: str,
    name: str,
    description: str = "A room.",
    exits: list[Exit] | None = None,
    contains: list[str] | None = None,
    reactions: list[Reaction] | None = None,
    interactions: list[Interaction] | None = None,
    is_start_room: bool = False,
) -> Room:
    return Room(
        id=rid,
        name=name,
        description=description,
        exits=exits or [],
        contains=contains or [],
        reactions=reactions or [],
        interactions=interactions or [],
        is_start_room=is_start_room,
    )


def _mk_exit(
    eid: str,
    target_room: str,
    direction: str = "Go",
    traversal_check: TraversalCheck | None = None,
    one_way: bool = False,
) -> Exit:
    return Exit(
        id=eid,
        direction=direction,
        target_room=target_room,
        traversal_check=traversal_check,
        one_way=one_way,
    )


def _mk_npc_entity(
    eid: str,
    description: str = "An NPC.",
    state_fields: dict[str, Any] | None = None,
    combat: CombatBlock | None = None,
    reactions: list[Reaction] | None = None,
) -> Entity:
    sf: dict[str, Any] = {"alive": {"type": "boolean", "description": "Alive?"}}
    if state_fields:
        sf.update(state_fields)
    return Entity(
        type="npc",
        id=eid,
        description=description,
        state_fields=sf,
        combat=combat,
        reactions=reactions or [],
    )


def _mk_item_entity(
    eid: str,
    description: str = "An item.",
    tags: list[str] | None = None,
    name: str | None = None,
) -> Entity:
    return Entity(
        type="item",
        id=eid,
        name=name or eid,
        description=description,
        tags=tags or [],
    )


def _mk_reaction(
    rid: str,
    on: str,
    effect: ReactionEffects,
    condition: ConditionExpression | None = None,
    phase: str | None = None,
) -> Reaction:
    kwargs: dict[str, Any] = {"id": rid, "on": on, "effect": effect}
    if condition is not None:
        kwargs["condition"] = condition
    if phase is not None:
        kwargs["phase"] = phase
    return Reaction.model_validate(kwargs)


def _mk_encounter_rule(
    outcome: str,
    condition: ConditionExpression | None = None,
    narrative: str | None = None,
    threshold: float | None = None,
    alter_stat: dict[str, StatModifier] | None = None,
    player_damage: str | None = None,
    success: BranchOutcome | None = None,
    failure: BranchOutcome | None = None,
) -> EncounterRule:
    rule_data: dict[str, Any] = {
        "condition": condition or _mk_cond(require="entity:test_npc.alive == true"),
        "outcome": outcome,
    }
    if narrative is not None:
        rule_data["narrative"] = narrative
    if threshold is not None:
        rule_data["threshold"] = threshold
    if alter_stat is not None:
        rule_data["alter_stat"] = alter_stat
    if player_damage is not None:
        rule_data["player_damage"] = player_damage
    if success is not None:
        rule_data["success"] = success
    if failure is not None:
        rule_data["failure"] = failure
    return EncounterRule.model_validate(rule_data)


def _mk_mechanic(
    mid: str,
    description: str,
    rules: list[EncounterRule],
) -> Mechanic:
    return Mechanic(
        id=mid,
        description=description,
        rules=rules,
    )


def _mk_hard_state(
    player_location: str = "start",
    flags: dict[str, bool] | None = None,
    entity_states: dict[str, dict[str, Any]] | None = None,
    room_states: dict[str, dict[str, Any]] | None = None,
    stats: dict[str, int] | None = None,
    inventory: list[str] | None = None,
) -> HardGameState:
    return HardGameState(
        player=PlayerState(
            location=player_location,
            inventory=inventory or [],
            stats=stats or copy.deepcopy(_STATS_10),
        ),
        flags=flags or {},
        room_states=room_states or {},
        entity_states=entity_states or {},
        turn_count=0,
        game_over=None,
    )


# ------------------------------------------------------------------
# Pre-built test corpora
# ------------------------------------------------------------------


def make_encounter_trigger_corpus(
    mechanic_id: str = "test_encounter",
    room_id: str = "start",
    exit_id: str = "exit_test",
    target_room_id: str = "target",
    reaction_event: str = "traversal.attempted",
    encounter_outcome: str = "flee",
    encounter_narrative: str | None = "Encounter!",
    alter_stat: dict[str, StatModifier] | None = None,
    player_damage: str | None = None,
    encounter_condition: ConditionExpression | None = None,
) -> ModuleCorpus:
    """Build a minimal corpus that tests encounter trigger via reaction."""
    room = _mk_room(
        room_id, "Start Room",
        exits=[_mk_exit(exit_id, target_room_id)],
        reactions=[
            _mk_reaction(
                "test_reaction",
                on=reaction_event,
                condition=_mk_cond(require=f"event:exit_id == {exit_id}"),
                effect=ReactionEffects(trigger_encounter=mechanic_id),
                phase="immediate",
            )
        ],
        is_start_room=True,
    )
    target = _mk_room(target_room_id, "Target Room")
    return ModuleCorpus(
        adventure=Adventure(
            title="Test Adventure",
            introduction="A test.",
            atmosphere=Atmosphere(setting="test", tone="neutral"),
        ),
        rooms={room_id: room, target_room_id: target},
        entities={
            "test_npc": _mk_npc_entity("test_npc"),
        },
        mechanics={
            mechanic_id: _mk_mechanic(
                mechanic_id,
                "Test encounter",
                rules=[
                    _mk_encounter_rule(
                        outcome=encounter_outcome,
                        narrative=encounter_narrative,
                        alter_stat=alter_stat,
                        player_damage=player_damage,
                        condition=encounter_condition,
                    )
                ],
            )
        },
        stats=_STATS_5E,
    )


def make_webs_test_corpus() -> ModuleCorpus:
    """Build a corpus that mirrors the web-traversal mechanics for testing."""
    spider_entity = _mk_npc_entity(
        "spider",
        description="A hairy spider.",
        state_fields={
            "fled": {"type": "boolean", "description": "Fled?"},
            "hidden": {"type": "boolean", "description": "Hidden?"},
            "attitude": {"type": "number", "description": "Attitude"},
            "current_hp": {"type": "number", "description": "HP"},
        },
        combat=CombatBlock(hp=15, ac=14, atk=5, dmg="1d4+3"),
        reactions=[
            _mk_reaction(
                "spider_attack_on_web_push",
                on="traversal.attempted",
                condition=ConditionExpression.model_validate({
                    "all": [
                        {"require": "event:exit_id == exit_force_through_web"},
                        {"require": "entity:spider.alive == true"},
                        {"unless": "entity:spider.fled == true"},
                    ]
                }),
                effect=ReactionEffects(trigger_encounter="spider_attack"),
                phase="immediate",
            ),
            _mk_reaction(
                "spider_defeated",
                on="entity_state.changed",
                condition=ConditionExpression.model_validate({
                    "all": [
                        {"require": "event:entity_id == spider"},
                        {"require": "event:field == alive"},
                        {"require": "event:new_value == false"},
                    ]
                }),
                effect=ReactionEffects(
                    result=Result(
                        narrative="The spider dies.",
                        set_flag={"spider_fled": True},
                        set_entity_state={"spider": {"fled": True}},
                    )
                ),
            ),
        ],
    )

    toenail = _mk_item_entity("toenail_sword", description="A sharp toenail.", tags=["weapon"], name="Toenail Sword")
    korbar = _mk_npc_entity(
        "korbar",
        description="A dwarf.",
        state_fields={
            "following": {"type": "boolean", "description": "Following?"},
            "attitude": {"type": "number", "description": "Attitude"},
            "current_hp": {"type": "number", "description": "HP"},
        },
        combat=CombatBlock(hp=29, ac=18, atk=4, dmg="1d4+1"),
    )

    lower_room = _mk_room(
        "axe_handle_lower",
        "Lower Handle",
        description="The lower axe handle, wrapped in webs.",
        contains=["spider"],
        exits=[
            _mk_exit("exit_up_handle_lower", "axe_handle_upper"),
            _mk_exit(
                "exit_force_through_web",
                "bag_floor",
                traversal_check=TraversalCheck.model_validate({
                    "check": {"type": "stat_check", "stat": "STR", "target": 14, "repeatable": True},
                    "gating": {"unless": "flag:webs_cleared == true"},
                    "skip_check_if": {"require": "flag:webs_cleared == true"},
                    "failure": {"narrative": "The webs hold fast."},
                    "using_results": {
                        "toenail_sword": {
                            "check": {"type": "stat_check", "stat": "STR", "target": 10, "repeatable": True},
                            "success": {},
                        },
                        "*": {
                            "check": {"type": "stat_check", "stat": "STR", "target": 10, "repeatable": True},
                            "success": {},
                        },
                    },
                }),
            ),
            _mk_exit(
                "exit_drop_from_lower",
                "bag_floor",
                one_way=True,
            ),
        ],
    )

    upper_room = _mk_room(
        "axe_handle_upper",
        "Upper Handle",
        exits=[
            _mk_exit("exit_down_handle_upper", "axe_handle_lower"),
        ],
    )

    floor_room = _mk_room(
        "bag_floor",
        "Bag Floor",
        contains=["korbar"],
        exits=[
            _mk_exit(
                "exit_climb_up_handle_floor",
                "axe_handle_lower",
                traversal_check=TraversalCheck.model_validate({
                    "gating": {"require": "inventory:giant_key"},
                    "check": {"type": "stat_check", "stat": "STR", "target": 12, "repeatable": True},
                    "skip_check_if": {"require": "entity:korbar.following == true"},
                    "failure": {"narrative": "Too heavy!"},
                }),
            ),
        ],
    )

    return ModuleCorpus(
        adventure=Adventure(
            title="Web Test",
            introduction="A test adventure.",
            atmosphere=Atmosphere(setting="test", tone="webby"),
        ),
        rooms={
            "axe_handle_lower": lower_room,
            "axe_handle_upper": upper_room,
            "bag_floor": floor_room,
        },
        entities={
            "spider": spider_entity,
            "toenail_sword": toenail,
            "korbar": korbar,
        },
        mechanics={
            "spider_attack": _mk_mechanic(
                "spider_attack",
                "Spider encounter",
                rules=[
                    _mk_encounter_rule(
                        outcome="combat",
                        narrative="The spider attacks!",
                        condition=_mk_cond(require="entity:spider.alive == true"),
                    )
                ],
            )
        },
        stats=_STATS_5E,
        flags_declared=["webs_cleared", "spider_fled"],
    )


def make_webs_hard_state(
    location: str = "axe_handle_lower",
    flags: dict[str, bool] | None = None,
    spider_alive: bool = True,
    spider_fled: bool = False,
    spider_hidden: bool = True,
    inventory: list[str] | None = None,
    korbar_following: bool = False,
) -> HardGameState:
    """Build a hard state matching make_webs_test_corpus."""
    entity_states: dict[str, dict[str, Any]] = {
        "spider": {
            "alive": spider_alive,
            "fled": spider_fled,
            "hidden": spider_hidden,
            "attitude": -2,
            "current_hp": 15,
        },
        "korbar": {
            "alive": True,
            "following": korbar_following,
            "attitude": 0,
            "current_hp": 29,
        },
    }
    room_states = {
        "axe_handle_lower": {"visited": False},
        "axe_handle_upper": {"visited": False},
        "bag_floor": {"visited": False},
    }
    default_flags = {"webs_cleared": False, "spider_fled": False}
    if flags:
        default_flags.update(flags)

    return _mk_hard_state(
        player_location=location,
        flags=default_flags,
        entity_states=entity_states,
        room_states=room_states,
        inventory=inventory or [],
    )


def make_char_sheet_corpus(
    rooms: dict[str, Room] | None = None,
    entities: dict[str, Entity] | None = None,
) -> ModuleCorpus:
    """Build a minimal corpus for testing char sheet application."""
    if rooms is None:
        rooms = {
            "axe_head": _mk_room("axe_head", "Axe Head", is_start_room=True),
            "bag_floor": _mk_room("bag_floor", "Bag Floor"),
        }
    if entities is None:
        entities = {
            "toenail_sword": _mk_item_entity("toenail_sword", "A sharp toenail.", name="Toenail Sword"),
        }
    return ModuleCorpus(
        adventure=Adventure(
            title="Char Sheet Test",
            introduction="Test.",
            atmosphere=Atmosphere(setting="test", tone="neutral"),
        ),
        rooms=rooms,
        entities=entities,
        stats=_STATS_5E,
    )


def make_char_sheet_state(
    location: str = "axe_head",
    inventory: list[str] | None = None,
    stats: dict[str, int] | None = None,
) -> HardGameState:
    """Build a hard state matching make_char_sheet_corpus."""
    room_states = {rid: {"visited": False} for rid in ["axe_head", "bag_floor"]}
    return _mk_hard_state(
        player_location=location,
        flags={},
        entity_states={},
        room_states=room_states,
        stats=stats or copy.deepcopy(_STATS_10),
        inventory=inventory or [],
    )


def build_state_manager(
    corpus: ModuleCorpus,
    hard_state: HardGameState | None = None,
    soft_state: SoftGameState | None = None,
) -> StateManager:
    """Assemble a StateManager with in-memory corpus and state.

    If *hard_state* is not provided, a default is built from the corpus:
    entity_states are populated from each entity's state_fields (boolean
    fields default to True, others to 0), and room_states are created with
    ``visited: False`` for every room in the corpus.
    """
    sm = StateManager()
    sm.corpus = corpus

    if hard_state is None:
        entity_states: dict[str, dict[str, Any]] = {}
        for eid, ent in corpus.entities.items():
            states: dict[str, Any] = {}
            for fname, fdecl in ent.state_fields.items():
                if fdecl.type == "boolean":
                    states[fname] = True
                elif fdecl.get("type") == "number":  # type: ignore[union-attr]
                    states[fname] = 0
                else:
                    states[fname] = ""
            entity_states[eid] = states
        room_states = {rid: {"visited": False} for rid in corpus.rooms}
        sm.hard_state = _mk_hard_state(
            entity_states=entity_states,
            room_states=room_states,
        )
    else:
        sm.hard_state = hard_state

    sm.soft_state = soft_state or SoftGameState()
    sm._adventure_dir = None
    # Initialise combat defaults (HP, AC) from corpus stats if present.
    sm._init_player_combat_defaults()
    return sm
