from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from mgmai.models.soft_state import SoftStatePatch


class PlayerAction(BaseModel):
    action_type: Literal[
        "move", "examine", "interact", "talk", "transfer", "wait", "ooc_discussion"
    ]
    detail: str
    target: Optional[str] = None
    style: Optional[str] = None
    rigorous: bool = False
    using: Optional[str] = None
    interaction_id: Optional[str] = None
    utterance: Optional[str] = None
    ends_dialogue: bool = False
    given_items: Optional[List[str]] = None
    taken_items: Optional[List[str]] = None
    follow_up: Optional[str] = None
    proposed_soft_state_patches: List[SoftStatePatch] = Field(default_factory=list)


class EngineResult(BaseModel):
    success: bool
    action_type: str
    target: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    player_input_echo: Optional[str] = None
    room_after: Optional[Dict[str, Any]] = None
    hard_state_changes: Optional[Dict[str, Any]] = None
    soft_state_patches_applied: List[SoftStatePatch] = Field(default_factory=list)
    soft_state_patches_rejected: List[Dict[str, Any]] = Field(default_factory=list)
    rolls: List[Any] = Field(default_factory=list)
    encounter_outcome: Optional[Dict[str, Any]] = None
    triggered_narration: List[str] = Field(default_factory=list)
    on_enter_events: List[Any] = Field(default_factory=list)
    game_over: Optional[Dict[str, Any]] = None
    dialogue_exited: Optional[Dict[str, Any]] = None
    will_reveal_readiness: Optional[Dict[str, Any]] = None
    revelations_applied: List[Any] = Field(default_factory=list)
    npc_attitude_limits: Optional[Dict[str, Any]] = None
    attitude_changes_applied: List[Any] = Field(default_factory=list)
    attitude_changes_rejected: List[Any] = Field(default_factory=list)
    chain_info: Optional[Any] = None
    warnings: List[str] = Field(default_factory=list)
