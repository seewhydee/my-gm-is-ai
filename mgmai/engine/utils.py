"""Utility helpers used across engine modules without circular import risk."""

from __future__ import annotations

from mgmai.models.briefing import BriefingEntity
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState


def get_following_npc_ids(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[str]:
    """Return entity IDs of all alive NPCs whose state says ``following == True``."""
    result: list[str] = []
    for eid, estate in hard.entity_states.items():
        if estate.get("following") is True:
            ent = corpus.entities.get(eid)
            if ent is not None and ent.type == "npc" and ent.dialogue_guidelines is not None:
                if estate.get("alive") is not False:
                    result.append(eid)
    return result


def inject_following_npcs(
    entities_visible: list[BriefingEntity],
    room_id: str,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> None:
    """Append following-NPC BriefingEntity entries that aren't already visible."""
    seen_ids = {e.id for e in entities_visible}
    for eid in get_following_npc_ids(hard, corpus):
        if eid in seen_ids:
            continue
        entity = corpus.entities[eid]
        entity_state = hard.entity_states.get(eid, {})
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
