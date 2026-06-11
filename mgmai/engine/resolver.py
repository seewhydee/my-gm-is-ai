from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional

from mgmai.models.actions import (
    DialogueExitedResult,
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
    ChainedCheck,
    Interaction,
    ModuleCorpus,
    OnExamineEvent,
    Result,
    RollCheck,
    StatCheck,
    TraversalCheck,
    UsingResultOverride,
)
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


@dataclass
class ResolutionResult:
    success: bool
    error: str | None = None
    hard_changes: HardStateChanges | None = None
    triggered_narration: list[str] = field(default_factory=list)
    revealed_hints: list[str] = field(default_factory=list)
    encounter_trigger: str | None = None
    on_enter_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    room_after_id: str | None = None
    dialogue_exited: DialogueExitedResult | dict | None = None
    soft_patches: list[SoftStatePatch] = field(default_factory=list)
    rolls: list[dict[str, Any]] = field(default_factory=list)
    surfaced_soft_items: dict[str, list[str]] = field(default_factory=dict)


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
        changes = HardStateChanges()
        base_narrative = [room.description]
        surface_result = _fire_on_examine_events(
            room.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
        )
        return ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=base_narrative,
            revealed_hints=surface_result["revealed_hints"],
            surfaced_soft_items=surface_result["surfaced"],
            rolls=surface_result["rolls"],
            room_after_id=room_id,
        )

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
        surface_result = _fire_on_examine_events(
            entity.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
        )
        return ResolutionResult(
            success=True,
            hard_changes=changes,
            triggered_narration=base_narrative,
            revealed_hints=surface_result["revealed_hints"],
            surfaced_soft_items=surface_result["surfaced"],
            rolls=surface_result["rolls"],
            room_after_id=room_id,
        )

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
            )
            if not passed:
                narrative_result = list(traversal_narrative)
                if trav_check.failure_narrative:
                    narrative_result.append(trav_check.failure_narrative)
                return ResolutionResult(
                    success=True,
                    hard_changes=HardStateChanges(),
                    triggered_narration=narrative_result,
                    room_after_id=room_id,
                    rolls=traversal_rolls,
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
    one_way_from = room_states.get("_one_way_from", {})
    if one_way_from.get(room_id):
        return ResolutionResult(
            success=False,
            error=f"Reverse traversal of one-way exit from '{exit_data.target_room}' to '{room_id}' is blocked",
        )

    if exit_data.one_way:
        changes.room_state_changes[exit_data.target_room] = {
            **room_states,
            "visited": True,
            "_one_way_from": {**one_way_from, room_id: True},
        }
    else:
        changes.room_state_changes[exit_data.target_room] = {
            **room_states,
            "visited": True,
        }

    # --- follower_blacklist: stop followers who refuse this room ---
    _check_follower_blacklist(hard, corpus, exit_data.target_room, narrative)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        encounter_trigger=encounter_trigger,
        room_after_id=exit_data.target_room,
        rolls=traversal_rolls,
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

    # Resolve dialogue path if specified
    path_result: ResolutionResult | None = None
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
        if path.check:
            synthetic_inter = Interaction(
                id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
                label="",
                check=path.check,
                success=path.success,
                failure=path.failure,
            )
            path_result = _resolve_interaction_check(
                synthetic_inter, hard, soft, corpus, room_id
            )
        elif path.result:
            path_result = _resolve_interaction_result(
                path.result, hard, soft, corpus, room_id
            )
        else:
            path_result = ResolutionResult(
                success=True,
                hard_changes=HardStateChanges(),
                room_after_id=room_id,
            )

    # If the path resolution itself failed (invalid, not just check failure),
    # do not enter dialogue.
    if path_result is not None and not path_result.success:
        return path_result

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

    if path_result is not None:
        return ResolutionResult(
            success=True,
            hard_changes=path_result.hard_changes or HardStateChanges(),
            triggered_narration=list(path_result.triggered_narration or []),
            revealed_hints=list(path_result.revealed_hints or []),
            room_after_id=room_id,
            dialogue_exited=dialogue_exited,
            rolls=list(path_result.rolls or []),
        )

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

    for item in given_items:
        if item in hard.player.inventory:
            changes.inventory_removed.append(item)
        elif item in soft.soft_inventory:
            soft_patches.append(
                SoftStatePatch(
                    field="soft_inventory_remove",
                    new_value=item,
                    reason=f"Transfer: given to {target_id}",
                )
            )
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

    surfaced: dict[str, list[str]] = {}

    for item in taken_items:
        if item in available_pool:
            changes.inventory_added.append(item)
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
        else:
            return ResolutionResult(
                success=False,
                error=f"Item '{item}' is not available from '{target_id}'",
            )

    # Given soft items: surface on the target (they now reside there)
    for item in given_items:
        if item in soft.soft_inventory:
            surfaced.setdefault(target_id, []).append(item)

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        soft_patches=soft_patches,
        room_after_id=room_id,
        surfaced_soft_items=surfaced,
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

    if inter.condition and not evaluate(inter.condition, hard, soft, corpus):
        return ResolutionResult(
            success=False,
            error=f"Conditions not met for interaction '{interaction_id}'",
        )

    if inter.parameter_signature:
        sig = inter.parameter_signature
        entity_types = {"player", "feature", "npc", "item"}
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

    if inter.using_results and action.using:
        item_override = inter.using_results.get(action.using)
        if item_override is not None:
            return _resolve_using_override(item_override, hard, soft, corpus, room_id)

    if inter.result:
        return _resolve_interaction_result(inter.result, hard, soft, corpus, room_id)

    return ResolutionResult(
        success=False,
        error=f"Interaction '{interaction_id}' has no defined result",
    )


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
) -> None:
    if depth >= MAX_CHAIN_CHECK_DEPTH:
        return
    check = chained.check
    if isinstance(check, StatCheck):
        _resolve_stat_check_chain(
            check, chained.success, chained.failure,
            hard, soft, corpus, room_id,
            changes, narrative, revealed_hints, rolls, depth,
        )
    else:
        _resolve_roll_check_chain(
            check, chained.success, chained.failure,
            hard, soft, corpus, room_id,
            changes, narrative, revealed_hints, rolls, depth,
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
) -> None:
    roll_val = random.random()
    success_flag = roll_val < check.threshold

    branch = success if success_flag else failure
    result = branch if branch else None

    rolls.append({
        "threshold": check.threshold,
        "result": roll_val,
        "success": success_flag,
    })

    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, depth + 1,
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
) -> None:
    stats_block = corpus.stats
    if stats_block is None:
        return

    player_stats = hard.player.stats
    if player_stats is None or check.stat not in player_stats:
        return

    stat_value = player_stats[check.stat]
    res_system = stats_block.resolution_system
    if res_system != "d20":
        return

    from mgmai.engine.stat_checks import compute_d20_modifier

    computed_mod = compute_d20_modifier(stat_value)
    total_mod = computed_mod + check.modifier

    params = (check.resolution_params or {}).get("d20", {})
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

    if result:
        _apply_result(result, changes, narrative, revealed_hints, hard, corpus)
        if result.chain_check:
            _resolve_chained_check(
                result.chain_check, hard, soft, corpus, room_id,
                changes, narrative, revealed_hints, rolls, depth + 1,
            )


def _resolve_traversal_check(
    check: CheckType,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    changes: HardStateChanges,
    narrative: list[str],
    rolls: list[dict[str, Any]],
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
        res_system = stats_block.resolution_system
        if res_system != "d20":
            return True

        from mgmai.engine.stat_checks import compute_d20_modifier

        computed_mod = compute_d20_modifier(stat_value)
        total_mod = computed_mod + check.modifier

        params = (check.resolution_params or {}).get("d20", {})
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
        return success_flag


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

    # Non-repeatable gating (shared by both check types)
    if not check.repeatable:
        attempted = soft.checks_attempted.get(inter.id, [])
        if room_id in attempted:
            return ResolutionResult(
                success=False,
                error=f"Interaction '{inter.id}' has already been attempted and is not repeatable",
            )

    if isinstance(check, StatCheck):
        return _resolve_stat_check(inter, check, hard, soft, corpus, room_id)
    else:
        return _resolve_roll_check(inter, check, hard, soft, corpus, room_id)


def _resolve_roll_check(
    inter: Interaction,
    check: RollCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
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
            )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls,
    )


def _resolve_stat_check(
    inter: Interaction,
    check: StatCheck,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
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
    res_system = stats_block.resolution_system

    if res_system != "d20":
        return ResolutionResult(
            success=False,
            error=f"Unsupported resolution system: {res_system!r}",
        )

    from mgmai.engine.stat_checks import compute_d20_modifier

    computed_mod = compute_d20_modifier(stat_value)
    total_mod = computed_mod + check.modifier

    # advantage / disadvantage
    params = (check.resolution_params or {}).get("d20", {})
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
            )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
        rolls=rolls,
    )


def _resolve_using_override(
    override: UsingResultOverride,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
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
        return _resolve_interaction_check(synthetic_inter, hard, soft, corpus, room_id)
    if override.result:
        return _resolve_interaction_result(override.result, hard, soft, corpus, room_id)
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
        )

    return ResolutionResult(
        success=True,
        hard_changes=changes,
        triggered_narration=narrative,
        revealed_hints=revealed_hints,
        room_after_id=room_id,
    )


def _apply_result(
    result: Result,
    changes: HardStateChanges,
    narrative: list[str],
    revealed_hints: list[str],
    hard: HardGameState | None = None,
    corpus: ModuleCorpus | None = None,
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
    if result.set_stat:
        for stat_key, delta in result.set_stat.items():
            changes.stat_changes[stat_key] = changes.stat_changes.get(stat_key, 0) + delta
    if result.set_entity_state and hard is not None:
        for ent_id, state_changes in result.set_entity_state.items():
            if ent_id not in hard.entity_states:
                hard.entity_states[ent_id] = {}
            hard.entity_states[ent_id].update(state_changes)
            changes.entity_state_changes.setdefault(ent_id, {}).update(state_changes)
    if result.adjust_attitude and hard is not None and corpus is not None:
        for npc_id, delta in result.adjust_attitude.items():
            npc_entity = corpus.entities.get(npc_id)
            if npc_entity is None or npc_entity.type != "npc":
                continue
            guidelines = npc_entity.dialogue_guidelines
            if guidelines is None:
                continue
            limits = guidelines.attitude_limits
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
            if npc_id not in hard.entity_states:
                hard.entity_states[npc_id] = {}
            hard.entity_states[npc_id]["attitude"] = new_value
            changes.entity_state_changes.setdefault(npc_id, {})["attitude"] = new_value
    if result.reveals:
        revealed_hints.append(result.reveals)


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
            result = _resolve_interaction_check(synthetic, hard, soft, corpus, room_id)
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
