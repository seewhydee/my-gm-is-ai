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
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.utils import get_following_npc_ids
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
) -> tuple[list[dict[str, Any]], list[CombatLogEntry], bool]:
    """Resolve an NPC's on-hit ``CheckResolution`` effects.

    Effects are resolved independently and damage accumulates in
    *hard_changes.player_hp_delta*. Returns ``(on_hit_log_entries,
    death_log_entries, game_over)``.
    """
    from mgmai.engine.resolver import _resolve_checkable

    entity = corpus.entities.get(npc_id)
    if entity is None or entity.combat is None:
        return [], [], False

    on_hit_log: list[dict[str, Any]] = []
    death_log: list[CombatLogEntry] = []
    game_over = False

    for effect in entity.combat.on_hit_effects:
        # Stop if the player is already dead from the base attack or a
        # previous on-hit effect.
        effective_hp = (hard.player.current_hp or 0) + (hard_changes.player_hp_delta or 0)
        if effective_hp <= 0 or game_over or hard.game_over is not None:
            break

        hp_before = hard_changes.player_hp_delta or 0
        rolls_before = len(rolls)

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
            resolution=None,
            source_id=npc_id,
            source_type="combat",
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


def _resolve_npc_turn(
    actor_id: str,
    combat: CombatState,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState | None,
    state_manager: Any | None,
    hard_changes: HardStateChanges,
    combat_log: list[CombatLogEntry],
) -> tuple[bool, bool]:
    """Resolve one NPC combatant's turn (attack plus on-hit effects).

    HP deltas and death bookkeeping are accumulated into *hard_changes*
    (player HP as a delta, NPC HP as absolute sets) and *combat*; log
    entries are appended to *combat_log*.  End-of-combat conditions are
    checked after the action.  Returns ``(game_over, combat_ended)`` —
    game_over when the player died, combat_ended when no living enemies
    remain.
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

    system = get_system_for_corpus(corpus)
    target_id = _choose_npc_target(actor_id, combat, hard, corpus)
    if target_id is None:
        # No living opponents: for an ally this means victory.
        return False, not _living_enemies(combat, hard)
    target_ac = _target_ac(target_id, hard, corpus)
    if target_ac is None:
        return False, False

    npc_result = system.resolve_npc_attack(
        actor_id, hard, corpus, target_id, target_ac, combat.round_number,
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
    # already dead.
    game_over = False
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
    and ``game_over``.
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
    game_over = False

    player_idx = initiative_order.index("player")
    for i in range(player_idx):
        actor_id = initiative_order[i]
        if actor_id == "player":
            continue
        go, ended = _resolve_npc_turn(
            actor_id, combat, hard, corpus, soft, state_manager,
            hard_changes, combat_log,
        )
        if go:
            game_over = True
            break
        if ended:
            # No living enemies remain (only reachable once allies can
            # fight, Phase 2); combat is over before the player's turn.
            hard.combat = None
            break

    if hard.combat is not None:
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
    soft: SoftGameState | None = None,
    state_manager: Any | None = None,
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
                go, ended = _resolve_npc_turn(
                    actor_id, combat, hard, corpus, soft, state_manager,
                    hard_changes, combat_log,
                )
                if go:
                    game_over = True
                    break
                if ended:
                    combat_ended = True
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
