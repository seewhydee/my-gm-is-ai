from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from mgmai.models.corpus import DialogueGuidelines


class BriefingInteraction(BaseModel):
    id: str
    label: str
    description: Optional[str] = None


class BriefingEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    state: Dict[str, Any] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)
    soft_items: List[str] = Field(default_factory=list)
    dialogue_paths: Dict[str, str] = Field(default_factory=dict)


class BriefingExit(BaseModel):
    id: str
    direction: str
    target_room: str
    hidden: bool = False


class BriefingRoom(BaseModel):
    id: str
    name: str
    description: str
    soft_items: List[str] = Field(default_factory=list)
    entities_visible: List[BriefingEntity] = Field(default_factory=list)
    exits_available: List[BriefingExit] = Field(default_factory=list)
    interactions_available: List[BriefingInteraction] = Field(default_factory=list)
    room_notes: List[str] = Field(default_factory=list)


class PlayerStatEntry(BaseModel):
    value: int
    modifier: int


class PlayerStateBriefing(BaseModel):
    location: str
    hard_inventory: List[str] = Field(default_factory=list)
    soft_inventory: List[str] = Field(default_factory=list)
    active_flags: Dict[str, bool] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)
    player_stats: Optional[Dict[str, PlayerStatEntry]] = None


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


class GMBriefing(BaseModel):
    adventure_title: str
    setting: str
    tone: str
    turn: int
    current_room: BriefingRoom
    player_state: PlayerStateBriefing
    player_knowledge_topics: List[str] = Field(default_factory=list)
    recent_history: List[BriefingHistoryEntry] = Field(default_factory=list)
    dialogue_context: Optional[DialogueContext] = None
    revealed_hints: List[str] = Field(default_factory=list)
    player_input: str
