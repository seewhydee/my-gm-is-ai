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

from mgmai.models.briefing import BriefingContainsEntry, BriefingEntity
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState


def _is_stackable(item_id: str, corpus: ModuleCorpus | None) -> bool:
    """Return True if *item_id* is tagged stackable in the corpus.

    Unknown items are treated as non-stackable.
    """
    if corpus is None:
        return False
    entity = corpus.entities.get(item_id)
    if entity is None:
        return False
    return "stackable" in entity.tags


def is_exit_visible(
    exit_obj: object,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> bool:
    """Return True if the exit should be visible given current state.

    condition is None       -> always visible
    condition is present    -> visible when the condition evaluates to true
    The condition is re-evaluated every turn.
    """
    from mgmai.engine.conditions import evaluate

    cond = getattr(exit_obj, "condition", None)
    if cond is None:
        return True
    return evaluate(cond, hard, soft, corpus)


def get_following_npc_ids(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[str]:
    """Return entity IDs of all alive NPCs whose state says ``following == True``."""
    result: list[str] = []
    for eid, estate in hard.entity_states.items():
        if estate.get("following") is True:
            ent = corpus.entities.get(eid)
            if ent is not None and ent.type == "npc" and ent.dialogue is not None:
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
        if entity.type == "npc" and entity.dialogue:
            path_descriptions = {
                path_id: resolvable.description
                for path_id, resolvable in entity.dialogue.dialogue_paths.items()
            }

        entities_visible.append(
            BriefingEntity(
                id=eid,
                name=entity.name or eid,
                type=entity.type,
                description=entity.description,
                state=entity_state,
                entity_notes=notes,
                soft_items=list(entity_soft),
                contains=build_contains(entity, hard, corpus, entity_id=eid),
                dialogue_paths=path_descriptions,
            )
        )


def build_contains(
    entity: object,
    hard: HardGameState,
    corpus: ModuleCorpus,
    entity_id: str = "",
) -> list[BriefingContainsEntry]:
    """Build BriefingContainsEntry list from the runtime entity_contains map,
    filtering out hidden entities and items already in player inventory.

    When the entity has the ``container`` tag and ``open`` is declared in
    its state_fields, the container is treated as closed (contents hidden)
    unless its hard state has ``open: true``.  Entities without the
    ``container`` tag are unaffected (backward compatibility)."""
    from mgmai.models.corpus import Entity as CorpusEntity
    assert isinstance(entity, CorpusEntity)

    if "container" in entity.tags and "open" in entity.state_fields:
        estate = hard.entity_states.get(entity_id, {})
        if estate.get("open") is not True:
            return []

    contained_map = hard.entity_contains.get(entity_id, {})
    contained: list[BriefingContainsEntry] = []
    for cid, count in contained_map.items():
        if count <= 0:
            continue
        contained_entity = corpus.entities.get(cid)
        if contained_entity is None:
            continue
        cstate = hard.entity_states.get(cid, {})
        if cstate.get("hidden", False):
            continue
        # Hide equipped items; hide inventory items only when non-stackable.
        if contained_entity.type == "item":
            if cid in hard.player.equipped:
                continue
            if cid in hard.player.inventory and not _is_stackable(cid, corpus):
                continue
        contained.append(BriefingContainsEntry(
            id=cid,
            name=contained_entity.name or cid,
            type=contained_entity.type,
            description=contained_entity.description,
            count=count,
        ))
    return contained
