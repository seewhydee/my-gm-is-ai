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

"""Tests for the rests feature: state fields, system hooks, the rest
action, ruling validation, and the rest.completed event."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mgmai.engine.engine import resolve
from mgmai.engine.resolver import resolve_action, resolve_rest
from mgmai.engine.systems import get_system_for_corpus
from mgmai.llm.ruling_validation import validate_ruling_action
from mgmai.models.actions import (
    PlayerAction,
    RestAction,
    RestRechargeResult,
    validate_player_action,
)
from mgmai.models.combat import CombatState
from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    CombatBlock,
    DialogueGuidelines,
    ModuleCorpus,
    ReactionEffects,
    Result,
    StatDefinition,
    StatsBlock,
)
from mgmai.models.hard_state import HardGameState, HitDice, PlayerState
from mgmai.models.soft_state import SoftGameState
from tests.helpers import (
    _mk_npc_entity,
    _mk_reaction,
    _mk_room,
    build_state_manager,
    make_char_sheet_corpus,
)

_STATS_5E = StatsBlock(
    definitions={
        s: StatDefinition(name=s.title())
        for s in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
    },
    system="5e",
)
_STATS_10 = {s: 10 for s in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}


def _corpus() -> ModuleCorpus:
    return make_char_sheet_corpus()


def _player(**kw) -> PlayerState:
    base = {
        "location": "axe_head",
        "current_hp": 3,
        "max_hp": 11,
        "stats": dict(_STATS_10),
        "spell_slots": {1: 0, 2: 1},
        "max_spell_slots": {1: 4, 2: 2},
        "hit_dice": HitDice(die="d8", current=1, max=5),
        "status_effects": {"mage_armor": 1, "exhaustion-2": 1},
    }
    base.update(kw)
    return PlayerState(**base)


def _hard(player: PlayerState | None = None) -> HardGameState:
    return HardGameState(player=player or _player())


def _soft() -> SoftGameState:
    return SoftGameState()


# ------------------------------------------------------------------
# Phase 0a — state model
# ------------------------------------------------------------------


class TestRestStateModel:
    def test_string_key_json_coercion(self):
        p = PlayerState.model_validate({
            "location": "r1",
            "spell_slots": {"1": 2, "2": 1},
            "max_spell_slots": {"1": 4, "2": 3},
            "hit_dice": {"die": "d8", "current": 2, "max": 5},
        })
        assert p.spell_slots == {1: 2, 2: 1}
        assert p.max_spell_slots == {1: 4, 2: 3}
        assert p.hit_dice.die == "d8"
        assert p.hit_dice.current == 2
        assert p.hit_dice.max == 5

    def test_json_round_trip_keeps_string_keys(self):
        p = _player()
        dumped = p.model_dump(mode="json")
        assert dumped["spell_slots"] == {"1": 0, "2": 1}
        assert dumped["max_spell_slots"] == {"1": 4, "2": 2}
        assert dumped["hit_dice"] == {"die": "d8", "current": 1, "max": 5}
        # Round-trips back to int keys.
        p2 = PlayerState.model_validate(dumped)
        assert p2.max_spell_slots == {1: 4, 2: 2}

    def test_char_sheet_merge_loads_new_fields(self, tmp_path):
        from mgmai.state.manager import StateManager

        sheet = {
            "system": "5e",
            "player": {
                "stats": _STATS_10,
                "max_hp": 8,
                "current_hp": 8,
                "spell_slots": {"1": 2},
                "max_spell_slots": {"1": 4},
                "hit_dice": {"die": "d6", "current": 2, "max": 2},
            },
        }
        sheet_path = tmp_path / "sheet.json"
        sheet_path.write_text(json.dumps(sheet))

        sm = StateManager()
        sm.load_all(Path("tests/integration/fixtures/spell_arena"))
        sm.apply_char_sheet(sheet_path)
        p = sm.hard_state.player
        assert p.max_spell_slots == {1: 4}
        assert p.hit_dice.die == "d6"
        assert p.hit_dice.current == 2
        assert p.hit_dice.max == 2


# ------------------------------------------------------------------
# System hooks
# ------------------------------------------------------------------


class TestRestHooks:
    def test_long_rest_full_recharge(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        rr = system.on_long_rest(_hard(), corpus)
        assert rr.hp_delta == 8          # 11 - 3
        assert rr.slots_refilled_to_max is True
        assert rr.statuses_to_clear == ["mage_armor"]
        assert rr.hit_dice_recovered == 4   # 5 - 1
        assert rr.exhaustion_decrement == 1

    def test_long_rest_no_max_spell_slots_is_no_refill(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        hard = _hard(player=_player(max_spell_slots={}))
        rr = system.on_long_rest(hard, corpus)
        assert rr.slots_refilled_to_max is False

    def test_long_rest_no_hit_dice_is_zero_recovered(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        hard = _hard(player=_player(hit_dice=None))
        rr = system.on_long_rest(hard, corpus)
        assert rr.hit_dice_recovered == 0

    def test_long_rest_exhaustion_level_1_flagged_for_decrement(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        hard = _hard(player=_player(
            status_effects={"exhaustion-1": 1, "mage_armor": 1},
        ))
        rr = system.on_long_rest(hard, corpus)
        assert rr.exhaustion_decrement == 1
        assert rr.statuses_to_clear == ["mage_armor"]

    def test_long_rest_no_exhaustion_no_decrement(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        hard = _hard(player=_player(status_effects={"mage_armor": 1}))
        rr = system.on_long_rest(hard, corpus)
        assert rr.exhaustion_decrement == 0

    def test_long_rest_full_hp_zero_delta(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        hard = _hard(player=_player(current_hp=11))
        rr = system.on_long_rest(hard, corpus)
        assert rr.hp_delta == 0

    def test_long_rest_does_not_clear_exhaustion_directly(self):
        # exhaustion-N must NOT appear in statuses_to_clear; the decrement
        # handles it separately so it is reduced, not wiped.
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        rr = system.on_long_rest(_hard(), corpus)
        assert not any(
            s.startswith("exhaustion") for s in rr.statuses_to_clear
        )

    def test_short_rest_is_no_op(self):
        corpus = _corpus()
        system = get_system_for_corpus(corpus)
        rr = system.on_short_rest(_hard(), corpus)
        assert rr.hp_delta == 0
        assert rr.slots_refilled_to_max is False
        assert rr.statuses_to_clear == []
        assert rr.hit_dice_recovered == 0
        assert rr.exhaustion_decrement == 0

    def test_base_defaults_are_no_op(self):
        from mgmai.engine.systems.base import ResolutionSystem

        # The base class defaults must be no-ops so non-5e systems are
        # unaffected until they override.  ResolutionSystem is abstract,
        # so call the unbound methods directly (their bodies don't use
        # ``self``).
        corpus = _corpus()
        rr = ResolutionSystem.on_long_rest(None, _hard(), corpus)
        assert isinstance(rr, RestRechargeResult)
        assert rr.hp_delta == 0
        rr = ResolutionSystem.on_short_rest(None, _hard(), corpus)
        assert rr.hp_delta == 0


# ------------------------------------------------------------------
# resolve_rest / resolve_action
# ------------------------------------------------------------------


class TestResolveRest:
    def test_long_rest_applies_full_recharge(self):
        corpus = _corpus()
        hard = _hard()
        res = resolve_action(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        assert res.hard_changes.player_hp_delta == 8
        assert hard.player.spell_slots == {1: 4, 2: 2}
        assert hard.player.hit_dice.current == 5
        assert "mage_armor" not in hard.player.status_effects
        assert "exhaustion-2" not in hard.player.status_effects
        assert "exhaustion-1" in hard.player.status_effects

    def test_long_rest_emits_rest_completed_event(self):
        corpus = _corpus()
        hard = _hard()
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert ("rest.completed", {"kind": "long"}) in res.events

    def test_long_rest_emits_status_effect_events(self):
        corpus = _corpus()
        hard = _hard()
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        cleared = [
            e[1]["status_effect_id"]
            for e in res.events
            if e[0] == "status_effect.cleared"
        ]
        assert "mage_armor" in cleared
        assert "exhaustion-2" in cleared
        applied = [
            e[1]["status_effect_id"]
            for e in res.events
            if e[0] == "status_effect.applied"
        ]
        assert "exhaustion-1" in applied

    def test_message_summarises_recharge(self):
        corpus = _corpus()
        hard = _hard()
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.message is not None
        assert "HP +8" in res.message
        assert "spell slots recharged" in res.message
        assert "exhaustion -1" in res.message

    def test_exhaustion_level_1_removed_entirely(self):
        corpus = _corpus()
        hard = _hard(player=_player(status_effects={
            "exhaustion-1": 1, "mage_armor": 1,
        }))
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        assert "exhaustion-1" not in hard.player.status_effects
        # No exhaustion-0 exists.
        assert not any(
            k.startswith("exhaustion") for k in hard.player.status_effects
        )

    def test_short_rest_is_no_op_recharge(self):
        corpus = _corpus()
        hard = _hard()
        res = resolve_action(
            RestAction(action_type="rest", kind="short", detail="nap"),
            hard, _soft(), corpus,
        )
        assert res.success
        assert res.hard_changes.player_hp_delta is None
        # State unchanged.
        assert hard.player.spell_slots == {1: 0, 2: 1}
        assert hard.player.current_hp == 3
        assert hard.player.status_effects == {"mage_armor": 1, "exhaustion-2": 1}
        assert ("rest.completed", {"kind": "short"}) in res.events
        assert "no resources recovered" in res.message

    def test_rejected_during_combat(self):
        corpus = _corpus()
        hard = _hard()
        hard.combat = CombatState(
            active=True, round_number=1, combatants=[],
            initiative_order=[], current_actor="player",
        )
        res = resolve_action(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert not res.success
        assert "combat" in res.error.lower()

    def test_no_max_spell_slots_skips_refill_gracefully(self):
        corpus = _corpus()
        hard = _hard(player=_player(max_spell_slots={}))
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        # spell_slots left untouched (no ceiling to refill to).
        assert hard.player.spell_slots == {1: 0, 2: 1}

    def test_partial_max_spell_slots_preserves_undeclared_levels(self):
        corpus = _corpus()
        # Level 2 has slots but no max entry (a sheet omission the
        # validator only warns about).
        hard = _hard(player=_player(
            spell_slots={1: 0, 2: 1},
            max_spell_slots={1: 4},
        ))
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        # Level 1 refilled to its ceiling; the undeclared level-2 slot
        # is preserved, not wiped.
        assert hard.player.spell_slots == {1: 4, 2: 1}

    def test_long_rest_heals_follower_allies(self):
        companion = _mk_npc_entity(
            "companion",
            combat=CombatBlock(hp=10, ac=12, atk=3, dmg="1d6", flee_dc=10),
        )
        companion.dialogue = DialogueGuidelines(guidelines="A loyal companion.")
        corpus = make_char_sheet_corpus(entities={"companion": companion})
        hard = _hard()
        hard.entity_states["companion"] = {
            "alive": True, "following": True, "current_hp": 4,
        }
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        # Full heal, mutated directly and recorded as an absolute set.
        assert hard.entity_states["companion"]["current_hp"] == 10
        assert (
            res.hard_changes.entity_state_changes["companion"]["current_hp"]
            == 10
        )
        assert "followers healed" in res.message

    def test_short_rest_does_not_heal_followers(self):
        companion = _mk_npc_entity(
            "companion",
            combat=CombatBlock(hp=10, ac=12, atk=3, dmg="1d6", flee_dc=10),
        )
        companion.dialogue = DialogueGuidelines(guidelines="A loyal companion.")
        corpus = make_char_sheet_corpus(entities={"companion": companion})
        hard = _hard()
        hard.entity_states["companion"] = {
            "alive": True, "following": True, "current_hp": 4,
        }
        res = resolve_rest(
            RestAction(action_type="rest", kind="short", detail="nap"),
            hard, _soft(), corpus,
        )
        assert res.success
        assert hard.entity_states["companion"]["current_hp"] == 4

    def test_hit_dice_recovered_clamps_to_max(self):
        corpus = _corpus()
        hard = _hard(player=_player(
            hit_dice=HitDice(die="d8", current=4, max=5),
        ))
        res = resolve_rest(
            RestAction(action_type="rest", kind="long", detail="camp"),
            hard, _soft(), corpus,
        )
        assert res.success
        # SRD 5.2.1: all spent regained -> 4 + (5-4)=5, clamped at max.
        assert hard.player.hit_dice.current == 5

    def test_unknown_action_type_returns_error(self):
        # Sanity: the dispatch still rejects unknown types.
        corpus = _corpus()

        class _Bogus:
            action_type = "rest_nap"

        res = resolve_action(_Bogus(), _hard(), _soft(), corpus)
        assert not res.success
        assert "Unknown action type" in res.error


# ------------------------------------------------------------------
# Engine integration
# ------------------------------------------------------------------


class TestRestEngineIntegration:
    def test_long_rest_through_engine(self):
        corpus = _corpus()
        sm = build_state_manager(corpus, _hard())
        turn_before = sm.hard_state.turn_count

        res = resolve(
            RestAction(action_type="rest", kind="long", detail="camp"), sm,
        )
        assert res.success
        assert res.costs_turn is True
        assert res.message and "HP +8" in res.message
        # HP delta applied to current_hp via HardStateChanges.
        assert sm.hard_state.player.current_hp == 11
        assert sm.hard_state.player.spell_slots == {1: 4, 2: 2}
        assert sm.hard_state.player.hit_dice.current == 5
        assert "exhaustion-1" in sm.hard_state.player.status_effects
        assert "mage_armor" not in sm.hard_state.player.status_effects
        # A rest costs a turn.
        assert sm.hard_state.turn_count == turn_before + 1

    def test_short_rest_through_engine_costs_turn(self):
        corpus = _corpus()
        sm = build_state_manager(corpus, _hard())
        turn_before = sm.hard_state.turn_count
        res = resolve(
            RestAction(action_type="rest", kind="short", detail="nap"), sm,
        )
        assert res.success
        assert sm.hard_state.turn_count == turn_before + 1
        # No recharge on a short rest.
        assert sm.hard_state.player.current_hp == 3

    def test_rest_completed_reaction_fires(self):
        # A corpus reaction on rest.completed (deferred) must fire when a
        # rest resolves.
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="T", introduction="t",
                atmosphere=Atmosphere(setting="test", tone="neutral"),
            ),
            rooms={
                "start": _mk_room("start", "Start", is_start_room=True,
                                  reactions=[
                                      _mk_reaction(
                                          "rest_reaction",
                                          on="rest.completed",
                                          effect=ReactionEffects(
                                              result=Result(
                                                  set_flag={"rested": True},
                                              ),
                                          ),
                                      ),
                                  ]),
            },
            entities={},
            stats=_STATS_5E,
            flags_declared=["rested"],
        )
        sm = build_state_manager(
            corpus, _hard(player=_player(location="start")),
        )
        res = resolve(
            RestAction(action_type="rest", kind="long", detail="camp"), sm,
        )
        assert res.success
        assert sm.hard_state.flags.get("rested") is True


# ------------------------------------------------------------------
# Ruling validation
# ------------------------------------------------------------------


def _rest(kind: str = "long") -> RestAction:
    return RestAction(action_type="rest", kind=kind, detail="rest")


class TestRestRulingValidation:
    def test_rest_flagged_during_combat(self):
        from tests.test_ruling_validation import _combat_briefing

        error = validate_ruling_action(_rest(), _combat_briefing())
        assert error is not None
        assert "rest" in error
        assert "'wait'" in error
        assert "detail" in error

    def test_rest_passes_outside_combat(self):
        from tests.test_ruling_validation import _peaceful_briefing

        assert validate_ruling_action(_rest(), _peaceful_briefing()) is None


# ------------------------------------------------------------------
# Action union parsing
# ------------------------------------------------------------------


class TestRestActionParsing:
    def test_parse_long_rest(self):
        a = validate_player_action({
            "action_type": "rest", "kind": "long",
            "detail": "camp", "follow_up": None, "soft_state_patches": [],
        })
        assert isinstance(a, RestAction)
        assert a.kind == "long"

    def test_parse_short_rest(self):
        a = PlayerAction.model_validate({
            "action_type": "rest", "kind": "short", "detail": "nap",
            "follow_up": None, "soft_state_patches": [],
        })
        assert a.kind == "short"

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            validate_player_action({
                "action_type": "rest", "kind": "nap",
                "detail": "x", "soft_state_patches": [],
            })

    def test_missing_kind_rejected(self):
        with pytest.raises(ValidationError):
            validate_player_action({
                "action_type": "rest", "detail": "x",
                "soft_state_patches": [],
            })
