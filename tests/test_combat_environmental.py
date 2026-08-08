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

"""Tests for non-combat actions during combat (the open action space).

Covers the engine backstops (talk rejection, weapon-only gear) and the
combat-turn wrapper that routes interact/transfer/rigorous-examine/gear
through the player's combat turn (status tick, positioning, NPC turns).
"""

import random

import pytest

from mgmai.engine.engine import resolve
from mgmai.engine.resolver import resolve_action
from mgmai.models.actions import (
    ExamineAction,
    GearAction,
    InteractAction,
    PositioningAssertion,
    TalkAction,
    TransferAction,
)
from mgmai.models.combat import CombatState
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from tests.helpers import build_state_manager

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def env_corpus() -> ModuleCorpus:
    """A corpus with two enemies, environmental interactions, and gear."""
    return ModuleCorpus.model_validate({
        "adventure": {
            "title": "Combat Environmental",
            "introduction": "Test.",
        },
        "rooms": {
            "room1": {
                "name": "Arena",
                "description": "A fighting pit.",
                "contains": ["goblin", "orc", "lever", "chest"],
                "exits": [
                    {"id": "exit_north", "direction": "north", "target_room": "room2"},
                ],
                "interactions": [
                    {
                        "id": "pull",
                        "description": "Pull the lever.",
                        "result": {
                            "narrative": "The lever clunks.",
                            "set_flag": {"lever_pulled": True},
                        },
                    },
                    {
                        "id": "open_portcullis",
                        "description": "Open the portcullis.",
                        "result": {
                            "narrative": "The portcullis rises — a way out!",
                            "set_player_location": "room2",
                        },
                    },
                    {
                        "id": "struggle",
                        "description": "Force the stuck mechanism.",
                        "check": {
                            "type": "stat_check",
                            "stat": "STR",
                            "target": 15,
                            "repeatable": True,
                        },
                        "success": {"narrative": "You force it open."},
                        "failure": {"narrative": "It won't budge."},
                    },
                ],
            },
            "room2": {
                "name": "Corridor",
                "description": "A corridor.",
            },
        },
        "entities": {
            "goblin": {
                "type": "npc",
                "description": "A scrawny goblin.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Is alive"},
                    "current_hp": {"type": "number", "description": "Current HP"},
                },
                "combat": {
                    "hp": 7,
                    "ac": 12,
                    "atk": 4,
                    "dmg": "1d6+2",
                    "initiative_mod": 2,
                    "flee_dc": 10,
                },
            },
            "orc": {
                "type": "npc",
                "description": "A hulking orc.",
                "state_fields": {
                    "alive": {"type": "boolean", "description": "Is alive"},
                    "current_hp": {"type": "number", "description": "Current HP"},
                },
                "combat": {
                    "hp": 15,
                    "ac": 13,
                    "atk": 5,
                    "dmg": "1d8+3",
                    "initiative_mod": 1,
                    "flee_dc": 12,
                },
            },
            "lever": {
                "type": "item",
                "name": "Lever",
                "description": "A rusty lever.",
            },
            "chest": {
                "type": "item",
                "name": "Chest",
                "description": "A wooden chest.",
                "tags": ["container"],
            },
            "gem": {
                "type": "item",
                "name": "Gem",
                "description": "A shiny gem.",
            },
            "sword": {
                "type": "item",
                "name": "Sword",
                "description": "A longsword.",
                "tags": ["weapon"],
                "equip_block": {
                    "equip_tags": ["weapon", "martial"],
                    "damage_expr": "1d8",
                },
            },
            "dagger": {
                "type": "item",
                "name": "Dagger",
                "description": "A dagger.",
                "tags": ["weapon"],
                "equip_block": {
                    "equip_tags": ["weapon", "simple"],
                    "damage_expr": "1d4",
                },
            },
            "leather_armor": {
                "type": "item",
                "name": "Leather Armor",
                "description": "A leather jerkin.",
                "tags": ["armor"],
                "equip_block": {
                    "equip_tags": ["armor", "light"],
                },
            },
            "shield": {
                "type": "item",
                "name": "Shield",
                "description": "A wooden shield.",
                "tags": ["shield"],
                "equip_block": {
                    "equip_tags": ["shield"],
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
        "flags_declared": ["lever_pulled"],
    })


@pytest.fixture
def env_hard() -> HardGameState:
    """Hard state with the player in room1, mid-fight with the goblin."""
    return HardGameState.model_validate({
        "player": {
            "location": "room1",
            "inventory": {},
            "stats": {
                "STR": 16,
                "DEX": 14,
                "CON": 12,
                "INT": 10,
                "WIS": 8,
                "CHA": 10,
            },
            "level": 1,
            "current_hp": 10,
            "max_hp": 10,
            "ac": 14,
            "proficiency_bonus": 2,
        },
        "flags": {},
        "room_states": {"room1": {"visited": True}},
        "entity_states": {
            "goblin": {"alive": True, "current_hp": 7},
            "orc": {"alive": True, "current_hp": 15},
        },
        "room_contains": {
            "room1": {"goblin": 1, "orc": 1, "lever": 1, "chest": 1},
        },
        "entity_contains": {"chest": {"gem": 1}},
        "turn_count": 0,
    })


def _combat_state(hard: HardGameState) -> CombatState:
    """Put the player mid-combat with the goblin, player acting first."""
    hard.combat = CombatState(
        active=True,
        combatants=["player", "goblin"],
        initiative_order=["player", "goblin"],
        current_index=0,
        round_number=1,
    )
    return hard.combat


def _interact_lever(interaction_id="pull", **kwargs) -> InteractAction:
    return InteractAction(
        action_type="interact",
        target="lever",
        interaction_id=interaction_id,
        detail="I reach for the lever.",
        **kwargs,
    )


# ------------------------------------------------------------------
# Talk is rejected during combat (backstop)
# ------------------------------------------------------------------

class TestTalkDuringCombat:
    def test_talk_rejected(self, env_hard, env_corpus):
        _combat_state(env_hard)
        soft = SoftGameState()
        action = TalkAction(
            action_type="talk",
            target="goblin",
            utterance="Wait — let's talk about this!",
            detail="I try to parley.",
        )
        result = resolve_action(action, env_hard, soft, env_corpus)
        assert not result.success
        assert "during combat" in result.error
        # Dialogue state is untouched and the combat is undisturbed.
        assert soft.dialogue_state.active_npc is None
        assert env_hard.combat is not None and env_hard.combat.active
        assert env_hard.combat.round_number == 1

    def test_talk_allowed_out_of_combat(self, env_hard, env_corpus):
        """The guard does not fire outside combat (presence validation
        fails instead of the combat backstop)."""
        soft = SoftGameState()
        action = TalkAction(
            action_type="talk",
            target="goblin",
            utterance="Hello.",
            detail="I greet the goblin.",
        )
        result = resolve_action(action, env_hard, soft, env_corpus)
        # The goblin has no dialogue block; the point is the failure is
        # NOT the combat backstop.
        assert "during combat" not in (result.error or "")


# ------------------------------------------------------------------
# Gear during combat: weapon swaps only
# ------------------------------------------------------------------

class TestGearDuringCombat:
    def test_weapon_swap_is_free_interaction(self, env_hard, env_corpus, monkeypatch):
        """A weapon swap is the player's one free object interaction per
        turn: it does NOT consume the action, so no NPC turns run and the
        round does not advance — the turn stays open."""
        _combat_state(env_hard)
        env_hard.player.inventory = {"dagger": 1}
        env_hard.player.equipped = ["sword"]

        action = GearAction(
            action_type="gear",
            equip_targets=["dagger"],
            unequip_targets=["sword"],
            detail="I swap my sword for the dagger.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert result.hard_changes.equipped_added == ["dagger"]
        assert result.hard_changes.equipped_removed == ["sword"]
        # The swap itself is logged as the player's (gear) action.
        assert result.combat_log[0].actor == "player"
        assert result.combat_log[0].action == "gear"
        # Free interaction: no NPC turns, no round advance; the turn stays
        # open for the player's real action.
        assert not any(
            e.actor == "goblin" and e.action == "attack" for e in result.combat_log
        )
        assert env_hard.combat.round_number == 1
        assert env_hard.combat.player_budget.free_interaction_used is True
        assert env_hard.combat.turn_continuation is True
        assert result.costs_turn is False

    def test_second_weapon_swap_costs_action(self, env_hard, env_corpus, monkeypatch):
        """A second object interaction in the same turn costs the action
        (Utilize): the swap resolves and NPC turns run."""
        _combat_state(env_hard)
        env_hard.player.inventory = {"dagger": 1}
        env_hard.player.equipped = ["sword"]

        # First swap: the free interaction (turn continues, no NPC turns).
        sm = build_state_manager(env_corpus, hard_state=env_hard)
        first = GearAction(
            action_type="gear",
            equip_targets=["dagger"],
            unequip_targets=["sword"],
            detail="I swap my sword for the dagger.",
        )
        r1 = resolve(first, sm)
        assert r1.success
        assert env_hard.combat.player_budget.free_interaction_used is True
        assert env_hard.combat.round_number == 1
        assert env_hard.player.equipped == ["dagger"]

        # Second swap on the same (continuation) turn: the free interaction
        # is spent, so it costs the action and NPC turns run.
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        second = GearAction(
            action_type="gear",
            equip_targets=["sword"],
            unequip_targets=["dagger"],
            detail="I swap back to the sword.",
        )
        result = resolve(second, sm)
        assert result.success
        assert result.hard_state_changes.equipped_added == ["sword"]
        assert result.hard_state_changes.equipped_removed == ["dagger"]
        # The second interaction consumed the action: NPC turns ran and
        # the round advanced.
        assert any(
            e.actor == "goblin" and e.action == "attack"
            for e in result.combat_log
        )
        assert env_hard.combat.round_number == 2

    def test_gear_with_no_budget_rejected(self, env_hard, env_corpus):
        """No budget left for a gear change (free interaction AND action
        both spent) is rejected — costs nothing."""
        _combat_state(env_hard)
        env_hard.player.inventory = {"dagger": 1}
        env_hard.player.equipped = ["sword"]
        # Mid-turn state: the budget is already spent and the turn is a
        # continuation (so _begin_player_turn does not reset it).
        env_hard.combat.player_budget.free_interaction_used = True
        env_hard.combat.player_budget.action_used = True
        env_hard.combat.turn_continuation = True
        action = GearAction(
            action_type="gear",
            equip_targets=["dagger"],
            unequip_targets=["sword"],
            detail="I swap my sword for the dagger.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert not result.success
        assert "already used this turn" in result.error
        assert env_hard.combat.round_number == 1
        assert env_hard.player.equipped == ["sword"]

    def test_armor_equip_rejected(self, env_hard, env_corpus):
        _combat_state(env_hard)
        env_hard.player.inventory = {"leather_armor": 1}
        action = GearAction(
            action_type="gear",
            equip_targets=["leather_armor"],
            detail="I strap on the armor.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert not result.success
        assert "only weapon swaps" in result.error
        # Rejection costs nothing: no NPC turns, no round advance.
        assert env_hard.combat.round_number == 1

    def test_armor_unequip_rejected(self, env_hard, env_corpus):
        _combat_state(env_hard)
        env_hard.player.equipped = ["leather_armor"]
        action = GearAction(
            action_type="gear",
            unequip_targets=["leather_armor"],
            detail="I shed the armor.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert not result.success
        assert "only weapon swaps" in result.error

    def test_armor_equip_allowed_out_of_combat(self, env_hard, env_corpus):
        env_hard.player.inventory = {"leather_armor": 1}
        action = GearAction(
            action_type="gear",
            equip_targets=["leather_armor"],
            detail="I strap on the armor.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success


# ------------------------------------------------------------------
# Environmental actions run through the combat turn
# ------------------------------------------------------------------

class TestCombatEnvironmental:
    def test_interact_resolves_and_npcs_act(self, env_hard, env_corpus, monkeypatch):
        """Pulling the lever mid-combat fires its Result AND the enemies
        still take their turns; the round advances."""
        _combat_state(env_hard)
        # goblin attacks (15+4=19 vs AC 14, hit) for 1+2=3 damage
        rand_vals = iter([15, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_action(
            _interact_lever(), env_hard, SoftGameState(), env_corpus
        )
        assert result.success
        # The interaction's Result fired.
        assert result.hard_changes.flags_set.get("lever_pulled") is True
        # The player's action is logged for the combat prefix, then the
        # goblin took its turn.
        assert result.combat_log[0].actor == "player"
        assert result.combat_log[0].action == "interact"
        # A room-feature interact is not an item use.
        assert result.combat_log[0].target_is_item is False
        goblin_attacks = [
            e for e in result.combat_log
            if e.actor == "goblin" and e.action == "attack"
        ]
        assert len(goblin_attacks) == 1
        assert result.hard_changes.player_hp_delta == -3
        assert env_hard.combat.round_number == 2

    def test_failed_check_still_consumes_turn(self, env_hard, env_corpus, monkeypatch):
        """A failed interaction *check* is a spent action: NPC turns run."""
        _combat_state(env_hard)
        # player STR check: 5 + 3 = 8 < 15 (fail); goblin misses (1)
        rand_vals = iter([5, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_action(
            _interact_lever("struggle"), env_hard, SoftGameState(), env_corpus
        )
        assert result.success  # check failed, but the resolution succeeded
        assert "won't budge" in (result.triggered_narration or [""])[0]
        assert env_hard.combat.round_number == 2
        assert any(
            e.actor == "goblin" and e.action == "attack" for e in result.combat_log
        )

    def test_failed_validation_does_not_consume_turn(self, env_hard, env_corpus):
        """A failed *validation* (unknown interaction id) never costs a
        turn: no NPC turns, no round advance, nothing logged."""
        _combat_state(env_hard)
        result = resolve_action(
            _interact_lever("nonexistent"), env_hard, SoftGameState(), env_corpus
        )
        assert not result.success
        assert "no defined result" in result.error
        assert env_hard.combat.round_number == 1
        assert env_hard.combat.log == []

    def test_transfer_runs_npc_turns(self, env_hard, env_corpus, monkeypatch):
        """The freeze exploit is closed: taking an item mid-combat lets
        the enemies act."""
        _combat_state(env_hard)
        # goblin attacks: natural 1, miss
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        action = TransferAction(
            action_type="transfer",
            target="chest",
            taken_items=["gem"],
            detail="I grab the gem from the chest.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert result.hard_changes.inventory_added.get("gem") == 1
        assert result.combat_log[0].action == "transfer"
        assert any(
            e.actor == "goblin" and e.action == "attack" for e in result.combat_log
        )
        assert env_hard.combat.round_number == 2

    def test_rigorous_examine_runs_npc_turns(self, env_hard, env_corpus, monkeypatch):
        _combat_state(env_hard)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        action = ExamineAction(
            action_type="examine",
            target="goblin",
            rigorous=True,
            detail="I study the goblin's stance.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert result.combat_log[0].action == "examine"
        assert any(
            e.actor == "goblin" and e.action == "attack" for e in result.combat_log
        )
        assert env_hard.combat.round_number == 2

    def test_casual_examine_stays_free(self, env_hard, env_corpus):
        """Non-rigorous examine does not run NPC turns or advance the round."""
        _combat_state(env_hard)
        action = ExamineAction(
            action_type="examine",
            target="goblin",
            rigorous=False,
            detail="I glance at the goblin.",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert result.combat_log == []
        assert env_hard.combat.round_number == 1

    def test_interact_attack_is_a_normal_combat_attack(
        self, env_hard, env_corpus, monkeypatch
    ):
        """interact/attack during combat is rerouted to a combat attack:
        no re-entry, no initiative reroll, no reinforcement merge."""
        combat = _combat_state(env_hard)
        # player hits (15+5=20 vs AC 12) for 1+3=4; goblin misses (1)
        rand_vals = iter([15, 1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = InteractAction(
            action_type="interact",
            target="goblin",
            interaction_id="attack",
            detail="I strike the goblin!",
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert not result.combat_triggered
        # Same combat object — no re-entry wiped the state.
        assert env_hard.combat is combat
        assert env_hard.combat.initiative_order == ["player", "goblin"]
        assert env_hard.combat.round_number == 2
        assert not any(e.action == "reinforcement" for e in result.combat_log)
        # The attack landed as a normal combat attack.
        assert result.combat_log[0].actor == "player"
        assert result.combat_log[0].action == "attack"
        assert env_hard.entity_states["goblin"]["current_hp"] == 3

    def test_relocation_result_ends_combat_as_fled(self, env_hard, env_corpus):
        """A Result that moves the player to another room ends combat
        immediately (reason 'fled'); no NPC turns run after."""
        _combat_state(env_hard)
        result = resolve_action(
            _interact_lever("open_portcullis"),
            env_hard, SoftGameState(), env_corpus,
        )
        assert result.success
        assert result.hard_changes.player_location == "room2"
        assert env_hard.combat is None
        assert ("combat.ended", {"reason": "fled"}) in result.events
        assert not any(
            e.actor == "goblin" and e.action == "attack" for e in result.combat_log
        )

    def test_start_combat_result_merges_reinforcements(
        self, env_hard, env_corpus, monkeypatch
    ):
        """An encounter trigger fired by an interaction mid-combat merges
        the new enemies into the active fight instead of overwriting it."""
        data = env_corpus.model_dump()
        data["rooms"]["room1"]["reactions"] = [
            {
                "id": "lever_calls_orc",
                "on": "interaction.used",
                "condition": {"require": "event:interaction_id == pull"},
                "effect": {"trigger_encounter": "reinforcements"},
                "phase": "immediate",
            },
        ]
        data["mechanics"] = {
            "reinforcements": {
                "id": "reinforcements",
                "rules": [
                    {
                        "condition": {"require": "entity:orc.alive == true"},
                        "result": {
                            "narrative": "The orc joins the fray!",
                            "start_combat": ["orc"],
                        },
                    },
                ],
            },
        }
        corpus = ModuleCorpus.model_validate(data)

        _combat_state(env_hard)
        # goblin misses (1); orc's merge initiative roll is low (1+1=2)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        sm = build_state_manager(corpus, hard_state=env_hard)
        result = resolve(_interact_lever(), sm)
        assert result.success
        combat = sm.hard_state.combat
        assert combat is not None and combat.active
        # The orc merged into the ongoing fight (acting last on a 2).
        assert combat.combatants == ["player", "goblin", "orc"]
        assert combat.initiative_order == ["player", "goblin", "orc"]
        # The wrapper's round advance happened; the merge did not reset it.
        assert combat.round_number == 2
        # The orc did not act this round (merged after the player's turn).
        assert not any(
            e.actor == "orc" and e.action == "attack" for e in combat.log
        )

    def test_gear_free_interaction_does_not_tick(self, env_hard, env_corpus, monkeypatch):
        """A free-interaction gear swap does NOT cost the turn: no engine
        persistent tick, no turn.end, no turn_count bump — the turn stays
        open for the follow-up action."""
        corpus = env_corpus.model_copy(deep=True)
        from mgmai.models.corpus import StatusEffectDef
        corpus.status_effects["festering_wound"] = StatusEffectDef.model_validate({
            "name": "Festering Wound",
            "scope": "persistent",
            "duration": "rounds",
        })
        _combat_state(env_hard)
        env_hard.player.status_effects = {"festering_wound": 3}
        env_hard.player.inventory = {"dagger": 1}
        env_hard.player.equipped = ["sword"]
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        sm = build_state_manager(corpus, hard_state=env_hard)
        action = GearAction(
            action_type="gear",
            equip_targets=["dagger"],
            unequip_targets=["sword"],
            detail="I swap weapons.",
        )
        result = resolve(action, sm)
        assert result.success
        assert result.costs_turn is False
        assert sm.hard_state.turn_count == 0  # no turn-costing action yet
        assert sm.hard_state.player.status_effects == {"festering_wound": 3}

        # The follow-up main action (an attack) ends the turn: the
        # persistent tick fires exactly once across both engine calls.
        from mgmai.models.actions import CombatAction
        attack = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="I strike the goblin!",
        )
        result2 = resolve(attack, sm)
        assert result2.success
        assert result2.costs_turn is True
        assert sm.hard_state.turn_count == 1
        assert sm.hard_state.player.status_effects == {"festering_wound": 2}


# ------------------------------------------------------------------
# Positioning assertions on interact actions
# ------------------------------------------------------------------

class TestInteractPositioning:
    def test_engage_assertion_applies(self, env_hard, env_corpus, monkeypatch):
        _combat_state(env_hard)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        action = _interact_lever(
            positioning=PositioningAssertion(engage=[["player", "goblin"]]),
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert result.warnings == []
        assert ["goblin", "player"] in env_hard.combat.engagement
        # The interaction itself still resolved.
        assert result.hard_changes.flags_set.get("lever_pulled") is True

    def test_malformed_assertion_degrades_to_warning(
        self, env_hard, env_corpus, monkeypatch
    ):
        """Bad positioning entries warn but never cost the turn."""
        _combat_state(env_hard)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)

        action = _interact_lever(
            positioning=PositioningAssertion(engage=[["player", "nonexistent"]]),
        )
        result = resolve_action(action, env_hard, SoftGameState(), env_corpus)
        assert result.success
        assert any("positioning" in w for w in result.warnings)
        # The interaction resolved and the turn proceeded normally.
        assert result.hard_changes.flags_set.get("lever_pulled") is True
        assert env_hard.combat.round_number == 2
