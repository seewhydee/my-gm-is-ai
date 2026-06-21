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
    FiveESystem,
    ResolutionSystem,
    SaveResult,
    get_system,
    get_system_for_corpus,
    register_system,
)
from mgmai.engine.systems.dice import parse_damage_dice


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
            def roll_check(self, stat, stat_value, dc, flat_modifier=0, params=None):
                return CheckResult(stat, dc, 0, flat_modifier, flat_modifier, 1, 1, 1 - dc, False, False, False)
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
            def resolve_save(self, stat, stat_value, dc, flat_modifier=0, params=None):
                return SaveResult(stat, dc, 0, 1, 1, 1 - dc, False, False, False)

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
        cr = FiveESystem().roll_check("STR", 14, dc=10, flat_modifier=0)
        assert isinstance(cr, CheckResult)
        assert cr.success is True
        assert cr.raw_roll == 15
        assert cr.computed_mod == 2
        assert cr.total == 17
        assert cr.margin == 7

    def test_roll_check_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 2)
        cr = FiveESystem().roll_check("STR", 10, dc=20)
        assert cr.success is False
        assert cr.flat_mod == 0

    def test_roll_check_reads_params_under_system_name(self, monkeypatch) -> None:
        vals = iter([5, 18])
        monkeypatch.setattr(random, "randint", lambda a, b: next(vals))
        cr = FiveESystem().roll_check(
            "DEX", 10, dc=15, params={"5e": {"advantage": True}},
        )
        assert cr.advantage is True
        assert cr.raw_roll == 18  # higher of (5, 18)
        assert cr.success is True

    def test_to_dict_has_canonical_keys(self) -> None:
        d = CheckResult("STR", 10, 2, 0, 2, 8, 10, 0, True, False, False).to_dict()
        assert d["type"] == "stat_check"
        for key in ("stat", "dc", "modifier", "computed_mod", "flat_mod",
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

    def test_base_ac_and_hp(self) -> None:
        s = FiveESystem()
        assert s.base_ac(16) == 13   # 10 + 3
        assert s.base_ac(10) == 10
        assert s.base_max_hp(14) == 10  # 8 + 2
        assert s.base_max_hp(10) == 8   # 8 + 0

    def test_base_max_hp_floor(self) -> None:
        # CON 1 -> mod -5 -> 8-5 = 3 (still >= 1)
        assert FiveESystem().base_max_hp(1) == 3

    def test_resolve_save_with_flat_modifier(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 18)
        sr = FiveESystem().resolve_save("CON", 14, dc=15, flat_modifier=2)
        assert isinstance(sr, SaveResult)
        # 18 + 2 (CON) + 2 (flat) = 22 >= 15
        assert sr.success is True
        assert sr.modifier == 4

    def test_resolve_save_without_flat_modifier(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        sr = FiveESystem().resolve_save("CON", 14, dc=15, flat_modifier=0)
        # 10 + 2 (CON) = 12 < 15
        assert sr.success is False
        assert sr.modifier == 2

    def test_save_to_dict(self) -> None:
        d = SaveResult("CON", 11, 2, 14, 16, 5, True, False, False).to_dict()
        assert d["type"] == "saving_throw"
        assert d["stat"] == "CON"

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

    def test_default_damage_exprs(self) -> None:
        s = FiveESystem()
        assert s.unarmed_damage == "1d6"
        assert s.default_weapon_damage == "1d8"


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
