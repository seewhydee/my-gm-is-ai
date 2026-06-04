from __future__ import annotations

from typing import Any

from mgmai.models.actions import (
    AttitudeLimitsCurrent,
    AttitudeChange as AttitudeChangeModel,
    EngineResult,
    RevelationApplied,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.narration import AttitudeChange
from mgmai.models.soft_state import NpcRevelation, SoftGameState
from mgmai.engine.conditions import evaluate


def post_validate_knowledge_tags(
    knowledge_tags: dict[str, list[str]],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> list[RevelationApplied]:
    """Validate and apply knowledge_tag revelations.

    Returns a list of RevelationApplied entries for accepted tags.
    Topics with unmet conditions or unknown topics are silently skipped.
    """
    applied: list[RevelationApplied] = []

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

        if npc_id not in soft.npc_revelations:
            soft.npc_revelations[npc_id] = []
        existing_topics = {r.topic_id for r in soft.npc_revelations[npc_id]}

        for topic_id in topic_ids:
            if topic_id in existing_topics:
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
                    side_effects.append(f"set_flag:{flag}={val}")

            if topic_entry.set_entity_state:
                for ent_id, state_changes in topic_entry.set_entity_state.items():
                    if ent_id not in hard.entity_states:
                        hard.entity_states[ent_id] = {}
                    hard.entity_states[ent_id].update(state_changes)
                    side_effects.append(f"set_entity_state:{ent_id}={state_changes}")

            soft.npc_revelations[npc_id].append(
                NpcRevelation(
                    topic_id=topic_id,
                    description=topic_entry.description,
                )
            )

            applied.append(
                RevelationApplied(
                    npc_id=npc_id,
                    topic_id=topic_id,
                    side_effects_applied=side_effects,
                )
            )

            existing_topics.add(topic_id)

    return applied


def post_validate_attitude_changes(
    attitude_changes: dict[str, AttitudeChange],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> tuple[dict[str, AttitudeChange], dict[str, dict[str, Any]]]:
    """Validate attitude changes.

    Returns (applied, rejected) where rejected has explanations.
    """
    applied: dict[str, AttitudeChange] = {}
    rejected: dict[str, dict[str, Any]] = {}

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
        current = soft.npc_attitudes.get(npc_id, limits.initial)

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

        soft.npc_attitudes[npc_id] = change.new_value
        applied[npc_id] = change

    return applied, rejected


def apply_post_validation(
    knowledge_tags: dict[str, list[str]] | None,
    attitude_changes: dict[str, AttitudeChange] | None,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> dict[str, Any]:
    """Run full post-validation and return updates to merge into EngineResult.

    Returns a dict with:
        revelations_applied: list[RevelationApplied]
        attitude_changes_applied: dict[str, AttitudeChange]
        attitude_changes_rejected: dict[str, dict]
    """
    result: dict[str, Any] = {
        "revelations_applied": [],
        "attitude_changes_applied": {},
        "attitude_changes_rejected": {},
    }

    if knowledge_tags:
        result["revelations_applied"] = post_validate_knowledge_tags(
            knowledge_tags, hard, soft, corpus
        )

    if attitude_changes:
        applied, rejected = post_validate_attitude_changes(
            attitude_changes, hard, soft, corpus
        )
        result["attitude_changes_applied"] = applied
        result["attitude_changes_rejected"] = rejected

    return result
