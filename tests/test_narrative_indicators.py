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

"""Tests for engine/narrative_indicators.py — marker-based inline indicators."""

from __future__ import annotations

from mgmai.engine.narrative_indicators import (
    NarrativeIndicator,
    _format_single_combat_entry,
    build_indicators,
    format_indicators_fallback,
    process_narration,
)


class FakeHardState:
    """Minimal stand-in for HardGameState in indicator tests."""

    class _Player:
        def __init__(self, current_hp=10, max_hp=10):
            self.current_hp = current_hp
            self.max_hp = max_hp

    def __init__(self, current_hp=10, max_hp=10):
        self.player = self._Player(current_hp, max_hp)


class TestBuildIndicators:
    """Tests for build_indicators()."""

    def test_empty_result(self):
        from mgmai.models.actions import EngineResult

        result = EngineResult(success=True, action_type="wait")
        hard = FakeHardState()
        indicators = build_indicators(result, hard)
        assert indicators == []

    def test_stat_check_indicator(self):
        from mgmai.models.actions import EngineResult

        result = EngineResult(
            success=True,
            action_type="interact",
            rolls=[{"type": "stat_check", "stat": "STR", "target": 10, "success": False}],
        )
        indicators = build_indicators(result, FakeHardState())
        assert len(indicators) == 1
        assert indicators[0].marker == "[MECH:check:0]"
        assert indicators[0].formatted == "**[STR check: failed]**"
        assert indicators[0].category == "check"

    def test_multiple_stat_checks(self):
        from mgmai.models.actions import EngineResult

        result = EngineResult(
            success=True,
            action_type="interact",
            rolls=[
                {"type": "stat_check", "stat": "STR", "target": 10, "success": False},
                {"type": "stat_check", "stat": "DEX", "target": 12, "success": True},
            ],
        )
        indicators = build_indicators(result, FakeHardState())
        assert len(indicators) == 2
        assert indicators[0].marker == "[MECH:check:0]"
        assert indicators[1].marker == "[MECH:check:1]"

    def test_hp_damage_indicator(self):
        from mgmai.models.actions import EngineResult, HardStateChanges

        result = EngineResult(
            success=True,
            action_type="interact",
            hard_state_changes=HardStateChanges(player_hp_delta=-3),
        )
        hard = FakeHardState(current_hp=7, max_hp=10)
        indicators = build_indicators(result, hard)
        assert len(indicators) == 1
        assert indicators[0].marker == "[MECH:hp]"
        assert "Took 3 damage" in indicators[0].formatted
        assert "HP 7/10" in indicators[0].formatted

    def test_hp_heal_indicator(self):
        from mgmai.models.actions import EngineResult, HardStateChanges

        result = EngineResult(
            success=True,
            action_type="interact",
            hard_state_changes=HardStateChanges(player_hp_delta=5),
        )
        hard = FakeHardState(current_hp=10, max_hp=10)
        indicators = build_indicators(result, hard)
        assert "Healed 5 HP" in indicators[0].formatted

    def test_hp_split_indicators_on_mixed_turn(self):
        """Healing and damage on the same turn produce separate markers —
        one net marker would misattribute (a +7/-10 turn is not "Took 3
        damage" next to the potion)."""
        from mgmai.models.actions import EngineResult, HardStateChanges

        result = EngineResult(
            success=True,
            action_type="interact",
            hard_state_changes=HardStateChanges(
                player_hp_delta=-3,
                player_damage_delta=10,
                player_heal_delta=7,
            ),
        )
        hard = FakeHardState(current_hp=7, max_hp=10)
        indicators = build_indicators(result, hard)
        assert [i.marker for i in indicators] == [
            "[MECH:hp_damage]", "[MECH:hp_heal]",
        ]
        assert "Took 10 damage" in indicators[0].formatted
        assert "HP 7/10" in indicators[0].formatted
        assert "Healed 7 HP" in indicators[1].formatted

    def test_stat_modifier_indicator(self):
        from mgmai.models.actions import EngineResult, HardStateChanges
        from mgmai.models.corpus import StatModifier

        result = EngineResult(
            success=True,
            action_type="interact",
            hard_state_changes=HardStateChanges(
                stat_modifiers={"STR": StatModifier(value=-2)},
                old_stat_values={"STR": 14},
            ),
        )
        indicators = build_indicators(result, FakeHardState())
        assert len(indicators) == 1
        assert indicators[0].marker == "[MECH:stat]"
        assert "STR -2 (now 12)" in indicators[0].formatted

    def test_combat_log_indicator(self):
        from mgmai.models.actions import EngineResult
        from mgmai.models.combat import CombatLogEntry

        result = EngineResult(
            success=True,
            action_type="interact",
            combat_log=[
                CombatLogEntry(
                    round=1,
                    actor="goblin",
                    action="attack",
                    target="player",
                    hit=True,
                    damage=4,
                ),
            ],
        )
        indicators = build_indicators(result, FakeHardState())
        assert len(indicators) == 1
        assert indicators[0].marker == "[MECH:combat:0]"
        assert "goblin" in indicators[0].formatted.lower()

    def test_mixed_indicators(self):
        from mgmai.models.actions import EngineResult, HardStateChanges

        result = EngineResult(
            success=True,
            action_type="interact",
            rolls=[{"type": "stat_check", "stat": "CON", "target": 10, "success": True}],
            hard_state_changes=HardStateChanges(player_hp_delta=-2),
        )
        hard = FakeHardState(current_hp=8, max_hp=10)
        indicators = build_indicators(result, hard)
        assert len(indicators) == 2
        assert indicators[0].category == "check"
        assert indicators[1].category == "hp"


class TestProcessNarration:
    """Tests for process_narration()."""

    def test_no_indicators(self):
        narration = "You walk down the hall."
        assert process_narration(narration, []) == narration

    def test_marker_replacement(self):
        indicators = [
            NarrativeIndicator(
                marker="[MECH:check:0]",
                formatted="**[STR check: failed]**",
                category="check",
            ),
        ]
        narration = "You try to lift.\n\n[MECH:check:0]\n\nToo heavy."
        result = process_narration(narration, indicators)
        assert "**[STR check: failed]**" in result
        assert "[MECH:check:0]" not in result

    def test_fallback_prepend(self):
        indicators = [
            NarrativeIndicator(
                marker="[MECH:check:0]",
                formatted="**[DEX check: success]**",
                category="check",
            ),
        ]
        narration = "You dodge gracefully."
        result = process_narration(narration, indicators)
        assert result.startswith("**[DEX check: success]**")
        assert "You dodge gracefully." in result

    def test_partial_placement(self):
        indicators = [
            NarrativeIndicator(
                marker="[MECH:check:0]",
                formatted="**[STR check: failed]**",
                category="check",
            ),
            NarrativeIndicator(
                marker="[MECH:hp]",
                formatted="**[Took 3 damage]**",
                category="hp",
            ),
        ]
        narration = "You swing.\n\n[MECH:check:0]\n\nThe blade glances off."
        result = process_narration(narration, indicators)
        assert "**[STR check: failed]**" in result
        assert result.startswith("**[Took 3 damage]**")
        assert "[MECH:hp]" not in result

    def test_multiple_combat_entries(self):
        indicators = [
            NarrativeIndicator(
                marker="[MECH:combat:0]",
                formatted="**You hit: 5 damage.**",
                category="combat",
            ),
            NarrativeIndicator(
                marker="[MECH:combat:1]",
                formatted="**Goblin hits you: 2 damage.**",
                category="combat",
            ),
        ]
        narration = "You strike.\n\n[MECH:combat:0]\n\nIt retaliates.\n\n[MECH:combat:1]\n\nYou stagger."
        result = process_narration(narration, indicators)
        assert "**You hit: 5 damage.**" in result
        assert "**Goblin hits you: 2 damage.**" in result
        assert "[MECH:combat:0]" not in result
        assert "[MECH:combat:1]" not in result


class TestFormatIndicatorsFallback:
    """Tests for format_indicators_fallback()."""

    def test_empty(self):
        from mgmai.models.actions import EngineResult

        result = EngineResult(success=True, action_type="wait")
        assert format_indicators_fallback(result, FakeHardState()) == ""

    def test_combined_prefix(self):
        from mgmai.models.actions import EngineResult, HardStateChanges

        result = EngineResult(
            success=True,
            action_type="interact",
            rolls=[{"type": "stat_check", "stat": "INT", "target": 10, "success": True}],
            hard_state_changes=HardStateChanges(player_hp_delta=-5),
        )
        hard = FakeHardState(current_hp=5, max_hp=10)
        prefix = format_indicators_fallback(result, hard)
        assert prefix.startswith("**[INT check: success]**")
        assert "Took 5 damage" in prefix
        assert prefix.endswith("\n\n")


class TestPlainDescription:
    """Tests for NarrativeIndicator.plain_description."""

    def test_strips_bold_brackets(self):
        ind = NarrativeIndicator(
            marker="[MECH:check:0]",
            formatted="**[STR check: failed]**",
            category="check",
        )
        assert ind.plain_description == "STR check: failed"

    def test_strips_bold_only(self):
        ind = NarrativeIndicator(
            marker="[MECH:hp]",
            formatted="**Took 3 damage**",
            category="hp",
        )
        assert ind.plain_description == "Took 3 damage"

    def test_passthrough(self):
        ind = NarrativeIndicator(
            marker="[MECH:x]",
            formatted="plain text",
            category="check",
        )
        assert ind.plain_description == "plain text"


class TestFormatSingleCombatEntry:
    """Tests for _format_single_combat_entry helper."""

    def test_player_attack_hit(self):
        entry = {
            "actor": "player",
            "action": "attack",
            "target": "goblin",
            "hit": True,
            "damage": 5,
        }
        result = _format_single_combat_entry(entry)
        assert "You attack goblin: hit" in result
        assert "5 damage" in result

    def test_npc_attack_miss(self):
        entry = {
            "actor": "spider",
            "action": "attack",
            "target": "player",
            "hit": False,
        }
        result = _format_single_combat_entry(entry)
        assert "spider attacks you: miss" in result

    def test_death(self):
        entry = {"actor": "goblin", "action": "death", "target": None}
        result = _format_single_combat_entry(entry)
        assert "goblin is dead" in result.lower()

    def test_flee(self):
        entry = {"actor": "goblin", "action": "flee", "target": None, "hit": True}
        result = _format_single_combat_entry(entry)
        assert "flees" in result.lower()

    def test_stunned(self):
        entry = {"actor": "player", "action": "stunned", "target": None}
        result = _format_single_combat_entry(entry)
        assert "stunned" in result.lower()

    def test_interact_item(self):
        entry = {
            "actor": "player",
            "action": "interact",
            "target": "healing potion",
        }
        result = _format_single_combat_entry(entry)
        assert "healing potion" in result.lower()

    def test_ability_save(self):
        entry = {
            "actor": "spider",
            "action": "ability_save",
            "target": "player",
            "attack_name": "Venom Spray",
            "damage": 3,
            "on_hit_effects": [{"save_stat": "CON", "save_success": False}],
        }
        result = _format_single_combat_entry(entry)
        assert "spider uses Venom Spray" in result
        assert "fails to resist" in result

    def test_ability_save_player_caster(self):
        # A player-cast save spell renders in the second person
        # ("You use", not "You uses").
        entry = {
            "actor": "player",
            "action": "ability_save",
            "target": "goblin",
            "attack_name": "Hold Person",
            "damage": 0,
            "on_hit_effects": [{"save_stat": "WIS", "save_success": False}],
        }
        result = _format_single_combat_entry(entry)
        assert "You use Hold Person" in result
        assert "You uses" not in result

    def test_ability_on_cast_player_caster(self):
        entry = {
            "actor": "player",
            "action": "ability_on_cast",
            "target": "player",
            "attack_name": "Blur",
            "on_hit_effects": [{"status_effect": "blur"}],
        }
        result = _format_single_combat_entry(entry)
        assert "You cast Blur" in result
        assert "You casts" not in result
        assert "gains blur" in result

    def test_ability_on_cast_npc_caster(self):
        # Third-person singular conjugation for an NPC caster.
        entry = {
            "actor": "mage",
            "action": "ability_on_cast",
            "target": "mage",
            "attack_name": "Blur",
            "on_hit_effects": [{"status_effect": "blur"}],
        }
        result = _format_single_combat_entry(entry)
        assert "mage casts Blur" in result

    def test_heal_player_caster(self):
        entry = {
            "actor": "player",
            "action": "heal",
            "target": "player",
            "attack_name": "Cure Wounds",
            "damage": 5,
        }
        result = _format_single_combat_entry(entry)
        assert "You use Cure Wounds" in result
        assert "You uses" not in result

    def test_ability_auto_player_caster(self):
        # A player-cast auto-damage spell renders in the second person
        # ("You use", not "You uses").
        entry = {
            "actor": "player",
            "action": "ability_auto",
            "target": "goblin",
            "attack_name": "Magic Missile",
            "damage": 7,
        }
        result = _format_single_combat_entry(entry)
        assert "You use Magic Missile" in result
        assert "You uses" not in result
        assert "takes 7 damage (no attack roll or save)" in result

    def test_ability_auto_npc_caster(self):
        # Third-person singular conjugation for an NPC caster.
        entry = {
            "actor": "mage",
            "action": "ability_auto",
            "target": "player",
            "attack_name": "Magic Missile",
            "damage": 7,
        }
        result = _format_single_combat_entry(entry)
        assert "mage uses Magic Missile" in result
        assert "takes 7 damage" in result

    def test_heal(self):
        entry = {
            "actor": "cleric",
            "action": "heal",
            "target": "player",
            "attack_name": "Cure Wounds",
            "damage": 5,
        }
        result = _format_single_combat_entry(entry)
        assert "cleric uses Cure Wounds on you" in result
        assert "healed 5 HP" in result

    def test_unknown_action(self):
        entry = {"actor": "player", "action": "dance", "target": None}
        assert _format_single_combat_entry(entry) == ""

    def test_opportunity_attack_player_hit(self):
        entry = {
            "actor": "player",
            "action": "opportunity_attack",
            "target": "goblin",
            "hit": True,
            "damage": 5,
        }
        result = _format_single_combat_entry(entry)
        assert "You make an opportunity attack on goblin: hit" in result
        assert "5 damage" in result

    def test_opportunity_attack_npc_miss(self):
        entry = {
            "actor": "spider",
            "action": "opportunity_attack",
            "target": "player",
            "hit": False,
        }
        result = _format_single_combat_entry(entry)
        assert "spider makes an opportunity attack on you: miss" in result

    def test_reposition_player(self):
        entry = {"actor": "player", "action": "reposition", "target": "goblin"}
        result = _format_single_combat_entry(entry)
        assert "You reposition relative to goblin" in result

    def test_reposition_npc(self):
        entry = {"actor": "spider", "action": "reposition", "target": "player"}
        result = _format_single_combat_entry(entry)
        assert "spider repositions relative to you" in result

    def test_maneuver_player(self):
        entry = {"actor": "player", "action": "maneuver", "target": None}
        result = _format_single_combat_entry(entry)
        assert "disengage" in result.lower()

    def test_impeded_npc(self):
        entry = {"actor": "spider", "action": "impeded", "target": None}
        result = _format_single_combat_entry(entry)
        assert "spider" in result
        assert "closing in" in result
