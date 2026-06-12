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
from typing import Optional

log = logging.getLogger(__name__)

from mgmai.models.briefing import (
    BriefingEntity,
    BriefingExit,
    BriefingHistoryEntry,
    BriefingInteraction,
    BriefingRoom,
    DialogueActiveNpc,
    DialogueContext,
    GMBriefing,
    PlayerStateBriefing,
    PlayerStatEntry,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate
from mgmai.engine.utils import get_following_npc_ids, inject_following_npcs


def assemble(
    corpus: ModuleCorpus,
    hard: HardGameState,
    soft: SoftGameState,
    player_input: str,
) -> GMBriefing:
    """Build a GMBriefing from the current corpus + game state."""
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        raise ValueError(f"Player location '{room_id}' not found in corpus")

    atmosphere = corpus.adventure.atmosphere

    player_stats = _build_player_stats(hard, corpus)

    return GMBriefing(
        adventure_title=corpus.adventure.title,
        setting=atmosphere.setting if atmosphere else "",
        tone=atmosphere.tone if atmosphere else "",
        turn=hard.turn_count,
        current_room=_build_room(room_id, room, hard, soft, corpus),
        player_state=_build_player_state(hard, soft, player_stats),
        player_knowledge_topics=_build_player_knowledge(soft),
        recent_history=_build_recent_history(soft),
        dialogue_context=_build_dialogue_context(soft, hard, corpus),
        revealed_hints=list(soft.revealed_hints),
        player_input=player_input,
    )


def _build_room(
    room_id: str,
    room: object,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> BriefingRoom:
    from mgmai.models.corpus import Room as CorpusRoom

    assert isinstance(room, CorpusRoom)

    entities_visible: list[BriefingEntity] = []
    for eid in room.entities_present:
        entity = corpus.entities.get(eid)
        if entity is None:
            continue

        entity_state = hard.entity_states.get(eid, {})
        if entity_state.get("hidden", False):
            continue
        if entity.type == "item" and eid in hard.player.inventory:
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
                state=dict(entity_state),
                entity_notes=list(notes),
                soft_items=list(entity_soft),
                dialogue_paths=path_descriptions,
            )
        )

    inject_following_npcs(entities_visible, room_id, hard, soft, corpus)

    exits_available: list[BriefingExit] = []
    for ex in room.exits:
        if ex.hidden:
            # Hidden exits are revealed only when their conditions are met
            if ex.conditions:
                all_met = True
                for cond in ex.conditions:
                    if not evaluate(cond, hard, soft, corpus):
                        all_met = False
                        break
                if not all_met:
                    continue
            else:
                continue
        elif ex.conditions:
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

    entity_ids: set[str] = set(room.entities_present)
    for eid in get_following_npc_ids(hard, corpus):
        entity_ids.add(eid)

    for eid in sorted(entity_ids):
        entity = corpus.entities.get(eid)
        if entity is None:
            continue
        entity_state = hard.entity_states.get(eid, {})
        if entity_state.get("alive") is False:
            continue
        for inter in entity.interactions:
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
    room_soft_items = soft.surfaced_soft_items.get(room_id, [])

    return BriefingRoom(
        id=room_id,
        name=room.name,
        description=room.description,
        soft_items=list(room_soft_items),
        entities_visible=entities_visible,
        exits_available=exits_available,
        interactions_available=interactions_available,
        room_notes=list(room_notes),
    )


def _build_player_state(
    hard: HardGameState,
    soft: SoftGameState,
    player_stats: Optional[dict[str, PlayerStatEntry]],
) -> PlayerStateBriefing:
    active_flags = {k: v for k, v in hard.flags.items() if v}
    player_entity_notes = soft.entity_notes.get("player", [])

    return PlayerStateBriefing(
        location=hard.player.location,
        hard_inventory=list(hard.player.inventory),
        soft_inventory=list(soft.soft_inventory),
        active_flags=active_flags,
        entity_notes=list(player_entity_notes),
        player_stats=player_stats,
    )


def _build_player_stats(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> Optional[dict[str, PlayerStatEntry]]:
    if hard.player.stats is None or corpus.stats is None:
        return None

    from mgmai.engine.stat_checks import compute_modifier

    stats_block = corpus.stats
    result: dict[str, PlayerStatEntry] = {}
    for stat_key, stat_value in hard.player.stats.items():
        mod = compute_modifier(stat_value, stats_block.system)
        result[stat_key] = PlayerStatEntry(value=stat_value, modifier=mod)
    return result


def _pair_conversation_log(
    log: list[object],
) -> list[dict[str, object]]:
    """Pair player+NPC entries into exchanges, cap at 5 most recent.

    Adjacent player→NPC entries become one exchange dict.
    Unpaired entries get their own dict.
    Returns the last 5 exchanges.
    """
    from mgmai.models.soft_state import ConversationLogEntry

    exchanges: list[dict[str, object]] = []
    i = 0
    while i < len(log):
        entry = log[i]
        assert isinstance(entry, ConversationLogEntry)
        if entry.speaker == "player":
            exchange: dict[str, object] = {"player": entry.text}
            if i + 1 < len(log):
                next_entry = log[i + 1]
                assert isinstance(next_entry, ConversationLogEntry)
                if next_entry.speaker == "npc":
                    exchange["npc"] = next_entry.text
                    i += 2
                else:
                    i += 1
            else:
                i += 1
            exchanges.append(exchange)
        else:
            exchanges.append({"npc": entry.text})
            i += 1

    return exchanges[-5:]


def _build_player_knowledge(
    soft: SoftGameState,
) -> list[str]:
    return [entry.topic_id for entry in soft.player_knowledge]


def _build_recent_history(
    soft: SoftGameState,
) -> list[BriefingHistoryEntry]:
    non_ooc = [e for e in soft.turn_history if e.ruled_action.get("action_type") != "ooc_discussion"]
    last_five = non_ooc[-5:]
    return [
        BriefingHistoryEntry(
            turn=entry.turn,
            summary=entry.engine_result_summary,
            location_after=entry.location_after,
        )
        for entry in last_five
    ]


def _build_dialogue_context(
    soft: SoftGameState,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> DialogueContext | None:
    ds = soft.dialogue_state
    if ds.active_npc is None:
        return None

    npc_id = ds.active_npc
    npc = corpus.entities.get(npc_id)
    if npc is None:
        return None

    guidelines = npc.dialogue_guidelines
    if guidelines is None:
        return None

    entity_state = hard.entity_states.get(npc_id, {})
    if entity_state.get("alive") is False:
        return None

    attitude_val = entity_state.get("attitude")
    if attitude_val is None:
        attitude = guidelines.attitude_limits.initial
    else:
        attitude = int(attitude_val)

    recent_exchanges = _pair_conversation_log(ds.conversation_log)

    revealed_topics: list[str] = []
    for entry in soft.player_knowledge:
        if entry.source_id == npc_id:
            revealed_topics.append(entry.topic_id)

    return DialogueContext(
        active_npc=DialogueActiveNpc(
            id=npc_id,
            name=getattr(npc, "name", npc_id),
            attitude=attitude,
            dialogue_guidelines=guidelines,
        ),
        recent_exchanges=recent_exchanges,
        topics_discussed=list(ds.topics_discussed),
        revealed_topics=revealed_topics,
    )
