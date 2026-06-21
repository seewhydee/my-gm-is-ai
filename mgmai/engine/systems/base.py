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

    # ------------------------------------------------------------------
    # Derived combat stats
    # ------------------------------------------------------------------
    @abstractmethod
    def base_ac(self, dex_value: int) -> int:
        """Unarmoured AC derived from Dexterity (before gear overrides)."""

    @abstractmethod
    def base_max_hp(self, con_value: int) -> int:
        """Maximum HP derived from Constitution (before explicit overrides)."""

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
