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

"""D&D 5th Edition resolution system.

This is the concrete :class:`~mgmai.engine.systems.base.ResolutionSystem`
that previously lived as free functions and inline blocks across
``stat_checks.py``, ``combat.py``, ``resolver.py``, and ``encounters.py``.
The behaviour is unchanged; the logic has merely been relocated behind the
system interface so the engine is system-agnostic.
"""

from __future__ import annotations

import random

from mgmai.engine.systems.base import CheckResult, ResolutionSystem, SaveResult
from mgmai.engine.systems.dice import parse_damage_dice


class FiveESystem(ResolutionSystem):
    """D&D 5e ability checks, attacks, crits, saves, and derived stats."""

    name = "5e"
    unarmed_damage = "1d6"
    default_weapon_damage = "1d8"

    # ------------------------------------------------------------------
    # Modifiers & dice
    # ------------------------------------------------------------------
    def compute_modifier(self, stat_value: int) -> int:
        # 5e: (score - 10) // 2, floored.
        return (stat_value - 10) // 2

    def roll_die(
        self,
        faces: int = 20,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> int:
        # Roll twice, keep the higher (advantage) or lower (disadvantage).
        # If both or neither are set, roll a single die.
        if advantage and not disadvantage:
            return max(random.randint(1, faces), random.randint(1, faces))
        elif disadvantage and not advantage:
            return min(random.randint(1, faces), random.randint(1, faces))
        else:
            return random.randint(1, faces)

    def roll_check(
        self,
        stat: str,
        stat_value: int,
        dc: int,
        flat_modifier: int = 0,
        params: dict | None = None,
    ) -> CheckResult:
        computed_mod = self.compute_modifier(stat_value)
        total_mod = computed_mod + flat_modifier

        sys_params = (params or {}).get(self.name, {})
        advantage = sys_params.get("advantage", False)
        disadvantage = sys_params.get("disadvantage", False)

        raw_roll = self.roll_die(20, advantage=advantage, disadvantage=disadvantage)
        total = raw_roll + total_mod
        success = total >= dc

        return CheckResult(
            stat=stat,
            dc=dc,
            computed_mod=computed_mod,
            flat_mod=flat_modifier,
            modifier=total_mod,
            raw_roll=raw_roll,
            total=total,
            margin=total - dc,
            success=success,
            advantage=advantage,
            disadvantage=disadvantage,
        )

    def roll_initiative(self, modifier: int) -> int:
        return self.roll_die(20) + modifier

    # ------------------------------------------------------------------
    # Attack / damage
    # ------------------------------------------------------------------
    def is_critical(self, roll: int) -> bool:
        return roll == 20

    def is_fumble(self, roll: int) -> bool:
        return roll == 1

    def roll_damage(self, expr: str, critical: bool = False) -> tuple[int, str]:
        # On a critical hit the number of dice is doubled (modifier added once).
        num_dice, die_size, modifier = parse_damage_dice(expr)

        if num_dice == 0:
            # Flat damage (bare integer) — no dice to roll or double.
            return modifier, f"{modifier} [flat]={modifier}"

        dice_count = num_dice * 2 if critical else num_dice
        rolls = [random.randint(1, die_size) for _ in range(dice_count)]
        total = sum(rolls) + modifier

        parts = [str(r) for r in rolls]
        roll_str = "+".join(parts)
        if modifier > 0:
            roll_str += f"+{modifier}"
        elif modifier < 0:
            roll_str += str(modifier)

        mod_str = ""
        if modifier > 0:
            mod_str = f"+{modifier}"
        elif modifier < 0:
            mod_str = str(modifier)

        return total, f"{dice_count}d{die_size}{mod_str} [{roll_str}]={total}"

    # ------------------------------------------------------------------
    # Derived combat stats
    # ------------------------------------------------------------------
    def base_ac(self, dex_value: int) -> int:
        return 10 + self.compute_modifier(dex_value)

    def base_max_hp(self, con_value: int) -> int:
        return max(1, 8 + self.compute_modifier(con_value))

    # ------------------------------------------------------------------
    # Saving throws (hook; not yet invoked by the combat loop)
    # ------------------------------------------------------------------
    def resolve_save(
        self,
        stat: str,
        stat_value: int,
        dc: int,
        proficient: bool = False,
        proficiency_bonus: int = 0,
        params: dict | None = None,
    ) -> SaveResult:
        computed_mod = self.compute_modifier(stat_value)
        total_mod = computed_mod + (proficiency_bonus if proficient else 0)

        sys_params = (params or {}).get(self.name, {})
        advantage = sys_params.get("advantage", False)
        disadvantage = sys_params.get("disadvantage", False)

        raw_roll = self.roll_die(20, advantage=advantage, disadvantage=disadvantage)
        total = raw_roll + total_mod
        success = total >= dc

        return SaveResult(
            stat=stat,
            dc=dc,
            modifier=total_mod,
            raw_roll=raw_roll,
            total=total,
            margin=total - dc,
            success=success,
            advantage=advantage,
            disadvantage=disadvantage,
        )
