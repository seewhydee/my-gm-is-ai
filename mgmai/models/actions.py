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
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, TypeAdapter, model_validator
from mgmai.models.briefing import BriefingRoom
from mgmai.models.combat import CombatLogEntry
from mgmai.models.corpus import StatModifier
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
    using: Optional[str] = None


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
    dialogue_path: Optional[str] = None


class TransferAction(_BaseAction):
    action_type: Literal["transfer"]
    target: str
    given_items: Optional[List[str]] = None
    taken_items: Optional[List[str]] = None
    given_counts: Optional[Dict[str, int]] = None
    taken_counts: Optional[Dict[str, int]] = None

    @model_validator(mode="after")
    def check_non_empty_transfer(self) -> TransferAction:
        gi = self.given_items
        ti = self.taken_items
        gc = self.given_counts
        tc = self.taken_counts
        has_gi = gi is not None and len(gi) > 0
        has_ti = ti is not None and len(ti) > 0
        has_gc = gc is not None and len(gc) > 0
        has_tc = tc is not None and len(tc) > 0
        if not any((has_gi, has_ti, has_gc, has_tc)):
            raise ValueError(
                "TransferAction must have at least one of given_items, "
                "taken_items, given_counts, or taken_counts be non-empty")
        for count_dict in (gc, tc):
            if count_dict is not None:
                for item_id, count in count_dict.items():
                    if count < 1:
                        raise ValueError(
                            f"Transfer count for '{item_id}' must be >= 1, "
                            f"got {count}")
        return self


class WaitAction(_BaseAction):
    action_type: Literal["wait"]


class CombatAction(_BaseAction):
    action_type: Literal["combat"]
    combat_action: Literal["attack"]
    target: str


class OocDiscussionAction(_BaseAction):
    action_type: Literal["ooc_discussion"]


class EquipAction(_BaseAction):
    action_type: Literal["equip"]
    target: str
    unequip_targets: list[str] = Field(default_factory=list)


class UnequipAction(_BaseAction):
    action_type: Literal["unequip"]
    target: str


PlayerActionType = Annotated[
    Union[
        MoveAction,
        ExamineAction,
        InteractAction,
        TalkAction,
        TransferAction,
        WaitAction,
        CombatAction,
        OocDiscussionAction,
        EquipAction,
        UnequipAction,
    ],
    Field(discriminator="action_type"),
]

_player_action_adapter = TypeAdapter(PlayerActionType)


def validate_player_action(data: dict) -> (
    MoveAction
    | ExamineAction
    | InteractAction
    | TalkAction
    | TransferAction
    | WaitAction
    | CombatAction
    | OocDiscussionAction
    | EquipAction
    | UnequipAction
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
        | CombatAction
        | OocDiscussionAction
        | EquipAction
        | UnequipAction
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
        | CombatAction
        | OocDiscussionAction
        | EquipAction
        | UnequipAction
    ):
        return _player_action_adapter.validate_json(json_str)


class HardStateChanges(BaseModel):
    player_location: Optional[str] = None
    inventory_added: Dict[str, int] = Field(default_factory=dict)
    inventory_removed: Dict[str, int] = Field(default_factory=dict)
    # Provenance for the inventory dicts above, used to derive item.acquired /
    # item.lost events with an accurate source/reason.  Keys are item IDs;
    # entries default to "interaction" when absent (see _derive_state_events).
    inventory_added_sources: Dict[str, str] = Field(default_factory=dict)
    inventory_removed_reasons: Dict[str, str] = Field(default_factory=dict)
    equipped_added: List[str] = Field(default_factory=list)
    equipped_removed: List[str] = Field(default_factory=list)
    equipment_changed: bool = False
    flags_set: Dict[str, bool] = Field(default_factory=dict)
    flags_cleared: List[str] = Field(default_factory=list)
    room_state_changes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    entity_state_changes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    stat_modifiers: Dict[str, StatModifier] = Field(default_factory=dict)
    old_stat_values: Dict[str, int] = Field(default_factory=dict)
    player_hp_delta: Optional[int] = None

    def merge(self, other: "HardStateChanges") -> "HardStateChanges":
        """Merge another HardStateChanges into this one in-place."""
        if other.player_location is not None:
            self.player_location = other.player_location
        for item_id, count in other.inventory_added.items():
            self.inventory_added[item_id] = self.inventory_added.get(item_id, 0) + count
        for item_id, count in other.inventory_removed.items():
            self.inventory_removed[item_id] = self.inventory_removed.get(item_id, 0) + count
        self.inventory_added_sources.update(other.inventory_added_sources)
        self.inventory_removed_reasons.update(other.inventory_removed_reasons)
        self.equipped_added.extend(other.equipped_added)
        self.equipped_removed.extend(other.equipped_removed)
        if other.equipment_changed:
            self.equipment_changed = True
        self.flags_set.update(other.flags_set)
        self.flags_cleared.extend(other.flags_cleared)
        for room_id, changes in other.room_state_changes.items():
            self.room_state_changes.setdefault(room_id, {}).update(changes)
        for entity_id, changes in other.entity_state_changes.items():
            self.entity_state_changes.setdefault(entity_id, {}).update(changes)
        for stat_key, mod in other.stat_modifiers.items():
            if mod.mode == "set":
                self.stat_modifiers[stat_key] = mod
            else:
                existing = self.stat_modifiers.get(stat_key)
                if existing is not None and existing.mode == "set":
                    self.stat_modifiers[stat_key] = StatModifier(
                        mode="set", value=existing.value + mod.value
                    )
                else:
                    prev = existing.value if existing else 0
                    self.stat_modifiers[stat_key] = StatModifier(
                        mode="delta", value=prev + mod.value
                    )
        for stat_key, old_val in other.old_stat_values.items():
            if stat_key not in self.old_stat_values:
                self.old_stat_values[stat_key] = old_val
        if other.player_hp_delta is not None:
            if self.player_hp_delta is not None:
                self.player_hp_delta += other.player_hp_delta
            else:
                self.player_hp_delta = other.player_hp_delta
        return self

    def has_changes(self) -> bool:
        """Return True if any field contains a change."""
        return (
            self.player_location is not None
            or bool(self.inventory_added)
            or bool(self.inventory_removed)
            or bool(self.equipped_added)
            or bool(self.equipped_removed)
            or self.equipment_changed
            or bool(self.flags_set)
            or bool(self.flags_cleared)
            or bool(self.room_state_changes)
            or bool(self.entity_state_changes)
            or bool(self.stat_modifiers)
            or self.player_hp_delta is not None
        )


class EncounterOutcome(BaseModel):
    encounter_id: str
    combat: bool = False
    narrative_brief: Optional[str] = None
    branch_taken: Optional[str] = None


class GameOverResult(BaseModel):
    type: str
    trigger: str
    narrative: Optional[str] = None


class DialogueExitedResult(BaseModel):
    npc_id: str
    exit_narrative: Optional[str] = None
    archival_fallback: Optional[str] = None


class WillRevealReadinessEntry(BaseModel):
    conditions_met: bool
    description: str
    conditions: List[ConditionStatus] = Field(default_factory=list)


class ConditionStatus(BaseModel):
    condition: str
    met: bool
    detail: str


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
    game_over: Optional[GameOverResult] = None
    dialogue_exited: Optional[DialogueExitedResult] = None
    will_reveal_readiness: Optional[Dict[str, Dict[str, WillRevealReadinessEntry]]] = None
    revelations_applied: List[RevelationApplied] = Field(default_factory=list)
    npc_attitude_limits: Optional[Dict[str, AttitudeLimitsCurrent]] = None
    attitude_changes_applied: Dict[str, AttitudeChange] = Field(default_factory=dict)
    attitude_changes_rejected: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    chain_info: Optional[ChainInfo] = None
    revealed_hints: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    combat_triggered: bool = False
    combat_log: list[CombatLogEntry] = Field(default_factory=list)
    costs_turn: bool = True
