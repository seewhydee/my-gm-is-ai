from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional

from mgmai.models.actions import (
    ExamineAction,
    HardStateChanges,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    TalkAction,
    TransferAction,
    WaitAction,
)
from mgmai.models.corpus import (
    Check,
    Interaction,
    ModuleCorpus,
    Result,
)
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch
from mgmai.engine.conditions import evaluate
from mgmai.engine.dialogue import (
    append_player_turn,
    enter_dialogue,
    exit_dialogue,
)


@dataclass
class ResolutionResult:
    success: bool
    error: str | None = None
    hard_changes: HardStateChanges | None = None
    triggered_narration: list[str] = field(default_factory=list)
    encounter_trigger: str | None = None
    on_enter_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    room_after_id: str | None = None
    dialogue_exited: dict | None = None


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
) -> ResolutionResult:
    target = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Current room '{room_id}' not found in corpus")

    if action.using is not None:
        if action.using not in hard.player.inventory and action.using not in soft.soft_inventory:
            return ResolutionResult(
                success=False,
                error=f"Item '{action.using}' is not in your inventory",
            )

    if target == room_id:
        return ResolutionResult(
            success=True,
            hard_changes=HardStateChanges(),
            triggered_narration=[room.description],
            room_after_id=room_id,
        )

    entity = _find_entity_in_room(target, room_id, room, corpus)
    if entity is not None:
        if entity.type == "npc":
            entity_state = hard.entity_states.get(target, {})
            if entity_state.get("alive") is False:
                description = f"{entity.description} (It is dead.)"
            else:
                description = entity.description
        else:
            description = entity.description
        return ResolutionResult(
            success=True,
            hard_changes=HardStateChanges(),
            triggered_narration=[description],
            room_after_id=room_id,
        )

    all_soft = set(room.soft_items or [])
    for eid in room.entities_present:
        ent = corpus.entities.get(eid)
        if ent and ent.soft_items:
            all_soft.update(ent.soft_items)
    if target in all_soft:
        return ResolutionResult(
            success=True,
            hard_changes=HardStateChanges(),
            triggered_narration=[f"You examine the {target}."],
            room_after_id=room_id,
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
            if trav.trigger_encounter:
                encounter_trigger = trav.trigger_encounter

    room_states = hard.room_states.get(exit_data.target_room, {})
    changes.room_state_changes[exit_data.target_room] = {
        **room_states,
        "visited": True,
    }

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        encounter_trigger=encounter_trigger,
        room_after_id=exit_data.target_room,
    )


def resolve_talk(
    action: TalkAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    target_npc = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)

    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    if target_npc not in room.entities_present:
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

    turn = hard.turn_count
    dialogue_exited = None

    current_active = soft.dialogue_state.active_npc
    if current_active is not None and current_active != target_npc:
        dialogue_exited = exit_dialogue(soft, corpus, hard)

    if soft.dialogue_state.active_npc is None:
        enter_dialogue(soft, target_npc, turn, action.utterance, action.detail)
    else:
        append_player_turn(soft, target_npc, turn, action.utterance, action.detail)

    if action.ends_dialogue:
        dialogue_exited = exit_dialogue(soft, corpus, hard)

    return ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=room_id,
        dialogue_exited=dialogue_exited,
    )


def resolve_transfer(
    action: TransferAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    target_id = action.target
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    target_is_room = target_id == room_id
    target_is_entity = target_id in room.entities_present

    if not target_is_room and not target_is_entity:
        return ResolutionResult(
            success=False,
            error=f"Transfer target '{target_id}' not found in room '{room_id}'",
        )

    given_items = action.given_items or []
    taken_items = action.taken_items or []

    changes = HardStateChanges()

    for item in given_items:
        if item in hard.player.inventory:
            changes.inventory_removed.append(item)
        elif item in soft.soft_inventory:
            changes.inventory_removed.append(item)
        else:
            return ResolutionResult(
                success=False,
                error=f"Item '{item}' is not in your inventory",
            )

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

    for item in taken_items:
        if item in available_pool:
            changes.inventory_added.append(item)
        else:
            return ResolutionResult(
                success=False,
                error=f"Item '{item}' is not available from '{target_id}'",
            )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=room_id,
    )


def resolve_interact(
    action: InteractAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    target_id = action.target
    interaction_id = action.interaction_id
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    if action.using is not None:
        if action.using not in hard.player.inventory and action.using not in soft.soft_inventory:
            return ResolutionResult(
                success=False,
                error=f"Item '{action.using}' is not in your inventory",
            )

    target_entity = _find_entity_in_room(target_id, room_id, room, corpus)

    if target_entity is None:
        if interaction_id not in ("take",):
            return ResolutionResult(
                success=False,
                error=f"Target '{target_id}' not found in room '{room_id}'",
            )

    matches: list[tuple[Interaction, str]] = []

    if target_entity:
        for inter in target_entity.interactions:
            if inter.id == interaction_id:
                matches.append((inter, "entity"))
        if interaction_id == "take" and target_entity.type == "item":
            return _handle_take(target_id, target_entity, room_id, room, hard, soft, corpus)
        if interaction_id == "attack":
            npc_entity = corpus.entities.get(target_id)
            if npc_entity and npc_entity.type == "npc" and npc_entity.behavior:
                encounter_trigger = target_id
                return ResolutionResult(
                    success=True,
                    hard_changes=HardStateChanges(),
                    encounter_trigger=encounter_trigger,
                    room_after_id=room_id,
                )
            return ResolutionResult(
                success=False,
                error=f"Nothing to attack — '{target_id}' is not a valid combat target",
            )

    for inter in room.interactions:
        if inter.id == interaction_id:
            matches.append((inter, "room"))

    if not matches:
        return ResolutionResult(
            success=False,
            error=f"Interaction '{interaction_id}' not found for target '{target_id}'",
        )

    inter, source = matches[0]

    if inter.condition and not evaluate(inter.condition, hard, soft, corpus):
        return ResolutionResult(
            success=False,
            error=f"Conditions not met for interaction '{interaction_id}'",
        )

    if inter.parameter_signature:
        sig = inter.parameter_signature
        entity_types = {"player", "feature", "npc", "trap", "item"}
        if sig.target:
            target_type = target_entity.type if target_entity else "soft_item"
            allowed = set(sig.target)
            if target_type not in allowed and not (
                "entity" in allowed and target_type in entity_types
            ):
                return ResolutionResult(
                    success=False,
                    error=f"Target type '{target_type}' not allowed for interaction '{interaction_id}' (expected: {sig.target})",
                )
        if sig.using and action.using:
            using_entity = corpus.entities.get(action.using)
            using_type = using_entity.type if using_entity else "soft_item"
            allowed_using = set(sig.using)
            if using_type not in allowed_using and not (
                "entity" in allowed_using and using_type in entity_types
            ):
                return ResolutionResult(
                    success=False,
                    error=f"Using item type '{using_type}' not allowed for interaction '{interaction_id}' (expected: {sig.using})",
                )

    if inter.check:
        return _resolve_interaction_check(inter, hard, soft, corpus, room_id)

    if inter.result:
        return _resolve_interaction_result(inter.result, hard, soft, corpus, room_id)

    return ResolutionResult(
        success=False,
        error=f"Interaction '{interaction_id}' has no defined result",
    )


def _resolve_interaction_check(
    inter: Interaction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
) -> ResolutionResult:
    check = inter.check
    if check is None:
        return ResolutionResult(success=False, error="Check defined but missing")

    roll = random.random()
    success_flag = roll < check.threshold

    branch = inter.success if success_flag else inter.failure
    result = branch if branch else inter.result

    changes = HardStateChanges()
    narrative: list[str] = []

    if result:
        _apply_result(result, changes, narrative)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        room_after_id=room_id,
    )


def _resolve_interaction_result(
    result: Result,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
) -> ResolutionResult:
    changes = HardStateChanges()
    narrative: list[str] = []

    _apply_result(result, changes, narrative)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        room_after_id=room_id,
    )


def _apply_result(
    result: Result,
    changes: HardStateChanges,
    narrative: list[str],
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
    if result.reveals:
        narrative.append(result.reveals)


def _handle_take(
    target_id: str,
    entity: Any,
    room_id: str,
    room: Any,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    changes = HardStateChanges()
    changes.inventory_added.append(target_id)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=[f"You take the {target_id}."],
        room_after_id=room_id,
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


def resolve_action(
    action: Any,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
    """Dispatch a PlayerAction to the appropriate resolver."""
    action_type = action.action_type
    if action_type == "move":
        return resolve_move(action, hard, soft, corpus)
    elif action_type == "examine":
        return resolve_examine(action, hard, soft, corpus)
    elif action_type == "interact":
        return resolve_interact(action, hard, soft, corpus)
    elif action_type == "talk":
        return resolve_talk(action, hard, soft, corpus)
    elif action_type == "transfer":
        return resolve_transfer(action, hard, soft, corpus)
    elif action_type == "wait":
        return resolve_wait(action, hard, soft, corpus)
    elif action_type == "ooc_discussion":
        return resolve_ooc(action, hard, soft, corpus)
    else:
        return ResolutionResult(
            success=False,
            error=f"Unknown action type: {action_type}",
        )
