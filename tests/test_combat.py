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

"""Tests for the combat system: models, dice, initiative, turns, and integration."""

import copy
import json
import random

import pytest

from mgmai.models.actions import (
    CombatAction,
    HardStateChanges,
    InteractAction,
    MoveAction,
    PlayerAction,
    validate_player_action,
)
from mgmai.models.combat import CombatLogEntry, CombatState
from mgmai.models.corpus import (
    CombatBlock,
    EncounterRule,
    Entity,
    ModuleCorpus,
)
from mgmai.models.hard_state import HardGameState, PlayerState
from mgmai.engine.combat import (
    enter_combat,
    get_player_ac,
    get_player_max_hp,
    resolve_combat_turn,
    roll_damage,
    roll_initiative,
)
from mgmai.engine.systems.five_e import FiveESystem
from mgmai.engine.resolver import ResolutionResult, resolve_action
from mgmai.engine.stat_checks import format_combat_prefix


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def combat_npc_corpus() -> ModuleCorpus:
    """A minimal corpus with one room and one combat-capable NPC."""
    return ModuleCorpus.model_validate({
        "adventure": {
            "title": "Test Combat",
            "introduction": "Test.",
        },
        "rooms": {
            "room1": {
                "name": "Test Room",
                "description": "A test room.",
                "contains": ["goblin"],
                "exits": [
                    {"id": "exit_north", "direction": "north", "target_room": "room2"},
                ],
            },
            "room2": {
                "name": "Second Room",
                "description": "Another room.",
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
        },
    })


@pytest.fixture
def combat_hard_state() -> HardGameState:
    """Hard state with player stats suitable for combat."""
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
        },
        "room_contains": {"room1": {"goblin": 1}},
        "turn_count": 0,
    })


# ------------------------------------------------------------------
# 1. CombatBlock model validation
# ------------------------------------------------------------------

class TestCombatBlock:
    def test_default_values(self):
        cb = CombatBlock(hp=5, ac=10, atk=0)
        assert cb.dmg == "1d6"
        assert cb.initiative_mod == 0
        assert cb.flee_dc == 10

    def test_hp_must_be_positive(self):
        with pytest.raises(ValueError):
            CombatBlock(hp=0, ac=10, atk=0)

    def test_non_npc_cannot_have_combat(self, combat_npc_corpus):
        """Entity validation: only NPC type may carry combat."""
        data = combat_npc_corpus.model_dump()
        data["entities"]["player_ent"] = {
            "type": "player",
            "description": "Test player.",
            "combat": {"hp": 10, "ac": 12, "atk": 4},
        }
        with pytest.raises(ValueError, match="Only 'npc' entities may carry combat"):
            ModuleCorpus.model_validate(data)


# ------------------------------------------------------------------
# 2. CombatAction model
# ------------------------------------------------------------------

class TestCombatAction:
    def test_combat_action_parsing(self):
        data = {
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin",
            "detail": "Player swings at the goblin",
        }
        action = validate_player_action(data)
        assert isinstance(action, CombatAction)
        assert action.combat_action == "attack"
        assert action.target == "goblin"

    def test_combat_action_in_player_action_union(self):
        data = {
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin",
            "detail": "Swing!",
        }
        action = PlayerAction.model_validate(data)
        assert isinstance(action, CombatAction)


# ------------------------------------------------------------------
# 3. Damage dice rolling
# ------------------------------------------------------------------

class TestDamageDice:
    def test_roll_damage_range(self, monkeypatch):
        """Damage from 1d6 should be in [1,6]."""
        monkeypatch.setattr(random, "randint", lambda a, b: a)
        total, s = roll_damage("1d6")
        assert total == 1

    def test_roll_damage_critical(self, monkeypatch):
        """Critical hit doubles dice count but modifier applied once."""
        monkeypatch.setattr(random, "randint", lambda a, b: b)
        total, s = roll_damage("1d6+2", critical=True)
        # 2 dice, each max 6, +2 modifier = 14
        assert total == 14


# ------------------------------------------------------------------
# 4. Player stat computation
# ------------------------------------------------------------------

class TestPlayerStats:
    def test_hit_bonus(self, combat_hard_state, combat_npc_corpus):
        # STR 16 → mod +3, proficient +2 → +5
        system = FiveESystem()
        bonus = system.compute_player_attack_bonus(
            combat_hard_state, combat_npc_corpus
        )
        assert bonus == 5

    def test_hit_bonus_no_stats(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.stats = None
        system = FiveESystem()
        bonus = system.compute_player_attack_bonus(hard, combat_npc_corpus)
        assert bonus == 2  # prof only, STR defaults to +0

    def test_damage_unarmed(self, combat_hard_state, combat_npc_corpus):
        # STR 16 → mod +3, no weapon → 1d6+3
        system = FiveESystem()
        expr = system.compute_player_damage_expr(
            combat_hard_state, combat_npc_corpus
        )
        assert expr == "1d6+3"

    def test_damage_with_weapon(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        # Add a weapon entity to corpus
        corpus_dict = combat_npc_corpus.model_dump()
        corpus_dict["entities"]["longsword"] = {
            "type": "item",
            "name": "Longsword",
            "description": "A longsword.",
            "tags": ["weapon"],
        }
        corpus2 = ModuleCorpus.model_validate(corpus_dict)
        hard.player.inventory["longsword"] = 1
        system = FiveESystem()
        expr = system.compute_player_damage_expr(hard, corpus2)
        assert expr == "1d8+3"  # weapon → 1d8 base

    def test_ac_explicit(self, combat_hard_state):
        assert get_player_ac(combat_hard_state) == 14

    def test_ac_computed_from_dex(self):
        hard = HardGameState.model_validate({
            "player": {"location": "room1",
                        "stats": {"DEX": 16}},
        })
        # DEX 16 → mod +3, 10 + 3 = 13
        assert get_player_ac(hard) == 13

    def test_max_hp_explicit(self, combat_hard_state):
        assert get_player_max_hp(combat_hard_state) == 10

    def test_max_hp_computed_from_con(self):
        hard = HardGameState.model_validate({
            "player": {"location": "room1",
                        "stats": {"CON": 14}},
        })
        # CON 14 → mod +2, 8 + 2 = 10
        assert get_player_max_hp(hard) == 10


# ------------------------------------------------------------------
# 5. Initiative
# ------------------------------------------------------------------

class TestInitiative:
    def test_initiative_order_contains_all(self, combat_hard_state, combat_npc_corpus):
        order = roll_initiative(combat_hard_state, combat_npc_corpus, ["goblin"])
        assert "player" in order
        assert "goblin" in order
        assert len(order) == 2

    def test_initiative_order_consistent(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """With deterministic dice, order should be predictable."""
        # player gets roll=15 (DEX mod +2) = 17, goblin gets roll=10 (init_mod +2) = 12
        rolls = iter([15, 10])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))
        monkeypatch.setattr(random, "random", lambda: 0.5)
        order = roll_initiative(combat_hard_state, combat_npc_corpus, ["goblin"])
        assert order[0] == "player"
        assert order[1] == "goblin"


# ------------------------------------------------------------------
# 6. Combat entry
# ------------------------------------------------------------------

class TestCombatEntry:
    def test_enter_combat_creates_state(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        result = enter_combat(["goblin"], hard, combat_npc_corpus)
        assert hard.combat is not None
        assert hard.combat.active
        assert hard.combat.round_number == 1
        assert "player" in hard.combat.combatants
        assert "goblin" in hard.combat.combatants
        assert result["combat_triggered"]

    def test_enter_combat_inits_npc_hp(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        # Remove pre-existing current_hp to test initialization
        hard.entity_states["goblin"].pop("current_hp", None)
        result = enter_combat(["goblin"], hard, combat_npc_corpus)
        assert hard.entity_states["goblin"]["current_hp"] == 7

    def test_enter_combat_inits_player_hp(self, combat_npc_corpus, monkeypatch):
        """Player HP initialises to max_hp even if enemies go first in initiative.

        The goblin's attack roll and initiative rolls are forced to a natural 1
        (automatic miss) so that only the HP initialisation is tested, not the
        RNG-dependent damage resolution.
        """
        # Pin all d20 rolls to 1 (natural miss) and tiebreakers to 0.5 so the
        # HP initialisation assertion isn't polluted by random damage from
        # pre-player NPC turns.
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        hard = HardGameState.model_validate({
            "player": {
                "location": "room1",
                "stats": {"STR": 10, "DEX": 10, "CON": 14},
            },
            "entity_states": {"goblin": {"alive": True}},
        })
        result = enter_combat(["goblin"], hard, combat_npc_corpus)
        # CON 14 → mod +2, 8+2 = 10, set as current_hp
        assert hard.player.current_hp == 10
        assert hard.player.max_hp == 10

    def test_enter_combat_sets_current_index(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """After entry, current_index should point at the player's position."""
        # Force player to go first
        rolls = iter([20, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))
        monkeypatch.setattr(random, "random", lambda: 0.5)
        hard = combat_hard_state.model_copy(deep=True)
        result = enter_combat(["goblin"], hard, combat_npc_corpus)
        assert hard.combat.current_index == 0  # player is first


# ------------------------------------------------------------------
# 7. Combat turn resolution
# ------------------------------------------------------------------

class TestCombatTurn:
    def test_player_attack_hit(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        # Set up a simple combat state with player going first
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

        # player rolls 15 on d20, +5 atk = 20 vs AC 12 → hit
        # damage: use min rolls for deterministic result
        rand_vals = iter([15, 1, 1])  # attack_roll, dmg_die1, npc_attack
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        hc = result["hard_changes"]
        assert hc is not None
        # goblin took damage: 1d6+3 with min roll 1 → 4 damage
        new_hp = hc.entity_state_changes["goblin"]["current_hp"]
        assert new_hp == 3  # 7 - 4 = 3?

    def test_player_attack_kill(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states["goblin"]["current_hp"] = 1
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

        # player hits, damage kills goblin
        rand_vals = iter([15, 6])  # attack_roll, max dmg die
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Finish him!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        hc = result["hard_changes"]
        assert hc.entity_state_changes["goblin"]["alive"] is False
        # combat ended when goblin died (last enemy)
        assert hard.combat is None

    def test_player_attack_miss(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

        # player rolls 1 on d20 → natural 1, auto-miss
        rand_vals = iter([1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Swing!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        # Miss → no damage to goblin
        hc = result["hard_changes"]
        assert "goblin" not in hc.entity_state_changes

    def test_player_nat20_crit(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

        # nat 20 → auto-hit and crit. damage: 2 * 1d6+3
        rand_vals = iter([20, 6, 6, 1])  # attack, 2 dmg dice at max, npc attack
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Crit!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        hc = result["hard_changes"]
        # 2 * 6 + 3 = 15 damage
        assert hc.entity_state_changes["goblin"]["current_hp"] == -8  # 7 - 15
        assert hc.entity_state_changes["goblin"]["alive"] is False

    def test_npc_attack_on_player(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["goblin", "player"],  # goblin goes first
            current_index=0,
            round_number=1,
        )

        # Player misses (roll 1 → auto-miss), then goblin attacks.
        # goblin rolls 12, +4 atk = 16 vs player AC 14 → hit. dmg: 1d6+2
        rand_vals = iter([1, 12, 4])  # player d20, npc d20, npc dmg die
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Fight back!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        hc = result["hard_changes"]
        # goblin dealt 4+2=6 damage → player loses 6 HP
        assert hc.player_hp_delta is not None
        assert hc.player_hp_delta < 0

    def test_combat_log_has_entries(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        rand_vals = iter([15, 3, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert len(result["combat_log"]) >= 1
        player_entry = result["combat_log"][0]
        assert player_entry.actor == "player"
        assert player_entry.action == "attack"

    def test_invalid_target_rejected(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="nonexistent",
            detail="Attack!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert not result["success"]


# ------------------------------------------------------------------
# 8. Fleeing
# ------------------------------------------------------------------

class TestFlee:
    def test_flee_success(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # DEX 14 → mod +2, flee DC 10. Roll 12 + 2 = 14 ≥ 10 → success
        monkeypatch.setattr(random, "randint", lambda a, b: 12)

        action = MoveAction(
            action_type="move",
            target="exit_north",
            detail="Run away!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        # combat ended
        assert hard.combat is None
        # player moved
        assert result["hard_changes"].player_location == "room2"

    def test_flee_failure(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # Roll 1 + 2 = 3 < 10 → fail. Then NPC attacks.
        rand_vals = iter([1, 5, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = MoveAction(
            action_type="move",
            target="exit_north",
            detail="Run!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        # combat still active
        assert hard.combat is not None
        # player did not move
        assert result["hard_changes"].player_location is None

    def test_move_routed_to_combat_flee(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """MoveAction during combat is routed to resolve_combat_turn via resolver."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        monkeypatch.setattr(random, "randint", lambda a, b: 12)

        action = MoveAction(
            action_type="move",
            target="exit_north",
            detail="Run!",
        )
        from mgmai.models.soft_state import SoftGameState
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, combat_npc_corpus)
        assert result.success
        # flee succeeded → combat ended
        assert hard.combat is None


# ------------------------------------------------------------------
# 9. HardStateChanges player_hp_delta
# ------------------------------------------------------------------

class TestHardStateChangesHp:
    def test_player_hp_delta_merge(self):
        a = HardStateChanges(player_hp_delta=-5)
        b = HardStateChanges(player_hp_delta=-3)
        a.merge(b)
        assert a.player_hp_delta == -8

    def test_player_hp_delta_has_changes(self):
        hc = HardStateChanges(player_hp_delta=-5)
        assert hc.has_changes()
        empty = HardStateChanges()
        assert not empty.has_changes()


# ------------------------------------------------------------------
# 10. Resolver integration
# ------------------------------------------------------------------

class TestResolverIntegration:
    def test_combat_action_dispatch(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """resolve_action dispatches combat action type correctly."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        rand_vals = iter([15, 3, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )
        from mgmai.models.soft_state import SoftGameState
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, combat_npc_corpus)
        assert result.success

    def test_interact_attack_starts_combat(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """InteractAction with interaction_id='attack' on NPC with CombatBlock starts combat."""
        hard = combat_hard_state.model_copy(deep=True)
        # goblin has combat block and no attack-triggered encounter reaction
        # → should enter combat directly
        rand_vals = iter([15, 2])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        monkeypatch.setattr(random, "random", lambda: 0.5)

        action = InteractAction(
            action_type="interact",
            target="goblin",
            interaction_id="attack",
            detail="I attack the goblin!",
        )
        from mgmai.models.soft_state import SoftGameState
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, combat_npc_corpus)
        assert result.success
        assert result.combat_triggered
        assert hard.combat is not None


# ------------------------------------------------------------------
# 11. Combat prefix formatting
# ------------------------------------------------------------------

class TestCombatPrefix:
    def test_empty_log(self):
        assert format_combat_prefix([]) == ""

    def test_player_attack_hit_prefix(self):
        log = [{"actor": "player", "action": "attack", "target": "goblin",
                "hit": True, "damage": 4}]
        prefix = format_combat_prefix(log)
        assert "hit" in prefix
        assert "4 damage" in prefix

    def test_player_attack_miss_prefix(self):
        log = [{"actor": "player", "action": "attack", "target": "goblin",
                "hit": False}]
        prefix = format_combat_prefix(log)
        assert "miss" in prefix

    def test_npc_attack_prefix(self):
        log = [{"actor": "goblin", "action": "attack", "target": "player",
                "hit": True, "damage": 6}]
        prefix = format_combat_prefix(log)
        assert "goblin" in prefix
        assert "you" in prefix
        assert "6 damage" in prefix

    def test_death_prefix(self):
        log = [{"actor": "goblin", "action": "death"}]
        prefix = format_combat_prefix(log)
        assert "dead" in prefix.lower()

    def test_flee_success_prefix(self):
        log = [{"actor": "player", "action": "flee", "hit": True}]
        prefix = format_combat_prefix(log)
        assert "break away" in prefix.lower()

    def test_flee_failure_prefix(self):
        log = [{"actor": "player", "action": "flee", "hit": False}]
        prefix = format_combat_prefix(log)
        assert "fail" in prefix.lower()


# ------------------------------------------------------------------
# 12. Save/load with CombatState
# ------------------------------------------------------------------

class TestCombatPersistence:
    def test_combat_state_serializable(self):
        cs = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=3,
            log=[
                CombatLogEntry(
                    round=3,
                    actor="player",
                    action="attack",
                    target="goblin",
                    attack_roll=15,
                    attack_total=20,
                    ac=12,
                    hit=True,
                    damage=4,
                    remaining_hp=3,
                ),
            ],
        )
        data = cs.model_dump(mode="json")
        cs2 = CombatState.model_validate(data)
        assert cs2.active == cs.active
        assert cs2.round_number == 3
        assert cs2.log[0].hit is True
        assert cs2.log[0].damage == 4


class TestCombatEndStates:
    """Combat state transitions: victory, death, flee."""

    def test_all_enemies_dead_ends_combat(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # Roll 20 → crit, max damage dice → kill
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Finishing blow!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        assert result["game_over"] is False
        assert hard.combat is None

    def test_player_death_game_over(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.current_hp = 1
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["goblin", "player"],
            current_index=0,
            round_number=1,
        )
        # Player misses (1), goblin hits hard (20 → crit, max damage: 2d6+2)
        rand_vals = iter([1, 20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Last stand!",
        )
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        assert result["game_over"] is True
        assert hard.combat is None
