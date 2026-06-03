from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SoftStatePatch(BaseModel):
    entity_id: Optional[str] = None
    field: str
    target_id: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Any
    reason: str


class ConversationLogEntry(BaseModel):
    turn: int
    speaker: str
    text: str


class DialogueState(BaseModel):
    active_npc: Optional[str] = None
    conversation_log: List[ConversationLogEntry] = Field(default_factory=list)
    topics_discussed: List[str] = Field(default_factory=list)
    entered_turn: int = 0
    stall_counter: int = 0


class TurnHistoryEntry(BaseModel):
    turn: int
    player_input: str
    ruled_action: Dict[str, Any]
    engine_result_summary: str
    flags_changed: List[str] = Field(default_factory=list)
    location_after: str


class NpcRevelation(BaseModel):
    topic_id: str
    description: str


class SoftGameState(BaseModel):
    soft_inventory: List[str] = Field(default_factory=list)
    room_notes: Dict[str, List[str]] = Field(default_factory=dict)
    entity_notes: Dict[str, List[str]] = Field(default_factory=dict)
    npc_attitudes: Dict[str, int] = Field(default_factory=dict)
    npc_revelations: Dict[str, List[NpcRevelation]] = Field(default_factory=dict)
    turn_history: List[TurnHistoryEntry] = Field(default_factory=list)
    dialogue_state: DialogueState = Field(default_factory=DialogueState)
