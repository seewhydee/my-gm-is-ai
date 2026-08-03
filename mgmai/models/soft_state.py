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

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class KnowledgeEntry(BaseModel):
    topic_id: str
    description: str
    source_type: Literal["npc_dialogue", "interaction", "examination", "book", "puzzle"]
    source_id: str | None = None
    turn_learned: int


class ImprovisedWeapon(BaseModel):
    """Temporary weapon created from a non-standard object.

    The ruling GM supplies only the ``keyword`` (a size class such as
    ``"light"``), an optional ``damage_type``, and descriptive fields;
    ``damage_expr`` and ``hit_bonus`` are resolved from the keyword by the
    resolution system when the patch is applied.

    ``source_item`` links the weapon to a carried soft item it was made
    from: the item stays in ``soft_inventory`` while wielded, and is
    consumed (removed) when a ``clears_after_turn`` weapon expires.
    """
    keyword: str
    damage_expr: str
    hit_bonus: int = 0
    damage_type: str = "bludgeoning"
    description: str = ""
    clears_after_turn: bool = False
    source_item: str | None = None


class SoftStatePatch(BaseModel):
    """Intent-coupled soft-state change proposed by LLM Call 1 as part of
    the PlayerAction.  Validated and applied by the engine during action
    resolution, before narration."""

    entity_id: str | None = None
    field: Literal["soft_inventory_remove", "set_improvised_weapon"]
    new_value: Any
    reason: str

    @model_validator(mode="after")
    def check_field_consistency(self) -> SoftStatePatch:
        if self.entity_id is not None:
            raise ValueError(
                f"{self.field} patch must not carry entity_id"
            )
        return self


class SoftStateNote(BaseModel):
    """Narrative note proposed by LLM Call 2 alongside its narration,
    recording a durable, non-plot-relevant change to the current room or
    to an entity in it.  Validated and applied by the engine during
    post-validation."""

    entity_id: str | None = None
    field: Literal["room_note", "entity_note"]
    new_value: str
    reason: str

    @model_validator(mode="after")
    def check_field_consistency(self) -> SoftStateNote:
        if self.field == "room_note":
            # room_note attaches to the player's current room; the engine
            # derives the target, so entity_id is not accepted on the note.
            if self.entity_id is not None:
                raise ValueError(
                    "room_note must not carry entity_id; it attaches "
                    "to the player's current room"
                )
        elif self.field == "entity_note" and self.entity_id is None:
            raise ValueError("entity_note requires entity_id")
        return self


class ConversationLogEntry(BaseModel):
    turn: int
    speaker: str
    text: str


class DialogueState(BaseModel):
    active_npc: str | None = None
    conversation_log: list[ConversationLogEntry] = Field(default_factory=list)
    topics_discussed: list[str] = Field(default_factory=list)
    entered_turn: int = 0
    stall_counter: int = 0


class TurnHistoryEntry(BaseModel):
    turn: int
    player_input: str
    ruled_action: dict[str, Any]
    engine_result_summary: str
    flags_changed: list[str] = Field(default_factory=list)
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
    soft_inventory: list[str] = Field(default_factory=list)
    room_notes: dict[str, list[str]] = Field(default_factory=dict)
    entity_notes: dict[str, list[str]] = Field(default_factory=dict)
    player_knowledge: list[KnowledgeEntry] = Field(default_factory=list)
    turn_history: list[TurnHistoryEntry] = Field(default_factory=list)
    dialogue_state: DialogueState = Field(default_factory=DialogueState)
    soft_items_taken: dict[str, dict[str, int]] = Field(default_factory=dict)
    soft_contents: dict[str, dict[str, int]] = Field(default_factory=dict)
    checks_attempted: dict[str, list[str]] = Field(default_factory=dict)
    revealed_hints: list[str] = Field(default_factory=list)
    improvised_weapon: ImprovisedWeapon | None = None
