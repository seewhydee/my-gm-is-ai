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
    ExamineAction,
    HardStateChanges,
    InteractAction,
    MoveAction,
    PlayerAction,
    WaitAction,
    validate_player_action,
)
from mgmai.models.combat import CombatLogEntry, CombatState
from mgmai.models.corpus import (
    CombatAIBlock,
    CombatBlock,
    StatusEffectDef,
    ConsumableBlock,
    EncounterRule,
    Entity,
    EquipBlock,
    ModuleCorpus,
    NPCAttackDef,
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
from mgmai.engine.engine import resolve
from mgmai.engine.resolver import ResolutionResult, resolve_action
from mgmai.engine.stat_checks import format_combat_prefix
from mgmai.engine.status_effects import apply_status_effect
from mgmai.engine.utils import get_status_effects
from tests.helpers import build_state_manager


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
        assert result["player_died"] is True
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
        # Inline (scripted) game-over, not HP death: player_died is False.
        assert result["player_died"] is False
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

    def test_wait_in_combat_passes_turn(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A wait action during combat passes the player's turn: the wait is
        logged, NPC turns proceed, and the round advances."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # goblin attacks (15+4=19 vs AC 14, hit) for 1+2=3 damage
        rand_vals = iter([15, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = WaitAction(action_type="wait", detail="Hold ground.")
        from mgmai.models.soft_state import SoftGameState
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, combat_npc_corpus)
        assert result.success
        assert hard.combat is not None and hard.combat.active
        assert hard.combat.round_number == 2
        assert result.combat_log[0].actor == "player"
        assert result.combat_log[0].action == "wait"
        assert result.combat_log[1].actor == "goblin"
        assert result.combat_log[1].action == "attack"
        assert result.hard_changes.player_hp_delta == -3

    def test_player_death_during_flee_attempt(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A player killed by NPC turns after a failed flee attempt must
        propagate player_died (previously dropped by the flee wrapper, so
        the game went on with a dead player)."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.current_hp = 3
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # flee roll fails (1+2 < 10); goblin hits (15+4 vs AC 14) for 6+2=8
        rand_vals = iter([1, 15, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))

        action = MoveAction(action_type="move", target="exit_north", detail="Run!")
        from mgmai.models.soft_state import SoftGameState
        soft = SoftGameState()
        result = resolve_action(action, hard, soft, combat_npc_corpus)
        assert result.success
        assert result.player_died is True
        assert any(
            e.actor == "player" and e.action == "death" for e in result.combat_log
        )

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

    def test_combat_action_attack_out_of_combat_starts_combat(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A combat/attack action received out of combat is equivalent to
        interact + interaction_id='attack': it starts combat."""
        hard = combat_hard_state.model_copy(deep=True)
        rand_vals = iter([15, 2])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        monkeypatch.setattr(random, "random", lambda: 0.5)

        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
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

    def test_wait_entry_produces_no_prefix(self):
        """A pass-turn entry yields no canned prefix line — the narrator
        describes the wait from the action's detail, as out of combat."""
        log = [{"actor": "player", "action": "wait"}]
        assert format_combat_prefix(log) == ""

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
        assert result["player_died"] is False
        assert result["combat_ended_reason"] == "victory"
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
        assert result["player_died"] is True
        assert result["combat_ended_reason"] == "defeat"
        assert hard.combat is None

    def test_flee_success_reports_fled_reason(self, combat_hard_state, combat_npc_corpus, monkeypatch):
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
        assert result["combat_ended_reason"] == "fled"
        assert hard.combat is None

    def test_combat_continues_reason_is_none(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """When combat does not end, combat_ended_reason is None."""
        hard = combat_hard_state.model_copy(deep=True)
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        # Player misses (1), goblin misses (1)
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
        assert result["combat_ended_reason"] is None
        assert hard.combat is not None


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
        assert result["player_died"] is True
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

    def test_briefing_conditions_include_descriptions(self, combat_hard_state, combat_npc_corpus):
        """Active status effects carry their StatusEffectDef.description so the GM
        LLM knows what each one does."""
        from mgmai.context.assembler import _build_combat_state
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 2}
        combat_npc_corpus.status_effects["frightened"] = StatusEffectDef.model_validate({
            "name": "Frightened",
            "description": "Too scared to fight well.",
        })
        hard.entity_states["goblin"]["status_effects"] = {"frightened": 1}
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        briefing = _build_combat_state(hard, combat_npc_corpus)
        assert briefing is not None
        by_id = {c["id"]: c for c in briefing.combatants}
        assert by_id["player"]["status_effects"] == [{
            "id": "poisoned",
            "rounds": 2,
            "description": "Disadvantage on attack rolls and ability checks.",
        }]
        assert by_id["goblin"]["status_effects"] == [{
            "id": "frightened",
            "rounds": 1,
            "description": "Too scared to fight well.",
        }]


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
        assert result["player_died"] is False
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
        assert result["player_died"] is False
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

    def test_passive_npc_persuadable_pattern(self):
        """An NPC can be passive by default (ai.passive=True, passive state
        field) and persuadable via a dialogue path that clears the state.

        This replaces the former ``test_bag_of_holding_korbar_persuadable``
        which depended on the ``adventures/bag-of-holding`` fixture.  The
        same data-model invariants are checked on a self-contained corpus.
        """
        from tests.helpers import build_state_manager

        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": {
                    "name": "Start",
                    "description": "A room.",
                    "contains": ["korbar"],
                },
            },
            "entities": {
                "korbar": {
                    "type": "npc",
                    "description": "A dwarf.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                        "passive": {
                            "type": "boolean",
                            "description": "Too scared to fight?",
                            "initial": True,
                        },
                    },
                    "combat": {
                        "hp": 10, "ac": 12, "atk": 2, "dmg": "1d6",
                        "ai": {"passive": True},
                    },
                    "dialogue": {
                        "guidelines": "A dwarf.",
                        "dialogue_paths": {
                            "convince_fight": {
                                "description": "Convince Korbar to fight.",
                                "result": {
                                    "narrative": "Korbar steels himself.",
                                    "set_entity_state": {
                                        "korbar": {"passive": False},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        })
        sm = build_state_manager(corpus)
        korbar = sm.corpus.entities["korbar"]
        assert "passive" in korbar.state_fields
        assert korbar.combat.ai is not None
        assert korbar.combat.ai.passive is True
        path = korbar.dialogue.dialogue_paths["convince_fight"]
        assert path.result is not None
        assert path.result.set_entity_state["korbar"]["passive"] is False
        assert sm.hard_state.entity_states["korbar"]["passive"] is True


# ------------------------------------------------------------------
# 15. Weapon properties (Phase 3a)
# ------------------------------------------------------------------

class TestWeaponProperties:
    """finesse / ranged weapon properties select the attack ability."""

    def _corpus_with_weapon(self, combat_npc_corpus, properties):
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["rapier"] = Entity(
            type="item",
            name="Rapier",
            description="A rapier.",
            tags=["weapon"],
            equip_block=EquipBlock(
                equip_tags=["weapon"],
                damage_expr="1d8",
                properties=properties,
            ),
        )
        return corpus

    def _hard_with_weapon(self, combat_hard_state, stats):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.stats = stats
        hard.player.equipped = ["rapier"]
        return hard

    def test_finesse_uses_dex_when_higher(self, combat_npc_corpus, combat_hard_state):
        corpus = self._corpus_with_weapon(combat_npc_corpus, ["finesse"])
        hard = self._hard_with_weapon(combat_hard_state, {"STR": 10, "DEX": 18, "CON": 12})
        s = FiveESystem()
        # DEX 18 -> +4, prof +2 -> +6
        assert s.compute_player_attack_bonus(hard, corpus) == 6
        assert s.compute_player_damage_expr(hard, corpus) == "1d8+4"

    def test_finesse_uses_str_when_higher(self, combat_npc_corpus, combat_hard_state):
        corpus = self._corpus_with_weapon(combat_npc_corpus, ["finesse"])
        hard = self._hard_with_weapon(combat_hard_state, {"STR": 18, "DEX": 12, "CON": 12})
        s = FiveESystem()
        # STR 18 -> +4, prof +2 -> +6
        assert s.compute_player_attack_bonus(hard, corpus) == 6
        assert s.compute_player_damage_expr(hard, corpus) == "1d8+4"

    def test_ranged_always_uses_dex(self, combat_npc_corpus, combat_hard_state):
        corpus = self._corpus_with_weapon(combat_npc_corpus, ["ranged"])
        hard = self._hard_with_weapon(combat_hard_state, {"STR": 18, "DEX": 12, "CON": 12})
        s = FiveESystem()
        # DEX 12 -> +1, prof +2 -> +3
        assert s.compute_player_attack_bonus(hard, corpus) == 3
        assert s.compute_player_damage_expr(hard, corpus) == "1d8+1"

    def test_plain_weapon_uses_str(self, combat_npc_corpus, combat_hard_state):
        corpus = self._corpus_with_weapon(combat_npc_corpus, [])
        hard = self._hard_with_weapon(combat_hard_state, {"STR": 16, "DEX": 14, "CON": 12})
        s = FiveESystem()
        assert s.compute_player_attack_bonus(hard, corpus) == 5
        assert s.compute_player_damage_expr(hard, corpus) == "1d8+3"


# ------------------------------------------------------------------
# 16. Damage types: resistance, vulnerability, immunity (Phase 3b)
# ------------------------------------------------------------------

class TestDamageTypes:
    """Typed damage vs NPC resistance/vulnerability/immunity."""

    def _setup(self, combat_npc_corpus, combat_hard_state, damage_type="fire", **enemy_block_kwargs):
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["flame_sword"] = Entity(
            type="item",
            name="Flame Sword",
            description="A burning sword.",
            tags=["weapon"],
            equip_block=EquipBlock(
                equip_tags=["weapon"], damage_expr="1d8", damage_type=damage_type,
            ),
        )
        cb = corpus.entities["goblin"].combat
        for key, value in enemy_block_kwargs.items():
            setattr(cb, key, value)
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.equipped = ["flame_sword"]
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        return corpus, hard

    def _attack(self):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Strike!",
        )

    def test_immune_target_takes_no_damage(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(combat_npc_corpus, combat_hard_state, immunities=["fire"])
        # player hits (15+5 vs 12), rolls 4 -> 4+3=7 fire, immune -> 0; goblin misses (1)
        rand_vals = iter([15, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.hit is True
        assert entry.damage == 0
        assert entry.mitigation == "immune"
        assert result["hard_changes"].entity_state_changes["goblin"]["current_hp"] == 7

    def test_resistance_halves_damage(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(combat_npc_corpus, combat_hard_state, resistances=["fire"])
        rand_vals = iter([15, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.damage == 3  # 7 // 2
        assert entry.mitigation == "resisted"
        assert result["hard_changes"].entity_state_changes["goblin"]["current_hp"] == 4

    def test_vulnerability_doubles_damage(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(combat_npc_corpus, combat_hard_state, vulnerabilities=["fire"])
        rand_vals = iter([15, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.damage == 14  # 7 * 2
        assert entry.mitigation == "vulnerable"
        assert result["hard_changes"].entity_state_changes["goblin"]["alive"] is False

    def test_untyped_damage_ignores_resistance(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state, damage_type="", resistances=["fire"],
        )
        rand_vals = iter([15, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.damage == 7
        assert entry.mitigation is None

    def test_npc_attack_mitigation_vs_npc_target(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        """An NPC attacker with a typed damage expr is mitigated by the NPC
        target's resistances (e.g. an ally striking a resistant enemy)."""
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["golem"] = Entity(
            type="npc",
            description="A stone golem.",
            state_fields={
                "alive": {"type": "boolean", "description": "Alive?"},
                "current_hp": {"type": "number", "description": "HP"},
            },
            combat=CombatBlock(hp=20, ac=10, atk=2, dmg="1d4", resistances=["fire"]),
        )
        cb = corpus.entities["goblin"].combat
        cb.dmg_type = "fire"
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states["golem"] = {"alive": True, "current_hp": 20}
        # goblin hits golem (12+4 vs 10), dmg 4+2=6 fire -> resisted -> 3
        rand_vals = iter([12, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = FiveESystem().resolve_npc_attack(
            "goblin", hard, corpus, "golem", 10, 1,
        )
        assert result.target_hp_delta == -3
        assert result.log_entries[0].mitigation == "resisted"

    def test_mitigation_prefix(self):
        log = [{"actor": "player", "action": "attack", "target": "goblin",
                "hit": True, "damage": 3, "mitigation": "resisted"}]
        prefix = format_combat_prefix(log)
        assert "(resisted)" in prefix


# ------------------------------------------------------------------
# 17. Conditions: poisoned, stunned, prone (Phase 3c)
# ------------------------------------------------------------------

class TestConditions:
    """Condition application, effects on rolls, ticking, and clearing."""

    def _combat_state(self, hard):
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

    def _attack(self):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Attack!",
        )

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

    def test_poisoned_player_attacks_with_disadvantage(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 2}
        self._combat_state(hard)
        # tick: 2 -> 1, still poisoned; attack rolls twice, keeps lower (3)
        rand_vals = iter([15, 3, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 3
        assert entry.hit is False
        assert hard.player.status_effects == {"poisoned": 1}

    def test_poison_expires_at_turn_start(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 1}
        self._combat_state(hard)
        # tick removes poison (1 -> 0); single attack roll 15 -> hit
        rand_vals = iter([15, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 15
        assert entry.hit is True

    def test_stunned_player_loses_action(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"stunned": 2}
        self._combat_state(hard)
        # player skips; goblin attacks the stunned player WITH ADVANTAGE
        # (keeps 12), hits for 3+2=5
        rand_vals = iter([12, 5, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        assert result["success"] is True
        stunned = [e for e in result["combat_log"] if e.action == "stunned"]
        assert len(stunned) == 1
        assert stunned[0].actor == "player"
        player_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "player"
        ]
        assert player_attacks == []
        assert result["hard_changes"].player_hp_delta == -5
        assert hard.combat.round_number == 2

    def test_stunned_npc_loses_turn(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states["goblin"]["status_effects"] = {"stunned": 2}
        self._combat_state(hard)
        # player attacks the stunned goblin WITH ADVANTAGE (keeps 15),
        # dmg 1+3=4 (goblin hp 7 -> 3); goblin stunned, skips
        rand_vals = iter([3, 15, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        stunned = [e for e in result["combat_log"] if e.action == "stunned"]
        assert len(stunned) == 1
        assert stunned[0].actor == "goblin"
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert goblin_attacks == []
        assert result["hard_changes"].player_hp_delta is None

    def test_attacks_against_prone_have_advantage(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states["goblin"]["status_effects"] = {"prone": 5}
        self._combat_state(hard)
        # player attacks with advantage (keeps 15), dmg 1+3=4 (hp 7 -> 3);
        # goblin auto-stands at its turn start and attacks normally
        rand_vals = iter([3, 15, 1, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 15
        assert entry.hit is True
        assert "prone" not in hard.entity_states["goblin"].get("status_effects", {})
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert len(goblin_attacks) == 1

    def test_apply_status_effect_from_on_hit(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        corpus = self._add_on_hit(combat_npc_corpus, [{
            "check": {
                "type": "stat_check", "stat": "CON", "target": 10,
                "proficiency": "save", "repeatable": False,
            },
            "success": {},
            "failure": {
                "narrative": "Venom burns through you.",
                "apply_status_effect": {"id": "poisoned", "rounds": 3},
            },
        }])
        hard = combat_hard_state.model_copy(deep=True)
        self._combat_state(hard)
        # player misses (1); goblin hits (15) for 1+2=3; save 5+1=6 < 10 fail
        rand_vals = iter([1, 15, 1, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus, soft=SoftGameState())
        assert result["success"]
        assert hard.player.status_effects == {"poisoned": 3}

    def test_conditions_cleared_at_combat_end(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 9}
        hard.entity_states["goblin"]["status_effects"] = {"stunned": 9}
        self._combat_state(hard)
        # player crits: 2*(1d6)+3 = 15 -> goblin dead -> combat ends
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, combat_npc_corpus)
        assert result["success"]
        assert hard.combat is None
        assert hard.player.status_effects == {}
        assert "status_effect" not in hard.entity_states["goblin"]

    def test_poisoned_flee_with_disadvantage(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 2}
        self._combat_state(hard)
        # flee rolls twice, keeps lower (5): 5+2=7 < 10 -> fail; goblin misses
        rand_vals = iter([12, 5, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = MoveAction(action_type="move", target="exit_north", detail="Run!")
        result = resolve_combat_turn(action, hard, combat_npc_corpus)
        assert result["success"]
        assert result["hard_changes"].player_location is None
        assert hard.combat is not None  # still in combat


class TestCustomConditions:
    """Corpus-defined status effects: system_effects, scope, duration, skip_turn."""

    def _combat_state(self, hard):
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )

    def _attack(self):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Attack!",
        )

    def _corpus_with(self, combat_npc_corpus, status_effects: dict) -> ModuleCorpus:
        corpus = combat_npc_corpus.model_copy(deep=True)
        for cid, cdef in status_effects.items():
            corpus.status_effects[cid] = StatusEffectDef.model_validate(cdef)
        return corpus

    def test_custom_condition_disadvantage_on_attack(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A corpus status effect with 5e disadvantage_on_attack behaves like
        the built-in poisoned default."""
        corpus = self._corpus_with(combat_npc_corpus, {
            "frightened": {
                "name": "Frightened",
                "system_effects": {"5e": {"disadvantage_on_attack": True}},
            },
        })
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"frightened": 2}
        self._combat_state(hard)
        # tick: 2 -> 1, still frightened; attack rolls twice, keeps lower (3)
        rand_vals = iter([15, 3, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 3
        assert entry.hit is False
        assert hard.player.status_effects == {"frightened": 1}

    def test_corpus_override_replaces_builtin_wholesale(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A corpus entry with a built-in ID replaces the default wholesale:
        no field-level merge, so the 5e disadvantage is gone."""
        corpus = self._corpus_with(combat_npc_corpus, {
            "poisoned": {"description": "Custom mild poison."},
        })
        assert corpus.effective_status_effects()["poisoned"].system_effects == {}
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 2}
        self._combat_state(hard)
        # tick: 2 -> 1, still poisoned but NO disadvantage: single roll 15,
        # dmg 1+3=4 (hp 7 -> 3); goblin misses (1)
        rand_vals = iter([15, 1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 15
        assert entry.hit is True
        assert hard.player.status_effects == {"poisoned": 1}

    def test_until_turn_start_reproduces_prone_behavior(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A custom until_turn_start status effect auto-clears on the
        afflicted's first tick, like legacy prone."""
        corpus = self._corpus_with(combat_npc_corpus, {
            "knocked_down": {
                "duration": "until_turn_start",
                "system_effects": {"5e": {"advantage_against": True}},
            },
        })
        hard = combat_hard_state.model_copy(deep=True)
        hard.entity_states["goblin"]["status_effects"] = {"knocked_down": 5}
        self._combat_state(hard)
        # player attacks with advantage (keeps 15), dmg 1+3=4 (hp 7 -> 3);
        # goblin gets up at its turn start and attacks normally
        rand_vals = iter([3, 15, 1, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        entry = result["combat_log"][0]
        assert entry.attack_roll == 15
        assert entry.hit is True
        assert "knocked_down" not in hard.entity_states["goblin"].get("status_effects", {})
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert len(goblin_attacks) == 1

    def test_skip_turn_custom_condition(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        """A custom status effect with skip_turn makes the player lose the
        action, like the built-in stunned default."""
        corpus = self._corpus_with(combat_npc_corpus, {
            "paralyzed": {"skip_turn": True},
        })
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"paralyzed": 2}
        self._combat_state(hard)
        # player skips; goblin attacks (12+4 vs AC 14) for 5+2=7
        rand_vals = iter([12, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        skipped = [e for e in result["combat_log"] if e.action == "stunned"]
        assert len(skipped) == 1
        assert skipped[0].actor == "player"
        player_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "player"
        ]
        assert player_attacks == []
        assert result["hard_changes"].player_hp_delta == -7

    def test_combat_end_clears_combat_scope_keeps_persistent(self, combat_hard_state, combat_npc_corpus, monkeypatch):
        corpus = self._corpus_with(combat_npc_corpus, {
            "curse": {"scope": "persistent", "duration": "rounds"},
        })
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.status_effects = {"poisoned": 9, "curse": 9}
        hard.entity_states["goblin"]["status_effects"] = {"stunned": 9}
        self._combat_state(hard)
        # player crits: 2*(1d6)+3 = 15 -> goblin dead -> combat ends
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack(), hard, corpus)
        assert result["success"]
        assert hard.combat is None
        assert hard.player.status_effects == {"curse": 9}
        assert "status_effect" not in hard.entity_states["goblin"]

    def test_reapplication_takes_max(self, combat_hard_state, combat_npc_corpus):
        hard = combat_hard_state.model_copy(deep=True)
        apply_status_effect("player", "poisoned", 3, hard, combat_npc_corpus, "result")
        apply_status_effect("player", "poisoned", 1, hard, combat_npc_corpus, "result")
        assert get_status_effects("player", hard) == {"poisoned": 3}
        apply_status_effect("player", "poisoned", 5, hard, combat_npc_corpus, "result")
        assert get_status_effects("player", hard) == {"poisoned": 5}


class TestPersistentConditions:
    """Persistent (out-of-combat) status effects applied from plain Results."""

    def _corpus(self) -> ModuleCorpus:
        return ModuleCorpus.model_validate({
            "adventure": {"title": "Persistent Test", "introduction": "Test."},
            "rooms": {
                "start": {
                    "name": "Start Room",
                    "description": "A room.",
                    "contains": ["slime", "goblin"],
                    "is_start_room": True,
                },
            },
            "entities": {
                "slime": {
                    "type": "feature",
                    "description": "A glistening slime mold.",
                    "interactions": [
                        {
                            "id": "touch",
                            "description": "Touch the slime.",
                            "result": {
                                "narrative": "It burns!",
                                "apply_status_effect": {
                                    "id": "slime_burn", "rounds": 2,
                                },
                            },
                        },
                        {
                            "id": "splash",
                            "description": "Fling slime at the goblin.",
                            "result": {
                                "narrative": "The goblin is splashed!",
                                "apply_status_effect": {
                                    "id": "poisoned", "rounds": 2,
                                    "target": "goblin",
                                },
                            },
                        },
                    ],
                },
                "goblin": {
                    "type": "npc",
                    "description": "A scrawny goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Is alive"},
                    },
                },
            },
            "status_effects": {
                "slime_burn": {
                    "name": "Slime Burn",
                    "description": "Burning slime residue.",
                    "scope": "persistent",
                    "duration": "rounds",
                    "tick_effect": {"player_damage": "2"},
                },
            },
        })

    def _hard(self, hp: int = 10) -> HardGameState:
        return HardGameState.model_validate({
            "player": {
                "location": "start",
                "inventory": {},
                "stats": {
                    "STR": 10, "DEX": 10, "CON": 10,
                    "INT": 10, "WIS": 10, "CHA": 10,
                },
                "level": 1,
                "current_hp": hp,
                "max_hp": 10,
                "ac": 10,
                "proficiency_bonus": 2,
            },
            "flags": {},
            "room_states": {"start": {"visited": True}},
            "entity_states": {"goblin": {"alive": True}},
            "turn_count": 0,
            "game_over": None,
        })

    def _interact(self, interaction_id: str) -> InteractAction:
        return InteractAction(
            action_type="interact", target="slime",
            interaction_id=interaction_id, detail="Go for it.",
        )

    def test_persistent_ticks_on_turn_end_and_expires(self):
        sm = build_state_manager(self._corpus(), hard_state=self._hard(hp=10))
        result = resolve(self._interact("touch"), sm)
        assert result.success
        # Applied for 2 rounds, then ticked once by this turn's turn.end.
        assert sm.hard_state.player.status_effects == {"slime_burn": 1}
        assert sm.hard_state.player.current_hp == 8  # tick_effect: 2 dmg

        # A free (non-turn-costing) action does not tick.
        result = resolve(
            ExamineAction(
                action_type="examine", target="slime", detail="Look closer."
            ),
            sm,
        )
        assert result.success
        assert sm.hard_state.player.status_effects == {"slime_burn": 1}
        assert sm.hard_state.player.current_hp == 8

        # The next turn-costing action ticks it to expiry.
        resolve(WaitAction(action_type="wait", detail="wait"), sm)
        assert sm.hard_state.player.status_effects == {}
        assert sm.hard_state.player.current_hp == 6

        # No further ticking once expired.
        resolve(WaitAction(action_type="wait", detail="wait"), sm)
        assert sm.hard_state.player.current_hp == 6

    def test_lethal_tick_damage_triggers_death_check(self):
        sm = build_state_manager(self._corpus(), hard_state=self._hard(hp=2))
        result = resolve(self._interact("touch"), sm)
        # tick_effect deals 2 -> 0 HP -> player.died poll -> game over.
        assert result.game_over is not None
        assert result.game_over.type == "lose"
        assert result.game_over.trigger == "player_death"

    def test_apply_status_effect_target_npc(self):
        sm = build_state_manager(self._corpus(), hard_state=self._hard())
        result = resolve(self._interact("splash"), sm)
        assert result.success
        assert get_status_effects("goblin", sm.hard_state) == {"poisoned": 2}
        assert sm.hard_state.player.status_effects == {}


# ------------------------------------------------------------------
# 18. Consumables: use_item combat action (Phase 3d)
# ------------------------------------------------------------------

class TestUseItem:
    """Drinking potions and using consumables in combat."""

    def _setup(self, combat_npc_corpus, combat_hard_state, consumable):
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["potion"] = Entity(
            type="item",
            name="Healing Potion",
            description="A red potion.",
            consumable=consumable,
        )
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.inventory["potion"] = 1
        hard.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=["player", "goblin"],
            current_index=0,
            round_number=1,
        )
        return corpus, hard

    def _use(self, target="potion"):
        return CombatAction(
            action_type="combat", combat_action="use_item",
            target=target, detail="Drink the potion!",
        )

    def test_heal_clamped_to_max_hp(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state,
            ConsumableBlock(heal="2d4+2"),
        )
        hard.player.current_hp = 5
        # heal rolls 3+4+2 = 9, clamped to 5 (max 10); goblin misses (1)
        rand_vals = iter([3, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"]
        hc = result["hard_changes"]
        assert hc.player_hp_delta == 5
        assert hc.inventory_removed == {"potion": 1}
        entry = result["combat_log"][0]
        assert entry.action == "use_item"
        assert entry.target == "potion"
        assert entry.damage == 5
        assert entry.remaining_hp == 10
        # the goblin still took its turn afterwards (action consumed)
        goblin_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        ]
        assert len(goblin_attacks) == 1

    def test_npc_attack_after_heal_uses_effective_hp(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        """A same-turn heal must be reflected in subsequent NPC attack log
        entries: no stale remaining_hp and no spurious player death entry
        while effective HP is positive."""
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state,
            ConsumableBlock(heal="2d4+2"),
        )
        hard.player.current_hp = 4
        # heal 3+1+2 = 6 -> effective 10 HP; goblin hits (15+4) for 6+2 = 8.
        # Stale base read would give 4-8 = -4 (fake death); effective is 2.
        rand_vals = iter([3, 1, 15, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"]
        assert result["player_died"] is False
        goblin_attack = next(
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "goblin"
        )
        assert goblin_attack.remaining_hp == 2
        assert not any(
            e.action == "death" and e.actor == "player"
            for e in result["combat_log"]
        )
        assert result["hard_changes"].player_hp_delta == -2

    def test_cure_conditions(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state,
            ConsumableBlock(cure_status_effects=["poisoned"]),
        )
        hard.player.status_effects = {"poisoned": 3}
        # tick: 3 -> 2; use_item then cures it; goblin misses (1)
        rand_vals = iter([1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"]
        assert hard.player.status_effects == {}

    def test_destroy_false_keeps_item(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state,
            ConsumableBlock(heal="1d4", destroy=False),
        )
        rand_vals = iter([2, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"]
        assert result["hard_changes"].inventory_removed == {}

    def test_use_item_not_in_inventory(self, combat_npc_corpus, combat_hard_state):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state, ConsumableBlock(heal="1d4"),
        )
        del hard.player.inventory["potion"]
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"] is False
        assert "not in inventory" in result["error"]

    def test_use_item_error_lists_usable_inventory(
        self, combat_npc_corpus, combat_hard_state
    ):
        """The not-in-inventory error lists the consumables the player CAN use."""
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state, ConsumableBlock(heal="1d4"),
        )
        hard.player.inventory["potion"] = 2
        # Non-consumable and zero-count items must not be listed.
        corpus.entities["rock"] = Entity(
            type="item", name="Rock", description="A rock.",
        )
        hard.player.inventory["rock"] = 1
        hard.player.inventory["old_junk"] = 0
        result = resolve_combat_turn(self._use(target="player"), hard, corpus)
        assert result["success"] is False
        assert "Item 'player' not in inventory" in result["error"]
        assert "Usable items in inventory: potion x2 (Healing Potion)." \
            in result["error"]
        assert "rock" not in result["error"]
        assert "old_junk" not in result["error"]

    def test_use_item_error_no_usable_inventory(
        self, combat_npc_corpus, combat_hard_state
    ):
        """With no consumables in inventory, the error says so plainly."""
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state, ConsumableBlock(heal="1d4"),
        )
        del hard.player.inventory["potion"]
        result = resolve_combat_turn(self._use(), hard, corpus)
        assert result["success"] is False
        assert "Item 'potion' not in inventory" in result["error"]
        assert "No usable items in inventory." in result["error"]

    def test_use_item_not_usable(self, combat_npc_corpus, combat_hard_state):
        corpus, hard = self._setup(
            combat_npc_corpus, combat_hard_state, ConsumableBlock(heal="1d4"),
        )
        corpus.entities["rock"] = Entity(
            type="item", name="Rock", description="A rock.",
        )
        hard.player.inventory["rock"] = 1
        result = resolve_combat_turn(self._use(target="rock"), hard, corpus)
        assert result["success"] is False
        assert "not usable" in result["error"]

    def test_use_item_prefix(self, combat_npc_corpus):
        log = [{"actor": "player", "action": "use_item",
                "target": "potion", "damage": 5}]
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["potion"] = Entity(
            type="item", name="Healing Potion", description="A red potion.",
            consumable=ConsumableBlock(heal="2d4+2"),
        )
        prefix = format_combat_prefix(log, corpus)
        assert "healing potion" in prefix.lower()
        assert "healed 5" in prefix.lower()


# ------------------------------------------------------------------
# 19. NPC attack definitions & multiattack (Phase 3e)
# ------------------------------------------------------------------

class TestMultiattack:
    """Per-attack definitions and ordered multiattack sequences."""

    def _wolf_corpus(self, combat_npc_corpus, multiattack):
        corpus = combat_npc_corpus.model_copy(deep=True)
        corpus.entities["wolf"] = Entity(
            type="npc",
            name="Wolf",
            description="A snarling wolf.",
            state_fields={
                "alive": {"type": "boolean", "description": "Alive?"},
                "current_hp": {"type": "number", "description": "HP"},
            },
            combat=CombatBlock(
                hp=20, ac=13,
                attacks=[
                    NPCAttackDef(id="bite", name="bites", atk=5, dmg="1d8+2"),
                    NPCAttackDef(id="claw", name="claws", atk=5, dmg="1d6+2"),
                ],
                multiattack=multiattack,
            ),
        )
        return corpus

    def _wolf_hard(self, combat_hard_state, player_hp=30):
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.current_hp = player_hp
        hard.player.max_hp = max(hard.player.max_hp or 0, player_hp)
        hard.entity_states["wolf"] = {"alive": True, "current_hp": 20}
        hard.combat = CombatState(
            active=True,
            combatants=["player", "wolf"],
            initiative_order=["player", "wolf"],
            current_index=0,
            round_number=1,
        )
        return hard

    def _attack_wolf(self):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target="wolf", detail="Attack the wolf!",
        )

    def test_multiattack_sequence_in_order(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus = self._wolf_corpus(combat_npc_corpus, ["claw", "claw", "bite"])
        hard = self._wolf_hard(combat_hard_state)
        # player misses (1); wolf: claw hits for 2+2=4, claw for 4, bite for 3+2=5
        rand_vals = iter([1, 12, 2, 12, 2, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_wolf(), hard, corpus)
        assert result["success"]
        attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "wolf"
        ]
        assert [e.attack_id for e in attacks] == ["claw", "claw", "bite"]
        assert [e.damage for e in attacks] == [4, 4, 5]
        assert result["hard_changes"].player_hp_delta == -13

    def test_sequence_stops_on_target_death(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        corpus = self._wolf_corpus(combat_npc_corpus, ["claw", "claw", "bite"])
        hard = self._wolf_hard(combat_hard_state, player_hp=8)
        # player misses; claw for 4 (hp 8 -> 4), claw for 6 (hp -> dead);
        # the bite never happens
        rand_vals = iter([1, 12, 2, 12, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_wolf(), hard, corpus)
        attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "wolf"
        ]
        assert [e.attack_id for e in attacks] == ["claw", "claw"]
        assert result["player_died"] is True
        deaths = [
            e for e in result["combat_log"]
            if e.action == "death" and e.actor == "player"
        ]
        assert len(deaths) == 1

    def test_single_default_attack(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        """Without multiattack, an NPC with attacks uses the first one."""
        corpus = self._wolf_corpus(combat_npc_corpus, [])
        hard = self._wolf_hard(combat_hard_state)
        rand_vals = iter([1, 12, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_wolf(), hard, corpus)
        attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "wolf"
        ]
        assert [e.attack_id for e in attacks] == ["bite"]

    def test_per_attack_on_hit_effects(self, combat_npc_corpus, combat_hard_state, monkeypatch):
        """On-hit effects fire from the attack that carries them only."""
        data = combat_npc_corpus.model_dump()
        data["stats"] = {
            "definitions": {
                "STR": {"name": "Strength"}, "DEX": {"name": "Dexterity"},
                "CON": {"name": "Constitution"}, "INT": {"name": "Intelligence"},
                "WIS": {"name": "Wisdom"}, "CHA": {"name": "Charisma"},
            },
            "system": "5e",
        }
        data["entities"]["wolf"] = {
            "type": "npc",
            "name": "Wolf",
            "description": "A snarling wolf.",
            "state_fields": {
                "alive": {"type": "boolean", "description": "Alive?"},
                "current_hp": {"type": "number", "description": "HP"},
            },
            "combat": {
                "hp": 20, "ac": 13,
                "attacks": [
                    {
                        "id": "bite", "name": "bites", "atk": 5, "dmg": "1d8+2",
                        "on_hit_effects": [{
                            "check": {
                                "type": "stat_check", "stat": "CON", "target": 10,
                                "proficiency": "save", "repeatable": False,
                            },
                            "success": {},
                            "failure": {"player_damage": "1d4"},
                        }],
                    },
                    {"id": "claw", "name": "claws", "atk": 5, "dmg": "1d6+2"},
                ],
                "multiattack": ["claw", "bite"],
            },
        }
        corpus = ModuleCorpus.model_validate(data)
        hard = self._wolf_hard(combat_hard_state)
        # player misses; claw hits (no save), bite hits -> save 5+1=6 < 10 -> 1d4=3
        rand_vals = iter([1, 12, 2, 12, 3, 5, 3])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_wolf(), hard, corpus, soft=SoftGameState())
        attacks = {e.attack_id: e for e in result["combat_log"] if e.action == "attack"}
        assert attacks["claw"].on_hit_effects == []
        assert len(attacks["bite"].on_hit_effects) == 1
        assert attacks["bite"].on_hit_effects[0]["save_success"] is False
        # 4 (claw) + 5 (bite) + 3 (poison) = 12
        assert result["hard_changes"].player_hp_delta == -12

    def test_multiattack_unknown_attack_id(self):
        with pytest.raises(ValueError, match="unknown attack"):
            CombatBlock(
                hp=5, ac=10,
                attacks=[NPCAttackDef(id="bite", atk=2)],
                multiattack=["claw"],
            )

    def test_attacks_forbid_block_on_hit_effects(self):
        with pytest.raises(ValueError, match="on_hit_effects"):
            CombatBlock(
                hp=5, ac=10,
                attacks=[NPCAttackDef(id="bite", atk=2)],
                on_hit_effects=[{
                    "check": {"type": "roll", "target": 50, "repeatable": False},
                    "success": {},
                }],
            )

    def test_duplicate_attack_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            CombatBlock(
                hp=5, ac=10,
                attacks=[NPCAttackDef(id="bite", atk=2), NPCAttackDef(id="bite", atk=3)],
            )

    def test_atk_required_without_attacks(self):
        with pytest.raises(ValueError, match="atk is required"):
            CombatBlock(hp=5, ac=10)

    def test_attack_name_prefix(self):
        log = [{"actor": "wolf", "action": "attack", "target": "player",
                "hit": True, "damage": 5, "attack_name": "bites"}]
        prefix = format_combat_prefix(log)
        assert "wolf bites you" in prefix.lower()


# ------------------------------------------------------------------
# 20. Abilities in combat (Phase 4)
# ------------------------------------------------------------------

class TestAbilities:
    """Player and NPC combat abilities: attack, save, heal."""

    @pytest.fixture
    def ability_corpus(self) -> ModuleCorpus:
        return ModuleCorpus.model_validate({
            "adventure": {"title": "Ability Test", "introduction": "Test."},
            "rooms": {
                "room1": {
                    "name": "Room 1", "description": "A room.",
                    "contains": ["goblin", "acolyte", "medic"],
                },
            },
            "abilities": {
                "fire_bolt": {
                    "name": "Fire Bolt",
                    "description": "A mote of fire.",
                    "target": "enemy",
                    "uses_per_combat": -1,
                    "attack": {
                        "stat": "INT", "proficient": True,
                        "damage": "1d10", "damage_type": "fire",
                    },
                },
                "cure_wounds": {
                    "name": "Cure Wounds",
                    "description": "Healing light.",
                    "target": "ally",
                    "uses_per_combat": 2,
                    "heal": "1d8+2",
                },
                "poison_spray": {
                    "name": "Poison Spray",
                    "description": "A puff of toxic gas.",
                    "target": "enemy",
                    "uses_per_combat": 1,
                    "save": {
                        "stat": "CON", "dc": 12, "damage": "1d12",
                        "damage_type": "poison", "half_on_success": True,
                    },
                },
                "breath": {
                    "name": "Fire Breath",
                    "description": "A gout of flame.",
                    "target": "enemy",
                    "uses_per_combat": -1,
                    "save": {
                        "stat": "DEX", "dc": 13, "damage": "2d6",
                        "damage_type": "fire", "half_on_success": True,
                    },
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
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6+2"},
                },
                "acolyte": {
                    "type": "npc",
                    "description": "A fire cultist.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {
                        "hp": 18, "ac": 12, "atk": 4, "dmg": "1d6+1",
                        "save_bonus": 1,
                        "abilities": ["breath"],
                        "ai": {"ability_rules": {"breath": {"cooldown_rounds": 2}}},
                    },
                },
                "medic": {
                    "type": "npc",
                    "name": "Medic",
                    "description": "A field medic.",
                    "dialogue": {"guidelines": "Kind and calm."},
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "following": {"type": "boolean", "description": "Following?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {
                        "hp": 16, "ac": 12, "atk": 2, "dmg": "1d4+1",
                        "abilities": ["cure_wounds"],
                    },
                },
            },
        })

    @pytest.fixture
    def ability_hard(self, combat_hard_state) -> HardGameState:
        hard = combat_hard_state.model_copy(deep=True)
        hard.player.abilities = ["fire_bolt", "cure_wounds", "poison_spray"]
        hard.entity_states = {
            "goblin": {"alive": True, "current_hp": 7},
            "acolyte": {"alive": True, "current_hp": 18},
            "medic": {"alive": True, "following": True, "current_hp": 16},
        }
        hard.room_contains = {"room1": {"goblin": 1, "acolyte": 1}}
        return hard

    def _combat_state(self, hard, order=("player", "goblin"), allies=()):
        hard.combat = CombatState(
            active=True,
            combatants=list(order),
            allies=list(allies),
            initiative_order=list(order),
            current_index=0,
            round_number=1,
        )

    def _ability(self, ability_id, target):
        return CombatAction(
            action_type="combat", combat_action="use_ability",
            target=target, ability_id=ability_id, detail="Use an ability!",
        )

    def _attack_goblin(self):
        return CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", detail="Attack!",
        )

    # -- Player attack abilities ---------------------------------------

    def test_player_attack_ability_hit(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        # INT 10 -> +0, prof +2; roll 15+2=17 vs 12 -> hit; 1d10=6 fire
        rand_vals = iter([15, 6, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("fire_bolt", "goblin"), ability_hard, ability_corpus)
        assert result["success"]
        entry = result["combat_log"][0]
        assert entry.action == "attack"
        assert entry.attack_id == "fire_bolt"
        assert entry.attack_name == "Fire Bolt"
        assert entry.hit is True
        assert entry.damage == 6
        assert result["hard_changes"].entity_state_changes["goblin"]["current_hp"] == 1
        assert ability_hard.combat.ability_uses["player"]["fire_bolt"] == 1

    def test_player_attack_ability_crit(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        # nat 20 -> crit, damage dice doubled: 2d10 = 12+... two dice at 5
        rand_vals = iter([20, 5, 5])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("fire_bolt", "goblin"), ability_hard, ability_corpus)
        entry = result["combat_log"][0]
        assert entry.critical is True
        assert entry.damage == 10
        assert result["hard_changes"].entity_state_changes["goblin"]["alive"] is False
        assert ability_hard.combat is None  # victory

    def test_uses_exhausted_error(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        # poison_spray has 1 use; goblin saves successfully (15 >= 12)
        rand_vals = iter([15, 8, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("poison_spray", "goblin"), ability_hard, ability_corpus)
        assert result["success"]
        # Second use is rejected
        result2 = resolve_combat_turn(self._ability("poison_spray", "goblin"), ability_hard, ability_corpus)
        assert result2["success"] is False
        assert "no uses left" in result2["error"]

    def test_unknown_and_unlearned_ability_errors(self, ability_hard, ability_corpus):
        self._combat_state(ability_hard)
        result = resolve_combat_turn(self._ability("wish", "goblin"), ability_hard, ability_corpus)
        assert result["success"] is False
        assert "Unknown ability" in result["error"]
        ability_corpus.abilities["wish"] = ability_corpus.abilities["fire_bolt"]
        result = resolve_combat_turn(self._ability("wish", "goblin"), ability_hard, ability_corpus)
        assert result["success"] is False
        assert "do not know" in result["error"]

    def test_ability_wrong_target_side(self, ability_hard, ability_corpus):
        self._combat_state(ability_hard, order=("player", "medic", "goblin"), allies=["medic"])
        result = resolve_combat_turn(self._ability("fire_bolt", "medic"), ability_hard, ability_corpus)
        assert result["success"] is False
        assert "must target an enemy" in result["error"]

    # -- Player save abilities -----------------------------------------

    def test_save_ability_full_damage_on_failure(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        # goblin save_bonus 0: save 5 < 12 -> fail -> full 1d12 = 8 -> dead
        rand_vals = iter([5, 8])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("poison_spray", "goblin"), ability_hard, ability_corpus)
        assert result["success"]
        entry = result["combat_log"][0]
        assert entry.action == "ability_save"
        assert entry.damage == 8
        save_dict = entry.on_hit_effects[0]
        assert save_dict["save_success"] is False
        assert save_dict["save_dc"] == 12
        assert result["hard_changes"].entity_state_changes["goblin"]["alive"] is False
        assert ability_hard.combat is None

    def test_save_ability_half_on_success(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        # goblin saves (15 >= 12): half of 8 = 4; goblin then misses
        rand_vals = iter([15, 8, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("poison_spray", "goblin"), ability_hard, ability_corpus)
        entry = result["combat_log"][0]
        assert entry.damage == 4
        assert entry.on_hit_effects[0]["save_success"] is True
        assert result["hard_changes"].entity_state_changes["goblin"]["current_hp"] == 3

    # -- Player heal abilities -----------------------------------------

    def test_heal_ally_target_player(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard)
        ability_hard.player.current_hp = 4
        # cure 6+2=8 clamped to 6 (max 10); goblin misses
        rand_vals = iter([6, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("cure_wounds", "player"), ability_hard, ability_corpus)
        assert result["success"]
        assert result["hard_changes"].player_hp_delta == 6
        entry = result["combat_log"][0]
        assert entry.action == "heal"
        assert entry.damage == 6

    def test_heal_ally_target_ally_npc(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard, order=("player", "medic", "goblin"), allies=["medic"])
        ability_hard.entity_states["medic"]["current_hp"] = 5
        # player cures medic 4+2=6 (5 -> 11); medic finds everyone healthy
        # and attacks the goblin (miss); goblin misses
        rand_vals = iter([4, 1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._ability("cure_wounds", "medic"), ability_hard, ability_corpus)
        assert result["success"]
        assert result["hard_changes"].entity_state_changes["medic"]["current_hp"] == 11
        assert ability_hard.entity_states["medic"]["current_hp"] == 11

    # -- NPC ability usage ----------------------------------------------

    def test_npc_uses_save_ability(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard, order=("player", "acolyte"))
        # player attacks goblin... (no goblin in this combat; attack acolyte)
        # player misses (1); acolyte breathes fire: player DEX save 10+2=12 < 13
        # -> fail -> full 2d6 = 8
        rand_vals = iter([1, 10, 4, 4])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="acolyte", detail="Attack!",
        )
        result = resolve_combat_turn(action, ability_hard, ability_corpus)
        assert result["success"]
        breath = [e for e in result["combat_log"] if e.action == "ability_save"]
        assert len(breath) == 1
        assert breath[0].actor == "acolyte"
        assert breath[0].attack_name == "Fire Breath"
        assert breath[0].on_hit_effects[0]["save_success"] is False
        assert result["hard_changes"].player_hp_delta == -8
        # cooldown recorded (2 rounds)
        assert ability_hard.combat.npc_cooldowns["acolyte"]["breath"] == 2

    def test_npc_cooldown_falls_back_to_attack(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(ability_hard, order=("player", "acolyte"))
        ability_hard.combat.npc_cooldowns["acolyte"] = {"breath": 1}
        # player misses; acolyte is on cooldown -> basic attack (miss);
        # cooldown ticks to 0 at round end
        rand_vals = iter([1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="acolyte", detail="Attack!",
        )
        result = resolve_combat_turn(action, ability_hard, ability_corpus)
        assert result["success"]
        assert [e for e in result["combat_log"] if e.action == "ability_save"] == []
        basic = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "acolyte"
        ]
        assert len(basic) == 1
        assert ability_hard.combat.npc_cooldowns["acolyte"]["breath"] == 0

    def test_ally_npc_heals_most_injured(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(
            ability_hard, order=("player", "medic", "goblin"), allies=["medic"],
        )
        ability_hard.player.current_hp = 3  # player is the most injured
        # player hits goblin for 5 (hp 7 -> 2); medic cures player 4+2=6;
        # goblin misses
        rand_vals = iter([15, 2, 4, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_goblin(), ability_hard, ability_corpus)
        assert result["success"]
        heals = [e for e in result["combat_log"] if e.action == "heal"]
        assert len(heals) == 1
        assert heals[0].actor == "medic"
        assert heals[0].target == "player"
        assert result["hard_changes"].player_hp_delta == 6

    def test_ally_healer_skips_when_all_healthy(self, ability_hard, ability_corpus, monkeypatch):
        self._combat_state(
            ability_hard, order=("player", "medic", "goblin"), allies=["medic"],
        )
        # everyone at full HP: medic falls back to its basic attack
        # player hits goblin for 5; medic attacks goblin (miss); goblin misses
        rand_vals = iter([15, 2, 1, 1])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        result = resolve_combat_turn(self._attack_goblin(), ability_hard, ability_corpus)
        assert result["success"]
        assert [e for e in result["combat_log"] if e.action == "heal"] == []
        medic_attacks = [
            e for e in result["combat_log"]
            if e.action == "attack" and e.actor == "medic"
        ]
        assert len(medic_attacks) == 1

    # -- Model validation & briefing ------------------------------------

    def test_ability_shape_validation(self):
        from mgmai.models.corpus import Ability

        with pytest.raises(ValueError, match="exactly one effect"):
            Ability(name="Bad", target="enemy")
        with pytest.raises(ValueError, match="exactly one effect"):
            Ability(
                name="Bad", target="enemy", heal="1d8",
                attack={"stat": "INT", "damage": "1d10"},
            )
        with pytest.raises(ValueError, match="heal abilities"):
            Ability(name="Bad", target="enemy", heal="1d8")

    def test_briefing_lists_abilities(self, ability_hard, ability_corpus):
        from mgmai.context.assembler import _build_combat_state
        self._combat_state(ability_hard)
        ability_hard.combat.ability_uses["player"] = {"poison_spray": 1}
        briefing = _build_combat_state(ability_hard, ability_corpus)
        assert briefing is not None
        by_id = {a["id"]: a for a in briefing.abilities}
        assert by_id["fire_bolt"]["uses_remaining"] is None  # unlimited
        assert by_id["poison_spray"]["uses_remaining"] == 0
        assert by_id["cure_wounds"]["uses_remaining"] == 2
        assert "attack" in by_id["fire_bolt"]["effect"]

    def test_ability_save_prefix(self):
        log = [{
            "actor": "player", "action": "ability_save", "target": "goblin",
            "attack_name": "Poison Spray", "damage": 8,
            "on_hit_effects": [{"save_success": False}],
        }]
        prefix = format_combat_prefix(log)
        assert "poison spray" in prefix.lower()
        assert "fails to resist" in prefix.lower()

    def test_heal_prefix(self):
        log = [{"actor": "player", "action": "heal", "target": "player",
                "attack_name": "Cure Wounds", "damage": 6}]
        prefix = format_combat_prefix(log)
        assert "cure wounds" in prefix.lower()
        assert "healed 6" in prefix.lower()
