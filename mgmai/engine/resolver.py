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
from typing import Any, Literal

from mgmai.engine.conditions import evaluate
from mgmai.engine.dialogue import (
    append_player_turn,
    enter_dialogue,
    exit_dialogue,
)
from mgmai.engine.status_effects import apply_status_effect, remove_status_effect
from mgmai.engine.systems import CheckResult, get_system_for_corpus
from mgmai.engine.utils import (
    _is_stackable,
    _match_soft_content,
    get_following_npc_ids,
    get_status_effects,
)
from mgmai.models.actions import (
    CURRENT_ROOM_SENTINEL,
    CombatAction,
    DialogueExitedResult,
    ExamineAction,
    GearAction,
    HardStateChanges,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    RestAction,
    SoftItemProposal,
    TalkAction,
    TransferAction,
    UseAbilityAction,
    WaitAction,
)
from mgmai.models.combat import CombatLogEntry
from mgmai.models.corpus import (
    CheckResolution,
    CheckType,
    EncounterRule,
    GatedCheck,
    Interaction,
    ModuleCorpus,
    OnExamineEvent,
    Resolvable,
    Result,
    StatCheck,
    StatModifier,
    UsingResultOverride,
)
from mgmai.models.hard_state import GameOverState, HardGameState
from mgmai.models.soft_state import SoftGameState

MAX_THEN_CHECK_DEPTH = 3

log = logging.getLogger(__name__)


def _merge_item_counts(
    items: list[str] | None,
    counts: dict[str, int] | None,
) -> dict[str, int]:
    """Merge a list of item IDs (each counts as +1) with an explicit count map."""
    result: dict[str, int] = {}
    if items:
        for item_id in items:
            result[item_id] = result.get(item_id, 0) + 1
    if counts:
        for item_id, count in counts.items():
            result[item_id] = result.get(item_id, 0) + count
    return result


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

    from mgmai.engine.event_bus import dispatch_reactions, find_matching_reactions

    matches = find_matching_reactions(
        event_type, context, hard, soft, corpus,
        disabled_once=getattr(state_manager, "disabled_once", None),
    )
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
    # Free-form summary surfaced to the prose LLM via EngineResult.message
    # (e.g. a rest's recharge breakdown).  None for actions with no
    # mechanical summary to convey.
    message: str | None = None
    triggered_narration: list[str] = field(default_factory=list)
    revealed_hints: list[str] = field(default_factory=list)
    encounter_trigger: str | None = None
    combat_trigger: list[str] | None = None
    combat_log: list[CombatLogEntry] = field(default_factory=list)
    combat_triggered: bool = False
    player_died: bool = False
    warnings: list[str] = field(default_factory=list)
    room_after_id: str | None = None
    dialogue_exited: DialogueExitedResult | dict | None = None
    rolls: list[dict[str, Any]] = field(default_factory=list)
    soft_content_takes: dict[str, dict[str, int]] = field(default_factory=dict)
    soft_item_proposals: list[Any] = field(default_factory=list)
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


def _summarise_recharge(
    kind: str,
    recharge: Any,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> str:
    """Build a concise factual summary of what a rest recovered.

    This is the ``EngineResult.message`` channel for the prose LLM — not
    the final narration, just a hint of the mechanical outcome.
    """
    label = "Long rest" if kind == "long" else "Short rest"
    parts: list[str] = []
    if recharge.hp_delta:
        parts.append(f"HP +{recharge.hp_delta}")
    if recharge.slots_refilled_to_max and hard.player.max_spell_slots:
        parts.append("spell slots recharged")
    if recharge.hit_dice_recovered:
        parts.append(f"Hit Dice +{recharge.hit_dice_recovered}")
    if recharge.exhaustion_decrement:
        parts.append("exhaustion -1")
    if recharge.statuses_to_clear:
        parts.append(
            "statuses cleared: " + ", ".join(recharge.statuses_to_clear)
        )
    if recharge.followers_healed:
        names = [
            getattr(corpus.entities.get(eid), "name", None) or eid
            for eid in recharge.followers_healed
        ]
        parts.append("followers healed: " + ", ".join(names))
    if not parts:
        return f"{label}: no resources recovered."
    return f"{label}: " + "; ".join(parts) + "."


def resolve_rest(
    action: RestAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a short or long rest.

    Recharge is deterministic and delegated to the resolution system's
    ``on_short_rest`` / ``on_long_rest`` hooks, which return a
    :class:`~mgmai.models.actions.RestRechargeResult` describing what the
    rest means for the active rules.  The resolver applies it here —
    system hooks never mutate ``hard`` directly.

    HP healing flows through ``HardStateChanges.player_hp_delta`` (so the
    prose LLM and state-change event derivation see it); slot, hit-dice,
    and status-effect changes are applied directly to ``hard.player``,
    mirroring how ``apply_status_effect`` / ``remove_status_effect`` work
    elsewhere.  A ``rest.completed`` event is emitted so corpus reactions
    can observe rests.

    Resting during combat is rejected (the engine backstop for a rest
    action emitted while combat is active; the ruling LLM is expected to
    rule it as ``wait`` instead).
    """
    if hard.combat is not None and hard.combat.active:
        return ResolutionResult(
            success=False,
            error="Cannot rest during combat",
        )

    system = get_system_for_corpus(corpus)
    if action.kind == "long":
        recharge = system.on_long_rest(hard, corpus)
    else:
        recharge = system.on_short_rest(hard, corpus)

    events: list[tuple[str, dict[str, Any]]] = []

    # HP healing — via HardStateChanges for the prose LLM / event diff.
    changes = HardStateChanges()
    if recharge.hp_delta:
        changes.player_hp_delta = recharge.hp_delta
        if recharge.hp_delta > 0:
            changes.player_heal_delta = recharge.hp_delta

    # Spell slots — refill each declared level to its ceiling.  Levels
    # present in spell_slots but absent from max_spell_slots (a sheet
    # omission the validator only warns about) are left untouched, not
    # wiped.
    if recharge.slots_refilled_to_max:
        for lvl, count in hard.player.max_spell_slots.items():
            hard.player.spell_slots[lvl] = count

    # Statuses — clear time-limited magic (e.g. Mage Armor).
    for eid in recharge.statuses_to_clear:
        remove_status_effect("player", eid, hard, corpus, "rest", events)

    # Hit dice — recover spent dice (SRD 5.2.1 long rest: all).
    hd = hard.player.hit_dice
    if hd is not None and recharge.hit_dice_recovered:
        hd.current = min(hd.max, hd.current + recharge.hit_dice_recovered)

    # Exhaustion — reduce by one level on a long rest.
    if recharge.exhaustion_decrement:
        current_level: int | None = None
        for eid in hard.player.status_effects:
            if eid.startswith("exhaustion-"):
                try:
                    current_level = int(eid.split("-", 1)[1])
                except ValueError:
                    continue
                break
        if current_level is not None:
            remove_status_effect(
                "player", f"exhaustion-{current_level}", hard, corpus,
                "rest", events,
            )
            if current_level > 1:
                apply_status_effect(
                    "player", f"exhaustion-{current_level - 1}", 1, hard,
                    corpus, "rest", events,
                )

    # Follower allies — long rest restores them to full HP (no hit-dice
    # tracking for NPCs).  Mutated directly and recorded as absolute
    # sets, matching NPC HP handling in combat.
    for eid in recharge.followers_healed:
        ent = corpus.entities.get(eid)
        if ent is None or ent.combat is None:
            continue
        hard.entity_states.setdefault(eid, {})["current_hp"] = ent.combat.hp
        changes.entity_state_changes.setdefault(eid, {})["current_hp"] = (
            ent.combat.hp
        )

    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=hard.player.location,
        events=events,
    )

    # Surface a rest.completed event for corpus reactions.  Interruption
    # mid-rest (ambush at hour six, partial benefit) is deferred — the
    # ruling LLM's refusal-at-ruling covers "it's not safe here".
    _emit_event(
        "rest.completed", {"kind": action.kind},
        hard, soft, corpus, state_manager, result,
    )

    result.message = _summarise_recharge(action.kind, recharge, hard, corpus)
    return result

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
    # The "current_room" sentinel denotes the player's current room; normalize
    # it to the actual room ID so downstream logic (event context, soft-item
    # proposals, etc.) sees a real ID.
    if target == CURRENT_ROOM_SENTINEL:
        target = room_id
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(
            success=False,
            error=f"Current room '{room_id}' not found in corpus",
            costs_turn=False,
        )

    if action.using is not None and (
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
        event_result = _fire_on_examine_events(
            room.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
            state_manager, result,
        )
        result.revealed_hints = event_result["revealed_hints"]
        result.rolls = event_result["rolls"]
        return result

    entity = _find_entity_in_room_followers(target, room_id, hard, corpus)
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
        event_result = _fire_on_examine_events(
            entity.on_examine, hard, soft, corpus, room_id, action, changes, base_narrative,
            state_manager, result,
        )
        result.revealed_hints = event_result["revealed_hints"]
        result.rolls = event_result["rolls"]
        return result

    # Not a hard room/entity; propose it as a soft-item examine.
    # Call 2 will adjudicate whether the item exists in the scene.
    return ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        triggered_narration=[f"You examine the {target}."],
        room_after_id=room_id,
        costs_turn=action.rigorous,
        soft_item_proposals=[
            SoftItemProposal(
                item_name=target,
                action="examine",
                source_id=room_id,
            )
        ],
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

    if exit_data.condition is not None and not evaluate(exit_data.condition, hard, soft, corpus):
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
            # Resolve using_results overrides (weapon-based DC reduction,
            # etc.).  An override replaces what it specifies — check,
            # success, failure — and inherits the rest from the parent
            # GatedCheck.  A result-only override is an automatic success
            # applying that result.
            effective_check = trav_check.check
            success_result = trav_check.success
            failure_result = trav_check.failure
            using_override: UsingResultOverride | None = None
            using_item = getattr(action, "using", None)
            if trav_check.using_results and using_item:
                using_override = trav_check.using_results.get(using_item)
                if using_override is None:
                    using_override = trav_check.using_results.get("*")
                if using_override is not None:
                    if using_override.check is not None:
                        effective_check = using_override.check
                    if using_override.success is not None:
                        success_result = using_override.success
                    if using_override.failure is not None:
                        failure_result = using_override.failure

            if using_override is not None and using_override.result is not None:
                # Fixed-result override: the traversal automatically succeeds.
                _apply_result_with_check(
                    using_override.result,
                    changes=traversal_changes, narrative=traversal_narrative,
                    revealed_hints=traversal_hints, hard=hard, corpus=corpus,
                    soft=soft, room_id=exit_data.target_room,
                    rolls=traversal_rolls,
                    state_manager=state_manager, resolution=result,
                    source_id=target_exit_id, source_type="traversal",
                    item_origin="traversal",
                )
                passed = True
            else:
                passed = _resolve_traversal_check(
                    effective_check, hard, soft, corpus,
                    traversal_changes, traversal_narrative, traversal_rolls,
                    state_manager, result, target_exit_id,
                )
            if not passed:
                if failure_result:
                    _apply_result_with_check(
                        failure_result,
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
                    },
                    hard, soft, corpus, state_manager, result,
                )
                return result
            # Traversal succeeded: apply success Result (including any then_check)
            if passed and success_result and (
                using_override is None or using_override.result is None
            ):
                _apply_result_with_check(
                    success_result,
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
    base_state = dict(room_states)
    base_state["visited"] = True
    existing_changes = changes.room_state_changes.get(exit_data.target_room, {})
    changes.room_state_changes[exit_data.target_room] = {**base_state, **existing_changes}

    # --- follower blacklist: stop followers who refuse this room ---
    _check_follower_blacklist(
        hard, corpus, exit_data.target_room, narrative, changes
    )

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

    # Dialogue and combat are mutually exclusive; the guards in the other
    # direction (combat entry exiting dialogue) live in engine.py and
    # event_bus.py.  This is the engine backstop for a talk action emitted
    # while combat is active.
    if hard.combat is not None and hard.combat.active:
        return ResolutionResult(
            success=False,
            error="Cannot hold a conversation during combat",
        )

    follower_ids = get_following_npc_ids(hard, corpus)
    if (target_npc not in hard.room_contains.get(room_id, {})
            and target_npc not in follower_ids):
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
    if action.dialogue_path and npc_entity.dialogue:
        path = npc_entity.dialogue.dialogue_paths.get(action.dialogue_path)
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
        path_result = _resolve_interaction(
            path, hard, soft, corpus, room_id,
            action_using=getattr(action, "using", None),
            state_manager=state_manager,
            resolution=result,
            source_type="dialogue_path",
            source_id=f"dialogue_path_{target_npc}_{action.dialogue_path}",
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


def _locate_world_item(
    hard: HardGameState,
    corpus: ModuleCorpus,
    room_id: str,
    item: str,
    preferred_container: str | None = None,
) -> tuple[Literal["room", "entity"], str] | None:
    """Return where *item* lives in the current room world state.

    If *preferred_container* is provided and contains the item, prefer it.
    Otherwise prefer room-level placement, then any open container in the
    room. Returns ("room", room_id) or ("entity", container_id), or None.
    """
    if preferred_container is not None and item in hard.entity_contains.get(preferred_container, {}):
        return ("entity", preferred_container)
    if item in hard.room_contains.get(room_id, {}):
        return ("room", room_id)
    for container_id in hard.room_contains.get(room_id, {}):
        if item in hard.entity_contains.get(container_id, {}):
            return ("entity", container_id)
    return None


def _is_alive_npc(entity_id: str, hard: HardGameState, corpus: ModuleCorpus) -> bool:
    """True if *entity_id* is an NPC that is currently alive.

    Transfers of items to/from a living NPC are deferred to LLM Call 2 for
    consent adjudication; dead NPCs (looting) short-circuit to a mechanical
    transfer.
    """
    ent = corpus.entities.get(entity_id)
    if ent is None or ent.type != "npc":
        return False
    return hard.entity_states.get(entity_id, {}).get("alive") is not False


def resolve_transfer(
    action: TransferAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    target_id = action.target
    room_id = hard.player.location
    # The "current_room" sentinel denotes the player's current room; normalize
    # it to the actual room ID so downstream logic (containment maps,
    # soft-item proposals, post-validation) sees a real ID.
    if target_id == CURRENT_ROOM_SENTINEL:
        target_id = room_id
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    room_contains = hard.room_contains.get(room_id, {})
    target_is_room = target_id == room_id
    follower_ids = get_following_npc_ids(hard, corpus)
    target_is_entity = target_id in room_contains or target_id in follower_ids

    if not target_is_room and not target_is_entity:
        return ResolutionResult(
            success=False,
            error=f"Transfer target '{target_id}' not found in room '{room_id}'",
        )

    given_items = action.given_items or []
    taken_items = action.taken_items or []
    given_counts = action.given_counts or {}
    taken_counts = action.taken_counts or {}

    changes = HardStateChanges()
    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=room_id,
    )

    for item, count in _merge_item_counts(given_items, given_counts).items():
        if item in hard.player.inventory:
            current = hard.player.inventory[item]
            if count > current:
                result.success = False
                result.error = f"Not enough '{item}' to give (have {current}, need {count})"
                return result
            if not _is_stackable(item, corpus) and count > 1:
                result.success = False
                result.error = f"Cannot give {count} of non-stackable item '{item}'"
                return result
            # Giving a hard item to a living NPC is deferred to LLM Call 2
            # for consent adjudication; the move is applied in
            # post-validation only if the NPC consents.  Dead NPCs and
            # non-NPC targets are handled mechanically (looting / placement).
            if target_is_entity and _is_alive_npc(target_id, hard, corpus):
                result.soft_item_proposals.append(
                    SoftItemProposal(
                        item_name=item,
                        action="give",
                        source_id="player",
                        target_id=target_id,
                        count=count,
                        item_kind="hard",
                    )
                )
                continue
            changes.inventory_removed[item] = count
            changes.inventory_removed_reasons[item] = "transfer"
            # Place given hard item into the world-side container.
            if target_is_room:
                changes.room_contains_added.setdefault(room_id, {})[item] = count
            else:
                changes.entity_contains_added.setdefault(target_id, {})[item] = count
        elif item in soft.soft_inventory:
            if count > len([i for i in soft.soft_inventory if i == item]):
                result.success = False
                result.error = f"Not enough '{item}' in soft inventory to give"
                return result
            result.soft_item_proposals.append(
                SoftItemProposal(
                    item_name=item,
                    action="give",
                    source_id="player",
                    target_id=target_id,
                    count=count,
                )
            )
        else:
            result.success = False
            result.error = f"Item '{item}' is not in your inventory"
            return result

    # Build available pool with quantities from the runtime maps (hard items only).
    available_pool: dict[str, int] = {}
    if target_is_room:
        for eid, ecount in room_contains.items():
            ent = corpus.entities.get(eid)
            if ent and ent.type == "item":
                available_pool[eid] = available_pool.get(eid, 0) + ecount
            if ent and hard.entity_contains.get(eid) and _container_is_open(eid, hard, corpus):
                    for cid, ccount in hard.entity_contains[eid].items():
                        cstate = hard.entity_states.get(cid, {})
                        if cstate.get("hidden", False):
                            continue
                        available_pool[cid] = available_pool.get(cid, 0) + ccount
    elif target_is_entity:
        target_ent = corpus.entities.get(target_id)
        if target_ent:
            if target_ent.type == "item" and target_id in room_contains:
                available_pool[target_id] = (
                    available_pool.get(target_id, 0) + room_contains[target_id]
                )
            if _container_is_open(target_id, hard, corpus):
                for cid, ccount in hard.entity_contains.get(target_id, {}).items():
                    available_pool[cid] = available_pool.get(cid, 0) + ccount
        # Fallback: add room-level items not nested inside another entity.
        claimed_entities: set[str] = set()
        for eid in room_contains:
            if eid == target_id:
                continue
            ent = corpus.entities.get(eid)
            if ent and hard.entity_contains.get(eid):
                claimed_entities.update(hard.entity_contains[eid])
        for eid, ecount in room_contains.items():
            ent = corpus.entities.get(eid)
            if ent and ent.type == "item" and eid not in claimed_entities:
                available_pool[eid] = available_pool.get(eid, 0) + ecount

    triggered_narration: list[str] = []
    revealed_hints: list[str] = []
    rolls: list[dict[str, Any]] = []

    for item, count in _merge_item_counts(taken_items, taken_counts).items():
        # Only items can be taken.  A feature or NPC targeted by name is a
        # clean failure, never a containment delta (a non-item delta crashes
        # state validation) and never a soft-item fallback (the id names a
        # real corpus entity, so no phantom copy may be invented).
        taken_ent = corpus.entities.get(item)
        if taken_ent is not None and taken_ent.type != "item":
            return ResolutionResult(
                success=False,
                error=(
                    f"Cannot take '{item}': it is a {taken_ent.type}, not an "
                    "item that can be picked up"
                ),
            )
        # Soft names (no corpus entity) are exempt from the stackable
        # guard — their counts are bounded by soft_contents or by
        # Call 2 adjudication, not by corpus tags.
        if item in corpus.entities and not _is_stackable(item, corpus) and count > 1:
            return ResolutionResult(
                success=False,
                error=f"Cannot take {count} of non-stackable item '{item}'",
            )

        if available_pool.get(item, 0) < count:
            # If the item exists as a hard item but the quantity is insufficient,
            # fail outright rather than falling back to a soft-item proposal.
            if item in available_pool:
                return ResolutionResult(
                    success=False,
                    error=(
                        f"'{item}' is not available in sufficient quantity "
                        f"(have {available_pool[item]}, need {count})"
                    ),
                )
            closed_error: str | None = None
            if target_is_entity:
                target_ent = corpus.entities.get(target_id)
                if target_ent and not _container_is_open(target_id, hard, corpus) and item in hard.entity_contains.get(target_id, {}):
                        closed_error = f"The {target_ent.name or target_id} is closed."
            else:
                for eid in room_contains:
                    ent = corpus.entities.get(eid)
                    if ent and not _container_is_open(eid, hard, corpus) and item in hard.entity_contains.get(eid, {}):
                            closed_error = f"The {ent.name or eid} is closed."
                            break
            if closed_error is not None:
                return ResolutionResult(
                    success=False,
                    error=closed_error,
                )
            # Not present as a hard item.  Consult placed soft items
            # (soft_contents) — their existence is mechanically verified —
            # before falling back to an ambient soft-item take proposal.
            # Order mirrors the hard-item path: accessible sources first,
            # then closed containers; NPC sources defer to Call 2 consent.
            if target_is_entity:
                soft_candidates = [target_id]
            else:
                soft_candidates = [room_id]
                soft_candidates.extend(room_contains)
                soft_candidates.extend(
                    fid for fid in follower_ids if fid not in room_contains
                )
            mech_source: tuple[str, str, int] | None = None
            npc_source: str | None = None
            closed_soft_error: str | None = None
            for source_id in soft_candidates:
                key, placed = _match_soft_content(
                    soft.soft_contents.get(source_id, {}), item
                )
                if key is None:
                    continue
                ent = corpus.entities.get(source_id)
                if ent is not None and ent.type == "npc":
                    if npc_source is None:
                        npc_source = source_id
                    continue
                if ent is not None and not _container_is_open(source_id, hard, corpus):
                    if closed_soft_error is None:
                        closed_soft_error = f"The {ent.name or source_id} is closed."
                    continue
                mech_source = (source_id, key, placed)
                break

            remaining = count
            if mech_source is not None:
                mech_source_id, mech_key, mech_placed = mech_source
                retrieved = min(mech_placed, remaining)
                sct = result.soft_content_takes.setdefault(mech_source_id, {})
                sct[mech_key] = sct.get(mech_key, 0) + retrieved
                remaining -= retrieved
            if remaining:
                if (
                    mech_source is None
                    and npc_source is None
                    and closed_soft_error is not None
                ):
                    return ResolutionResult(
                        success=False,
                        error=closed_soft_error,
                    )
                # NPC-held items keep their full count in the proposal —
                # consent is Call 2's call, and post-validation decrements
                # soft_contents first on acceptance.  A shortfall after
                # mechanical retrieval becomes an ambient proposal from
                # the same source.
                proposal_source = (
                    mech_source[0] if mech_source is not None
                    else npc_source if npc_source is not None
                    else target_id
                )
                result.soft_item_proposals.append(
                    SoftItemProposal(
                        item_name=item,
                        action="take",
                        source_id=proposal_source,
                        count=remaining,
                    )
                )
            continue

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

        changes.inventory_added[item] = count
        changes.inventory_added_sources[item] = "transfer"

        # Record world-side removal.
        preferred = target_id if target_is_entity else None
        location = _locate_world_item(
            hard, corpus, room_id, item, preferred_container=preferred
        )
        # Taking a hard item from a living NPC is deferred to LLM Call 2
        # for consent adjudication: the move is applied in post-validation
        # only if the NPC consents.  Dead NPCs (looting) and non-NPC
        # containers proceed mechanically.  take_check (above) is
        # independent and always applies.
        if (
            location is not None
            and location[0] == "entity"
            and _is_alive_npc(location[1], hard, corpus)
        ):
            # Roll back the optimistic inventory add; the move is deferred.
            del changes.inventory_added[item]
            changes.inventory_added_sources.pop(item, None)
            result.soft_item_proposals.append(
                SoftItemProposal(
                    item_name=item,
                    action="take",
                    source_id=location[1],
                    count=count,
                    item_kind="hard",
                )
            )
            continue
        if location is not None:
            kind, container_id = location
            if kind == "room":
                changes.room_contains_removed.setdefault(
                    container_id, {}
                )[item] = count
            else:
                changes.entity_contains_removed.setdefault(
                    container_id, {}
                )[item] = count

    result.hard_changes = changes
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
    # The "current_room" sentinel denotes the player's current room; normalize
    # it to the actual room ID so downstream logic (event context, etc.) sees
    # a real ID.
    if target_id == CURRENT_ROOM_SENTINEL:
        target_id = room_id
    room = corpus.rooms.get(room_id)
    if room is None:
        return ResolutionResult(success=False, error=f"Room '{room_id}' not found")

    if action.using is not None and (
        action.using not in hard.player.inventory
        and action.using not in hard.player.equipped
        and action.using not in soft.soft_inventory
    ):
        return ResolutionResult(
            success=False,
            error=f"Item '{action.using}' is not in your inventory",
        )

    target_entity = _find_entity_in_room_followers(target_id, room_id, hard, corpus)

    if target_entity is None and target_id != room_id:
        return ResolutionResult(
            success=False,
            error=f"Target '{target_id}' not found in room '{room_id}' or your inventory",
        )

    matches: list[tuple[Interaction, str]] = []

    if target_entity:
        # Reject interactions with dead NPCs.
        if target_entity.type == "npc":
            entity_state = hard.entity_states.get(target_id, {})
            if entity_state.get("alive") is False:
                return ResolutionResult(
                    success=False,
                    error=f"NPC '{target_id}' is dead",
                )

        # If NPC has a CombatBlock and the interaction is an attack, start
        # combat directly (pulling in any present members of its combat_group).
        if interaction_id == "attack" and target_entity.combat is not None:
            from mgmai.engine.combat import enter_combat, resolve_combat_enemies
            enemies = resolve_combat_enemies([target_id], None, hard, corpus)
            if not enemies:
                return ResolutionResult(
                    success=False,
                    error=(
                        f"Cannot start combat with '{target_id}' "
                        f"(not present or not a valid combatant)"
                    ),
                    room_after_id=room_id,
                )
            entry = enter_combat(enemies, hard, corpus, soft=soft, state_manager=state_manager, engage_source=target_id)
            events: list[tuple[str, dict[str, Any]]] = [
                ("combat.started", {"combatant_ids": enemies}),
            ]
            events.extend(entry.get("events") or [])
            if entry.get("combat_ended_reason"):
                events.append(("combat.ended", {
                    "reason": entry["combat_ended_reason"],
                }))
            return ResolutionResult(
                success=True,
                hard_changes=entry["hard_changes"],
                combat_triggered=True,
                combat_log=entry["combat_log"],
                player_died=entry.get("player_died", False),
                room_after_id=room_id,
                events=events,
            )

        # Attacking an NPC always triggers an encounter.  If the NPC has an
        # explicit "attack" interaction defined, that interaction takes
        # precedence and is resolved below.  Otherwise, set an encounter
        # trigger so the engine dispatches it (using aggro.encounter_rules
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

    inter, _source = matches[0]

    if inter.condition and not evaluate(inter.condition, hard, soft, corpus):
        result.error = f"Conditions not met for interaction '{interaction_id}'"
        return result

    inter_result = _resolve_interaction(
        inter, hard, soft, corpus, room_id,
        action_using=action.using,
        state_manager=state_manager,
        resolution=result,
        source_type="interaction",
    )
    result.success = inter_result.success
    result.error = inter_result.error
    result.hard_changes = inter_result.hard_changes
    result.triggered_narration = inter_result.triggered_narration
    result.revealed_hints = inter_result.revealed_hints
    result.encounter_trigger = inter_result.encounter_trigger or result.encounter_trigger
    result.rolls = inter_result.rolls
    result.events.extend(inter_result.events)
    return result


def _resolve_interaction(
    inter: Resolvable,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    *,
    action_using: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_type: str = "interaction",
    source_id: str | None = None,
) -> ResolutionResult:
    """Resolve a single Resolvable (shared by interact, talk, examine).

    Handles skip_check_if bypass, using_results override, result-only,
    and check-bearing branches.  Does NOT evaluate the availability
    ``condition`` (callers gate entry themselves) and does NOT emit
    ``interaction.used`` (callers emit context-appropriate events).
    """
    effective_source_id = source_id if source_id is not None else inter.id

    # skip_check_if bypass takes precedence over using_results: the
    # obstacle is gone, so tools are irrelevant.
    if inter.check and inter.skip_check_if and evaluate(inter.skip_check_if, hard, soft, corpus):
        if inter.success:
            return _resolve_interaction_result(
                inter.success, hard, soft, corpus, room_id,
                encounter_trigger=None, state_manager=state_manager,
                resolution=resolution, source_id=effective_source_id,
                source_type=source_type,
            )
        return ResolutionResult(
            success=True,
            hard_changes=HardStateChanges(),
            room_after_id=room_id,
        )

    # A using_results override replaces the usual resolution: it carries
    # either a fixed result, or its own check with success/failure
    # branches (inheriting any it omits from the parent Resolvable).
    if inter.using_results and action_using:
        item_override = inter.using_results.get(action_using)
        if item_override is None:
            item_override = inter.using_results.get("*")
        if item_override is not None:
            return _resolve_using_override(
                item_override, hard, soft, corpus, room_id,
                encounter_trigger=None, state_manager=state_manager,
                resolution=resolution, source_id=effective_source_id,
                source_type=source_type, parent=inter,
            )

    if inter.check:
        return _resolve_interaction_check(
            inter, hard, soft, corpus, room_id,
            encounter_trigger=None, state_manager=state_manager,
            resolution=resolution, source_type=source_type,
            source_id=effective_source_id,
            attempt_key=effective_source_id,
        )

    if inter.result:
        return _resolve_interaction_result(
            inter.result, hard, soft, corpus, room_id,
            encounter_trigger=None, state_manager=state_manager,
            resolution=resolution, source_id=effective_source_id,
            source_type=source_type,
        )

    return ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=room_id,
    )


def _stat_check_params(
    check: StatCheck,
    system: Any,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> dict:
    """Roll params for a stat check: the check's authored extras
    (``advantage`` / ``disadvantage``) merged with any modifiers the
    player's active status effects impose on ability checks (5e: e.g.
    poisoned).  Saving throws get advantage from the roller's effects
    where the system supports it (5e: ``save_advantage``, e.g. the
    ``dodging`` effect) — see
    :meth:`ResolutionSystem.check_roll_mods`."""
    params = dict(check.model_extra or {})
    status_adv, status_disadv = system.check_roll_mods(
        check.save, get_status_effects("player", hard), corpus
    )
    if status_adv:
        params["advantage"] = True
    if status_disadv:
        params["disadvantage"] = True
    if check.save and system.save_advantage(
        check.stat, get_status_effects("player", hard), corpus
    ):
        params["advantage"] = True
    return params


def _roll_stat_check(
    check: StatCheck,
    system: Any,
    stat_value: int,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> CheckResult:
    """Roll a StatCheck, honouring status-effect modifiers: the flat d20
    modifier (5e: exhaustion) and, for saving throws, forced failure
    without a roll (5e: ``auto_fail_str_dex_saves``, e.g. paralyzed)."""
    status = get_status_effects("player", hard)
    flat_modifier = (
        check.modifier
        + system.proficiency_bonus(check, hard.player)
        + system.d20_test_modifier(status, corpus)
    )
    if check.save and system.save_auto_fail(check.stat, status, corpus):
        computed_mod = system.compute_modifier(stat_value)
        total_mod = computed_mod + flat_modifier
        # raw_roll 0 marks a save that failed without a roll.
        return CheckResult(
            stat=check.stat,
            target=check.target,
            computed_mod=computed_mod,
            flat_mod=flat_modifier,
            modifier=total_mod,
            raw_roll=0,
            total=total_mod,
            margin=total_mod - check.target,
            success=False,
            advantage=False,
            disadvantage=False,
        )
    return system.roll_check(
        check.stat,
        stat_value,
        check.target,
        flat_modifier=flat_modifier,
        params=_stat_check_params(check, system, hard, corpus),
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

        system = get_system_for_corpus(corpus)
        stat_value = system.stat_value_for_check(check.stat, hard.player)
        if stat_value is None:
            return True

        cr = _roll_stat_check(check, system, stat_value, hard, corpus)

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
    inter: Resolvable,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    encounter_trigger: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_type: str = "interaction",
    source_id: str | None = None,
    attempt_key: str | None = None,
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

    effective_source_id = source_id if source_id is not None else inter.id
    effective_attempt_key = attempt_key if attempt_key is not None else effective_source_id

    passed = _resolve_checkable(
        inter,
        hard=hard, soft=soft, corpus=corpus, room_id=room_id,
        changes=changes, narrative=narrative,
        revealed_hints=revealed_hints, rolls=rolls,
        state_manager=state_manager, resolution=resolution,
        source_id=effective_source_id, source_type=source_type,
        track_attempts=True, attempt_key=effective_attempt_key,
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
    parent: Resolvable | None = None,
) -> ResolutionResult:
    """Resolve a using_results override, which may carry its own check.

    The override replaces what it specifies and inherits the rest from the
    parent Resolvable: a check-only override resolves its own check but
    falls back to the parent's success/failure branches.
    """
    if override.check:
        # Build a synthetic Interaction from the override for check resolution
        synthetic_inter = Interaction(
            id=source_id or "_using_override",
            description="",
            check=override.check,
            success=override.success if override.success is not None else (
                parent.success if parent is not None else None
            ),
            failure=override.failure if override.failure is not None else (
                parent.failure if parent is not None else None
            ),
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
    if result.add_item or result.add_item_count:
        added = _merge_item_counts(result.add_item, result.add_item_count)
        for item_id, count in added.items():
            current = hard.player.inventory.get(item_id, 0) if hard is not None else 0
            if not _is_stackable(item_id, corpus) and current > 0:
                log.debug(
                    "_apply_result: skipping duplicate add of non-stackable item '%s'",
                    item_id,
                )
                continue
            if not _is_stackable(item_id, corpus) and count > 1:
                log.debug(
                    "_apply_result: skipping add of non-stackable item '%s' with count %d",
                    item_id, count,
                )
                continue
            changes.inventory_added[item_id] = changes.inventory_added.get(item_id, 0) + count
            changes.inventory_added_sources[item_id] = item_origin
            # For non-stackable items, if the item exists in a world
            # container, remove it to prevent duplication.  Stackable
            # items are left alone: add_item_count on a stackable is a
            # materialization grant (quest reward, reaction effect, etc.),
            # not a "move from world" operation.
            if (hard is not None and corpus is not None
                    and not _is_stackable(item_id, corpus)):
                room_id = hard.player.location
                if room_id:
                    loc = _locate_world_item(hard, corpus, room_id, item_id)
                    if loc is not None:
                        kind, container_id = loc
                        if kind == "room":
                            changes.room_contains_removed.setdefault(
                                container_id, {}
                            )[item_id] = count
                        else:
                            changes.entity_contains_removed.setdefault(
                                container_id, {}
                            )[item_id] = count
    if result.remove_item or result.remove_item_count:
        removed = _merge_item_counts(result.remove_item, result.remove_item_count)
        for item_id, count in removed.items():
            current = hard.player.inventory.get(item_id, 0) if hard is not None else 0
            if count > current:
                log.debug(
                    "_apply_result: skipping remove of '%s' (need %d, have %d)",
                    item_id, count, current,
                )
                continue
            changes.inventory_removed[item_id] = changes.inventory_removed.get(item_id, 0) + count
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
    if result.increment_entity_state:
        for ent_id, deltas in result.increment_entity_state.items():
            merged = changes.increment_entity_state.setdefault(ent_id, {})
            for field, delta in deltas.items():
                merged[field] = merged.get(field, 0) + delta
    if result.increment_room_state:
        for room_id, deltas in result.increment_room_state.items():
            merged = changes.increment_room_state.setdefault(room_id, {})
            for field, delta in deltas.items():
                merged[field] = merged.get(field, 0) + delta
    if result.set_player_location is not None:
        changes.player_location = result.set_player_location
    if result.adjust_attitude and hard is not None and corpus is not None:
        for npc_id, delta in result.adjust_attitude.items():
            npc_entity = corpus.entities.get(npc_id)
            if npc_entity is None or npc_entity.type != "npc":
                continue
            guidelines = npc_entity.dialogue
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
                    current = 0
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
        changes.player_damage_delta = (
            (changes.player_damage_delta or 0) + dmg_total
        )
    if result.player_heal and corpus is not None:
        system = get_system_for_corpus(corpus)
        heal_total, _ = system.roll_damage(result.player_heal)
        if hard is not None:
            # Clamp to max HP, as with consumable healing.
            effective_hp = (hard.player.current_hp or 0) + (
                changes.player_hp_delta or 0
            )
            max_hp = system.compute_player_max_hp(hard, corpus)
            heal_total = max(0, min(heal_total, max_hp - effective_hp))
        existing = changes.player_hp_delta or 0
        changes.player_hp_delta = existing + heal_total
        if heal_total:
            changes.player_heal_delta = (
                (changes.player_heal_delta or 0) + heal_total
            )
    if result.apply_status_effect is not None and hard is not None:
        # Engine-owned runtime state (like combat state): mutate directly.
        apply_status_effect(
            result.apply_status_effect.target,
            result.apply_status_effect.id,
            result.apply_status_effect.rounds,
            hard, corpus, "result",
            events=resolution.events if resolution is not None else None,
        )
    if result.cure_status_effects and hard is not None:
        from mgmai.engine.status_effects import remove_status_effect
        for effect_id in result.cure_status_effects:
            remove_status_effect(
                "player", effect_id, hard, corpus, "interaction",
                resolution.events if resolution is not None else None,
            )
    if result.reveals:
        revealed_hints.append(result.reveals)
    # Inline game-over: propagate from any result (interaction, reaction,
    # encounter) by setting hard.game_over directly.
    if result.game_over is not None and hard is not None:
        hard.game_over = GameOverState(
            type=result.game_over.type,
            trigger=result.game_over.trigger_id,
        )


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
    chk: CheckResolution | Resolvable | GatedCheck | EncounterRule,
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
        system = get_system_for_corpus(corpus)
        stat_value = system.stat_value_for_check(check.stat, hard.player)
        if stat_value is None:
            if resolution is not None:
                resolution.error = f"Player has no '{check.stat}' stat"
            return False
        cr = _roll_stat_check(check, system, stat_value, hard, corpus)
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
    room_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Any | None:
    if entity_id in hard.room_contains.get(room_id, {}):
        return corpus.entities.get(entity_id)
    return None


def _find_nested_entity(
    entity_id: str,
    room_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Any | None:
    """Find an entity nested inside a container in the room, when visible.

    Walks the containment tree rooted at room-level entities.  Hidden
    entities and the contents of closed containers are not visible, so
    they cannot be targeted — mirroring what the briefing shows.
    """
    stack: list[str] = [
        eid
        for eid, count in hard.room_contains.get(room_id, {}).items()
        if count > 0
    ]
    visited: set[str] = set(stack)
    while stack:
        container_id = stack.pop()
        if not _container_is_open(container_id, hard, corpus):
            continue
        for cid, count in hard.entity_contains.get(container_id, {}).items():
            if count <= 0 or cid in visited:
                continue
            visited.add(cid)
            if hard.entity_states.get(cid, {}).get("hidden", False):
                continue
            if cid == entity_id:
                return corpus.entities.get(entity_id)
            stack.append(cid)
    return None


def _find_entity_in_room_followers(
    entity_id: str,
    room_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Any | None:
    """Like _find_entity_in_room but also matches following NPCs and
    inventory items (so the player can interact with items they carry)."""
    result = _find_entity_in_room(entity_id, room_id, hard, corpus)
    if result is not None:
        return result
    # Entities nested inside containers in the room (e.g. a crate stowed
    # behind the bar) are visible in the briefing and targetable.
    result = _find_nested_entity(entity_id, room_id, hard, corpus)
    if result is not None:
        return result
    follower_ids = get_following_npc_ids(hard, corpus)
    if entity_id in follower_ids:
        return corpus.entities.get(entity_id)
    if entity_id in hard.player.inventory:
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

    Returns a dict with accumulated 'revealed_hints' and 'rolls'.
    """
    revealed_hints: list[str] = []
    rolls: list[dict[str, Any]] = []

    for event in events:
        if event.condition and not evaluate(event.condition, hard, soft, corpus):
            continue
        if event.rigorous_only and not getattr(action, "rigorous", False):
            continue

        if event.check:
            ex_result = _resolve_interaction(
                event, hard, soft, corpus, room_id,
                state_manager=state_manager,
                resolution=resolution,
                source_type="examine",
                source_id=f"_on_examine_{event.id}",
            )
            if ex_result.hard_changes:
                changes.merge(ex_result.hard_changes)
            if ex_result.triggered_narration:
                narrative.extend(ex_result.triggered_narration)
            if ex_result.revealed_hints:
                revealed_hints.extend(ex_result.revealed_hints)
            if ex_result.rolls:
                rolls.extend(ex_result.rolls)
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
        "rolls": rolls,
    }


def _check_follower_blacklist(
    hard: HardGameState,
    corpus: ModuleCorpus,
    target_room: str,
    narrative: list[str],
    changes: HardStateChanges,
) -> None:
    """Check if any following NPC refuses to enter the target room.

    If an NPC's follower.blacklist includes the target room, clear their
    ``following`` state and add a narrative note.  The state change is
    routed through *changes* (rather than mutating ``hard`` directly) so
    that an ``entity_state.changed`` event fires for it, consistent with
    every other entity-state mutation.
    """
    for eid, state in hard.entity_states.items():
        if not state.get("following"):
            continue
        entity = corpus.entities.get(eid)
        if entity is None:
            continue
        if entity.follower is None:
            continue
        if target_room in entity.follower.blacklist:
            changes.entity_state_changes.setdefault(eid, {})["following"] = False
            narrative.append(
                f"{entity.description.split('.')[0]} refuses to follow you "
                f"and stays behind."
            )


def _resolve_use_ability(
    action: UseAbilityAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a top-level ``use_ability`` action outside combat.

    Self/ally heal/on-cast abilities resolve directly.  Enemy-targeted
    abilities start combat (mirroring interact/attack), pulling in the
    target's combat_group.
    """
    from mgmai.engine.combat import (
        enter_combat,
        resolve_combat_enemies,
        resolve_out_of_combat_ability,
    )

    result = resolve_out_of_combat_ability(action, hard, corpus)

    # Enemy-targeted abilities return success=True with combat_triggered=True:
    # the spell is deferred to the player's first combat turn, and combat
    # starts now (mirroring interact/attack).
    if result.get("combat_triggered"):
        target_id = action.target
        target_entity = _find_entity_in_room_followers(
            target_id, hard.player.location, hard, corpus
        )
        if target_entity is None or target_entity.combat is None:
            return ResolutionResult(
                success=False,
                error=(
                    f"Cannot start combat with '{target_id}' "
                    f"(not present or not a valid combatant)"
                ),
                room_after_id=hard.player.location,
            )
        enemies = resolve_combat_enemies([target_id], None, hard, corpus)
        if not enemies:
            return ResolutionResult(
                success=False,
                error=(
                    f"Cannot start combat with '{target_id}' "
                    f"(not present or not a valid combatant)"
                ),
                room_after_id=hard.player.location,
            )
        entry = enter_combat(
            enemies, hard, corpus, soft=soft, state_manager=state_manager,
            engage_source=target_id,
        )
        events: list[tuple[str, dict[str, Any]]] = [
            ("combat.started", {"combatant_ids": enemies}),
        ]
        events.extend(entry.get("events") or [])
        if entry.get("combat_ended_reason"):
            events.append(("combat.ended", {
                "reason": entry["combat_ended_reason"],
            }))
        return ResolutionResult(
            success=True,
            hard_changes=entry["hard_changes"],
            combat_triggered=True,
            combat_log=entry["combat_log"],
            player_died=entry.get("player_died", False),
            room_after_id=hard.player.location,
            events=events,
        )

    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    events = list(result.get("events") or [])
    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        player_died=result.get("player_died", False),
        room_after_id=hard.player.location,
        events=events,
    )


def _resolve_combat_action(
    action: CombatAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a CombatAction via the combat module.

    Out of combat, an ``attack`` is equivalent to the generic
    ``interact``/``attack`` interaction: it starts combat with the
    target.  (LLM Call 1 naturally emits ``combat``/``attack`` for
    out-of-combat attack commands, and the engine already knows
    exactly what that means.)
    """
    from mgmai.engine.combat import resolve_combat_turn

    combat = hard.combat
    if (
        (combat is None or not combat.active)
        and action.combat_action == "attack"
    ):
        return resolve_interact(
            InteractAction(
                action_type="interact",
                target=action.target,
                interaction_id="attack",
                detail=action.detail,
            ),
            hard, soft, corpus, state_manager,
        )

    result = resolve_combat_turn(
        action, hard, corpus, soft=soft, state_manager=state_manager
    )
    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    events: list[tuple[str, dict[str, Any]]] = list(result.get("events") or [])
    if result.get("combat_ended_reason"):
        events.append(("combat.ended", {
            "reason": result["combat_ended_reason"],
        }))

    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        player_died=result.get("player_died", False),
        warnings=list(result.get("warnings") or []),
        room_after_id=hard.player.location,
        events=events,
        # A continuation segment (budget remains, turn open) does NOT cost
        # the turn: no engine persistent tick, no turn.end, no turn_count
        # bump.  Only a segment that actually ended the turn does.
        costs_turn=bool(result.get("turn_ended", True)),
    )


def _resolve_combat_pass(
    action: WaitAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a turn pass (wait during combat) via the combat module."""
    from mgmai.engine.combat import resolve_combat_turn

    result = resolve_combat_turn(action, hard, corpus, soft=soft, state_manager=state_manager)
    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    events: list[tuple[str, dict[str, Any]]] = list(result.get("events") or [])
    if result.get("combat_ended_reason"):
        events.append(("combat.ended", {
            "reason": result["combat_ended_reason"],
        }))

    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        player_died=result.get("player_died", False),
        warnings=list(result.get("warnings") or []),
        room_after_id=hard.player.location,
        events=events,
        # A continuation segment (budget remains, turn open) does NOT cost
        # the turn: no engine persistent tick, no turn.end, no turn_count
        # bump.  Only a segment that actually ended the turn does.
        costs_turn=bool(result.get("turn_ended", True)),
    )


def _resolve_combat_environmental(
    action: InteractAction | TransferAction | ExamineAction | GearAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a non-combat action during combat as the player's turn.

    Covers ``interact`` (non-attack), ``transfer``, rigorous ``examine``,
    and weapon ``gear`` swaps while combat is active.  Each action costs
    budget on the player's turn: start-of-turn status processing and
    positioning assertions apply, the normal resolver resolves the action
    itself, then the §3.3 turn-end rule decides whether the turn stays
    open (a free object interaction or a remaining bonus action) or the
    enemies take their turns.

    A ``gear`` action is the player's one free object interaction per
    turn; a second object interaction (or a ``gear`` after the free
    interaction is spent) costs the action (Utilize).  An ``interact``
    tagged ``interaction_cost: "free"`` likewise consumes the free
    interaction and the turn continues; potions and other carried
    ``usable_items`` always require an action.  ``transfer`` and rigorous
    ``examine`` cost the action.

    A failed validation returns without running NPC turns (failed
    validations never cost a turn — consistent with the engine's failed
    resolution path).  A Result that moves the player to another room
    ends combat immediately (reason ``"fled"``, no NPC turns after).  An
    encounter trigger on the delegate's result flows through the engine's
    normal encounter path, which merges reinforcements into the active
    combat (NPC turns for the current round still proceed first, with the
    pre-merge roster).
    """
    from mgmai.engine.combat import (
        _begin_player_turn,
        _clear_status_effects,
        _end_player_turn,
        _player_died,
        meaningful_budget_remains,
    )

    combat = hard.combat
    system = get_system_for_corpus(corpus)

    hard_changes = HardStateChanges()
    combat_log: list[CombatLogEntry] = []
    begin_events: list[tuple[str, dict[str, Any]]] = []
    end_events: list[tuple[str, dict[str, Any]]] = []
    warnings: list[str] = []

    player_skips, died_to_oa = _begin_player_turn(
        action, combat, hard, corpus, soft, state_manager,
        system, hard_changes, combat_log, begin_events, warnings,
    )

    budget = combat.player_budget
    # What does this action cost?  ``"free"`` (one per turn, turn stays
    # open) or ``"action"`` (the Utilize action).
    if action.action_type == "gear":
        cost = "free" if not budget.free_interaction_used else "action"
    elif action.action_type == "interact":
        cost = getattr(action, "interaction_cost", "action") or "action"
        if cost == "free":
            if budget.free_interaction_used:
                return ResolutionResult(
                    success=False,
                    error=(
                        "The free object interaction was already used this "
                        "turn — a second one would cost the action"
                    ),
                )
            # Potions and other carried usable items always require an
            # action to use (SRD: "Some magic items and other special
            # objects always require an action to use").
            target = action.target
            if target in hard.player.inventory or target in hard.player.equipped:
                return ResolutionResult(
                    success=False,
                    error=(
                        "Items such as potions always require an action to "
                        "use — set interaction_cost to \"action\""
                    ),
                )
    else:
        cost = "action"

    delegate: ResolutionResult | None = None
    game_over = False
    combat_ended = False
    end_reason: str | None = None

    if died_to_oa:
        game_over = True
        end_reason = "defeat"
    elif not player_skips:
        if cost == "action" and budget.action_used:
            return ResolutionResult(
                success=False,
                error=(
                    "The action was already used this turn — you can only "
                    "take one action per turn"
                ),
            )
        # Log the player's action so the combat prefix can summarize it.
        interact_target = getattr(action, "target", None)
        combat_log.append(
            CombatLogEntry(
                round=combat.round_number,
                actor="player",
                action=action.action_type,
                target=interact_target,
                target_is_item=(
                    action.action_type == "interact"
                    and interact_target is not None
                    and (
                        interact_target in hard.player.inventory
                        or interact_target in hard.player.equipped
                    )
                ),
            )
        )
        if action.action_type == "interact":
            delegate = resolve_interact(action, hard, soft, corpus, state_manager)
        elif action.action_type == "transfer":
            delegate = resolve_transfer(action, hard, soft, corpus, state_manager)
        elif action.action_type == "examine":
            delegate = resolve_examine(action, hard, soft, corpus, state_manager)
        else:
            delegate = resolve_gear(action, hard, soft, corpus, state_manager)

        if not delegate.success:
            # Failed validation never costs a turn: no NPC turns.
            return delegate

        # Merge the delegate's hard changes (e.g. a potion's heal and
        # item consumption) into hard_changes BEFORE NPC turns, so that
        # _end_player_turn sees the correct effective player HP.  Without
        # this, NPC attacks compute effective HP without the heal and
        # may spuriously log a "player death" that didn't actually happen.
        if delegate.hard_changes:
            hard_changes.merge(delegate.hard_changes)

        # A healing interaction (e.g. drinking a potion) otherwise leaves
        # no trace in the combat log: the bare "interact" entry above
        # carries no amount, and the heal only feeds the net HP delta.
        # Log it as a heal entry so the narrator and indicators can
        # anchor to the actual event.
        if (
            action.action_type == "interact"
            and delegate.hard_changes
            and delegate.hard_changes.player_heal_delta
        ):
            heal_source = corpus.entities.get(getattr(action, "target", "") or "")
            combat_log.append(
                CombatLogEntry(
                    round=combat.round_number,
                    actor="player",
                    action="heal",
                    target="player",
                    attack_name=(
                        (heal_source.name if heal_source else None)
                        or getattr(action, "target", None)
                    ),
                    damage=delegate.hard_changes.player_heal_delta,
                    remaining_hp=(
                        (hard.player.current_hp or 0)
                        + (hard_changes.player_hp_delta or 0)
                    ),
                )
            )

        # Consume the budget the resolved action cost.
        if cost == "free":
            budget.free_interaction_used = True
        else:
            budget.action_used = True

        # Hazard checks on the result, before the turn-end decision.
        if hard.game_over is not None:
            # An inline (scripted) game-over ended everything; no NPC turns.
            game_over = True
            end_reason = "defeat"
        elif hard.combat is None or not hard.combat.active:
            # The resolution itself ended combat already.
            combat_ended = True
        elif (
            delegate.hard_changes
            and delegate.hard_changes.player_location
            and delegate.hard_changes.player_location != hard.player.location
        ):
            # The Result moved the player to another room: combat ends.
            combat_ended = True
            end_reason = "fled"

    # --- Turn-end decision (§3.3) ---
    if game_over or combat_ended:
        combat.log.extend(combat_log)
        _clear_status_effects(hard, corpus, end_events)
        hard.combat = None
        turn_ended = True
    elif player_skips:
        # A ``skip_turn`` status effect consumed the player's action: the
        # turn ends and NPC turns proceed.
        game_over, combat_ended, end_reason = _end_player_turn(
            combat, hard, corpus, soft, state_manager, system,
            hard_changes, combat_log, end_events,
        )
        turn_ended = True
    elif meaningful_budget_remains(combat, hard, corpus):
        # The turn stays open: budget remains (e.g. a free interaction
        # taken before the real action).  No NPC turns, no round advance.
        combat.log.extend(combat_log)
        combat.turn_continuation = True
        turn_ended = False
    else:
        game_over, combat_ended, end_reason = _end_player_turn(
            combat, hard, corpus, soft, state_manager, system,
            hard_changes, combat_log, end_events,
        )
        turn_ended = True

    if end_reason is not None:
        end_events.append(("combat.ended", {"reason": end_reason}))

    if delegate is None:
        # The player was stunned or died to a provoked OA before acting.
        return ResolutionResult(
            success=True,
            hard_changes=hard_changes,
            combat_log=combat_log,
            player_died=_player_died(hard, hard_changes),
            warnings=warnings,
            room_after_id=hard.player.location,
            events=begin_events + end_events,
            costs_turn=turn_ended,
        )

    # hard_changes already includes the delegate's changes (merged
    # before NPC turns so the effective HP was correct).
    return ResolutionResult(
        success=True,
        hard_changes=hard_changes,
        triggered_narration=delegate.triggered_narration,
        revealed_hints=delegate.revealed_hints,
        encounter_trigger=delegate.encounter_trigger,
        combat_log=combat_log,
        player_died=_player_died(hard, hard_changes),
        warnings=warnings + delegate.warnings,
        room_after_id=delegate.room_after_id,
        rolls=delegate.rolls,
        soft_content_takes=delegate.soft_content_takes,
        soft_item_proposals=delegate.soft_item_proposals,
        events=begin_events + delegate.events + end_events,
        immediate_changes=delegate.immediate_changes,
        # A continuation segment (budget remains, turn open) does NOT cost
        # the turn: no engine persistent tick, no turn.end, no turn_count
        # bump.  Only a segment that actually ended the turn does.
        costs_turn=turn_ended,
    )


def _resolve_combat_flee(
    action: MoveAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    soft: SoftGameState,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a flee attempt (move during combat) via the combat module."""
    from mgmai.engine.combat import resolve_combat_turn

    result = resolve_combat_turn(action, hard, corpus, soft=soft, state_manager=state_manager)
    if not result["success"]:
        return ResolutionResult(
            success=False,
            error=result.get("error"),
        )

    events: list[tuple[str, dict[str, Any]]] = list(result.get("events") or [])
    if result.get("combat_ended_reason"):
        events.append(("combat.ended", {
            "reason": result["combat_ended_reason"],
        }))

    return ResolutionResult(
        success=True,
        hard_changes=result["hard_changes"],
        combat_log=result["combat_log"],
        player_died=result.get("player_died", False),
        warnings=list(result.get("warnings") or []),
        room_after_id=(
            result["hard_changes"].player_location
            if result["hard_changes"] and result["hard_changes"].player_location
            else hard.player.location
        ),
        events=events,
        # A continuation segment (budget remains, turn open) does NOT cost
        # the turn: no engine persistent tick, no turn.end, no turn_count
        # bump.  Only a segment that actually ended the turn does.
        costs_turn=bool(result.get("turn_ended", True)),
    )


def _validate_gear_changes(
    action: GearAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
    *,
    combat_check: bool = True,
) -> str | None:
    """Validate a gear change, shared by :func:`resolve_gear` (which
    returns the validated result as ``HardStateChanges``) and the
    attack-carried equip/unequip path (which applies it to ``hard``
    immediately, §4.2).

    Returns an error message on failure, ``None`` when the change is valid
    (the whole action is atomic — any failure rejects everything).

    Logic:
    0. Validate every unequip target is currently equipped.
    1. For each equip target, in order:
       a. Validate target in inventory.
       b. Look up EquipBlock from corpus; reject if None.
       c. Build incompatible tag set.
       d. Check conflicts against the evolving equipped set (which includes
          any items already equipped by this same action).
       e. Check max_equipped for the slot tag group.
    """
    # During combat only weapon swaps are allowed (matching the attack
    # code's weapon detection); changing armor or other gear mid-fight is
    # rejected.  Turn-costing behavior arrives via the combat wrapper in
    # resolve_action.
    if combat_check and hard.combat is not None and hard.combat.active:
        for target in list(action.equip_targets) + list(action.unequip_targets):
            item_entity = corpus.entities.get(target)
            eb = item_entity.equip_block if item_entity is not None else None
            if eb is None or "weapon" not in eb.equip_tags:
                return (
                    f"Cannot change '{target}' during combat: "
                    "only weapon swaps are allowed"
                )

    # Step 0: Validate unequip_targets
    for uid in action.unequip_targets:
        if uid not in hard.player.equipped:
            return f"Cannot unequip '{uid}': not currently equipped"

    # Post-unequip equipped set; grows as each equip target is validated so
    # that items equipped together conflict-check against each other.
    still_equipped = [eid for eid in hard.player.equipped if eid not in action.unequip_targets]

    # Step 1: Validate each equip target against the evolving equipped set
    for target in action.equip_targets:
        if target not in hard.player.inventory:
            return f"Item '{target}' is not in your inventory"

        item_entity = corpus.entities.get(target)
        if item_entity is None:
            return f"Item '{target}' not found in corpus"
        eb = item_entity.equip_block
        if eb is None:
            return f"Item '{target}' cannot be equipped (no equip_block)"

        slot_tag = eb.equip_tags[0] if eb.equip_tags else None

        # Compute the slot group's max_equipped across the evolving set
        # (the highest value among all items sharing the slot tag).
        max_limit = eb.max_equipped
        if slot_tag is not None:
            for eid in still_equipped:
                eq_entity = corpus.entities.get(eid)
                if eq_entity and eq_entity.equip_block and eq_entity.equip_block.equip_tags and eq_entity.equip_block.equip_tags[0] == slot_tag:
                    other_max = eq_entity.equip_block.max_equipped
                    if other_max is None:
                        max_limit = None
                    elif max_limit is not None:
                        max_limit = max(max_limit, other_max)

        # Default incompatibility: items sharing the same *single-item*
        # slot conflict (one helmet, one armour).  A multi-item slot
        # (max_equipped > 1, e.g. two rings or two weapons) does NOT
        # self-conflict — the max_equipped cap enforces the limit instead.
        incompatible = set(eb.incompatible_with)
        if not incompatible and slot_tag is not None and max_limit == 1:
            incompatible.add(slot_tag)

        # Check conflicts with equipped items
        new_tags = set(eb.equip_tags)
        for eid in still_equipped:
            eq_entity = corpus.entities.get(eid)
            if eq_entity is None or eq_entity.equip_block is None:
                continue
            eq_tags = set(eq_entity.equip_block.equip_tags)
            if eq_tags & incompatible:
                return (
                    f"Cannot equip '{target}': conflicts with equipped item '{eid}' "
                    f"(tags: {eq_tags & incompatible})"
                )
            # Reverse direction: the equipped item's *explicit*
            # incompatible_with may cover the new item's tags (e.g. a
            # two-handed weapon rejects a second weapon or a shield
            # regardless of equip order).  The default slot self-conflict
            # is not applied in reverse — the max_equipped cap handles it.
            eq_incompatible = set(eq_entity.equip_block.incompatible_with)
            if new_tags & eq_incompatible:
                return (
                    f"Cannot equip '{target}': equipped item '{eid}' "
                    f"conflicts with it (tags: {new_tags & eq_incompatible})"
                )

        # Check max_equipped
        if max_limit is not None:
            current_count = sum(
                1 for eid in still_equipped
                if (_e := corpus.entities.get(eid)) and _e.equip_block
                and _e.equip_block.equip_tags and _e.equip_block.equip_tags[0] == slot_tag
            )
            if current_count >= max_limit:
                return (
                    f"Cannot equip '{target}': slot '{slot_tag}' limit "
                    f"({max_limit}) would be exceeded (currently {current_count})"
                )

        still_equipped.append(target)

    return None


def _apply_gear_changes_immediate(
    action: GearAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    immediate_changes: HardStateChanges | None = None,
) -> str | None:
    """Validate and immediately apply a gear change to ``hard``.

    Used by the attack-carried equip/unequip path (§4.2): the swap must be
    visible to the attack roll in the same engine call, so it mutates
    ``hard.player`` in place and emits the ``equipment.changed`` event.  It
    deliberately produces **no** ``HardStateChanges`` for the swap itself —
    the state-manager apply is not idempotent for gear moves, and a second
    apply would move the items back.

    The ``equipment.changed`` event and any immediate reactions to it are
    drained into the caller's collectors: pass the combat turn's ``events``
    list so deferred reactions fire at end of turn, and its ``hard_changes``
    as ``immediate_changes`` so immediate-reaction state mutations are
    applied (the combat pipeline has no separate immediate-changes
    channel).  Without collectors the event would be lost.

    Returns an error message on validation failure (nothing applied),
    ``None`` on success.
    """
    error = _validate_gear_changes(action, hard, corpus)
    if error is not None:
        return error

    for target in action.equip_targets:
        hard.player.inventory[target] -= 1
        if hard.player.inventory[target] <= 0:
            del hard.player.inventory[target]
        hard.player.equipped.append(target)
    for uid in action.unequip_targets:
        hard.player.equipped.remove(uid)
        hard.player.inventory[uid] = hard.player.inventory.get(uid, 0) + 1

    result = ResolutionResult(
        success=True,
        hard_changes=HardStateChanges(),
        room_after_id=hard.player.location,
    )
    _emit_event(
        "equipment.changed",
        {"added": action.equip_targets, "removed": action.unequip_targets},
        hard, soft, corpus, state_manager, result,
    )
    if events is not None:
        events.extend(result.events)
    if immediate_changes is not None and result.immediate_changes:
        immediate_changes.merge(result.immediate_changes)
    return None


def resolve_gear(
    action: GearAction,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    state_manager: Any | None = None,
) -> ResolutionResult:
    """Resolve a gear action (equip and/or unequip) with tag conflict
    validation.

    On success: move equip targets from inventory to equipped, unequip
    targets from equipped to inventory.  The whole action is atomic: any
    failure rejects everything.
    """
    room_id = hard.player.location

    error = _validate_gear_changes(action, hard, corpus)
    if error is not None:
        return ResolutionResult(success=False, error=error)

    # Step 2: Success — apply all movements
    changes = HardStateChanges()
    for target in action.equip_targets:
        changes.inventory_removed[target] = changes.inventory_removed.get(target, 0) + 1
        changes.inventory_removed_reasons[target] = "equip"
        changes.equipped_added.append(target)
    for uid in action.unequip_targets:
        changes.equipped_removed.append(uid)
        changes.inventory_added[uid] = changes.inventory_added.get(uid, 0) + 1
        changes.inventory_added_sources[uid] = "unequip"
    changes.equipment_changed = True

    result = ResolutionResult(
        success=True,
        hard_changes=changes,
        room_after_id=room_id,
    )
    _emit_event(
        "equipment.changed",
        {"added": action.equip_targets, "removed": action.unequip_targets},
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
    in_combat = hard.combat is not None and hard.combat.active

    # During combat, move actions become flee attempts
    if action_type == "move" and in_combat:
        return _resolve_combat_flee(action, hard, corpus, soft, state_manager)
    # During combat, wait actions pass the player's turn
    if action_type == "wait" and in_combat:
        return _resolve_combat_pass(action, hard, corpus, soft, state_manager)
    # During combat, use_ability resolves via the combat turn pipeline
    # (action economy, bonus-action rules, concentration, engagement).
    if action_type == "use_ability" and in_combat:
        from mgmai.engine.combat import resolve_combat_turn
        result = resolve_combat_turn(action, hard, corpus, soft=soft, state_manager=state_manager)
        if not result["success"]:
            return ResolutionResult(
                success=False,
                error=result.get("error"),
            )
        events: list[tuple[str, dict[str, Any]]] = list(result.get("events") or [])
        if result.get("combat_ended_reason"):
            events.append(("combat.ended", {
                "reason": result["combat_ended_reason"],
            }))
        return ResolutionResult(
            success=True,
            hard_changes=result["hard_changes"],
            combat_log=result["combat_log"],
            player_died=result.get("player_died", False),
            warnings=list(result.get("warnings") or []),
            room_after_id=hard.player.location,
            events=events,
            # A bonus-action segment does NOT cost the turn: the turn stays
            # open and the follow-up main action shares it.
            costs_turn=bool(result.get("turn_ended", True)),
        )

    if in_combat:
        # An attack interaction during combat is a normal combat attack —
        # never re-enter combat mid-combat (which would reroll initiative
        # and wipe engagement/cooldown state).
        if action_type == "interact" and action.interaction_id == "attack":
            return _resolve_combat_action(
                CombatAction(
                    action_type="combat",
                    combat_action="attack",
                    target=action.target,
                    detail=action.detail,
                    follow_up=action.follow_up,
                    soft_state_patches=action.soft_state_patches,
                    positioning=action.positioning,
                ),
                hard, corpus, soft, state_manager,
            )
        # Other environmental actions cost the player's combat turn:
        # they resolve normally, then the enemies take their turns.
        if action_type in ("interact", "transfer", "gear"):
            return _resolve_combat_environmental(
                action, hard, soft, corpus, state_manager
            )
        if action_type == "examine" and action.rigorous:
            return _resolve_combat_environmental(
                action, hard, soft, corpus, state_manager
            )
        # Non-rigorous examine stays free (no NPC turns); talk falls
        # through to resolve_talk, which rejects it during combat;
        # ooc_discussion is a no-op as today.

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
        return _resolve_combat_action(action, hard, corpus, soft, state_manager)
    elif action_type == "use_ability":
        return _resolve_use_ability(action, hard, corpus, soft, state_manager)
    elif action_type == "wait":
        return resolve_wait(action, hard, soft, corpus)
    elif action_type == "rest":
        return resolve_rest(action, hard, soft, corpus, state_manager)
    elif action_type == "gear":
        return resolve_gear(action, hard, soft, corpus, state_manager)
    elif action_type == "ooc_discussion":
        return resolve_ooc(action, hard, soft, corpus)
    else:
        return ResolutionResult(
            success=False,
            error=f"Unknown action type: {action_type}",
        )
