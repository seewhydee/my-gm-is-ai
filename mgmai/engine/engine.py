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

import copy
import logging
from typing import Any

log = logging.getLogger(__name__)

from mgmai.models.actions import (
    AttitudeLimitsCurrent,
    ChainInfo,
    CombatLogEntry,
    ConditionStatus,
    EncounterOutcome,
    EngineResult,
    GameOverResult,
    HardStateChanges,
    OnEnterEventResult,
    PlayerAction,
    WillRevealReadinessEntry,
)
from mgmai.models.briefing import (
    BriefingEntity,
    BriefingExit,
    BriefingInteraction,
    BriefingRoom,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState, GameOverState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch, TurnHistoryEntry
from mgmai.state.manager import StateManager
from mgmai.engine.conditions import evaluate, get_condition_detail
from mgmai.engine.resolver import resolve_action, ResolutionResult
from mgmai.engine.utils import inject_following_npcs, get_following_npc_ids
from mgmai.engine.event_bus import find_matching_reactions, dispatch_reactions
from mgmai.engine.encounters import (
    apply_flee_effects,
    resolve_encounter,
)
from mgmai.engine.dialogue import (
    check_room_change_exit,
    enter_dialogue,
    exit_dialogue,
    increment_stall,
)

MAX_CHAIN_LENGTH = 10


def resolve(
    player_action: PlayerAction,
    state_manager: StateManager,
    *,
    chain_depth: int = 0,
    player_input_echo: str | None = None,
) -> EngineResult:
    """Resolve a PlayerAction and produce an EngineResult.

    This is the main engine entry point. It validates the action, applies
    hard-state changes, resolves encounters, fires on-enter events, manages
    dialogue, checks game-over conditions, increments the turn counter, and
    builds the full EngineResult.

    For chained actions, returns an EngineResult with chain_info indicating
    the follow_up action that the game loop should process next.
    """
    hard = state_manager.hard_state
    soft = state_manager.soft_state
    corpus = state_manager.corpus
    if hard is None or soft is None or corpus is None:
        return EngineResult(
            success=False,
            action_type=player_action.action_type,
            error="State not loaded",
        )

    action_type = player_action.action_type

    if action_type == "ooc_discussion":
        turn_entry = TurnHistoryEntry(
            turn=hard.turn_count,
            player_input=player_input_echo or player_action.detail,
            ruled_action=player_action.model_dump(),
            engine_result_summary="OOC discussion",
            flags_changed=[],
            location_after=hard.player.location,
        )
        state_manager.append_turn_history(turn_entry)
        return EngineResult(
            success=True,
            action_type="ooc_discussion",
            player_input_echo=player_input_echo,
            message="Out-of-character discussion — no state changes.",
        )

    if player_action.follow_up and chain_depth >= MAX_CHAIN_LENGTH:
        return EngineResult(
            success=False,
            action_type=action_type,
            target=getattr(player_action, "target", None),
            error=f"Chain exceeded maximum depth ({MAX_CHAIN_LENGTH})",
            chain_info=ChainInfo(
                follow_up=player_action.follow_up,
                termination_reason=f"max depth ({MAX_CHAIN_LENGTH})",
            ),
        )

    # Auto-clear expired improvised weapons before resolving the action
    state_manager.clear_expired_improvised_weapon()

    # Snapshots for state-change event derivation.  These are taken before any
    # reaction or action effects are applied this turn.
    old_flags = dict(hard.flags)
    old_stats = dict(hard.player.stats or {})
    old_entity_states = copy.deepcopy(hard.entity_states)
    old_room = hard.player.location

    # Accumulator for all hard-state changes produced during this turn, used
    # to derive the final state-change events under Option B.
    merged_changes = HardStateChanges()
    reaction_combat_log: list[CombatLogEntry] = []

    def _apply_and_merge(batch: HardStateChanges) -> None:
        """Apply *batch* and merge it into *merged_changes* for diff tracking."""
        if batch.has_changes():
            state_manager.apply_hard_changes(batch)
            merged_changes.merge(batch)

    # 1. Turn-start reactions fire before the action resolves.
    turn_start_changes = HardStateChanges()
    turn_start_narration: list[str] = []
    turn_start_reveals: list[str] = []
    _dispatch_events(
        [("turn.start", {"turn_number": hard.turn_count})],
        hard, soft, corpus, state_manager, changes=turn_start_changes,
        triggered_narration=turn_start_narration,
        revealed_hints=turn_start_reveals,
        combat_log=reaction_combat_log,
    )
    _apply_and_merge(turn_start_changes)

    # 2. Resolve the action.  Immediate reactions fire synchronously inside
    #    the resolvers and accumulate into resolution.immediate_changes.
    resolution = resolve_action(player_action, hard, soft, corpus, state_manager)

    # Merge turn-start narration/reveals into resolution.
    resolution.triggered_narration = turn_start_narration + list(resolution.triggered_narration or [])
    resolution.revealed_hints = turn_start_reveals + list(resolution.revealed_hints or [])

    # Initialize result-tracking variables.
    encounter_outcome: dict[str, Any] | None = None
    game_over = None
    rolls: list[dict[str, Any]] = list(resolution.rolls or [])
    combat_triggered = False
    combat_log: list[CombatLogEntry] = []

    # 3. Process encounter triggers from the action or immediate reactions.
    if resolution.encounter_trigger:
        trigger_id = resolution.encounter_trigger
        npc = corpus.entities.get(trigger_id)
        encounter_rules = None
        encounter_source_id = trigger_id

        if npc and npc.behavior:
            encounter_rules = npc.behavior.encounter_rules
        else:
            mech = corpus.mechanics.get(trigger_id)
            if mech and mech.rules:
                if mech.condition and not evaluate(mech.condition, hard, soft, corpus):
                    pass
                else:
                    encounter_rules = mech.rules

        if encounter_rules:
            enc_result = resolve_encounter(
                encounter_rules, hard, soft, corpus, encounter_source_id
            )
            if enc_result["narrative"]:
                resolution.triggered_narration.append(enc_result["narrative"])

            encounter_changes = HardStateChanges()
            set_flags = enc_result.get("set_flags") or {}
            if set_flags:
                encounter_changes.flags_set.update(set_flags)

            if enc_result["flee_effects"]:
                pre_flags = dict(hard.flags)
                pre_entity = {
                    eid: dict(state)
                    for eid, state in hard.entity_states.items()
                }
                apply_flee_effects(enc_result["flee_effects"], hard)
                for flag, val in hard.flags.items():
                    if pre_flags.get(flag) != val:
                        encounter_changes.flags_set[flag] = val
                for eid, state in hard.entity_states.items():
                    pre = pre_entity.get(eid, {})
                    delta = {k: v for k, v in state.items() if pre.get(k) != v}
                    if delta:
                        encounter_changes.entity_state_changes.setdefault(eid, {}).update(delta)

            alter_stat = enc_result.get("alter_stat") or {}
            if alter_stat:
                encounter_changes.stat_modifiers.update(dict(alter_stat))

            if enc_result["game_over"]:
                go = enc_result["game_over"]
                hard.game_over = GameOverState(type=go["type"], trigger=go["trigger"])
                game_over = GameOverResult(
                    type=go["type"],
                    trigger=go["trigger"],
                    narrative=enc_result.get("narrative"),
                )

            encounter_outcome = EncounterOutcome(
                encounter_id=encounter_source_id,
                outcome=enc_result["outcome"],
                narrative_brief=enc_result.get("narrative"),
            )
            enc_rolls = enc_result.get("rolls") or []
            rolls.extend(enc_rolls)

            if enc_result["outcome"] == "combat":
                from mgmai.engine.combat import enter_combat
                combat_entry = enter_combat([encounter_source_id], hard, corpus)
                combat_triggered = True
                combat_log = combat_entry["combat_log"]
                if combat_entry.get("hard_changes"):
                    encounter_changes.merge(combat_entry["hard_changes"])
                if combat_entry.get("game_over"):
                    hard.game_over = GameOverState(type="lose", trigger="player_death")
                    game_over = GameOverResult(type="lose", trigger="player_death")
                if soft.dialogue_state.active_npc is not None:
                    resolution.dialogue_exited = exit_dialogue(soft, corpus, hard)

            _apply_and_merge(encounter_changes)

    # On a failed resolution, return early; deferred reactions do not run.
    if not resolution.success:
        chain_info = None
        if player_action.follow_up:
            chain_info = ChainInfo(
                follow_up=player_action.follow_up,
                termination_reason="validation failure",
            )
        return EngineResult(
            success=False,
            action_type=action_type,
            target=getattr(player_action, "target", None),
            error=resolution.error,
            player_input_echo=player_input_echo,
            chain_info=chain_info,
            game_over=game_over,
            encounter_outcome=encounter_outcome,
            rolls=rolls,
        )

    # 4. Merge action + immediate-reaction changes and apply them once.
    action_changes = HardStateChanges()
    action_changes.merge(resolution.hard_changes or HardStateChanges())
    action_changes.merge(resolution.immediate_changes)
    _apply_and_merge(action_changes)

    # 5. Apply soft patches and persist surfaced items / revealed hints.
    engine_soft_patches = list(resolution.soft_patches or [])
    if engine_soft_patches:
        state_manager.apply_soft_patches(engine_soft_patches)

    for entity_or_room_id, items in resolution.surfaced_soft_items.items():
        if entity_or_room_id not in soft.surfaced_soft_items:
            soft.surfaced_soft_items[entity_or_room_id] = []
        for item in items:
            if item not in soft.surfaced_soft_items[entity_or_room_id]:
                soft.surfaced_soft_items[entity_or_room_id].append(item)

    soft_patches = _validate_soft_patches(
        player_action.proposed_soft_state_patches or [],
        hard,
        soft,
        corpus,
    )
    applied_patches, rejected_patches = soft_patches
    if applied_patches:
        state_manager.apply_soft_patches(applied_patches)
    combined_applied = engine_soft_patches + applied_patches

    for hint in resolution.revealed_hints or []:
        if hint not in soft.revealed_hints:
            soft.revealed_hints.append(hint)

    # 6. Handle direct combat triggers and game-over from resolver.
    if resolution.combat_triggered:
        combat_triggered = True
        combat_log = list(resolution.combat_log or [])
        if resolution.game_over_trigger:
            hard.game_over = GameOverState(type="lose", trigger=resolution.game_over_trigger)
            game_over = GameOverResult(type="lose", trigger=resolution.game_over_trigger)
        if soft.dialogue_state.active_npc is not None:
            resolution.dialogue_exited = exit_dialogue(soft, corpus, hard)

    if resolution.combat_log and not combat_triggered:
        combat_log = list(resolution.combat_log)
        if resolution.game_over_trigger:
            hard.game_over = GameOverState(type="lose", trigger=resolution.game_over_trigger)
            game_over = GameOverResult(type="lose", trigger=resolution.game_over_trigger)

    if hard.game_over is None:
        _check_game_over_mechanics(hard, soft, corpus, game_over_ref := [None])
        if game_over_ref[0]:
            game_over = game_over_ref[0]
            hard.game_over = GameOverState(type=game_over.type, trigger=game_over.trigger)

    # Track whether an encounter has already fired this turn, so that
    # subsequent reaction trigger_encounter effects are suppressed.
    encounter_fired_ref = [encounter_outcome is not None]

    # 7. Room transition and room-entered reactions.
    on_enter_results: list[OnEnterEventResult] = []
    new_room = resolution.room_after_id or hard.player.location

    dialogue_exit_reason: str | None = None
    if new_room != old_room:
        room_changes = HardStateChanges()

        # room.exited has no immediate phase, so this only dispatches deferred
        # reactions and accumulates their effects.
        _dispatch_events(
            [("room.exited", {"room_id": old_room})],
            hard, soft, corpus, state_manager, changes=room_changes,
            triggered_narration=resolution.triggered_narration,
            revealed_hints=resolution.revealed_hints,
            encounter_fired_ref=encounter_fired_ref,
            combat_log=reaction_combat_log,
        )

        # room.entered immediate reactions fire before legacy on-enter events.
        entered_matches = find_matching_reactions(
            "room.entered", {"room_id": new_room}, hard, soft, corpus,
        )
        entered_immediate = [(r, o) for r, o in entered_matches if r.phase == "immediate"]
        if entered_immediate:
            dispatch_reactions(
                entered_immediate, hard, soft, corpus, state_manager,
                changes=room_changes,
                triggered_narration=resolution.triggered_narration,
                revealed_hints=resolution.revealed_hints,
                encounter_fired_ref=encounter_fired_ref,
                combat_log=reaction_combat_log,
            )

        # Deferred room.entered reactions also accumulate before on-enter.
        entered_deferred = [(r, o) for r, o in entered_matches if r.phase != "immediate"]
        if entered_deferred:
            dispatch_reactions(
                entered_deferred, hard, soft, corpus, state_manager,
                changes=room_changes,
                triggered_narration=resolution.triggered_narration,
                revealed_hints=resolution.revealed_hints,
                encounter_fired_ref=encounter_fired_ref,
                combat_log=reaction_combat_log,
            )

        _apply_and_merge(room_changes)

        on_enter_results = _fire_on_enter_events(
            new_room, hard, soft, corpus, resolution.triggered_narration
        )

        dialogue_exit = check_room_change_exit(soft, old_room, new_room, corpus, hard)
        if dialogue_exit:
            resolution.dialogue_exited = dialogue_exit
            dialogue_exit_reason = "room_change"

    if hard.game_over is not None and game_over is None:
        game_over = GameOverResult(type=hard.game_over.type, trigger=hard.game_over.trigger)

    if action_type == "talk":
        pass
    elif action_type != "ooc_discussion":
        if soft.dialogue_state.active_npc is not None:
            stall_exited = increment_stall(soft)
            if stall_exited:
                resolution.dialogue_exited = exit_dialogue(soft, corpus, hard)

    # 8. Dispatch deferred reactions for action-level events.
    action_events: list[tuple[str, dict[str, Any]]] = list(resolution.events)
    if resolution.dialogue_exited:
        npc_id = (
            resolution.dialogue_exited.get("npc_id")
            if isinstance(resolution.dialogue_exited, dict)
            else getattr(resolution.dialogue_exited, "npc_id", None)
        )
        # Avoid emitting a duplicate dialogue.ended if the resolver already
        # emitted one (e.g. talk action with ends_dialogue or switched_npc).
        already_emitted = any(
            ev[0] == "dialogue.ended" and ev[1].get("npc_id") == npc_id
            for ev in action_events
        )
        if npc_id and not already_emitted:
            reason = dialogue_exit_reason or (
                "stall" if action_type != "talk" else "player_left"
            )
            action_events.append(("dialogue.ended", {
                "npc_id": npc_id,
                "reason": reason,
            }))

    event_changes = HardStateChanges()
    _dispatch_events(
        action_events, hard, soft, corpus, state_manager, changes=event_changes,
        triggered_narration=resolution.triggered_narration,
        revealed_hints=resolution.revealed_hints,
        encounter_fired_ref=encounter_fired_ref,
        combat_log=reaction_combat_log,
    )
    _apply_and_merge(event_changes)

    # 9. Derive state-change events from the merged diff and dispatch them once.
    state_events = _derive_state_events(
        merged_changes, old_flags, old_stats, old_entity_states, hard,
    )
    _dispatch_events(state_events, hard, soft, corpus, state_manager, changes=None,
                     triggered_narration=resolution.triggered_narration,
                     revealed_hints=resolution.revealed_hints,
                     encounter_fired_ref=encounter_fired_ref,
                     combat_log=reaction_combat_log)

    # 10. turn.end reactions (state changes apply directly, no second derivation).
    _dispatch_events(
        [("turn.end", {"turn_number": hard.turn_count})],
        hard, soft, corpus, state_manager, changes=None,
        triggered_narration=resolution.triggered_narration,
        revealed_hints=resolution.revealed_hints,
        encounter_fired_ref=encounter_fired_ref,
        combat_log=reaction_combat_log,
    )

    # If a reaction started combat, ensure the result reflects it.
    if not combat_triggered and hard.combat is not None and hard.combat.active:
        combat_triggered = True

    hard.turn_count += 1

    turn_entry = TurnHistoryEntry(
        turn=hard.turn_count,
        player_input=player_input_echo or player_action.detail,
        ruled_action=player_action.model_dump(),
        engine_result_summary=_summarize_resolution(resolution, new_room),
        flags_changed=list(merged_changes.flags_set.keys())
        + list(merged_changes.flags_cleared),
        location_after=new_room,
    )
    state_manager.append_turn_history(turn_entry)

    room_after = _build_room_after(new_room, hard, soft, corpus)
    will_reveal = _build_will_reveal_readiness(new_room, hard, soft, corpus)
    attitude_limits = _build_npc_attitude_limits(new_room, hard, soft, corpus)

    warnings = list(resolution.warnings or [])
    if player_action.follow_up:
        warnings.append(
            f"Chain action: follow_up remaining after this turn: "
            f"{player_action.follow_up[:100]}"
        )

    chain_info = None
    if player_action.follow_up:
        chain_info = ChainInfo(follow_up=player_action.follow_up)

    return EngineResult(
        success=True,
        action_type=action_type,
        target=getattr(player_action, "target", None),
        player_input_echo=player_input_echo,
        room_after=room_after,
        hard_state_changes=merged_changes,
        soft_state_patches_applied=combined_applied,
        soft_state_patches_rejected=rejected_patches,
        rolls=rolls,
        encounter_outcome=encounter_outcome if isinstance(encounter_outcome, EncounterOutcome) else None,
        triggered_narration=resolution.triggered_narration,
        on_enter_events=on_enter_results,
        game_over=game_over,
        dialogue_exited=resolution.dialogue_exited,
        will_reveal_readiness=will_reveal,
        npc_attitude_limits=attitude_limits,
        chain_info=chain_info,
        revealed_hints=resolution.revealed_hints or [],
        warnings=warnings,
        combat_triggered=combat_triggered,
        combat_log=combat_log + reaction_combat_log,
    )


def _validate_soft_patches(
    patches: list[SoftStatePatch],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> tuple[list[SoftStatePatch], list[dict[str, Any]]]:
    applied: list[SoftStatePatch] = []
    rejected: list[dict[str, Any]] = []

    for patch in patches:
        reason = None

        if patch.field == "room_note":
            if not patch.target_id or patch.target_id not in corpus.rooms:
                reason = f"Invalid room_id: {patch.target_id}"
            elif not isinstance(patch.new_value, str) or not patch.new_value.strip():
                reason = "room_note new_value must be a non-empty string"
            else:
                room = corpus.rooms.get(patch.new_value if isinstance(patch.new_value, str) else "")
                if room is None:
                    pass
                contradiction = _check_note_contradiction(patch.new_value, patch.target_id, hard, corpus)
                if contradiction:
                    reason = contradiction
        elif patch.field == "entity_note":
            if not patch.entity_id or patch.entity_id not in corpus.entities:
                reason = f"Invalid entity_id: {patch.entity_id}"
            elif not isinstance(patch.new_value, str) or not patch.new_value.strip():
                reason = "entity_note new_value must be a non-empty string"
            else:
                entity_state = hard.entity_states.get(patch.entity_id, {})
                if entity_state.get("alive") is False:
                    reason = f"Entity '{patch.entity_id}' is dead; notes are not allowed"
                else:
                    contradiction = _check_note_contradiction(patch.new_value, None, hard, corpus)
                    if contradiction:
                        reason = contradiction
        elif patch.field == "soft_inventory_add":
            room_id = hard.player.location
            room = corpus.rooms.get(room_id)
            if room is None:
                reason = f"Invalid room: {room_id}"
            else:
                all_soft = set(room.soft_items or [])
                for eid in room.entities_present:
                    ent = corpus.entities.get(eid)
                    if ent and ent.soft_items:
                        all_soft.update(ent.soft_items)
                item = patch.new_value if isinstance(patch.new_value, str) else str(patch.new_value)
                if item not in all_soft:
                    reason = f"Soft item '{item}' not available in room '{room_id}'"
        elif patch.field == "soft_inventory_remove":
            item = patch.new_value if isinstance(patch.new_value, str) else str(patch.new_value)
            if item not in soft.soft_inventory:
                reason = f"Soft item '{item}' not in soft inventory"

        if not patch.reason or not patch.reason.strip():
            reason = "reason is empty"

        if reason:
            rejected.append({
                "patch": patch.model_dump(),
                "reason": reason,
            })
        else:
            applied.append(patch)

    return applied, rejected


def _check_note_contradiction(
    text: str,
    room_id: str | None,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> str | None:
    """Basic contradiction check: note text must not claim an entity is
    dead/alive in contradiction with hard state."""
    text_lower = text.lower()
    for ent_id, state in hard.entity_states.items():
        if room_id is not None:
            room = corpus.rooms.get(room_id)
            if room is None or ent_id not in room.entities_present:
                continue
        ent = corpus.entities.get(ent_id)
        if ent is None:
            continue
        name = getattr(ent, "name", ent_id) or ent_id
        name_lower = name.lower()
        if name_lower not in text_lower.split():
            continue
        if state.get("alive") is False and "dead" not in text_lower:
            pass
        elif state.get("alive") is True and "dead" in text_lower and name_lower in text_lower:
            return f"Note contradicts hard state: '{name}' is alive"
    return None


def _build_room_after(
    room_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> BriefingRoom:
    room = corpus.rooms.get(room_id)
    if room is None:
        return BriefingRoom(
            id=room_id,
            name="Unknown",
            description="",
        )

    entities_visible: list[BriefingEntity] = []
    for eid in room.entities_present:
        entity = corpus.entities.get(eid)
        if entity is None:
            continue

        entity_state = hard.entity_states.get(eid, {})
        if entity_state.get("hidden", False):
            continue
        if entity.type == "item" and eid in hard.player.inventory:
            continue

        notes = soft.entity_notes.get(eid, [])[-5:]
        entity_soft = soft.surfaced_soft_items.get(eid, [])

        path_descriptions: dict[str, str] = {}
        if entity.type == "npc" and entity.dialogue_guidelines:
            path_descriptions = {
                path_id: path.description
                for path_id, path in entity.dialogue_guidelines.dialogue_paths.items()
            }

        entities_visible.append(
            BriefingEntity(
                id=eid,
                name=getattr(entity, "name", eid),
                type=entity.type,
                description=entity.description,
                state=entity_state,
                entity_notes=notes,
                soft_items=list(entity_soft),
                dialogue_paths=path_descriptions,
            )
        )

    exits_available: list[BriefingExit] = []
    for ex in room.exits:
        if ex.hidden:
            # Hidden exits are revealed only when their conditions are met
            if ex.conditions:
                all_met = True
                for cond in ex.conditions:
                    if not evaluate(cond, hard, soft, corpus):
                        all_met = False
                        break
                if not all_met:
                    continue
            else:
                continue
        elif ex.conditions:
            all_met = True
            for cond in ex.conditions:
                if not evaluate(cond, hard, soft, corpus):
                    all_met = False
                    break
            if not all_met:
                continue
        exits_available.append(
            BriefingExit(
                id=ex.id,
                direction=ex.direction,
                target_room=ex.target_room,
                hidden=ex.hidden,
            )
        )

    interactions_available: list[BriefingInteraction] = []
    for inter in room.interactions:
        if inter.condition:
            if not evaluate(inter.condition, hard, soft, corpus):
                continue
        interactions_available.append(
            BriefingInteraction(
                id=inter.id,
                label=inter.label,
                description=inter.description,
            )
        )

    room_notes = soft.room_notes.get(room_id, [])[-5:]
    room_soft_items = soft.surfaced_soft_items.get(room_id, [])

    inject_following_npcs(entities_visible, room_id, hard, soft, corpus)

    return BriefingRoom(
        id=room_id,
        name=room.name,
        description=room.description,
        soft_items=list(room_soft_items),
        entities_visible=entities_visible,
        exits_available=exits_available,
        interactions_available=interactions_available,
        room_notes=room_notes,
    )


def _build_will_reveal_readiness(
    room_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> dict[str, dict[str, WillRevealReadinessEntry]]:
    result: dict[str, dict[str, WillRevealReadinessEntry]] = {}
    room = corpus.rooms.get(room_id)
    if room is None:
        return result

    npc_ids: set[str] = set()
    for eid in room.entities_present:
        npc_ids.add(eid)
    for eid in get_following_npc_ids(hard, corpus):
        npc_ids.add(eid)

    for eid in sorted(npc_ids):
        entity = corpus.entities.get(eid)
        if entity is None or entity.type != "npc":
            continue

        guidelines = entity.dialogue_guidelines
        if guidelines is None:
            continue

        entity_state = hard.entity_states.get(eid, {})
        if entity_state.get("alive") is False:
            continue

        npc_ready: dict[str, WillRevealReadinessEntry] = {}
        for topic_id, topic_entry in guidelines.will_reveal.items():
            conditions_met = True
            conditions: list[ConditionStatus] = []
            for cond_raw in topic_entry.conditions:
                status = get_condition_detail(cond_raw, hard, soft, corpus)
                conditions.append(status)
                if not status.met:
                    conditions_met = False
            npc_ready[topic_id] = WillRevealReadinessEntry(
                conditions_met=conditions_met,
                description=topic_entry.description,
                conditions=conditions,
            )

        if npc_ready:
            result[eid] = npc_ready

    return result


def _build_npc_attitude_limits(
    room_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> dict[str, AttitudeLimitsCurrent]:
    result: dict[str, AttitudeLimitsCurrent] = {}
    room = corpus.rooms.get(room_id)
    if room is None:
        return result

    npc_ids: set[str] = set()
    for eid in room.entities_present:
        npc_ids.add(eid)
    for eid in get_following_npc_ids(hard, corpus):
        npc_ids.add(eid)

    for eid in sorted(npc_ids):
        entity = corpus.entities.get(eid)
        if entity is None or entity.type != "npc":
            continue

        guidelines = entity.dialogue_guidelines
        if guidelines is None:
            continue

        limits = guidelines.attitude_limits
        entity_state = hard.entity_states.get(eid, {})
        attitude_val = entity_state.get("attitude")
        if attitude_val is None:
            current = limits.initial
        else:
            current = int(attitude_val)

        result[eid] = AttitudeLimitsCurrent(
            min=limits.min,
            max=limits.max,
            step_per_turn=limits.step_per_turn,
            current=current,
        )

    return result


def _fire_on_enter_events(
    room_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    triggered_narration: list[str],
) -> list[OnEnterEventResult]:
    results: list[OnEnterEventResult] = []
    room = corpus.rooms.get(room_id)
    if room is None:
        return results

    room_state = hard.room_states.setdefault(room_id, {})
    fired_events = room_state.setdefault("_fired_on_enter", [])

    for event in room.on_enter:
        if event.condition is None:
            if event.id in fired_events:
                continue

        if event.condition and not evaluate(event.condition, hard, soft, corpus):
            continue

        if event.set_flag:
            for flag, val in event.set_flag.items():
                hard.flags[flag] = val

        if event.set_entity_state:
            for ent_id, state_changes in event.set_entity_state.items():
                if ent_id not in hard.entity_states:
                    hard.entity_states[ent_id] = {}
                hard.entity_states[ent_id].update(state_changes)

        if event.set_room_state:
            for target_room_id, state_changes in event.set_room_state.items():
                if target_room_id not in hard.room_states:
                    hard.room_states[target_room_id] = {}
                hard.room_states[target_room_id].update(state_changes)

        if event.narrative:
            triggered_narration.append(event.narrative)

        if event.trigger_dialogue:
            npc = corpus.entities.get(event.trigger_dialogue)
            if npc and npc.type == "npc":
                from mgmai.engine.dialogue import enter_dialogue as _enter_dlg
                _enter_dlg(soft, event.trigger_dialogue, hard.turn_count, None, "")

        results.append(
            OnEnterEventResult(
                event_id=event.id,
                narrative=event.narrative,
            )
        )

        if event.condition is None:
            fired_events.append(event.id)

    return results


def _check_game_over_mechanics(
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    game_over_ref: list[Any],
) -> None:
    for mech_id, mech in corpus.mechanics.items():
        if mech.type is None:
            continue

        if mech.condition and evaluate(mech.condition, hard, soft, corpus):
            game_over_ref[0] = GameOverResult(
                type=mech.type,
                trigger=mech.trigger_id or mech_id,
                narrative=mech.narrative,
            )
            return


# ------------------------------------------------------------------
# Event dispatch helpers
# ------------------------------------------------------------------


def _derive_state_events(
    hard_changes: HardStateChanges,
    old_flags: dict[str, bool],
    old_stats: dict[str, int],
    old_entity_states: dict[str, dict[str, Any]],
    hard: HardGameState,
) -> list[tuple[str, dict[str, Any]]]:
    """Derive state-change events from the HardStateChanges diff."""
    events: list[tuple[str, dict[str, Any]]] = []

    # flag.set / flag.cleared
    for flag, val in hard_changes.flags_set.items():
        old_val = old_flags.get(flag)
        if old_val is True and val is False:
            events.append(("flag.cleared", {"flag_name": flag}))
        elif not old_val and val is True:
            events.append(("flag.set", {"flag_name": flag}))

    for flag in hard_changes.flags_cleared:
        if old_flags.get(flag):
            events.append(("flag.cleared", {"flag_name": flag}))

    # entity_state.changed
    for entity_id, entity_changes in hard_changes.entity_state_changes.items():
        for field, new_value in entity_changes.items():
            events.append(("entity_state.changed", {
                "entity_id": entity_id,
                "field": field,
                "new_value": new_value,
            }))

    # stat.changed
    for stat_key, mod in hard_changes.stat_modifiers.items():
        old_val = old_stats.get(stat_key, 0)
        new_stats = hard.player.stats or {}
        new_val = new_stats.get(stat_key, old_val)
        delta = new_val - old_val
        events.append(("stat.changed", {
            "stat_name": stat_key,
            "old_value": old_val,
            "new_value": new_val,
            "delta": delta,
        }))

    # attitude.changed (detected from entity_state_changes)
    for entity_id, entity_changes in hard_changes.entity_state_changes.items():
        if "attitude" in entity_changes:
            new_att = entity_changes["attitude"]
            old_att = old_entity_states.get(entity_id, {}).get("attitude", 0)
            try:
                new_att_num = int(new_att) if not isinstance(new_att, bool) else (1 if new_att else 0)
                old_att_num = int(old_att) if not isinstance(old_att, bool) else (1 if old_att else 0)
            except (ValueError, TypeError):
                new_att_num, old_att_num = 0, 0
            events.append(("attitude.changed", {
                "npc_id": entity_id,
                "old_value": old_att_num,
                "new_value": new_att_num,
                "delta": new_att_num - old_att_num,
            }))

    # item.acquired / item.lost (from inventory changes)
    for item in hard_changes.inventory_added:
        events.append(("item.acquired", {
            "item_id": item,
            "source": "interaction",
        }))
    for item in hard_changes.inventory_removed:
        events.append(("item.lost", {
            "item_id": item,
            "reason": "interaction",
        }))

    # equipment.changed
    if hard_changes.equipment_changed:
        events.append(("equipment.changed", {
            "added": hard_changes.equipped_added,
            "removed": hard_changes.equipped_removed,
        }))

    # player.damaged / player.healed
    if hard_changes.player_hp_delta is not None:
        hp_delta = hard_changes.player_hp_delta
        new_hp = hard.player.current_hp or 0
        if hp_delta < 0:
            events.append(("player.damaged", {
                "amount": abs(hp_delta),
                "new_hp": new_hp,
            }))
        elif hp_delta > 0:
            events.append(("player.healed", {
                "amount": hp_delta,
                "new_hp": new_hp,
            }))

    return events


def _dispatch_events(
    events: list[tuple[str, dict[str, Any]]],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any,
    changes: HardStateChanges | None,
    triggered_narration: list[str] | None = None,
    revealed_hints: list[str] | None = None,
    encounter_fired_ref: list[bool] | None = None,
    combat_log: list[CombatLogEntry] | None = None,
) -> None:
    """Dispatch a batch of deferred reactions for the given events.

    Immediate reactions are assumed to have been fired at event emission
    time (inside the resolvers).  This function only dispatches reactions
    with ``phase != "immediate"``.

    When *changes* is provided, reaction state mutations are merged into it
    so the caller can apply them in a single batch.  When *changes* is
    ``None``, mutations are applied immediately via *state_manager*.

    *triggered_narration*, *revealed_hints*, and *combat_log* are optional
    output lists that collect narrative, reveals, and combat log entries
    from reaction results.
    """
    deferred: list[tuple[Reaction, str | None]] = []

    for event_type, context in events:
        matches = find_matching_reactions(
            event_type, context, hard, soft, corpus,
        )
        deferred.extend(
            (r, o) for r, o in matches if r.phase != "immediate"
        )

    if deferred:
        dispatch_reactions(
            deferred, hard, soft, corpus, state_manager,
            changes=changes,
            triggered_narration=triggered_narration,
            revealed_hints=revealed_hints,
            encounter_fired_ref=encounter_fired_ref,
            combat_log=combat_log,
        )


def _summarize_resolution(
    resolution: ResolutionResult,
    room_after: str,
) -> str:
    parts: list[str] = []
    if resolution.hard_changes:
        hc = resolution.hard_changes
        if hc.player_location:
            parts.append(f"Moved to {hc.player_location}")
        if hc.inventory_added:
            parts.append(f"Gained: {', '.join(hc.inventory_added)}")
        if hc.inventory_removed:
            parts.append(f"Lost: {', '.join(hc.inventory_removed)}")
        if hc.flags_set:
            flags = [f"{k}={v}" for k, v in hc.flags_set.items()]
            parts.append(f"Flags set: {', '.join(flags)}")
        if hc.flags_cleared:
            parts.append(f"Flags cleared: {', '.join(hc.flags_cleared)}")
        if hc.stat_modifiers:
            stat_descs = []
            for stat_key, mod in hc.stat_modifiers.items():
                if mod.mode == "set":
                    stat_descs.append(f"{stat_key}={mod.value}")
                else:
                    sign = "+" if mod.value >= 0 else ""
                    stat_descs.append(f"{stat_key}{sign}{mod.value}")
            parts.append(f"Stats: {', '.join(stat_descs)}")
    if resolution.encounter_trigger:
        parts.append(f"Encounter: {resolution.encounter_trigger}")
    if resolution.triggered_narration:
        parts.append(
            f"Narration: {resolution.triggered_narration[0][:80]}..."
            if len(resolution.triggered_narration[0]) > 80
            else f"Narration: {resolution.triggered_narration[0]}"
        )
    return "; ".join(parts) if parts else "No changes"
