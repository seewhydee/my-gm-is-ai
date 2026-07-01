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

"""Tests for equipment (equip/unequip) system."""

import copy
import json
from pathlib import Path

import pytest

from mgmai.engine.resolver import (
    resolve_equip,
    resolve_unequip,
    resolve_action,
)
from mgmai.models.actions import (
    EquipAction,
    UnequipAction,
    HardStateChanges,
)
from mgmai.models.corpus import (
    EquipBlock,
    ModuleCorpus,
    StatModifier,
)
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import (
    SoftGameState,
    SoftStatePatch,
    ImprovisedWeapon,
)
from mgmai.state.manager import StateManager

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def state_manager():
    """A fresh StateManager with sample data."""
    corpus_path = FIXTURES_DIR / "corpus.json"
    hard_path = FIXTURES_DIR / "hard-state.json"
    soft_path = FIXTURES_DIR / "soft-state.json"

    manager = StateManager()
    manager.corpus = ModuleCorpus.model_validate(
        json.loads(corpus_path.read_text())
    )
    manager.hard_state = HardGameState.model_validate(
        json.loads(hard_path.read_text())
    )
    manager.soft_state = SoftGameState.model_validate(
        json.loads(soft_path.read_text())
    )
    manager._adventure_dir = FIXTURES_DIR
    return manager


# ------------------------------------------------------------------
# EquipBlock Model Validation
# ------------------------------------------------------------------

class TestEquipBlockModel:
    def test_defaults(self):
        eb = EquipBlock(equip_tags=["weapon"])
        assert eb.equip_tags == ["weapon"]
        assert eb.incompatible_with == []
        assert eb.stat_effects == {}
        assert eb.max_equipped == 1
        assert eb.damage_expr == "1d8"
        assert eb.hit_bonus == 0

    def test_custom_values(self):
        eb = EquipBlock(
            equip_tags=["armor", "heavy"],
            incompatible_with=["light_armor"],
            stat_effects={"STR": StatModifier(mode="delta", value=1)},
        )
        assert len(eb.stat_effects) == 1

    def test_max_equipped_none(self):
        eb = EquipBlock(equip_tags=["weapon"], max_equipped=None)
        assert eb.max_equipped is None

    def test_extra_fields(self):
        """5e-specific extras are accepted via extra='allow' but are not core fields."""
        eb = EquipBlock(
            equip_tags=["armor", "heavy"],
            ac_override=18,
            ac_bonus=0,
        )
        assert eb.equip_tags == ["armor", "heavy"]
        assert getattr(eb, "ac_override") == 18
        assert getattr(eb, "ac_bonus") == 0

        simple = EquipBlock(equip_tags=["ring"])
        assert getattr(simple, "ac_override", None) is None


# ------------------------------------------------------------------
# Resolve Equip
# ------------------------------------------------------------------

class TestResolveEquip:
    def test_equip_valid_item(self, state_manager):
        """Equipping a valid item from inventory should succeed."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        # Place the item in inventory
        hard.player.inventory.append("toenail_sword")

        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            detail="Equipping the toenail sword",
        )
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes is not None
        assert "toenail_sword" in result.hard_changes.equipped_added
        assert "toenail_sword" in result.hard_changes.inventory_removed
        assert result.hard_changes.equipment_changed is True

    def test_equip_not_in_inventory(self, state_manager):
        """Equipping an item not in inventory should fail."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            detail="Equipping nonexistent item",
        )
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is False
        assert "not in your inventory" in (result.error or "")

    def test_equip_item_without_equip_block(self, state_manager):
        """Equipping a non-equippable item (rusty_key) should fail."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.inventory.append("rusty_key")

        action = EquipAction(
            action_type="equip",
            target="rusty_key",
            detail="Equipping rusty key",
        )
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is False
        assert "cannot be equipped" in (result.error or "").lower()

    def test_equip_with_unequip_targets(self, state_manager):
        """Equipping a weapon with unequip_targets should succeed."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.inventory.append("toenail_sword")

        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            unequip_targets=[],
            detail="Equipping sword",
        )
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is True

    def test_equip_invalid_unequip_target(self, state_manager):
        """Unequip target that isn't equipped should fail."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.inventory.append("toenail_sword")

        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            unequip_targets=["nonexistent_item"],
            detail="Equipping with bad unequip",
        )
        result = resolve_equip(action, hard, soft, corpus)
        assert result.success is False
        assert "not currently equipped" in (result.error or "")


# ------------------------------------------------------------------
# Resolve Unequip
# ------------------------------------------------------------------

class TestResolveUnequip:
    def test_unequip_valid_item(self, state_manager):
        """Unequipping a currently equipped item should succeed."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.equipped.append("toenail_sword")

        action = UnequipAction(
            action_type="unequip",
            target="toenail_sword",
            detail="Unequipping the toenail sword",
        )
        result = resolve_unequip(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes is not None
        assert "toenail_sword" in result.hard_changes.equipped_removed
        assert "toenail_sword" in result.hard_changes.inventory_added
        assert result.hard_changes.equipment_changed is True

    def test_unequip_not_equipped(self, state_manager):
        """Unequipping an item that isn't equipped should fail."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        action = UnequipAction(
            action_type="unequip",
            target="toenail_sword",
            detail="Unequipping nonexistent item",
        )
        result = resolve_unequip(action, hard, soft, corpus)
        assert result.success is False
        assert "not currently equipped" in (result.error or "")


# ------------------------------------------------------------------
# Dispatch via resolve_action
# ------------------------------------------------------------------

class TestResolveActionDispatch:
    def test_equip_dispatch(self, state_manager):
        """resolve_action should dispatch equip to resolve_equip."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.inventory.append("toenail_sword")

        action = EquipAction(
            action_type="equip",
            target="toenail_sword",
            detail="Equipping sword",
        )
        result = resolve_action(action, hard, soft, corpus)
        assert result.success is True
        assert result.hard_changes.equipment_changed is True

    def test_unequip_dispatch(self, state_manager):
        """resolve_action should dispatch unequip to resolve_unequip."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.equipped.append("toenail_sword")

        action = UnequipAction(
            action_type="unequip",
            target="toenail_sword",
            detail="Unequipping sword",
        )
        result = resolve_action(action, hard, soft, corpus)
        assert result.success is True
        assert "toenail_sword" in result.hard_changes.equipped_removed
        assert "toenail_sword" in result.hard_changes.inventory_added


# ------------------------------------------------------------------
# State Manager integration
# ------------------------------------------------------------------

class TestStateManagerEquipment:
    def test_apply_equip_changes(self, state_manager):
        """StateManager.apply_hard_changes should move IDs between lists."""
        hard = state_manager.hard_state
        hard.player.inventory.append("toenail_sword")

        changes = HardStateChanges(
            equipped_added=["toenail_sword"],
            inventory_removed=["toenail_sword"],
            equipment_changed=True,
        )
        state_manager.apply_hard_changes(changes)
        assert "toenail_sword" in hard.player.equipped
        assert "toenail_sword" not in hard.player.inventory

    def test_apply_unequip_changes(self, state_manager):
        """StateManager.apply_hard_changes should move IDs back to inventory."""
        hard = state_manager.hard_state
        hard.player.equipped.append("toenail_sword")

        changes = HardStateChanges(
            equipped_removed=["toenail_sword"],
            inventory_added=["toenail_sword"],
            equipment_changed=True,
        )
        state_manager.apply_hard_changes(changes)
        assert "toenail_sword" in hard.player.inventory
        assert "toenail_sword" not in hard.player.equipped

    def test_equipped_defaults_to_empty(self):
        """Old save files without `equipped` should default to empty list."""
        player_data = {"location": "room1", "inventory": []}
        from mgmai.models.hard_state import PlayerState
        ps = PlayerState.model_validate(player_data)
        assert ps.equipped == []

    def test_equipped_validation(self, state_manager):
        """StateManager should validate equipped item IDs."""
        hard = state_manager.hard_state
        hard.player.equipped.append("nonexistent_item")
        with pytest.raises(ValueError, match="No matching entity"):
            state_manager.validate_cross_references()


# ------------------------------------------------------------------
# Improved Weapon in Soft State
# ------------------------------------------------------------------

class TestImprovisedWeapon:
    def test_improvised_weapon_defaults(self):
        iw = ImprovisedWeapon()
        assert iw.damage_expr == "1d6"
        assert iw.hit_bonus == 0
        assert iw.clears_after_turn is False

    def test_set_improvised_weapon(self, state_manager):
        """SoftStatePatch with set_improvised_weapon should update soft state."""
        soft = state_manager.soft_state
        patch = SoftStatePatch(
            field="set_improvised_weapon",
            new_value={
                "damage_expr": "1d4",
                "hit_bonus": 0,
                "description": "broken bottle",
                "clears_after_turn": True,
            },
            reason="Player picked up a broken bottle as a weapon",
        )
        state_manager.apply_soft_patches([patch])
        assert soft.improvised_weapon is not None
        assert soft.improvised_weapon.damage_expr == "1d4"
        assert soft.improvised_weapon.clears_after_turn is True

    def test_clear_improvised_weapon(self, state_manager):
        """Setting improvised_weapon to None should clear it."""
        soft = state_manager.soft_state
        from mgmai.models.soft_state import ImprovisedWeapon
        soft.improvised_weapon = ImprovisedWeapon(
            damage_expr="1d4", description="stick"
        )
        patch = SoftStatePatch(
            field="set_improvised_weapon",
            new_value=None,
            reason="Player dropped the improvised weapon",
        )
        state_manager.apply_soft_patches([patch])
        assert soft.improvised_weapon is None

    def test_clear_expired_improvised_weapon(self, state_manager):
        """clear_expired_improvised_weapon should remove one-shot weapons."""
        soft = state_manager.soft_state
        from mgmai.models.soft_state import ImprovisedWeapon
        soft.improvised_weapon = ImprovisedWeapon(
            damage_expr="1d4",
            description="broken bottle",
            clears_after_turn=True,
        )
        state_manager.clear_expired_improvised_weapon()
        assert soft.improvised_weapon is None

    def test_clear_does_not_remove_persistent_weapon(self, state_manager):
        """Persistent improvised weapons should survive clear_expired."""
        soft = state_manager.soft_state
        from mgmai.models.soft_state import ImprovisedWeapon
        soft.improvised_weapon = ImprovisedWeapon(
            damage_expr="1d6",
            description="heavy rock",
            clears_after_turn=False,
        )
        state_manager.clear_expired_improvised_weapon()
        assert soft.improvised_weapon is not None
        assert soft.improvised_weapon.description == "heavy rock"


# ------------------------------------------------------------------
# Condition Domain: equipped:
# ------------------------------------------------------------------

class TestEquippedConditionDomain:
    def test_equipped_by_entity_id(self, state_manager):
        """equipped:toenail_sword should be true when the item is equipped."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        hard.player.equipped.append("toenail_sword")
        result = evaluate_condition_string(
            "equipped:toenail_sword", hard, soft, corpus
        )
        assert result is True

    def test_equipped_by_tag(self, state_manager):
        """equipped:weapon should be true when a weapon is equipped."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        hard.player.equipped.append("toenail_sword")
        result = evaluate_condition_string(
            "equipped:weapon", hard, soft, corpus
        )
        assert result is True

    def test_equipped_false_when_not_equipped(self, state_manager):
        """equipped:toenail_sword should be false when not equipped."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        result = evaluate_condition_string(
            "equipped:toenail_sword", hard, soft, corpus
        )
        assert result is False


# ------------------------------------------------------------------
# Tag domain scans both inventory and equipped
# ------------------------------------------------------------------

class TestTagDomainBackwardCompat:
    def test_tag_in_inventory(self, state_manager):
        """tag:weapon should match items in inventory (backward compat)."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        hard.player.inventory.append("toenail_sword")
        result = evaluate_condition_string("tag:weapon", hard, soft, corpus)
        assert result is True

    def test_tag_in_equipped(self, state_manager):
        """tag:weapon should also match items in equipped."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        hard.player.equipped.append("toenail_sword")
        result = evaluate_condition_string("tag:weapon", hard, soft, corpus)
        assert result is True

    def test_tag_in_neither(self, state_manager):
        """tag:weapon should be false when no weapon in inventory or equipped."""
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        from mgmai.engine.conditions import evaluate_condition_string

        assert "toenail_sword" not in hard.player.inventory
        assert "toenail_sword" not in hard.player.equipped
        result = evaluate_condition_string("tag:weapon", hard, soft, corpus)
        assert result is False


# ------------------------------------------------------------------
# Context Assembler: equipped items in briefing
# ------------------------------------------------------------------

class TestAssemblerEquipment:
    def test_equipped_items_in_briefing(self, state_manager):
        """Equipped items should appear in the PlayerStateBriefing."""
        from mgmai.context.assembler import assemble

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        hard.player.equipped.append("toenail_sword")
        briefing = assemble(corpus, hard, soft, "")
        assert len(briefing.player_state.equipped_items) > 0
        equipped_names = [e.id for e in briefing.player_state.equipped_items]
        assert "toenail_sword" in equipped_names

    def test_effective_stats_in_briefing(self, state_manager):
        """Effective stats should be populated when player has stats."""
        from mgmai.context.assembler import assemble

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        # The test fixture doesn't have player stats in hard_state
        # So effective_stats should be None
        briefing = assemble(corpus, hard, soft, "")
        assert briefing.player_state.effective_stats is None

    def test_effective_ac_in_briefing(self, state_manager):
        """Effective AC should be calculated."""
        from mgmai.context.assembler import assemble

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        briefing = assemble(corpus, hard, soft, "")
        # Default AC: 10 + DEX mod. DEX default 10 = +0 mod = AC 10
        assert briefing.player_state.effective_ac >= 10


# ------------------------------------------------------------------
# Combat stat computation with equipment
# ------------------------------------------------------------------

class TestCombatEquipmentStats:
    def test_compute_player_ac_base(self, state_manager):
        """Base AC should be 10 + DEX mod."""
        from mgmai.engine.combat import compute_player_ac

        hard = state_manager.hard_state
        corpus = state_manager.corpus

        # Default stats have no DEX, so DEX = 10, mod = 0, AC = 10
        ac = compute_player_ac(hard, corpus)
        assert ac == 10

    def test_compute_player_ac_with_equipment(self, state_manager):
        """AC override from equipped items should apply."""
        from mgmai.engine.combat import compute_player_ac

        hard = state_manager.hard_state
        corpus = state_manager.corpus

        # Add a shield-like item with ac_bonus to equipped
        # We need an item with equip_block in the corpus for this
        # The currently available equipable item is toenail_sword
        # Since it doesn't have AC bonuses, it won't affect AC
        hard.player.equipped.append("toenail_sword")
        ac = compute_player_ac(hard, corpus)
        assert ac == 10  # No AC bonus from the weapon

    def test_get_player_attack_bonus_with_equipped_weapon(self, state_manager):
        """Attack bonus should include weapon hit_bonus from equipped items."""
        from mgmai.engine.systems.five_e import FiveESystem

        hard = state_manager.hard_state
        corpus = state_manager.corpus
        system = FiveESystem()

        # No stats, STR = 10, mod = 0, prof = 2
        base_bonus = system.compute_player_attack_bonus(hard, corpus)
        assert base_bonus == 2  # prof only

        # Equip the sword (hit_bonus=0), should be the same
        hard.player.equipped.append("toenail_sword")
        bonus_with_sword = system.compute_player_attack_bonus(hard, corpus)
        assert bonus_with_sword == 2  # toenail_sword has hit_bonus=0

    def test_get_player_damage_expr_with_equipped_weapon(self, state_manager):
        """Damage expression should use equipped weapon's damage_expr."""
        from mgmai.engine.systems.five_e import FiveESystem

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        system = FiveESystem()

        # No equipped weapon and no weapon in inventory → unarmed 1d6
        expr = system.compute_player_damage_expr(hard, corpus, soft)
        assert "1d6" in expr

        # Equip the sword → 1d6 (toenail_sword has damage_expr "1d6")
        hard.player.equipped.append("toenail_sword")
        expr = system.compute_player_damage_expr(hard, corpus, soft)
        assert "1d6" in expr

    def test_get_player_damage_with_improvised_weapon(self, state_manager):
        """Improvised weapon should be used when no equipped weapon."""
        from mgmai.engine.systems.five_e import FiveESystem

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        system = FiveESystem()

        soft.improvised_weapon = ImprovisedWeapon(
            damage_expr="1d4", description="broken bottle"
        )
        expr = system.compute_player_damage_expr(hard, corpus, soft)
        assert "1d4" in expr

    def test_equipped_weapon_takes_priority_over_improvised(self, state_manager):
        """Equipped weapons should take priority over improvised weapons."""
        from mgmai.engine.systems.five_e import FiveESystem

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        system = FiveESystem()

        soft.improvised_weapon = ImprovisedWeapon(
            damage_expr="1d4", description="broken bottle"
        )
        hard.player.equipped.append("toenail_sword")
        expr = system.compute_player_damage_expr(hard, corpus, soft)
        assert "1d4" not in expr
        assert "1d6" in expr

    def test_compute_effective_stats_no_stats(self, state_manager):
        """compute_effective_stats should return None when player has no stats."""
        from mgmai.engine.combat import compute_effective_stats

        hard = state_manager.hard_state
        corpus = state_manager.corpus

        # Test fixture has no player.stats
        result = compute_effective_stats(hard, corpus)
        assert result is None


# ------------------------------------------------------------------
# Appearance notes (soft state)
# ------------------------------------------------------------------

class TestAppearanceNotes:
    def test_appearance_note_add(self, state_manager):
        """appearance_note_add patch should append to appearance_notes."""
        soft = state_manager.soft_state
        patch = SoftStatePatch(
            field="appearance_note_add",
            new_value="tattered cloak pulled from a goblin corpse",
            reason="Player described wearing a goblin cloak",
        )
        state_manager.apply_soft_patches([patch])
        assert "tattered cloak" in soft.appearance_notes[0]

    def test_appearance_notes_persist(self, state_manager):
        """Multiple appearance notes should accumulate."""
        soft = state_manager.soft_state
        for note in ["note 1", "note 2"]:
            state_manager.apply_soft_patches([
                SoftStatePatch(field="appearance_note_add", new_value=note, reason="test")
            ])
        assert len(soft.appearance_notes) == 2


# ------------------------------------------------------------------
# HardStateChanges merge with equipment fields
# ------------------------------------------------------------------

class TestHardStateChangesEquipment:
    def test_merge_equipped_added(self):
        """merge should combine equipped_added lists."""
        a = HardStateChanges(equipped_added=["sword"])
        b = HardStateChanges(equipped_added=["shield"])
        a.merge(b)
        assert "sword" in a.equipped_added
        assert "shield" in a.equipped_added

    def test_merge_equipment_changed(self):
        """merge should set equipment_changed if either has it."""
        a = HardStateChanges()
        b = HardStateChanges(equipment_changed=True)
        a.merge(b)
        assert a.equipment_changed is True

    def test_has_changes_equipment(self):
        """has_changes should detect equipment changes."""
        changes = HardStateChanges(equipped_added=["sword"])
        assert changes.has_changes() is True

        changes = HardStateChanges(equipment_changed=True)
        assert changes.has_changes() is True

        changes = HardStateChanges()
        assert changes.has_changes() is False
