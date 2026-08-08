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

from pathlib import Path

from mgmai.datapack import load_pack
from mgmai.engine.resolver import _roll_stat_check
from mgmai.engine.systems.five_e import FiveESystem
from mgmai.models.corpus import (
    DEFAULT_SPELLS,
    DEFAULT_STATUS_EFFECTS,
    Ability,
    StatCheck,
    StatusEffectDef,
)
from mgmai.state.manager import StateManager
from tests.helpers import (
    build_state_manager,
    make_char_sheet_corpus,
    make_char_sheet_state,
    make_webs_hard_state,
    make_webs_test_corpus,
)

FIXTURES = Path(__file__).resolve().parent / "integration" / "fixtures"

SRD_CONDITIONS = {
    "blinded", "charmed", "deafened", "frightened", "grappled",
    "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
    "prone", "restrained", "stunned", "unconscious",
}
EXHAUSTION_LEVELS = {f"exhaustion-{n}" for n in range(1, 7)}
SRD_SPELL_IDS = {
    "fire_bolt", "sacred_flame", "cure_wounds", "magic_missile",
    "healing_word", "mage_armor", "sleep",
    # Cantrips (Tier 1 expansion).
    "chill_touch", "eldritch_blast", "produce_flame", "ray_of_frost",
    "shocking_grasp", "starry_wisp", "vicious_mockery",
    # Level 1 (Tier 1 + Tier 2).
    "charm_person", "chromatic_orb", "command", "dissonant_whispers",
    "faerie_fire", "guiding_bolt", "hideous_laughter", "inflict_wounds",
    "ray_of_sickness",
    # Level 2 (Tier 1 + Tier 2).
    "barkskin", "blindness_deafness", "blur", "hold_person",
    "invisibility", "mind_spike",
}


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


class TestSpellsPack:
    def test_spells_pack_loads(self) -> None:
        raw = load_pack("5e", "spells")
        assert SRD_SPELL_IDS <= set(raw)

    def test_every_entry_parses_as_ability(self) -> None:
        for spell_id, entry in load_pack("5e", "spells").items():
            parsed = Ability.model_validate(entry)
            assert parsed.name, spell_id
            assert parsed.spell_level is not None, spell_id

    def test_pack_spell_mechanics(self) -> None:
        fire_bolt = DEFAULT_SPELLS["fire_bolt"]
        assert fire_bolt.spell_level == 0
        assert fire_bolt.attack is not None
        assert fire_bolt.attack.damage == "1d10"
        assert fire_bolt.attack.damage_type == "fire"

        magic_missile = DEFAULT_SPELLS["magic_missile"]
        assert magic_missile.spell_level == 1
        assert magic_missile.auto_damage is not None
        assert magic_missile.auto_damage.damage_type == "force"

        mage_armor = DEFAULT_SPELLS["mage_armor"]
        assert mage_armor.target == "self"
        assert mage_armor.on_cast is not None
        assert mage_armor.on_cast.id == "mage_armor"

        sleep = DEFAULT_SPELLS["sleep"]
        assert sleep.concentration is True
        assert sleep.save is not None
        rider = sleep.save.apply_status_effect_on_failure
        assert rider is not None and rider.id == "incapacitated"

        # Tier 1 expansion: attack cantrips carry the pack's derived-attack
        # shape; 2024 Inflict Wounds is a CON save, not an attack roll.
        eldritch_blast = DEFAULT_SPELLS["eldritch_blast"]
        assert eldritch_blast.spell_level == 0
        assert eldritch_blast.attack is not None
        assert eldritch_blast.attack.damage == "1d10"
        assert eldritch_blast.attack.damage_type == "force"

        inflict_wounds = DEFAULT_SPELLS["inflict_wounds"]
        assert inflict_wounds.spell_level == 1
        assert inflict_wounds.save is not None
        assert inflict_wounds.save.stat == "CON"
        assert inflict_wounds.save.damage == "2d10"

        # Concentration + save-status spells keep the Sleep pattern.
        hold_person = DEFAULT_SPELLS["hold_person"]
        assert hold_person.concentration is True
        assert hold_person.sustained_status_effects == ["paralyzed"]
        hold_rider = hold_person.save.apply_status_effect_on_failure
        assert hold_rider is not None and hold_rider.id == "paralyzed"

        # Tier 2: on_cast buff spells with their new pack conditions.
        barkskin = DEFAULT_SPELLS["barkskin"]
        assert barkskin.casting_time == "bonus_action"
        assert barkskin.on_cast is not None and barkskin.on_cast.id == "barkskin"
        assert barkskin.concentration is False

        invisibility = DEFAULT_SPELLS["invisibility"]
        assert invisibility.on_cast is not None
        assert invisibility.on_cast.id == "invisible"
        assert invisibility.sustained_status_effects == ["invisible"]

        blur = DEFAULT_SPELLS["blur"]
        assert blur.target == "self"
        assert blur.on_cast is not None and blur.on_cast.id == "blur"

    def test_mage_armor_condition_in_pack(self) -> None:
        cond = DEFAULT_STATUS_EFFECTS["mage_armor"]
        assert cond.scope == "persistent"
        assert cond.duration == "until_cleared"
        assert cond.system_effects["5e"]["ac_base"] == 13

    def test_tier2_conditions_in_pack(self) -> None:
        # Barkskin mirrors mage_armor (persistent AC replacement); a long
        # rest clears every persistent-scope status, so it ends there too.
        barkskin = DEFAULT_STATUS_EFFECTS["barkskin"]
        assert barkskin.scope == "persistent"
        assert barkskin.duration == "until_cleared"
        assert barkskin.system_effects["5e"]["ac_base"] == 17

        # Blur / faerie fire are combat-scoped concentration riders using
        # the engine's existing roll-modifier keys.
        blur = DEFAULT_STATUS_EFFECTS["blur"]
        assert blur.system_effects["5e"]["disadvantage_against"] is True

        faerie_fire = DEFAULT_STATUS_EFFECTS["faerie_fire"]
        assert faerie_fire.system_effects["5e"]["advantage_against"] is True


class TestEffectiveSpells:
    def test_includes_pack_and_corpus_spells(self) -> None:
        corpus = make_char_sheet_corpus()
        corpus.abilities["guiding_bolt"] = Ability(
            name="Guiding Bolt", target="enemy", spell_level=1,
            attack={"stat": "WIS", "damage": "4d6", "damage_type": "radiant"},
        )
        spells = corpus.effective_spells()
        assert "fire_bolt" in spells      # from the pack
        assert "guiding_bolt" in spells   # from the corpus

    def test_corpus_spell_replaces_pack_entry_wholesale(self) -> None:
        corpus = make_char_sheet_corpus()
        custom = Ability(
            name="Greater Fire Bolt", target="enemy", spell_level=0,
            attack={"stat": "CHA", "damage": "2d10", "damage_type": "fire"},
        )
        corpus.abilities["fire_bolt"] = custom
        spells = corpus.effective_spells()
        assert spells["fire_bolt"] is custom  # no field-level merge
        # Untouched pack entries still come through.
        assert "sleep" in spells

    def test_non_spell_abilities_excluded(self) -> None:
        corpus = make_char_sheet_corpus()
        corpus.abilities["slash"] = Ability(
            name="Slash", target="enemy",
            attack={"stat": "STR", "damage": "1d8"},
        )
        assert "slash" not in corpus.effective_spells()


class TestPackSpellMaterialization:
    def test_pack_spells_minted_at_load(self) -> None:
        sm = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        assert "fire_bolt" in sm.corpus.abilities
        assert "magic_missile" in sm.corpus.abilities
        assert sm.corpus.abilities["fire_bolt"].spell_level == 0

    def test_corpus_ability_wins_over_pack_template(self) -> None:
        # A corpus-defined ability with a pack ID is kept as-is when pack
        # spells are materialized (wholesale replace, corpus wins).
        corpus = make_char_sheet_corpus()
        custom = Ability(
            name="Fire Bolt", target="enemy",
            attack={"stat": "INT", "damage": "1d10", "damage_type": "fire"},
        )
        corpus.abilities["fire_bolt"] = custom
        sm = build_state_manager(corpus)
        sm._materialize_pack_spells()
        assert sm.corpus.abilities["fire_bolt"] is custom
        assert "magic_missile" in sm.corpus.abilities  # untouched IDs minted

    def test_materialized_abilities_are_independent_copies(self) -> None:
        sm1 = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        assert sm1.corpus.abilities["fire_bolt"].attack is not None
        sm1.corpus.abilities["fire_bolt"].attack.damage = "9d9"
        sm2 = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        assert sm2.corpus.abilities["fire_bolt"].attack is not None
        assert sm2.corpus.abilities["fire_bolt"].attack.damage == "1d10"
        assert DEFAULT_SPELLS["fire_bolt"].attack is not None
        assert DEFAULT_SPELLS["fire_bolt"].attack.damage == "1d10"
