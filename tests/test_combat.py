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
    CombatAIBlock,
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
    resolve_combat_enemies,
    resolve_combat_turn,
    roll_damage,
    roll_initiative,
)
from mgmai.models.soft_state import SoftGameState
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


class TestOnHitEffects:
    """On-hit effects now resolve through CheckResolution in the combat manager."""

    def _add_on_hit(self, corpus: ModuleCorpus, effects: list[dict]) -> ModuleCorpus:
        data = corpus.model_dump()
        data["stats"] = {
            "definitions": {
                "STR": {"name": "Strength"},
                "DEX": {"name": "Dexterity"},
                "CON": {"name": "Constitution"},
                "INT": {"name": "Intelligence"},
                "WIS": {"name": "Wisdom"},
                "CHA": {"name": "Charisma"},
            },
            "system": "5e",
        }
        data["entities"]["goblin"]["combat"]["on_hit_effects"] = effects
        return ModuleCorpus.model_validate(data)

    def _goblin_first_combat(self, hard: HardGameState) -> None:
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["goblin", "player"],
            current_index=0,
            round_number=1,
        )

    def _player_action(self) -> CombatAction:
        return CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )

    def _goblin_attack_entry(self, result: dict) -> CombatLogEntry:
        """Return the goblin's attack entry (NPC turn follows player turn)."""
        return result["combat_log"][1]

    def test_on_hit_half_save_made(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist.", "player_damage": "half(1d8)"},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        # player misses (1), goblin hits (15+4=19) base dmg 1+2=3,
        # save roll 10 (+1 mod +2 prof =13) success, on-hit roll 5 -> half=2.
        rand_vals = iter([1, 15, 1, 10, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["success"]
        assert result["hard_changes"].player_hp_delta == -5  # 3 base + 2 on-hit
        attack_entry = self._goblin_attack_entry(result)
        assert len(attack_entry.on_hit_effects) == 1
        assert attack_entry.on_hit_effects[0]["save_success"] is True
        assert attack_entry.on_hit_effects[0]["damage"] == 2

    def test_on_hit_half_save_failed(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist.", "player_damage": "half(1d8)"},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 5 (+3 =8) fail, on-hit roll 5 -> full=5.
        rand_vals = iter([1, 15, 1, 5, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -8  # 3 base + 5 on-hit
        attack_entry = self._goblin_attack_entry(result)
        assert attack_entry.on_hit_effects[0]["save_success"] is False
        assert attack_entry.on_hit_effects[0]["damage"] == 5

    def test_on_hit_none_save_made(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist."},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        rand_vals = iter([1, 15, 1, 10])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -3  # base only
        assert self._goblin_attack_entry(result).on_hit_effects[0]["damage"] == 0

    def test_on_hit_full_always_damages(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist.", "player_damage": "1d8"},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        rand_vals = iter([1, 15, 1, 10, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -7  # 3 + 4

    def test_on_hit_multiple_effects_sum(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        effect = {
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "success": {"player_damage": "half(1d8)"},
            "failure": {"player_damage": "1d8"},
        }
        corpus = self._add_on_hit(combat_npc_corpus, [effect, effect])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, two save successes + half damages
        rand_vals = iter([1, 15, 1, 10, 5, 10, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -7  # 3 + 2 + 2
        assert len(self._goblin_attack_entry(result).on_hit_effects) == 2

    def test_on_hit_sets_flag(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "failure": {"set_flag": {"poisoned": True}},
            "success": {},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 5 (+1 =6) fail
        rand_vals = iter([1, 15, 1, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].flags_set.get("poisoned") is True

    def test_on_hit_proficiency_applied(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.save_proficiencies = ["CON"]
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 8,
                "proficiency": "save", "repeatable": False,
            },
            "success": {},
            "failure": {"player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 6 + CON mod +1 + prof +2 = 9 >= 8 success
        rand_vals = iter([1, 15, 1, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -3  # base only
        assert self._goblin_attack_entry(result).on_hit_effects[0]["save_success"] is True

    def test_on_hit_death_from_secondary_damage(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.current_hp = 4
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "failure": {"player_damage": "1d8"},
            "success": {},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save fail, on-hit dmg 5 -> total 8 -> death
        rand_vals = iter([1, 15, 1, 5, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["game_over"] is True
        assert any(entry.action == "death" for entry in result["combat_log"])

    def test_on_hit_log_entry_shape(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"player_damage": "half(1d8)"},
            "failure": {"player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 10 (+1 =11) success, half damage roll 5 -> 2
        rand_vals = iter([1, 15, 1, 10, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        entry = self._goblin_attack_entry(result).on_hit_effects[0]
        assert entry["save_stat"] == "CON"
        assert entry["save_dc"] == 10
        assert entry["save_roll"] == 10
        assert entry["save_total"] == 11
        assert entry["save_success"] is True
        assert entry["damage_expr"] == "half(1d8)"
        assert entry["damage"] == 2
        assert entry["damage_type"] == "poison"

    def test_on_hit_alters_stat(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "failure": {"alter_stat": {"STR": {"value": -2}}},
            "success": {},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 5 (+1 =6) fail -> STR drain
        rand_vals = iter([1, 15, 1, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].stat_modifiers["STR"].value == -2

    def test_on_hit_game_over_result(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """An on-hit failure branch that sets game_over ends the game (save-or-die)."""
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "failure": {
                "narrative": "The venom stops your heart.",
                "game_over": {"type": "lose", "trigger_id": "poison_death"},
            },
            "success": {},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3 (player survives at 7), save fail -> game_over
        rand_vals = iter([1, 15, 1, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["game_over"] is True
        assert hard.game_over is not None
        assert hard.game_over.type == "lose"

    def test_on_hit_nested_then_check(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A then_check on an on-hit branch resolves and stacks its damage."""
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "success": {},
            "failure": {
                "player_damage": "1d8",
                "then_check": {
                    "check": {
                        "type": "stat_check", "stat": "DEX", "target": 10,
                        "repeatable": False,
                    },
                    "success": {},
                    "failure": {"player_damage": "1d8"},
                },
            },
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, CON save 5 (+1=6) fail -> 1d8=2,
        # then DEX save 5 (+2=7) fail -> 1d8=2. On-hit total 4, grand total 7.
        rand_vals = iter([1, 15, 1, 5, 2, 5, 2])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -7  # 3 base + 2 + 2 nested
        entry = self._goblin_attack_entry(result).on_hit_effects[0]
        assert entry["save_success"] is False
        assert entry["damage"] == 4  # primary + then_check damage combined

    def test_on_hit_proficiency_stacks_with_modifier(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A save-proficient player gets check.modifier AND the proficiency bonus."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.save_proficiencies = ["CON"]
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 14,
                "modifier": 2, "proficiency": "save", "repeatable": False,
            },
            "success": {},
            "failure": {"player_damage": "1d8"},
        }])
        self._goblin_first_combat(hard)
        # player misses, goblin hits base dmg 3, save roll 9 + CON +1 + modifier +2
        # + prof +2 = 14 >= 14 success (would be 12 < 14 without both bonuses)
        rand_vals = iter([1, 15, 1, 9])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = resolve_combat_turn(self._player_action(), hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -3  # base only, save made
        assert self._goblin_attack_entry(result).on_hit_effects[0]["save_success"] is True

    def test_enter_combat_resolves_on_hit(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """On-hit effects resolve during the pre-player NPC loop in enter_combat."""
        hard = combat_hard_state.model_copy(deep=True)
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist.", "player_damage": "half(1d8)"},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }])
        monkeypatch.setattr(random, "random", lambda: 0.5)
        # player init 1 (+2 =3), goblin init 20 (+2 =22) -> goblin first,
        # goblin attack 15 (+4=19) hit, base dmg 1 (+2=3), save 5 (+1=6) fail,
        # on-hit 1d8=4 -> total 7.
        rand_vals = iter([1, 20, 15, 1, 5, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        result = enter_combat(["goblin"], hard, corpus, soft=SoftGameState())
        assert result["hard_changes"].player_hp_delta == -7  # 3 base + 4 on-hit
        attack_entry = next(
            (e for e in result["combat_log"] if e.action == "attack"), None
        )
        assert attack_entry is not None
        assert len(attack_entry.on_hit_effects) == 1
        assert attack_entry.on_hit_effects[0]["save_success"] is False
        assert attack_entry.on_hit_effects[0]["damage"] == 4

    def test_on_hit_format_prefix(self):
        log = [{
            "actor": "goblin", "action": "attack", "target": "player",
            "hit": True, "damage": 3,
            "on_hit_effects": [
                {"save_stat": "CON", "save_success": True, "damage": 2,
                 "damage_type": "poison", "damage_expr": "half(1d8)"},
            ],
        }]
        prefix = format_combat_prefix(log)
        assert "CON save: success" in prefix
        assert "half poison damage (2)" in prefix


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

    def test_combat_action_on_hit_through_resolver(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """resolve_action passes soft/state_manager so on-hit effects resolve."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["goblin", "player"],
            current_index=0,
            round_number=1,
        )
        data = combat_npc_corpus.model_dump()
        data["stats"] = {
            "definitions": {
                "STR": {"name": "Strength"},
                "DEX": {"name": "Dexterity"},
                "CON": {"name": "Constitution"},
                "INT": {"name": "Intelligence"},
                "WIS": {"name": "Wisdom"},
                "CHA": {"name": "Charisma"},
            },
            "system": "5e",
        }
        data["entities"]["goblin"]["combat"]["on_hit_effects"] = [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "tag": "poison",
            "success": {"narrative": "You resist.", "player_damage": "half(1d8)"},
            "failure": {"narrative": "You fail.", "player_damage": "1d8"},
        }]
        corpus = ModuleCorpus.model_validate(data)
        # player misses (1), goblin hits (15+4=19), base dmg 1+2=3,
        # save fail (5+1=6), on-hit dmg 5 -> total 8
        rand_vals = iter([1, 15, 1, 5, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, corpus)
        assert result.success
        assert result.hard_changes.player_hp_delta == -8
        goblin_entry = result.combat_log[1]
        assert goblin_entry.actor == "goblin"
        assert len(goblin_entry.on_hit_effects) == 1
        assert goblin_entry.on_hit_effects[0]["save_success"] is False
        assert goblin_entry.on_hit_effects[0]["damage"] == 5

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


# ------------------------------------------------------------------
# 12b. Generalized NPC targeting (Phase 1)
# ------------------------------------------------------------------

class TestNpcTargeting:
    """resolve_npc_attack against NPC targets + per-action end checks."""

    @pytest.fixture
    def two_goblin_corpus(self) -> ModuleCorpus:
        return ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "room1": {
                    "name": "Test Room",
                    "description": "A test room.",
                    "contains": ["goblin_1", "goblin_2"],
                },
            },
            "entities": {
                "goblin_1": {
                    "type": "npc",
                    "description": "First goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6+2"},
                },
                "goblin_2": {
                    "type": "npc",
                    "description": "Second goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6+2"},
                },
            },
        })

    @pytest.fixture
    def two_goblin_hard(self, combat_hard_state) -> HardGameState:
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states = {
            "goblin_1": {"alive": True, "current_hp": 7},
            "goblin_2": {"alive": True, "current_hp": 7},
        }
        hard.room_contains = {"room1": {"goblin_1": 1, "goblin_2": 1}}
        return hard

    def test_npc_attack_npc_target_hit(self, two_goblin_corpus, two_goblin_hard, monkeypatch):
        """An NPC attack against an NPC target reads the target's HP from
        entity_states and reports a target HP delta."""
        rand_vals = iter([12, 3])  # attack roll, damage die
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = FiveESystem().resolve_npc_attack(
            "goblin_1", two_goblin_hard, two_goblin_corpus,
            target_id="goblin_2", target_ac=12, round_number=1,
        )
        assert result.hit is True
        assert result.target_hp_delta == -5  # 3 + 2
        assert result.target_died is False
        entry = result.log_entries[0]
        assert entry.actor == "goblin_1"
        assert entry.target == "goblin_2"
        assert entry.remaining_hp == 2  # 7 - 5

    def test_npc_attack_npc_target_kill(self, two_goblin_corpus, two_goblin_hard, monkeypatch):
        """Lethal damage sets target_died and appends a death log entry."""
        two_goblin_hard.entity_states["goblin_2"]["current_hp"] = 4
        rand_vals = iter([12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = FiveESystem().resolve_npc_attack(
            "goblin_1", two_goblin_hard, two_goblin_corpus,
            target_id="goblin_2", target_ac=12, round_number=1,
        )
        assert result.target_died is True
        death = [e for e in result.log_entries if e.action == "death"]
        assert len(death) == 1
        assert death[0].actor == "goblin_2"

    def test_npc_attack_npc_target_miss(self, two_goblin_corpus, two_goblin_hard, monkeypatch):
        monkeypatch.setattr(random, "randint", lambda a, b: 1)  # natural 1
        result = FiveESystem().resolve_npc_attack(
            "goblin_1", two_goblin_hard, two_goblin_corpus,
            target_id="goblin_2", target_ac=12, round_number=1,
        )
        assert result.hit is False
        assert result.target_hp_delta == 0
        assert result.target_died is False

    def test_cumulative_damage_game_over(self, two_goblin_corpus, two_goblin_hard, monkeypatch):
        """Two attackers whose combined damage drops the player to 0 HP end
        the game immediately, even though neither single attack is lethal
        against the player's start-of-turn HP."""
        hard = two_goblin_hard
        hard.player.current_hp = 5
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin_1", "goblin_2"],
            initiative_order=["player", "goblin_1", "goblin_2"],
            current_index=0,
            round_number=1,
        )
        # player misses (1); goblin_1 hits (15) for 3; goblin_2 hits (15) for 3
        rand_vals = iter([1, 15, 1, 15, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin_1", detail="Swing!",
        )
        result = resolve_combat_turn(action, hard, two_goblin_corpus)
        assert result["success"]
        assert result["game_over"] is True
        assert result["hard_changes"].player_hp_delta == -6
        deaths = [
            e for e in result["combat_log"]
            if e.action == "death" and e.actor == "player"
        ]
        assert len(deaths) == 1  # exactly one death entry, appended by the engine
        assert hard.combat is None

    def test_slain_npc_does_not_act_same_round(self, two_goblin_corpus, two_goblin_hard, monkeypatch):
        """An enemy killed by the player is skipped when its initiative slot
        comes up later in the same round."""
        hard = two_goblin_hard
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin_1", "goblin_2"],
            initiative_order=["player", "goblin_1", "goblin_2"],
            current_index=0,
            round_number=1,
        )
        # player crits goblin_1 (20, dmg 6+6+3 = 15 -> dead);
        # goblin_2 then hits (12) for 2+2 = 4
        rand_vals = iter([20, 6, 6, 12, 2])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin_1", detail="Take one down!",
        )
        result = resolve_combat_turn(action, hard, two_goblin_corpus)
        assert result["success"]
        g1_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin_1"
        ]
        assert g1_attacks == []  # slain before its turn
        g2_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin_2"
        ]
        assert len(g2_attacks) == 1
        assert result["hard_changes"].player_hp_delta == -4
        # goblin_2 is still alive, so combat continues
        assert hard.combat is not None


# ------------------------------------------------------------------
# 13. Enemy resolution (resolve_combat_enemies)
# ------------------------------------------------------------------

class TestResolveCombatEnemies:
    """Combatant set expansion, filtering, and follower handling."""

    @pytest.fixture
    def band_corpus(self) -> ModuleCorpus:
        return ModuleCorpus.model_validate({
            "adventure": {"title": "Band Test", "introduction": "Test."},
            "rooms": {
                "room1": {
                    "name": "Room 1",
                    "description": "A room.",
                    "contains": ["goblin_1", "goblin_2", "goblin_3"],
                },
                "room2": {
                    "name": "Room 2",
                    "description": "Another room.",
                    "contains": ["goblin_4"],
                },
            },
            "entities": {
                "goblin_1": {
                    "type": "npc",
                    "description": "Goblin 1.",
                    "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6"},
                    "combat_group": "goblin_band",
                },
                "goblin_2": {
                    "type": "npc",
                    "description": "Goblin 2.",
                    "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6"},
                    "combat_group": "goblin_band",
                },
                "goblin_3": {
                    "type": "npc",
                    "description": "Goblin 3.",
                    "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6"},
                    "combat_group": "goblin_band",
                },
                "goblin_4": {
                    "type": "npc",
                    "description": "Goblin 4 in another room.",
                    "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6"},
                    "combat_group": "goblin_band",
                },
                "noncombat_goblin": {
                    "type": "npc",
                    "description": "No combat block.",
                    "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
                    "combat_group": "goblin_band",
                },
            },
        })

    @pytest.fixture
    def band_hard_state(self) -> HardGameState:
        return HardGameState.model_validate({
            "player": {"location": "room1"},
            "flags": {},
            "room_states": {},
            "entity_states": {
                "goblin_1": {"alive": True},
                "goblin_2": {"alive": True},
                "goblin_3": {"alive": True},
                "goblin_4": {"alive": True},
                "noncombat_goblin": {"alive": True},
            },
            "room_contains": {
                "room1": {"goblin_1": 1, "goblin_2": 1, "goblin_3": 1},
                "room2": {"goblin_4": 1},
            },
        })

    def test_seed_expands_to_present_band(self, band_hard_state, band_corpus):
        enemies = resolve_combat_enemies(
            ["goblin_1"], None, band_hard_state, band_corpus
        )
        assert set(enemies) == {"goblin_1", "goblin_2", "goblin_3"}

    def test_absent_seed_band_expands_to_present(self, band_hard_state, band_corpus):
        # goblin_4 is in room2 (player is in room1).  It is dropped as a seed,
        # but its combat_group still expands to the present band in room1.
        enemies = resolve_combat_enemies(
            ["goblin_4"], None, band_hard_state, band_corpus
        )
        assert set(enemies) == {"goblin_1", "goblin_2", "goblin_3"}
        assert "goblin_4" not in enemies

    def test_dead_and_fled_dropped(self, band_hard_state, band_corpus):
        band_hard_state.entity_states["goblin_2"]["alive"] = False
        band_hard_state.room_contains["room1"].pop("goblin_3", None)
        enemies = resolve_combat_enemies(
            ["goblin_1"], None, band_hard_state, band_corpus
        )
        assert enemies == ["goblin_1"]

    def test_noncombat_band_member_dropped(self, band_hard_state, band_corpus):
        enemies = resolve_combat_enemies(
            ["goblin_1"], None, band_hard_state, band_corpus
        )
        assert "noncombat_goblin" not in enemies

    def test_explicit_combatants_expand_group(self, band_hard_state, band_corpus):
        enemies = resolve_combat_enemies(
            ["goblin_1"], ["goblin_2"], band_hard_state, band_corpus
        )
        assert set(enemies) == {"goblin_1", "goblin_2", "goblin_3"}

    def test_unknown_seed_dropped(self, band_hard_state, band_corpus):
        enemies = resolve_combat_enemies(
            ["unknown_id"], None, band_hard_state, band_corpus
        )
        assert enemies == []

    def test_follower_not_auto_pulled(self, band_hard_state, band_corpus):
        # Make goblin_2 a follower: it has dialogue and following=true.
        from mgmai.models.corpus import DialogueGuidelines
        ent = band_corpus.entities["goblin_2"]
        ent.dialogue = DialogueGuidelines(guidelines="A goblin follower.")
        band_hard_state.entity_states["goblin_2"]["following"] = True
        enemies = resolve_combat_enemies(
            ["goblin_1"], None, band_hard_state, band_corpus
        )
        assert "goblin_2" not in enemies
        assert set(enemies) == {"goblin_1", "goblin_3"}

    def test_attacked_follower_seed_is_included(self, band_hard_state, band_corpus):
        from mgmai.models.corpus import DialogueGuidelines
        ent = band_corpus.entities["goblin_2"]
        ent.dialogue = DialogueGuidelines(guidelines="A goblin follower.")
        band_hard_state.entity_states["goblin_2"]["following"] = True
        enemies = resolve_combat_enemies(
            ["goblin_2"], None, band_hard_state, band_corpus
        )
        assert "goblin_2" in enemies

    def test_empty_result(self, band_hard_state, band_corpus):
        band_hard_state.entity_states["goblin_1"]["alive"] = False
        band_hard_state.entity_states["goblin_2"]["alive"] = False
        band_hard_state.room_contains["room1"].pop("goblin_3", None)
        enemies = resolve_combat_enemies(
            ["goblin_1"], None, band_hard_state, band_corpus
        )
        assert enemies == []


class TestBriefingMultiEnemy:
    """A multi-enemy CombatState yields one briefing entry per living enemy."""

    def test_briefing_lists_all_enemies(self, combat_hard_state, combat_npc_corpus):
        from mgmai.context.assembler import _build_combat_state
        hard = combat_hard_state.model_copy(deep=True)
        # Add a second goblin to the room.
        hard.room_contains["room1"]["goblin2"] = 1
        combat_npc_corpus.entities["goblin2"] = Entity(
            type="npc",
            description="Another goblin.",
            state_fields={"alive": {"type": "boolean", "description": "Alive?"}, "current_hp": {"type": "number", "description": "HP"}},
            combat=CombatBlock(hp=5, ac=10, atk=2, dmg="1d4"),
        )
        hard.entity_states["goblin2"] = {"alive": True, "current_hp": 5}
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin", "goblin2"],
            initiative_order=["player", "goblin", "goblin2"],
            current_index=0,
            round_number=1,
        )
        briefing = _build_combat_state(hard, combat_npc_corpus)
        assert briefing is not None
        enemy_ids = {c["id"] for c in briefing.combatants if c["id"] != "player"}
        assert enemy_ids == {"goblin", "goblin2"}


# ------------------------------------------------------------------
# 14. Party combat (allies + combat AI)
# ------------------------------------------------------------------

class TestPartyCombat:
    """Allied NPCs in combat and rule-of-thumb NPC targeting."""

    @pytest.fixture
    def party_corpus(self) -> ModuleCorpus:
        return ModuleCorpus.model_validate({
            "adventure": {"title": "Party Test", "introduction": "Test."},
            "rooms": {
                "room1": {
                    "name": "Room 1",
                    "description": "A room.",
                    "contains": ["goblin"],
                    "exits": [
                        {"id": "exit_north", "direction": "north", "target_room": "room2"},
                    ],
                },
                "room2": {"name": "Room 2", "description": "Another room."},
            },
            "entities": {
                "companion": {
                    "type": "npc",
                    "name": "Companion",
                    "description": "A loyal companion.",
                    "dialogue": {"guidelines": "Loyal and brave."},
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "following": {"type": "boolean", "description": "Following?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {
                        "hp": 20, "ac": 14, "atk": 5, "dmg": "1d8+2",
                        "initiative_mod": 1,
                    },
                },
                "goblin": {
                    "type": "npc",
                    "description": "A goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6+2", "flee_dc": 10},
                },
            },
        })

    @pytest.fixture
    def party_hard(self, combat_hard_state) -> HardGameState:
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states = {
            "companion": {"alive": True, "following": True, "current_hp": 20},
            "goblin": {"alive": True, "current_hp": 7},
        }
        hard.room_contains = {"room1": {"goblin": 1}}
        return hard

    def _combat_state(self, hard, order=None):
        order = order or ["player", "companion", "goblin"]
        hard.combat = CombatState(
            active=True,
            combatants=list(order),
            allies=["companion"],
            initiative_order=list(order),
            current_index=0,
            round_number=1,
        )

    def _attack(self, target="goblin"):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target=target, detail="Attack!",
        )

    # -- Ally auto-join at combat entry -------------------------------

    def test_allies_auto_join(self, party_hard, party_corpus, monkeypatch):
        """enter_combat pulls combat-capable followers in as allies."""
        monkeypatch.setattr(random, "randint", lambda a, b: b)
        monkeypatch.setattr(random, "random", lambda: 0.5)
        result = enter_combat(["goblin"], party_hard, party_corpus)
        combat = party_hard.combat
        assert combat is not None
        assert combat.allies == ["companion"]
        assert combat.combatants == ["player", "companion", "goblin"]
        # Initiative: all roll 20; mods break ties (player +2, companion +1, goblin +0)
        assert combat.initiative_order == ["player", "companion", "goblin"]
        assert result["combat_triggered"] is True

    def test_attacked_follower_not_also_ally(self, party_hard, party_corpus, monkeypatch):
        """Attacking one's own follower makes it the enemy, not an ally."""
        monkeypatch.setattr(random, "randint", lambda a, b: b)
        monkeypatch.setattr(random, "random", lambda: 0.5)
        enter_combat(["companion"], party_hard, party_corpus)
        combat = party_hard.combat
        assert combat.allies == []
        assert "companion" in combat.combatants

    # -- Ally behavior ------------------------------------------------

    def test_ally_attacks_player_target(self, party_hard, party_corpus, monkeypatch):
        """Default ally AI: attack the player's most recent target."""
        self._combat_state(party_hard)
        # player hits goblin (15+5=20 vs 12), dmg 3+3=6;
        # companion hits goblin (10+5=15 vs 12), dmg 4+2=6 -> dead
        rand_vals = iter([15, 3, 10, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        ally_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "companion"
        ]
        assert len(ally_attacks) == 1
        assert ally_attacks[0].target == "goblin"

    def test_ally_kill_ends_combat_mid_sequence(self, party_hard, party_corpus, monkeypatch):
        """When an ally kills the last enemy, combat ends immediately and
        the slain enemy does not act."""
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 5
        # player misses (1); companion hits (10) for 4+2=6 -> goblin dead
        rand_vals = iter([1, 10, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        assert result["game_over"] is False
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert goblin_attacks == []
        assert party_hard.combat is None  # victory
        assert result["hard_changes"].entity_state_changes["goblin"]["alive"] is False

    def test_passive_ally_does_not_act(self, party_hard, party_corpus, monkeypatch):
        """A passive ally joins combat but takes no actions."""
        party_corpus.entities["companion"].combat.ai = (
            CombatAIBlock(passive=True)
        )
        self._combat_state(party_hard)
        # player hits goblin for 6 (hp 7 -> 1); goblin attacks player, misses
        rand_vals = iter([15, 3, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        ally_actions = [
            e for e in result["combat_log"] if e.actor == "companion"
        ]
        assert ally_actions == []

    # -- Enemy targeting rules ----------------------------------------

    def test_enemy_retaliates_on_last_attacker(self, party_hard, party_corpus, monkeypatch):
        """Default enemy AI: attack whoever hit it most recently."""
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 20
        # player hits for 6; companion hits for 6 (last attacker = companion);
        # goblin retaliates: 12+4=16 vs companion AC 14 -> hit, dmg 3+2=5
        rand_vals = iter([15, 3, 10, 4, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert len(goblin_attacks) == 1
        assert goblin_attacks[0].target == "companion"
        assert result["hard_changes"].entity_state_changes["companion"]["current_hp"] == 15

    def test_enemy_targeting_player_override(self, party_hard, party_corpus, monkeypatch):
        """ai.targeting 'player': ignore the last attacker, attack the player."""
        party_corpus.entities["goblin"].combat.ai = (
            CombatAIBlock(targeting="player")
        )
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 20
        # player hits; companion hits (last attacker); goblin still hits player
        rand_vals = iter([15, 3, 10, 4, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert goblin_attacks[0].target == "player"

    def test_enemy_targeting_lowest_hp(self, party_hard, party_corpus, monkeypatch):
        """ai.targeting 'lowest_hp': pick the weakest living opponent."""
        party_corpus.entities["goblin"].combat.ai = (
            CombatAIBlock(targeting="lowest_hp")
        )
        self._combat_state(party_hard)
        party_hard.entity_states["companion"]["current_hp"] = 5
        # player misses; companion attacks and misses; goblin picks companion (5 < 10)
        rand_vals = iter([1, 1, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert goblin_attacks[0].target == "companion"

    def test_enemy_targeting_random(self, party_hard, party_corpus, monkeypatch):
        """ai.targeting 'random': randint-steered pick among opponents."""
        party_corpus.entities["goblin"].combat.ai = (
            CombatAIBlock(targeting="random")
        )
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 20
        # player misses; companion hits; goblin picks opponents[1] = companion
        rand_vals = iter([1, 10, 4, 1, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert goblin_attacks[0].target == "companion"

    # -- NPC flee -----------------------------------------------------

    def test_npc_flees_below_hp_threshold(self, party_hard, party_corpus, monkeypatch):
        """An enemy below its flee threshold leaves combat; if it was the
        last enemy, combat ends."""
        party_corpus.entities["goblin"].combat.ai = (
            CombatAIBlock(flee_below_hp_pct=50)
        )
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 3  # 3/7 = 43% < 50%
        # player misses; companion misses; goblin flees
        rand_vals = iter([1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        assert party_hard.entity_states["goblin"]["fled"] is True
        flees = [
            e for e in result["combat_log"]
            if e.action == "flee" and e.actor == "goblin"
        ]
        assert len(flees) == 1
        assert party_hard.combat is None  # last enemy gone -> combat over

    def test_combat_continues_after_one_enemy_flees(self, party_hard, party_corpus, monkeypatch):
        """With other enemies alive, one fleeing does not end combat."""
        party_corpus.entities["spider"] = Entity(
            type="npc",
            description="A spider.",
            state_fields={
                "alive": {"type": "boolean", "description": "Alive?"},
                "current_hp": {"type": "number", "description": "HP"},
            },
            combat=CombatBlock(hp=30, ac=13, atk=5, dmg="1d8+3"),
        )
        party_corpus.entities["goblin"].combat.ai = (
            CombatAIBlock(flee_below_hp_pct=50)
        )
        party_hard.entity_states["spider"] = {"alive": True, "current_hp": 30}
        party_hard.entity_states["goblin"]["current_hp"] = 3
        self._combat_state(party_hard, order=["player", "companion", "goblin", "spider"])
        # player misses; companion misses goblin; goblin flees; spider attacks
        # player (no last attacker): 5+5=10 vs AC 14 -> miss
        rand_vals = iter([1, 1, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        assert party_hard.combat is not None
        assert "goblin" not in party_hard.combat.combatants
        assert "spider" in party_hard.combat.combatants
        assert party_hard.entity_states["goblin"]["fled"] is True

    # -- Ally death ---------------------------------------------------

    def test_ally_death(self, party_hard, party_corpus, monkeypatch):
        """A slain ally is removed from combat, marked dead, and stops
        following; combat continues."""
        self._combat_state(party_hard)
        party_hard.entity_states["goblin"]["current_hp"] = 20
        party_hard.entity_states["companion"]["current_hp"] = 5
        # player misses; companion hits goblin (last attacker); goblin
        # retaliates: 15+4=19 vs AC 14 -> hit, dmg 6+2=8 -> companion dead
        rand_vals = iter([1, 10, 4, 15, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        assert result["success"]
        assert result["game_over"] is False
        companion_changes = result["hard_changes"].entity_state_changes["companion"]
        assert companion_changes["alive"] is False
        assert companion_changes["current_hp"] <= 0
        assert "companion" not in party_hard.combat.combatants
        assert "companion" not in party_hard.combat.allies
        assert party_hard.combat is not None  # goblin still alive
        from mgmai.engine.utils import get_following_npc_ids
        assert "companion" not in get_following_npc_ids(party_hard, party_corpus)
        deaths = [
            e for e in result["combat_log"]
            if e.action == "death" and e.actor == "companion"
        ]
        assert len(deaths) == 1

    # -- Player actions with allies ------------------------------------

    def test_cannot_target_ally(self, party_hard, party_corpus):
        self._combat_state(party_hard)
        result = resolve_combat_turn(self._attack(target="companion"), party_hard, party_corpus)
        assert result["success"] is False
        assert "not an enemy" in result["error"]

    def test_player_flee_with_allies(self, party_hard, party_corpus, monkeypatch):
        """A successful player flee ends combat for the whole party; the
        follower keeps following."""
        self._combat_state(party_hard)
        # DEX 14 -> +2; roll 8 + 2 = 10 >= goblin flee_dc 10
        monkeypatch.setattr(random, "randint", lambda a, b: 8)
        action = MoveAction(
            action_type="move", target="exit_north", detail="Run north!",
        )
        result = resolve_combat_turn(action, party_hard, party_corpus)
        assert result["success"]
        assert party_hard.combat is None
        assert result["hard_changes"].player_location == "room2"
        assert party_hard.entity_states["companion"]["following"] is True
        from mgmai.engine.utils import get_following_npc_ids
        assert "companion" in get_following_npc_ids(party_hard, party_corpus)

    def test_flee_dc_ignores_allies(self, party_hard, party_corpus, monkeypatch):
        """The flee DC is the max over enemies only, not allies."""
        party_corpus.entities["companion"].combat.flee_dc = 18
        self._combat_state(party_hard)
        # roll 10 + 2 = 12: succeeds vs enemy DC 10, would fail vs ally DC 18
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        action = MoveAction(
            action_type="move", target="exit_north", detail="Run!",
        )
        result = resolve_combat_turn(action, party_hard, party_corpus)
        assert result["success"]
        assert result["hard_changes"].player_location == "room2"

    # -- State / briefing / prefix ------------------------------------

    def test_combat_state_ai_fields_roundtrip(self):
        """CombatState AI bookkeeping survives serialization."""
        cs = CombatState(
            active=True,
            combatants=["player", "companion", "goblin"],
            allies=["companion"],
            initiative_order=["player", "companion", "goblin"],
            current_index=0,
            round_number=2,
            last_attacker={"goblin": "companion", "player": "goblin"},
            player_last_target="goblin",
        )
        cs2 = CombatState.model_validate(cs.model_dump(mode="json"))
        assert cs2.allies == ["companion"]
        assert cs2.last_attacker == {"goblin": "companion", "player": "goblin"}
        assert cs2.player_last_target == "goblin"

    def test_briefing_includes_sides(self, party_hard, party_corpus):
        from mgmai.context.assembler import _build_combat_state
        self._combat_state(party_hard)
        briefing = _build_combat_state(party_hard, party_corpus)
        assert briefing is not None
        sides = {c["id"]: c["side"] for c in briefing.combatants}
        assert sides == {"player": "party", "companion": "party", "goblin": "enemy"}

    def test_npc_flee_prefix(self, party_corpus):
        log = [{"actor": "goblin", "action": "flee"}]
        prefix = format_combat_prefix(log, party_corpus)
        assert "goblin flees!" in prefix.lower()

    # -- Passive entity-state override --------------------------------

    def test_passive_entity_state_override_enables_fighting(self, party_hard, party_corpus, monkeypatch):
        """A declared ``passive`` entity state overrides the corpus AI
        default: a passive ally persuaded to fight (passive: false) acts."""
        party_corpus.entities["companion"].combat.ai = CombatAIBlock(passive=True)
        party_hard.entity_states["companion"]["passive"] = False
        self._combat_state(party_hard)
        # player hits goblin for 6; companion acts (override) and hits for 6 -> dead
        rand_vals = iter([15, 3, 10, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        ally_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "companion"
        ]
        assert len(ally_attacks) == 1

    def test_passive_entity_state_override_suppresses_fighting(self, party_hard, party_corpus, monkeypatch):
        """Entity state ``passive: true`` suppresses an NPC that would
        otherwise act (no ai block at all)."""
        party_hard.entity_states["companion"]["passive"] = True
        self._combat_state(party_hard)
        # player hits goblin for 6 (hp 7 -> 1); goblin attacks player, misses
        rand_vals = iter([15, 3, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), party_hard, party_corpus)
        ally_actions = [e for e in result["combat_log"] if e.actor == "companion"]
        assert ally_actions == []

    def test_bag_of_holding_korbar_persuadable(self):
        """Scenario guard: Korbar is passive by default but persuadable —
        passive state field declared, convince_fight path clears it."""
        from pathlib import Path

        from mgmai.state.manager import StateManager

        sm = StateManager()
        sm.load_all(Path("adventures/bag-of-holding"))
        korbar = sm.corpus.entities["korbar"]
        assert "passive" in korbar.state_fields
        assert korbar.combat.ai is not None
        assert korbar.combat.ai.passive is True
        path = korbar.dialogue.dialogue_paths["convince_fight"]
        assert path.result is not None
        assert path.result.set_entity_state["korbar"]["passive"] is False
        assert sm.hard_state.entity_states["korbar"]["passive"] is True
