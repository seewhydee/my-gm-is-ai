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

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class KnowledgeEntry(BaseModel):
    topic_id: str
    description: str
    source_type: Literal["npc_dialogue", "interaction", "examination", "book", "puzzle"]
    source_id: Optional[str] = None
    turn_learned: int


class ImprovisedWeapon(BaseModel):
    """Temporary weapon created from a non-standard object."""
    damage_expr: str = "1d6"
    hit_bonus: int = 0
    description: str = ""
    clears_after_turn: bool = False


class SoftStatePatch(BaseModel):
    entity_id: Optional[str] = None
    field: Literal[
        "room_note", "entity_note", "soft_inventory_remove",
        "appearance_note_add", "set_improvised_weapon"
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
        elif self.field == "appearance_note_add":
            if self.target_id is not None:
                raise ValueError(
                    "appearance_note_add patch must not have target_id"
                )
            if not isinstance(self.new_value, str) or not self.new_value.strip():
                raise ValueError("appearance_note_add new_value must be a non-empty string")
        elif self.field == "set_improvised_weapon":
            if self.target_id is not None:
                raise ValueError(
                    "set_improvised_weapon patch must not have target_id"
                )
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


class SoftGameState(BaseModel):
    soft_inventory: List[str] = Field(default_factory=list)
    room_notes: Dict[str, List[str]] = Field(default_factory=dict)
    entity_notes: Dict[str, List[str]] = Field(default_factory=dict)
    player_knowledge: List[KnowledgeEntry] = Field(default_factory=list)
    turn_history: List[TurnHistoryEntry] = Field(default_factory=list)
    dialogue_state: DialogueState = Field(default_factory=DialogueState)
    soft_items_taken: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    soft_contents: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    checks_attempted: Dict[str, List[str]] = Field(default_factory=dict)
    revealed_hints: List[str] = Field(default_factory=list)
    appearance_notes: List[str] = Field(default_factory=list)
    improvised_weapon: Optional[ImprovisedWeapon] = None
