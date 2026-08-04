# My GM is AI — Phase 2 maneuver tests (Dodge, Grapple/Shove, Help, and
# the Light-property off-hand attack)
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Phase 2 tests: the Dodge action (save-advantage wiring), Grapple /
Shove (+ the escape action and grapple engagement), Help, and the
Light-property bonus-action off-hand attack (§5, §6, §9 of the
action-economy plan)."""

import random

import pytest

from mgmai.engine.combat import resolve_combat_turn
from mgmai.engine.resolver import resolve_action
from mgmai.engine.systems import get_system
from mgmai.models.actions import CombatAction, GearAction, WaitAction
from mgmai.models.combat import CombatState
from mgmai.models.corpus import ModuleCorpus, StatCheck
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mvr_corpus() -> ModuleCorpus:
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Maneuvers", "introduction": "Test."},
        "rooms": {
            "room1": {
                "name": "Room 1", "description": "A room.",
                "contains": ["goblin", "shortsword", "dagger", "longsword"],
            },
        },
        "entities": {
            "goblin": {
                "type": "npc",
                "description": "A goblin.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Alive?"},
                    "current_hp": {"type": "number", "description": "HP"},
                },
                "combat": {
                    "hp": 30, "ac": 12, "atk": 4, "dmg": "1d6+2",
                    "save_bonus": 0,
                },
            },
            "ally": {
                "type": "npc",
                "description": "A loyal ally.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Alive?"},
                    "current_hp": {"type": "number", "description": "HP"},
                },
                "combat": {
                    "hp": 20, "ac": 14, "atk": 4, "dmg": "1d6+2",
                    "save_bonus": 0,
                },
            },
            "shortsword": {
                "type": "item",
                "name": "Shortsword",
                "description": "A light blade.",
                "equip_block": {
                    "equip_tags": ["weapon", "simple"],
                    "damage_expr": "1d6", "damage_type": "slashing",
                    "max_equipped": 2, "properties": ["light"],
                },
            },
            "dagger": {
                "type": "item",
                "name": "Dagger",
                "description": "A throwing dagger.",
                "equip_block": {
                    "equip_tags": ["weapon", "simple"],
                    "damage_expr": "1d4", "damage_type": "piercing",
                    "max_equipped": 2, "properties": ["finesse", "light", "thrown"],
                },
            },
            "longsword": {
                "type": "item",
                "name": "Longsword",
                "description": "A heavier blade.",
                "equip_block": {
                    "equip_tags": ["weapon", "martial"],
                    "damage_expr": "1d8", "damage_type": "slashing",
                    "max_equipped": 2, "properties": [],
                },
            },
            "greatsword": {
                "type": "item",
                "name": "Greatsword",
                "description": "A huge two-handed blade.",
                "equip_block": {
                    "equip_tags": ["weapon", "martial", "two_handed"],
                    "damage_expr": "2d6", "damage_type": "slashing",
                    "max_equipped": 2, "properties": ["heavy", "two_handed"],
                    "incompatible_with": ["weapon", "shield"],
                },
            },
        },
        "stats": {
            "definitions": {
                "STR": {"name": "Strength"},
                "DEX": {"name": "Dexterity"},
                "CON": {"name": "Constitution"},
                "INT": {"name": "Intelligence"},
                "WIS": {"name": "Wisdom"},
                "CHA": {"name": "Charisma"},
            },
            "system": "5e",
        },
    })


@pytest.fixture
def mvr_hard() -> HardGameState:
    return HardGameState.model_validate({
        "player": {
            "location": "room1",
            "inventory": {"shortsword": 1, "dagger": 1, "longsword": 1},
            "equipped": ["shortsword"],
            "weapon_proficiencies": ["simple", "martial"],
            "stats": {
                "STR": 16, "DEX": 14, "CON": 12,
                "INT": 10, "WIS": 8, "CHA": 10,
            },
            "level": 1,
            "current_hp": 10,
            "max_hp": 20,
            "ac": 12,
            "proficiency_bonus": 2,
        },
        "flags": {},
        "room_states": {"room1": {"visited": True}},
        "entity_states": {
            "goblin": {"alive": True, "current_hp": 30},
            "ally": {"alive": True, "current_hp": 20},
        },
        "room_contains": {
            "room1": {"goblin": 1, "shortsword": 1, "dagger": 1, "longsword": 1},
        },
        "turn_count": 0,
    })


def _combat_state(hard, *combatants, allies=()) -> CombatState:
    ids = ["player"] + list(combatants)
    hard.combat = CombatState(
        active=True,
        combatants=list(ids),
        allies=list(allies),
        initiative_order=list(ids),
        current_index=0,
        round_number=1,
    )
    return hard.combat


def _maneuver(kind, target=None, **kwargs) -> CombatAction:
    return CombatAction(
        action_type="combat", combat_action="maneuver",
        maneuver=kind, target=target, detail="Maneuver!", **kwargs,
    )


def _attack(target="goblin", **kwargs) -> CombatAction:
    return CombatAction(
        action_type="combat", combat_action="attack",
        target=target, detail="Attack!", **kwargs,
    )


def _rand_seq(vals):
    """randint that consumes *vals* and then defaults to 1."""
    it = iter(vals)
    return lambda a, b: next(it, 1)


# ------------------------------------------------------------------
# Dodge
# ------------------------------------------------------------------


class TestDodge:
    def test_dodge_applies_status_and_consumes_action(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(_maneuver("dodge"), mvr_hard, mvr_corpus)
        assert result["success"]
        assert result["turn_ended"] is True
        assert mvr_hard.player.status_effects.get("dodging") == 1
        # The dodge consumed the action (the turn ended); the budget
        # itself was reset at turn end.
        assert mvr_hard.combat.player_budget.action_used is False
        assert mvr_hard.combat.round_number == 2

    def test_dodging_grants_attackers_disadvantage(self, mvr_corpus):
        system = get_system("5e")
        # ``dodging`` is a target effect: attacks against the dodging
        # creature have disadvantage.
        adv, disadv = system.attack_roll_mods(
            {}, {"dodging": 1}, mvr_corpus, engaged=True
        )
        assert (adv, disadv) == (False, True)

    def test_dodging_grants_dex_save_advantage(self, mvr_corpus):
        system = get_system("5e")
        assert system.save_advantage("DEX", {"dodging": 1}, mvr_corpus) is True
        assert system.save_advantage("STR", {"dodging": 1}, mvr_corpus) is False
        assert system.save_advantage("DEX", {}, mvr_corpus) is False

    def test_dodging_dex_save_rolls_with_advantage(self, mvr_hard, mvr_corpus, monkeypatch):
        """The save-advantage wiring reaches the StatCheck save path: a DEX
        save while dodging rolls with advantage."""
        from mgmai.engine.resolver import _stat_check_params

        system = get_system("5e")
        mvr_hard.player.status_effects = {"dodging": 1}
        check = StatCheck(stat="DEX", target=12, save=True, repeatable=True)
        params = _stat_check_params(check, system, mvr_hard, mvr_corpus)
        assert params.get("advantage") is True
        # A non-DEX save gets no advantage from dodging.
        str_check = StatCheck(stat="STR", target=12, save=True, repeatable=True)
        assert "advantage" not in _stat_check_params(str_check, system, mvr_hard, mvr_corpus)

    def test_dodging_dex_save_advantage_in_ability_saves(self, mvr_hard, mvr_corpus, monkeypatch):
        """The save-advantage wiring reaches the ability-save path: a DEX
        save by the dodging player against a spell rolls with advantage."""
        from mgmai.engine.combat import _resolve_save_ability
        from mgmai.engine.resolver import HardStateChanges
        from mgmai.models.corpus import Ability, AbilitySave

        system = get_system("5e")
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.status_effects = {"dodging": 1}
        combat = mvr_hard.combat
        ability = Ability(
            name="Dexterity Trap", description="A DEX save spell.",
            target="enemy", save=AbilitySave(stat="DEX", dc=12),
        )
        hard_changes = HardStateChanges()
        combat_log = []
        events: list = []

        calls = []
        real_roll_die = system.roll_die

        def spy_roll_die(sides, advantage=False, disadvantage=False):
            calls.append((advantage, disadvantage))
            return real_roll_die(sides, advantage=advantage, disadvantage=disadvantage)

        monkeypatch.setattr(system, "roll_die", spy_roll_die)
        _resolve_save_ability(
            "goblin", "dex_trap", ability, "player", combat, mvr_hard,
            mvr_corpus, hard_changes, combat_log, events,
        )
        assert calls and calls[0][0] is True  # advantage on the DEX save

    def test_dodging_clears_at_next_turn_start(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        resolve_combat_turn(_maneuver("dodge"), mvr_hard, mvr_corpus)
        assert mvr_hard.player.status_effects.get("dodging") == 1
        # Round 2: the player's turn start clears the until_turn_start effect.
        r2 = resolve_combat_turn(
            WaitAction(action_type="wait", detail="Hold."),
            mvr_hard, mvr_corpus,
        )
        assert r2["success"]
        assert "dodging" not in mvr_hard.player.status_effects

    def test_npc_attack_against_dodging_player_rolls_with_disadvantage(self, mvr_hard, mvr_corpus, monkeypatch):
        """End to end: the goblin's attack in the NPC phase rolls two dice
        and takes the worse against a dodging player."""
        _combat_state(mvr_hard, "goblin")
        # Dodge ends the turn; the goblin attacks with disadvantage: rolls
        # 15 and 3 -> 3 + 4 = 7 < AC 12, miss.  Without disadvantage the
        # 15 + 4 = 19 would hit.
        monkeypatch.setattr(random, "randint", _rand_seq([15, 3, 1]))
        r = resolve_combat_turn(_maneuver("dodge"), mvr_hard, mvr_corpus)
        assert r["success"]
        assert mvr_hard.player.current_hp == 10  # untouched
        goblin_attacks = [
            e for e in r["combat_log"]
            if e.actor == "goblin" and e.action == "attack"
        ]
        assert goblin_attacks and goblin_attacks[0].hit is False


# ------------------------------------------------------------------
# Grapple / Shove
# ------------------------------------------------------------------


class TestGrapple:
    def test_grapple_applies_condition_and_engagement(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        # Grapple DC = 8 + 3 (STR) + 2 (prof) = 13; goblin save_bonus 0,
        # save roll 5 -> fails.
        monkeypatch.setattr(random, "randint", _rand_seq([5, 1]))
        result = resolve_combat_turn(_maneuver("grapple", "goblin"), mvr_hard, mvr_corpus)
        assert result["success"]
        combat = mvr_hard.combat
        assert combat.grapples.get("goblin") == "player"
        assert "grappled" in mvr_hard.entity_states["goblin"]["status_effects"]
        assert ["goblin", "player"] in combat.engagement
        assert result["combat_log"][0].action == "grapple"
        assert result["combat_log"][0].hit is True

    def test_grapple_resisted(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        # Save roll 15 >= DC 13 -> resisted; the action is still spent.
        monkeypatch.setattr(random, "randint", _rand_seq([15, 1]))
        result = resolve_combat_turn(_maneuver("grapple", "goblin"), mvr_hard, mvr_corpus)
        assert result["success"]
        assert mvr_hard.combat.grapples == {}
        assert "grappled" not in mvr_hard.entity_states["goblin"]
        # The action was spent (the turn ended and the round advanced);
        # the budget itself was reset at turn end.
        assert mvr_hard.combat.player_budget.action_used is False
        assert mvr_hard.combat.round_number == 2

    def test_grapple_requires_enemy_target(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(_maneuver("grapple", "nonexistent"), mvr_hard, mvr_corpus)
        assert not result["success"]
        assert "not in combat" in result["error"]

    def test_grappled_npc_escapes_on_its_turn(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["goblin"] = "player"
        combat.engagement = [["goblin", "player"]]
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"grappled": 1}
        # Escape DC 13; goblin save roll 15 -> escapes.
        monkeypatch.setattr(random, "randint", _rand_seq([15]))
        result = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples == {}
        assert "grappled" not in mvr_hard.entity_states["goblin"]["status_effects"]
        escapes = [e for e in result["combat_log"] if e.action == "escape"]
        assert escapes and escapes[0].hit is True

    def test_grappled_npc_stays_grappled_on_failed_escape(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["goblin"] = "player"
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"grappled": 1}
        monkeypatch.setattr(random, "randint", _rand_seq([5]))
        result = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples.get("goblin") == "player"
        assert "grappled" in mvr_hard.entity_states["goblin"]["status_effects"]

    def test_player_escape_maneuver(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["player"] = "goblin"
        mvr_hard.player.status_effects = {"grappled": 1}
        # Escape DC for the goblin grappler = 8 + save_bonus(0) + 2 = 10.
        # Player STR 16 (mod 3) + prof 2; roll 10 -> 10 + 5 = 15 >= 10.
        monkeypatch.setattr(random, "randint", _rand_seq([10, 1]))
        result = resolve_combat_turn(_maneuver("escape"), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples == {}
        assert "grappled" not in mvr_hard.player.status_effects
        assert result["combat_log"][0].action == "escape"

    def test_escape_fails_when_not_grappled(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(_maneuver("escape"), mvr_hard, mvr_corpus)
        assert not result["success"]
        assert "not currently grappled" in result["error"]

    def test_grappled_player_cannot_disengage(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["player"] = "goblin"
        combat.engagement = [["goblin", "player"]]
        mvr_hard.player.status_effects = {"grappled": 1}
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(_maneuver("disengage"), mvr_hard, mvr_corpus)
        assert not result["success"]
        assert "grappled" in result["error"]

    def test_grapple_ends_if_grappler_incapacitated(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["player"] = "goblin"
        mvr_hard.player.status_effects = {"grappled": 1}
        # Stun the goblin (the player's grappler).
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"stunned": 1}
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples == {}
        assert "grappled" not in mvr_hard.player.status_effects

    def test_only_one_grapple_at_a_time(self, mvr_hard, mvr_corpus, monkeypatch):
        """SRD: one hand, one grapple — a second grapple while holding one
        is rejected and costs nothing."""
        _combat_state(mvr_hard, "goblin", "ally")  # 'ally' as a second enemy
        # Grapple the goblin (save roll 5 < DC 13 -> held).
        monkeypatch.setattr(random, "randint", _rand_seq([5, 1]))
        r1 = resolve_combat_turn(_maneuver("grapple", "goblin"), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert mvr_hard.combat.grapples.get("goblin") == "player"
        # Grapple a second target on a fresh turn: rejected.
        r2 = resolve_combat_turn(_maneuver("grapple", "ally"), mvr_hard, mvr_corpus)
        assert not r2["success"]
        assert "already grappling" in r2["error"]
        assert mvr_hard.combat.player_budget.action_used is False

    def test_grappled_mover_cannot_disengage_via_positioning(self, mvr_hard, mvr_corpus, monkeypatch):
        """A positioning disengage assertion for a grappled mover is
        dropped with a warning; the engagement survives."""
        from mgmai.models.actions import PositioningAssertion

        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["goblin"] = "player"
        combat.engagement = [["goblin", "player"]]
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"grappled": 1}
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(
            _attack(positioning=PositioningAssertion(disengage=[["goblin", "player"]])),
            mvr_hard, mvr_corpus,
        )
        assert result["success"]
        assert any("grappled" in w for w in result["warnings"])
        assert ["goblin", "player"] in combat.engagement

    def test_grapple_ends_when_player_grappler_incapacitated(self, mvr_hard, mvr_corpus, monkeypatch):
        """The realistic prune direction: the player grapples the goblin,
        then is stunned — the goblin is freed at the player's next turn."""
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["goblin"] = "player"
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"grappled": 1}
        mvr_hard.player.status_effects = {"stunned": 1}
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples == {}
        assert "grappled" not in mvr_hard.entity_states["goblin"]["status_effects"]

    def test_grapple_ends_when_grappled_npc_dies(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.grapples["goblin"] = "player"
        mvr_hard.entity_states.setdefault("goblin", {})["status_effects"] = {"grappled": 1}
        # The grappled goblin dies (e.g. to an ally's attack): the grapple
        # entry is pruned at the player's next turn.
        mvr_hard.entity_states["goblin"]["current_hp"] = 0
        combat.combatants.remove("goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        result = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert result["success"]
        assert combat.grapples == {}


class TestShove:
    def test_shove_knocks_prone(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        # Save roll 5 < DC 13 -> the shove lands (knocked prone).  The
        # ``prone`` condition auto-clears at the start of the goblin's own
        # turn, which runs in the same NPC phase — so by the time the turn
        # returns, the goblin has stood up; the log entry records the hit.
        monkeypatch.setattr(random, "randint", _rand_seq([5, 1]))
        result = resolve_combat_turn(_maneuver("shove", "goblin"), mvr_hard, mvr_corpus)
        assert result["success"]
        assert result["combat_log"][0].action == "shove"
        assert result["combat_log"][0].hit is True  # save failed, prone applied
        assert "prone" not in mvr_hard.entity_states["goblin"].get(
            "status_effects", {}
        )  # stood up at its own turn

    def test_shove_resisted(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([15, 1]))
        result = resolve_combat_turn(_maneuver("shove", "goblin"), mvr_hard, mvr_corpus)
        assert result["success"]
        assert result["combat_log"][0].hit is False


# ------------------------------------------------------------------
# Help
# ------------------------------------------------------------------


class TestHelp:
    def test_help_flags_enemy_for_ally_advantage(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin", "ally", allies=["ally"])
        combat = mvr_hard.combat
        # Help directs the ally to the goblin (player_last_target) and flags
        # it.  Help consumes the action; the turn's NPC phase runs: the
        # goblin attacks the player (roll 1 = miss), then the ally attacks
        # the help-flagged goblin WITH advantage: rolls 3 and 15 -> 15 hits
        # (WITHOUT advantage the 3 + 4 = 7 would miss AC 12 — the dice order
        # makes the advantage discriminating), dealing 4 + 2 = 6 damage and
        # consuming the flag.
        monkeypatch.setattr(random, "randint", _rand_seq([1, 3, 15, 4]))
        r1 = resolve_combat_turn(_maneuver("help", "goblin"), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert combat.help_flagged == []  # consumed by the ally's attack
        assert mvr_hard.entity_states["goblin"]["current_hp"] == 30 - 6
        # Help consumed the action (the NPC phase ran); the budget itself
        # was reset at turn end.
        assert mvr_hard.combat.player_budget.action_used is False

    def test_help_flag_expires_at_players_next_turn(self, mvr_hard, mvr_corpus, monkeypatch):
        """SRD: the Help benefit expires at the start of the helper's next
        turn — an unconsumed flag does not persist into later rounds."""
        _combat_state(mvr_hard, "goblin")
        monkeypatch.setattr(random, "randint", _rand_seq([1]))
        r1 = resolve_combat_turn(_maneuver("help", "goblin"), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert mvr_hard.combat.help_flagged == ["goblin"]  # no ally to consume it
        r2 = resolve_combat_turn(WaitAction(action_type="wait", detail="."), mvr_hard, mvr_corpus)
        assert r2["success"]
        assert mvr_hard.combat.help_flagged == []

    def test_players_own_attack_ignores_help_flag(self, mvr_hard, mvr_corpus, monkeypatch):
        """Help aids an *ally's* attack, never the helper's own: the
        player's attack neither benefits from nor consumes the flag."""
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.help_flagged.append("goblin")
        combat.turn_continuation = True  # mid-turn: skip the expiry reset
        rolls = []

        def recording_randint(a, b):
            rolls.append((a, b))
            return 5  # player and goblin both miss; nothing else happens

        monkeypatch.setattr(random, "randint", recording_randint)
        r = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r["success"]
        # The player's attack rolls one d20 (no advantage from the flag);
        # the only other d20 is the goblin's own attack in the NPC phase.
        d20s = [r for r in rolls if r[1] == 20]
        assert len(d20s) == 2
        assert combat.help_flagged == ["goblin"]  # not consumed


# ------------------------------------------------------------------
# Light-property off-hand attack
# ------------------------------------------------------------------


class TestOffHandAttack:
    def test_dual_wield_light_weapons(self, mvr_hard, mvr_corpus):
        """The max_equipped fix lets two weapons share the weapon slot."""
        action = GearAction(
            action_type="gear",
            equip_targets=["dagger"],
            detail="Draw the dagger.",
        )
        result = resolve_action(action, mvr_hard, SoftGameState(), mvr_corpus)
        assert result.success
        assert set(result.hard_changes.equipped_added) == {"dagger"}

    def test_off_hand_attack_damage_excludes_ability_mod(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        combat = mvr_hard.combat
        combat.engagement = [["goblin", "player"]]

        # Rolls read as (sides - 1): d20 -> 19 (hit), so the damage die
        # decides.  Action attack: shortsword 1d6 -> 5, +3 STR = 8.
        # Goblin 30 -> 22.
        monkeypatch.setattr(random, "randint", lambda a, b: b - 1)
        r1 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is False  # off-hand available keeps turn open
        assert mvr_hard.entity_states["goblin"]["current_hp"] == 22
        assert combat.action_weapon_id == "shortsword"
        assert combat.player_budget.action_used is True

        # Off-hand bonus-action attack: the DAGGER (1d4 -> 3), NO ability
        # mod.  Goblin 22 -> 19.  If the off-hand wrongly re-used the
        # shortsword (1d6 -> 5), the result would be 17.
        r2 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r2["success"]
        assert mvr_hard.entity_states["goblin"]["current_hp"] == 19
        assert r2["turn_ended"] is True  # action + bonus action both spent
        # Both were spent (the turn ended); the budget itself was reset
        # at turn end.
        assert combat.player_budget.bonus_action_used is False

    def test_off_hand_not_available_without_second_light_weapon(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["shortsword"]  # only one light weapon
        combat = mvr_hard.combat
        combat.engagement = [["goblin", "player"]]
        monkeypatch.setattr(random, "randint", _rand_seq([10, 4]))
        r1 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is True  # no off-hand: turn closes
        # A second attack on the next round would be a normal new action,
        # so directly test the rejection on a mid-turn continuation:
        combat.action_weapon_id = "shortsword"
        combat.player_budget.action_used = True
        combat.turn_continuation = True
        r2 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert not r2["success"]
        assert "off-hand" in r2["error"]

    def test_off_hand_negative_ability_mod_still_applies(self, mvr_hard, mvr_corpus, monkeypatch):
        """'No ability mod to damage unless negative': a negative ability
        modifier still applies to the off-hand damage."""
        _combat_state(mvr_hard, "goblin")
        # Feeble player: STR 6 and DEX 6 (both -2), so even the finesse
        # dagger's better-of-STR/DEX stat mod is -2.
        mvr_hard.player.stats = {
            "STR": 6, "DEX": 6, "CON": 12, "INT": 10, "WIS": 8, "CHA": 10,
        }
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        combat = mvr_hard.combat
        combat.engagement = [["goblin", "player"]]
        # d20 -> 19 (19 - 2 + 2 = 19 vs AC 12, hit); damage die = sides - 1.
        monkeypatch.setattr(random, "randint", lambda a, b: b - 1)
        r1 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is False
        # Main attack: shortsword 1d6 -> 5, -2 = 3.  Goblin 30 -> 27.
        assert mvr_hard.entity_states["goblin"]["current_hp"] == 27
        # Off-hand dagger: 1d4 -> 3, and the NEGATIVE mod still applies:
        # 3 - 2 = 1.  Goblin 27 -> 26.  (Were the mod dropped, it'd be 24.)
        r2 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r2["success"]
        assert r2["turn_ended"] is True
        assert mvr_hard.entity_states["goblin"]["current_hp"] == 26

    def test_briefing_exposes_off_hand_availability(self, mvr_hard, mvr_corpus, monkeypatch):
        from mgmai.context.assembler import assemble

        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        combat = mvr_hard.combat
        combat.engagement = [["goblin", "player"]]
        monkeypatch.setattr(random, "randint", _rand_seq([10, 4]))
        resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        briefing = assemble(mvr_corpus, mvr_hard, SoftGameState(), "I attack again.")
        assert briefing.combat_state.off_hand_attack_available is True
        # After the off-hand is used, it is no longer available.
        monkeypatch.setattr(random, "randint", _rand_seq([10, 3]))
        resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        briefing2 = assemble(mvr_corpus, mvr_hard, SoftGameState(), "I attack again.")
        assert briefing2.combat_state.off_hand_attack_available is False

    def test_off_hand_rejected_when_bonus_action_spent(self, mvr_hard, mvr_corpus, monkeypatch):
        """The off-hand attack IS the bonus action: with the bonus action
        already spent, a second attack is rejected."""
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        combat = mvr_hard.combat
        combat.action_weapon_id = "shortsword"
        combat.player_budget.action_used = True
        combat.player_budget.bonus_action_used = True
        combat.turn_continuation = True
        r = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert not r["success"]
        assert "action and the bonus action" in r["error"]

    def test_third_weapon_rejected(self, mvr_hard, mvr_corpus):
        """Two weapons share the weapon slot (max_equipped 2); a third is
        rejected by the cap."""
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        action = GearAction(
            action_type="gear", equip_targets=["longsword"],
            unequip_targets=[], detail="Draw a third weapon.",
        )
        result = resolve_action(action, mvr_hard, SoftGameState(), mvr_corpus)
        assert not result.success
        assert "limit" in result.error

    def test_two_handed_weapon_blocks_second_weapon(self, mvr_hard, mvr_corpus):
        """A two-handed weapon is incompatible with ANY second weapon,
        regardless of equip order (symmetric conflict check)."""
        mvr_hard.player.equipped = ["greatsword"]
        mvr_hard.player.inventory = {"dagger": 1, "longsword": 1}
        onto_two_hander = GearAction(
            action_type="gear", equip_targets=["dagger"],
            unequip_targets=[], detail="Off-hand dagger.",
        )
        result = resolve_action(onto_two_hander, mvr_hard, SoftGameState(), mvr_corpus)
        assert not result.success
        assert "conflicts" in result.error

    def test_second_weapon_blocks_two_hander(self, mvr_hard, mvr_corpus):
        """Reverse order: equipping a two-hander onto an equipped weapon is
        likewise rejected."""
        mvr_hard.player.equipped = ["dagger"]
        mvr_hard.player.inventory = {"greatsword": 1}
        action = GearAction(
            action_type="gear", equip_targets=["greatsword"],
            unequip_targets=[], detail="Swap up.",
        )
        result = resolve_action(action, mvr_hard, SoftGameState(), mvr_corpus)
        assert not result.success
        assert "conflicts" in result.error


class TestManeuverBudget:
    def test_second_maneuver_rejected(self, mvr_hard, mvr_corpus, monkeypatch):
        """A maneuver costs the action: a second maneuver on an open turn
        is rejected and costs nothing."""
        _combat_state(mvr_hard, "goblin")
        combat = mvr_hard.combat
        combat.player_budget.action_used = True
        combat.turn_continuation = True
        r = resolve_combat_turn(_maneuver("dodge"), mvr_hard, mvr_corpus)
        assert not r["success"]
        assert "action was already used" in r["error"]
        assert "dodging" not in mvr_hard.player.status_effects

    def test_maneuver_after_attack_rejected(self, mvr_hard, mvr_corpus, monkeypatch):
        """Attacking first (action spent), a maneuver on the same turn is
        rejected even though the turn stays open for a bonus action."""
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["shortsword", "dagger"]
        monkeypatch.setattr(random, "randint", lambda a, b: b - 1)
        r1 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r1["turn_ended"] is False  # off-hand keeps the turn open
        r2 = resolve_combat_turn(_maneuver("dodge"), mvr_hard, mvr_corpus)
        assert not r2["success"]
        assert "action was already used" in r2["error"]


class TestOffHandLightRequirement:
    def test_off_hand_requires_light_action_weapon(self, mvr_hard, mvr_corpus, monkeypatch):
        _combat_state(mvr_hard, "goblin")
        mvr_hard.player.equipped = ["longsword", "dagger"]  # action weapon not light
        combat = mvr_hard.combat
        combat.engagement = [["goblin", "player"]]
        monkeypatch.setattr(random, "randint", _rand_seq([10, 4]))
        r1 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is True  # longsword is not light: no off-hand
        assert combat.action_weapon_id is None  # reset at turn end
        # Simulate the mid-turn state: the longsword attack spent the
        # action and the turn is still open.
        combat.action_weapon_id = "longsword"
        combat.player_budget.action_used = True
        combat.turn_continuation = True
        r2 = resolve_combat_turn(_attack(), mvr_hard, mvr_corpus)
        assert not r2["success"]
        assert "off-hand" in r2["error"]
