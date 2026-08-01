# My GM is AI — Phase 1 action-economy (TurnBudget) tests
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Phase 1 tests for the D&D 5e SRD 5.2.1 action economy.

Covers the §3.3 turn-end rule (auto-end vs. continuation), the
``turn_ended`` -> ``costs_turn`` forwarding (§3.2, including the
engine-layer double-fire regression), the ``turn.start`` continuation
gate, ``wait`` as pass, attack-carried equip/unequip (§4.2),
``interaction_cost: "free"`` (§4.1a), the OA reaction cap (§7), and the
briefing's budget exposure.
"""

import random

import pytest

from mgmai.context.assembler import assemble
from mgmai.engine.combat import (
    legal_bonus_action_ability_ids,
    meaningful_budget_remains,
    resolve_combat_turn,
)
from mgmai.engine.engine import resolve
from mgmai.engine.resolver import resolve_action
from mgmai.llm.ruling_validation import validate_improvised_weapon_budget
from mgmai.models.actions import (
    CombatAction,
    GearAction,
    InteractAction,
    MoveAction,
    PositioningAssertion,
    UseAbilityAction,
    WaitAction,
)
from mgmai.models.combat import CombatState
from mgmai.models.corpus import ModuleCorpus, Reaction, ReactionEffects, Result
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch
from tests.helpers import build_state_manager

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def economy_corpus() -> ModuleCorpus:
    return ModuleCorpus.model_validate({
        "adventure": {"title": "Economy", "introduction": "Test."},
        "rooms": {
            "room1": {
                "name": "Room 1", "description": "A room.",
                "contains": ["goblin", "orc", "sword", "longsword", "potion"],
                "exits": [
                    {"id": "exit_north", "direction": "north", "target_room": "room2"},
                ],
                "interactions": [
                    {
                        "id": "pull",
                        "description": "Pull the lever.",
                        "result": {"narrative": "The lever clunks."},
                    },
                ],
            },
            "room2": {"name": "Room 2", "description": "A corridor."},
        },
        "abilities": {
            "healing_word": {
                "name": "Healing Word",
                "description": "A word of healing.",
                "target": "ally",
                "spell_level": 1,
                "casting_time": "bonus_action",
                "heal": "2d4",
            },
            "quick_missile": {
                "name": "Quick Missile",
                "description": "A swift dart.",
                "target": "enemy",
                "spell_level": 1,
                "casting_time": "bonus_action",
                "auto_damage": {"damage": "3d4+3", "damage_type": "force"},
            },
            "second_wind": {
                "name": "Second Wind",
                "description": "A burst of stamina.",
                "target": "self",
                "uses_per_combat": 1,
                "casting_time": "bonus_action",
                "heal": "1d10",
            },
            "fire_bolt": {
                "name": "Fire Bolt",
                "description": "A mote of fire.",
                "target": "enemy",
                "spell_level": 0,
                "attack": {
                    "stat": "INT", "proficient": True,
                    "damage": "1d10", "damage_type": "fire",
                },
            },
            "magic_missile": {
                "name": "Magic Missile",
                "description": "Three unerring darts.",
                "target": "enemy",
                "spell_level": 1,
                "auto_damage": {"damage": "3d4+3", "damage_type": "force"},
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
                "combat": {"hp": 30, "ac": 12, "atk": 4, "dmg": "1d6+2"},
            },
            "orc": {
                "type": "npc",
                "description": "An orc.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Alive?"},
                    "current_hp": {"type": "number", "description": "HP"},
                },
                "combat": {"hp": 30, "ac": 12, "atk": 4, "dmg": "1d6+2"},
            },
            "sword": {
                "type": "item",
                "name": "Sword",
                "description": "A plain sword.",
                "equip_block": {
                    "equip_tags": ["weapon", "martial"],
                    "damage_expr": "1d6", "damage_type": "slashing",
                },
            },
            "longsword": {
                "type": "item",
                "name": "Longsword",
                "description": "A heavier blade.",
                "equip_block": {
                    "equip_tags": ["weapon", "martial"],
                    "damage_expr": "1d8", "damage_type": "slashing",
                },
            },
            "potion": {
                "type": "item",
                "name": "Potion of Healing",
                "description": "A crimson potion.",
                "interactions": [
                    {
                        "id": "drink",
                        "description": "Drink the potion.",
                        "result": {"narrative": "A warm glow spreads."},
                    },
                ],
            },
            "lever": {
                "type": "item",
                "name": "Lever",
                "description": "A rusty lever.",
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
        "status_effects": {
            "persistent_burn": {
                "name": "Persistent Burn",
                "scope": "persistent",
                "duration": "rounds",
            },
        },
    })


@pytest.fixture
def economy_hard() -> HardGameState:
    return HardGameState.model_validate({
        "player": {
            "location": "room1",
            "inventory": {"sword": 1, "longsword": 1, "potion": 1},
            "equipped": ["sword"],
            "weapon_proficiencies": ["martial"],
            "stats": {
                "STR": 10, "DEX": 14, "CON": 12,
                "INT": 16, "WIS": 10, "CHA": 10,
            },
            "level": 1,
            "current_hp": 10,
            "max_hp": 20,
            "ac": 12,
            "proficiency_bonus": 2,
            "spellcasting_ability": "INT",
            "spell_slots": {1: 3},
            "abilities": [
                "healing_word", "quick_missile", "second_wind",
                "fire_bolt", "magic_missile",
            ],
        },
        "flags": {},
        "room_states": {"room1": {"visited": True}},
        "entity_states": {
            "goblin": {"alive": True, "current_hp": 30},
            "orc": {"alive": True, "current_hp": 30},
        },
        "room_contains": {
            "room1": {"goblin": 1, "orc": 1, "sword": 1, "longsword": 1, "potion": 1},
        },
        "turn_count": 0,
    })


def _combat_state(hard, *combatants) -> CombatState:
    ids = ["player"] + list(combatants)
    hard.combat = CombatState(
        active=True,
        combatants=list(ids),
        initiative_order=list(ids),
        current_index=0,
        round_number=1,
    )
    return hard.combat


def _attack(target="goblin", **kwargs) -> CombatAction:
    return CombatAction(
        action_type="combat", combat_action="attack",
        target=target, detail="Strike!", **kwargs,
    )


def _ability(ability_id, target="player") -> UseAbilityAction:
    return UseAbilityAction(
        action_type="use_ability", ability_id=ability_id,
        target=target, detail="Cast!",
    )


# ------------------------------------------------------------------
# The §3.3 turn-end rule
# ------------------------------------------------------------------


class TestTurnEndRule:
    def test_plain_fighter_attack_auto_ends_turn(self, economy_hard, economy_corpus, monkeypatch):
        """A fighter with no bonus-action option never gets re-prompted:
        the attack closes the turn, NPCs act, the round advances."""
        _combat_state(economy_hard, "goblin")
        # Player with no legal bonus-action ability (remove spells).
        economy_hard.player.abilities = []
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        result = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert result["success"]
        assert result["turn_ended"] is True
        assert economy_hard.combat.player_budget.action_used is True
        assert economy_hard.combat.round_number == 2
        assert not economy_hard.combat.turn_continuation

    def test_action_keeps_turn_open_when_ba_available(self, economy_hard, economy_corpus, monkeypatch):
        """A main action with a legal bonus action still available keeps
        the turn open (SRD-faithful BA ordering)."""
        _combat_state(economy_hard, "goblin")
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        result = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert result["success"]
        assert result["turn_ended"] is False
        budget = economy_hard.combat.player_budget
        assert budget.action_used is True
        assert budget.bonus_action_used is False
        assert economy_hard.combat.turn_continuation is True
        assert economy_hard.combat.round_number == 1

    def test_ba_followed_by_action_closes_turn(self, economy_hard, economy_corpus, monkeypatch):
        """Bonus action then main action: after the second segment no
        meaningful budget remains, so the turn closes and NPCs act."""
        _combat_state(economy_hard, "goblin")
        r1 = resolve_combat_turn(_ability("healing_word"), economy_hard, economy_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is False
        r2 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r2["success"]
        assert r2["turn_ended"] is True
        assert economy_hard.combat.round_number == 2

    def test_action_then_ba_closes_turn(self, economy_hard, economy_corpus, monkeypatch):
        """Main action then bonus action (SRD allows BA after the action):
        the BA closes the turn."""
        _combat_state(economy_hard, "goblin")
        r1 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is False
        r2 = resolve_combat_turn(_ability("healing_word"), economy_hard, economy_corpus)
        assert r2["success"]
        assert r2["turn_ended"] is True
        assert economy_hard.combat.round_number == 2

    def test_leveled_main_spell_blocks_leveled_ba_auto_end(self, economy_hard, economy_corpus):
        """The one-slot rule forbids a leveled BA after a leveled main
        spell, so with no other legal BA the turn auto-ends after the main
        action (no spurious re-prompt)."""
        _combat_state(economy_hard, "goblin")
        # Only magic_missile (level 1 action) + healing_word (level 1 BA).
        economy_hard.player.abilities = ["magic_missile", "healing_word"]
        r1 = resolve_combat_turn(_ability("magic_missile", "goblin"), economy_hard, economy_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is True
        assert economy_hard.combat.player_budget.slot_cast_this_turn is True
        assert economy_hard.combat.round_number == 2

    def test_wait_passes_and_ends_turn(self, economy_hard, economy_corpus, monkeypatch):
        """``wait`` is a pass: it spends nothing but ends the turn even
        when budget remains."""
        _combat_state(economy_hard, "goblin")
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        result = resolve_combat_turn(
            WaitAction(action_type="wait", detail="Hold."),
            economy_hard, economy_corpus,
        )
        assert result["success"]
        assert result["turn_ended"] is True
        assert economy_hard.combat.player_budget.action_used is False
        assert economy_hard.combat.round_number == 2

    def test_budget_resets_next_round(self, economy_hard, economy_corpus, monkeypatch):
        """The budget resets at the start of the player's next turn."""
        _combat_state(economy_hard, "goblin")
        economy_hard.player.abilities = []
        r1 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r1["turn_ended"] is True
        assert economy_hard.combat.round_number == 2
        assert economy_hard.combat.player_budget.action_used is True
        # Round 2: a fresh budget means a second attack is a legal new
        # action, not a rejected "second action".
        r2 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r2["success"]
        assert r2["turn_ended"] is True
        assert economy_hard.combat.round_number == 3

    def test_second_action_rejected(self, economy_hard, economy_corpus, monkeypatch):
        """A second action-costing action on an open turn (action spent,
        turn still open) is rejected and costs nothing."""
        _combat_state(economy_hard, "goblin")
        r1 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r1["turn_ended"] is False  # bonus action still available
        assert economy_hard.combat.player_budget.action_used is True
        r2 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert not r2["success"]
        assert "action was already used" in r2["error"]
        # The rejection cost nothing: no second attack resolved.
        assert economy_hard.combat.round_number == 1
        assert economy_hard.entity_states["goblin"]["current_hp"] == 28

    def test_second_bonus_action_rejected(self, economy_hard, economy_corpus):
        """A second bonus action on an open turn is rejected."""
        _combat_state(economy_hard, "goblin")
        r1 = resolve_combat_turn(_ability("healing_word"), economy_hard, economy_corpus)
        assert r1["turn_ended"] is False
        r2 = resolve_combat_turn(_ability("healing_word"), economy_hard, economy_corpus)
        assert not r2["success"]
        assert "bonus action was already used" in r2["error"]

    def test_free_interaction_alone_keeps_turn_open(self, economy_hard, economy_corpus):
        """A free object interaction taken while the action is still
        unused keeps the turn open for the round's real action."""
        _combat_state(economy_hard, "goblin")
        action = GearAction(
            action_type="gear",
            equip_targets=["longsword"],
            unequip_targets=["sword"],
            detail="I swap my sword for the longsword.",
        )
        result = resolve_action(action, economy_hard, SoftGameState(), economy_corpus)
        assert result.success
        assert result.costs_turn is False
        assert economy_hard.combat.turn_continuation is True
        assert economy_hard.combat.player_budget.free_interaction_used is True


# ------------------------------------------------------------------
# legal_bonus_action_ability_ids / meaningful_budget_remains
# ------------------------------------------------------------------


class TestLegalBonusActions:
    def test_enemy_ba_requires_living_enemy(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        # No allies in this fight: the ally-targeted BA is not legal.
        assert "healing_word" not in legal
        assert "quick_missile" in legal
        assert "second_wind" in legal
        # Kill the only enemy: enemy-targeted BAs drop out.
        economy_hard.entity_states["goblin"]["current_hp"] = 0
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "quick_missile" not in legal
        assert "second_wind" in legal  # self always available

    def test_ally_ba_requires_living_ally(self, economy_hard, economy_corpus):
        """An ally-targeted bonus action is legal only with a living ally
        on the player's side (the §3.3 cheap roster check)."""
        combat = _combat_state(economy_hard, "goblin", "orc")
        # The orc fights on the player's side.
        combat.allies = ["orc"]
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "healing_word" in legal
        # The ally drops: the ally-targeted BA is no longer legal.
        economy_hard.entity_states["orc"]["current_hp"] = 0
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "healing_word" not in legal

    def test_uses_exhausted_ba_not_legal(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.combat.ability_uses.setdefault("player", {})["second_wind"] = 1
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "second_wind" not in legal

    def test_slot_rule_blocks_leveled_ba(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.combat.player_budget.slot_cast_this_turn = True
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "healing_word" not in legal
        assert "quick_missile" not in legal
        assert "second_wind" in legal  # not a spell: no slot axis

    def test_no_slot_remaining_ba_not_legal(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.player.spell_slots = {1: 0}
        legal = legal_bonus_action_ability_ids(economy_hard.combat, economy_hard, economy_corpus)
        assert "healing_word" not in legal

    def test_meaningful_budget_rule(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        budget = economy_hard.combat.player_budget
        assert meaningful_budget_remains(economy_hard.combat, economy_hard, economy_corpus) is True
        budget.action_used = True
        assert meaningful_budget_remains(economy_hard.combat, economy_hard, economy_corpus) is True
        budget.bonus_action_used = True
        assert meaningful_budget_remains(economy_hard.combat, economy_hard, economy_corpus) is False


# ------------------------------------------------------------------
# §3.2 engine-layer regression: BA turn spanning two engine calls
# ------------------------------------------------------------------


class TestEngineTurnEconomy:
    """The double-fire regression: a BA turn that spans two engine calls
    must tick persistent status effects, fire ``turn.end``, and bump
    ``turn_count`` exactly once — and fire ``turn.start`` exactly once."""

    @pytest.fixture
    def engine_sm(self, economy_corpus, economy_hard):
        sm = build_state_manager(economy_corpus, hard_state=economy_hard)
        _combat_state(sm.hard_state, "goblin")
        sm.hard_state.player.status_effects = {"persistent_burn": 3}
        sm.corpus.rooms["room1"].reactions.extend([
            Reaction(
                id="r_adventure_start",
                on="adventure.start",
                effect=ReactionEffects(result=Result(narrative="GAME START MARKER")),
            ),
            Reaction(
                id="r_turn_start",
                on="turn.start",
                effect=ReactionEffects(result=Result(narrative="START MARKER")),
            ),
            Reaction(
                id="r_turn_end",
                on="turn.end",
                effect=ReactionEffects(result=Result(narrative="END MARKER")),
            ),
        ])
        return sm

    def test_ba_turn_ticks_and_fires_turn_events_once(self, engine_sm, monkeypatch):
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        # BA cast: the turn stays open, so nothing fires at the engine layer.
        r1 = resolve(_ability("healing_word"), engine_sm)
        assert r1.success
        assert r1.costs_turn is False
        assert engine_sm.hard_state.turn_count == 0
        assert engine_sm.hard_state.player.status_effects == {"persistent_burn": 3}
        assert "START MARKER" in r1.triggered_narration
        # Exactly once: a double turn.start dispatch within the call must
        # not pass (membership alone would not catch it).
        assert r1.triggered_narration.count("START MARKER") == 1
        assert not any("END MARKER" in n for n in r1.triggered_narration)
        assert r1.triggered_narration.count("GAME START MARKER") == 1

        # Main action (the closing segment): exactly one of each.
        r2 = resolve(_attack(), engine_sm)
        assert r2.success
        assert r2.costs_turn is True
        assert engine_sm.hard_state.turn_count == 1
        assert engine_sm.hard_state.player.status_effects == {"persistent_burn": 2}
        assert "END MARKER" in r2.triggered_narration
        # The continuation call did NOT re-fire turn.start — or the
        # game-start dispatch (turn_count is still 0 mid-turn).
        assert not any("START MARKER" in n for n in r2.triggered_narration)
        assert not any("GAME START MARKER" in n for n in r2.triggered_narration)

    def test_cross_round_chain_each_link_costs_one_turn(self, engine_sm, monkeypatch):
        """'attack, then drink potion' across two rounds: a chain whose
        links each end their own turn must NOT be conflated with the
        continuation path — each link costs exactly one turn."""
        engine_sm.hard_state.player.abilities = []  # no BA: attack closes round 1
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        r1 = resolve(_attack(), engine_sm)
        assert r1.costs_turn is True
        assert engine_sm.hard_state.turn_count == 1
        # Second link, next round: drinking the potion costs another turn.
        drink = InteractAction(
            action_type="interact",
            target="potion",
            interaction_id="drink",
            detail="I drink the potion.",
        )
        r2 = resolve(drink, engine_sm)
        assert r2.success
        assert r2.costs_turn is True
        assert engine_sm.hard_state.turn_count == 2


# ------------------------------------------------------------------
# §4.2 attack-carried equip/unequip
# ------------------------------------------------------------------


class TestAttackCarriedEquip:
    def test_equip_and_attack_with_drawn_weapon(self, economy_hard, economy_corpus, monkeypatch):
        """Drawing a weapon as part of an attack uses that weapon's damage,
        costs only the free interaction, and is a single ruling."""
        _combat_state(economy_hard, "goblin")
        # Start unarmed: the gear model conflicts weapons sharing the
        # "weapon" slot, so drawing onto an equipped weapon is not expressible.
        economy_hard.player.equipped = []
        economy_hard.player.inventory = {"longsword": 1}
        # Rolls read as (sides - 1): d20 -> 19 (hit, no crit), so the
        # damage die decides: longsword 1d8 -> 7, unarmed 1d6 -> 5.  The
        # assertion below only holds if the drawn longsword was used.
        monkeypatch.setattr(random, "randint", lambda a, b: b - 1)

        result = resolve_combat_turn(
            _attack(equip_target="longsword"), economy_hard, economy_corpus
        )
        assert result["success"]
        # The swap applied immediately and the drawn weapon dealt damage.
        assert economy_hard.player.equipped == ["longsword"]
        assert "longsword" not in economy_hard.player.inventory
        assert economy_hard.entity_states["goblin"]["current_hp"] == 30 - 7
        budget = economy_hard.combat.player_budget
        assert budget.action_used is True
        assert budget.free_interaction_used is True
        # The turn stays open: the caster still has legal bonus actions.
        assert economy_hard.combat.turn_continuation is True

    def test_unequip_then_attack_unarmed(self, economy_hard, economy_corpus, monkeypatch):
        _combat_state(economy_hard, "goblin")
        economy_hard.player.abilities = []
        # Player sheathes the sword and attacks unarmed (1d6 + STR 0).
        # Attack 10 + 2 = 12 vs AC 12 -> hit; 1d6 = 3.
        rand_vals = iter([10, 3, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(
            _attack(unequip_target="sword"), economy_hard, economy_corpus
        )
        assert result["success"]
        assert economy_hard.player.equipped == []
        assert "sword" in economy_hard.player.inventory
        assert economy_hard.entity_states["goblin"]["current_hp"] == 27
        assert economy_hard.combat.player_budget.free_interaction_used is True

    def test_invalid_equip_rejected_costs_nothing(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        result = resolve_combat_turn(
            _attack(equip_target="potion"), economy_hard, economy_corpus
        )
        assert not result["success"]
        assert "only weapon swaps" in result["error"]
        assert economy_hard.combat.round_number == 1
        assert economy_hard.combat.player_budget.action_used is False

    def test_equip_with_attack_rejected_when_free_interaction_spent(self, economy_hard, economy_corpus):
        """Engine-layer backstop (bypassing ruling validation): an
        attack-carried equip when the free interaction is already spent is
        rejected and costs nothing."""
        _combat_state(economy_hard, "goblin")
        economy_hard.combat.player_budget.free_interaction_used = True
        economy_hard.combat.turn_continuation = True
        result = resolve_combat_turn(
            _attack(unequip_target="sword"), economy_hard, economy_corpus
        )
        assert not result["success"]
        assert "free object interaction" in result["error"]
        assert economy_hard.player.equipped == ["sword"]
        assert economy_hard.combat.player_budget.action_used is False
        assert economy_hard.entity_states["goblin"]["current_hp"] == 30

    def test_attack_carried_equip_fires_equipment_changed(self, economy_hard, economy_corpus, monkeypatch):
        """The swap's ``equipment.changed`` event is not lost: deferred
        reactions to it fire at end of turn (§4.2)."""
        sm = build_state_manager(economy_corpus, hard_state=economy_hard)
        _combat_state(sm.hard_state, "goblin")
        sm.corpus.rooms["room1"].reactions.append(
            Reaction(
                id="r_equip",
                on="equipment.changed",
                effect=ReactionEffects(
                    result=Result(
                        narrative="EQUIP MARKER",
                        set_flag={"sword_drawn": True},
                    )
                ),
            )
        )
        sm.hard_state.player.equipped = []
        sm.hard_state.player.inventory = {"longsword": 1}
        monkeypatch.setattr(random, "randint", lambda a, b: b - 1)

        result = resolve(
            _attack(equip_target="longsword"), sm,
        )
        assert result.success
        assert "EQUIP MARKER" in result.triggered_narration
        assert sm.hard_state.flags.get("sword_drawn") is True


class TestFleeBudget:
    def test_flee_rejected_after_action_spent(self, economy_hard, economy_corpus, monkeypatch):
        """Fleeing consumes the whole turn: it cannot follow another
        action in the same turn."""
        _combat_state(economy_hard, "goblin")
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        r1 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r1["turn_ended"] is False  # BA available: turn still open
        flee = MoveAction(
            action_type="move", target="exit_north", detail="I run!"
        )
        r2 = resolve_combat_turn(flee, economy_hard, economy_corpus)
        assert not r2["success"]
        assert "cannot flee" in r2["error"]
        assert economy_hard.player.location == "room1"

    def test_flee_allowed_after_bonus_action(self, economy_hard, economy_corpus, monkeypatch):
        """A flee attempt is still whole-turn, but legal after a bonus
        action (the action is unspent); on a failed check the remaining
        budget is forfeited."""
        _combat_state(economy_hard, "goblin")
        r1 = resolve_combat_turn(_ability("second_wind"), economy_hard, economy_corpus)
        assert r1["success"]
        assert r1["turn_ended"] is False
        # Failed flee (roll 1 vs DC 10): the whole turn is consumed.
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        flee = MoveAction(
            action_type="move", target="exit_north", detail="I run!"
        )
        r2 = resolve_combat_turn(flee, economy_hard, economy_corpus)
        assert r2["success"]
        assert r2["turn_ended"] is True
        assert economy_hard.combat.round_number == 2


# ------------------------------------------------------------------
# §4.1a interaction_cost: "free"
# ------------------------------------------------------------------


class TestInteractionCost:
    def test_free_interact_keeps_turn_open(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.room_contains["room1"]["lever"] = 1
        economy_hard.player.inventory = {}
        action = InteractAction(
            action_type="interact",
            target="lever",
            interaction_id="pull",
            interaction_cost="free",
            detail="I pull the lever.",
        )
        result = resolve_action(action, economy_hard, SoftGameState(), economy_corpus)
        assert result.success
        assert result.costs_turn is False
        assert economy_hard.combat.turn_continuation is True
        assert economy_hard.combat.player_budget.free_interaction_used is True
        assert economy_hard.combat.round_number == 1

    def test_free_interact_when_free_used_rejected(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.room_contains["room1"]["lever"] = 1
        economy_hard.combat.player_budget.free_interaction_used = True
        economy_hard.combat.turn_continuation = True
        action = InteractAction(
            action_type="interact",
            target="lever",
            interaction_id="pull",
            interaction_cost="free",
            detail="I pull the lever.",
        )
        result = resolve_action(action, economy_hard, SoftGameState(), economy_corpus)
        assert not result.success
        assert "free object interaction" in result.error

    def test_potion_cannot_be_free(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        action = InteractAction(
            action_type="interact",
            target="potion",
            interaction_id="drink",
            interaction_cost="free",
            detail="I drink the potion.",
        )
        result = resolve_action(action, economy_hard, SoftGameState(), economy_corpus)
        assert not result.success
        assert "always require an action" in result.error

    def test_action_cost_interact_ends_turn(self, economy_hard, economy_corpus, monkeypatch):
        _combat_state(economy_hard, "goblin")
        economy_hard.player.abilities = []
        economy_hard.room_contains["room1"]["lever"] = 1
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        action = InteractAction(
            action_type="interact",
            target="lever",
            interaction_id="pull",
            detail="I pull the lever.",
        )
        result = resolve_action(action, economy_hard, SoftGameState(), economy_corpus)
        assert result.success
        assert result.costs_turn is True
        assert economy_hard.combat.round_number == 2


# ------------------------------------------------------------------
# §7 reaction cap on opportunity attacks
# ------------------------------------------------------------------


class TestReactionCap:
    def test_player_cannot_oa_twice(self, economy_hard, economy_corpus, monkeypatch):
        """The player's single reaction blocks a second opportunity attack
        in the same round."""
        _combat_state(economy_hard, "goblin", "orc")
        combat = economy_hard.combat
        combat.engagement = [["goblin", "player"], ["orc", "player"]]
        economy_hard.player.abilities = []
        # The goblin and orc both leave the player's reach; the player can
        # OA only one of them (one reaction per round).
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        action = _attack("goblin", positioning=PositioningAssertion(
            disengage=[["goblin", "player"], ["orc", "player"]],
        ))
        result = resolve_combat_turn(action, economy_hard, economy_corpus)
        assert result["success"]
        oas = [
            e for e in result["combat_log"]
            if e.action == "opportunity_attack" and e.actor == "player"
        ]
        assert len(oas) == 1
        assert "player" in economy_hard.combat.reactions_spent

    def test_player_reaction_resets_next_turn(self, economy_hard, economy_corpus, monkeypatch):
        _combat_state(economy_hard, "goblin", "orc")
        combat = economy_hard.combat
        combat.engagement = [["goblin", "player"], ["orc", "player"]]
        economy_hard.player.abilities = []
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        r1 = resolve_combat_turn(
            _attack("goblin", positioning=PositioningAssertion(
                disengage=[["goblin", "player"], ["orc", "player"]],
            )),
            economy_hard, economy_corpus,
        )
        assert r1["success"]
        assert "player" in economy_hard.combat.reactions_spent
        assert economy_hard.combat.round_number == 2
        # Next round: the player's reaction refreshed at turn start.
        combat.engagement = [["goblin", "player"], ["orc", "player"]]
        r2 = resolve_combat_turn(
            _attack("goblin", positioning=PositioningAssertion(
                disengage=[["goblin", "player"], ["orc", "player"]],
            )),
            economy_hard, economy_corpus,
        )
        assert r2["success"]
        oas = [
            e for e in r2["combat_log"]
            if e.action == "opportunity_attack" and e.actor == "player"
        ]
        assert len(oas) == 1

    def test_npc_oa_and_reaction_reset_at_own_turn(self, economy_hard, economy_corpus, monkeypatch):
        """A goblin that OAs the player spends its reaction; its batched
        turn (same round) resets it."""
        _combat_state(economy_hard, "goblin")
        economy_hard.player.abilities = []
        economy_hard.combat.engagement = [["player", "goblin"]]
        # The player leaves the goblin's reach: the goblin OAs (1 = miss).
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        r1 = resolve_combat_turn(
            _attack("goblin", positioning=PositioningAssertion(
                disengage=[["player", "goblin"]],
            )),
            economy_hard, economy_corpus,
        )
        assert r1["success"]
        oas = [
            e for e in r1["combat_log"]
            if e.action == "opportunity_attack" and e.actor == "goblin"
        ]
        assert len(oas) == 1
        # The goblin's own batched turn reset its reaction this round; the
        # player never spent theirs (they made no OA).
        assert "goblin" not in economy_hard.combat.reactions_spent
        assert economy_hard.combat.reactions_spent == set()


# ------------------------------------------------------------------
# Briefing budget exposure (§8 item 7)
# ------------------------------------------------------------------


class TestBriefingBudget:
    def test_briefing_exposes_remaining_budget(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        briefing = assemble(economy_corpus, economy_hard, SoftGameState(), "I act.")
        combat = briefing.combat_state
        assert combat is not None
        assert combat.action_available is True
        assert combat.bonus_action_available is True
        # Solo fight: enemy- and self-targeted BAs are legal options; the
        # ally-targeted healing_word is not (no living ally).
        assert "quick_missile" in combat.bonus_action_options
        assert "second_wind" in combat.bonus_action_options
        assert "healing_word" not in combat.bonus_action_options
        assert combat.free_interaction_available is True
        assert combat.reaction_available is True

    def test_briefing_budget_after_action(self, economy_hard, economy_corpus, monkeypatch):
        _combat_state(economy_hard, "goblin")
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        r1 = resolve_combat_turn(_attack(), economy_hard, economy_corpus)
        assert r1["turn_ended"] is False
        briefing = assemble(economy_corpus, economy_hard, SoftGameState(), "I act.")
        combat = briefing.combat_state
        assert combat.action_available is False
        assert combat.bonus_action_available is True
        assert combat.free_interaction_available is True
        # The bonus action is still available for the next segment.
        assert "second_wind" in combat.bonus_action_options


# ------------------------------------------------------------------
# §4.3 improvised-weapon pickup consumes an object interaction
# ------------------------------------------------------------------


class TestImprovisedPickupBudget:
    def test_ruling_validation_flags_pickup_with_no_budget(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        economy_hard.combat.player_budget.free_interaction_used = True
        economy_hard.combat.player_budget.action_used = True
        briefing = assemble(economy_corpus, economy_hard, SoftGameState(), "I grab a rock.")
        action = WaitAction(
            action_type="wait",
            detail="I grab a rock.",
            soft_state_patches=[
                SoftStatePatch(
                    field="set_improvised_weapon",
                    new_value={"keyword": "light", "description": "a rock"},
                    reason="Picking up a rock as a weapon.",
                )
            ],
        )
        error = validate_improvised_weapon_budget(action, briefing)
        assert error is not None
        assert "object interaction" in error

    def test_ruling_validation_allows_pickup_with_budget(self, economy_hard, economy_corpus):
        _combat_state(economy_hard, "goblin")
        briefing = assemble(economy_corpus, economy_hard, SoftGameState(), "I grab a rock.")
        action = WaitAction(
            action_type="wait",
            detail="I grab a rock.",
            soft_state_patches=[
                SoftStatePatch(
                    field="set_improvised_weapon",
                    new_value={"keyword": "light", "description": "a rock"},
                    reason="Picking up a rock as a weapon.",
                )
            ],
        )
        assert validate_improvised_weapon_budget(action, briefing) is None

    def test_engine_backstop_rejects_pickup_when_both_budgets_spent(self, economy_hard, economy_corpus):
        """The engine-level soft-patch backstop rejects the pickup and lets
        the (wait) action proceed."""
        sm = build_state_manager(economy_corpus, hard_state=economy_hard)
        _combat_state(sm.hard_state, "goblin")
        sm.hard_state.combat.player_budget.free_interaction_used = True
        sm.hard_state.combat.player_budget.action_used = True
        sm.hard_state.combat.turn_continuation = True
        action = WaitAction(
            action_type="wait",
            detail="I grab a rock.",
            soft_state_patches=[
                SoftStatePatch(
                    field="set_improvised_weapon",
                    new_value={"keyword": "light", "description": "a rock"},
                    reason="Picking up a rock as a weapon.",
                )
            ],
        )
        result = resolve(action, sm)
        assert result.success
        assert result.soft_state_patches_applied == []
        assert result.soft_state_patches_rejected
        assert "object interaction" in result.soft_state_patches_rejected[0]["reason"]

    def _pickup_wait(self) -> WaitAction:
        return WaitAction(
            action_type="wait",
            detail="I grab a rock.",
            soft_state_patches=[
                SoftStatePatch(
                    field="set_improvised_weapon",
                    new_value={"keyword": "light", "description": "a rock"},
                    reason="Picking up a rock as a weapon.",
                )
            ],
        )

    def test_accepted_pickup_consumes_free_interaction(self, economy_hard, economy_corpus):
        """An accepted pickup (applied patch) consumes the free object
        interaction (§4.3)."""
        sm = build_state_manager(economy_corpus, hard_state=economy_hard)
        _combat_state(sm.hard_state, "goblin")
        result = resolve(self._pickup_wait(), sm)
        assert result.success
        assert result.soft_state_patches_applied
        budget = sm.hard_state.combat.player_budget
        assert budget.free_interaction_used is True
        assert budget.action_used is False

    def test_pickup_falls_back_to_action_when_free_spent(self, economy_hard, economy_corpus):
        """With the free interaction already spent, an accepted pickup
        consumes the action instead (§4.3)."""
        sm = build_state_manager(economy_corpus, hard_state=economy_hard)
        _combat_state(sm.hard_state, "goblin")
        # Mid-turn state (continuation): the preset survives
        # _begin_player_turn's budget reset.
        sm.hard_state.combat.player_budget.free_interaction_used = True
        sm.hard_state.combat.turn_continuation = True
        result = resolve(self._pickup_wait(), sm)
        assert result.success
        assert result.soft_state_patches_applied
        assert sm.hard_state.combat.player_budget.action_used is True


# ------------------------------------------------------------------
# hit_bonus scoping with an explicit weapon_id
# ------------------------------------------------------------------


class TestWeaponIdHitBonus:
    def test_hit_bonus_scoped_to_attacking_weapon(self, economy_hard, economy_corpus):
        """With an explicit ``weapon_id`` only that weapon's ``hit_bonus``
        applies; a second equipped weapon must not leak its bonus into the
        attack.  (Co-equipped weapons are not reachable through gear
        validation in Phase 1, so the state is set up directly.)"""
        from mgmai.engine.systems import get_system_for_corpus

        economy_hard.player.equipped = ["sword", "longsword"]
        economy_corpus.entities["longsword"].equip_block.hit_bonus = 3
        system = get_system_for_corpus(economy_corpus)
        # STR 10 -> +0, proficient -> +2.
        base = system.compute_player_attack_bonus(economy_hard, economy_corpus)
        scoped = system.compute_player_attack_bonus(
            economy_hard, economy_corpus, weapon_id="sword"
        )
        assert base == 0 + 2 + 3  # historical sum over all equipped weapons
        assert scoped == 0 + 2  # only the attacking sword's bonus (0)
