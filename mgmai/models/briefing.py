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

import json
from typing import Any

from pydantic import BaseModel, Field

from mgmai.models.corpus import DialogueGuidelines


def _is_empty(value: Any) -> bool:
    """True for values that carry no information for the LLM.

    None, empty strings, and empty containers (``[]``/``{}``) are dropped
    from the serialized briefing. Falsy scalars like ``0`` or ``False``
    are meaningful (e.g. ``modifier: 0``, ``impeded: false``) and kept.
    """
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    return isinstance(value, (list, dict)) and len(value) == 0


def _strip_empty(obj: Any) -> Any:
    """Recursively drop empty fields from a JSON-native structure."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            v = _strip_empty(v)
            if _is_empty(v):
                continue
            out[k] = v
        return out
    if isinstance(obj, list):
        out_list: list[Any] = []
        for item in obj:
            v = _strip_empty(item)
            if _is_empty(v):
                continue
            out_list.append(v)
        return out_list
    return obj


class BriefingInteraction(BaseModel):
    id: str
    description: str


class PlayerKnowledgeTopic(BaseModel):
    """A topic the player has learned, with its description."""
    topic_id: str
    description: str


class BriefingContainsEntry(BaseModel):
    """Minimal entity info for an item nested inside another entity."""
    id: str
    name: str
    type: str = "item"
    description: str
    count: int = 1


class BriefingEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    state: dict[str, Any] = Field(default_factory=dict)
    entity_notes: list[str] = Field(default_factory=list)
    soft_item_guidance: str | None = None
    soft_items_taken: list[str] = Field(default_factory=list)
    soft_items_present: list[str] = Field(default_factory=list)
    contains: list[BriefingContainsEntry] = Field(default_factory=list)
    dialogue_paths: dict[str, str] = Field(default_factory=dict)
    combat_block: dict[str, Any] | None = None
    count: int = 1


class BriefingExit(BaseModel):
    id: str
    direction: str
    target_room: str


class BriefingRoom(BaseModel):
    id: str
    name: str
    description: str
    soft_item_guidance: str | None = None
    soft_items_taken: list[str] = Field(default_factory=list)
    soft_items_present: list[str] = Field(default_factory=list)
    entities_visible: list[BriefingEntity] = Field(default_factory=list)
    exits_available: list[BriefingExit] = Field(default_factory=list)
    interactions_available: list[BriefingInteraction] = Field(default_factory=list)
    room_notes: list[str] = Field(default_factory=list)


class EquippedItemBriefing(BaseModel):
    id: str
    name: str
    description: str
    equip_tags: list[str] = Field(default_factory=list)
    effects_summary: str = ""


class PlayerStatEntry(BaseModel):
    value: int
    modifier: int


class PlayerCombatStats(BaseModel):
    current_hp: int
    max_hp: int
    ac: int
    proficiency_bonus: int
    skill_proficiencies: list[str] = Field(default_factory=list)
    # Each entry is a bare string (category or weapon ID) or a dict
    # {"category": ..., "properties": [...]} (a WeaponProfClause, serialized).
    weapon_proficiencies: list[str | dict[str, Any]] = Field(
        default_factory=list
    )


class PlayerStateBriefing(BaseModel):
    location: str
    hard_inventory: dict[str, int] = Field(default_factory=dict)
    soft_inventory: list[str] = Field(default_factory=list)
    equipped_items: list[EquippedItemBriefing] = Field(default_factory=list)
    effective_ac: int = 10
    effective_stats: dict[str, int] | None = None
    active_flags: dict[str, bool] = Field(default_factory=dict)
    entity_notes: list[str] = Field(default_factory=list)
    player_stats: dict[str, PlayerStatEntry] | None = None
    combat_stats: PlayerCombatStats | None = None
    # Player's known abilities (same entry shape as CombatBriefing.abilities):
    # [{id, name, description, target, uses_remaining, effect, effect_kind,
    #   spell_level?, concentration?, slot_level?, save_dc?}]
    abilities: list[dict[str, Any]] = Field(default_factory=list)
    # Spell level -> slots remaining (empty when the player has no
    # leveled spells; cantrips cost nothing).
    spell_slots: dict[int, int] = Field(default_factory=dict)
    # Status effects active on the player (e.g. an ongoing Mage Armor):
    # [{id, rounds, description?}]
    status_effects: list[dict[str, Any]] = Field(default_factory=list)
    # Inventory items with a usable interaction (drink, read, etc.):
    # [{id, name, interactions: [{id, description}]}]
    usable_items: list[dict[str, Any]] = Field(default_factory=list)


class BriefingHistoryEntry(BaseModel):
    turn: int
    summary: str
    location_after: str


class DialogueActiveNpc(BaseModel):
    id: str
    name: str
    attitude: int
    dialogue: DialogueGuidelines


class DialogueContext(BaseModel):
    active_npc: DialogueActiveNpc
    recent_exchanges: list[dict[str, Any]] = Field(default_factory=list)
    topics_discussed: list[str] = Field(default_factory=list)
    revealed_topics: list[str] = Field(default_factory=list)


class CombatBriefing(BaseModel):
    round_number: int
    initiative_order: list[str]
    current_actor: str
    combatants: list[dict[str, Any]]  # [{id, name, side, current_hp, max_hp,
    #   status_effects: [{id, rounds, description?}], engaged_with: [ids],
    #   impeded: bool, impede_used: bool}]
    # Inventory items with a usable interaction: [{id, name, interactions: [{id, description}]}]
    usable_items: list[dict[str, Any]] = Field(default_factory=list)
    # Player's combat abilities: [{id, name, description, target, uses_remaining,
    #   effect, effect_kind, spell_level?, concentration?, slot_level?,
    #   casting_time?, save_dc?}]
    abilities: list[dict[str, Any]] = Field(default_factory=list)
    # Spell level -> slots remaining (empty when the player has no
    # leveled spells; cantrips cost nothing).
    spell_slots: dict[int, int] = Field(default_factory=dict)
    # Interactions the player may use via the `interact` action during
    # combat: same entries as the room briefing's interactions_available
    # (room + present entities), minus the generic "attack" id (attack
    # maps to the `combat` action).
    interactions_available: list[BriefingInteraction] = Field(default_factory=list)


class GMBriefing(BaseModel):
    adventure_title: str
    setting: str
    tone: str
    turn: int
    current_room: BriefingRoom
    player_state: PlayerStateBriefing
    player_knowledge_topics: list[PlayerKnowledgeTopic] = Field(default_factory=list)
    recent_history: list[BriefingHistoryEntry] = Field(default_factory=list)
    dialogue_context: DialogueContext | None = None
    revealed_hints: list[str] = Field(default_factory=list)
    player_input: str
    combat_state: CombatBriefing | None = None

    def compact_dump(self) -> dict[str, Any]:
        """Return the briefing as a dict with empty fields omitted.

        Drops keys whose values are ``None``, ``""``, ``[]``, or ``{}``
        recursively. Absence is semantically equivalent to "no value"
        for every briefing field, so the LLM loses no information while
        prompt tokens and visual noise are reduced.
        """
        return _strip_empty(self.model_dump(mode="json"))

    def compact_dump_json(self, indent: int = 2) -> str:
        """JSON string form of :meth:`compact_dump`."""
        return json.dumps(self.compact_dump(), indent=indent)
