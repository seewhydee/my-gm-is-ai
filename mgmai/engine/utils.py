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
        if entity_state.get("hidden", False):
            continue
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
