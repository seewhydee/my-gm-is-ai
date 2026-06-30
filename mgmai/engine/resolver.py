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
    CheckResolution,
    GatedCheck,
    Interaction,
    ModuleCorpus,
    OnExamineEvent,
    Result,
    RollCheck,
    StatCheck,
    StatModifier,
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
from mgmai.engine.systems import get_system_for_corpus

MAX_THEN_CHECK_DEPTH = 3

log = logging.getLogger(__name__)


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
        rolls=resolution.rolls,
        combat_log=resolution.combat_log,
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
    warnings: list[str] = field(default_factory=list)
    room_after_id: str | None = None
    dialogue_exited: DialogueExitedResult | dict | None = None
    soft_patches: list[SoftStatePatch] = field(default_factory=list)
    rolls: list[dict[str, Any]] = field(default_factory=list)
    surfaced_soft_items: dict[str, list[str]] = field(default_factory=dict)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    immediate_changes: HardStateChanges = field(default_factory=HardStateChanges)
    costs_turn: bool = True


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
        return ResolutionResult(
            success=False,
            error=f"Current room '{room_id}' not found in corpus",
            costs_turn=False,
        )

    if action.using is not None:
        if (
            action.using not in hard.player.inventory
            and action.using not in hard.player.equipped
            and action.using not in soft.soft_inventory
        ):
            return ResolutionResult(
                success=False,
                error=f"Item '{action.using}' is not in your inventory",
                costs_turn=False,
            )

    if target == room_id:
        changes = HardStateChanges()
        base_narrative = [room.description]
        result = ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=base_narrative,
            room_after_id=room_id,
            costs_turn=action.rigorous,
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
            costs_turn=action.rigorous,
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
    for eid in room.contains:
        ent = corpus.entities.get(eid)
        if ent and ent.soft_items:
            all_soft.update(ent.soft_items)
    if target in all_soft:
        # Determine where the soft item lives for surfacing
        surfaced: dict[str, list[str]] = {}
        if room.soft_items and target in room.soft_items:
            surfaced[room_id] = [target]
        else:
            for eid in room.contains:
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
            costs_turn=action.rigorous,
        )

    return ResolutionResult(
        success=False,
        error=f"Target '{target}' not found in room '{room_id}' or your inventory",
        costs_turn=False,
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

    if exit_data.condition is not None:
        if not evaluate(exit_data.condition, hard, soft, corpus):
            return ResolutionResult(
                success=False,
                error=f"Condition not met for exit '{target_exit_id}'",
            )

    traversal_rolls: list[dict[str, Any]] = []
    traversal_changes = HardStateChanges()
    traversal_narrative: list[str] = []
    traversal_hints: list[str] = []
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
        if trav_check.gating and not evaluate(trav_check.gating, hard, soft, corpus):
            should_check = False  # inactive: traversal proceeds, no result applied
        elif trav_check.skip_check_if and evaluate(trav_check.skip_check_if, hard, soft, corpus):
            should_check = False  # bypassed: apply success Result if present
            if trav_check.success:
                _apply_result_with_check(
                    trav_check.success,
                    changes=traversal_changes, narrative=traversal_narrative,
                    revealed_hints=traversal_hints, hard=hard, corpus=corpus,
                    soft=soft, room_id=room_id, rolls=traversal_rolls,
                    state_manager=state_manager, resolution=result,
                    source_id=target_exit_id, source_type="traversal",
                    item_origin="traversal",
                )
        if should_check:
            # Resolve using_results overrides (weapon-based DC reduction, etc.)
            effective_check = trav_check.check
            using_override: UsingResultOverride | None = None
            using_item = getattr(action, "using", None)
            if trav_check.using_results and using_item:
                for item_id, override in trav_check.using_results.items():
                    if item_id == using_item or item_id == "*":
                        using_override = override
                        break
                if using_override is not None and using_override.check is not None:
                    effective_check = using_override.check

            passed = _resolve_traversal_check(
                effective_check, hard, soft, corpus,
                traversal_changes, traversal_narrative, traversal_rolls,
                state_manager, result, target_exit_id,
            )
            if not passed:
                if trav_check.failure:
                    _apply_result_with_check(
                        trav_check.failure,
                        changes=traversal_changes, narrative=traversal_narrative,
                        revealed_hints=traversal_hints, hard=hard, corpus=corpus,
                        soft=soft, room_id=room_id, rolls=traversal_rolls,
                        state_manager=state_manager, resolution=result,
                        source_id=target_exit_id, source_type="traversal",
                        item_origin="traversal",
                    )
                result.hard_changes = traversal_changes
                result.triggered_narration = list(traversal_narrative)
                result.revealed_hints = list(traversal_hints)
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
            # Traversal succeeded: apply success Result (including any then_check)
            if trav_check.success:
                _apply_result_with_check(
                    trav_check.success,
                    changes=traversal_changes, narrative=traversal_narrative,
                    revealed_hints=traversal_hints, hard=hard, corpus=corpus,
                    soft=soft, room_id=exit_data.target_room,
                    rolls=traversal_rolls,
                    state_manager=state_manager, resolution=result,
                    source_id=target_exit_id, source_type="traversal",
                    item_origin="traversal",
                )

    changes = HardStateChanges(player_location=exit_data.target_room)
    if exit_data.traversal_check:
        changes.merge(traversal_changes)
    narrative: list[str] = list(traversal_narrative)

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
    existing_changes = changes.room_state_changes.get(exit_data.target_room, {})
    changes.room_state_changes[exit_data.target_room] = {**base_state, **existing_changes}

    # --- follower_blacklist: stop followers who refuse this room ---
    _check_follower_blacklist(hard, corpus, exit_data.target_room, narrative)

    result.hard_changes = changes
    result.triggered_narration = narrative
    result.revealed_hints = traversal_hints
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
    if target_npc not in room.contains and target_npc not in follower_ids:
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
            # Handle skip_check_if: bypass check and apply success Result
            if path.skip_check_if and evaluate(path.skip_check_if, hard, soft, corpus):
                if path.success:
                    path_result = _resolve_interaction_result(
                        path.success, hard, soft, corpus, room_id,
                        state_manager=state_manager,
                        resolution=result,
                        source_id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
                        source_type="dialogue_path",
                    )
                else:
                    path_result = ResolutionResult(
                        success=True,
                        hard_changes=HardStateChanges(),
                        room_after_id=room_id,
                    )
            else:
                synthetic_inter = Interaction(
                    id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
                    description="",
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
                source_id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
                source_type="dialogue_path",
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


def _container_is_open(entity_id: str, hard: HardGameState, corpus: ModuleCorpus) -> bool:
    """Return True if the entity is not a container, or if it is a container
    and its hard-state ``open`` is ``true``.  Return False if it is a
    container and ``open`` is ``false``, ``None``, or absent.

    An entity is only treated as a gated container when it has the
    ``container`` tag AND ``open`` is declared in its state_fields.
    Without ``open`` declared, a ``container``-tagged entity is
    default-open (contents always accessible)."""
    ent = corpus.entities.get(entity_id)
    if ent is None:
        return True
    if "container" not in ent.tags:
        return True
    if "open" not in ent.state_fields:
        return True
    return hard.entity_states.get(entity_id, {}).get("open") is True


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
    target_is_entity = target_id in room.contains or target_id in follower_ids

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
            changes.inventory_removed_reasons[item] = "transfer"
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
        for eid in room.contains:
            ent = corpus.entities.get(eid)
            if ent and ent.type == "item":
                available_pool.add(eid)
            if ent and ent.contains:
                if _container_is_open(eid, hard, corpus):
                    for cid in ent.contains:
                        cstate = hard.entity_states.get(cid, {})
                        if not cstate.get("hidden", False):
                            available_pool.add(cid)
            if ent and ent.soft_items:
                if _container_is_open(eid, hard, corpus):
                    available_pool.update(ent.soft_items)
        room_soft = room.soft_items or []
        available_pool.update(room_soft)
    elif target_is_entity:
        target_ent = corpus.entities.get(target_id)
        if target_ent:
            if target_ent.type == "item":
                available_pool.add(target_id)
            if _container_is_open(target_id, hard, corpus):
                if target_ent.soft_items:
                    available_pool.update(target_ent.soft_items)
                if target_ent.contains:
                    available_pool.update(target_ent.contains)
        # Fallback: add room-level items that are not nested inside any
        # other entity in the room (via contains).
        claimed_entities: set[str] = set()
        for eid in room.contains:
            if eid == target_id:
                continue
            ent = corpus.entities.get(eid)
            if ent and ent.contains:
                claimed_entities.update(ent.contains)
        for eid in room.contains:
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
            closed_error: str | None = None
            if target_is_entity:
                target_ent = corpus.entities.get(target_id)
                if target_ent and not _container_is_open(target_id, hard, corpus):
                    if item in target_ent.contains or item in target_ent.soft_items:
                        closed_error = f"The {target_ent.name or target_id} is closed."
            else:
                for eid in room.contains:
                    ent = corpus.entities.get(eid)
                    if ent and not _container_is_open(eid, hard, corpus):
                        if item in ent.contains or (ent.soft_items and item in ent.soft_items):
                            closed_error = f"The {ent.name or eid} is closed."
                            break
            if closed_error is not None:
                return ResolutionResult(
                    success=False,
                    error=closed_error,
                )
            return ResolutionResult(
                success=False,
                error=f"Item '{item}' is not available from '{target_id}'",
            )

        item_entity = corpus.entities.get(item)
        if item_entity and item_entity.take_check:
            tc = item_entity.take_check
            if tc.gating and not evaluate(tc.gating, hard, soft, corpus):
                pass  # inactive: item taken freely, no result applied
            else:
                # _resolve_checkable handles skip_check_if (apply success) and
                # the roll (apply success/failure). Returns True if passed/bypassed.
                # Clear any stale error so an unresolvable check can be detected.
                if result.error is not None:
                    result.error = None
                passed = _resolve_checkable(
                    tc,
                    hard=hard, soft=soft, corpus=corpus, room_id=room_id,
                    changes=changes, narrative=triggered_narration,
                    revealed_hints=revealed_hints, rolls=rolls,
                    state_manager=state_manager, resolution=result,
                    source_id=f"take_{item}", source_type="take",
                    item_origin="take",
                    track_attempts=True, attempt_key=f"take_{item}",
                )
                if not passed:
                    if result.error:
                        # Unresolvable check (missing stats, etc.) — abort transfer
                        return ResolutionResult(
                            success=False, error=result.error,
                            hard_changes=changes, room_after_id=room_id,
                            rolls=rolls, triggered_narration=triggered_narration,
                            revealed_hints=revealed_hints,
                        )
                    continue  # check failed: item not taken

        changes.inventory_added.append(item)
        changes.inventory_added_sources[item] = "transfer"
        # Surface the soft item on its source
        if target_is_room:
            if room.soft_items and item in room.soft_items:
                surfaced.setdefault(room_id, []).append(item)
            else:
                for eid in room.contains:
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

        # If NPC has a CombatBlock and the interaction is an attack, start
        # combat directly.
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

        # Attacking an NPC always triggers an encounter.  If the NPC has an
        # explicit "attack" interaction defined, that interaction takes
        # precedence and is resolved below.  Otherwise, set an encounter
        # trigger so the engine dispatches it (using behavior.encounter_rules
        # if present, or a default "NPC dies" outcome).
        if (
            interaction_id == "attack"
            and target_entity.type == "npc"
            and not any(inter.id == "attack" for inter in target_entity.interactions)
        ):
            result = ResolutionResult(
                success=True,
                encounter_trigger=target_id,
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
            return result

        for inter in target_entity.interactions:
            if inter.id == interaction_id:
                matches.append((inter, "entity"))

    for inter in room.interactions:
        if inter.id == interaction_id:
            matches.append((inter, "room"))

    # Emit interaction.used before matching so entity-scoped reactions
    # fire for effects (set_flag, narrative, etc.) even when no
    # interaction definition exists.
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

    if not matches:
        return result

    inter, source = matches[0]

    if inter.condition and not evaluate(inter.condition, hard, soft, corpus):
        result.error = f"Conditions not met for interaction '{interaction_id}'"
        return result

    if inter.check:
        # Handle skip_check_if: bypass check and apply success Result
        if inter.skip_check_if and evaluate(inter.skip_check_if, hard, soft, corpus):
            if inter.success:
                skip_result = _resolve_interaction_result(
                    inter.success, hard, soft, corpus, room_id,
                    encounter_trigger=None, state_manager=state_manager,
                    resolution=result, source_id=inter.id, source_type="interaction",
                )
                result.success = skip_result.success
                result.error = skip_result.error
                result.hard_changes = skip_result.hard_changes
                result.triggered_narration = skip_result.triggered_narration
                result.revealed_hints = skip_result.revealed_hints
                result.encounter_trigger = skip_result.encounter_trigger or result.encounter_trigger
                result.rolls = skip_result.rolls
                result.events.extend(skip_result.events)
            return result
        check_result = _resolve_interaction_check(inter, hard, soft, corpus, room_id, encounter_trigger=None, state_manager=state_manager, resolution=result)
        # Merge the base interaction event and any events/check results from
        # the check resolution into a single result.
        result.success = check_result.success
        result.error = check_result.error
        result.hard_changes = check_result.hard_changes
        result.triggered_narration = check_result.triggered_narration
        result.revealed_hints = check_result.revealed_hints
        result.encounter_trigger = check_result.encounter_trigger or result.encounter_trigger
        result.rolls = check_result.rolls
        result.events.extend(check_result.events)
        return result

    if inter.using_results and action.using:
        item_override = inter.using_results.get(action.using)
        if item_override is not None:
            override_result = _resolve_using_override(item_override, hard, soft, corpus, room_id, encounter_trigger=None, state_manager=state_manager, resolution=result, source_id=inter.id, source_type="interaction")
            result.success = override_result.success
            result.error = override_result.error
            result.hard_changes = override_result.hard_changes
            result.triggered_narration = override_result.triggered_narration
            result.revealed_hints = override_result.revealed_hints
            result.encounter_trigger = override_result.encounter_trigger or result.encounter_trigger
            result.rolls = override_result.rolls
            result.events.extend(override_result.events)
            return result

    if inter.result:
        result_result = _resolve_interaction_result(inter.result, hard, soft, corpus, room_id, encounter_trigger=None, state_manager=state_manager, resolution=result, source_id=inter.id, source_type="interaction")
        result.success = result_result.success
        result.error = result_result.error
        result.hard_changes = result_result.hard_changes
        result.triggered_narration = result_result.triggered_narration
        result.revealed_hints = result_result.revealed_hints
        result.encounter_trigger = result_result.encounter_trigger or result.encounter_trigger
        result.rolls = result_result.rolls
        result.events.extend(result_result.events)
        return result

    return result


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

        system = get_system_for_corpus(corpus)
        cr = system.roll_check(
            check.stat,
            player_stats[check.stat],
            check.target,
            flat_modifier=check.modifier,
            params=check.model_extra or {},
        )

        roll_dict = cr.to_dict()
        roll_dict["source_id"] = source_id
        roll_dict["source_type"] = "traversal"
        roll_dict["check_type"] = "stat_check"
        roll_dict["traversal_check"] = True
        rolls.append(roll_dict)

        if resolution is not None:
            _emit_event(
                "check.passed" if cr.success else "check.failed",
                {
                    "check_type": "stat_check",
                    "stat": check.stat,
                    "target": check.target,
                    "source_type": "traversal",
                    "source_id": source_id,
                },
                hard, soft, corpus, state_manager, resolution,
            )

        return cr.success
    else:
        roll_val = random.random()
        success_flag = roll_val < check.threshold
        rolls.append({
            "source_id": source_id,
            "source_type": "traversal",
            "check_type": "roll",
            "threshold": check.threshold,
            "result": roll_val,
            "success": success_flag,
            "traversal_check": True,
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

    # Clear any stale error on the accumulator so we can use it as a signal
    # from _resolve_checkable for genuinely unresolvable checks.
    if resolution is not None:
        resolution.error = None

    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []
    rolls: list[dict[str, Any]] = []

    passed = _resolve_checkable(
        inter,
        hard=hard, soft=soft, corpus=corpus, room_id=room_id,
        changes=changes, narrative=narrative,
        revealed_hints=revealed_hints, rolls=rolls,
        state_manager=state_manager, resolution=resolution,
        source_id=inter.id, source_type=source_type,
        track_attempts=True, attempt_key=inter.id,
    )

    # A False return with an error set means the check could not be resolved
    # (missing stats, or a non-repeatable check already attempted). A normal
    # failed roll or depth-capped then_check returns False with no error.
    if not passed and resolution is not None and resolution.error:
        return ResolutionResult(
            success=False,
            error=resolution.error,
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
    source_id: str | None = None,
    source_type: str = "interaction",
) -> ResolutionResult:
    """Resolve a using_results override, which may carry its own check."""
    if override.check:
        # Build a synthetic Interaction from the override for check resolution
        synthetic_inter = Interaction(
            id=source_id or "_using_override",
            description="",
            check=override.check,
            success=override.success,
            failure=override.failure,
        )
        return _resolve_interaction_check(synthetic_inter, hard, soft, corpus, room_id, encounter_trigger, state_manager, resolution, source_type)
    if override.result:
        return _resolve_interaction_result(override.result, hard, soft, corpus, room_id, encounter_trigger, state_manager, resolution, source_id, source_type)
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
    source_id: str | None = None,
    source_type: str = "interaction",
) -> ResolutionResult:
    changes = HardStateChanges()
    narrative: list[str] = []
    revealed_hints: list[str] = []
    rolls: list[dict[str, Any]] = []

    _apply_result_with_check(
        result,
        changes=changes, narrative=narrative,
        revealed_hints=revealed_hints, hard=hard, corpus=corpus,
        soft=soft, room_id=room_id, rolls=rolls,
        state_manager=state_manager, resolution=resolution,
        source_id=source_id, source_type=source_type,
    )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls if rolls else None,
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
    item_origin: str = "interaction",
) -> None:
    if result.narrative:
        narrative.append(result.narrative)
    if result.add_item:
        for item_id in result.add_item:
            changes.inventory_added.append(item_id)
            changes.inventory_added_sources[item_id] = item_origin
    if result.remove_item:
        for item_id in result.remove_item:
            changes.inventory_removed.append(item_id)
            changes.inventory_removed_reasons[item_id] = item_origin
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
    if result.set_player_location is not None:
        changes.player_location = result.set_player_location
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
    if result.player_damage and corpus is not None:
        system = get_system_for_corpus(corpus)
        dmg_total, _ = system.roll_damage(result.player_damage)
        existing = changes.player_hp_delta or 0
        changes.player_hp_delta = existing - dmg_total
    if result.reveals:
        revealed_hints.append(result.reveals)


def _apply_result_with_check(
    result: Result,
    *,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    rolls: list[dict[str, Any]],
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_id: str | None = None,
    source_type: str | None = None,
    then_check_depth: int = 0,
    item_origin: str = "interaction",
) -> None:
    _apply_result(result, changes, narrative, revealed_hints,
                  hard, corpus, soft, state_manager, resolution,
                  source_id, item_origin)
    if result.then_check:
        _resolve_checkable(
            result.then_check,
            hard=hard, soft=soft, corpus=corpus, room_id=room_id,
            changes=changes, narrative=narrative,
            revealed_hints=revealed_hints, rolls=rolls,
            depth=then_check_depth,
            state_manager=state_manager, resolution=resolution,
            source_id=source_id, source_type=source_type,
        )


def _resolve_checkable(
    chk: CheckResolution | Interaction | OnExamineEvent | GatedCheck,
    *,
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
    item_origin: str = "interaction",
    track_attempts: bool = False,
    attempt_key: str | None = None,
) -> bool:
    """Resolve a Checkable's check, apply the chosen branch, recurse into
    any then_check. Returns True if the check passed or was skipped."""
    if depth >= MAX_THEN_CHECK_DEPTH:
        log.warning(
            "then_check recursion stopped at depth %d (MAX_THEN_CHECK_DEPTH)",
            MAX_THEN_CHECK_DEPTH,
        )
        return False

    if chk.skip_check_if and evaluate(chk.skip_check_if, hard, soft, corpus):
        if chk.success:
            _apply_result_with_check(
                chk.success,
                changes=changes, narrative=narrative,
                revealed_hints=revealed_hints, hard=hard, corpus=corpus,
                soft=soft, room_id=room_id, rolls=rolls,
                state_manager=state_manager, resolution=resolution,
                source_id=source_id, source_type=source_type,
                then_check_depth=depth + 1,
                item_origin=item_origin,
            )
        return True

    check = getattr(chk, "check", None)
    if check is None:
        return False

    if track_attempts and not check.repeatable and attempt_key:
        attempted = soft.checks_attempted.get(attempt_key, [])
        if room_id in attempted:
            if resolution is not None:
                resolution.error = (
                    f"Interaction '{attempt_key}' has already been attempted "
                    "and is not repeatable"
                )
            return False

    if isinstance(check, StatCheck):
        stats_block = corpus.stats
        if stats_block is None:
            if resolution is not None:
                resolution.error = "Adventure has no stats system defined"
            return False
        player_stats = hard.player.stats
        if player_stats is None or check.stat not in player_stats:
            if resolution is not None:
                resolution.error = f"Player has no '{check.stat}' stat"
            return False
        system = get_system_for_corpus(corpus)
        cr = system.roll_check(
            check.stat,
            player_stats[check.stat],
            check.target,
            flat_modifier=check.modifier,
            params=check.model_extra or {},
        )
        success_flag = cr.success
        roll_dict: dict[str, Any] = {
            "source_id": source_id or "",
            "source_type": source_type or "",
            "check_type": "stat_check",
            "stat": check.stat,
            "target": check.target,
        }
        roll_dict.update(cr.to_dict())
        rolls.append(roll_dict)
    else:
        roll_val = random.random()
        success_flag = roll_val < check.threshold
        rolls.append({
            "source_id": source_id or "",
            "source_type": source_type or "",
            "check_type": "roll",
            "threshold": check.threshold,
            "result": roll_val,
            "success": success_flag,
        })

    if resolution is not None:
        ctx: dict[str, Any] = {
            "check_type": "stat_check" if isinstance(check, StatCheck) else "roll",
            "source_type": source_type or "",
            "source_id": source_id or "",
        }
        if isinstance(check, StatCheck):
            ctx["stat"] = check.stat
            ctx["target"] = check.target
        else:
            ctx["threshold"] = check.threshold
        _emit_event(
            "check.passed" if success_flag else "check.failed",
            ctx, hard, soft, corpus, state_manager, resolution,
        )

    if track_attempts and not check.repeatable and attempt_key:
        if attempt_key not in soft.checks_attempted:
            soft.checks_attempted[attempt_key] = []
        soft.checks_attempted[attempt_key].append(room_id)

    branch = getattr(chk, "success", None) if success_flag else getattr(chk, "failure", None)
    if branch:
        _apply_result_with_check(
            branch,
            changes=changes, narrative=narrative,
            revealed_hints=revealed_hints, hard=hard, corpus=corpus,
            soft=soft, room_id=room_id, rolls=rolls,
            state_manager=state_manager, resolution=resolution,
            source_id=source_id, source_type=source_type,
            then_check_depth=depth + 1,
            item_origin=item_origin,
        )

    return success_flag


def _find_entity_in_room(
    entity_id: str,
    room: Any,
    corpus: ModuleCorpus,
) -> Any | None:
    if entity_id in room.contains:
        return corpus.entities.get(entity_id)
    return None


def _find_entity_in_room_followers(
    entity_id: str,
    room_id: str,
    room: Any,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Any | None:
    """Like _find_entity_in_room but also matches following NPCs."""
    result = _find_entity_in_room(entity_id, room, corpus)
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
            # Handle skip_check_if: bypass check and apply success Result
            if event.skip_check_if and evaluate(event.skip_check_if, hard, soft, corpus):
                if event.success:
                    _apply_result_with_check(
                        event.success,
                        changes=changes, narrative=narrative,
                        revealed_hints=revealed_hints, hard=hard, corpus=corpus,
                        soft=soft, room_id=room_id, rolls=rolls,
                        state_manager=state_manager, resolution=resolution,
                        source_id=f"_on_examine_{event.id}",
                        source_type="examine",
                        item_origin="examine",
                    )
                continue
            # Build a synthetic Interaction for check resolution
            synthetic = Interaction(
                id=f"_on_examine_{event.id}",
                description="",
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
            _apply_result_with_check(
                event.result,
                changes=changes, narrative=narrative,
                revealed_hints=revealed_hints, hard=hard, corpus=corpus,
                soft=soft, room_id=room_id, rolls=rolls,
                state_manager=state_manager, resolution=resolution,
                source_id=f"_on_examine_{event.id}",
                source_type="examine",
                item_origin="examine",
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
    changes.inventory_removed_reasons[target] = "equip"
    changes.equipped_added.append(target)
    for uid in action.unequip_targets:
        changes.equipped_removed.append(uid)
        changes.inventory_added.append(uid)
        changes.inventory_added_sources[uid] = "unequip"
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
    changes.inventory_added_sources[target] = "unequip"
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
