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
    WaitAction,
)
from mgmai.models.combat import CombatLogEntry, CombatState
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.utils import get_status_effects, get_following_npc_ids
from mgmai.engine.status_effects import (
    apply_status_effect,
    emit_status_effect_event,
    remove_status_effect,
)
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
    first, then delta modifiers from each equipped item's stat_effects.
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
        for stat_key, mod in entity.equip_block.stat_effects.items():
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
    npc_ids: list[str],
) -> list[str]:
    """Roll initiative for the player and all NPC combatants (allies and
    enemies).  Return sorted order.

    Ties are broken by initiative modifier, then coin flip.
    """
    system = get_system_for_corpus(corpus)

    entries: list[tuple[str, int, int, float]] = []  # (id, roll, tiebreaker, coin)

    # Player
    player_mod = system.compute_player_initiative_modifier(hard, corpus)
    player_roll = system.roll_initiative(player_mod)
    entries.append(("player", player_roll, player_mod, random.random()))

    # NPCs
    for eid in npc_ids:
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
# On-hit effect resolution (via generic CheckResolution)
# ------------------------------------------------------------------

def _resolve_npc_on_hits(
    npc_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None,
    hard_changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    rolls: list[dict[str, Any]],
    *,
    round_number: int,
    on_hit_effects: list,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[CombatLogEntry], bool]:
    """Resolve an NPC's on-hit ``CheckResolution`` effects.

    Effects are resolved independently and damage accumulates in
    *hard_changes.player_hp_delta*. Returns ``(on_hit_log_entries,
    death_log_entries, game_over)``.
    """
    from mgmai.engine.resolver import _resolve_checkable, ResolutionResult

    entity = corpus.entities.get(npc_id)
    if entity is None or entity.combat is None:
        return [], [], False

    on_hit_log: list[dict[str, Any]] = []
    death_log: list[CombatLogEntry] = []
    game_over = False

    for effect in on_hit_effects:
        # Stop if the player is already dead from the base attack or a
        # previous on-hit effect.
        effective_hp = (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0)
        if effective_hp <= 0 or game_over or hard.game_over is not None:
            break

        hp_before = hard_changes.player_hp_delta or 0
        rolls_before = len(rolls)

        # A throwaway ResolutionResult collects events emitted by the
        # effect; only status-effect events (e.g. status_effect.applied from
        # apply_status_effect) are forwarded — check events keep their
        # historical no-event behavior for combat on-hits.
        on_hit_resolution = ResolutionResult(success=True) if events is not None else None
        passed = _resolve_checkable(
            effect,
            hard=hard,
            soft=soft,
            corpus=corpus,
            room_id=hard.player.location,
            changes=hard_changes,
            narrative=narrative,
            revealed_hints=revealed_hints,
            rolls=rolls,
            state_manager=state_manager,
            resolution=on_hit_resolution,
            source_id=npc_id,
            source_type="combat",
        )
        if events is not None:
            events.extend(
                ev for ev in on_hit_resolution.events
                if ev[0].startswith("status_effect.")
            )

        # Identify the primary check roll among any rolls added by the
        # resolution (nested then_checks may add further rolls).
        primary_roll: dict[str, Any] | None = None
        for r in rolls[rolls_before:]:
            if r.get("check_type") in ("stat_check", "roll"):
                primary_roll = r
                break

        save_success = bool(primary_roll.get("success")) if primary_roll else passed
        branch = effect.success if save_success else effect.failure
        damage_expr = branch.player_damage if branch is not None else None

        hp_after = hard_changes.player_hp_delta or 0
        damage = hp_before - hp_after

        on_hit_log.append(
            {
                "save_stat": primary_roll.get("stat") if primary_roll else None,
                "save_dc": primary_roll.get("target") if primary_roll else None,
                "save_roll": primary_roll.get("raw_roll") if primary_roll else None,
                "save_total": primary_roll.get("total") if primary_roll else None,
                "save_success": save_success,
                "damage_expr": damage_expr,
                "damage": damage,
                "damage_type": effect.tag,
            }
        )

        if hard.game_over is not None:
            game_over = True

        effective_hp = (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0)
        if effective_hp <= 0:
            death_log.append(
                CombatLogEntry(
                    round=round_number,
                    actor="player",
                    action="death",
                )
            )
            game_over = True
            break

    return on_hit_log, death_log, game_over


# ------------------------------------------------------------------
# NPC turn resolution
# ------------------------------------------------------------------

def _side_of(combat: CombatState, combatant_id: str) -> str:
    """Return the side of a combatant: ``"player"``, ``"party"``, or ``"enemy"``."""
    if combatant_id == "player":
        return "player"
    if combatant_id in combat.allies:
        return "party"
    return "enemy"


def _living_enemies(combat: CombatState, hard: HardGameState) -> list[str]:
    """Return living enemy combatants; combat ends in victory when empty.

    Combatants killed or fled earlier in the round are already removed
    from ``combat.combatants``; the HP check additionally filters enemies
    whose hard state says they are dead (belt-and-braces: combat HP is
    mutated live mid-round, but other systems may kill entities outside
    the combat module).
    """
    return [
        c
        for c in combat.combatants
        if _side_of(combat, c) == "enemy"
        and (hard.entity_states.get(c, {}).get("current_hp") or 0) > 0
    ]


def _same_side(a: str, b: str) -> bool:
    """True if two sides are the same: the player and party are one side."""
    return (a in ("player", "party")) == (b in ("player", "party"))


def _living_opponents(
    actor_id: str,
    combat: CombatState,
    hard: HardGameState,
) -> list[str]:
    """Return living combatants on the side opposing *actor_id*.

    Membership in ``combat.combatants`` (updated immediately on death) is
    the primary liveness filter, since hard entity state lags mid-turn;
    the player is always a valid opponent while in combatants.
    """
    actor_side = _side_of(combat, actor_id)
    opponents: list[str] = []
    for cid in combat.combatants:
        if cid == actor_id or _same_side(actor_side, _side_of(combat, cid)):
            continue
        if cid == "player":
            opponents.append(cid)
        elif (hard.entity_states.get(cid, {}).get("current_hp") or 0) > 0:
            opponents.append(cid)
    return opponents


def _choose_npc_target(
    actor_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> str | None:
    """Pick a target for an NPC combatant via rule-of-thumb combat AI.

    Returns None when no living opponent exists.  Targeting rules (from
    the NPC's ``combat.ai`` block):

    - ``player`` — enemies only: attack the player.
    - ``last_attacker`` — whoever landed the most recent hit on the
      actor, if still a living opponent (fallback: player for enemies,
      lowest-HP opponent for allies).
    - ``lowest_hp`` — the living opponent with the lowest current HP.
    - ``random`` — a random living opponent.

    Defaults without an ``ai`` block: enemies use the ``last_attacker``
    rule (in solo play this is always the player, preserving pre-AI
    behavior); allies attack the player's most recent living target, then
    their own last attacker, then the lowest-HP opponent.
    """
    entity = corpus.entities.get(actor_id)
    ai = entity.combat.ai if entity and entity.combat else None
    rule = ai.targeting if ai else None
    actor_side = _side_of(combat, actor_id)
    opponents = _living_opponents(actor_id, combat, hard)
    if not opponents:
        return None

    def _hp(cid: str) -> int:
        if cid == "player":
            return hard.player.current_hp or 0
        return hard.entity_states.get(cid, {}).get("current_hp") or 0

    def _lowest() -> str:
        return min(opponents, key=lambda c: (_hp(c), opponents.index(c)))

    if rule == "player" and actor_side == "enemy":
        return "player"
    if rule == "random":
        # randint (not random.choice) so tests that monkeypatch
        # random.randint steer targeting like every other roll.
        return opponents[random.randint(0, len(opponents) - 1)]
    if rule == "lowest_hp":
        return _lowest()
    if rule == "last_attacker":
        attacker = combat.last_attacker.get(actor_id)
        if attacker in opponents:
            return attacker
        return "player" if actor_side == "enemy" else _lowest()

    # Defaults (no ai block).
    if actor_side == "enemy":
        attacker = combat.last_attacker.get(actor_id)
        if attacker in opponents:
            return attacker
        return "player"
    # Ally default: the player's most recent living target, then own last
    # attacker, then the lowest-HP opponent.
    if combat.player_last_target in opponents:
        return combat.player_last_target
    attacker = combat.last_attacker.get(actor_id)
    if attacker in opponents:
        return attacker
    return _lowest()


def _target_ac(
    target_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> int | None:
    """Return the AC of a combatant (player or NPC); None if not attackable."""
    if target_id == "player":
        return compute_player_ac(hard, corpus)
    entity = corpus.entities.get(target_id)
    if entity is None or entity.combat is None:
        return None
    return entity.combat.ac


def _attack_sequence(entity: Any) -> list:
    """Return the ordered attack definitions for an NPC's turn.

    ``multiattack`` lists the attack ids performed each turn (repeats
    allowed); without it the NPC makes a single attack — the first entry
    of ``attacks``, or the implicit basic attack (``None``, built from
    block-level fields) when ``attacks`` is absent.
    """
    cb = entity.combat
    if not cb.attacks:
        return [None]  # basic attack from block-level fields
    if cb.multiattack:
        by_id = {a.id: a for a in cb.attacks}
        return [by_id[atk_id] for atk_id in cb.multiattack]
    return [cb.attacks[0]]


# ------------------------------------------------------------------
# Conditions
# ------------------------------------------------------------------

def _tick_status_effects(
    combatant_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> None:
    """Start-of-turn status-effect processing for one combatant.

    Behaviour is driven by each status effect's definition (see
    ``ModuleCorpus.effective_status_effects``): ``until_turn_start``
    status effects (e.g. prone) auto-clear; combat-scoped ``rounds``
    status effects tick down one round and expire at zero; persistent and
    ``until_cleared`` status effects are left alone.  Unknown IDs behave
    like the legacy defaults (combat-scoped, round-based).
    """
    status_effects = get_status_effects(combatant_id, hard)
    if not status_effects:
        return
    effect_defs = corpus.effective_status_effects()
    for effect_id in list(status_effects):
        cdef = effect_defs.get(effect_id)
        duration = cdef.duration if cdef is not None else "rounds"
        scope = cdef.scope if cdef is not None else "combat"
        if duration == "until_turn_start":
            remove_status_effect(
                combatant_id, effect_id, hard, corpus, "auto_clear", events
            )
        elif duration == "rounds" and scope == "combat":
            status_effects[effect_id] -= 1
            expired = status_effects[effect_id] <= 0
            if expired:
                remove_status_effect(
                    combatant_id, effect_id, hard, corpus, "expired", events
                )
            emit_status_effect_event(events, "status_effect.ticked", {
                "target_id": combatant_id,
                "status_effect_id": effect_id,
                "remaining_rounds": status_effects.get(effect_id, 0),
                "expired": expired,
            })


def _clear_status_effects(
    hard: HardGameState,
    corpus: ModuleCorpus,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> None:
    """Clear combat-scoped status effects at combat end (persistent survive)."""
    effect_defs = corpus.effective_status_effects()

    def _is_combat_scoped(effect_id: str) -> bool:
        cdef = effect_defs.get(effect_id)
        return cdef.scope == "combat" if cdef is not None else True

    for effect_id in [c for c in hard.player.status_effects if _is_combat_scoped(c)]:
        remove_status_effect("player", effect_id, hard, corpus, "combat_end", events)
    for entity_id, state in hard.entity_states.items():
        status_effects = state.get("status_effects") or {}
        for effect_id in [c for c in status_effects if _is_combat_scoped(c)]:
            remove_status_effect(
                entity_id, effect_id, hard, corpus, "combat_end", events
            )
        if not status_effects:
            state.pop("status_effects", None)


def _skips_turn(combatant_id: str, hard: HardGameState, corpus: ModuleCorpus) -> bool:
    """True if any of the combatant's status effects has ``skip_turn`` set."""
    effect_defs = corpus.effective_status_effects()
    return any(
        effect_defs[c].skip_turn
        for c in get_status_effects(combatant_id, hard)
        if c in effect_defs
    )


# ------------------------------------------------------------------
# Abilities
# ------------------------------------------------------------------

def _apply_damage_to_target(
    target_id: str,
    damage: int,
    hard: HardGameState,
    combat: CombatState,
    hard_changes: HardStateChanges,
) -> bool:
    """Apply damage to a combatant, handling death bookkeeping.

    Player HP goes through hard_changes as a delta (applied at end of
    turn); NPC HP is mutated directly and also recorded as absolute sets.
    Returns True when the target dropped to 0 HP or below.
    """
    if damage <= 0:
        return False
    if target_id == "player":
        hard_changes.player_hp_delta = (
            (hard_changes.player_hp_delta or 0) - damage
        )
        effective_hp = (hard.player.current_hp or 0) + (
            hard_changes.player_hp_delta or 0
        )
        return effective_hp <= 0
    new_hp = (
        hard.entity_states.get(target_id, {}).get("current_hp") or 0
    ) - damage
    tgt_state = hard.entity_states.setdefault(target_id, {})
    tgt_state["current_hp"] = new_hp
    tgt_changes = hard_changes.entity_state_changes.setdefault(target_id, {})
    tgt_changes["current_hp"] = new_hp
    if new_hp <= 0:
        tgt_state["alive"] = False
        tgt_changes["alive"] = False
        if target_id in combat.combatants:
            combat.combatants.remove(target_id)
        if target_id in combat.allies:
            combat.allies.remove(target_id)
        return True
    return False


def _apply_healing_to_target(
    target_id: str,
    amount: int,
    hard: HardGameState,
    corpus: ModuleCorpus,
    system: Any,
    hard_changes: HardStateChanges,
) -> int:
    """Apply healing clamped to the target's max HP; returns the actual
    amount healed."""
    if target_id == "player":
        effective_hp = (hard.player.current_hp or 0) + (
            hard_changes.player_hp_delta or 0
        )
        max_hp = system.compute_player_max_hp(hard, corpus)
        healed = max(0, min(amount, max_hp - effective_hp))
        if healed:
            hard_changes.player_hp_delta = (
                (hard_changes.player_hp_delta or 0) + healed
            )
        return healed
    entity = corpus.entities.get(target_id)
    max_hp = entity.combat.hp if entity and entity.combat else 0
    cur = hard.entity_states.get(target_id, {}).get("current_hp") or 0
    healed = max(0, min(amount, max_hp - cur))
    if healed:
        new_hp = cur + healed
        tgt_state = hard.entity_states.setdefault(target_id, {})
        tgt_state["current_hp"] = new_hp
        hard_changes.entity_state_changes.setdefault(target_id, {})[
            "current_hp"
        ] = new_hp
    return healed


def _target_current_hp(
    target_id: str,
    hard: HardGameState,
    hard_changes: HardStateChanges,
) -> int:
    """Current effective HP of a combatant (player HP includes the
    pending end-of-turn delta)."""
    if target_id == "player":
        return (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0)
    return hard.entity_states.get(target_id, {}).get("current_hp") or 0


def _most_injured(
    ids: list[str],
    hard: HardGameState,
    corpus: ModuleCorpus,
    system: Any,
    hard_changes: HardStateChanges,
) -> str | None:
    """Return the most-injured (lowest HP fraction) combatant among *ids*
    that is below max HP, or None when everyone is unhurt."""
    best: str | None = None
    best_frac = 1.0
    for cid in ids:
        if cid == "player":
            max_hp = system.compute_player_max_hp(hard, corpus)
        else:
            entity = corpus.entities.get(cid)
            max_hp = entity.combat.hp if entity and entity.combat else 0
        if max_hp <= 0:
            continue
        cur = _target_current_hp(cid, hard, hard_changes)
        frac = cur / max_hp
        if frac < best_frac:
            best, best_frac = cid, frac
    return best


def _resolve_heal_ability(
    caster_id: str,
    aid: str,
    ability: Any,
    target_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
) -> None:
    """Resolve a heal ability (clamped to the target's max HP)."""
    system = get_system_for_corpus(corpus)
    heal_total, heal_roll = system.roll_damage(ability.heal)
    healed = _apply_healing_to_target(
        target_id, heal_total, hard, corpus, system, hard_changes
    )
    combat_log.append(
        CombatLogEntry(
            round=combat.round_number,
            actor=caster_id,
            action="heal",
            target=target_id,
            attack_id=aid,
            attack_name=ability.name,
            damage=healed,
            damage_roll=heal_roll,
            remaining_hp=_target_current_hp(target_id, hard, hard_changes),
        )
    )


def _resolve_attack_ability(
    caster_id: str,
    aid: str,
    ability: Any,
    atk_bonus: int,
    target_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
) -> bool:
    """Resolve an attack ability (attack roll + damage, crits, mitigation).

    Returns True when the target died.
    """
    system = get_system_for_corpus(corpus)
    atk = ability.attack
    target_ac = _target_ac(target_id, hard, corpus)
    adv, disadv = system.attack_roll_mods(
        get_status_effects(caster_id, hard), get_status_effects(target_id, hard), corpus
    )
    attack_roll = system.roll_die(20, advantage=adv, disadvantage=disadv)
    attack_total = attack_roll + atk_bonus
    critical = system.is_critical(attack_roll)
    miss = system.is_fumble(attack_roll)
    hit = critical or (not miss and attack_total >= (target_ac or 0))

    log_entry = CombatLogEntry(
        round=combat.round_number,
        actor=caster_id,
        action="attack",
        target=target_id,
        attack_roll=attack_roll,
        attack_total=attack_total,
        ac=target_ac,
        hit=hit,
        critical=critical if hit else None,
        attack_id=aid,
        attack_name=ability.name,
    )
    combat_log.append(log_entry)
    if not hit:
        log_entry.remaining_hp = _target_current_hp(target_id, hard, hard_changes)
        return False

    damage, damage_roll = system.roll_damage(atk.damage, critical=critical)
    damage, mitigation = system.apply_damage_modifiers(
        damage, atk.damage_type, target_id, hard, corpus
    )
    log_entry.damage_roll = damage_roll
    log_entry.damage = damage
    log_entry.damage_type = atk.damage_type or None
    log_entry.mitigation = mitigation
    combat.last_attacker[target_id] = caster_id
    died = _apply_damage_to_target(target_id, damage, hard, combat, hard_changes)
    log_entry.remaining_hp = _target_current_hp(target_id, hard, hard_changes)
    if died:
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number, actor=target_id, action="death",
            )
        )
    return died


def _resolve_save_ability(
    caster_id: str,
    aid: str,
    ability: Any,
    target_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> bool:
    """Resolve a save ability: the target saves (player with proficiency
    rules, NPCs with their ``save_bonus``), taking half or no damage on
    success and possibly a status effect on failure.  Returns True when the
    target died."""
    system = get_system_for_corpus(corpus)
    save = ability.save
    if target_id == "player":
        stat_value = (
            hard.player.stats.get(save.stat, 10) if hard.player.stats else 10
        )
        flat = system.compute_save_modifier(save.stat, hard.player)
        check = system.roll_check(
            save.stat, stat_value, save.dc, flat_modifier=flat
        )
        save_success = check.success
        save_roll, save_total = check.raw_roll, check.total
    else:
        tgt_entity = corpus.entities.get(target_id)
        save_bonus = (
            tgt_entity.combat.save_bonus
            if tgt_entity and tgt_entity.combat
            else 0
        )
        save_roll = system.roll_die(20)
        save_total = save_roll + save_bonus
        save_success = save_total >= save.dc

    damage = 0
    damage_roll: str | None = None
    mitigation: str | None = None
    if save.damage:
        damage, damage_roll = system.roll_damage(save.damage)
        if save_success:
            damage = damage // 2 if save.half_on_success else 0
        damage, mitigation = system.apply_damage_modifiers(
            damage, save.damage_type, target_id, hard, corpus
        )

    applied_effect: str | None = None
    if not save_success and save.apply_status_effect_on_failure is not None:
        effect = save.apply_status_effect_on_failure
        apply_status_effect(
            target_id, effect.id, effect.rounds, hard, corpus, "save_failure", events
        )
        applied_effect = effect.id

    died = False
    if damage:
        died = _apply_damage_to_target(
            target_id, damage, hard, combat, hard_changes
        )

    save_dict: dict[str, Any] = {
        "save_stat": save.stat,
        "save_dc": save.dc,
        "save_roll": save_roll,
        "save_total": save_total,
        "save_success": save_success,
        "damage_expr": save.damage or None,
        "damage": damage,
        "damage_type": save.damage_type or None,
    }
    if applied_effect:
        save_dict["status_effect"] = applied_effect
    combat_log.append(
        CombatLogEntry(
            round=combat.round_number,
            actor=caster_id,
            action="ability_save",
            target=target_id,
            attack_id=aid,
            attack_name=ability.name,
            damage=damage,
            damage_roll=damage_roll,
            mitigation=mitigation,
            remaining_hp=_target_current_hp(target_id, hard, hard_changes),
            on_hit_effects=[save_dict],
        )
    )
    if died:
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number, actor=target_id, action="death",
            )
        )
    return died


def _choose_npc_ability(
    actor_id: str,
    entity: Any,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
) -> tuple[str, Any, str] | None:
    """Pick an ability for an NPC to use this turn: the first entry of
    its ``combat.abilities`` list that is usable (uses remaining,
    cooldown expired, AI HP condition met) and has a valid target.

    Returns ``(ability_id, ability, target_id)`` or None.  Heal abilities
    pick the most-injured living same-side combatant and are skipped
    when nobody is hurt.
    """
    cb = entity.combat
    if not cb.abilities:
        return None
    system = get_system_for_corpus(corpus)
    actor_side = _side_of(combat, actor_id)
    used_map = combat.ability_uses.setdefault(actor_id, {})
    cd_map = combat.npc_cooldowns.setdefault(actor_id, {})
    rules = cb.ai.ability_rules if cb.ai else {}

    for aid in cb.abilities:
        ability = corpus.abilities.get(aid)
        if ability is None:
            continue
        if (
            ability.uses_per_combat >= 0
            and used_map.get(aid, 0) >= ability.uses_per_combat
        ):
            continue
        if cd_map.get(aid, 0) > 0:
            continue
        rule = rules.get(aid)
        if rule is not None and rule.use_below_own_hp_pct is not None:
            hp = hard.entity_states.get(actor_id, {}).get("current_hp") or 0
            if 100 * hp >= rule.use_below_own_hp_pct * cb.hp:
                continue

        if ability.target == "self":
            if ability.heal:
                cur = hard.entity_states.get(actor_id, {}).get("current_hp") or 0
                if cur >= cb.hp:
                    continue
            target_id = actor_id
        elif ability.target == "ally":
            if not ability.heal:
                continue  # only ally healing is supported this phase
            friends = [
                c
                for c in combat.combatants
                if c != actor_id and _same_side(actor_side, _side_of(combat, c))
            ]
            target_id = _most_injured(friends, hard, corpus, system, hard_changes)
            if target_id is None:
                continue
        else:  # enemy
            target_id = _choose_npc_target(actor_id, combat, hard, corpus)
            if target_id is None:
                continue
        return aid, ability, target_id
    return None


def _use_npc_ability(
    actor_id: str,
    entity: Any,
    aid: str,
    ability: Any,
    target_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> bool:
    """Resolve an NPC's chosen ability; returns True when the player died."""
    combat.ability_uses[actor_id][aid] = (
        combat.ability_uses[actor_id].get(aid, 0) + 1
    )
    rule = entity.combat.ai.ability_rules.get(aid) if entity.combat.ai else None
    if rule is not None and rule.cooldown_rounds:
        # +1 because cooldowns tick at the end of the cast round too:
        # cooldown_rounds N = unusable for the N rounds after this one.
        combat.npc_cooldowns[actor_id][aid] = rule.cooldown_rounds + 1

    if ability.heal:
        _resolve_heal_ability(
            actor_id, aid, ability, target_id,
            combat, hard, corpus, hard_changes, combat_log,
        )
        return False
    if ability.attack is not None:
        died = _resolve_attack_ability(
            actor_id, aid, ability, entity.combat.atk or 0, target_id,
            combat, hard, corpus, hard_changes, combat_log,
        )
        return died and target_id == "player"
    if ability.save is not None:
        died = _resolve_save_ability(
            actor_id, aid, ability, target_id,
            combat, hard, corpus, hard_changes, combat_log, events,
        )
        return died and target_id == "player"
    return False


def _resolve_player_ability(
    action: CombatAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
    combat: CombatState,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Resolve the player's ``use_ability`` combat action.

    Returns an error dict on failure, None on success (uses are consumed
    even on a missed attack roll, by tabletop convention).
    """
    system = get_system_for_corpus(corpus)
    aid = action.ability_id
    if not aid:
        return {"success": False, "error": "use_ability requires 'ability_id'"}
    ability = corpus.abilities.get(aid)
    if ability is None:
        return {"success": False, "error": f"Unknown ability '{aid}'"}
    if aid not in hard.player.abilities:
        return {"success": False, "error": f"You do not know ability '{aid}'"}
    used_map = combat.ability_uses.setdefault("player", {})
    if (
        ability.uses_per_combat >= 0
        and used_map.get(aid, 0) >= ability.uses_per_combat
    ):
        return {
            "success": False,
            "error": f"'{ability.name}' has no uses left this combat",
        }

    target_id = action.target
    if ability.target == "self":
        if target_id != "player":
            return {
                "success": False,
                "error": f"'{ability.name}' can only target yourself",
            }
    elif ability.target == "ally":
        if target_id not in combat.combatants or _side_of(combat, target_id) == "enemy":
            return {
                "success": False,
                "error": f"'{ability.name}' must target a party member",
            }
    else:  # enemy
        if target_id not in combat.combatants:
            return {"success": False, "error": f"Target '{target_id}' not in combat"}
        if _side_of(combat, target_id) != "enemy":
            return {
                "success": False,
                "error": f"'{ability.name}' must target an enemy",
            }
        if (hard.entity_states.get(target_id, {}).get("current_hp") or 0) <= 0:
            return {
                "success": False,
                "error": f"Target '{target_id}' is already dead",
            }

    used_map[aid] = used_map.get(aid, 0) + 1
    if ability.target == "enemy":
        combat.player_last_target = target_id

    if ability.heal:
        _resolve_heal_ability(
            "player", aid, ability, target_id,
            combat, hard, corpus, hard_changes, combat_log,
        )
        return None

    if ability.attack is not None:
        stat_value = (
            hard.player.stats.get(ability.attack.stat, 10)
            if hard.player.stats
            else 10
        )
        atk_bonus = system.compute_modifier(stat_value)
        if ability.attack.proficient:
            atk_bonus += getattr(hard.player, "proficiency_bonus", None) or 2
        _resolve_attack_ability(
            "player", aid, ability, atk_bonus, target_id,
            combat, hard, corpus, hard_changes, combat_log,
        )
        return None

    if ability.save is not None:
        _resolve_save_ability(
            "player", aid, ability, target_id,
            combat, hard, corpus, hard_changes, combat_log, events,
        )
        return None

    return {"success": False, "error": f"Ability '{aid}' has no effect"}


def _resolve_npc_turn(
    actor_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState | None,
    state_manager: Any | None,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[bool, bool]:
    """Resolve one NPC combatant's turn (attack plus on-hit effects).

    HP deltas and death bookkeeping are accumulated into *hard_changes*
    (player HP as a delta, NPC HP as absolute sets) and *combat*; log
    entries are appended to *combat_log*.  End-of-combat status effects are
    checked after the action.  Returns ``(game_over, combat_ended)`` —
    game_over when the player dropped to 0 HP or an inline (scripted)
    game-over occurred, combat_ended when no living enemies remain.
    """
    entity = corpus.entities.get(actor_id)
    if entity is None or entity.combat is None:
        return False, False
    if actor_id not in combat.combatants:
        # Killed or fled earlier this round: departed combatants are
        # removed from combatants immediately (entity state is also
        # mutated live, so the HP check below is a second line of defense).
        return False, False
    npc_state = hard.entity_states.get(actor_id, {})
    if (npc_state.get("current_hp") or 0) <= 0:
        return False, False

    # Start-of-turn status-effect processing; combatants with a skip_turn
    # status effect (e.g. stunned) lose the turn.
    _tick_status_effects(actor_id, hard, corpus, events)
    if _skips_turn(actor_id, hard, corpus):
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number, actor=actor_id, action="stunned",
            )
        )
        return False, False

    ai = entity.combat.ai
    passive = ai.passive if ai is not None else False
    if npc_state.get("passive") is not None:
        # A declared ``passive`` entity state overrides the corpus AI
        # default at runtime (e.g. an ally persuaded to fight).
        passive = bool(npc_state["passive"])
    if passive:
        # Passive NPCs (cowering civilians, bystanders) take no actions.
        return False, False

    # NPC flee: enemies with a flee threshold abandon combat when badly
    # hurt.  Allies never flee — they withdraw with the player.
    if (
        _side_of(combat, actor_id) == "enemy"
        and ai is not None
        and ai.flee_below_hp_pct is not None
    ):
        hp = npc_state.get("current_hp") or 0
        if 100 * hp < ai.flee_below_hp_pct * entity.combat.hp:
            combat.combatants.remove(actor_id)
            # ``fled`` is engine-owned runtime state, set by direct
            # mutation (same as current_hp initialisation in enter_combat).
            hard.entity_states.setdefault(actor_id, {})["fled"] = True
            combat_log.append(
                CombatLogEntry(
                    round=combat.round_number, actor=actor_id, action="flee",
                )
            )
            return False, not _living_enemies(combat, hard)

    # Abilities take precedence over basic attacks: the NPC's first
    # usable ability (uses, cooldown, AI rules) wins.
    chosen = _choose_npc_ability(
        actor_id, entity, combat, hard, corpus, hard_changes
    )
    if chosen is not None:
        aid, ability, ability_target = chosen
        game_over = _use_npc_ability(
            actor_id, entity, aid, ability, ability_target,
            combat, hard, corpus, hard_changes, combat_log, events,
        )
        return game_over, not _living_enemies(combat, hard)

    system = get_system_for_corpus(corpus)
    target_id = _choose_npc_target(actor_id, combat, hard, corpus)
    if target_id is None:
        # No living opponents: for an ally this means victory.
        return False, not _living_enemies(combat, hard)
    target_ac = _target_ac(target_id, hard, corpus)
    if target_ac is None:
        return False, False

    game_over = False
    for attack_def in _attack_sequence(entity):
        npc_result = system.resolve_npc_attack(
            actor_id, hard, corpus, target_id, target_ac,
            combat.round_number, attack=attack_def,
            player_hp_pending=hard_changes.player_hp_delta or 0,
        )
        combat_log.extend(npc_result.log_entries)
        turn_entries = list(npc_result.log_entries)

        if npc_result.hit:
            combat.last_attacker[target_id] = actor_id

        if npc_result.target_hp_delta:
            if target_id == "player":
                hard_changes.player_hp_delta = (
                    (hard_changes.player_hp_delta or 0) + npc_result.target_hp_delta
                )
            else:
                new_hp = (
                    hard.entity_states.get(target_id, {}).get("current_hp") or 0
                ) + npc_result.target_hp_delta
                # Mutate hard entity state directly so subsequent attackers in
                # the same round see fresh HP.  The same absolute values are
                # recorded in hard_changes, and absolute sets are idempotent
                # when the state manager applies them at end of turn.
                tgt_state = hard.entity_states.setdefault(target_id, {})
                tgt_state["current_hp"] = new_hp
                tgt_changes = hard_changes.entity_state_changes.setdefault(
                    target_id, {}
                )
                tgt_changes["current_hp"] = new_hp
                if new_hp <= 0:
                    tgt_state["alive"] = False
                    tgt_changes["alive"] = False
                    if target_id in combat.combatants:
                        combat.combatants.remove(target_id)
                    if target_id in combat.allies:
                        combat.allies.remove(target_id)

        # On-hit effects resolve only against the player (they reference
        # player stats and saves); they no-op internally if the player is
        # already dead.  Effects come from the attack definition (basic
        # attack: block-level on_hit_effects).
        if npc_result.hit and target_id == "player" and soft is not None:
            attack_entry = next(
                (entry for entry in npc_result.log_entries if entry.action == "attack"),
                None,
            )
            on_hit_narrative: list[str] = []
            on_hit_hints: list[str] = []
            on_hit_rolls: list[dict[str, Any]] = []
            on_hit_entries, death_entries, on_hit_game_over = _resolve_npc_on_hits(
                actor_id, hard, soft, corpus, state_manager,
                hard_changes, on_hit_narrative, on_hit_hints, on_hit_rolls,
                round_number=combat.round_number,
                on_hit_effects=(
                    attack_def.on_hit_effects if attack_def is not None
                    else entity.combat.on_hit_effects
                ),
                events=events,
            )
            if attack_entry is not None:
                attack_entry.on_hit_effects.extend(on_hit_entries)
            combat_log.extend(death_entries)
            turn_entries.extend(death_entries)
            if on_hit_game_over:
                # Either an inline Result.game_over (save-or-die) or death by
                # on-hit damage.
                game_over = True

        # Authoritative end-condition check after the action.  hard.player is
        # not mutated mid-turn, so effective player HP combines the base value
        # with the accumulated delta; this catches the player dropping to 0 HP
        # from damage accumulated across several attackers, which no single
        # attack roll detects on its own.
        if target_id == "player":
            effective_hp = (hard.player.current_hp or 0) + (
                hard_changes.player_hp_delta or 0
            )
            if effective_hp <= 0:
                game_over = True
                if not any(
                    e.action == "death" and e.actor == "player" for e in turn_entries
                ):
                    combat_log.append(
                        CombatLogEntry(
                            round=combat.round_number,
                            actor="player",
                            action="death",
                        )
                    )

        # Remaining attacks in the sequence are lost once the target drops.
        if game_over or npc_result.target_died:
            break

    return game_over, not _living_enemies(combat, hard)


# ------------------------------------------------------------------
# Combat entry
# ------------------------------------------------------------------

def resolve_combat_enemies(
    seed_ids: list[str],
    explicit: list[str] | None,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[str]:
    """Resolve the set of enemies to enter combat with.

    Combines *seed_ids* (the encounter source or directly-attacked target)
    with an optional explicit *start_combat* list, then expands every
    ``combat_group`` referenced by those ids.  The result is deduplicated,
    filtered to present/living/stat-blocked entities, and returned in order.

    Followers (NPCs with dialogue whose hard state says ``following``) are
    treated as allies: they are never pulled in via group expansion, though
    a follower may still become a combatant if it is itself a seed (i.e. the
    player attacked it directly).
    """
    room_id = hard.player.location
    room_present = set(hard.room_contains.get(room_id, {}))
    follower_ids = set(get_following_npc_ids(hard, corpus))
    seed_set = set(seed_ids) | set(explicit or [])

    # 1. Expand combat_group membership for every seed/explicit id.
    #    Followers are allies: they are never pulled in via group
    #    expansion. A follower can only become a combatant by being a
    #    seed itself (i.e. the player attacked it directly).
    expanded: list[str] = []
    seen_groups: set[str] = set()
    for cid in list(seed_ids) + list(explicit or []):
        ent = corpus.entities.get(cid)
        grp = ent.combat_group if ent else None
        if grp and grp not in seen_groups:
            seen_groups.add(grp)
            for eid, e in corpus.entities.items():
                if e.combat_group == grp and (eid == cid or eid not in follower_ids):
                    expanded.append(eid)
        else:
            expanded.append(cid)

    # 2. Dedup (preserve order), then filter to eligible enemies.
    out: list[str] = []
    for cid in dict.fromkeys(expanded):
        ent = corpus.entities.get(cid)
        if ent is None or ent.combat is None:
            # Unknown ids and non-stat-blocked entities cannot be combatants.
            continue
        # Presence: a seed is eligible if it is in the room or a follower
        # (you may attack a follower). Group-expanded members must be in
        # the current room; followers are excluded by the expansion step.
        if cid in seed_set:
            if cid not in room_present and cid not in follower_ids:
                continue
        else:
            if cid not in room_present:
                continue
        st = hard.entity_states.get(cid, {})
        if st.get("alive") is False:
            continue
        out.append(cid)
    return out


def resolve_combat_allies(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[str]:
    """Return follower NPCs that join combat on the player's side.

    Every alive follower (``following == True``, see
    ``get_following_npc_ids``) that carries a combat block fights as an
    ally; followers without combat blocks stay non-combatant bystanders.
    """
    allies: list[str] = []
    for eid in get_following_npc_ids(hard, corpus):
        entity = corpus.entities.get(eid)
        if entity is not None and entity.combat is not None:
            allies.append(eid)
    return allies


def enter_combat(
    enemy_ids: list[str],
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState | None = None,
    state_manager: Any | None = None,
) -> dict[str, Any]:
    """Initialize combat state, roll initiative, resolve pre-player NPC turns.

    Returns a dict with ``combat_log``, ``hard_changes``, ``combat_triggered``,
    ``player_died``, ``combat_ended_reason``, and ``events``.  ``player_died``
    is True
    when the player dropped to 0 HP without an inline (scripted) game-over;
    the engine routes that through the ``player.died`` event, which lets
    rescue reactions avert the death.  ``combat_ended_reason`` is ``None``
    when combat continues, or one of ``"victory"`` / ``"defeat"`` when
    pre-player NPC turns already ended combat (the caller should emit a
    ``combat.ended`` event in that case).  ``events`` carries the status-effect
    events (``status_effect.applied`` / ``status_effect.ticked`` /
    ``status_effect.cleared``) raised during pre-player NPC turns, for the
    caller to dispatch.
    """
    system = get_system_for_corpus(corpus)

    # Followers with combat blocks join the player's side automatically —
    # unless one of them is itself an enemy (the player attacked it).
    ally_ids = [a for a in resolve_combat_allies(hard, corpus) if a not in enemy_ids]

    # Initialize player HP if absent
    if hard.player.current_hp is None:
        hard.player.current_hp = system.compute_player_max_hp(hard, corpus)
        hard.player.max_hp = hard.player.max_hp or hard.player.current_hp

    # Initialize NPC current_hp from combat block
    for eid in list(ally_ids) + list(enemy_ids):
        entity = corpus.entities.get(eid)
        if entity is None or entity.combat is None:
            continue
        state = hard.entity_states.setdefault(eid, {})
        if state.get("current_hp") is None:
            state["current_hp"] = entity.combat.hp

    # Roll initiative once
    initiative_order = roll_initiative(hard, corpus, list(ally_ids) + list(enemy_ids))

    # Create combat state
    combat = CombatState(
        active=True,
        combatants=["player"] + list(ally_ids) + list(enemy_ids),
        allies=list(ally_ids),
        initiative_order=initiative_order,
        current_index=0,
        round_number=1,
        log=[],
    )
    hard.combat = combat

    # Resolve NPC turns before the player's first turn
    hard_changes = HardStateChanges()
    combat_log: list[CombatLogEntry] = []
    events: list[tuple[str, dict[str, Any]]] = []
    combat_ended_reason: str | None = None

    player_idx = initiative_order.index("player")
    for i in range(player_idx):
        actor_id = initiative_order[i]
        if actor_id == "player":
            continue
        go, ended = _resolve_npc_turn(
            actor_id, combat, hard, corpus, soft, state_manager,
            hard_changes, combat_log, events,
        )
        if go:
            combat_ended_reason = "defeat"
            # Combat ends the moment the player drops; if a rescue
            # reaction (player.died) later averts the death, the player
            # survives out of combat.
            _clear_status_effects(hard, corpus, events)
            hard.combat = None
            break
        if ended:
            # No living enemies remain (only reachable once allies can
            # fight, Phase 2); combat is over before the player's turn.
            combat_ended_reason = "victory"
            _clear_status_effects(hard, corpus, events)
            hard.combat = None
            break

    if hard.combat is not None:
        combat.current_index = player_idx
        combat.log.extend(combat_log)

    # HP-based death is reported separately from an inline (scripted)
    # game-over: the engine routes it through the ``player.died`` event,
    # which lets rescue reactions avert the death.
    player_died = hard.game_over is None and (
        (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0) <= 0
    )

    return {
        "combat_log": combat_log,
        "hard_changes": hard_changes,
        "combat_triggered": True,
        "player_died": player_died,
        "combat_ended_reason": combat_ended_reason,
        "events": events,
    }


# ------------------------------------------------------------------
# Combat turn resolution
# ------------------------------------------------------------------

def _resolve_use_item(
    item_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
    system: Any,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
    round_number: int,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Resolve a ``use_item`` combat action (drink a potion, …).

    Uses the player's action: healing is clamped to max HP, one count of
    the item is consumed (when the block says so), and NPC turns proceed
    normally.  Returns an error dict on failure, None on success.
    """
    if item_id not in hard.player.inventory:
        usable: list[str] = []
        for inv_id, count in hard.player.inventory.items():
            if count <= 0:
                continue
            inv_entity = corpus.entities.get(inv_id)
            if inv_entity is not None and inv_entity.consumable is not None:
                usable.append(f"{inv_id} x{count} ({inv_entity.name or inv_id})")
        if usable:
            suffix = ". Usable items in inventory: " + ", ".join(usable) + "."
        else:
            suffix = ". No usable items in inventory."
        return {
            "success": False,
            "error": f"Item '{item_id}' not in inventory{suffix}",
        }
    entity = corpus.entities.get(item_id)
    if entity is None or entity.consumable is None:
        return {"success": False, "error": f"Item '{item_id}' is not usable"}
    block = entity.consumable

    healed = 0
    heal_roll: str | None = None
    if block.heal:
        heal_total, heal_roll = system.roll_damage(block.heal)
        effective_hp = (hard.player.current_hp or 0) + (
            hard_changes.player_hp_delta or 0
        )
        max_hp = system.compute_player_max_hp(hard, corpus)
        healed = max(0, min(heal_total, max_hp - effective_hp))
        if healed:
            hard_changes.player_hp_delta = (
                (hard_changes.player_hp_delta or 0) + healed
            )

    for effect_id in block.cure_status_effects:
        remove_status_effect("player", effect_id, hard, corpus, "consumable", events)

    if block.destroy:
        hard_changes.inventory_removed[item_id] = (
            hard_changes.inventory_removed.get(item_id, 0) + 1
        )
        hard_changes.inventory_removed_reasons[item_id] = "consumed"

    combat_log.append(
        CombatLogEntry(
            round=round_number,
            actor="player",
            action="use_item",
            target=item_id,
            damage=healed,  # healing amount (positive), shown by the prefix
            damage_roll=heal_roll,
            remaining_hp=(hard.player.current_hp or 0)
            + (hard_changes.player_hp_delta or 0),
        )
    )
    return None


def resolve_combat_turn(
    action: CombatAction | MoveAction | WaitAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState | None = None,
    state_manager: Any | None = None,
) -> dict[str, Any]:
    """Resolve the player's combat action and any following NPC turns.

    The player's action is an attack/item/ability (``CombatAction``), a
    flee attempt (``MoveAction``), or a turn pass (``WaitAction``).

    Returns a dict with ``success``, ``hard_changes``, ``combat_log``,
    ``player_died``, ``combat_ended_reason``, ``events``, and ``error``
    (if failure).
    ``player_died`` is True when the player dropped to 0 HP without an
    inline (scripted) game-over; the engine routes that through the
    ``player.died`` event, which lets rescue reactions avert the death.
    ``combat_ended_reason`` is ``None`` when combat continues, or one of
    ``"victory"``, ``"defeat"``, or ``"fled"`` when combat ended this turn;
    the caller should emit a ``combat.ended`` event in that case.
    ``events`` carries the status-effect events (``status_effect.applied`` /
    ``status_effect.ticked`` / ``status_effect.cleared``) raised during the turn,
    for the caller to dispatch.
    """
    combat = hard.combat
    if combat is None or not combat.active:
        return {"success": False, "error": "Not in combat"}

    system = get_system_for_corpus(corpus)

    hard_changes = HardStateChanges()
    combat_log: list[CombatLogEntry] = []
    events: list[tuple[str, dict[str, Any]]] = []
    game_over = False
    combat_ended = False
    combat_end_reason: str | None = None

    # Start-of-turn status-effect processing for the player; a player with a
    # skip_turn status effect (e.g. stunned) loses the action but the turn
    # (and NPC turns) still proceeds.
    _tick_status_effects("player", hard, corpus, events)
    if _skips_turn("player", hard, corpus):
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number, actor="player", action="stunned",
            )
        )
    elif isinstance(action, CombatAction) and action.combat_action == "use_ability":
        # --- Use a combat ability ---
        err = _resolve_player_ability(
            action, hard, corpus, hard_changes, combat_log, combat, events,
        )
        if err is not None:
            return err
        if not _living_enemies(combat, hard):
            combat_ended = True
            combat_end_reason = "victory"
    elif isinstance(action, CombatAction) and action.combat_action == "use_item":
        # --- Use a consumable item ---
        err = _resolve_use_item(
            action.target, hard, corpus, system,
            hard_changes, combat_log, combat.round_number, events,
        )
        if err is not None:
            return err
    elif isinstance(action, CombatAction):
        # --- Player attack ---
        target_id = action.target
        if target_id not in combat.combatants:
            return {"success": False, "error": f"Target '{target_id}' not in combat"}

        if _side_of(combat, target_id) != "enemy":
            return {
                "success": False,
                "error": f"Cannot attack '{target_id}': not an enemy combatant",
            }

        entity = corpus.entities.get(target_id)
        if entity is None or entity.combat is None:
            return {"success": False, "error": f"Invalid combat target '{target_id}'"}

        npc_state = hard.entity_states.get(target_id, {})
        if (npc_state.get("current_hp") or 0) <= 0:
            return {"success": False, "error": f"Target '{target_id}' is already dead"}

        combat.player_last_target = target_id
        target_ac = entity.combat.ac
        pa_result = system.resolve_player_attack(hard, corpus, target_id, target_ac, combat.round_number)
        combat_log.extend(pa_result.log_entries)

        if pa_result.hit:
            combat.last_attacker[target_id] = "player"
            new_hp = (npc_state.get("current_hp") or 0) + pa_result.target_hp_delta
            # Mutate hard entity state directly (fresh mid-turn reads for
            # allies attacking the same target); the same absolute values
            # are recorded in hard_changes, which the state manager applies
            # idempotently at end of turn.
            tgt_state = hard.entity_states.setdefault(target_id, {})
            tgt_state["current_hp"] = new_hp
            hard_changes.entity_state_changes.setdefault(target_id, {})[
                "current_hp"
            ] = new_hp

            if new_hp <= 0:
                tgt_state["alive"] = False
                hard_changes.entity_state_changes.setdefault(target_id, {})[
                    "alive"
                ] = False
                # Remove from combatants — note: also handled by engine
                # via entity_state_changes, but we track it locally too
                if target_id in combat.combatants:
                    combat.combatants.remove(target_id)

        # Check if all enemies are dead
        if not _living_enemies(combat, hard):
            combat_ended = True
            combat_end_reason = "victory"

    elif isinstance(action, MoveAction):
        # --- Flee attempt ---
        flee_dc = max(
            (
                corpus.entities.get(c).combat.flee_dc
                for c in combat.combatants
                if _side_of(combat, c) == "enemy"
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
            combat_end_reason = "fled"
            # Move the player to the target room
            room = corpus.rooms.get(hard.player.location)
            if room:
                for ex in room.exits:
                    if ex.id == action.target:
                        hard_changes.player_location = ex.target_room
                        break
        # On failure: turn is consumed, combat continues
    elif isinstance(action, WaitAction):
        # --- Pass the turn ---
        # The player forgoes their combat action; NPC turns and the round
        # advance proceed below.  The action's detail still drives the
        # narration, and soft-state patches apply as usual (engine-level).
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number, actor="player", action="wait",
            )
        )
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
                go, ended = _resolve_npc_turn(
                    actor_id, combat, hard, corpus, soft, state_manager,
                    hard_changes, combat_log, events,
                )
                if go:
                    game_over = True
                    combat_end_reason = "defeat"
                    break
                if ended:
                    combat_ended = True
                    combat_end_reason = "victory"
                    break
            idx = (idx + 1) % n

        # Advance to next round
        combat.round_number += 1
        combat.current_index = player_idx
        # NPC ability cooldowns tick at round end.
        for cds in combat.npc_cooldowns.values():
            for aid in list(cds):
                cds[aid] = max(0, cds[aid] - 1)

    combat.log.extend(combat_log)

    if combat_ended:
        _clear_status_effects(hard, corpus, events)
        hard.combat = None
    elif game_over:
        _clear_status_effects(hard, corpus, events)
        hard.combat = None

    # HP-based death is reported separately from an inline (scripted)
    # game-over: the engine routes it through the ``player.died`` event,
    # which lets rescue reactions avert the death.
    player_died = hard.game_over is None and (
        (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0) <= 0
    )

    return {
        "success": True,
        "hard_changes": hard_changes,
        "combat_log": combat_log,
        "player_died": player_died,
        "combat_ended_reason": combat_end_reason,
        "events": events,
    }
