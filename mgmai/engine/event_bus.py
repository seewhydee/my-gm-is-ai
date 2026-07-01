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

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

from mgmai.models.corpus import (
    ModuleCorpus,
    Reaction,
    ReactionEffects,
)
from mgmai.models.hard_state import HardGameState, GameOverState
from mgmai.models.soft_state import SoftGameState
from mgmai.models.actions import HardStateChanges
from mgmai.models.combat import CombatLogEntry
from mgmai.engine.conditions import evaluate

MAX_RECURSION_DEPTH = 5

_disabled_once: set[str] = set()


def reset_disabled_once() -> None:
    """Reset the in-memory once-reaction disabled set (called on reload)."""
    _disabled_once.clear()


# ------------------------------------------------------------------
# Reaction discovery
# ------------------------------------------------------------------


def find_matching_reactions(
    event_type: str,
    context: dict[str, Any],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> list[tuple[Reaction, str | None]]:
    """Find all reactions whose ``on`` matches *event_type* and whose
    condition (if any) holds given *context* as ``event_ctx``.

    Returns a list of ``(reaction, owner_id)`` tuples sorted by:
    1. ``priority`` ascending (lower = fires earlier)
    2. scope: entity → room → mechanic
    3. definition order (list index) within same scope

    *owner_id* is the ID of the entity that owns an entity-scoped reaction,
    or ``None`` for room-scoped and mechanic-scoped reactions.
    """
    from mgmai.engine.utils import get_following_npc_ids

    room_id = hard.player.location
    room = corpus.rooms.get(room_id)

    tagged: list[tuple[Reaction, str | None, int, int]] = []
    # tagged = [(reaction, owner_id, scope_rank, defn_index), ...]
    # scope_rank: 0=entity, 1=room, 2=mechanic

    # --- Entity-scoped reactions ---
    if room is not None:
        entity_ids: set[str] = set(room.contains)
        for eid in get_following_npc_ids(hard, corpus):
            entity_ids.add(eid)

        for eid in sorted(entity_ids):
            entity = corpus.entities.get(eid)
            if entity is None:
                continue
            entity_state = hard.entity_states.get(eid, {})
            # Active only when alive and not fled
            if entity_state.get("alive") is False:
                continue
            if entity_state.get("fled") is True:
                continue
            for idx, reaction in enumerate(entity.reactions):
                if _reaction_matches(reaction, event_type, context,
                                     hard, soft, corpus):
                    tagged.append((reaction, eid, 0, idx))

    # --- Room-scoped reactions ---
    if room is not None:
        for idx, reaction in enumerate(room.reactions):
            if _reaction_matches(reaction, event_type, context,
                                 hard, soft, corpus):
                tagged.append((reaction, None, 1, idx))

    # --- Mechanic-scoped reactions (global) ---
    for mech_id in sorted(corpus.mechanics):
        mechanic = corpus.mechanics[mech_id]
        for idx, reaction in enumerate(mechanic.reactions):
            if _reaction_matches(reaction, event_type, context,
                                 hard, soft, corpus):
                tagged.append((reaction, None, 2, idx))

    # Sort: priority asc, scope rank asc, definition order asc
    tagged.sort(key=lambda x: (x[0].priority, x[2], x[3]))

    return [(r, owner) for r, owner, _s, _i in tagged]


def _reaction_matches(
    reaction: Reaction,
    event_type: str,
    context: dict[str, Any],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> bool:
    if reaction.id in _disabled_once:
        return False
    if reaction.on != event_type:
        return False
    if reaction.condition is None:
        return True
    return evaluate(reaction.condition, hard, soft, corpus, event_ctx=context)


# ------------------------------------------------------------------
# Reaction dispatch
# ------------------------------------------------------------------


def dispatch_reactions(
    reactions: list[tuple[Reaction, str | None]],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any,
    changes: HardStateChanges | None = None,
    depth: int = 0,
    encounter_trigger_ref: list[str | None] | None = None,
    triggered_narration: list[str] | None = None,
    revealed_hints: list[str] | None = None,
    rolls: list[dict[str, Any]] | None = None,
    encounter_fired_ref: list[bool] | None = None,
    combat_log: list[CombatLogEntry] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Apply effects for a list of pre-matched ``(reaction, owner_id)`` tuples.

    *changes* is an optional ``HardStateChanges`` accumulator.  When provided,
    all state mutations produced by the reactions are merged into it; when
    ``None``, state mutations are applied immediately via *state_manager*.
    Using an accumulator lets the caller apply a batch of reaction effects in
    a single ``apply_hard_changes()`` call and derive state-change events from
    the merged diff.

    *encounter_trigger_ref* is an optional one-element list used by immediate
    reactions.  When provided, ``trigger_encounter`` effects append the
    encounter ID to the list instead of resolving the encounter inline.  The
    caller (the resolver) is responsible for setting
    ``resolution.encounter_trigger`` and letting ``engine.resolve()`` run the
    encounter through the normal pipeline.

    *triggered_narration*, *revealed_hints*, and *combat_log* are optional
    output lists.  When provided, narrative text, hint reveals, and combat
    log entries from reaction results are appended so the caller can merge
    them into the final EngineResult.

    Reactions with ``once=True`` are disabled in-memory after firing.

    Returns a list of ``(event_type, context)`` tuples for new events emitted
    by reaction effects (encounter outcomes, dialogue transitions, etc.).
    These are eligible for recursive dispatch up to ``MAX_RECURSION_DEPTH``.
    """
    if depth >= MAX_RECURSION_DEPTH:
        log.warning(
            "Reaction dispatch exceeded max recursion depth %d",
            MAX_RECURSION_DEPTH,
        )
        return []

    # Mutable one-element list shared across recursive calls to track
    # whether an encounter has already been triggered this turn.
    if encounter_fired_ref is None:
        encounter_fired_ref = [False]

    new_events: list[tuple[str, dict[str, Any]]] = []

    for reaction, owner_id in reactions:
        # --- once tracking ---
        if reaction.once:
            _disabled_once.add(reaction.id)

        # --- "self" resolution ---
        resolved = _resolve_self(reaction.effect, owner_id)

        # --- apply result (state mutations) ---
        chain_events: list[tuple[str, dict[str, Any]]] = []
        if resolved.result is not None and resolved.result.has_any_effect():
            hc = HardStateChanges()
            narrative: list[str] = []
            revealed: list[str] = []
            from mgmai.engine.resolver import _apply_result_with_check, ResolutionResult
            resolution_for_chain = ResolutionResult(success=True)
            chain_rolls: list[dict[str, Any]] = []
            _apply_result_with_check(
                resolved.result,
                changes=hc, narrative=narrative,
                revealed_hints=revealed, hard=hard, corpus=corpus,
                soft=soft, room_id=hard.player.location or "",
                rolls=chain_rolls,
                state_manager=None,
                resolution=resolution_for_chain,
                source_id=reaction.id,
                source_type="reaction",
            )
            chain_events.extend(resolution_for_chain.events)
            if rolls is not None:
                rolls.extend(chain_rolls)
            if triggered_narration is not None:
                triggered_narration.extend(narrative)
            if revealed_hints is not None:
                revealed_hints.extend(revealed)
            if changes is not None:
                changes.merge(hc)
            else:
                state_manager.apply_hard_changes(hc)

        # --- trigger_encounter (once-per-turn guard) ---
        if resolved.trigger_encounter is not None:
            if encounter_trigger_ref is not None:
                encounter_trigger_ref.append(resolved.trigger_encounter)
            else:
                if encounter_fired_ref[0]:
                    log.warning(
                        "Ignoring trigger_encounter '%s': an encounter already "
                        "fired this turn",
                        resolved.trigger_encounter,
                    )
                else:
                    encounter_fired_ref[0] = True
                    enc_events = _resolve_reaction_encounter(
                        resolved.trigger_encounter, hard, soft, corpus, state_manager,
                        changes=changes,
                        triggered_narration=triggered_narration,
                        combat_log=combat_log,
                    )
                    new_events.extend(enc_events)

        # --- trigger_dialogue ---
        if resolved.trigger_dialogue is not None:
            npc_id = resolved.trigger_dialogue
            from mgmai.engine.dialogue import enter_dialogue, exit_dialogue

            current_npc = soft.dialogue_state.active_npc
            if current_npc is not None and current_npc != npc_id:
                exit_dialogue(soft, corpus, hard)
                new_events.append(("dialogue.ended", {
                    "npc_id": current_npc,
                    "reason": "triggered",
                }))

            if soft.dialogue_state.active_npc is None:
                enter_dialogue(soft, npc_id, hard.turn_count, None, "")
                new_events.append(("dialogue.started", {"npc_id": npc_id}))

        # --- game_over ---
        if resolved.game_over is not None:
            go = resolved.game_over
            hard.game_over = GameOverState(type=go.type, trigger=go.trigger_id)

        # Chain-check events are action-level events that the event bus should
        # dispatch recursively alongside other reaction-generated events.
        new_events.extend(chain_events)

    # --- recurse ---
    # Iterate over a snapshot of new_events: events returned from the deeper
    # level (more_events) have already been dispatched there and must not be
    # re-dispatched at this depth, otherwise a self-chaining reaction would
    # grow new_events without bound and defeat the depth limit.
    if new_events and depth + 1 < MAX_RECURSION_DEPTH:
        for ev_type, ev_ctx in list(new_events):
            more = find_matching_reactions(
                ev_type, ev_ctx, hard, soft, corpus,
            )
            more_events = dispatch_reactions(
                more, hard, soft, corpus, state_manager,
                changes, depth + 1, encounter_trigger_ref,
                triggered_narration, revealed_hints, rolls,
                encounter_fired_ref, combat_log,
            )
            new_events.extend(more_events)

    return new_events


# ------------------------------------------------------------------
# "self" resolution
# ------------------------------------------------------------------

_SELF_FIELDS = frozenset({
    "trigger_encounter",
    "trigger_dialogue",
})


def _resolve_self(
    effects: ReactionEffects,
    owner_id: str | None,
) -> ReactionEffects:
    """Return a copy of *effects* with ``"self"`` replaced by *owner_id*.

    Resolves both the top-level trigger fields and ``Result`` fields
    ``set_entity_state`` / ``adjust_attitude`` that use ``"self"`` as an
    entity key.
    """
    if owner_id is None:
        return effects

    # Resolve top-level effect fields
    resolved_result = effects.result
    if resolved_result is not None and resolved_result.has_any_effect():
        resolved_result = _resolve_self_in_result(resolved_result, owner_id)

    trigger_encounter = effects.trigger_encounter
    if trigger_encounter == "self":
        trigger_encounter = owner_id

    trigger_dialogue = effects.trigger_dialogue
    if trigger_dialogue == "self":
        trigger_dialogue = owner_id

    return ReactionEffects(
        result=resolved_result,
        trigger_encounter=trigger_encounter,
        trigger_dialogue=trigger_dialogue,
        game_over=effects.game_over,
    )


def _resolve_self_in_result(
    result: Any,
    owner_id: str,
) -> Any:
    """Replace ``"self"`` keys in result's entity/attitude fields."""
    from mgmai.models.corpus import Result, StatModifier

    kwargs = dict(result.__dict__) if result.__dict__ else {}
    pydantic_fields = result.model_dump(exclude_unset=True, exclude_defaults=False)

    set_entity_state = pydantic_fields.get("set_entity_state")
    if set_entity_state is not None and "self" in set_entity_state:
        new_es = dict(set_entity_state)
        new_es[owner_id] = new_es.pop("self")
        kwargs["set_entity_state"] = new_es

    adjust_attitude = pydantic_fields.get("adjust_attitude")
    if adjust_attitude is not None and "self" in adjust_attitude:
        new_aa = dict(adjust_attitude)
        new_aa[owner_id] = new_aa.pop("self")
        kwargs["adjust_attitude"] = new_aa

    return Result(**kwargs)


# ------------------------------------------------------------------
# Encounter resolution from reactions
# ------------------------------------------------------------------


def _resolve_reaction_encounter(
    encounter_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any,
    changes: HardStateChanges | None = None,
    triggered_narration: list[str] | None = None,
    combat_log: list[CombatLogEntry] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Resolve an encounter triggered by a reaction.

    Returns a list of new events emitted by the encounter outcome.
    """
    from mgmai.engine.encounters import resolve_encounter as resolve_enc

    encounter_rules = None
    source_id = encounter_id

    # Try NPC aggro first
    npc = corpus.entities.get(encounter_id)
    if npc and npc.aggro:
        encounter_rules = npc.aggro
    else:
        mech = corpus.mechanics.get(encounter_id)
        if mech and mech.rules:
            if mech.condition:
                if not evaluate(mech.condition, hard, soft, corpus):
                    return []
            encounter_rules = mech.rules

    if not encounter_rules:
        return []

    enc_result = resolve_enc(encounter_rules, hard, soft, corpus, source_id)
    events: list[tuple[str, dict[str, Any]]] = []

    # Propagate encounter narrative
    if enc_result.get("narrative") and triggered_narration is not None:
        triggered_narration.append(enc_result["narrative"])

    # Apply encounter state changes
    set_flags = enc_result.get("set_flags") or {}
    if set_flags:
        if changes is not None:
            changes.flags_set.update(set_flags)
        else:
            for flag, val in set_flags.items():
                hard.flags[flag] = val

    alter_stat = enc_result.get("alter_stat") or {}
    if alter_stat:
        if changes is not None:
            changes.stat_modifiers.update(dict(alter_stat))
        else:
            state_manager.apply_hard_changes(
                HardStateChanges(stat_modifiers=dict(alter_stat))
            )

    player_damage = enc_result.get("player_damage")
    if player_damage and corpus is not None:
        from mgmai.engine.systems import get_system_for_corpus as _eb_get_system
        _eb_system = _eb_get_system(corpus)
        eb_dmg_total, _ = _eb_system.roll_damage(player_damage)
        if changes is not None:
            changes.player_hp_delta = (
                (changes.player_hp_delta or 0) - eb_dmg_total
            )
        else:
            state_manager.apply_hard_changes(
                HardStateChanges(player_hp_delta=-eb_dmg_total)
            )

    if enc_result["game_over"]:
        go = enc_result["game_over"]
        hard.game_over = GameOverState(type=go["type"], trigger=go["trigger"])

    # Combat entry via encounter outcome
    if enc_result["trigger_combat"]:
        from mgmai.engine.combat import enter_combat
        combat_entry = enter_combat([source_id], hard, corpus)
        if combat_entry.get("hard_changes"):
            if changes is not None:
                changes.merge(combat_entry["hard_changes"])
            else:
                state_manager.apply_hard_changes(combat_entry["hard_changes"])
        if combat_entry.get("game_over"):
            hard.game_over = GameOverState(type="lose", trigger="player_death")
        if combat_entry.get("combat_log") and combat_log is not None:
            combat_log.extend(combat_entry["combat_log"])
        events.append(("combat.started", {"combatant_ids": [source_id]}))

    branch_taken = enc_result.get("branch_taken")
    if branch_taken is not None:
        events.append((
            "encounter.branched",
            {
                "encounter_id": source_id,
                "branch": branch_taken,
            },
        ))

    return events
