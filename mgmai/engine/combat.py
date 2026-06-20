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

"""Combat resolver — turn-based HP combat with initiative, attacks, and fleeing.

This module is the engine's combat phase handler.  It is called by the
resolver when the player enters combat or takes a combat action, and by
the engine when an encounter produces a ``"combat"`` outcome.
"""

from __future__ import annotations

import random
from typing import Any

from mgmai.models.actions import (
    CombatAction,
    HardStateChanges,
    MoveAction,
)
from mgmai.models.combat import CombatLogEntry, CombatState
from mgmai.models.corpus import CombatBlock, ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.engine.systems import get_system, get_system_for_corpus
from mgmai.engine.systems.base import SaveResult
from mgmai.engine.systems.dice import parse_damage_dice


# ------------------------------------------------------------------
# Damage dice parsing & rolling
# ------------------------------------------------------------------
# ``parse_damage_dice`` is imported from ``mgmai.engine.systems.dice`` and
# re-exported here for backward compatibility.  ``roll_damage`` is a thin
# wrapper around the 5e system for standalone/legacy callers; the combat
# loop resolves damage through the corpus's active system directly.

def roll_damage(expr: str, critical: bool = False) -> tuple[int, str]:
    """Roll damage from a dice expression (5e crit rule).

    Returns ``(total, readable_string)``.  Delegates to the 5e resolution
    system; the combat loop uses the corpus's active system directly via
    ``system.roll_damage``.
    """
    return get_system("5e").roll_damage(expr, critical=critical)


# ------------------------------------------------------------------
# Player stat computation
# ------------------------------------------------------------------

def _get_stat(stats: dict[str, int] | None, key: str) -> int:
    """Return a stat value, defaulting to 10."""
    if stats is None:
        return 10
    return stats.get(key, 10)


def compute_effective_stats(
    hard_state: HardGameState,
    corpus: ModuleCorpus,
) -> dict[str, int] | None:
    """Build effective stats from permanent baseline + equipped item effects.

    Per plan.md §4d: start with hard.player.stats, apply set modifiers
    first, then delta modifiers from each equipped item's equip_effects.
    Returns None if the player has no stats block.
    """
    from mgmai.models.corpus import StatModifier
    from copy import deepcopy

    base = hard_state.player.stats
    if base is None:
        return None

    effective = dict(base)

    for item_id in hard_state.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity is None or entity.equip_block is None:
            continue
        for stat_key, mod in entity.equip_block.equip_effects.items():
            if mod.mode == "set":
                effective[mod.stat] = mod.value
            elif mod.mode == "delta" and mod.stat in effective:
                effective[mod.stat] += mod.value

    return effective


def get_player_attack_bonus(
    hard: HardGameState,
    corpus: ModuleCorpus,
    effective_stats: dict[str, int] | None = None,
) -> int:
    """Compute player melee attack bonus: STR modifier + proficiency + weapon bonuses.

    If effective_stats is provided (from compute_effective_stats), uses those
    instead of hard.player.stats so equipment-based stat changes apply.
    """
    system = get_system_for_corpus(corpus)

    stats = effective_stats if effective_stats is not None else hard.player.stats
    str_mod = system.compute_modifier(_get_stat(stats, "STR"))
    prof = hard.player.proficiency_bonus or 2

    # Sum attack_bonus from all equipped weapons
    weapon_bonus = 0
    for item_id in hard.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity and entity.equip_block and "weapon" in entity.equip_block.equip_tags:
            weapon_bonus += entity.equip_block.attack_bonus

    return str_mod + prof + weapon_bonus


def get_player_damage_expr(
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: object = None,
    effective_stats: dict[str, int] | None = None,
) -> str:
    """Determine player damage expression.

    Priority (highest first):
    1. Equipped weapon damage_expr from equip_block.
    2. Improvised weapon (from soft.improvised_weapon).
    3. Any item tagged ``weapon`` in inventory (legacy fallback) → default weapon damage.
    4. Unarmed → system unarmed damage.
    """
    system = get_system_for_corpus(corpus)

    stats = effective_stats if effective_stats is not None else hard.player.stats
    str_mod = system.compute_modifier(_get_stat(stats, "STR"))

    # Check equipped weapons first
    for item_id in hard.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity and entity.equip_block and "weapon" in entity.equip_block.equip_tags:
            base = entity.equip_block.damage_expr
            if str_mod >= 0:
                return f"{base}+{str_mod}"
            else:
                return f"{base}{str_mod}"

    # Check improvised weapon
    if soft is not None:
        from mgmai.models.soft_state import SoftGameState
        if isinstance(soft, SoftGameState) and soft.improvised_weapon is not None:
            base = soft.improvised_weapon.damage_expr
            if str_mod >= 0:
                return f"{base}+{str_mod}"
            else:
                return f"{base}{str_mod}"

    # Legacy: check inventory for weapon tag
    has_weapon = False
    for item_id in hard.player.inventory:
        entity = corpus.entities.get(item_id)
        if entity and "weapon" in entity.tags:
            has_weapon = True
            break

    base = system.default_weapon_damage if has_weapon else system.unarmed_damage
    if str_mod >= 0:
        return f"{base}+{str_mod}"
    else:
        return f"{base}{str_mod}"


def compute_player_ac(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> int:
    """Compute player AC with equipment modifiers.

    Per plan.md §4c:
    1. Base AC = 10 + DEX mod (or hard.player.ac if explicitly set).
    2. Apply ac_override from equipped items (use max).
    3. Add all ac_bonus values from equipped items.
    """
    # Step 1: Base AC
    if hard.player.ac is not None:
        base_ac = hard.player.ac
    else:
        base_ac = get_system_for_corpus(corpus).base_ac(
            _get_stat(hard.player.stats, "DEX")
        )

    # Step 2: Apply ac_override (highest wins)
    ac_override = None
    for item_id in hard.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity and entity.equip_block and entity.equip_block.ac_override is not None:
            if ac_override is None or entity.equip_block.ac_override > ac_override:
                ac_override = entity.equip_block.ac_override

    effective_ac = ac_override if ac_override is not None else base_ac

    # Step 3: Add all ac_bonus values
    for item_id in hard.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity and entity.equip_block:
            effective_ac += entity.equip_block.ac_bonus

    return effective_ac


def get_player_ac(hard: HardGameState) -> int:
    """Return player AC (backward-compatible, equipment-unaware).

    Used by the combat engine to compute NPC hit chance against the player.
    Note: the combat engine currently calls this directly.  After the gear
    implementation is complete, call sites should use compute_player_ac()
    with corpus access for full equipment-aware AC.
    """
    if hard.player.ac is not None:
        return hard.player.ac
    # No corpus available; fall back to the default (5e) system.
    return get_system("5e").base_ac(_get_stat(hard.player.stats, "DEX"))


def get_player_max_hp(hard: HardGameState) -> int:
    """Return player max HP.  Computed from CON if not explicitly set."""
    if hard.player.max_hp is not None:
        return hard.player.max_hp
    # No corpus available; fall back to the default (5e) system.
    return get_system("5e").base_max_hp(_get_stat(hard.player.stats, "CON"))


# ------------------------------------------------------------------
# Initiative
# ------------------------------------------------------------------

def roll_initiative(
    hard: HardGameState,
    corpus: ModuleCorpus,
    enemy_ids: list[str],
) -> list[str]:
    """Roll initiative for the player and all enemies.  Return sorted order.

    Ties are broken by DEX/initiative modifier, then coin flip.
    """
    system = get_system_for_corpus(corpus)

    entries: list[tuple[str, int, int, float]] = []  # (id, roll, tiebreaker, coin)

    # Player
    dex_mod = 0
    if hard.player.stats and "DEX" in hard.player.stats:
        dex_mod = system.compute_modifier(hard.player.stats["DEX"])
    player_roll = system.roll_initiative(dex_mod)
    entries.append(("player", player_roll, dex_mod, random.random()))

    # Enemies
    for eid in enemy_ids:
        entity = corpus.entities.get(eid)
        if entity is None or entity.combat is None:
            continue
        npc_roll = system.roll_initiative(entity.combat.initiative_mod)
        entries.append(
            (eid, npc_roll, entity.combat.initiative_mod, random.random())
        )

    # Sort: highest roll first, then tiebreaker, then coin flip
    entries.sort(key=lambda e: (e[1], e[2], e[3]), reverse=True)
    return [e[0] for e in entries]


# ------------------------------------------------------------------
# NPC attack resolution (internal helper)
# ------------------------------------------------------------------

def _resolve_npc_attack(
    npc_id: str,
    combat_block: CombatBlock,
    hard: HardGameState,
    corpus: ModuleCorpus,
    round_number: int,
) -> dict[str, Any]:
    """Resolve a single NPC's attack against the player.

    Returns a dict with ``log`` (list of CombatLogEntry), ``player_hp_delta``,
    and ``game_over``.
    """
    system = get_system_for_corpus(corpus)

    # Use equipment-aware AC when the player has equipped items
    if hard.player.equipped:
        player_ac = compute_player_ac(hard, corpus)
    else:
        player_ac = get_player_ac(hard)
    attack_roll = system.roll_die(20)
    attack_total = attack_roll + combat_block.atk
    critical = system.is_critical(attack_roll)
    miss = system.is_fumble(attack_roll)
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

    result: dict[str, Any] = {
        "log": [log_entry],
        "player_hp_delta": 0,
        "game_over": False,
    }

    if hit:
        damage, dmg_str = system.roll_damage(combat_block.dmg, critical=critical)
        log_entry.damage_roll = dmg_str
        log_entry.damage = damage
        total_damage = damage

        # On-hit effects (secondary damage via saving throws)
        for effect in combat_block.on_hit_effects:
            eh_result = _resolve_on_hit_effect(
                effect, hard, system, round_number,
            )
            log_entry.on_hit_effects.append(eh_result)
            total_damage += eh_result.get("damage", 0)

        result["player_hp_delta"] = -total_damage
        new_hp = (hard.player.current_hp or 0) - total_damage
        log_entry.remaining_hp = new_hp
        if new_hp <= 0:
            death_entry = CombatLogEntry(
                round=round_number,
                actor="player",
                action="death",
            )
            result["log"].append(death_entry)
            result["game_over"] = True

    return result


def _resolve_on_hit_effect(
    effect: object,
    hard: HardGameState,
    system: object,
    round_number: int,
) -> dict[str, Any]:
    """Resolve a single on-hit effect against the player.

    Returns a dict suitable for ``CombatLogEntry.on_hit_effects`` with
    keys: ``save_stat``, ``save_dc``, ``save_roll``, ``save_total``,
    ``save_success``, ``damage_expr``, ``damage``, ``on_save``,
    ``damage_type``.
    """
    save_stat = effect.save.stat.upper()
    save_dc = effect.save.dc

    stat_value = (hard.player.stats or {}).get(save_stat, 10)
    proficient = save_stat in hard.player.save_proficiencies
    prof_bonus = hard.player.proficiency_bonus or 2

    save_result: SaveResult = system.resolve_save(
        save_stat, stat_value, save_dc,
        proficient=proficient,
        proficiency_bonus=prof_bonus,
    )

    effect_damage = 0
    dmg_expr = effect.damage
    on_save = effect.on_save

    if on_save == "none" and save_result.success:
        effect_damage = 0
    else:
        raw_damage, _ = system.roll_damage(dmg_expr)
        if on_save == "half" and save_result.success:
            effect_damage = max(1, raw_damage // 2)
        else:
            effect_damage = raw_damage

    return {
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


# ------------------------------------------------------------------
# Combat entry
# ------------------------------------------------------------------

def enter_combat(
    enemy_ids: list[str],
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> dict[str, Any]:
    """Initialize combat state, roll initiative, resolve pre-player NPC turns.

    Returns a dict with ``combat_log``, ``hard_changes``, ``combat_triggered``,
    and ``game_over``.
    """
    # Initialize player HP if absent
    if hard.player.current_hp is None:
        hard.player.current_hp = get_player_max_hp(hard)
        hard.player.max_hp = hard.player.max_hp or hard.player.current_hp

    # Initialize NPC current_hp from combat block
    for eid in enemy_ids:
        entity = corpus.entities.get(eid)
        if entity is None or entity.combat is None:
            continue
        state = hard.entity_states.setdefault(eid, {})
        if state.get("current_hp") is None:
            state["current_hp"] = entity.combat.hp

    # Roll initiative once
    initiative_order = roll_initiative(hard, corpus, enemy_ids)

    # Create combat state
    combat = CombatState(
        active=True,
        combatants=["player"] + list(enemy_ids),
        initiative_order=initiative_order,
        current_index=0,
        round_number=1,
        log=[],
    )
    hard.combat = combat

    # Resolve NPC turns before the player's first turn
    hard_changes = HardStateChanges()
    combat_log: list[CombatLogEntry] = []
    game_over = False

    player_idx = initiative_order.index("player")
    for i in range(player_idx):
        actor_id = initiative_order[i]
        if actor_id == "player":
            continue
        entity = corpus.entities.get(actor_id)
        if entity is None or entity.combat is None:
            continue
        npc_state = hard.entity_states.get(actor_id, {})
        if (npc_state.get("current_hp") or 0) <= 0:
            continue

        npc_result = _resolve_npc_attack(
            actor_id, entity.combat, hard, corpus, 1,
        )
        combat_log.extend(npc_result["log"])
        if npc_result.get("player_hp_delta"):
            hard_changes.player_hp_delta = (
                (hard_changes.player_hp_delta or 0) + npc_result["player_hp_delta"]
            )
        if npc_result.get("game_over"):
            game_over = True
            break

    combat.current_index = player_idx
    combat.log.extend(combat_log)

    return {
        "combat_log": combat_log,
        "hard_changes": hard_changes,
        "combat_triggered": True,
        "game_over": game_over,
    }


# ------------------------------------------------------------------
# Combat turn resolution
# ------------------------------------------------------------------

def resolve_combat_turn(
    action: CombatAction | MoveAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> dict[str, Any]:
    """Resolve the player's combat action and any following NPC turns.

    Returns a dict with ``success``, ``hard_changes``, ``combat_log``,
    ``game_over``, and ``error`` (if failure).
    """
    combat = hard.combat
    if combat is None or not combat.active:
        return {"success": False, "error": "Not in combat"}

    system = get_system_for_corpus(corpus)

    hard_changes = HardStateChanges()
    combat_log: list[CombatLogEntry] = []
    game_over = False
    combat_ended = False

    if isinstance(action, CombatAction):
        # --- Player attack ---
        target_id = action.target
        if target_id not in combat.combatants:
            return {"success": False, "error": f"Target '{target_id}' not in combat"}

        entity = corpus.entities.get(target_id)
        if entity is None or entity.combat is None:
            return {"success": False, "error": f"Invalid combat target '{target_id}'"}

        npc_state = hard.entity_states.get(target_id, {})
        if (npc_state.get("current_hp") or 0) <= 0:
            return {"success": False, "error": f"Target '{target_id}' is already dead"}

        atk_bonus = get_player_attack_bonus(hard, corpus)
        attack_roll = system.roll_die(20)
        attack_total = attack_roll + atk_bonus
        critical = system.is_critical(attack_roll)
        miss = system.is_fumble(attack_roll)
        hit = critical or (not miss and attack_total >= entity.combat.ac)

        log_entry = CombatLogEntry(
            round=combat.round_number,
            actor="player",
            action="attack",
            target=target_id,
            attack_roll=attack_roll,
            attack_total=attack_total,
            ac=entity.combat.ac,
            hit=hit,
            critical=critical if hit else None,
        )

        if hit:
            dmg_expr = get_player_damage_expr(hard, corpus)
            damage, dmg_str = system.roll_damage(dmg_expr, critical=critical)
            log_entry.damage_roll = dmg_str
            log_entry.damage = damage
            new_hp = (npc_state.get("current_hp") or 0) - damage
            hard_changes.entity_state_changes.setdefault(target_id, {})[
                "current_hp"
            ] = new_hp
            log_entry.remaining_hp = new_hp

            if new_hp <= 0:
                death_log = CombatLogEntry(
                    round=combat.round_number,
                    actor=target_id,
                    action="death",
                )
                combat_log.append(death_log)
                hard_changes.entity_state_changes.setdefault(target_id, {})[
                    "alive"
                ] = False
                # Remove from combatants — note: also handled by engine
                # via entity_state_changes, but we track it locally too
                if target_id in combat.combatants:
                    combat.combatants.remove(target_id)
        else:
            log_entry.remaining_hp = npc_state.get("current_hp")

        combat_log.append(log_entry)

        # Check if all enemies are dead
        alive_enemies = [
            c
            for c in combat.combatants
            if c != "player"
            and (hard.entity_states.get(c, {}).get("current_hp") or 0) > 0
        ]
        if not alive_enemies:
            combat_ended = True

    elif isinstance(action, MoveAction):
        # --- Flee attempt ---
        flee_dc = max(
            (
                corpus.entities.get(c).combat.flee_dc
                for c in combat.combatants
                if c != "player"
                and corpus.entities.get(c)
                and corpus.entities.get(c).combat
            ),
            default=10,
        )
        dex_mod = 0
        if hard.player.stats and "DEX" in hard.player.stats:
            dex_mod = system.compute_modifier(hard.player.stats["DEX"])
        flee_roll = system.roll_die(20)
        flee_total = flee_roll + dex_mod
        flee_success = flee_total >= flee_dc

        flee_log = CombatLogEntry(
            round=combat.round_number,
            actor="player",
            action="flee",
            target=action.target,
            attack_roll=flee_roll,
            attack_total=flee_total,
            ac=flee_dc,
            hit=flee_success,
        )
        combat_log.append(flee_log)

        if flee_success:
            combat_ended = True
            # Move the player to the target room
            room = corpus.rooms.get(hard.player.location)
            if room:
                for ex in room.exits:
                    if ex.id == action.target:
                        hard_changes.player_location = ex.target_room
                        break
        # On failure: turn is consumed, combat continues
    else:
        return {"success": False, "error": "Invalid action in combat"}

    # --- Resolve NPC turns after the player ---
    if not combat_ended and not game_over:
        initiative = combat.initiative_order
        n = len(initiative)
        player_idx = initiative.index("player")
        # advance past the player
        idx = (player_idx + 1) % n
        while idx != player_idx:
            actor_id = initiative[idx]
            if actor_id != "player":
                ent = corpus.entities.get(actor_id)
                if ent and ent.combat:
                    npc_state = hard.entity_states.get(actor_id, {})
                    if (npc_state.get("current_hp") or 0) > 0:
                        npc_result = _resolve_npc_attack(
                            actor_id, ent.combat, hard, corpus, combat.round_number,
                        )
                        combat_log.extend(npc_result["log"])
                        if npc_result.get("player_hp_delta"):
                            hard_changes.player_hp_delta = (
                                (hard_changes.player_hp_delta or 0)
                                + npc_result["player_hp_delta"]
                            )
                        if npc_result.get("game_over"):
                            game_over = True
                            break
            idx = (idx + 1) % n

        # Advance to next round
        combat.round_number += 1
        combat.current_index = player_idx

    combat.log.extend(combat_log)

    if combat_ended:
        hard.combat = None
    elif game_over:
        hard.combat = None

    return {
        "success": True,
        "hard_changes": hard_changes,
        "combat_log": combat_log,
        "game_over": game_over,
    }
