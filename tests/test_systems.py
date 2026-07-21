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

"""Tests for the resolution-system abstraction (mgmai.engine.systems)."""

from __future__ import annotations

import random

import pytest

from mgmai.engine.systems import (
    CheckResult,
    FleeResult,
    FiveESystem,
    NPCAttackResult,
    PlayerAttackResult,
    ResolutionSystem,
    SaveResult,
    get_system,
    get_system_for_corpus,
    register_system,
)
from mgmai.engine.systems.dice import parse_damage_dice
from mgmai.models.combat import CombatLogEntry
from mgmai.models.corpus import EquipBlock, ModuleCorpus, StatCheck
from mgmai.models.hard_state import HardGameState


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

class TestRegistry:
    def test_default_is_5e(self) -> None:
        assert get_system().name == "5e"

    def test_returns_cached_instance(self) -> None:
        assert get_system("5e") is get_system("5e")

    def test_unknown_system_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown system"):
            get_system("pathfinder")

    def test_get_system_for_corpus_with_stats(self) -> None:
        class Stats:
            system = "5e"

        class Corpus:
            stats = Stats()

        assert get_system_for_corpus(Corpus()).name == "5e"

    def test_get_system_for_corpus_without_stats_defaults_to_5e(self) -> None:
        class Corpus:
            stats = None

        assert get_system_for_corpus(Corpus()).name == "5e"
        assert get_system_for_corpus(None).name == "5e"

    def test_register_system_is_additive(self) -> None:
        class DummySystem(ResolutionSystem):
            name = "dummy"
            unarmed_damage = "1d4"
            default_weapon_damage = "2d4"

            def compute_modifier(self, v: int) -> int:
                return 0
            def roll_die(self, faces=20, advantage=False, disadvantage=False) -> int:
                return 1
            def roll_check(self, stat, stat_value, target, flat_modifier=0, params=None):
                return CheckResult(stat, target, 0, flat_modifier, flat_modifier, 1, 1, 1 - target, False, False, False)
            def roll_initiative(self, modifier: int) -> int:
                return 1
            def is_critical(self, roll: int) -> bool:
                return False
            def is_fumble(self, roll: int) -> bool:
                return False
            def roll_damage(self, expr, critical=False):
                return (0, "0")
            def base_ac(self, dex_value: int) -> int:
                return 10
            def base_max_hp(self, con_value: int) -> int:
                return 1
            def resolve_player_attack(self, hard, corpus, target_id, target_ac, round_number):
                return PlayerAttackResult(
                    hit=True,
                    damage=0,
                    target_hp_delta=0,
                    log_entries=[CombatLogEntry(round=round_number, actor="player", action="attack", target=target_id)],
                )
            def resolve_npc_attack(self, npc_id, hard, corpus, target_id, target_ac, round_number, attack=None):
                return NPCAttackResult(
                    hit=True,
                    damage=0,
                    target_hp_delta=0,
                    log_entries=[CombatLogEntry(round=round_number, actor=npc_id, action="attack", target=target_id)],
                )
            def resolve_flee(self, hard, corpus, flee_dc, round_number):
                return FleeResult(
                    success=True, roll=20, total=20, dc=flee_dc,
                    log_entries=[CombatLogEntry(round=round_number, actor="player", action="flee")],
                )
            def compute_player_ac(self, hard, corpus):
                return 10
            def compute_player_max_hp(self, hard, corpus):
                return 1
            def compute_player_initiative_modifier(self, hard, corpus):
                return 0

        register_system("dummy", DummySystem)
        try:
            inst = get_system("dummy")
            assert isinstance(inst, DummySystem)
            assert inst.unarmed_damage == "1d4"
        finally:
            from mgmai.engine.systems import _REGISTRY, _INSTANCES
            _REGISTRY.pop("dummy", None)
            _INSTANCES.pop("dummy", None)


# ------------------------------------------------------------------
# FiveESystem: modifiers & dice
# ------------------------------------------------------------------

class TestFiveEModifiers:
    @pytest.mark.parametrize("score,expected", [
        (1, -5), (3, -4), (8, -1), (9, -1), (10, 0),
        (11, 0), (12, 1), (14, 2), (16, 3), (18, 4), (20, 5),
    ])
    def test_compute_modifier(self, score, expected) -> None:
        assert FiveESystem().compute_modifier(score) == expected

    def test_roll_die_normal(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 13)
        assert FiveESystem().roll_die(20) == 13

    def test_roll_die_advantage_takes_higher(self, monkeypatch) -> None:
        vals = iter([4, 17])
        monkeypatch.setattr(random, "randint", lambda a, b: next(vals))
        assert FiveESystem().roll_die(20, advantage=True) == 17

    def test_roll_die_disadvantage_takes_lower(self, monkeypatch) -> None:
        vals = iter([4, 17])
        monkeypatch.setattr(random, "randint", lambda a, b: next(vals))
        assert FiveESystem().roll_die(20, disadvantage=True) == 4

    def test_roll_die_adv_and_disadv_cancel(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 9)
        assert FiveESystem().roll_die(20, advantage=True, disadvantage=True) == 9


# ------------------------------------------------------------------
# FiveESystem: checks
# ------------------------------------------------------------------

class TestFiveEChecks:
    def test_roll_check_success(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 15)
        cr = FiveESystem().roll_check("STR", 14, target=10, flat_modifier=0)
        assert isinstance(cr, CheckResult)
        assert cr.success is True
        assert cr.raw_roll == 15
        assert cr.computed_mod == 2
        assert cr.total == 17
        assert cr.margin == 7

    def test_roll_check_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 2)
        cr = FiveESystem().roll_check("STR", 10, target=20)
        assert cr.success is False
        assert cr.flat_mod == 0

    def test_roll_check_reads_flat_params(self, monkeypatch) -> None:
        vals = iter([5, 18])
        monkeypatch.setattr(random, "randint", lambda a, b: next(vals))
        cr = FiveESystem().roll_check(
            "DEX", 10, target=15, params={"advantage": True},
        )
        assert cr.advantage is True
        assert cr.raw_roll == 18  # higher of (5, 18)
        assert cr.success is True

    def test_to_dict_has_canonical_keys(self) -> None:
        d = CheckResult("STR", 10, 2, 0, 2, 8, 10, 0, True, False, False).to_dict()
        assert d["type"] == "stat_check"
        for key in ("stat", "target", "modifier", "computed_mod", "flat_mod",
                    "raw_roll", "total", "margin", "success",
                    "advantage", "disadvantage"):
            assert key in d


# ------------------------------------------------------------------
# FiveESystem: attack / damage / derived stats / saves
# ------------------------------------------------------------------

class TestFiveECombat:
    def test_crit_and_fumble(self) -> None:
        s = FiveESystem()
        assert s.is_critical(20) and not s.is_critical(19)
        assert s.is_fumble(1) and not s.is_fumble(2)

    def test_roll_damage_normal(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 3)
        total, _ = FiveESystem().roll_damage("1d6+2")
        assert total == 5

    def test_roll_damage_critical_doubles_dice(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 6)
        total, s = FiveESystem().roll_damage("1d6+2", critical=True)
        # 2 dice * 6 + 2 = 14, modifier applied once
        assert total == 14
        assert s.startswith("2d6+2")

    def test_roll_damage_half(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 5)
        total, s = FiveESystem().roll_damage("half(1d8)")
        assert total == 2  # max(1, 5 // 2)
        assert "half(" in s

    def test_roll_damage_half_minimum_one(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        total, _ = FiveESystem().roll_damage("half(1d8)")
        assert total == 1  # max(1, 1 // 2)

    def test_roll_damage_half_with_modifier(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 4)
        # half(2d6+3): total = 4+4+3 = 11 -> half = 5
        total, _ = FiveESystem().roll_damage("half(2d6+3)")
        assert total == 5

    def test_roll_damage_half_flat(self) -> None:
        total, _ = FiveESystem().roll_damage("half(4)")
        assert total == 2

    def test_roll_damage_nested_half(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 5)
        # half(half(1d8)) -> 5 -> 2 -> 1
        total, _ = FiveESystem().roll_damage("half(half(1d8))")
        assert total == 1

    def test_base_ac_and_hp(self) -> None:
        s = FiveESystem()
        assert s.base_ac(16) == 13   # 10 + 3
        assert s.base_ac(10) == 10
        assert s.base_max_hp(14) == 10  # 8 + 2
        assert s.base_max_hp(10) == 8   # 8 + 0

    def test_base_max_hp_floor(self) -> None:
        # CON 1 -> mod -5 -> 8-5 = 3 (still >= 1)
        assert FiveESystem().base_max_hp(1) == 3

    def test_compute_save_modifier_proficient(self) -> None:
        class FakePlayer:
            save_proficiencies = ["CON", "DEX"]
            proficiency_bonus = 3

        s = FiveESystem()
        assert s.compute_save_modifier("CON", FakePlayer()) == 3
        assert s.compute_save_modifier("DEX", FakePlayer()) == 3
        assert s.compute_save_modifier("STR", FakePlayer()) == 0

    def test_compute_save_modifier_default_prof_bonus(self) -> None:
        class FakePlayer:
            save_proficiencies = ["CON"]
            proficiency_bonus = None

        assert FiveESystem().compute_save_modifier("CON", FakePlayer()) == 2

    def test_compute_save_modifier_no_proficiencies(self) -> None:
        class FakePlayer:
            save_proficiencies = []
            proficiency_bonus = 2

        assert FiveESystem().compute_save_modifier("CON", FakePlayer()) == 0

    def test_save_to_dict(self) -> None:
        d = SaveResult("CON", 11, 2, 14, 16, 5, True, False, False).to_dict()
        assert d["type"] == "saving_throw"
        assert d["stat"] == "CON"

    def test_proficiency_bonus_applies_to_save_proficiency(self) -> None:
        class FakePlayer:
            save_proficiencies = ["CON"]
            proficiency_bonus = 3

        check = StatCheck(stat="CON", target=10, proficiency="save", repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 3

    def test_proficiency_bonus_ignored_without_marker(self) -> None:
        class FakePlayer:
            save_proficiencies = ["CON"]
            proficiency_bonus = 3

        check = StatCheck(stat="CON", target=10, repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 0

    def test_proficiency_bonus_non_proficient_player(self) -> None:
        class FakePlayer:
            save_proficiencies = []
            proficiency_bonus = 3

        check = StatCheck(stat="CON", target=10, proficiency="save", repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 0

    def test_default_damage_exprs(self) -> None:
        s = FiveESystem()
        assert s.unarmed_damage == "1d6"
        assert s.default_weapon_damage == "1d8"


# ------------------------------------------------------------------
# FiveESystem: skill checks
# ------------------------------------------------------------------

class TestFiveESkills:
    def test_skill_table_has_18_srd_skills(self) -> None:
        assert len(FiveESystem.SKILL_ABILITIES) == 18
        assert FiveESystem.SKILL_ABILITIES["acrobatics"] == "DEX"
        assert FiveESystem.SKILL_ABILITIES["athletics"] == "STR"
        assert FiveESystem.SKILL_ABILITIES["sleight of hand"] == "DEX"

    def test_stat_value_for_check_maps_skill_to_ability(self) -> None:
        class FakePlayer:
            stats = {"STR": 12, "DEX": 16}

        s = FiveESystem()
        assert s.stat_value_for_check("acrobatics", FakePlayer()) == 16
        assert s.stat_value_for_check("athletics", FakePlayer()) == 12

    def test_stat_value_for_check_skill_case_insensitive(self) -> None:
        class FakePlayer:
            stats = {"DEX": 14}

        assert FiveESystem().stat_value_for_check("Acrobatics", FakePlayer()) == 14

    def test_stat_value_for_check_skill_defaults_to_10(self) -> None:
        class FakePlayer:
            stats = {"STR": 12}

        assert FiveESystem().stat_value_for_check("acrobatics", FakePlayer()) == 10

    def test_stat_value_for_check_falls_back_to_stats(self) -> None:
        class FakePlayer:
            stats = {"STR": 12}

        s = FiveESystem()
        assert s.stat_value_for_check("STR", FakePlayer()) == 12
        assert s.stat_value_for_check("LUCK", FakePlayer()) is None

    def test_is_known_check_stat(self) -> None:
        s = FiveESystem()
        assert s.is_known_check_stat("acrobatics")
        assert s.is_known_check_stat("Sleight of Hand")
        assert not s.is_known_check_stat("STR")
        assert not s.is_known_check_stat("luck")

    def test_skill_modifier_proficient(self) -> None:
        class FakePlayer:
            skill_proficiencies = ["acrobatics", "Stealth"]
            proficiency_bonus = 3

        s = FiveESystem()
        assert s.skill_modifier("acrobatics", FakePlayer()) == 3
        assert s.skill_modifier("stealth", FakePlayer()) == 3  # case-insensitive
        assert s.skill_modifier("perception", FakePlayer()) == 0

    def test_skill_modifier_default_prof_bonus(self) -> None:
        class FakePlayer:
            skill_proficiencies = ["acrobatics"]
            proficiency_bonus = None

        assert FiveESystem().skill_modifier("acrobatics", FakePlayer()) == 2

    def test_skill_modifier_ignores_non_skills(self) -> None:
        class FakePlayer:
            skill_proficiencies = ["acrobatics"]
            proficiency_bonus = 3

        assert FiveESystem().skill_modifier("STR", FakePlayer()) == 0

    def test_proficiency_bonus_applies_to_skill_check(self) -> None:
        class FakePlayer:
            skill_proficiencies = ["acrobatics"]
            proficiency_bonus = 3

        check = StatCheck(stat="acrobatics", target=13, repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 3

    def test_proficiency_bonus_skill_not_proficient(self) -> None:
        class FakePlayer:
            skill_proficiencies = []
            proficiency_bonus = 3

        check = StatCheck(stat="acrobatics", target=13, repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 0

    def test_proficiency_bonus_save_branch_unaffected(self) -> None:
        class FakePlayer:
            save_proficiencies = ["CON"]
            skill_proficiencies = ["acrobatics"]
            proficiency_bonus = 3

        check = StatCheck(stat="CON", target=10, proficiency="save", repeatable=True)
        assert FiveESystem().proficiency_bonus(check, FakePlayer()) == 3


# ------------------------------------------------------------------
# dice.parse_damage_dice (re-exported via combat)
# ------------------------------------------------------------------

class TestParseDamageDice:
    def test_simple(self) -> None:
        assert parse_damage_dice("1d6") == (1, 6, 0)

    def test_with_mod(self) -> None:
        assert parse_damage_dice("2d4+3") == (2, 4, 3)
        assert parse_damage_dice("1d8-1") == (1, 8, -1)

    def test_invalid(self) -> None:
        with pytest.raises(ValueError):
            parse_damage_dice("not_dice")


# ------------------------------------------------------------------
# FiveESystem: player-derived combat stats (AC, HP, initiative, flee)
# ------------------------------------------------------------------

def _hard_player(stats=None, ac=None, max_hp=None, equipped=None, current_hp=None):
    """Minimal HardGameState for system-derived-stat tests."""
    return HardGameState.model_validate({
        "player": {
            "location": "room1",
            "stats": stats,
            "ac": ac,
            "max_hp": max_hp,
            "current_hp": current_hp,
            "equipped": equipped or [],
        },
    })


def _corpus_with_item(item_id, ac_override=None, ac_bonus=0):
    """Minimal corpus with one equippable item entity."""
    return ModuleCorpus.model_validate({
        "adventure": {"title": "T", "introduction": "T"},
        "rooms": {"room1": {"name": "R", "description": "D"}},
        "entities": {
            item_id: {
                "type": "item",
                "name": item_id,
                "description": "D",
                "equip_block": {
                    "equip_tags": ["armor"],
                    "ac_override": ac_override,
                    "ac_bonus": ac_bonus,
                },
            },
        },
    })


class TestFiveEPlayerDerivedStats:
    def test_compute_player_ac_explicit(self) -> None:
        s = FiveESystem()
        hard = _hard_player(stats={"DEX": 16}, ac=14)
        assert s.compute_player_ac(hard, _corpus_with_item("none")) == 14

    def test_compute_player_ac_from_dex(self) -> None:
        s = FiveESystem()
        # DEX 16 -> mod +3 -> 10 + 3 = 13
        hard = _hard_player(stats={"DEX": 16})
        assert s.compute_player_ac(hard, _corpus_with_item("none")) == 13

    def test_compute_player_ac_default_dex(self) -> None:
        s = FiveESystem()
        # No stats -> DEX defaults 10 -> AC 10
        hard = _hard_player(stats=None)
        assert s.compute_player_ac(hard, _corpus_with_item("none")) == 10

    def test_compute_player_ac_with_override(self) -> None:
        s = FiveESystem()
        hard = _hard_player(stats={"DEX": 16}, equipped=["armor"])
        corpus = _corpus_with_item("armor", ac_override=18)
        # override (18) wins over base (13)
        assert s.compute_player_ac(hard, corpus) == 18

    def test_compute_player_ac_with_bonus(self) -> None:
        s = FiveESystem()
        hard = _hard_player(stats={"DEX": 10}, equipped=["shield"])
        corpus = _corpus_with_item("shield", ac_bonus=2)
        # base 10 + bonus 2 = 12
        assert s.compute_player_ac(hard, corpus) == 12

    def test_compute_player_max_hp_explicit(self) -> None:
        s = FiveESystem()
        hard = _hard_player(max_hp=27)
        assert s.compute_player_max_hp(hard, _corpus_with_item("none")) == 27

    def test_compute_player_max_hp_from_con(self) -> None:
        s = FiveESystem()
        # CON 14 -> mod +2 -> 8 + 2 = 10
        hard = _hard_player(stats={"CON": 14})
        assert s.compute_player_max_hp(hard, _corpus_with_item("none")) == 10

    def test_compute_player_initiative_modifier(self) -> None:
        s = FiveESystem()
        # DEX 16 -> mod +3
        hard = _hard_player(stats={"DEX": 16})
        assert s.compute_player_initiative_modifier(hard, _corpus_with_item("none")) == 3

    def test_compute_player_initiative_modifier_default(self) -> None:
        s = FiveESystem()
        hard = _hard_player(stats=None)
        assert s.compute_player_initiative_modifier(hard, _corpus_with_item("none")) == 0

    def test_resolve_flee_success(self, monkeypatch) -> None:
        s = FiveESystem()
        monkeypatch.setattr(random, "randint", lambda a, b: 15)
        hard = _hard_player(stats={"DEX": 14})  # DEX mod +2
        # roll 15 + 2 = 17 >= 10
        result = s.resolve_flee(hard, _corpus_with_item("none"), flee_dc=10, round_number=1)
        assert result.success is True
        assert result.roll == 15
        assert result.total == 17
        assert result.dc == 10
        assert len(result.log_entries) == 1
        entry = result.log_entries[0]
        assert entry.actor == "player"
        assert entry.action == "flee"
        assert entry.hit is True
        assert entry.attack_roll == 15
        assert entry.attack_total == 17
        assert entry.ac == 10

    def test_resolve_flee_failure(self, monkeypatch) -> None:
        s = FiveESystem()
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        hard = _hard_player(stats={"DEX": 14})  # DEX mod +2
        # roll 1 + 2 = 3 < 10
        result = s.resolve_flee(hard, _corpus_with_item("none"), flee_dc=10, round_number=2)
        assert result.success is False
        assert result.total == 3
        assert result.log_entries[0].round == 2
        assert result.log_entries[0].hit is False


class TestFiveEEquipmentExtras:
    def test_two_handed_tag_with_explicit_incompatibilities(self) -> None:
        """Two-handed weapons use the 'two_handed' tag with explicit incompatible_with."""
        eb = EquipBlock(
            equip_tags=["weapon", "two_handed", "heavy"],
            incompatible_with=["shield", "handwear"],
        )
        assert "two_handed" in eb.equip_tags
        assert eb.incompatible_with == ["shield", "handwear"]

    def test_get_equip_incompatibilities_default_is_empty(self) -> None:
        """get_equip_incompatibilities returns empty by default (no two_handed magic)."""
        sys = FiveESystem()
        eb = EquipBlock(equip_tags=["weapon"])
        assert sys.get_equip_incompatibilities(eb) == set()
        eb2 = EquipBlock(equip_tags=["weapon", "two_handed"])
        assert sys.get_equip_incompatibilities(eb2) == set()
