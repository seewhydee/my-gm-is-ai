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
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.engine.systems import get_system, get_system_for_corpus
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


def compute_player_ac(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> int:
    """Compute player AC with equipment modifiers.

    Delegates the AC formula (and how gear modifies it) to the active
    resolution system.  Kept as a free function for backward compatibility
    with callers (assembler, tests).
    """
    return get_system_for_corpus(corpus).compute_player_ac(hard, corpus)


def get_player_ac(hard: HardGameState) -> int:
    """Return player AC (corpus-less, equipment-unaware backward-compat shim).

    The combat engine and assembler use ``compute_player_ac(hard, corpus)``
    (which delegates to the active system and applies gear).  This shim is
    retained for corpus-less callers and tests; without a corpus it cannot
    know the active system, so it falls back to the default (5e) system's
    base AC from Dexterity.
    """
    if hard.player.ac is not None:
        return hard.player.ac
    # No corpus available; fall back to the default (5e) system.
    return get_system("5e").base_ac(_get_stat(hard.player.stats, "DEX"))


def get_player_max_hp(hard: HardGameState) -> int:
    """Return player max HP (corpus-less backward-compat shim).

    Callers with a corpus should use
    ``get_system_for_corpus(corpus).compute_player_max_hp(hard, corpus)``
    instead.  Without a corpus this falls back to the default (5e) system's
    base max HP from Constitution.
    """
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

    Ties are broken by initiative modifier, then coin flip.
    """
    system = get_system_for_corpus(corpus)

    entries: list[tuple[str, int, int, float]] = []  # (id, roll, tiebreaker, coin)

    # Player
    player_mod = system.compute_player_initiative_modifier(hard, corpus)
    player_roll = system.roll_initiative(player_mod)
    entries.append(("player", player_roll, player_mod, random.random()))

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
    system = get_system_for_corpus(corpus)

    # Initialize player HP if absent
    if hard.player.current_hp is None:
        hard.player.current_hp = system.compute_player_max_hp(hard, corpus)
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
    player_ac = compute_player_ac(hard, corpus)
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

        npc_result = system.resolve_npc_attack(
            actor_id, hard, corpus, player_ac, 1,
        )
        combat_log.extend(npc_result.log_entries)
        if npc_result.player_hp_delta:
            hard_changes.player_hp_delta = (
                (hard_changes.player_hp_delta or 0) + npc_result.player_hp_delta
            )
        if npc_result.game_over:
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

        target_ac = entity.combat.ac
        pa_result = system.resolve_player_attack(hard, corpus, target_id, target_ac, combat.round_number)
        combat_log.extend(pa_result.log_entries)

        if pa_result.hit:
            new_hp = (npc_state.get("current_hp") or 0) + pa_result.target_hp_delta
            hard_changes.entity_state_changes.setdefault(target_id, {})[
                "current_hp"
            ] = new_hp

            if new_hp <= 0:
                hard_changes.entity_state_changes.setdefault(target_id, {})[
                    "alive"
                ] = False
                # Remove from combatants — note: also handled by engine
                # via entity_state_changes, but we track it locally too
                if target_id in combat.combatants:
                    combat.combatants.remove(target_id)

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
        flee_result = system.resolve_flee(
            hard, corpus, flee_dc, combat.round_number
        )
        # Tag the log entry with the exit being fled through (engine concept).
        for entry in flee_result.log_entries:
            entry.target = action.target
        combat_log.extend(flee_result.log_entries)

        if flee_result.success:
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
        player_ac = compute_player_ac(hard, corpus)
        # advance past the player
        idx = (player_idx + 1) % n
        while idx != player_idx:
            actor_id = initiative[idx]
            if actor_id != "player":
                ent = corpus.entities.get(actor_id)
                if ent and ent.combat:
                    npc_state = hard.entity_states.get(actor_id, {})
                    if (npc_state.get("current_hp") or 0) > 0:
                        npc_result = system.resolve_npc_attack(
                            actor_id,
                            hard,
                            corpus,
                            player_ac,
                            combat.round_number,
                        )
                        combat_log.extend(npc_result.log_entries)
                        if npc_result.player_hp_delta:
                            hard_changes.player_hp_delta = (
                                (hard_changes.player_hp_delta or 0)
                                + npc_result.player_hp_delta
                            )
                        if npc_result.game_over:
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
