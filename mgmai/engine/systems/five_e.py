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
from typing import TYPE_CHECKING, Any

from mgmai.engine.systems.base import (
    CheckResult,
    FleeResult,
    NPCAttackResult,
    PlayerAttackResult,
    ResolutionSystem,
    SaveResult,
)
from mgmai.engine.systems.dice import parse_damage_dice
from mgmai.models.combat import CombatLogEntry

if TYPE_CHECKING:
    from mgmai.models.corpus import EquipBlock, ModuleCorpus, OnHitEffect
    from mgmai.models.hard_state import HardGameState


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
        target: int,
        flat_modifier: int = 0,
        params: dict | None = None,
    ) -> CheckResult:
        computed_mod = self.compute_modifier(stat_value)
        total_mod = computed_mod + flat_modifier

        advantage = (params or {}).get("advantage", False)
        disadvantage = (params or {}).get("disadvantage", False)

        raw_roll = self.roll_die(20, advantage=advantage, disadvantage=disadvantage)
        total = raw_roll + total_mod
        success = total >= target

        return CheckResult(
            stat=stat,
            target=target,
            computed_mod=computed_mod,
            flat_mod=flat_modifier,
            modifier=total_mod,
            raw_roll=raw_roll,
            total=total,
            margin=total - target,
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
    # Attack resolution (engine delegates after validation)
    # ------------------------------------------------------------------
    def _player_stat(self, stats: dict[str, int] | None, key: str) -> int:
        """Return a player stat value, defaulting to 10."""
        if stats is None:
            return 10
        return stats.get(key, 10)

    def compute_player_attack_bonus(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """5e melee attack bonus: STR mod + proficiency + weapon bonuses."""
        stats = hard.player.stats
        str_mod = self.compute_modifier(self._player_stat(stats, "STR"))
        prof = getattr(hard.player, "proficiency_bonus", None) or 2
        weapon_bonus = 0
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if (
                entity
                and entity.equip_block
                and "weapon" in entity.equip_block.equip_tags
            ):
                weapon_bonus += entity.equip_block.hit_bonus
        return str_mod + prof + weapon_bonus

    def compute_player_damage_expr(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        soft: object | None = None,
    ) -> str:
        """5e melee damage expression: weapon dice + STR mod, or unarmed."""
        stats = hard.player.stats
        str_mod = self.compute_modifier(self._player_stat(stats, "STR"))

        # Equipped weapon
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if (
                entity
                and entity.equip_block
                and "weapon" in entity.equip_block.equip_tags
            ):
                base = entity.equip_block.damage_expr
                return f"{base}+{str_mod}" if str_mod >= 0 else f"{base}{str_mod}"

        # Improvised weapon
        if soft is not None:
            from mgmai.models.soft_state import SoftGameState

            if (
                isinstance(soft, SoftGameState)
                and soft.improvised_weapon is not None
            ):
                base = soft.improvised_weapon.damage_expr
                return f"{base}+{str_mod}" if str_mod >= 0 else f"{base}{str_mod}"

        # Legacy inventory weapon fallback
        has_weapon = False
        for item_id in hard.player.inventory:
            entity = corpus.entities.get(item_id)
            if entity and "weapon" in entity.tags:
                has_weapon = True
                break

        base = self.default_weapon_damage if has_weapon else self.unarmed_damage
        return f"{base}+{str_mod}" if str_mod >= 0 else f"{base}{str_mod}"

    def _resolve_on_hit_effects(
        self,
        effects: list[OnHitEffect],
        hard: HardGameState,
        round_number: int,
    ) -> tuple[int, list[dict]]:
        """Resolve NPC on-hit effects and return extra damage + result dicts."""
        total_extra = 0
        results: list[dict] = []
        for effect in effects:
            save_stat = effect.save.stat.upper()
            save_dc = effect.save.dc
            stat_value = self._player_stat(hard.player.stats, save_stat)
            flat_mod = self.compute_save_modifier(save_stat, hard.player)

            save_result = self.resolve_save(
                save_stat, stat_value, save_dc, flat_modifier=flat_mod
            )

            effect_damage = 0
            dmg_expr = effect.damage
            on_save = effect.on_save

            if on_save == "none" and save_result.success:
                effect_damage = 0
            else:
                raw_damage, _ = self.roll_damage(dmg_expr)
                if on_save == "half" and save_result.success:
                    effect_damage = max(1, raw_damage // 2)
                else:
                    effect_damage = raw_damage

            total_extra += effect_damage
            results.append(
                {
                    "save_stat": save_stat,
                    "save_dc": save_dc,
                    "save_roll": save_result.raw_roll,
                    "save_total": save_result.total,
                    "save_success": save_result.success,
                    "damage_expr": dmg_expr,
                    "damage": effect_damage,
                    "on_save": on_save,
                    "damage_type": effect.type,
                }
            )

        return total_extra, results

    def resolve_player_attack(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        target_id: str,
        target_ac: int,
        round_number: int,
    ) -> PlayerAttackResult:
        """Resolve a player melee attack against target_id."""
        entity = corpus.entities.get(target_id)
        if entity is None or entity.combat is None:
            raise ValueError(f"Invalid combat target '{target_id}'")

        atk_bonus = self.compute_player_attack_bonus(hard, corpus)
        attack_roll = self.roll_die(20)
        attack_total = attack_roll + atk_bonus
        critical = self.is_critical(attack_roll)
        miss = self.is_fumble(attack_roll)
        hit = critical or (not miss and attack_total >= target_ac)

        log_entry = CombatLogEntry(
            round=round_number,
            actor="player",
            action="attack",
            target=target_id,
            attack_roll=attack_roll,
            attack_total=attack_total,
            ac=target_ac,
            hit=hit,
            critical=critical if hit else None,
        )
        log_entries: list[CombatLogEntry] = [log_entry]

        damage = 0
        damage_roll: str | None = None
        target_hp_delta = 0

        npc_state = hard.entity_states.get(target_id, {})
        if hit:
            dmg_expr = self.compute_player_damage_expr(hard, corpus)
            damage, damage_roll = self.roll_damage(dmg_expr, critical=critical)
            log_entry.damage_roll = damage_roll
            log_entry.damage = damage
            target_hp_delta = -damage

            current_hp = npc_state.get("current_hp") or 0
            new_hp = current_hp - damage
            log_entry.remaining_hp = new_hp

            if new_hp <= 0:
                death_entry = CombatLogEntry(
                    round=round_number,
                    actor=target_id,
                    action="death",
                )
                log_entries.append(death_entry)
        else:
            log_entry.remaining_hp = npc_state.get("current_hp")

        return PlayerAttackResult(
            hit=hit,
            damage=damage,
            target_hp_delta=target_hp_delta,
            log_entries=log_entries,
            attack_roll=attack_roll,
            attack_total=attack_total,
            target_ac=target_ac,
            critical=critical if hit else None,
            damage_roll=damage_roll,
        )

    def resolve_npc_attack(
        self,
        npc_id: str,
        hard: HardGameState,
        corpus: ModuleCorpus,
        player_ac: int,
        round_number: int,
    ) -> NPCAttackResult:
        """Resolve an NPC attack against the player."""
        entity = corpus.entities.get(npc_id)
        if entity is None or entity.combat is None:
            raise ValueError(f"Invalid NPC '{npc_id}'")

        combat_block = entity.combat
        attack_roll = self.roll_die(20)
        attack_total = attack_roll + combat_block.atk
        critical = self.is_critical(attack_roll)
        miss = self.is_fumble(attack_roll)
        hit = critical or (not miss and attack_total >= player_ac)

        log_entry = CombatLogEntry(
            round=round_number,
            actor=npc_id,
            action="attack",
            target="player",
            attack_roll=attack_roll,
            attack_total=attack_total,
            ac=player_ac,
            hit=hit,
            critical=critical if hit else None,
        )
        log_entries: list[CombatLogEntry] = [log_entry]

        damage = 0
        damage_roll: str | None = None
        player_hp_delta = 0
        game_over = False

        if hit:
            damage, damage_roll = self.roll_damage(
                combat_block.dmg, critical=critical
            )
            log_entry.damage_roll = damage_roll
            log_entry.damage = damage
            total_damage = damage

            # On-hit effects (saving throws for secondary damage)
            extra_damage, on_hit_results = self._resolve_on_hit_effects(
                combat_block.on_hit_effects, hard, round_number
            )
            log_entry.on_hit_effects.extend(on_hit_results)
            total_damage += extra_damage

            player_hp_delta = -total_damage
            current_hp = hard.player.current_hp or 0
            new_hp = current_hp - total_damage
            log_entry.remaining_hp = new_hp

            if new_hp <= 0:
                death_entry = CombatLogEntry(
                    round=round_number,
                    actor="player",
                    action="death",
                )
                log_entries.append(death_entry)
                game_over = True

        return NPCAttackResult(
            hit=hit,
            damage=damage,
            player_hp_delta=player_hp_delta,
            log_entries=log_entries,
            game_over=game_over,
            attack_roll=attack_roll,
            attack_total=attack_total,
            player_ac=player_ac,
            critical=critical if hit else None,
            damage_roll=damage_roll,
        )

    def resolve_flee(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        flee_dc: int,
        round_number: int,
    ) -> FleeResult:
        """5e flee: a DEX ability check (d20 + DEX mod) against flee_dc."""
        dex_mod = self.compute_modifier(
            self._player_stat(hard.player.stats, "DEX")
        )
        roll = self.roll_die(20)
        total = roll + dex_mod
        success = total >= flee_dc

        log_entry = CombatLogEntry(
            round=round_number,
            actor="player",
            action="flee",
            attack_roll=roll,
            attack_total=total,
            ac=flee_dc,
            hit=success,
        )
        return FleeResult(
            success=success,
            roll=roll,
            total=total,
            dc=flee_dc,
            log_entries=[log_entry],
        )

    # ------------------------------------------------------------------
    # Derived combat stats
    # ------------------------------------------------------------------
    def base_ac(self, dex_value: int) -> int:
        return 10 + self.compute_modifier(dex_value)

    def base_max_hp(self, con_value: int) -> int:
        return max(1, 8 + self.compute_modifier(con_value))

    def compute_player_ac(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """5e player AC: explicit value or 10+DEX, then gear overrides/bonuses.

        Per plan.md §4c:
        1. Base AC = 10 + DEX mod (or hard.player.ac if explicitly set).
        2. Apply ac_override from equipped items (highest wins).
        3. Add all ac_bonus values from equipped items.
        """
        # Step 1: Base AC
        if hard.player.ac is not None:
            base_ac = hard.player.ac
        else:
            base_ac = self.base_ac(self._player_stat(hard.player.stats, "DEX"))

        # Step 2: Apply ac_override (highest wins)
        ac_override = None
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if entity and entity.equip_block:
                override_val = getattr(entity.equip_block, "ac_override", None)
                if override_val is not None:
                    if ac_override is None or override_val > ac_override:
                        ac_override = override_val

        effective_ac = ac_override if ac_override is not None else base_ac

        # Step 3: Add all ac_bonus values
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if entity and entity.equip_block:
                effective_ac += getattr(entity.equip_block, "ac_bonus", 0)

        return effective_ac

    def compute_player_max_hp(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """5e player max HP: explicit value, else 8 + CON mod."""
        if hard.player.max_hp is not None:
            return hard.player.max_hp
        return self.base_max_hp(self._player_stat(hard.player.stats, "CON"))

    def compute_player_initiative_modifier(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """5e initiative modifier: DEX mod."""
        return self.compute_modifier(
            self._player_stat(hard.player.stats, "DEX")
        )

    # ------------------------------------------------------------------
    # Saving throws (hook; invoked by the combat loop on NPC hits)
    # ------------------------------------------------------------------
    def resolve_save(
        self,
        stat: str,
        stat_value: int,
        dc: int,
        flat_modifier: int = 0,
        params: dict | None = None,
    ) -> SaveResult:
        computed_mod = self.compute_modifier(stat_value)
        total_mod = computed_mod + flat_modifier

        # NOTE: This still uses the old per-system-key nesting. It is
        # inconsistent with roll_check() and should be flattened when saves
        # grow corpus-driven params.
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

    def compute_save_modifier(self, stat: str, player_state: Any) -> int:
        """5e: proficient saves add the player's proficiency bonus."""
        profs = getattr(player_state, "save_proficiencies", [])
        if stat in profs:
            return getattr(player_state, "proficiency_bonus", None) or 2
        return 0

    # get_equip_incompatibilities() — inherit default (two_handed is now
    # a conventional equip_tag with explicit incompatible_with entries).
