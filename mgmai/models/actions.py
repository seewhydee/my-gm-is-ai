from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from mgmai.models.briefing import BriefingRoom
from mgmai.models.narration import AttitudeChange
from mgmai.models.soft_state import SoftStatePatch


class _BaseAction(BaseModel):
    detail: str
    follow_up: Optional[str] = None
    proposed_soft_state_patches: List[SoftStatePatch] = Field(default_factory=list)


class MoveAction(_BaseAction):
    action_type: Literal["move"]
    target: str
    style: Optional[str] = None


class ExamineAction(_BaseAction):
    action_type: Literal["examine"]
    target: str
    rigorous: bool = False
    using: Optional[str] = None


class InteractAction(_BaseAction):
    action_type: Literal["interact"]
    target: str
    interaction_id: str
    using: Optional[str] = None


class TalkAction(_BaseAction):
    action_type: Literal["talk"]
    target: str
    utterance: Optional[str] = None
    ends_dialogue: bool = False


class TransferAction(_BaseAction):
    action_type: Literal["transfer"]
    target: str
    given_items: Optional[List[str]] = None
    taken_items: Optional[List[str]] = None

    @model_validator(mode="after")
    def check_non_empty_transfer(self) -> TransferAction:
        gi = self.given_items
        ti = self.taken_items
        if (gi is None or len(gi) == 0) and (ti is None or len(ti) == 0):
            raise ValueError(
                "TransferAction must have at least one of given_items or "
                "taken_items be non-empty"
            )
        return self


class WaitAction(_BaseAction):
    action_type: Literal["wait"]


class OocDiscussionAction(_BaseAction):
    action_type: Literal["ooc_discussion"]


PlayerActionType = Annotated[
    Union[
        MoveAction,
        ExamineAction,
        InteractAction,
        TalkAction,
        TransferAction,
        WaitAction,
        OocDiscussionAction,
    ],
    Field(discriminator="action_type"),
]

_player_action_adapter = TypeAdapter(PlayerActionType)


def validate_player_action(
    data: dict,
) -> (
    MoveAction
    | ExamineAction
    | InteractAction
    | TalkAction
    | TransferAction
    | WaitAction
    | OocDiscussionAction
):
    return _player_action_adapter.validate_python(data)


class PlayerAction:
    """Backward-compatible access to the discriminated union."""

    ActionType = PlayerActionType

    @staticmethod
    def model_validate(
        data: dict,
    ) -> (
        MoveAction
        | ExamineAction
        | InteractAction
        | TalkAction
        | TransferAction
        | WaitAction
        | OocDiscussionAction
    ):
        return _player_action_adapter.validate_python(data)

    @staticmethod
    def model_validate_json(json_str: str) -> (
        MoveAction
        | ExamineAction
        | InteractAction
        | TalkAction
        | TransferAction
        | WaitAction
        | OocDiscussionAction
    ):
        return _player_action_adapter.validate_json(json_str)


class HardStateChanges(BaseModel):
    player_location: Optional[str] = None
    inventory_added: List[str] = Field(default_factory=list)
    inventory_removed: List[str] = Field(default_factory=list)
    flags_set: Dict[str, bool] = Field(default_factory=dict)
    flags_cleared: List[str] = Field(default_factory=list)
    room_state_changes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    entity_state_changes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def merge(self, other: "HardStateChanges") -> "HardStateChanges":
        """Merge another HardStateChanges into this one in-place."""
        if other.player_location is not None:
            self.player_location = other.player_location
        self.inventory_added.extend(other.inventory_added)
        self.inventory_removed.extend(other.inventory_removed)
        self.flags_set.update(other.flags_set)
        self.flags_cleared.extend(other.flags_cleared)
        for room_id, changes in other.room_state_changes.items():
            self.room_state_changes.setdefault(room_id, {}).update(changes)
        for entity_id, changes in other.entity_state_changes.items():
            self.entity_state_changes.setdefault(entity_id, {}).update(changes)
        return self

    def has_changes(self) -> bool:
        """Return True if any field contains a change."""
        return (
            self.player_location is not None
            or bool(self.inventory_added)
            or bool(self.inventory_removed)
            or bool(self.flags_set)
            or bool(self.flags_cleared)
            or bool(self.room_state_changes)
            or bool(self.entity_state_changes)
        )


class EncounterOutcome(BaseModel):
    encounter_id: str
    outcome: str
    narrative_brief: Optional[str] = None


class OnEnterEventResult(BaseModel):
    event_id: Optional[str] = None
    narrative: Optional[str] = None


class GameOverResult(BaseModel):
    type: str
    trigger: str
    narrative: Optional[str] = None


class DialogueExitedResult(BaseModel):
    npc_id: str
    exit_narrative: Optional[str] = None


class WillRevealReadinessEntry(BaseModel):
    conditions_met: bool
    description: str


class AttitudeLimitsCurrent(BaseModel):
    min: int
    max: int
    step_per_turn: int
    current: int


class RevelationApplied(BaseModel):
    npc_id: str
    topic_id: str
    side_effects_applied: List[str] = Field(default_factory=list)


class ChainInfo(BaseModel):
    follow_up: Optional[str] = None
    termination_reason: Optional[str] = None


class EngineResult(BaseModel):
    success: bool
    action_type: str
    target: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    player_input_echo: Optional[str] = None
    room_after: Optional[BriefingRoom] = None
    hard_state_changes: Optional[HardStateChanges] = None
    soft_state_patches_applied: List[SoftStatePatch] = Field(default_factory=list)
    soft_state_patches_rejected: List[Dict[str, Any]] = Field(default_factory=list)
    rolls: List[Dict[str, Any]] = Field(default_factory=list)
    encounter_outcome: Optional[EncounterOutcome] = None
    triggered_narration: List[str] = Field(default_factory=list)
    on_enter_events: List[OnEnterEventResult] = Field(default_factory=list)
    game_over: Optional[GameOverResult] = None
    dialogue_exited: Optional[DialogueExitedResult] = None
    will_reveal_readiness: Optional[Dict[str, Dict[str, WillRevealReadinessEntry]]] = None
    revelations_applied: List[RevelationApplied] = Field(default_factory=list)
    npc_attitude_limits: Optional[Dict[str, AttitudeLimitsCurrent]] = None
    attitude_changes_applied: Dict[str, AttitudeChange] = Field(default_factory=dict)
    attitude_changes_rejected: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    chain_info: Optional[ChainInfo] = None
    warnings: List[str] = Field(default_factory=list)
