from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AttitudeChange(BaseModel):
    old_value: int
    new_value: int
    reason: str


class KnowledgeTags(BaseModel):
    npc_revealed: Optional[Dict[str, List[str]]] = None


class NarrationOutput(BaseModel):
    narration: str
    npc_response: Optional[str] = None
    knowledge_tags: Optional[KnowledgeTags] = None
    attitude_changes: Optional[Dict[str, AttitudeChange]] = None
    conversation_note: Optional[str] = None
    terminate_chain: bool = False
