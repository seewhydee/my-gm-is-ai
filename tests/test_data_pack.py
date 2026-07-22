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

"""Tests for the SRD data pack (Phase A): the pack loader, the shipped
conditions pack, and the new 5e ``system_effects`` keys the full SRD
condition list needs (``advantage_on_attack``, ``disadvantage_against``,
``auto_fail_str_dex_saves``, ``d20_test_modifier``)."""

from __future__ import annotations

from mgmai.datapack import load_pack
from mgmai.engine.resolver import _roll_stat_check
from mgmai.engine.systems.five_e import FiveESystem
from mgmai.models.corpus import (
    DEFAULT_STATUS_EFFECTS,
    StatCheck,
    StatusEffectDef,
)
from tests.helpers import (
    make_char_sheet_corpus,
    make_char_sheet_state,
    make_webs_hard_state,
    make_webs_test_corpus,
)

SRD_CONDITIONS = {
    "blinded", "charmed", "deafened", "frightened", "grappled",
    "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
    "prone", "restrained", "stunned", "unconscious",
}
EXHAUSTION_LEVELS = {f"exhaustion-{n}" for n in range(1, 7)}


class TestPackLoader:
    def test_conditions_pack_loads(self) -> None:
        raw = load_pack("5e", "conditions")
        assert SRD_CONDITIONS | EXHAUSTION_LEVELS <= set(raw)

    def test_every_pack_entry_parses(self) -> None:
        for effect_id, entry in load_pack("5e", "conditions").items():
            parsed = StatusEffectDef.model_validate(entry)
            assert parsed.name, effect_id
            assert parsed.description, effect_id

    def test_unknown_system_returns_empty(self) -> None:
        assert load_pack("gurps", "conditions") == {}

    def test_unknown_kind_returns_empty(self) -> None:
        assert load_pack("5e", "spelljammer") == {}


class TestDefaultStatusEffects:
    def test_defaults_come_from_pack(self) -> None:
        assert set(DEFAULT_STATUS_EFFECTS) == set(load_pack("5e", "conditions"))

    def test_full_srd_condition_list(self) -> None:
        assert SRD_CONDITIONS | EXHAUSTION_LEVELS <= set(DEFAULT_STATUS_EFFECTS)

    def test_legacy_defaults_preserved(self) -> None:
        poisoned = DEFAULT_STATUS_EFFECTS["poisoned"]
        assert poisoned.system_effects["5e"]["disadvantage_on_attack"] is True
        assert poisoned.system_effects["5e"]["disadvantage_on_ability_checks"] is True
        assert DEFAULT_STATUS_EFFECTS["stunned"].skip_turn is True
        assert DEFAULT_STATUS_EFFECTS["prone"].duration == "until_turn_start"

    def test_overlay_replaces_pack_entry_wholesale(self) -> None:
        corpus = make_char_sheet_corpus()
        corpus.status_effects["stunned"] = StatusEffectDef(name="Custom Stun")
        effective = corpus.effective_status_effects()
        assert effective["stunned"].name == "Custom Stun"
        assert effective["stunned"].skip_turn is False  # no field-level merge
        # Untouched pack entries still come through.
        assert "invisible" in effective


class TestAttackRollModsNewKeys:
    def test_invisible_attacker_has_advantage(self) -> None:
        corpus = make_char_sheet_corpus()
        assert FiveESystem().attack_roll_mods(
            {"invisible": 1}, {}, corpus
        ) == (True, False)

    def test_invisible_target_imposes_disadvantage(self) -> None:
        corpus = make_char_sheet_corpus()
        assert FiveESystem().attack_roll_mods(
            {}, {"invisible": 1}, corpus
        ) == (False, True)

    def test_blinded_target_grants_advantage(self) -> None:
        corpus = make_char_sheet_corpus()
        assert FiveESystem().attack_roll_mods(
            {}, {"blinded": 1}, corpus
        ) == (True, False)

    def test_blinded_attacker_has_disadvantage(self) -> None:
        corpus = make_char_sheet_corpus()
        assert FiveESystem().attack_roll_mods(
            {"blinded": 1}, {}, corpus
        ) == (False, True)

    def test_advantage_and_disadvantage_combine(self) -> None:
        corpus = make_char_sheet_corpus()
        # Attacker poisoned (disadv) striking a stunned target (adv).
        assert FiveESystem().attack_roll_mods(
            {"poisoned": 1}, {"stunned": 1}, corpus
        ) == (True, True)


class TestD20TestModifier:
    def test_exhaustion_level_scales_penalty(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        assert system.d20_test_modifier({"exhaustion-1": 1}, corpus) == -2
        assert system.d20_test_modifier({"exhaustion-4": 1}, corpus) == -8

    def test_sums_over_active_effects(self) -> None:
        corpus = make_char_sheet_corpus()
        corpus.status_effects["bleed"] = StatusEffectDef.model_validate({
            "name": "Bleed",
            "system_effects": {"5e": {"d20_test_modifier": -1}},
        })
        assert FiveESystem().d20_test_modifier(
            {"exhaustion-2": 1, "bleed": 1}, corpus
        ) == -5

    def test_no_effects_or_unknown_ids_give_zero(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        assert system.d20_test_modifier({}, corpus) == 0
        assert system.d20_test_modifier({"nonexistent": 1}, corpus) == 0
        assert system.d20_test_modifier({"poisoned": 1}, corpus) == 0

    def test_player_attack_total_includes_penalty(self) -> None:
        corpus = make_webs_test_corpus()
        hard = make_webs_hard_state()
        hard.player.status_effects["exhaustion-2"] = 1
        result = FiveESystem().resolve_player_attack(hard, corpus, "spider", 14, 1)
        # Unarmed: STR mod 0 + proficiency 2, then -4 from exhaustion.
        assert result.attack_total == result.attack_roll + 2 - 4


class TestSaveAutoFail:
    def test_stunned_auto_fails_str_and_dex(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        assert system.save_auto_fail("STR", {"stunned": 1}, corpus) is True
        assert system.save_auto_fail("dex", {"stunned": 1}, corpus) is True

    def test_other_abilities_unaffected(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        assert system.save_auto_fail("INT", {"stunned": 1}, corpus) is False
        assert system.save_auto_fail("CON", {"paralyzed": 1}, corpus) is False

    def test_conditions_without_the_key_do_not_auto_fail(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        assert system.save_auto_fail("STR", {"poisoned": 1}, corpus) is False
        assert system.save_auto_fail("STR", {}, corpus) is False

    def test_all_auto_fail_conditions(self) -> None:
        corpus = make_char_sheet_corpus()
        system = FiveESystem()
        for condition in ("paralyzed", "petrified", "stunned", "unconscious"):
            assert system.save_auto_fail("STR", {condition: 1}, corpus) is True, condition

    def test_resolver_save_auto_fails_without_roll(self) -> None:
        corpus = make_char_sheet_corpus()
        hard = make_char_sheet_state()
        hard.player.status_effects["paralyzed"] = 1
        check = StatCheck(stat="STR", target=1, save=True, repeatable=True)
        cr = _roll_stat_check(check, FiveESystem(), 10, hard, corpus)
        assert cr.success is False
        assert cr.raw_roll == 0  # no roll happened

    def test_resolver_non_save_check_still_rolls(self) -> None:
        corpus = make_char_sheet_corpus()
        hard = make_char_sheet_state()
        hard.player.status_effects["paralyzed"] = 1
        check = StatCheck(stat="STR", target=30, save=False, repeatable=True)
        cr = _roll_stat_check(check, FiveESystem(), 10, hard, corpus)
        assert cr.raw_roll >= 1

    def test_resolver_exhaustion_penalizes_check(self) -> None:
        corpus = make_char_sheet_corpus()
        hard = make_char_sheet_state()
        hard.player.status_effects["exhaustion-3"] = 1
        check = StatCheck(stat="INT", target=20, save=False, repeatable=True)
        cr = _roll_stat_check(check, FiveESystem(), 10, hard, corpus)
        assert cr.flat_mod == -6
        assert cr.total == cr.raw_roll - 6
