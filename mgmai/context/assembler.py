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
from typing import Any

from mgmai.engine.systems import get_system_for_corpus
from mgmai.engine.utils import build_briefing_room
from mgmai.models.briefing import (
    BriefingHistoryEntry,
    CombatBriefing,
    DialogueActiveNpc,
    DialogueContext,
    EquippedItemBriefing,
    GMBriefing,
    PlayerCombatStats,
    PlayerKnowledgeTopic,
    PlayerStateBriefing,
    PlayerStatEntry,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

log = logging.getLogger(__name__)


def assemble(corpus: ModuleCorpus,
             hard: HardGameState,
             soft: SoftGameState,
             player_input: str) -> GMBriefing:
    """Build a GMBriefing from the current corpus + game state."""
    room_id = hard.player.location
    if room_id not in corpus.rooms:
        raise ValueError(f"Player location '{room_id}' not found in corpus")

    atmosphere   = corpus.adventure.atmosphere
    player_stats = _build_player_stats(hard, corpus)
    combat_state = _build_combat_state(hard, corpus)

    return GMBriefing(
        adventure_title=corpus.adventure.title,
        setting=atmosphere.setting if atmosphere else "",
        tone=atmosphere.tone if atmosphere else "",
        turn=hard.turn_count,
        current_room=build_briefing_room(room_id, hard, soft, corpus),
        player_state=_build_player_state(hard, soft, player_stats, corpus),
        player_knowledge_topics=_build_player_knowledge(soft),
        recent_history=_build_recent_history(soft),
        dialogue_context=_build_dialogue_context(soft, hard, corpus),
        revealed_hints=list(soft.revealed_hints),
        player_input=player_input,
        combat_state=combat_state)


def _build_player_state(
        hard: HardGameState,
        soft: SoftGameState,
        player_stats: dict[str, PlayerStatEntry] | None,
        corpus: ModuleCorpus) -> PlayerStateBriefing:
    active_flags = {k: v for k, v in hard.flags.items() if v}
    player_entity_notes = soft.entity_notes.get("player", [])
    in_combat = hard.combat is not None and hard.combat.active

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

    from mgmai.engine.combat import compute_player_ac
    effective_ac = compute_player_ac(hard, corpus)

    combat_stats = None
    if hard.player.current_hp is not None:
        from mgmai.engine.combat import get_player_max_hp
        combat_stats = PlayerCombatStats(
            current_hp=hard.player.current_hp,
            max_hp=hard.player.max_hp or get_player_max_hp(hard),
            ac=effective_ac,
            proficiency_bonus=hard.player.proficiency_bonus or 2,
            skill_proficiencies=list(hard.player.skill_proficiencies),
            weapon_proficiencies=[
                c if isinstance(c, str) else c.model_dump()
                for c in hard.player.weapon_proficiencies
            ],
        )

    # Abilities (same entry shape as the combat briefing), spell slots,
    # and usable items, so the GM LLM can rule out-of-combat ability and
    # item use (e.g. casting Mage Armor before a fight).  During combat
    # these live on combat_state instead, which tracks per-combat
    # remaining uses; duplicating them here would risk the LLM reading a
    # stale copy.
    abilities: list[dict[str, Any]] = []
    if not in_combat:
        system = get_system_for_corpus(corpus)
        for aid in hard.player.abilities:
            ability = corpus.abilities.get(aid)
            if ability is None:
                continue
            # uses_per_combat counters are combat-scoped: outside combat an
            # ability shows its full per-combat allotment (null = unlimited).
            remaining = None if ability.uses_per_combat < 0 else ability.uses_per_combat
            abilities.append(
                _ability_briefing_entry(aid, ability, system, hard, remaining)
            )

    return PlayerStateBriefing(
        hard_inventory=dict(hard.player.inventory),
        soft_inventory=list(soft.soft_inventory),
        equipped_items=equipped_items,
        active_flags=active_flags,
        entity_notes=list(player_entity_notes),
        player_stats=player_stats,
        combat_stats=combat_stats,
        abilities=abilities,
        spell_slots={} if in_combat else dict(hard.player.spell_slots),
        status_effects=_status_effect_briefs(hard.player.status_effects, corpus),
        improvised_weapon=(
            soft.improvised_weapon.model_dump(mode="json")
            if soft.improvised_weapon is not None
            else None
        ),
        usable_items=[] if in_combat else _build_usable_items(hard, corpus),
    )


def _build_player_stats(hard: HardGameState,
                        corpus: ModuleCorpus) -> dict[str, PlayerStatEntry] | None:
    """Effective (gear-adjusted) stats with computed modifiers."""
    from mgmai.engine.combat import compute_effective_stats
    from mgmai.engine.stat_checks import compute_modifier

    effective = compute_effective_stats(hard, corpus)
    if effective is None or corpus.stats is None:
        return None

    system = corpus.stats.system
    return {
        stat_key: PlayerStatEntry(
            value=stat_value,
            modifier=compute_modifier(stat_value, system))
        for stat_key, stat_value in effective.items()
    }


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


def _status_effect_briefs(
    status_effects: dict[str, int], corpus: ModuleCorpus
) -> list[dict[str, Any]]:
    """Briefing entries for active status effects, with def descriptions.

    Each entry carries the status effect ID and remaining rounds; when the
    status effect's StatusEffectDef has a ``description``, it is included so the
    GM LLM knows what it does.
    """
    effect_defs = corpus.effective_status_effects()
    briefs: list[dict[str, Any]] = []
    for cid in sorted(status_effects):
        entry: dict[str, Any] = {"id": cid, "rounds": status_effects[cid]}
        cdef = effect_defs.get(cid)
        if cdef is not None and cdef.description:
            entry["description"] = cdef.description
        briefs.append(entry)
    return briefs


def _ability_briefing_entry(
    aid: str,
    ability: Any,
    system: Any,
    hard: HardGameState,
    uses_remaining: int | None,
) -> dict[str, Any]:
    """Briefing entry for one player ability (shared by the combat and
    player-state briefings).  Spell entries carry their slot cost and
    (for save spells) the player's derived save DC."""
    if ability.attack is not None:
        effect_kind = "attack"
    elif ability.save is not None:
        effect_kind = "save"
    elif ability.heal:
        effect_kind = "heal"
    elif ability.auto_damage is not None:
        effect_kind = "auto_damage"
    else:
        effect_kind = "on_cast"
    entry: dict[str, Any] = {
        "id": aid,
        "name": ability.name,
        "description": ability.description,
        "target": ability.target,
        "uses_remaining": uses_remaining,  # null = unlimited
        "effect": ability.effect_summary(),
        "effect_kind": effect_kind,
        # The ability's casting time drives its budget cost in combat
        # (bonus-action abilities consume the bonus action, everything
        # else the action).  Exposed for every ability, not just spells.
        "casting_time": ability.casting_time,
    }
    if ability.spell_level is not None:
        entry["spell_level"] = ability.spell_level
        entry["concentration"] = ability.concentration
        entry["slot_level"] = ability.spell_level
        if ability.save is not None:
            entry["save_dc"] = system.compute_spell_save_dc(hard)
    return entry


def _build_usable_items(
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> list[dict[str, Any]]:
    """Inventory items that carry an interaction (e.g. potions with ``drink``)."""
    items: list[dict[str, Any]] = []
    for item_id in hard.player.inventory:
        entity = corpus.entities.get(item_id)
        if entity is None or not entity.interactions:
            continue
        interaction_briefs = [
            {"id": inter.id, "description": inter.description}
            for inter in entity.interactions
        ]
        items.append({
            "id": item_id,
            "name": entity.name or item_id,
            "interactions": interaction_briefs,
        })
    return items


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
        # Positioning: engagement partners ("within melee reach") and
        # impede flags, so the ruling LLM sees the current map.
        engaged_with = sorted(
            p[1] if p[0] == cid else p[0]
            for p in combat.engagement
            if cid in p
        )
        positioning = {
            "engaged_with": engaged_with,
            "impeded": cid in combat.impeded,
            "impede_used": cid in combat.impede_used,
        }
        if cid == "player":
            combatants.append({
                "id": "player",
                "name": "Player",
                "side": "party",
                "current_hp": hard.player.current_hp or 0,
                "max_hp": hard.player.max_hp or 0,
                "status_effects": _status_effect_briefs(hard.player.status_effects, corpus),
                **positioning,
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
                "status_effects": _status_effect_briefs(
                    state.get("status_effects", {}) or {}, corpus
                ),
                **positioning,
            })

    usable_items: list[dict[str, Any]] = _build_usable_items(hard, corpus)

    abilities: list[dict[str, Any]] = []
    system = get_system_for_corpus(corpus)
    for aid in hard.player.abilities:
        ability = corpus.abilities.get(aid)
        if ability is None:
            continue
        used = combat.ability_uses.get("player", {}).get(aid, 0)
        remaining = (
            None
            if ability.uses_per_combat < 0
            else max(0, ability.uses_per_combat - used)
        )
        abilities.append(
            _ability_briefing_entry(aid, ability, system, hard, remaining)
        )

    # The remaining per-turn budget (SRD 5.2.1) is derived from CombatState
    # — never from chat history.  The legal bonus-action option set is the
    # §3.3 cheap roster check; the auto-end rule uses the same set.
    from mgmai.engine.combat import legal_bonus_action_ability_ids

    budget = combat.player_budget
    ba_ids = legal_bonus_action_ability_ids(combat, hard, corpus)

    return CombatBriefing(
        round_number=combat.round_number,
        initiative_order=list(initiative),
        current_actor=current_actor,
        combatants=combatants,
        usable_items=usable_items,
        abilities=abilities,
        spell_slots=dict(hard.player.spell_slots),
        action_available=not budget.action_used,
        bonus_action_available=(not budget.bonus_action_used) and bool(ba_ids),
        bonus_action_options=ba_ids,
        free_interaction_available=not budget.free_interaction_used,
        reaction_available="player" not in combat.reactions_spent,
    )
