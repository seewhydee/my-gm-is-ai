from __future__ import annotations

from typing import Any

from mgmai.models.actions import (
    AttitudeLimitsCurrent,
    ChainInfo,
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
from mgmai.engine.conditions import evaluate
from mgmai.engine.resolver import resolve_action, ResolutionResult
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

    resolution = resolve_action(player_action, hard, soft, corpus)

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
        )

    hard_changes = resolution.hard_changes or HardStateChanges()

    old_room = hard.player.location

    state_manager.apply_hard_changes(hard_changes)

    engine_soft_patches = list(resolution.soft_patches or [])
    if engine_soft_patches:
        state_manager.apply_soft_patches(engine_soft_patches)

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

    encounter_outcome: dict[str, Any] | None = None
    game_over = None
    rolls: list[dict[str, Any]] = list(resolution.rolls or [])

    if resolution.encounter_trigger:
        npc_id = resolution.encounter_trigger
        npc = corpus.entities.get(npc_id)
        if npc and npc.behavior:
            encounter_rules = npc.behavior.encounter_rules
            enc_result = resolve_encounter(encounter_rules, hard, soft, corpus, npc_id)
            if enc_result["narrative"]:
                resolution.triggered_narration.append(enc_result["narrative"])

            set_flags = enc_result.get("set_flags") or {}
            for flag, val in set_flags.items():
                hard.flags[flag] = val

            if enc_result["flee_effects"]:
                apply_flee_effects(enc_result["flee_effects"], hard)

            if enc_result["game_over"]:
                go = enc_result["game_over"]
                hard.game_over = GameOverState(type=go["type"], trigger=go["trigger"])
                game_over = GameOverResult(
                    type=go["type"],
                    trigger=go["trigger"],
                    narrative=enc_result.get("narrative"),
                )

            encounter_outcome = EncounterOutcome(
                encounter_id=npc_id,
                outcome=enc_result["outcome"],
                narrative_brief=enc_result.get("narrative"),
            )
            enc_rolls = enc_result.get("rolls") or []
            rolls.extend(enc_rolls)

    if resolution.encounter_trigger and game_over is None:
        interact_target = getattr(player_action, "target", None)
        if interact_target:
            npc = corpus.entities.get(interact_target)
            if npc and npc.behavior and "attack" in (npc.behavior.triggers_on or []):
                pass

    if hard.game_over is None:
        _check_game_over_mechanics(hard, soft, corpus, game_over_ref := [None])
        if game_over_ref[0]:
            game_over = game_over_ref[0]
            hard.game_over = GameOverState(
                type=game_over.type,
                trigger=game_over.trigger,
            )

    on_enter_results: list[OnEnterEventResult] = []
    new_room = resolution.room_after_id or hard.player.location
    if new_room != old_room:
        on_enter_results = _fire_on_enter_events(
            new_room, hard, soft, corpus, resolution.triggered_narration
        )

        dialogue_exit = check_room_change_exit(
            soft, old_room, new_room, corpus, hard
        )
        if dialogue_exit:
            resolution.dialogue_exited = dialogue_exit

    if hard.game_over is not None and game_over is None:
        game_over = GameOverResult(
            type=hard.game_over.type,
            trigger=hard.game_over.trigger,
        )

    if action_type == "talk":
        pass
    elif action_type != "ooc_discussion":
        if soft.dialogue_state.active_npc is not None:
            stall_exited = increment_stall(soft)
            if stall_exited:
                resolution.dialogue_exited = exit_dialogue(soft, corpus, hard)

    hard.turn_count += 1

    turn_entry = TurnHistoryEntry(
        turn=hard.turn_count,
        player_input=player_input_echo or player_action.detail,
        ruled_action=player_action.model_dump(),
        engine_result_summary=_summarize_resolution(resolution, new_room),
        flags_changed=list(hard_changes.flags_set.keys())
        + list(hard_changes.flags_cleared),
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
        hard_state_changes=hard_changes,
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
        warnings=warnings,
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
        if entity_state.get("alive") is False:
            continue

        notes = soft.entity_notes.get(eid, [])[-3:]

        entities_visible.append(
            BriefingEntity(
                id=eid,
                name=getattr(entity, "name", eid),
                type=entity.type,
                description=entity.description,
                state=entity_state,
                entity_notes=notes,
                soft_items=entity.soft_items or [],
            )
        )

    exits_available: list[BriefingExit] = []
    for ex in room.exits:
        if ex.hidden:
            continue
        if ex.conditions:
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

    return BriefingRoom(
        id=room_id,
        name=room.name,
        description=room.description,
        soft_items=room.soft_items or [],
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

    for eid in room.entities_present:
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
            for cond_raw in topic_entry.conditions:
                if not evaluate(cond_raw, hard, soft, corpus):
                    conditions_met = False
                    break
            npc_ready[topic_id] = WillRevealReadinessEntry(
                conditions_met=conditions_met,
                description=topic_entry.description,
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

    for eid in room.entities_present:
        entity = corpus.entities.get(eid)
        if entity is None or entity.type != "npc":
            continue

        guidelines = entity.dialogue_guidelines
        if guidelines is None:
            continue

        limits = guidelines.attitude_limits
        current = soft.npc_attitudes.get(eid, limits.initial)

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
    if resolution.encounter_trigger:
        parts.append(f"Encounter: {resolution.encounter_trigger}")
    if resolution.triggered_narration:
        parts.append(
            f"Narration: {resolution.triggered_narration[0][:80]}..."
            if len(resolution.triggered_narration[0]) > 80
            else f"Narration: {resolution.triggered_narration[0]}"
        )
    return "; ".join(parts) if parts else "No changes"
