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
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from mgmai.models.corpus import DialogueGuidelines


class BriefingInteraction(BaseModel):
    id: str
    label: str
    description: Optional[str] = None


class PlayerKnowledgeTopic(BaseModel):
    """A topic the player has learned, with its description."""
    topic_id: str
    description: str


class BriefingContainedEntity(BaseModel):
    """Minimal entity info for an item nested inside another entity."""
    id: str
    name: str
    type: str = "item"
    description: str


class BriefingEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    state: Dict[str, Any] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)
    soft_items: List[str] = Field(default_factory=list)
    contained_entities: List[BriefingContainedEntity] = Field(default_factory=list)
    dialogue_paths: Dict[str, str] = Field(default_factory=dict)
    combat_block: Optional[dict[str, Any]] = None


class BriefingExit(BaseModel):
    id: str
    direction: str
    target_room: str


class BriefingRoom(BaseModel):
    id: str
    name: str
    description: str
    soft_items: List[str] = Field(default_factory=list)
    entities_visible: List[BriefingEntity] = Field(default_factory=list)
    exits_available: List[BriefingExit] = Field(default_factory=list)
    interactions_available: List[BriefingInteraction] = Field(default_factory=list)
    room_notes: List[str] = Field(default_factory=list)


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


class PlayerStateBriefing(BaseModel):
    location: str
    hard_inventory: List[str] = Field(default_factory=list)
    soft_inventory: List[str] = Field(default_factory=list)
    equipped_items: List[EquippedItemBriefing] = Field(default_factory=list)
    effective_ac: int = 10
    effective_stats: Optional[Dict[str, int]] = None
    active_flags: Dict[str, bool] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)
    player_stats: Optional[Dict[str, PlayerStatEntry]] = None
    combat_stats: Optional[PlayerCombatStats] = None


class BriefingHistoryEntry(BaseModel):
    turn: int
    summary: str
    location_after: str


class DialogueActiveNpc(BaseModel):
    id: str
    name: str
    attitude: int
    dialogue_guidelines: DialogueGuidelines


class DialogueContext(BaseModel):
    active_npc: DialogueActiveNpc
    recent_exchanges: List[Dict[str, Any]] = Field(default_factory=list)
    topics_discussed: List[str] = Field(default_factory=list)
    revealed_topics: List[str] = Field(default_factory=list)


class CombatBriefing(BaseModel):
    round_number: int
    initiative_order: list[str]
    current_actor: str
    combatants: list[dict[str, Any]]  # [{id, name, current_hp, max_hp}]


class GMBriefing(BaseModel):
    adventure_title: str
    setting: str
    tone: str
    turn: int
    current_room: BriefingRoom
    player_state: PlayerStateBriefing
    player_knowledge_topics: List[PlayerKnowledgeTopic] = Field(default_factory=list)
    recent_history: List[BriefingHistoryEntry] = Field(default_factory=list)
    dialogue_context: Optional[DialogueContext] = None
    revealed_hints: List[str] = Field(default_factory=list)
    player_input: str
    combat_state: Optional[CombatBriefing] = None
