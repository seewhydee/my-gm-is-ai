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

import random
from dataclasses import dataclass, field
from typing import Any, Optional

from mgmai.models.actions import (
    CombatAction,
    DialogueExitedResult,
    EquipAction,
    ExamineAction,
    HardStateChanges,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    TalkAction,
    TransferAction,
    UnequipAction,
    WaitAction,
)
from mgmai.models.corpus import (
    ChainedCheck,
    Interaction,
    ModuleCorpus,
    OnExamineEvent,
    Result,
    RollCheck,
    StatCheck,
    StatModifier,
    TraversalCheck,
    UsingResultOverride,
)
from mgmai.models.combat import CombatLogEntry
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch
from mgmai.engine.conditions import evaluate
from mgmai.engine.dialogue import (
    append_player_turn,
    enter_dialogue,
    exit_dialogue,
)
from mgmai.engine.utils import get_following_npc_ids

MAX_CHAIN_CHECK_DEPTH = 3


def _emit_event(
    event_type: str,
    context: dict[str, Any],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None,
    resolution: ResolutionResult,
) -> None:
    """Record an event and synchronously dispatch immediate reactions to it.

    *resolution.events* receives the event so that deferred reactions can
    match it during the end-of-turn dispatch.  If *state_manager* is provided,
    any matching reactions with ``phase="immediate"`` are dispatched right
    away, with their state mutations accumulating into
    ``resolution.immediate_changes``.  A single ``trigger_encounter`` from an
    immediate reaction is recorded as ``resolution.encounter_trigger``; if
    multiple immediate reactions request encounters, a warning is logged and
    the first wins.
    """
    resolution.events.append((event_type, context))
    if state_manager is None:
        return

    from mgmai.engine.event_bus import find_matching_reactions, dispatch_reactions

    matches = find_matching_reactions(event_type, context, hard, soft, corpus)
    immediate = [(r, o) for r, o in matches if r.phase == "immediate"]
    if not immediate:
        return

    encounter_triggers: list[str | None] = []
    dispatch_reactions(
        immediate, hard, soft, corpus, state_manager,
        changes=resolution.immediate_changes,
        encounter_trigger_ref=encounter_triggers,
        triggered_narration=resolution.triggered_narration,
        revealed_hints=resolution.revealed_hints,
    )

    triggered = [t for t in encounter_triggers if t is not None]
    if triggered:
        if len(triggered) > 1:
            import logging
            logging.getLogger(__name__).warning(
                "Multiple immediate trigger_encounter reactions for %s; using %s",
                event_type, triggered[0]
            )
        if resolution.encounter_trigger is None:
            resolution.encounter_trigger = triggered[0]


@dataclass
class ResolutionResult:
    success: bool
    error: str | None = None
    hard_changes: HardStateChanges | None = None
    triggered_narration: list[str] = field(default_factory=list)
    revealed_hints: list[str] = field(default_factory=list)
    encounter_trigger: str | None = None
    combat_trigger: list[str] | None = None
    combat_log: list[CombatLogEntry] = field(default_factory=list)
    combat_triggered: bool = False
    game_over_trigger: str | None = None
    on_enter_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    room_after_id: str | None = None
    dialogue_exited: DialogueExitedResult | dict | None = None
    soft_patches: list[SoftStatePatch] = field(default_factory=list)
    rolls: list[dict[str, Any]] = field(default_factory=list)
    surfaced_soft_items: dict[str, list[str]] = field(default_factory=dict)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    immediate_changes: HardStateChanges = field(default_factory=HardStateChanges)


def resolve_wait(
    action: WaitAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    return ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=hard.player.location,
    )


def resolve_ooc(
    action: OocDiscussionAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    return ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=hard.player.location,
    )


def resolve_examine(
    action: ExamineAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    target = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Current room '{room_id}' not found in corpus")

    if action.using is not None:
        if (
            action.using not in hard.player.inventory
            and action.using not in hard.player.equipped
            and action.using not in soft.soft_inventory
        ):
            return ResolutionResult(
                success=False,
                error=f"Item '{action.using}' is not in your inventory",
            )

    if target == room_id:
        changes = HardStateChanges()
        base_narrative = [room.description]
        result = ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=base_narrative,
            room_after_id=room_id,
        )
        surface_result = _fire_on_examine_events(
            room.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
            state_manager, result,
        )
        result.revealed_hints = surface_result["revealed_hints"]
        result.surfaced_soft_items = surface_result["surfaced"]
        result.rolls = surface_result["rolls"]
        return result

    entity = _find_entity_in_room_followers(target, room_id, room, hard, corpus)
    if entity is not None:
        changes = HardStateChanges()
        if entity.type == "npc":
            entity_state = hard.entity_states.get(target, {})
            if entity_state.get("alive") is False:
                description = f"{entity.description} (It is dead.)"
            else:
                description = entity.description
        else:
            description = entity.description
        base_narrative = [description]
        result = ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=base_narrative,
            room_after_id=room_id,
        )
        surface_result = _fire_on_examine_events(
            entity.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
            state_manager, result,
        )
        result.revealed_hints = surface_result["revealed_hints"]
        result.surfaced_soft_items = surface_result["surfaced"]
        result.rolls = surface_result["rolls"]
        return result

    all_soft = set(room.soft_items or [])
    for eid in room.entities_present:
        ent = corpus.entities.get(eid)
        if ent and ent.soft_items:
            all_soft.update(ent.soft_items)
    if target in all_soft:
        # Determine where the soft item lives for surfacing
        surfaced: dict[str, list[str]] = {}
        if room.soft_items and target in room.soft_items:
            surfaced[room_id] = [target]
        else:
            for eid in room.entities_present:
                ent = corpus.entities.get(eid)
                if ent and ent.soft_items and target in ent.soft_items:
                    surfaced[eid] = [target]
                    break
        return ResolutionResult(
            success=True,
            hard_changes=HardStateChanges(),
            triggered_narration=[f"You examine the {target}."],
            room_after_id=room_id,
            surfaced_soft_items=surfaced,
        )

    return ResolutionResult(
        success=False,
        error=f"Target '{target}' not found in room '{room_id}' or your inventory",
    )


def resolve_move(
    action: MoveAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Current room '{room_id}' not found")

    target_exit_id = action.target
    exit_data = None
    for ex in room.exits:
        if ex.id == target_exit_id:
            exit_data = ex
            break

    if exit_data is None:
        return ResolutionResult(
            success=False,
            error=f"Exit '{target_exit_id}' not found in room '{room_id}'",
        )

    if exit_data.conditions:
        all_met = True
        unmet: list[str] = []
        for cond in exit_data.conditions:
            if not evaluate(cond, hard, soft, corpus):
                all_met = False
                unmet.append(str(cond))
        if not all_met:
            return ResolutionResult(
                success=False,
                error=f"Conditions not met for exit '{target_exit_id}'",
            )

    traversal_rolls: list[dict[str, Any]] = []
    result = ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=room_id,
    )
    _emit_event(
        "traversal.attempted",
        {
            "exit_id": target_exit_id,
            "from_room": room_id,
            "to_room": exit_data.target_room,
        },
        hard, soft, corpus, state_manager, result,
    )
    if exit_data.traversal_check:
        trav_check = exit_data.traversal_check
        should_check = True
        if trav_check.skip_check_if and evaluate(trav_check.skip_check_if, hard, soft, corpus):
            should_check = False
        elif trav_check.condition:
            should_check = evaluate(trav_check.condition, hard, soft, corpus)
        if should_check:
            traversal_narrative: list[str] = []
            traversal_changes = HardStateChanges()
            passed = _resolve_traversal_check(
                trav_check.check, hard, soft, corpus,
                traversal_changes, traversal_narrative, traversal_rolls,
                state_manager, result, target_exit_id,
            )
            if not passed:
                narrative_result = list(traversal_narrative)
                if trav_check.failure_narrative:
                    narrative_result.append(trav_check.failure_narrative)
                result.hard_changes = HardStateChanges()
                result.triggered_narration = narrative_result
                result.rolls = traversal_rolls
                _emit_event(
                    "traversal.failed",
                    {
                        "exit_id": target_exit_id,
                        "from_room": room_id,
                        "fail_reason": "check_failed",
                    },
                    hard, soft, corpus, state_manager, result,
                )
                return result

    changes = HardStateChanges(player_location=exit_data.target_room)
    narrative: list[str] = []
    encounter_trigger = None

    if exit_data.on_traverse:
        trav = exit_data.on_traverse
        skip = False
        if trav.skip_if and evaluate(trav.skip_if, hard, soft, corpus):
            skip = True
            if trav.narrative_skip:
                narrative.append(trav.narrative_skip)
        if not skip:
            if trav.narrative:
                narrative.append(trav.narrative)
            if trav.set_flag:
                for flag, val in trav.set_flag.items():
                    if val is True:
                        changes.flags_set[flag] = val
                    elif val is False:
                        changes.flags_cleared.append(flag)
                    else:
                        changes.flags_set[flag] = val
            if trav.set_room_state:
                for target_room_id, state_changes in trav.set_room_state.items():
                    changes.room_state_changes.setdefault(target_room_id, {}).update(state_changes)
            if trav.alter_stat:
                for stat_key, mod in trav.alter_stat.items():
                    if mod.mode == "set":
                        changes.stat_modifiers[stat_key] = mod
                    else:
                        existing = changes.stat_modifiers.get(stat_key)
                        if existing is not None and existing.mode == "set":
                            changes.stat_modifiers[stat_key] = StatModifier(
                                mode="set", value=existing.value + mod.value
                            )
                        else:
                            prev = existing.value if existing else 0
                            changes.stat_modifiers[stat_key] = StatModifier(
                                mode="delta", value=prev + mod.value
                            )
            if trav.trigger_encounter:
                encounter_trigger = trav.trigger_encounter

    room_states = hard.room_states.get(exit_data.target_room, {})
    one_way_from = room_states.get("_one_way_from", {})
    if one_way_from.get(room_id):
        return ResolutionResult(
            success=False,
            error=f"Reverse traversal of one-way exit from '{exit_data.target_room}' to '{room_id}' is blocked",
        )

    base_state = dict(room_states)
    base_state["visited"] = True
    if exit_data.one_way:
        base_state["_one_way_from"] = {**one_way_from, room_id: True}
    # Merge with any room state changes already accumulated (e.g., from on_traverse.set_room_state)
    existing_changes = changes.room_state_changes.get(exit_data.target_room, {})
    changes.room_state_changes[exit_data.target_room] = {**base_state, **existing_changes}

    # --- follower_blacklist: stop followers who refuse this room ---
    _check_follower_blacklist(hard, corpus, exit_data.target_room, narrative)

    result.hard_changes = changes
    result.triggered_narration = narrative
    result.encounter_trigger = encounter_trigger
    result.room_after_id = exit_data.target_room
    result.rolls = traversal_rolls
    _emit_event(
        "traversal.succeeded",
        {
            "exit_id": target_exit_id,
            "from_room": room_id,
            "to_room": exit_data.target_room,
        },
        hard, soft, corpus, state_manager, result,
    )
    return result


def resolve_talk(
    action: TalkAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    target_npc = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)

    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    follower_ids = get_following_npc_ids(hard, corpus)
    if target_npc not in room.entities_present and target_npc not in follower_ids:
        return ResolutionResult(
            success=False,
            error=f"NPC '{target_npc}' is not present in room '{room_id}'",
        )

    npc_entity = corpus.entities.get(target_npc)
    if npc_entity is None or npc_entity.type != "npc":
        return ResolutionResult(
            success=False,
            error=f"'{target_npc}' is not an NPC",
        )

    entity_state = hard.entity_states.get(target_npc, {})
    if entity_state.get("alive") is False:
        return ResolutionResult(
            success=False,
            error=f"NPC '{target_npc}' is dead",
        )

    # Validate dialogue path early so invalid paths prevent dialogue entry.
    path = None
    if action.dialogue_path and npc_entity.dialogue_guidelines:
        path = npc_entity.dialogue_guidelines.dialogue_paths.get(action.dialogue_path)
        if path is None:
            return ResolutionResult(
                success=False,
                error=f"Dialogue path '{action.dialogue_path}' not found for NPC '{target_npc}'",
            )
        if path.condition and not evaluate(path.condition, hard, soft, corpus):
            return ResolutionResult(
                success=False,
                error=f"Conditions not met for dialogue path '{action.dialogue_path}'",
            )

    turn = hard.turn_count
    dialogue_exited = None

    result = ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=room_id,
        dialogue_exited=dialogue_exited,
    )

    current_active = soft.dialogue_state.active_npc
    if current_active is not None and current_active != target_npc:
        dialogue_exited = exit_dialogue(soft, corpus, hard)
        _emit_event(
            "dialogue.ended",
            {"npc_id": current_active, "reason": "switched_npc"},
            hard, soft, corpus, state_manager, result,
        )

    if soft.dialogue_state.active_npc is None:
        enter_dialogue(soft, target_npc, turn, action.utterance, action.detail)
        _emit_event(
            "dialogue.started",
            {"npc_id": target_npc},
            hard, soft, corpus, state_manager, result,
        )
    else:
        append_player_turn(soft, target_npc, turn, action.utterance, action.detail)

    if action.ends_dialogue:
        dialogue_exited = exit_dialogue(soft, corpus, hard)
        _emit_event(
            "dialogue.ended",
            {"npc_id": target_npc, "reason": "ends_dialogue"},
            hard, soft, corpus, state_manager, result,
        )

    result.dialogue_exited = dialogue_exited

    # Resolve dialogue path check/result now that dialogue state is set up.
    # Passing *result* as the resolution accumulator ensures check events are
    # emitted and immediate reactions can fire.
    if path is not None:
        if path.check:
            synthetic_inter = Interaction(
                id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
                label="",
                check=path.check,
                success=path.success,
                failure=path.failure,
            )
            path_result = _resolve_interaction_check(
                synthetic_inter, hard, soft, corpus, room_id,
                state_manager=state_manager,
                resolution=result,
                source_type="dialogue_path",
            )
        elif path.result:
            path_result = _resolve_interaction_result(
                path.result, hard, soft, corpus, room_id,
                state_manager=state_manager,
                resolution=result,
            )
        else:
            path_result = ResolutionResult(
                success=True,
                hard_changes=HardStateChanges(),
                room_after_id=room_id,
            )

        result.hard_changes = path_result.hard_changes or HardStateChanges()
        result.triggered_narration.extend(path_result.triggered_narration or [])
        result.revealed_hints.extend(path_result.revealed_hints or [])
        result.rolls.extend(path_result.rolls or [])
        result.events.extend(path_result.events)

    return result


def resolve_transfer(
    action: TransferAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    target_id = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    target_is_room = target_id == room_id
    follower_ids = get_following_npc_ids(hard, corpus)
    target_is_entity = target_id in room.entities_present or target_id in follower_ids

    if not target_is_room and not target_is_entity:
        return ResolutionResult(
            success=False,
            error=f"Transfer target '{target_id}' not found in room '{room_id}'",
        )

    given_items = action.given_items or []
    taken_items = action.taken_items or []

    changes = HardStateChanges()
    soft_patches: list[SoftStatePatch] = []
    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        soft_patches=soft_patches,
        room_after_id=room_id,
    )

    for item in given_items:
        if item in hard.player.inventory:
            changes.inventory_removed.append(item)
            _emit_event(
                "item.lost",
                {"item_id": item, "reason": "transfer"},
                hard, soft, corpus, state_manager, result,
            )
        elif item in soft.soft_inventory:
            soft_patches.append(
                SoftStatePatch(
                    field="soft_inventory_remove",
                    new_value=item,
                    reason=f"Transfer: given to {target_id}",
                )
            )
        else:
            result.success = False
            result.error = f"Item '{item}' is not in your inventory"
            return result

    available_pool: set[str] = set()
    if target_is_room:
        for eid in room.entities_present:
            ent = corpus.entities.get(eid)
            if ent and ent.type == "item":
                available_pool.add(eid)
        room_soft = room.soft_items or []
        available_pool.update(room_soft)
    elif target_is_entity:
        target_ent = corpus.entities.get(target_id)
        if target_ent:
            if target_ent.type == "item":
                available_pool.add(target_id)
            if target_ent.soft_items:
                available_pool.update(target_ent.soft_items)
            if target_ent.contained_entities:
                available_pool.update(target_ent.contained_entities)
        # Fallback: add room-level items that are not nested inside any
        # other entity in the room (via contained_entities).
        claimed_entities: set[str] = set()
        for eid in room.entities_present:
            if eid == target_id:
                continue
            ent = corpus.entities.get(eid)
            if ent and ent.contained_entities:
                claimed_entities.update(ent.contained_entities)
        for eid in room.entities_present:
            ent = corpus.entities.get(eid)
            if ent and ent.type == "item" and eid not in claimed_entities:
                available_pool.add(eid)
        room_soft = room.soft_items or []
        available_pool.update(room_soft)

    surfaced: dict[str, list[str]] = {}
    triggered_narration: list[str] = []
    revealed_hints: list[str] = []
    rolls: list[dict[str, Any]] = []

    for item in taken_items:
        if item not in available_pool:
            return ResolutionResult(
                success=False,
                error=f"Item '{item}' is not available from '{target_id}'",
            )

        item_entity = corpus.entities.get(item)
        if item_entity and item_entity.take_check:
            synthetic = Interaction(
                id=f"take_{item}",
                label="",
                check=item_entity.take_check.check,
                success=item_entity.take_check.success,
                failure=item_entity.take_check.failure,
            )
            check_result = _resolve_interaction_check(
                synthetic, hard, soft, corpus, room_id
            )
            if not check_result.success:
                return check_result
            if check_result.hard_changes:
                changes.merge(check_result.hard_changes)
            if check_result.triggered_narration:
                triggered_narration.extend(check_result.triggered_narration)
            if check_result.revealed_hints:
                revealed_hints.extend(check_result.revealed_hints)
            if check_result.rolls:
                rolls.extend(check_result.rolls)

            check_succeeded = False
            for roll in check_result.rolls:
                if "success" in roll:
                    check_succeeded = roll["success"]
                    break
            if not check_succeeded:
                continue

        changes.inventory_added.append(item)
        _emit_event(
            "item.acquired",
            {"item_id": item, "source": "transfer"},
            hard, soft, corpus, state_manager, result,
        )
        # Surface the soft item on its source
        if target_is_room:
            if room.soft_items and item in room.soft_items:
                surfaced.setdefault(room_id, []).append(item)
            else:
                for eid in room.entities_present:
                    ent = corpus.entities.get(eid)
                    if ent and ent.soft_items and item in ent.soft_items:
                        surfaced.setdefault(eid, []).append(item)
                        break
        elif target_is_entity:
            target_ent = corpus.entities.get(target_id)
            if target_ent and target_ent.soft_items and item in target_ent.soft_items:
                surfaced.setdefault(target_id, []).append(item)

    # Given soft items: surface on the target (they now reside there)
    for item in given_items:
        if item in soft.soft_inventory:
            surfaced.setdefault(target_id, []).append(item)

    result.hard_changes = changes
    result.soft_patches = soft_patches
    result.surfaced_soft_items = surfaced
    result.triggered_narration = triggered_narration
    result.revealed_hints = revealed_hints
    result.rolls = rolls
    return result


def resolve_interact(
    action: InteractAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    target_id = action.target
    interaction_id = action.interaction_id
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    if action.using is not None:
        if (
            action.using not in hard.player.inventory
            and action.using not in hard.player.equipped
            and action.using not in soft.soft_inventory
        ):
            return ResolutionResult(
                success=False,
                error=f"Item '{action.using}' is not in your inventory",
            )

    target_entity = _find_entity_in_room_followers(target_id, room_id, room, hard, corpus)

    if target_entity is None:
        return ResolutionResult(
            success=False,
            error=f"Target '{target_id}' not found in room '{room_id}'",
        )

    matches: list[tuple[Interaction, str]] = []

    if target_entity:
        if target_entity.type == "npc" and target_entity.behavior:
            entity_state = hard.entity_states.get(target_id, {})
            if entity_state.get("alive") is False:
                return ResolutionResult(
                    success=False,
                    error=f"NPC '{target_id}' is dead",
                )
            if interaction_id in (target_entity.behavior.triggers_on or []):
                return ResolutionResult(
                    success=True,
                    hard_changes=HardStateChanges(),
                    encounter_trigger=target_id,
                    room_after_id=room_id,
                )

        # If NPC has a CombatBlock but no behavior trigger matched, and the
        # interaction is an attack, start combat directly.
        if interaction_id == "attack" and target_entity.combat is not None:
            from mgmai.engine.combat import enter_combat
            entry = enter_combat([target_id], hard, corpus)
            return ResolutionResult(
                success=True,
                hard_changes=entry["hard_changes"],
                combat_triggered=True,
                combat_log=entry["combat_log"],
                game_over_trigger="player_death" if entry["game_over"] else None,
                room_after_id=room_id,
            )

        for inter in target_entity.interactions:
            if inter.id == interaction_id:
                matches.append((inter, "entity"))

    for inter in room.interactions:
        if inter.id == interaction_id:
            matches.append((inter, "room"))

    if not matches:
        return ResolutionResult(
            success=False,
            error=f"Interaction '{interaction_id}' not found for target '{target_id}'",
        )

    inter, source = matches[0]

    # Base result that all return paths share.  interaction.used is emitted
    # here so immediate reactions can fire before the condition/check/result
    # is evaluated.
    result = ResolutionResult(
        success=False,
        error=f"Interaction '{interaction_id}' has no defined result",
        encounter_trigger=None,
        room_after_id=room_id,
    )
    _emit_event(
        "interaction.used",
        {
            "interaction_id": interaction_id,
            "target_id": target_id,
            "using_item": action.using,
        },
        hard, soft, corpus, state_manager, result,
    )

    # Check if any room NPC's behavior triggers on this interaction
    auto_encounter_npc: str | None = None
    for entity_id in room.entities_present:
        entity = corpus.entities.get(entity_id)
        if entity and entity.type == "npc" and entity.behavior:
            if interaction_id in (entity.behavior.triggers_on or []):
                entity_state = hard.entity_states.get(entity_id, {})
                if entity_state.get("alive") is not False and entity_state.get("fled") is not True:
                    auto_encounter_npc = entity_id
                    break

    if inter.condition and not evaluate(inter.condition, hard, soft, corpus):
        result.error = f"Conditions not met for interaction '{interaction_id}'"
        result.encounter_trigger = auto_encounter_npc
        return result

    if inter.parameter_signature:
        sig = inter.parameter_signature
        entity_types = {"player", "feature", "npc", "item"}
        if sig.target:
            target_type = target_entity.type if target_entity else "soft_item"
            allowed = set(sig.target)
            if target_type not in allowed and not (
                "entity" in allowed and target_type in entity_types
            ):
                result.error = f"Target type '{target_type}' not allowed for interaction '{interaction_id}' (expected: {sig.target})"
                result.encounter_trigger = auto_encounter_npc
                return result
        if sig.using and action.using:
            using_entity = corpus.entities.get(action.using)
            using_type = using_entity.type if using_entity else "soft_item"
            allowed_using = set(sig.using)
            if using_type not in allowed_using and not (
                "entity" in allowed_using and using_type in entity_types
            ):
                result.error = f"Using item type '{using_type}' not allowed for interaction '{interaction_id}' (expected: {sig.using})"
                result.encounter_trigger = auto_encounter_npc
                return result

    if inter.check:
        check_result = _resolve_interaction_check(inter, hard, soft, corpus, room_id, encounter_trigger=auto_encounter_npc, state_manager=state_manager, resolution=result)
        # Merge the base interaction event and any events/check results from
        # the check resolution into a single result.
        result.success = check_result.success
        result.error = check_result.error
        result.hard_changes = check_result.hard_changes
        result.triggered_narration = check_result.triggered_narration
        result.revealed_hints = check_result.revealed_hints
        result.encounter_trigger = check_result.encounter_trigger or auto_encounter_npc
        result.rolls = check_result.rolls
        result.events.extend(check_result.events)
        return result

    if inter.using_results and action.using:
        item_override = inter.using_results.get(action.using)
        if item_override is not None:
            override_result = _resolve_using_override(item_override, hard, soft, corpus, room_id, encounter_trigger=auto_encounter_npc, state_manager=state_manager, resolution=result)
            result.success = override_result.success
            result.error = override_result.error
            result.hard_changes = override_result.hard_changes
            result.triggered_narration = override_result.triggered_narration
            result.revealed_hints = override_result.revealed_hints
            result.encounter_trigger = override_result.encounter_trigger or auto_encounter_npc
            result.rolls = override_result.rolls
            result.events.extend(override_result.events)
            return result

    if inter.result:
        result_result = _resolve_interaction_result(inter.result, hard, soft, corpus, room_id, encounter_trigger=auto_encounter_npc, state_manager=state_manager, resolution=result)
        result.success = result_result.success
        result.error = result_result.error
        result.hard_changes = result_result.hard_changes
        result.triggered_narration = result_result.triggered_narration
        result.revealed_hints = result_result.revealed_hints
        result.encounter_trigger = result_result.encounter_trigger or auto_encounter_npc
        result.rolls = result_result.rolls
        result.events.extend(result_result.events)
        return result

    result.encounter_trigger = auto_encounter_npc
    return result


def _resolve_chained_check(
    chained: ChainedCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    rolls: list[dict[str, Any]],
    depth: int = 0,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
) -> None:
    if depth >= MAX_CHAIN_CHECK_DEPTH:
        return
    if source_type is None:
        source_type = "reaction" if source_id else "unknown"
    check = chained.check
    if isinstance(check, StatCheck):
        _resolve_stat_check_chain(
            check, chained.success, chained.failure,
            hard, soft, corpus, room_id,
            changes, narrative, revealed_hints, rolls, depth,
            state_manager, resolution, source_id, source_type,
        )
    else:
        _resolve_roll_check_chain(
            check, chained.success, chained.failure,
            hard, soft, corpus, room_id,
            changes, narrative, revealed_hints, rolls, depth,
            state_manager, resolution, source_id, source_type,
        )


def _resolve_roll_check_chain(
    check: RollCheck,
    success: Result,
    failure: Result | None,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    rolls: list[dict[str, Any]],
    depth: int,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
) -> None:
    if source_type is None:
        source_type = "reaction" if source_id else "unknown"
    roll_val = random.random()
    success_flag = roll_val < check.threshold

    branch = success if success_flag else failure
    result = branch if branch else None

    rolls.append({
        "threshold": check.threshold,
        "result": roll_val,
        "success": success_flag,
    })

    if resolution is not None:
        _emit_event(
            "check.passed" if success_flag else "check.failed",
            {
                "check_type": "roll",
                "threshold": check.threshold,
                "source_type": source_type,
                "source_id": source_id or "",
            },
            hard, soft, corpus, state_manager, resolution,
        )

    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus, soft, state_manager, resolution, source_id)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, depth + 1,
                state_manager, resolution, source_id, source_type,
            )


def _resolve_stat_check_chain(
    check: StatCheck,
    success: Result,
    failure: Result | None,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    rolls: list[dict[str, Any]],
    depth: int,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
) -> None:
    if source_type is None:
        source_type = "reaction" if source_id else "unknown"
    stats_block = corpus.stats
    if stats_block is None:
        return

    player_stats = hard.player.stats
    if player_stats is None or check.stat not in player_stats:
        return

    stat_value = player_stats[check.stat]
    res_system = stats_block.system
    if res_system != "5e":
        return

    from mgmai.engine.stat_checks import compute_5e_modifier, roll_d20

    computed_mod = compute_5e_modifier(stat_value)
    total_mod = computed_mod + check.modifier

    params = (check.resolution_params or {}).get("5e", {})
    advantage = params.get("advantage", False)
    disadvantage = params.get("disadvantage", False)

    raw_roll = roll_d20(advantage=advantage, disadvantage=disadvantage)

    total = raw_roll + total_mod
    success_flag = total >= check.dc

    branch = success if success_flag else failure
    result = branch if branch else None

    rolls.append({
        "type": "stat_check",
        "stat": check.stat,
        "dc": check.dc,
        "modifier": total_mod,
        "computed_mod": computed_mod,
        "flat_mod": check.modifier,
        "raw_roll": raw_roll,
        "total": total,
        "margin": total - check.dc,
        "success": success_flag,
        "advantage": advantage,
        "disadvantage": disadvantage,
    })

    if resolution is not None:
        _emit_event(
            "check.passed" if success_flag else "check.failed",
            {
                "check_type": "stat_check",
                "stat": check.stat,
                "dc": check.dc,
                "source_type": source_type,
                "source_id": source_id or "",
            },
            hard, soft, corpus, state_manager, resolution,
        )

    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus, soft, state_manager, resolution, source_id)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, depth + 1,
                state_manager, resolution, source_id, source_type,
            )


def _resolve_traversal_check(
    check: CheckType,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    changes: HardStateChanges,
    narrative: list[str],
    rolls: list[dict[str, Any]],
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str = "",
) -> bool:
    """Resolve a traversal check. Returns True if passed, False if failed."""
    if isinstance(check, StatCheck):
        stats_block = corpus.stats
        if stats_block is None:
            return True
        player_stats = hard.player.stats
        if player_stats is None or check.stat not in player_stats:
            return True
        stat_value = player_stats[check.stat]
        res_system = stats_block.system
        if res_system != "5e":
            return True

        from mgmai.engine.stat_checks import compute_5e_modifier, roll_d20

        computed_mod = compute_5e_modifier(stat_value)
        total_mod = computed_mod + check.modifier

        params = (check.resolution_params or {}).get("5e", {})
        advantage = params.get("advantage", False)
        disadvantage = params.get("disadvantage", False)

        raw_roll: int
        if advantage and not disadvantage:
            raw_roll = max(random.randint(1, 20), random.randint(1, 20))
        elif disadvantage and not advantage:
            raw_roll = min(random.randint(1, 20), random.randint(1, 20))
        else:
            raw_roll = random.randint(1, 20)

        total = raw_roll + total_mod
        success_flag = total >= check.dc

        rolls.append({
            "type": "stat_check",
            "traversal_check": True,
            "stat": check.stat,
            "dc": check.dc,
            "modifier": total_mod,
            "computed_mod": computed_mod,
            "flat_mod": check.modifier,
            "raw_roll": raw_roll,
            "total": total,
            "margin": total - check.dc,
            "success": success_flag,
            "advantage": advantage,
            "disadvantage": disadvantage,
        })

        if resolution is not None:
            _emit_event(
                "check.passed" if success_flag else "check.failed",
                {
                    "check_type": "stat_check",
                    "stat": check.stat,
                    "dc": check.dc,
                    "source_type": "traversal",
                    "source_id": source_id,
                },
                hard, soft, corpus, state_manager, resolution,
            )

        return success_flag
    else:
        roll_val = random.random()
        success_flag = roll_val < check.threshold
        rolls.append({
            "traversal_check": True,
            "threshold": check.threshold,
            "result": roll_val,
            "success": success_flag,
        })

        if resolution is not None:
            _emit_event(
                "check.passed" if success_flag else "check.failed",
                {
                    "check_type": "roll",
                    "threshold": check.threshold,
                    "source_type": "traversal",
                    "source_id": source_id,
                },
                hard, soft, corpus, state_manager, resolution,
            )

        return success_flag


def _resolve_interaction_check(
    inter: Interaction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_type: str = "interaction",
) -> ResolutionResult:
    check = inter.check
    if check is None:
        return ResolutionResult(success=False, error="Check defined but missing")

    # Non-repeatable gating (shared by both check types)
    if not check.repeatable:
        attempted = soft.checks_attempted.get(inter.id, [])
        if room_id in attempted:
            return ResolutionResult(
                success=False,
                error=f"Interaction '{inter.id}' has already been attempted and is not repeatable",
            )

    if isinstance(check, StatCheck):
        check_result = _resolve_stat_check(
            inter, check, hard, soft, corpus, room_id, encounter_trigger, source_type
        )
    else:
        check_result = _resolve_roll_check(
            inter, check, hard, soft, corpus, room_id, encounter_trigger, source_type
        )

    if resolution is not None and check_result.rolls:
        success_flag = any(r.get("success") for r in check_result.rolls)
        check_type = "stat_check" if isinstance(check, StatCheck) else "roll"
        ctx: dict[str, Any] = {
            "check_type": check_type,
            "source_type": source_type,
            "source_id": inter.id,
        }
        if isinstance(check, StatCheck):
            ctx["stat"] = check.stat
            ctx["dc"] = check.dc
        else:
            ctx["threshold"] = check.threshold
        _emit_event(
            "check.passed" if success_flag else "check.failed",
            ctx, hard, soft, corpus, state_manager, resolution,
        )

    return check_result


def _resolve_roll_check(
    inter: Interaction,
    check: RollCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    source_type: str = "interaction",
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
) -> ResolutionResult:
    roll = random.random()
    success_flag = roll < check.threshold

    branch = inter.success if success_flag else inter.failure
    result = branch if branch else inter.result

    changes = HardStateChanges()
    narrative: list[str] = []
    rolls: list[dict[str, Any]] = []

    if not check.repeatable:
        if inter.id not in soft.checks_attempted:
            soft.checks_attempted[inter.id] = []
        soft.checks_attempted[inter.id].append(room_id)

    rolls.append({
        "check_id": inter.id,
        "threshold": check.threshold,
        "result": roll,
        "success": success_flag,
    })

    revealed_hints: list[str] = []
    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, 0,
                state_manager, resolution, inter.id, source_type,
            )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls,
        encounter_trigger=encounter_trigger,
    )


def _resolve_stat_check(
    inter: Interaction,
    check: StatCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    source_type: str = "interaction",
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
) -> ResolutionResult:
    stats_block = corpus.stats
    if stats_block is None:
        return ResolutionResult(
            success=False, error="Adventure has no stats system defined"
        )

    player_stats = hard.player.stats
    if player_stats is None or check.stat not in player_stats:
        return ResolutionResult(
            success=False,
            error=f"Player has no '{check.stat}' stat",
        )

    stat_value = player_stats[check.stat]
    res_system = stats_block.system

    if res_system != "5e":
        return ResolutionResult(
            success=False,
            error=f"Unsupported resolution system: {res_system!r}",
        )

    from mgmai.engine.stat_checks import compute_5e_modifier, roll_d20

    computed_mod = compute_5e_modifier(stat_value)
    total_mod = computed_mod + check.modifier

    # advantage / disadvantage
    params = (check.resolution_params or {}).get("5e", {})
    advantage = params.get("advantage", False)
    disadvantage = params.get("disadvantage", False)

    raw_roll = roll_d20(advantage=advantage, disadvantage=disadvantage)

    total = raw_roll + total_mod
    success_flag = total >= check.dc

    branch = inter.success if success_flag else inter.failure
    result = branch if branch else inter.result

    if not check.repeatable:
        if inter.id not in soft.checks_attempted:
            soft.checks_attempted[inter.id] = []
        soft.checks_attempted[inter.id].append(room_id)

    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []

    rolls: list[dict[str, Any]] = [{
        "check_id": inter.id,
        "type": "stat_check",
        "stat": check.stat,
        "dc": check.dc,
        "modifier": total_mod,
        "computed_mod": computed_mod,
        "flat_mod": check.modifier,
        "raw_roll": raw_roll,
        "total": total,
        "margin": total - check.dc,
        "success": success_flag,
        "advantage": advantage,
        "disadvantage": disadvantage,
    }]

    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, 0,
                state_manager, resolution, inter.id, source_type,
            )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls,
        encounter_trigger=encounter_trigger,
    )


def _resolve_using_override(
    override: UsingResultOverride,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
) -> ResolutionResult:
    """Resolve a using_results override, which may carry its own check."""
    if override.check:
        # Build a synthetic Interaction from the override for check resolution
        synthetic_inter = Interaction(
            id="_using_override",
            label="",
            check=override.check,
            success=override.success,
            failure=override.failure,
        )
        return _resolve_interaction_check(synthetic_inter, hard, soft, corpus, room_id, encounter_trigger, state_manager, resolution)
    if override.result:
        return _resolve_interaction_result(override.result, hard, soft, corpus, room_id, encounter_trigger, state_manager, resolution)
    return ResolutionResult(
        success=False,
        error="UsingResultOverride has neither check nor result",
    )


def _resolve_interaction_result(
    result: Result,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
) -> ResolutionResult:
    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []

    _apply_result(result, changes, narrative, revealed_hints, hard, corpus)
    if result.chain_check:
        rolls: list[dict[str, Any]] = []
        _resolve_chained_check(
            result.chain_check, hard, soft, corpus, room_id,
            changes, narrative, revealed_hints, rolls, 0,
        )
        return ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=narrative,
            revealed_hints=revealed_hints,
            room_after_id=room_id,
            rolls=rolls,
            encounter_trigger=encounter_trigger,
        )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        encounter_trigger=encounter_trigger,
    )


def _apply_result(
    result: Result,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    hard: HardGameState | None = None,
    corpus: ModuleCorpus | None = None,
    soft: SoftGameState | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
) -> None:
    if result.narrative:
        narrative.append(result.narrative)
    if result.add_item:
        changes.inventory_added.append(result.add_item)
    if result.remove_item:
        changes.inventory_removed.append(result.remove_item)
    if result.set_flag:
        for flag, val in result.set_flag.items():
            if val is False:
                changes.flags_cleared.append(flag)
            else:
                changes.flags_set[flag] = val
    if result.alter_stat:
        for stat_key, mod in result.alter_stat.items():
            if mod.mode == "set":
                changes.stat_modifiers[stat_key] = mod
            else:
                existing = changes.stat_modifiers.get(stat_key)
                if existing is not None and existing.mode == "set":
                    changes.stat_modifiers[stat_key] = StatModifier(
                        mode="set", value=existing.value + mod.value
                    )
                else:
                    prev = existing.value if existing else 0
                    changes.stat_modifiers[stat_key] = StatModifier(
                        mode="delta", value=prev + mod.value
                    )
    if result.set_entity_state:
        for ent_id, state_changes in result.set_entity_state.items():
            changes.entity_state_changes.setdefault(ent_id, {}).update(state_changes)
    if result.set_room_state:
        for room_id, state_changes in result.set_room_state.items():
            changes.room_state_changes.setdefault(room_id, {}).update(state_changes)
    if result.adjust_attitude and hard is not None and corpus is not None:
        for npc_id, delta in result.adjust_attitude.items():
            npc_entity = corpus.entities.get(npc_id)
            if npc_entity is None or npc_entity.type != "npc":
                continue
            guidelines = npc_entity.dialogue_guidelines
            if guidelines is None:
                continue
            limits = guidelines.attitude_limits
            # Start from hard state, but respect any pending attitude change
            # already accumulated in *changes* this turn.
            pending = changes.entity_state_changes.get(npc_id, {})
            current = pending.get("attitude")
            if current is None:
                entity_state = hard.entity_states.get(npc_id, {})
                current = entity_state.get("attitude")
                if current is None:
                    current = limits.initial
            current = int(current)
            new_value = current + delta
            # Clamp to [min, max]
            new_value = max(limits.min, min(new_value, limits.max))
            # Respect step_per_turn
            if abs(new_value - current) > limits.step_per_turn:
                step = limits.step_per_turn
                if new_value > current:
                    new_value = current + step
                else:
                    new_value = current - step
                new_value = max(limits.min, min(new_value, limits.max))
            changes.entity_state_changes.setdefault(npc_id, {})["attitude"] = new_value
    if result.reveals:
        revealed_hints.append(result.reveals)
    if result.chain_check and hard is not None and corpus is not None and soft is not None:
        rolls: list[dict[str, Any]] = []
        _resolve_chained_check(
            result.chain_check, hard, soft, corpus,
            hard.player.location or "", changes, narrative, revealed_hints, rolls, 0,
            state_manager, resolution, source_id,
        )


def _find_entity_in_room(
    entity_id: str,
    room_id: str,
    room: Any,
    corpus: ModuleCorpus,
) -> Any | None:
    if entity_id in room.entities_present:
        return corpus.entities.get(entity_id)
    for eid in room.entities_present:
        ent = corpus.entities.get(eid)
        if ent and ent.spans_rooms and room_id in ent.spans_rooms:
            if eid == entity_id:
                return ent
    return None


def _find_entity_in_room_followers(
    entity_id: str,
    room_id: str,
    room: Any,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Any | None:
    """Like _find_entity_in_room but also matches following NPCs."""
    result = _find_entity_in_room(entity_id, room_id, room, corpus)
    if result is not None:
        return result
    follower_ids = get_following_npc_ids(hard, corpus)
    if entity_id in follower_ids:
        return corpus.entities.get(entity_id)
    return None


def _fire_on_examine_events(
    events: list[OnExamineEvent],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    action: Any,
    changes: HardStateChanges,
    narrative: list[str],
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
) -> dict[str, Any]:
    """Fire matching on_examine events for an entity or room being examined.

    Returns a dict with accumulated 'revealed_hints', 'surfaced', and 'rolls'.
    """
    revealed_hints: list[str] = []
    surfaced: dict[str, list[str]] = {}
    rolls: list[dict[str, Any]] = []

    for event in events:
        if event.condition and not evaluate(event.condition, hard, soft, corpus):
            continue
        if event.rigorous_only and not getattr(action, "rigorous", False):
            continue

        if event.check:
            # Build a synthetic Interaction for check resolution
            synthetic = Interaction(
                id=f"_on_examine_{event.id}",
                label="",
                check=event.check,
                success=event.success,
                failure=event.failure,
            )
            result = _resolve_interaction_check(synthetic, hard, soft, corpus, room_id, state_manager=state_manager, resolution=resolution, source_type="examine")
            if result.hard_changes:
                changes.merge(result.hard_changes)
            if result.triggered_narration:
                narrative.extend(result.triggered_narration)
            if result.revealed_hints:
                revealed_hints.extend(result.revealed_hints)
            if result.surfaced_soft_items:
                for k, v in result.surfaced_soft_items.items():
                    surfaced.setdefault(k, []).extend(v)
            if result.rolls:
                rolls.extend(result.rolls)
        elif event.result:
            _apply_result(event.result, changes, narrative, revealed_hints, hard, corpus)
            if event.result.chain_check:
                _resolve_chained_check(
                    event.result.chain_check, hard, soft, corpus, room_id,
                    changes, narrative, revealed_hints, rolls, 0,
                )

    return {
        "revealed_hints": revealed_hints,
        "surfaced": surfaced,
        "rolls": rolls,
    }


def _check_follower_blacklist(
    hard: HardGameState,
    corpus: ModuleCorpus,
    target_room: str,
    narrative: list[str],
) -> None:
    """Check if any following NPC refuses to enter the target room.

    If an NPC's follower_blacklist includes the target room, clear their
    ``following`` state and add a narrative note.
    """
    for eid, state in hard.entity_states.items():
        if not state.get("following"):
            continue
        entity = corpus.entities.get(eid)
        if entity is None:
            continue
        blacklist = entity.follower_blacklist or []
        if target_room in blacklist:
            state["following"] = False
            narrative.append(
                f"{entity.description.split('.')[0]} refuses to follow you "
                f"and stays behind."
            )


def _resolve_combat_action(
    action: CombatAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    """Resolve a CombatAction via the combat module."""
    from mgmai.engine.combat import resolve_combat_turn

    result = resolve_combat_turn(action, hard, corpus)
    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        game_over_trigger="player_death" if result["game_over"] else None,
        room_after_id=hard.player.location,
    )


def _resolve_combat_flee(
    action: MoveAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    """Resolve a flee attempt (move during combat) via the combat module."""
    from mgmai.engine.combat import resolve_combat_turn

    result = resolve_combat_turn(action, hard, corpus)
    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        room_after_id=(
            result["hard_changes"].player_location
            if result["hard_changes"] and result["hard_changes"].player_location
            else hard.player.location
        ),
    )


def resolve_equip(
    action: EquipAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve an equip action with tag conflict validation.

    Logic per plan.md §4a:
    0. Unequip targets first (atomically).
    1. Validate target in inventory.
    2. Look up EquipBlock from corpus.
    3. Reject if equip_block is None.
    4. Build incompatible tag set.
    5. Check each already-equipped item for conflicts.
    6. Check max_equipped for the primary tag group.
    7. On success: move from inventory to equipped.
    """
    target = action.target
    room_id = hard.player.location

    # Step 0: Validate and process unequip_targets
    for uid in action.unequip_targets:
        if uid not in hard.player.equipped:
            return ResolutionResult(
                success=False,
                error=f"Cannot unequip '{uid}': not currently equipped",
            )

    # Step 1: Validate target in inventory
    if target not in hard.player.inventory:
        return ResolutionResult(
            success=False,
            error=f"Item '{target}' is not in your inventory",
        )

    # Step 2-3: Look up EquipBlock
    item_entity = corpus.entities.get(target)
    if item_entity is None:
        return ResolutionResult(
            success=False,
            error=f"Item '{target}' not found in corpus",
        )
    eb = item_entity.equip_block
    if eb is None:
        return ResolutionResult(
            success=False,
            error=f"Item '{target}' cannot be equipped (no equip_block)",
        )

    # Build post-unequip state for conflict checking
    # (conceptually remove unequip_targets from equipped)
    still_equipped = [eid for eid in hard.player.equipped if eid not in action.unequip_targets]

    # Step 4: Build incompatible tags
    incompatible = set(eb.incompatible_with)
    if eb.two_handed:
        incompatible.update(["handwear", "weapon", "shield"])
    if not incompatible and eb.equip_tags:
        # Default: conflicts with items sharing the primary tag
        incompatible.add(eb.equip_tags[0])

    # Step 5: Check conflicts with already-equipped items
    for eid in still_equipped:
        eq_entity = corpus.entities.get(eid)
        if eq_entity is None or eq_entity.equip_block is None:
            continue
        eq_tags = set(eq_entity.equip_block.equip_tags)
        if eq_tags & incompatible:
            return ResolutionResult(
                success=False,
                error=f"Cannot equip '{target}': conflicts with equipped item '{eid}' "
                      f"(tags: {eq_tags & incompatible})",
            )

    # Step 6: Check max_equipped
    if eb.equip_tags:
        primary_tag = eb.equip_tags[0]
        # Collect max_equipped from all items sharing this primary tag
        max_limit = eb.max_equipped
        for eid in still_equipped:
            eq_entity = corpus.entities.get(eid)
            if eq_entity and eq_entity.equip_block:
                if eq_entity.equip_block.equip_tags and eq_entity.equip_block.equip_tags[0] == primary_tag:
                    other_max = eq_entity.equip_block.max_equipped
                    if other_max is None:
                        max_limit = None
                    elif max_limit is not None:
                        max_limit = max(max_limit, other_max)
        if max_limit is not None:
            current_count = sum(
                1 for eid in still_equipped
                if (_e := corpus.entities.get(eid)) and _e.equip_block
                and _e.equip_block.equip_tags and _e.equip_block.equip_tags[0] == primary_tag
            )
            if current_count >= max_limit:
                return ResolutionResult(
                    success=False,
                    error=f"Cannot equip '{target}': tag '{primary_tag}' limit "
                          f"({max_limit}) would be exceeded (currently {current_count})",
                )

    # Step 7: Success — move target from inventory to equipped
    changes = HardStateChanges()
    changes.inventory_removed.append(target)
    changes.equipped_added.append(target)
    for uid in action.unequip_targets:
        changes.equipped_removed.append(uid)
        changes.inventory_added.append(uid)
    changes.equipment_changed = True

    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=room_id,
    )
    _emit_event(
        "equipment.changed",
        {"added": [target], "removed": action.unequip_targets},
        hard, soft, corpus, state_manager, result,
    )
    return result


def resolve_unequip(
    action: UnequipAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve an unequip action per plan.md §4b."""
    target = action.target
    room_id = hard.player.location

    # Validate target is equipped
    if target not in hard.player.equipped:
        return ResolutionResult(
            success=False,
            error=f"Item '{target}' is not currently equipped",
        )

    changes = HardStateChanges()
    changes.equipped_removed.append(target)
    changes.inventory_added.append(target)
    changes.equipment_changed = True

    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=room_id,
    )
    _emit_event(
        "equipment.changed",
        {"removed": [target]},
        hard, soft, corpus, state_manager, result,
    )
    return result


def resolve_action(
    action: Any,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Dispatch a PlayerAction to the appropriate resolver."""
    action_type = action.action_type

    # During combat, move actions become flee attempts
    if action_type == "move" and hard.combat is not None and hard.combat.active:
        return _resolve_combat_flee(action, hard, corpus)

    if action_type == "move":
        return resolve_move(action, hard, soft, corpus, state_manager)
    elif action_type == "examine":
        return resolve_examine(action, hard, soft, corpus, state_manager)
    elif action_type == "interact":
        return resolve_interact(action, hard, soft, corpus, state_manager)
    elif action_type == "talk":
        return resolve_talk(action, hard, soft, corpus, state_manager)
    elif action_type == "transfer":
        return resolve_transfer(action, hard, soft, corpus, state_manager)
    elif action_type == "combat":
        return _resolve_combat_action(action, hard, corpus)
    elif action_type == "wait":
        return resolve_wait(action, hard, soft, corpus)
    elif action_type == "equip":
        return resolve_equip(action, hard, soft, corpus, state_manager)
    elif action_type == "unequip":
        return resolve_unequip(action, hard, soft, corpus, state_manager)
    elif action_type == "ooc_discussion":
        return resolve_ooc(action, hard, soft, corpus)
    else:
        return ResolutionResult(
            success=False,
            error=f"Unknown action type: {action_type}",
        )
