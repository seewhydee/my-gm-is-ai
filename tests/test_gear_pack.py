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

"""Tests for the SRD gear data pack (Phase B): the pack itself, the
``effective_gear`` overlay, and load-time materialization of pack items
into ``corpus.entities``."""

from __future__ import annotations

from pathlib import Path

from mgmai.datapack import load_pack
from mgmai.engine.systems.five_e import FiveESystem
from mgmai.models.corpus import DEFAULT_GEAR, Entity
from mgmai.state.manager import StateManager
from tests.helpers import make_char_sheet_corpus

FIXTURES = Path(__file__).resolve().parent / "integration" / "fixtures"

WEAPON_IDS = {
    # Simple melee
    "club", "dagger", "greatclub", "handaxe", "javelin", "light_hammer",
    "mace", "quarterstaff", "sickle", "spear",
    # Simple ranged
    "light_crossbow", "dart", "shortbow", "sling",
    # Martial melee
    "battleaxe", "flail", "glaive", "greataxe", "greatsword", "halberd",
    "lance", "longsword", "maul", "morningstar", "pike", "rapier",
    "scimitar", "shortsword", "trident", "war_pick", "warhammer", "whip",
    # Martial ranged
    "blowgun", "hand_crossbow", "heavy_crossbow", "longbow", "musket",
    "pistol",
}
ARMOR_IDS = {
    "padded_armor", "leather_armor", "studded_leather_armor",
    "hide_armor", "chain_shirt", "scale_mail", "breastplate",
    "half_plate_armor", "ring_mail", "chain_mail", "splint_armor",
    "plate_armor", "shield",
}
CONSUMABLE_IDS = {
    "potion_of_healing", "potion_of_greater_healing",
    "potion_of_superior_healing", "potion_of_supreme_healing",
}


class TestGearPack:
    def test_every_entry_parses_as_item_entity(self) -> None:
        raw = load_pack("5e", "gear")
        assert raw, "gear pack is empty"
        for gear_id, entry in raw.items():
            entity = Entity.model_validate(entry)
            assert entity.type == "item", gear_id
            assert entity.name, gear_id
            assert entity.description, gear_id

    def test_full_srd_weapon_table(self) -> None:
        assert WEAPON_IDS <= set(DEFAULT_GEAR)
        for gear_id in WEAPON_IDS:
            block = DEFAULT_GEAR[gear_id].equip_block
            assert block is not None, gear_id
            assert "weapon" in block.equip_tags, gear_id
            assert block.damage_expr, gear_id
            assert block.damage_type, gear_id

    def test_every_weapon_has_one_proficiency_category(self) -> None:
        # Each SRD weapon carries exactly one of "simple"/"martial" in its
        # equip_tags, so weapon proficiency gating can key off it.
        for gear_id in WEAPON_IDS:
            etags = DEFAULT_GEAR[gear_id].equip_block.equip_tags
            cats = {"simple", "martial"} & set(etags)
            assert len(cats) == 1, f"{gear_id} must have one category, got {etags}"

    def test_weapon_category_counts_match_srd(self) -> None:
        from collections import Counter
        counts = Counter()
        for gear_id in WEAPON_IDS:
            etags = set(DEFAULT_GEAR[gear_id].equip_block.equip_tags)
            if "martial" in etags:
                counts["martial"] += 1
            else:
                counts["simple"] += 1
        # SRD: 24 martial, 14 simple weapons.
        assert counts == {"martial": 24, "simple": 14}

    def test_full_srd_armor_table(self) -> None:
        assert ARMOR_IDS <= set(DEFAULT_GEAR)
        for gear_id in ARMOR_IDS:
            assert DEFAULT_GEAR[gear_id].equip_block is not None, gear_id

    def test_spot_checks_against_srd(self) -> None:
        longsword = DEFAULT_GEAR["longsword"].equip_block
        assert longsword.damage_expr == "1d8"
        assert longsword.damage_type == "slashing"
        assert "versatile" in longsword.properties

        greatsword = DEFAULT_GEAR["greatsword"].equip_block
        assert greatsword.damage_expr == "2d6"
        assert "two_handed" in greatsword.equip_tags
        assert "shield" in greatsword.incompatible_with

        rapier = DEFAULT_GEAR["rapier"].equip_block
        assert "finesse" in rapier.properties

        longbow = DEFAULT_GEAR["longbow"].equip_block
        assert "ranged" in longbow.properties
        assert longbow.damage_expr == "1d8"

        plate = DEFAULT_GEAR["plate_armor"].equip_block
        assert getattr(plate, "ac_override") == 18
        leather = DEFAULT_GEAR["leather_armor"].equip_block
        assert getattr(leather, "ac_bonus", 0) == 1
        shield = DEFAULT_GEAR["shield"].equip_block
        assert getattr(shield, "ac_bonus", 0) == 2

        potion = DEFAULT_GEAR["potion_of_healing"].consumable
        assert potion.heal == "2d4+2"
        assert potion.destroy is True


class TestEffectiveGear:
    def test_includes_pack_and_corpus_items(self) -> None:
        corpus = make_char_sheet_corpus()  # has the corpus item toenail_sword
        gear = corpus.effective_gear()
        assert "longsword" in gear          # from the pack
        assert "toenail_sword" in gear      # from the corpus

    def test_corpus_item_replaces_pack_entry_wholesale(self) -> None:
        corpus = make_char_sheet_corpus()
        custom = Entity.model_validate({
            "type": "item",
            "name": "Sun Blade",
            "description": "A radiant longsword.",
            "tags": ["weapon"],
            "equip_block": {
                "equip_tags": ["weapon"],
                "damage_expr": "1d10",
                "damage_type": "radiant",
            },
        })
        corpus.entities["longsword"] = custom
        gear = corpus.effective_gear()
        assert gear["longsword"] is custom  # no field-level merge


class TestPackGearMaterialization:
    def test_pack_items_minted_at_load(self) -> None:
        # The combat_arena fixture references longsword/potion_of_healing
        # without declaring them; they come from the pack.
        sm = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        assert "longsword" in sm.corpus.entities
        assert "potion_of_healing" in sm.corpus.entities
        # Unreferenced pack gear is available too.
        assert "plate_armor" in sm.corpus.entities

    def test_pack_weapon_drives_player_attack(self) -> None:
        sm = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        system = FiveESystem()
        # STR 16 (+3) with the pack longsword (1d8).
        assert system.compute_player_damage_expr(sm.hard_state, sm.corpus) == "1d8+3"
        # Attack bonus: +3 STR, +2 proficiency, +0 hit_bonus.
        assert system.compute_player_attack_bonus(sm.hard_state, sm.corpus) == 5

    def test_corpus_entity_wins_over_pack_template(self) -> None:
        # A corpus-defined entity with a pack ID is kept as-is when pack
        # gear is materialized (wholesale replace, corpus wins).
        corpus = make_char_sheet_corpus()
        custom = Entity.model_validate({
            "type": "item",
            "name": "Sun Blade",
            "description": "A radiant longsword.",
            "tags": ["weapon"],
            "equip_block": {
                "equip_tags": ["weapon"],
                "damage_expr": "1d10",
                "damage_type": "radiant",
            },
        })
        corpus.entities["longsword"] = custom
        from tests.helpers import build_state_manager

        sm = build_state_manager(corpus)
        sm._materialize_pack_gear()
        assert sm.corpus.entities["longsword"] is custom
        assert "plate_armor" in sm.corpus.entities  # untouched IDs minted

    def test_materialized_entities_are_independent_copies(self) -> None:
        sm1 = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        sm1.corpus.entities["longsword"].equip_block.hit_bonus = 3
        sm2 = StateManager(adventure_dir=str(FIXTURES / "combat_arena"))
        assert sm2.corpus.entities["longsword"].equip_block.hit_bonus == 0
        assert DEFAULT_GEAR["longsword"].equip_block.hit_bonus == 0

    def test_unknown_item_ids_still_fail_validation(self) -> None:
        import json
        import shutil
        import tempfile

        src = FIXTURES / "combat_arena"
        dst = Path(tempfile.mkdtemp()) / "arena"
        shutil.copytree(src, dst)
        player_path = dst / "default-player.json"
        data = json.loads(player_path.read_text())
        data["player"]["inventory"]["excalibur"] = 1
        player_path.write_text(json.dumps(data))

        sm = StateManager()
        try:
            sm.load_all(dst)
            raise AssertionError("expected load_all to reject unknown item")
        except ValueError as e:
            assert "excalibur" in str(e)
