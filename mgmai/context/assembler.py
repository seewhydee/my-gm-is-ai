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
    CombatBriefing,
    DialogueActiveNpc,
    DialogueContext,
    EquippedItemBriefing,
    GMBriefing,
    PlayerCombatStats,
    PlayerKnowledgeTopic,
    PlayerStateBriefing,
    PlayerStatEntry)

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate
from mgmai.engine.utils import (
    get_following_npc_ids,
    inject_following_npcs,
    build_contains,
    is_exit_visible,
    _is_stackable,
)


def assemble(corpus: ModuleCorpus,
             hard: HardGameState,
             soft: SoftGameState,
             player_input: str) -> GMBriefing:
    """Build a GMBriefing from the current corpus + game state."""
    room_id = hard.player.location
    room = corpus.rooms.get(room_id)
    if room is None:
        raise ValueError(f"Player location '{room_id}' not found in corpus")

    atmosphere   = corpus.adventure.atmosphere
    player_stats = _build_player_stats(hard, corpus)
    combat_state = _build_combat_state(hard, corpus)

    return GMBriefing(
        adventure_title=corpus.adventure.title,
        setting=atmosphere.setting if atmosphere else "",
        tone=atmosphere.tone if atmosphere else "",
        turn=hard.turn_count,
        current_room=_build_room(room_id, room, hard, soft, corpus),
        player_state=_build_player_state(hard, soft, player_stats, corpus),
        player_knowledge_topics=_build_player_knowledge(soft),
        recent_history=_build_recent_history(soft),
        dialogue_context=_build_dialogue_context(soft, hard, corpus),
        revealed_hints=list(soft.revealed_hints),
        player_input=player_input,
        combat_state=combat_state)


def _build_room(room_id: str,
                room: object,
                hard: HardGameState,
                soft: SoftGameState,
                corpus: ModuleCorpus) -> BriefingRoom:

    from mgmai.models.corpus import Room as CorpusRoom
    assert isinstance(room, CorpusRoom)

    entities_visible: list[BriefingEntity] = []
    room_contains = hard.room_contains.get(room_id, {})
    for eid, count in room_contains.items():
        if count <= 0:
            continue
        entity = corpus.entities.get(eid)
        if entity is None:
            continue

        entity_state = hard.entity_states.get(eid, {})
        if entity_state.get("hidden", False):
            continue
        # Hide equipped items; hide inventory items only when non-stackable.
        if entity.type == "item":
            if eid in hard.player.equipped:
                continue
            if eid in hard.player.inventory and not _is_stackable(eid, corpus):
                continue

        notes = soft.entity_notes.get(eid, [])
        entity_soft_items_taken = [
            f"{name} (taken {count})"
            for name, count in soft.soft_items_taken.get(eid, {}).items()
        ]
        entity_soft_items_present = [
            f"{name} x{count}"
            for name, count in soft.soft_contents.get(eid, {}).items()
        ]

        path_descriptions: dict[str, str] = {}
        if entity.type == "npc" and entity.dialogue:
            path_descriptions = {
                path_id: resolvable.description
                for path_id, resolvable in entity.dialogue.dialogue_paths.items()
            }

        combat_block_dict = None
        if entity.combat is not None:
            combat_block_dict = entity.combat.model_dump(mode="json")

        entities_visible.append(
            BriefingEntity(
                id=eid,
                name=entity.name or eid,
                type=entity.type,
                description=entity.description,
                state=dict(entity_state),
                entity_notes=list(notes),
                soft_item_guidance=entity.soft_item_guidance,
                soft_items_taken=entity_soft_items_taken,
                soft_items_present=entity_soft_items_present,
                contains=build_contains(entity, hard, corpus, entity_id=eid),
                dialogue_paths=path_descriptions,
                combat_block=combat_block_dict,
                count=count))

    inject_following_npcs(entities_visible, room_id, hard, soft, corpus)

    exits_available: list[BriefingExit] = []
    for ex in room.exits:
        if not is_exit_visible(ex, hard, soft, corpus):
            continue
        exits_available.append(
            BriefingExit(id=ex.id,
                         direction=ex.direction,
                         target_room=ex.target_room))

    interactions_available: list[BriefingInteraction] = []
    for inter in room.interactions:
        if inter.condition:
            if not evaluate(inter.condition, hard, soft, corpus):
                continue
        interactions_available.append(
            BriefingInteraction(id=inter.id,
                                description=inter.description))

    entity_ids: set[str] = set(hard.room_contains.get(room_id, {}))
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
                BriefingInteraction(id=inter.id,
                                    description=inter.description))

    room_notes = soft.room_notes.get(room_id, [])
    room_soft_items_taken = [
        f"{name} (taken {count})"
        for name, count in soft.soft_items_taken.get(room_id, {}).items()
    ]
    room_soft_items_present = [
        f"{name} x{count}"
        for name, count in soft.soft_contents.get(room_id, {}).items()
    ]

    return BriefingRoom(
        id=room_id,
        name=room.name,
        description=room.description,
        soft_item_guidance=room.soft_item_guidance,
        soft_items_taken=room_soft_items_taken,
        soft_items_present=room_soft_items_present,
        entities_visible=entities_visible,
        exits_available=exits_available,
        interactions_available=interactions_available,
        room_notes=list(room_notes))


def _build_player_state(
        hard: HardGameState,
        soft: SoftGameState,
        player_stats: Optional[dict[str, PlayerStatEntry]],
        corpus: ModuleCorpus) -> PlayerStateBriefing:
    active_flags = {k: v for k, v in hard.flags.items() if v}
    player_entity_notes = soft.entity_notes.get("player", [])

    # Build equipped items briefing
    equipped_items: list[EquippedItemBriefing] = []
    for item_id in hard.player.equipped:
        entity = corpus.entities.get(item_id)
        if entity is None:
            continue
        equip_tags = []
        effects_summary = ""
        if entity.equip_block:
            equip_tags = list(entity.equip_block.equip_tags)
            effects_summary = entity.equip_block.effects_summary()
        equipped_items.append(EquippedItemBriefing(
            id=item_id,
            name=entity.name or item_id,
            description=entity.description,
            equip_tags=equip_tags,
            effects_summary=effects_summary,
        ))

    # Effective stats and AC
    from mgmai.engine.combat import compute_player_ac, compute_effective_stats
    effective_ac = compute_player_ac(hard, corpus)
    effective_stats = compute_effective_stats(hard, corpus)

    combat_stats = None
    if hard.player.current_hp is not None:
        from mgmai.engine.combat import get_player_max_hp
        combat_stats = PlayerCombatStats(
            current_hp=hard.player.current_hp,
            max_hp=hard.player.max_hp or get_player_max_hp(hard),
            ac=effective_ac,
            proficiency_bonus=hard.player.proficiency_bonus or 2,
        )

    return PlayerStateBriefing(
        location=hard.player.location,
        hard_inventory=dict(hard.player.inventory),
        soft_inventory=list(soft.soft_inventory),
        equipped_items=equipped_items,
        effective_ac=effective_ac,
        effective_stats=effective_stats,
        active_flags=active_flags,
        entity_notes=list(player_entity_notes),
        player_stats=player_stats,
        combat_stats=combat_stats)


def _build_player_stats(hard: HardGameState,
                        corpus: ModuleCorpus) -> Optional[dict[str, PlayerStatEntry]]:
    if hard.player.stats is None or corpus.stats is None:
        return None

    from mgmai.engine.stat_checks import compute_modifier

    stats_block = corpus.stats
    result: dict[str, PlayerStatEntry] = {}
    for stat_key, stat_value in hard.player.stats.items():
        mod = compute_modifier(stat_value, stats_block.system)
        result[stat_key] = PlayerStatEntry(value=stat_value, modifier=mod)
    return result


_CONVERSATION_LOG_CAP = 5


def _pair_conversation_log(log: list[object]) -> list[dict[str, object]]:
    """Pair player+NPC entries into exchanges, capped at the most recent.

    Adjacent player→NPC entries become one exchange dict.
    Unpaired entries get their own dict.
    Returns the last ``_CONVERSATION_LOG_CAP`` exchanges.
    """
    from mgmai.models.soft_state import ConversationLogEntry

    exchanges: list[dict[str, object]] = []
    i = len(log) - 1
    while i >= 0 and len(exchanges) < _CONVERSATION_LOG_CAP:
        entry = log[i]
        assert isinstance(entry, ConversationLogEntry)
        if entry.speaker == "npc":
            exchange: dict[str, object] = {"npc": entry.text}
            if i - 1 >= 0:
                prev_entry = log[i - 1]
                assert isinstance(prev_entry, ConversationLogEntry)
                if prev_entry.speaker == "player":
                    exchange["player"] = prev_entry.text
                    i -= 1
            exchanges.append(exchange)
        else:
            exchanges.append({"player": entry.text})
        i -= 1

    return list(reversed(exchanges))


def _build_player_knowledge(soft: SoftGameState) -> list[PlayerKnowledgeTopic]:
    return [
        PlayerKnowledgeTopic(
            topic_id=entry.topic_id,
            description=entry.description,
        )
        for entry in soft.player_knowledge
    ]


def _build_recent_history(soft: SoftGameState) -> list[BriefingHistoryEntry]:
    non_ooc = [e for e in soft.turn_history if e.ruled_action.get("action_type") != "ooc_discussion"]
    last_five = non_ooc[-5:]
    return [
        BriefingHistoryEntry(turn=entry.turn,
                             summary=entry.engine_result_summary,
                             location_after=entry.location_after)
        for entry in last_five
    ]


def _build_dialogue_context(soft: SoftGameState,
                            hard: HardGameState,
                            corpus: ModuleCorpus) -> DialogueContext | None:
    ds = soft.dialogue_state
    if ds.active_npc is None:
        return None

    npc_id = ds.active_npc
    npc = corpus.entities.get(npc_id)
    if npc is None:
        return None

    guidelines = npc.dialogue
    if guidelines is None:
        return None

    entity_state = hard.entity_states.get(npc_id, {})
    if entity_state.get("alive") is False:
        return None

    attitude_val = entity_state.get("attitude")
    if attitude_val is None:
        attitude = 0
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
            name=npc.name or npc_id,
            attitude=attitude,
            dialogue=guidelines),
        recent_exchanges=recent_exchanges,
        topics_discussed=list(ds.topics_discussed),
        revealed_topics=revealed_topics)


def _build_combat_state(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> CombatBriefing | None:
    """Build a CombatBriefing when combat is active."""
    combat = hard.combat
    if combat is None or not combat.active:
        return None

    initiative = combat.initiative_order
    current_actor = (
        initiative[combat.current_index]
        if combat.current_index < len(initiative)
        else "?"
    )

    combatants: list[dict[str, Any]] = []
    for cid in combat.combatants:
        if cid == "player":
            combatants.append({
                "id": "player",
                "name": "Player",
                "side": "party",
                "current_hp": hard.player.current_hp or 0,
                "max_hp": hard.player.max_hp or 0,
            })
        else:
            entity = corpus.entities.get(cid)
            name = (entity.name or cid) if entity else cid
            state = hard.entity_states.get(cid, {})
            combatants.append({
                "id": cid,
                "name": name,
                "side": "party" if cid in combat.allies else "enemy",
                "current_hp": state.get("current_hp") or 0,
                "max_hp": (entity.combat.hp if entity and entity.combat else 0),
            })

    return CombatBriefing(
        round_number=combat.round_number,
        initiative_order=list(initiative),
        current_actor=current_actor,
        combatants=combatants,
    )
