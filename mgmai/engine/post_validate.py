from __future__ import annotations

from typing import Any

from mgmai.models.actions import EngineResult, HardStateChanges, RevelationApplied
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.narration import AttitudeChange
from mgmai.models.soft_state import KnowledgeEntry, SoftGameState
from mgmai.state.manager import StateManager
from mgmai.engine.conditions import evaluate


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

        guidelines = npc_entity.dialogue_guidelines
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

        guidelines = npc_entity.dialogue_guidelines
        if guidelines is None:
            rejected[npc_id] = {
                "change": change.model_dump(),
                "reason": f"NPC '{npc_id}' has no dialogue_guidelines",
            }
            continue

        limits = guidelines.attitude_limits
        attitude_val = entity_state.get("attitude")
        if attitude_val is None:
            current = limits.initial
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
        attitude_changes_applied, attitude_changes_rejected, attitude_hard_changes = (
            post_validate_attitude_changes(attitude_changes, hard, soft, corpus)
        )
        if attitude_hard_changes.has_changes():
            state_manager.apply_hard_changes(attitude_hard_changes)
            post_hard_changes.merge(attitude_hard_changes)

    if base_result is not None:
        result = base_result.model_copy(deep=True)
        if post_hard_changes.has_changes() and result.hard_state_changes is not None:
            result.hard_state_changes.merge(post_hard_changes)
        elif post_hard_changes.has_changes():
            result.hard_state_changes = post_hard_changes
        result.revelations_applied = revelations_applied
        result.attitude_changes_applied = attitude_changes_applied
        result.attitude_changes_rejected = attitude_changes_rejected
        return result

    return EngineResult(
        success=True,
        action_type="post_validation",
        hard_state_changes=post_hard_changes if post_hard_changes.has_changes() else None,
        revelations_applied=revelations_applied,
        attitude_changes_applied=attitude_changes_applied,
        attitude_changes_rejected=attitude_changes_rejected,
    )
