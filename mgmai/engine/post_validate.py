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

from typing import Any

from mgmai.engine.conditions import evaluate
from mgmai.engine.utils import (
    _match_soft_content,
    _normalize_item_name,
    present_entity_ids,
)
from mgmai.models.actions import (
    EngineResult,
    HardStateChanges,
    RevelationApplied,
    SoftItemProposal,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.narration import AttitudeChange, SoftItemAdjudication
from mgmai.models.soft_state import KnowledgeEntry, SoftGameState, SoftStateNote
from mgmai.state.manager import StateManager, reconcile_improvised_weapon


def _is_hard_entity_collision(name: str, corpus: ModuleCorpus) -> bool:
    """Return True if *name* matches a hard entity ID or display name."""
    normalized = _normalize_item_name(name)
    for eid, entity in corpus.entities.items():
        if _normalize_item_name(eid) == normalized:
            return True
        if entity.name and _normalize_item_name(entity.name) == normalized:
            return True
    return False


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
            if room is None or ent_id not in hard.room_contains.get(room_id, {}):
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


def post_validate_notes(
    notes: list[SoftStateNote],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> tuple[list[SoftStateNote], list[dict[str, Any]]]:
    """Validate soft-state notes from Call 2.

    Returns a tuple of (applied_notes, rejected_entries).  State is not
    mutated here; the caller applies the accepted notes via the state
    manager.
    """
    applied: list[SoftStateNote] = []
    rejected: list[dict[str, Any]] = []

    present_room = hard.player.location
    present_entities = present_entity_ids(hard, corpus)

    for note in notes:
        reason = None

        if note.field == "room_note":
            # room_note always attaches to the player's current room.
            if present_room not in corpus.rooms:
                reason = f"Invalid current room: {present_room}"
            elif not note.new_value.strip():
                reason = "room_note new_value must be a non-empty string"
            else:
                contradiction = _check_note_contradiction(
                    note.new_value, present_room, hard, corpus)
                if contradiction:
                    reason = contradiction
        elif note.field == "entity_note":
            eid = note.entity_id
            entity = corpus.entities.get(eid) if eid else None
            is_player = eid == "player" or (
                entity is not None and entity.type == "player")
            if not eid or (entity is None and not is_player):
                reason = f"Invalid entity_id: {eid}"
            elif not note.new_value.strip():
                reason = "entity_note new_value must be a non-empty string"
            else:
                entity_state = hard.entity_states.get(eid, {})
                if entity_state.get("alive") is False:
                    reason = f"Entity '{eid}' is dead; notes are not allowed"
                elif not is_player and eid not in present_entities:
                    # The player entity (type == "player") is always a
                    # valid target — it carries "global" notes that follow
                    # the player.  Otherwise the entity must be present in
                    # the current room (directly, nested in a container, or
                    # a following NPC).
                    reason = (
                        f"Entity '{eid}' is not present in room "
                        f"'{present_room}'; entity notes are only allowed "
                        f"on entities in the current room or on the "
                        f"player entity"
                    )
                else:
                    contradiction = _check_note_contradiction(
                        note.new_value, None, hard, corpus)
                    if contradiction:
                        reason = contradiction

        if not note.reason or not note.reason.strip():
            reason = "reason is empty"

        if reason:
            rejected.append({
                "note": note.model_dump(),
                "reason": reason,
            })
        else:
            applied.append(note)

    return applied, rejected


def post_validate_soft_items(
    adjudications: list[SoftItemAdjudication],
    proposals: list[SoftItemProposal],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> tuple[list[SoftItemAdjudication], list[dict[str, Any]], HardStateChanges]:
    """Validate and apply item adjudications from Call 2.

    Returns a tuple of (applied_adjudications, rejected_entries,
    hard_changes).  Soft-item state is mutated directly: accepted takes
    append to ``soft_inventory`` and decrement ``soft_contents`` on the
    source first (retrieval of placed items), with any remainder
    incrementing ``soft_items_taken`` (ambient extraction); accepted
    gives remove from ``soft_inventory`` and increment ``soft_contents``
    on the target; accepted examines have no state effect.

    Hard items (``item_kind == "hard"``) are deferred transfers to/from a
    living NPC.  On acceptance, the deferred hard move is accumulated into
    the returned ``hard_changes`` (the caller applies it via the state
    manager); on rejection, no move occurs.  Defense-in-depth: the source
    must still hold the item in the required quantity at apply time.
    """
    applied: list[SoftItemAdjudication] = []
    rejected: list[dict[str, Any]] = []
    hard_changes = HardStateChanges()

    valid_source_ids = set(corpus.rooms.keys()) | set(corpus.entities.keys()) | {"player"}
    pending = list(proposals)

    for adj in adjudications:
        reason: str | None = None
        matched_prop: SoftItemProposal | None = None

        if not adj.item_name or not adj.item_name.strip():
            reason = "item_name is empty"
        elif adj.action not in ("take", "give", "examine"):
            reason = f"invalid action: {adj.action}"
        elif not isinstance(adj.accepted, bool):
            reason = "accepted must be a boolean"
        elif not adj.accepted and (not adj.justification or not adj.justification.strip()):
            reason = "justification required when accepted is false"
        elif not adj.source_id or adj.source_id not in valid_source_ids:
            reason = f"invalid source_id: {adj.source_id}"
        elif adj.action == "give" and (
            not adj.target_id
            or (adj.target_id not in corpus.entities and adj.target_id not in corpus.rooms)
        ):
            reason = f"give action requires valid target_id: {adj.target_id}"
        else:
            match_index: int | None = None
            for i, prop in enumerate(pending):
                if (
                    _normalize_item_name(prop.item_name)
                    == _normalize_item_name(adj.item_name)
                    and prop.action == adj.action
                    and prop.source_id == adj.source_id
                    and prop.target_id == adj.target_id
                    and prop.count == adj.count
                ):
                    match_index = i
                    break
            if match_index is None:
                reason = "no matching soft_item_proposal"
            else:
                matched_prop = pending[match_index]
                if matched_prop.item_kind == "soft":
                    if _is_hard_entity_collision(adj.item_name, corpus):
                        reason = f"item_name '{adj.item_name}' collides with a hard entity"
                    elif adj.accepted and adj.action == "give":
                        available = sum(
                            1
                            for x in soft.soft_inventory
                            if _normalize_item_name(x) == _normalize_item_name(adj.item_name)
                        )
                        if available < adj.count:
                            reason = f"not enough '{adj.item_name}' in soft inventory to give"
                elif adj.accepted and adj.action == "give":
                    # Hard give: player must still hold the item.
                    available = hard.player.inventory.get(adj.item_name, 0)
                    if available < adj.count:
                        reason = f"not enough '{adj.item_name}' in inventory to give"
                elif adj.accepted and adj.action == "take":
                    # Hard take: the NPC source must still hold the item.
                    available = hard.entity_contains.get(adj.source_id, {}).get(adj.item_name, 0)
                    if available < adj.count:
                        reason = (
                            f"'{adj.item_name}' is no longer held by "
                            f"'{adj.source_id}'"
                        )

        if reason:
            rejected.append({
                "adjudication": adj.model_dump(),
                "reason": reason,
            })
            continue

        # Consume the matched proposal.
        if matched_prop is not None:
            pending.remove(matched_prop)

        applied.append(adj)

        if not adj.accepted:
            continue

        if matched_prop is not None and matched_prop.item_kind == "hard":
            # Apply the deferred hard move.
            if adj.action == "give":
                hard_changes.inventory_removed[adj.item_name] = (
                    hard_changes.inventory_removed.get(adj.item_name, 0) + adj.count
                )
                hard_changes.inventory_removed_reasons[adj.item_name] = "transfer"
                hard_changes.entity_contains_added.setdefault(
                    adj.target_id, {}
                )[adj.item_name] = adj.count
            elif adj.action == "take":
                hard_changes.inventory_added[adj.item_name] = (
                    hard_changes.inventory_added.get(adj.item_name, 0) + adj.count
                )
                hard_changes.inventory_added_sources[adj.item_name] = "transfer"
                hard_changes.entity_contains_removed.setdefault(
                    adj.source_id, {}
                )[adj.item_name] = adj.count
            # Hard examines do not occur (examine targets are soft items).
            continue

        if adj.action == "take":
            # Placed items on the source are retrieved first — retrieval is
            # not extraction and must not pollute the depletion signal.
            remaining = adj.count
            contents = soft.soft_contents.get(adj.source_id)
            if contents:
                key, _placed = _match_soft_content(contents, adj.item_name)
                if key is not None:
                    retrieved = min(contents[key], remaining)
                    contents[key] -= retrieved
                    remaining -= retrieved
                    if contents[key] <= 0:
                        del contents[key]
                    if not contents:
                        del soft.soft_contents[adj.source_id]
            if remaining:
                taken = soft.soft_items_taken.setdefault(adj.source_id, {})
                taken[adj.item_name] = taken.get(adj.item_name, 0) + remaining
            for _ in range(adj.count):
                soft.soft_inventory.append(adj.item_name)
        elif adj.action == "give":
            removed = 0
            new_inventory: list[str] = []
            for item in soft.soft_inventory:
                if (
                    removed < adj.count
                    and _normalize_item_name(item) == _normalize_item_name(adj.item_name)
                ):
                    removed += 1
                else:
                    new_inventory.append(item)
            soft.soft_inventory = new_inventory
            if adj.target_id:
                placed = soft.soft_contents.setdefault(adj.target_id, {})
                placed[adj.item_name] = placed.get(adj.item_name, 0) + adj.count
            # Dropping/giving away the improvised weapon's source item
            # ends the weapon: it cannot persist while the item is gone.
            reconcile_improvised_weapon(soft)
        # Accepted examines have no state effect.

    # Any proposals still pending did not receive an adjudication.
    for prop in pending:
        rejected.append({
            "proposal": prop.model_dump(),
            "reason": "no adjudication received",
        })

    return applied, rejected, hard_changes


def post_validate_knowledge_tags(
    knowledge_tags: dict[str, list[str]],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> tuple[list[RevelationApplied], HardStateChanges]:
    """Validate and apply knowledge_tag revelations.

    Returns a tuple of (applied_revelations, hard_state_changes).
    Topics with unmet conditions or unknown topics are silently skipped.

    Note: hard state is mutated directly so that subsequent topic condition
    evaluations see earlier side effects, but the same mutations are also
    collected into the returned HardStateChanges delta.
    """
    applied: list[RevelationApplied] = []
    hard_changes = HardStateChanges()

    existing_topic_ids = {k.topic_id for k in soft.player_knowledge}

    for npc_id, topic_ids in knowledge_tags.items():
        npc_entity = corpus.entities.get(npc_id)
        if npc_entity is None or npc_entity.type != "npc":
            continue

        entity_state = hard.entity_states.get(npc_id, {})
        if entity_state.get("alive") is False:
            continue

        guidelines = npc_entity.dialogue
        if guidelines is None:
            continue

        will_reveal = guidelines.will_reveal or {}

        for topic_id in topic_ids:
            if topic_id in existing_topic_ids:
                continue

            topic_entry = will_reveal.get(topic_id)
            if topic_entry is None:
                continue

            conditions_met = True
            for cond_raw in topic_entry.conditions:
                if not evaluate(cond_raw, hard, soft, corpus):
                    conditions_met = False
                    break

            if not conditions_met:
                continue

            side_effects: list[str] = []

            if topic_entry.set_flag:
                for flag, val in topic_entry.set_flag.items():
                    hard.flags[flag] = val
                    hard_changes.flags_set[flag] = val
                    side_effects.append(f"set_flag:{flag}={val}")

            if topic_entry.set_entity_state:
                for ent_id, state_changes in topic_entry.set_entity_state.items():
                    if ent_id not in hard.entity_states:
                        hard.entity_states[ent_id] = {}
                    hard.entity_states[ent_id].update(state_changes)
                    hard_changes.entity_state_changes.setdefault(
                        ent_id, {}
                    ).update(state_changes)
                    side_effects.append(f"set_entity_state:{ent_id}={state_changes}")

            soft.player_knowledge.append(
                KnowledgeEntry(
                    topic_id=topic_id,
                    description=topic_entry.description,
                    source_type="npc_dialogue",
                    source_id=npc_id,
                    turn_learned=hard.turn_count,
                )
            )

            applied.append(
                RevelationApplied(
                    npc_id=npc_id,
                    topic_id=topic_id,
                    side_effects_applied=side_effects,
                )
            )

            existing_topic_ids.add(topic_id)

    return applied, hard_changes


def post_validate_attitude_changes(
    attitude_changes: dict[str, AttitudeChange],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    prior_changes: HardStateChanges | None = None,
) -> tuple[dict[str, AttitudeChange], dict[str, dict[str, Any]], HardStateChanges]:
    """Validate attitude changes.

    Returns (applied, rejected, hard_state_changes) where rejected has
    explanations and hard_state_changes records validated attitude updates.
    """
    applied: dict[str, AttitudeChange] = {}
    rejected: dict[str, dict[str, Any]] = {}
    hard_changes = HardStateChanges()

    for npc_id, change in attitude_changes.items():
        npc_entity = corpus.entities.get(npc_id)
        if npc_entity is None or npc_entity.type != "npc":
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": f"'{npc_id}' is not a valid NPC",
            }
            continue

        entity_state = hard.entity_states.get(npc_id, {})
        if entity_state.get("alive") is False:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": f"NPC '{npc_id}' is dead",
            }
            continue

        guidelines = npc_entity.dialogue
        if guidelines is None:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": f"NPC '{npc_id}' has no dialogue",
            }
            continue

        limits = guidelines.attitude_limits
        attitude_val = entity_state.get("attitude")
        if attitude_val is None:
            current = 0
        else:
            current = int(attitude_val)

        if change.old_value != current:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": (
                    f"old_value mismatch: proposed {change.old_value}, "
                    f"actual {current}"
                ),
            }
            continue

        step = limits.step_per_turn
        if step == 0:
            if change.new_value != change.old_value:
                rejected[npc_id] = {
                    "change": change.model_dump(),
                    "reason": (
                        f"step_per_turn is 0: no attitude changes allowed "
                        f"for NPC '{npc_id}'"
                    ),
                }
                continue
        elif abs(change.new_value - change.old_value) > step:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": (
                    f"Change ({change.old_value} -> {change.new_value}) exceeds "
                    f"step_per_turn limit ({step})"
                ),
            }
            continue

        if change.new_value < limits.min or change.new_value > limits.max:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": (
                    f"new_value {change.new_value} is outside allowed range "
                    f"[{limits.min}, {limits.max}]"
                ),
            }
            continue

        if not change.reason or not change.reason.strip():
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": "reason is empty",
            }
            continue

        # Reject if attitude was already mechanically adjusted this turn
        if prior_changes is not None:
            prior_entity_changes = prior_changes.entity_state_changes.get(npc_id, {})
            if "attitude" in prior_entity_changes:
                rejected[npc_id] = {
                    "change": change.model_dump(),
                    "reason": (
                        f"NPC '{npc_id}' attitude was already mechanically adjusted "
                        f"this turn via an interaction result"
                    ),
                }
                continue

        if npc_id not in hard.entity_states:
            hard.entity_states[npc_id] = {}
        hard.entity_states[npc_id]["attitude"] = change.new_value
        hard_changes.entity_state_changes.setdefault(npc_id, {})["attitude"] = change.new_value
        applied[npc_id] = change

    return applied, rejected, hard_changes


def apply_post_validation(
    knowledge_tags: dict[str, list[str]] | None,
    attitude_changes: dict[str, AttitudeChange] | None,
    state_manager: StateManager,
    base_result: EngineResult | None = None,
    soft_item_adjudications: list[SoftItemAdjudication] | None = None,
    soft_state_notes: list[SoftStateNote] | None = None,
) -> EngineResult:
    """Run full post-validation and produce an updated EngineResult.

    If ``base_result`` is provided, the post-validation fields and any
    hard-state changes are merged into it.  If not, a minimal EngineResult
    containing only the post-validation outcomes is returned.
    """
    hard = state_manager.hard_state
    soft = state_manager.soft_state
    corpus = state_manager.corpus

    if hard is None or soft is None or corpus is None:
        if base_result is not None:
            return base_result
        return EngineResult(
            success=True,
            action_type="post_validation",
            error="State not loaded",
        )

    revelations_applied: list[RevelationApplied] = []
    post_hard_changes = HardStateChanges()

    if knowledge_tags:
        revelations_applied, post_hard_changes = post_validate_knowledge_tags(
            knowledge_tags, hard, soft, corpus
        )
        if post_hard_changes.has_changes():
            state_manager.apply_hard_changes(post_hard_changes)

    attitude_changes_applied: dict[str, AttitudeChange] = {}
    attitude_changes_rejected: dict[str, dict[str, Any]] = {}

    if attitude_changes:
        prior_changes = base_result.hard_state_changes if base_result is not None else None
        attitude_changes_applied, attitude_changes_rejected, attitude_hard_changes = (
            post_validate_attitude_changes(
                attitude_changes, hard, soft, corpus, prior_changes=prior_changes
            )
        )
        if attitude_hard_changes.has_changes():
            state_manager.apply_hard_changes(attitude_hard_changes)
            post_hard_changes.merge(attitude_hard_changes)

    soft_items_accepted: list[SoftItemAdjudication] = []
    soft_items_rejected: list[dict[str, Any]] = []

    proposals: list[SoftItemProposal] = []
    if base_result is not None:
        proposals = list(base_result.soft_item_proposals or [])

    if proposals or soft_item_adjudications:
        soft_items_accepted, soft_items_rejected, item_hard_changes = (
            post_validate_soft_items(
                soft_item_adjudications or [],
                proposals,
                hard,
                soft,
                corpus,
            )
        )
        if item_hard_changes.has_changes():
            state_manager.apply_hard_changes(item_hard_changes)
            post_hard_changes.merge(item_hard_changes)

    notes_applied: list[SoftStateNote] = []
    notes_rejected: list[dict[str, Any]] = []

    if soft_state_notes:
        notes_applied, notes_rejected = post_validate_notes(
            soft_state_notes, hard, soft, corpus
        )
        if notes_applied:
            state_manager.apply_soft_patches(notes_applied)

    if base_result is not None:
        result = base_result.model_copy(deep=True)
        if post_hard_changes.has_changes() and result.hard_state_changes is not None:
            result.hard_state_changes.merge(post_hard_changes)
        elif post_hard_changes.has_changes():
            result.hard_state_changes = post_hard_changes
        result.revelations_applied = revelations_applied
        result.attitude_changes_applied = attitude_changes_applied
        result.attitude_changes_rejected = attitude_changes_rejected
        result.soft_items_accepted = soft_items_accepted
        result.soft_items_rejected = soft_items_rejected
        result.soft_state_notes_applied = notes_applied
        result.soft_state_notes_rejected = notes_rejected
        return result

    return EngineResult(
        success=True,
        action_type="post_validation",
        hard_state_changes=post_hard_changes if post_hard_changes.has_changes() else None,
        revelations_applied=revelations_applied,
        attitude_changes_applied=attitude_changes_applied,
        attitude_changes_rejected=attitude_changes_rejected,
        soft_items_accepted=soft_items_accepted,
        soft_items_rejected=soft_items_rejected,
        soft_state_notes_applied=notes_applied,
        soft_state_notes_rejected=notes_rejected,
    )
