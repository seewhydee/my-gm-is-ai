from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from mgmai.models.corpus import DialogueGuidelines


class BriefingEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    state: Dict[str, Any] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)
    soft_items: List[str] = Field(default_factory=list)


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
    interactions_available: List[Any] = Field(default_factory=list)
    room_notes: List[str] = Field(default_factory=list)


class PlayerStateBriefing(BaseModel):
    location: str
    hard_inventory: List[str] = Field(default_factory=list)
    soft_inventory: List[str] = Field(default_factory=list)
    active_flags: Dict[str, bool] = Field(default_factory=dict)
    entity_notes: List[str] = Field(default_factory=list)


class BriefingHistoryEntry(BaseModel):
    turn: int
    summary: str
    location_after: str


class DialogueContext(BaseModel):
    active_npc: BriefingEntity
    dialogue_guidelines: DialogueGuidelines
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
    npc_attitudes: Dict[str, int] = Field(default_factory=dict)
    npc_revelations: Dict[str, List[Dict[str, str]]] = Field(default_factory=dict)
    recent_history: List[BriefingHistoryEntry] = Field(default_factory=list)
    dialogue_context: Optional[DialogueContext] = None
    player_input: str
