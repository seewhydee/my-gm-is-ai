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

"""Abstract base for RPG resolution systems.

The engine delegates all system-specific mechanics — stat modifiers, dice
rolls, check/save resolution, attack/crit rules, AC/HP formulas — to a
concrete :class:`ResolutionSystem` subclass.  The combat loop, resolvers,
and encounter engine remain system-agnostic: they orchestrate state and
turns, while a system object owns the maths.  Adding a new system
(Pathfinder, GURPS, d20 Modern, etc.) means implementing this interface
and registering it via :func:`mgmai.engine.systems.register_system`; no
edits to the combat loop or resolvers are required.

Dice are rolled through the shared ``random`` module so that test code
which monkeypatches ``random.randint`` / ``random.random`` continues to
steer every system uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mgmai.models.corpus import ModuleCorpus
    from mgmai.models.hard_state import HardGameState

from mgmai.models.combat import CombatLogEntry


@dataclass
class CheckResult:
    """Outcome of a stat/ability check, system-agnostic.

    Mirrors the roll-dict shape historically produced inline by the
    resolvers so downstream consumers (loggers, prefixes, briefings) see an
    identical field set.
    """

    stat: str
    dc: int
    computed_mod: int
    flat_mod: int
    modifier: int            # total modifier applied (computed_mod + flat_mod)
    raw_roll: int
    total: int
    margin: int              # total - dc
    success: bool
    advantage: bool
    disadvantage: bool

    def to_dict(self) -> dict:
        return {
            "type": "stat_check",
            "stat": self.stat,
            "dc": self.dc,
            "modifier": self.modifier,
            "computed_mod": self.computed_mod,
            "flat_mod": self.flat_mod,
            "raw_roll": self.raw_roll,
            "total": self.total,
            "margin": self.margin,
            "success": self.success,
            "advantage": self.advantage,
            "disadvantage": self.disadvantage,
        }


@dataclass
class SaveResult:
    """Outcome of a saving throw.

    Used by the combat loop for on-hit effects (poison, elemental damage,
    etc.).  The hook is wired in via
    :func:`mgmai.engine.combat._resolve_on_hit_effect`.
    """

    stat: str
    dc: int
    modifier: int
    raw_roll: int
    total: int
    margin: int
    success: bool
    advantage: bool
    disadvantage: bool

    def to_dict(self) -> dict:
        return {
            "type": "saving_throw",
            "stat": self.stat,
            "dc": self.dc,
            "modifier": self.modifier,
            "raw_roll": self.raw_roll,
            "total": self.total,
            "margin": self.margin,
            "success": self.success,
            "advantage": self.advantage,
            "disadvantage": self.disadvantage,
        }


@dataclass
class PlayerAttackResult:
    """Outcome of a player attack resolved by the RPG system.

    The engine performs target validation; the system decides whether the
    attack hits, how much damage it deals, and what log entries to record.
    """

    hit: bool
    damage: int
    target_hp_delta: int          # negative for damage dealt to the target
    log_entries: list[CombatLogEntry]
    attack_roll: int | None = None
    attack_total: int | None = None
    target_ac: int | None = None
    critical: bool | None = None
    damage_roll: str | None = None


@dataclass
class NPCAttackResult:
    """Outcome of an NPC attack resolved by the RPG system."""

    hit: bool
    damage: int
    player_hp_delta: int          # negative for damage dealt to the player
    log_entries: list[CombatLogEntry]
    game_over: bool = False
    attack_roll: int | None = None
    attack_total: int | None = None
    player_ac: int | None = None
    critical: bool | None = None
    damage_roll: str | None = None


@dataclass
class FleeResult:
    """Outcome of a player flee attempt resolved by the RPG system.

    The engine computes the flee DC (max across enemies); the system
    resolves the check (which stat/die/model to use) and returns the
    outcome plus log entries.  The engine handles movement on success.
    """

    success: bool
    roll: int
    total: int
    dc: int
    log_entries: list[CombatLogEntry]


class ResolutionSystem(ABC):
    """Interface for an RPG resolution system.

    Concrete subclasses bundle every system-specific rule the engine needs.
    The engine never branches on a system *name*; it calls these methods.
    """

    #: Short identifier matching ``corpus.stats.system`` (e.g. ``"5e"``).
    name: str = ""

    #: Default damage expression for an unarmed strike.
    unarmed_damage: str = "1d6"

    #: Default damage expression for an improvised/legacy weapon
    #: (an inventory item tagged ``weapon`` with no explicit dice).
    default_weapon_damage: str = "1d8"

    # ------------------------------------------------------------------
    # Modifiers & dice
    # ------------------------------------------------------------------
    @abstractmethod
    def compute_modifier(self, stat_value: int) -> int:
        """Map a raw ability score to its modifier."""

    @abstractmethod
    def roll_die(
        self,
        faces: int = 20,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> int:
        """Roll a single die, honouring advantage/disadvantage if the
        system supports it (5e: roll twice, keep higher/lower)."""

    @abstractmethod
    def roll_check(
        self,
        stat: str,
        stat_value: int,
        dc: int,
        flat_modifier: int = 0,
        params: dict | None = None,
    ) -> CheckResult:
        """Resolve an ability/skill check against a DC."""

    @abstractmethod
    def roll_initiative(self, modifier: int) -> int:
        """Roll a single combatant's initiative given a pre-computed
        modifier (DEX mod for the player, ``initiative_mod`` for NPCs)."""

    # ------------------------------------------------------------------
    # Attack / damage
    # ------------------------------------------------------------------
    @abstractmethod
    def is_critical(self, roll: int) -> bool:
        """True if a raw attack roll is a critical hit."""

    @abstractmethod
    def is_fumble(self, roll: int) -> bool:
        """True if a raw attack roll is an automatic miss."""

    @abstractmethod
    def roll_damage(self, expr: str, critical: bool = False) -> tuple[int, str]:
        """Roll a dice expression, applying the system's crit rule.
        Returns ``(total, readable_string)``."""

    @abstractmethod
    def resolve_player_attack(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        target_id: str,
        target_ac: int,
        round_number: int,
    ) -> PlayerAttackResult:
        """Resolve a player attack against target_id.

        The engine has already validated the target and computed its AC. The
        system computes the attack modifier, rolls to hit, determines
        hit/miss/critical, rolls damage, and returns log entries. It must not
        mutate ``hard``.
        """

    @abstractmethod
    def resolve_npc_attack(
        self,
        npc_id: str,
        hard: HardGameState,
        corpus: ModuleCorpus,
        player_ac: int,
        round_number: int,
    ) -> NPCAttackResult:
        """Resolve an NPC attack against the player.

        The engine has already computed the player's AC. The system reads the
        NPC's combat data from ``corpus.entities[npc_id]``, computes the
        attack, and returns log entries plus the player HP delta. It must not
        mutate ``hard``.
        """

    @abstractmethod
    def resolve_flee(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        flee_dc: int,
        round_number: int,
    ) -> FleeResult:
        """Resolve a player flee attempt against ``flee_dc``.

        The engine has already aggregated the flee DC (max across enemies).
        The system decides which stat/die/model the check uses, rolls it,
        and returns the outcome plus log entries.  The engine handles
        movement on success.
        """

    # ------------------------------------------------------------------
    # Derived combat stats
    # ------------------------------------------------------------------
    @abstractmethod
    def base_ac(self, dex_value: int) -> int:
        """Unarmoured AC derived from Dexterity (before gear overrides)."""

    @abstractmethod
    def base_max_hp(self, con_value: int) -> int:
        """Maximum HP derived from Constitution (before explicit overrides)."""

    @abstractmethod
    def compute_player_ac(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """Full player AC from stats and equipped gear.

        The system owns the AC formula and how equipment modifies it
        (overrides, bonuses).  The combat loop calls this instead of
        reading player stats directly.
        """

    @abstractmethod
    def compute_player_max_hp(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """Full player max HP from stats and explicit overrides.

        The system owns the HP formula.  The combat loop and state
        initialisation call this instead of reading CON directly.
        """

    @abstractmethod
    def compute_player_initiative_modifier(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """Player's initiative modifier for the active system.

        5e uses DEX mod; other systems may differ.  The combat loop
        calls this instead of reading DEX directly.
        """

    # ------------------------------------------------------------------
    # Saving throws (hook for the on-hit-effects phase)
    # ------------------------------------------------------------------
    @abstractmethod
    def resolve_save(
        self,
        stat: str,
        stat_value: int,
        dc: int,
        flat_modifier: int = 0,
        params: dict | None = None,
    ) -> SaveResult:
        """Resolve a saving throw against a DC."""

    def compute_save_modifier(self, stat: str, player_state: Any) -> int:
        """Return any extra modifier the system applies to a save for this player.

        Default is 0. Override in subclasses for system-specific rules
        (e.g. 5e proficiency bonus on proficient saves).
        """
        return 0
