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
)
from mgmai.engine.systems.dice import parse_damage_dice
from mgmai.engine.utils import get_status_effects
from mgmai.models.combat import CombatLogEntry
from mgmai.models.hard_state import WeaponProfClause

if TYPE_CHECKING:
    from mgmai.models.corpus import EquipBlock, ModuleCorpus, NPCAttackDef
    from mgmai.models.hard_state import HardGameState


class FiveESystem(ResolutionSystem):
    """D&D 5e ability checks, attacks, crits, saves, and derived stats."""

    name = "5e"
    unarmed_damage = "1d6"
    default_weapon_damage = "1d8"

    #: Recognized damage types (SRD 5.2.1).
    DAMAGE_TYPES = frozenset({
        "acid", "bludgeoning", "cold", "fire", "force", "lightning",
        "necrotic", "piercing", "poison", "radiant", "slashing", "thunder",
    })

    #: Weapon proficiency categories (SRD 5.2.1).  A weapon carries one of
    #: these as an ``equip_tag``; a player proficient in the category (or in
    #: the weapon's individual ID) adds their proficiency bonus to attack
    #: rolls with it.  Unarmed strikes are always proficient.
    WEAPON_PROFICIENCY_CATEGORIES = ("simple", "martial")

    #: The 18 skills (SRD 5.2.1 "Skills" table), lowercase name -> governing
    #: ability score.  A stat check naming a skill uses the player's score in
    #: the governing ability, plus the proficiency bonus when the player is
    #: proficient in the skill (``player_state.skill_proficiencies``).
    SKILL_ABILITIES = {
        "acrobatics": "DEX",
        "animal handling": "WIS",
        "arcana": "INT",
        "athletics": "STR",
        "deception": "CHA",
        "history": "INT",
        "insight": "WIS",
        "intimidation": "CHA",
        "investigation": "INT",
        "medicine": "WIS",
        "nature": "INT",
        "perception": "WIS",
        "performance": "CHA",
        "persuasion": "CHA",
        "religion": "INT",
        "sleight of hand": "DEX",
        "stealth": "DEX",
        "survival": "WIS",
    }

    def apply_damage_modifiers(
        self,
        damage: int,
        damage_type: str,
        target_id: str,
        hard: HardGameState,
        corpus: ModuleCorpus,
    ) -> tuple[int, str | None]:
        """5e resistance (half, rounded down), vulnerability (double),
        immunity (zero).  Applied to NPC targets; the player has no
        damage-type modifiers yet (no-op hook for a future phase)."""
        if not damage_type or target_id == "player":
            return damage, None
        entity = corpus.entities.get(target_id)
        cb = entity.combat if entity else None
        if cb is None:
            return damage, None
        if damage_type in cb.immunities:
            return 0, "immune"
        if damage_type in cb.resistances:
            return damage // 2, "resisted"
        if damage_type in cb.vulnerabilities:
            return damage * 2, "vulnerable"
        return damage, None

    # ------------------------------------------------------------------
    # Modifiers & dice
    # ------------------------------------------------------------------
    def stat_value_for_check(self, stat: str, player_state: Any) -> int | None:
        """5e: a skill key resolves to the governing ability score."""
        ability = self.SKILL_ABILITIES.get(stat.lower())
        if ability is not None:
            return self._player_stat(getattr(player_state, "stats", None), ability)
        return super().stat_value_for_check(stat, player_state)

    def is_known_check_stat(self, stat: str) -> bool:
        return stat.lower() in self.SKILL_ABILITIES

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
        expr = expr.strip()
        if expr.startswith("half(") and expr.endswith(")"):
            inner = expr[5:-1].strip()
            raw_total, raw_str = self.roll_damage(inner, critical=critical)
            halved = max(1, raw_total // 2)
            return halved, f"half({raw_str})={halved}"

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

    def _equipped_weapon(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> "tuple[str, EquipBlock] | None":
        """Return ``(item_id, EquipBlock)`` of the first equipped weapon,
        else ``None``."""
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if (
                entity
                and entity.equip_block
                and "weapon" in entity.equip_block.equip_tags
            ):
                return item_id, entity.equip_block
        return None

    def _equipped_weapon_block(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> "EquipBlock | None":
        """Return the EquipBlock of the first equipped weapon, else None."""
        equipped = self._equipped_weapon(hard, corpus)
        return equipped[1] if equipped is not None else None

    def _player_proficient_with_weapon(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> bool:
        """Whether the player is proficient with the equipped weapon.

        Unarmed (no equipped weapon) is always proficient — everyone is
        proficient with unarmed strikes.  Otherwise each entry in the
        player's ``weapon_proficiencies`` is tested (the list is an OR of
        clauses); a clause matches when:

        - it is a bare string equal to the weapon's entity ID, or to one
          of :attr:`WEAPON_PROFICIENCY_CATEGORIES` present in the
          weapon's ``equip_tags``; or
        - it is a :class:`~mgmai.models.hard_state.WeaponProfClause`
          whose ``category`` matches one of the weapon's category tags
          and whose ``properties`` share at least one element with the
          weapon's ``properties`` (OR within the list) — e.g. the
          Rogue's "martial weapons that have the Finesse or Light
          property".

        A non-proficient weapon may still be used, but grants no
        proficiency bonus to the attack roll.
        """
        equipped = self._equipped_weapon(hard, corpus)
        if equipped is None:
            return True
        item_id, block = equipped
        profs = getattr(hard.player, "weapon_proficiencies", None) or []
        weapon_cats = set(block.equip_tags) & set(self.WEAPON_PROFICIENCY_CATEGORIES)
        weapon_props = set(block.properties)
        for clause in profs:
            if isinstance(clause, WeaponProfClause):
                if clause.category in weapon_cats and (
                    weapon_props & set(clause.properties)
                ):
                    return True
            elif clause == item_id or clause in weapon_cats:
                return True
        return False

    def _weapon_attack_stat(self, hard: HardGameState, corpus: ModuleCorpus) -> str:
        """Ability score for the equipped weapon's attack and damage rolls.

        ``ranged`` weapons use DEX; ``finesse`` weapons use the better of
        STR and DEX; everything else uses STR.
        """
        weapon = self._equipped_weapon_block(hard, corpus)
        props = weapon.properties if weapon else []
        if "ranged" in props:
            return "DEX"
        if "finesse" in props:
            str_mod = self.compute_modifier(self._player_stat(hard.player.stats, "STR"))
            dex_mod = self.compute_modifier(self._player_stat(hard.player.stats, "DEX"))
            return "DEX" if dex_mod > str_mod else "STR"
        return "STR"

    def player_attack_is_ranged(self, hard: HardGameState, corpus: ModuleCorpus) -> bool:
        """Whether the player's attack with the equipped weapon is ranged
        (5e: the weapon's ``properties`` carry ``ranged``).  Unarmed and
        improvised weapons count as melee."""
        weapon = self._equipped_weapon_block(hard, corpus)
        return weapon is not None and "ranged" in weapon.properties

    def compute_player_attack_bonus(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> int:
        """5e attack bonus: weapon ability mod + proficiency (when
        proficient with the weapon) + weapon bonuses.

        A non-proficient weapon still hits with the ability modifier and
        the weapon's ``hit_bonus``; only the proficiency bonus is withheld.
        Unarmed strikes are always proficient.
        """
        stats = hard.player.stats
        stat_mod = self.compute_modifier(
            self._player_stat(stats, self._weapon_attack_stat(hard, corpus))
        )
        prof = 0
        if self._player_proficient_with_weapon(hard, corpus):
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
        return stat_mod + prof + weapon_bonus

    def compute_player_damage_type(
        self, hard: HardGameState, corpus: ModuleCorpus
    ) -> str:
        """Damage type of the player's equipped weapon ("" when untyped —
        unarmed, improvised, or legacy weapons apply no type modifiers)."""
        weapon = self._equipped_weapon_block(hard, corpus)
        return weapon.damage_type if weapon else ""

    def attack_roll_mods(
        self, attacker_status_effects: dict, target_status_effects: dict, corpus: ModuleCorpus,
        engaged: bool = False,
    ) -> tuple[bool, bool]:
        """(advantage, disadvantage) from status-effect system effects (5e):

        - advantage: ``advantage_against`` ORed over the target's status
          effects (e.g. stunned), or ``advantage_on_attack`` ORed over the
          attacker's (e.g. invisible), or ``advantage_against_engaged``
          ORed over the target's when the attacker is engaged with it
          (e.g. prone, within reach)
        - disadvantage: ``disadvantage_on_attack`` ORed over the attacker's
          status effects (e.g. poisoned), or ``disadvantage_against`` ORed
          over the target's (e.g. invisible), or
          ``disadvantage_against_unengaged`` ORed over the target's when
          the attacker is not engaged with it (e.g. prone, at a distance)

        ``engaged`` is attacker <-> target engagement (theater-of-the-mind
        positioning) and defaults to False.
        """
        effect_defs = corpus.effective_status_effects()

        def _effects(active: dict) -> list[dict]:
            return [
                effect_defs[c].system_effects.get("5e", {})
                for c in active
                if c in effect_defs
            ]

        attacker_effects = _effects(attacker_status_effects)
        target_effects = _effects(target_status_effects)
        advantage = (
            any(e.get("advantage_against") for e in target_effects)
            or any(e.get("advantage_on_attack") for e in attacker_effects)
            or (engaged and any(e.get("advantage_against_engaged") for e in target_effects))
        )
        disadvantage = (
            any(e.get("disadvantage_on_attack") for e in attacker_effects)
            or any(e.get("disadvantage_against") for e in target_effects)
            or (not engaged and any(
                e.get("disadvantage_against_unengaged") for e in target_effects
            ))
        )
        return advantage, disadvantage

    # ------------------------------------------------------------------
    # Positioning (theater-of-the-mind engagement)
    # ------------------------------------------------------------------
    @staticmethod
    def _pair_engaged(hard: HardGameState, a: str, b: str) -> bool:
        """True if combatants *a* and *b* are engaged (within melee reach)."""
        combat = getattr(hard, "combat", None)
        if combat is None:
            return False
        pair = sorted((a, b))
        return any(sorted(p) == pair for p in combat.engagement)

    @staticmethod
    def _has_system_effect(status_effects: dict, corpus: ModuleCorpus, key: str) -> bool:
        """True if any active status effect sets the given 5e system key."""
        effect_defs = corpus.effective_status_effects()
        return any(
            effect_defs[c].system_effects.get("5e", {}).get(key)
            for c in status_effects
            if c in effect_defs
        )

    def _close_combat_threat(
        self, attacker_id: str, hard: HardGameState, corpus: ModuleCorpus
    ) -> bool:
        """True if the attacker is engaged with at least one living enemy
        able to punish a ranged attack (no ``skip_turn`` status effect and
        no pending impede flag — SRD: "can see you and isn't
        incapacitated")."""
        combat = getattr(hard, "combat", None)
        if combat is None:
            return False
        effect_defs = corpus.effective_status_effects()
        allies = set(combat.allies)
        attacker_side = attacker_id == "player" or attacker_id in allies
        for pair in combat.engagement:
            if attacker_id not in pair:
                continue
            other = pair[0] if pair[1] == attacker_id else pair[1]
            other_side = other == "player" or other in allies
            if attacker_side == other_side:
                continue  # not an enemy of the attacker
            if other != "player":
                if other not in combat.combatants:
                    continue
                if (hard.entity_states.get(other, {}).get("current_hp") or 0) <= 0:
                    continue
            if other in combat.impeded:
                continue
            if any(
                effect_defs[c].skip_turn
                for c in get_status_effects(other, hard)
                if c in effect_defs
            ):
                continue
            return True
        return False

    def d20_test_modifier(
        self, status_effects: dict, corpus: ModuleCorpus
    ) -> int:
        """Flat d20 modifier from the roller's status effects (5e): sums the
        ``d20_test_modifier`` keys of the roller's active effects (the
        exhaustion conditions).  Applies to every d20 test — attack rolls,
        ability checks, and saving throws."""
        effect_defs = corpus.effective_status_effects()
        return sum(
            effect_defs[c].system_effects.get("5e", {}).get("d20_test_modifier", 0)
            for c in status_effects
            if c in effect_defs
        )

    def save_auto_fail(
        self, stat: str, status_effects: dict, corpus: ModuleCorpus
    ) -> bool:
        """5e: ``auto_fail_str_dex_saves`` (paralyzed, petrified, stunned,
        unconscious) forces STR and DEX saving throws to fail without a
        roll."""
        if stat.upper() not in ("STR", "DEX"):
            return False
        effect_defs = corpus.effective_status_effects()
        return any(
            effect_defs[c].system_effects.get("5e", {}).get("auto_fail_str_dex_saves")
            for c in status_effects
            if c in effect_defs
        )

    def check_roll_mods(
        self, is_save: bool, status_effects: dict, corpus: ModuleCorpus
    ) -> tuple[bool, bool]:
        """(advantage, disadvantage) for an ability/skill check (5e): ORs
        ``advantage_on_ability_checks`` / ``disadvantage_on_ability_checks``
        over the roller's status effects.  Saving throws are not ability
        checks in 5e (SRD: Poisoned affects "attack rolls and ability
        checks"), so ``is_save`` short-circuits to neither."""
        if is_save:
            return False, False
        effect_defs = corpus.effective_status_effects()
        effects = [
            effect_defs[c].system_effects.get("5e", {})
            for c in status_effects
            if c in effect_defs
        ]
        advantage = any(e.get("advantage_on_ability_checks") for e in effects)
        disadvantage = any(e.get("disadvantage_on_ability_checks") for e in effects)
        return advantage, disadvantage

    def compute_player_damage_expr(
        self,
        hard: HardGameState,
        corpus: ModuleCorpus,
        soft: object | None = None,
    ) -> str:
        """5e damage expression: weapon dice + ability mod, or unarmed."""
        stats = hard.player.stats
        str_mod = self.compute_modifier(self._player_stat(stats, "STR"))

        # Equipped weapon (ability mod per its properties)
        weapon = self._equipped_weapon_block(hard, corpus)
        if weapon is not None:
            stat_mod = self.compute_modifier(
                self._player_stat(stats, self._weapon_attack_stat(hard, corpus))
            )
            return (
                f"{weapon.damage_expr}+{stat_mod}"
                if stat_mod >= 0
                else f"{weapon.damage_expr}{stat_mod}"
            )

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
        player_effects = get_status_effects("player", hard)
        target_effects = get_status_effects(target_id, hard)
        engaged_with_target = self._pair_engaged(hard, "player", target_id)
        adv, disadv = self.attack_roll_mods(
            player_effects, target_effects, corpus, engaged=engaged_with_target
        )
        # Ranged attacks in close combat: Disadvantage while within reach
        # of a living, non-incapacitated enemy.
        if self.player_attack_is_ranged(hard, corpus) and self._close_combat_threat(
            "player", hard, corpus
        ):
            disadv = True
        attack_roll = self.roll_die(20, advantage=adv, disadvantage=disadv)
        attack_total = (
            attack_roll + atk_bonus + self.d20_test_modifier(player_effects, corpus)
        )
        critical = self.is_critical(attack_roll)
        miss = self.is_fumble(attack_roll)
        hit = critical or (not miss and attack_total >= target_ac)
        # A hit from within reach against e.g. an unconscious target is an
        # automatic critical.
        if (
            hit
            and not critical
            and engaged_with_target
            and self._has_system_effect(target_effects, corpus, "auto_crit_against_engaged")
        ):
            critical = True

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
            damage_type = self.compute_player_damage_type(hard, corpus)
            damage, mitigation = self.apply_damage_modifiers(
                damage, damage_type, target_id, hard, corpus
            )
            log_entry.damage_roll = damage_roll
            log_entry.damage = damage
            log_entry.damage_type = damage_type or None
            log_entry.mitigation = mitigation
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
        target_id: str,
        target_ac: int,
        round_number: int,
        attack: "NPCAttackDef | None" = None,
        player_hp_pending: int = 0,
    ) -> NPCAttackResult:
        """Resolve an NPC attack against a combatant (player or NPC).

        ``attack=None`` resolves the basic attack (block-level fields).
        ``player_hp_pending`` is the player HP delta accumulated earlier
        this turn; the player's effective HP is the base value plus this
        delta, since ``hard.player`` is not mutated mid-turn.
        """
        entity = corpus.entities.get(npc_id)
        if entity is None or entity.combat is None:
            raise ValueError(f"Invalid NPC '{npc_id}'")

        combat_block = entity.combat
        atk_bonus = attack.atk if attack is not None else (combat_block.atk or 0)
        dmg_expr = attack.dmg if attack is not None else combat_block.dmg
        dmg_type = (
            (attack.dmg_type or combat_block.dmg_type)
            if attack is not None
            else combat_block.dmg_type
        )
        # Per-attack override, falling back to the block-level flag (same
        # pattern as dmg_type) so block-level ``ranged`` is not silently
        # ignored when an ``attacks`` list is present.
        is_ranged = (
            (attack.ranged or combat_block.ranged)
            if attack is not None
            else combat_block.ranged
        )

        npc_effects = get_status_effects(npc_id, hard)
        target_effects = get_status_effects(target_id, hard)
        engaged_with_target = self._pair_engaged(hard, npc_id, target_id)
        adv, disadv = self.attack_roll_mods(
            npc_effects, target_effects, corpus, engaged=engaged_with_target
        )
        # Ranged attacks in close combat: Disadvantage while within reach
        # of a living, non-incapacitated enemy.
        if is_ranged and self._close_combat_threat(npc_id, hard, corpus):
            disadv = True
        attack_roll = self.roll_die(20, advantage=adv, disadvantage=disadv)
        attack_total = (
            attack_roll + atk_bonus + self.d20_test_modifier(npc_effects, corpus)
        )
        critical = self.is_critical(attack_roll)
        miss = self.is_fumble(attack_roll)
        hit = critical or (not miss and attack_total >= target_ac)
        # A hit from within reach against e.g. an unconscious target is an
        # automatic critical.
        if (
            hit
            and not critical
            and engaged_with_target
            and self._has_system_effect(target_effects, corpus, "auto_crit_against_engaged")
        ):
            critical = True

        log_entry = CombatLogEntry(
            round=round_number,
            actor=npc_id,
            action="attack",
            target=target_id,
            attack_roll=attack_roll,
            attack_total=attack_total,
            ac=target_ac,
            hit=hit,
            critical=critical if hit else None,
            attack_id=attack.id if attack is not None else None,
            attack_name=(attack.name or attack.id) if attack is not None else None,
        )
        log_entries: list[CombatLogEntry] = [log_entry]

        damage = 0
        damage_roll: str | None = None
        target_hp_delta = 0
        target_died = False

        if hit:
            damage, damage_roll = self.roll_damage(
                dmg_expr, critical=critical
            )
            damage, mitigation = self.apply_damage_modifiers(
                damage, dmg_type, target_id, hard, corpus
            )
            log_entry.damage_roll = damage_roll
            log_entry.damage = damage
            log_entry.damage_type = dmg_type or None
            log_entry.mitigation = mitigation
            target_hp_delta = -damage
            if target_id == "player":
                current_hp = (hard.player.current_hp or 0) + player_hp_pending
            else:
                current_hp = (
                    hard.entity_states.get(target_id, {}).get("current_hp") or 0
                )
            new_hp = current_hp - damage
            log_entry.remaining_hp = new_hp

            if new_hp <= 0:
                death_entry = CombatLogEntry(
                    round=round_number,
                    actor=target_id,
                    action="death",
                )
                log_entries.append(death_entry)
                target_died = True

        return NPCAttackResult(
            hit=hit,
            damage=damage,
            target_hp_delta=target_hp_delta,
            log_entries=log_entries,
            target_died=target_died,
            attack_roll=attack_roll,
            attack_total=attack_total,
            target_ac=target_ac,
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
        # Conditions may impose advantage/disadvantage on ability checks
        # (e.g. poisoned) or a flat d20 penalty (e.g. exhaustion).
        player_effects = get_status_effects("player", hard)
        advantage, disadvantage = self.check_roll_mods(False, player_effects, corpus)
        roll = self.roll_die(20, advantage=advantage, disadvantage=disadvantage)
        total = roll + dex_mod + self.d20_test_modifier(player_effects, corpus)
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
    # Proficiency (saving throws for CheckResolution saves; skill checks)
    # ------------------------------------------------------------------
    def compute_save_modifier(self, stat: str, player_state: Any) -> int:
        """5e: proficient saves add the player's proficiency bonus."""
        profs = getattr(player_state, "save_proficiencies", [])
        if stat in profs:
            return getattr(player_state, "proficiency_bonus", None) or 2
        return 0

    def skill_modifier(self, stat: str, player_state: Any) -> int:
        """5e: proficient skills add the player's proficiency bonus.

        ``stat`` is a skill name (matched case-insensitively); proficiency is
        a property of the player, not of the check."""
        profs = getattr(player_state, "skill_proficiencies", []) or []
        if stat.lower() in self.SKILL_ABILITIES and any(
            p.lower() == stat.lower() for p in profs
        ):
            return getattr(player_state, "proficiency_bonus", None) or 2
        return 0

    def proficiency_bonus(self, check, player_state: Any) -> int:
        """5e: apply save or skill proficiency when it applies."""
        if getattr(check, "save", False):
            return self.compute_save_modifier(check.stat, player_state)
        return self.skill_modifier(check.stat, player_state)

    # get_equip_incompatibilities() — inherit default (two_handed is now
    # a conventional equip_tag with explicit incompatible_with entries).
