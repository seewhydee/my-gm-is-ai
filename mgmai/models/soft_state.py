from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SoftStatePatch(BaseModel):
    entity_id: Optional[str] = None
    field: Literal[
        "room_note", "entity_note", "soft_inventory_add", "soft_inventory_remove"
    ]
    target_id: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Any
    reason: str

    @model_validator(mode="after")
    def check_field_consistency(self) -> SoftStatePatch:
        if self.field == "room_note":
            if self.entity_id is not None:
                raise ValueError(
                    "room_note patch must not have entity_id; use target_id "
                    "for the room ID"
                )
            if self.target_id is None:
                raise ValueError("room_note patch requires target_id (the room ID)")
        elif self.field == "entity_note":
            if self.target_id is not None:
                raise ValueError(
                    "entity_note patch must not have target_id; use entity_id "
                    "for the entity ID"
                )
            if self.entity_id is None:
                raise ValueError("entity_note patch requires entity_id")
        return self


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

    model_config = {
        "json_schema_extra": {
            "ruled_action_description": (
                "Serialized form of the validated PlayerAction (discriminated "
                "union).  Validation happens at LLM Call 1 parse time via "
                "validate_player_action() — this field stores the model_dump() "
                "output for archival and save/load.  The engine reads action "
                "history only for GMBriefing summaries, not for re-execution."
            ),
        },
    }


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
    surfaced_soft_items: Dict[str, List[str]] = Field(default_factory=dict)
    checks_attempted: Dict[str, List[str]] = Field(default_factory=dict)
    revealed_hints: List[str] = Field(default_factory=list)
