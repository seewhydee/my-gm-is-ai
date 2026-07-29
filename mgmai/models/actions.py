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

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from mgmai.models.briefing import BriefingRoom
from mgmai.models.combat import CombatLogEntry
from mgmai.models.corpus import StatModifier
from mgmai.models.narration import AttitudeChange, SoftItemAdjudication
from mgmai.models.soft_state import SoftStatePatch

# Reserved sentinel used in player-action ``target`` fields to denote the
# player's current room.  Using this instead of the room's actual ID removes
# any need to disambiguate a room ID from an entity ID (the two namespaces
# are separate and need not be mutually disjoint).  See ``schema/corpus.md``.
CURRENT_ROOM_SENTINEL = "current_room"


class PositioningAssertion(BaseModel):
    """LLM-asserted positioning changes attached to a combat/wait/interact action.

    ``engage`` entries are symmetric pairs ``[a, b]`` (the two combatants
    are now within melee reach of each other); ``disengage`` entries are
    directional pairs ``[mover, stationary]`` (the mover leaves the
    stationary party's reach, provoking an opportunity attack from the
    stationary party); ``impede`` entries are enemy combatant ids delayed
    by an obstacle (they spend their next turn closing in).  The engine
    re-validates every entry at apply time and drops malformed ones with
    a warning; the core action always proceeds.
    """
    engage: list[list[str]] = Field(default_factory=list)
    disengage: list[list[str]] = Field(default_factory=list)
    impede: list[str] = Field(default_factory=list)


class _BaseAction(BaseModel):
    detail: str
    follow_up: str | None = None
    soft_state_patches: list[SoftStatePatch] = Field(default_factory=list)
    positioning: PositioningAssertion | None = None


class MoveAction(_BaseAction):
    action_type: Literal["move"]
    target: str
    style: str | None = None
    using: str | None = None


class ExamineAction(_BaseAction):
    action_type: Literal["examine"]
    target: str
    rigorous: bool = False
    using: str | None = None


class InteractAction(_BaseAction):
    action_type: Literal["interact"]
    target: str
    interaction_id: str
    using: str | None = None


class TalkAction(_BaseAction):
    action_type: Literal["talk"]
    target: str
    utterance: str | None = None
    ends_dialogue: bool = False
    dialogue_path: str | None = None


class TransferAction(_BaseAction):
    action_type: Literal["transfer"]
    target: str
    given_items: list[str] | None = None
    taken_items: list[str] | None = None
    given_counts: dict[str, int] | None = None
    taken_counts: dict[str, int] | None = None

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


class RestAction(_BaseAction):
    action_type: Literal["rest"]
    kind: Literal["short", "long"]


class CombatAction(_BaseAction):
    action_type: Literal["combat"]
    combat_action: Literal["attack", "maneuver"]
    target: str | None = None
    maneuver: Literal["disengage"] | None = None

    @model_validator(mode="after")
    def check_target_requirement(self) -> CombatAction:
        if self.combat_action != "maneuver" and not self.target:
            raise ValueError(
                f"combat action '{self.combat_action}' requires a target"
            )
        return self


class UseAbilityAction(_BaseAction):
    action_type: Literal["use_ability"]
    ability_id: str
    target: str | None = None


class OocDiscussionAction(_BaseAction):
    action_type: Literal["ooc_discussion"]


class GearAction(_BaseAction):
    action_type: Literal["gear"]
    equip_targets: list[str] = Field(default_factory=list)
    unequip_targets: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_non_empty_gear_change(self) -> GearAction:
        if not self.equip_targets and not self.unequip_targets:
            raise ValueError(
                "GearAction must have at least one of equip_targets or "
                "unequip_targets be non-empty")
        for field_name, targets in (
            ("equip_targets", self.equip_targets),
            ("unequip_targets", self.unequip_targets),
        ):
            if len(set(targets)) != len(targets):
                raise ValueError(
                    f"GearAction {field_name} must not contain duplicates")
        return self


PlayerActionType = Annotated[
    MoveAction | ExamineAction | InteractAction | TalkAction | TransferAction | WaitAction | RestAction | CombatAction | UseAbilityAction | OocDiscussionAction | GearAction,
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
    | RestAction
    | CombatAction
    | UseAbilityAction
    | OocDiscussionAction
    | GearAction
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
        | RestAction
        | CombatAction
        | UseAbilityAction
        | OocDiscussionAction
        | GearAction
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
        | RestAction
        | CombatAction
        | UseAbilityAction
        | OocDiscussionAction
        | GearAction
    ):
        return _player_action_adapter.validate_json(json_str)


class HardStateChanges(BaseModel):
    player_location: str | None = None
    inventory_added: dict[str, int] = Field(default_factory=dict)
    inventory_removed: dict[str, int] = Field(default_factory=dict)
    # Provenance for the inventory dicts above, used to derive item.acquired /
    # item.lost events with an accurate source/reason.  Keys are item IDs;
    # entries default to "interaction" when absent (see _derive_state_events).
    inventory_added_sources: dict[str, str] = Field(default_factory=dict)
    inventory_removed_reasons: dict[str, str] = Field(default_factory=dict)
    equipped_added: list[str] = Field(default_factory=list)
    equipped_removed: list[str] = Field(default_factory=list)
    equipment_changed: bool = False
    flags_set: dict[str, bool] = Field(default_factory=dict)
    flags_cleared: list[str] = Field(default_factory=list)
    room_state_changes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    entity_state_changes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    stat_modifiers: dict[str, StatModifier] = Field(default_factory=dict)
    old_stat_values: dict[str, int] = Field(default_factory=dict)
    player_hp_delta: int | None = None
    # Directional components of player_hp_delta (positive magnitudes):
    # player_damage_delta accumulates HP lost, player_heal_delta HP gained.
    # They let the narrative indicators show healing and damage as separate
    # events instead of one misleading net figure on mixed turns.  Code that
    # needs the net change should keep reading player_hp_delta.
    player_damage_delta: int | None = None
    player_heal_delta: int | None = None
    # World-side containment deltas. Keys are room/container IDs; values are
    # {entity_id: count} maps. Added counts are summed on merge.
    room_contains_added: dict[str, dict[str, int]] = Field(default_factory=dict)
    room_contains_removed: dict[str, dict[str, int]] = Field(default_factory=dict)
    entity_contains_added: dict[str, dict[str, int]] = Field(default_factory=dict)
    entity_contains_removed: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Author-facing entity placements derived from set_entity_state "location".
    # {entity_id: "room:<id>" | "entity:<id>" | None}.  Merged by dict-overwrite
    # (last wins), unlike the count-summed containment deltas above.
    entity_placements: dict[str, str | None] = Field(default_factory=dict)

    @staticmethod
    def _merge_nested_counts(
        target: dict[str, dict[str, int]],
        source: dict[str, dict[str, int]],
    ) -> None:
        """Sum nested {container_id: {entity_id: count}} maps into *target*."""
        for container_id, entries in source.items():
            target.setdefault(container_id, {})
            for entity_id, count in entries.items():
                target[container_id][entity_id] = (
                    target[container_id].get(entity_id, 0) + count
                )

    def merge(self, other: HardStateChanges) -> HardStateChanges:
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
        self._merge_nested_counts(
            self.room_contains_added, other.room_contains_added
        )
        self._merge_nested_counts(
            self.room_contains_removed, other.room_contains_removed
        )
        self._merge_nested_counts(
            self.entity_contains_added, other.entity_contains_added
        )
        self._merge_nested_counts(
            self.entity_contains_removed, other.entity_contains_removed
        )
        self.entity_placements.update(other.entity_placements)
        if other.player_hp_delta is not None:
            if self.player_hp_delta is not None:
                self.player_hp_delta += other.player_hp_delta
            else:
                self.player_hp_delta = other.player_hp_delta
        if other.player_damage_delta is not None:
            self.player_damage_delta = (
                (self.player_damage_delta or 0) + other.player_damage_delta
            )
        if other.player_heal_delta is not None:
            self.player_heal_delta = (
                (self.player_heal_delta or 0) + other.player_heal_delta
            )
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
            or self.player_damage_delta is not None
            or self.player_heal_delta is not None
            or bool(self.room_contains_added)
            or bool(self.room_contains_removed)
            or bool(self.entity_contains_added)
            or bool(self.entity_contains_removed)
            or bool(self.entity_placements)
        )


class RestRechargeResult(BaseModel):
    """What a rest restores, as decided by the resolution system.

    The engine records that a rest occurred and emits a ``rest.completed``
    event; the system hook decides what that *means* for the active rules
    (5e: refill slots to max, heal, recover hit dice, reduce exhaustion on
    a long rest) and returns it here.  The resolver applies it
    deterministically — system hooks never mutate ``hard`` directly.

    HP healing flows through ``HardStateChanges.player_hp_delta`` (so the
    prose LLM and event derivation see it); slot/hit-dice/exhaustion
    changes are applied directly to ``hard.player`` by the resolver, like
    ``apply_status_effect`` / ``remove_status_effect``.
    """

    # Positive = HP gained. The resolver builds HardStateChanges.player_hp_delta
    # from this.
    hp_delta: int = 0
    # True → set spell_slots := max_spell_slots for every declared level.
    slots_refilled_to_max: bool = False
    # Status-effect IDs to clear from the player (e.g. time-limited buffs
    # ended by a long rest). Exhaustion is NOT listed here — it is handled
    # by ``exhaustion_decrement``.
    statuses_to_clear: list[str] = Field(default_factory=list)
    # Number of spent Hit Dice to recover (SRD 5.2.1 long rest: all of them).
    hit_dice_recovered: int = 0
    # 1 → reduce the player's exhaustion level by one step on a long rest;
    # 0 otherwise.
    exhaustion_decrement: int = 0
    # Follower NPC IDs restored to full HP by the rest (5e long rest heals
    # the party; NPCs get no hit-dice tracking, so this is a full heal).
    followers_healed: list[str] = Field(default_factory=list)


class EncounterOutcome(BaseModel):
    encounter_id: str
    combat: bool = False
    narrative_brief: str | None = None
    branch_taken: str | None = None


class SoftItemProposal(BaseModel):
    item_name: str
    action: Literal["take", "give", "examine"]
    source_id: str
    target_id: str | None = None
    count: int = 1
    proposed_by: Literal["call_1"] = "call_1"


class GameOverResult(BaseModel):
    type: str
    trigger: str
    narrative: str | None = None


class DialogueExitedResult(BaseModel):
    npc_id: str
    exit_narrative: str | None = None
    archival_fallback: str | None = None


class WillRevealReadinessEntry(BaseModel):
    conditions_met: bool
    description: str
    conditions: list[ConditionStatus] = Field(default_factory=list)


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
    side_effects_applied: list[str] = Field(default_factory=list)


class ChainInfo(BaseModel):
    follow_up: str | None = None
    termination_reason: str | None = None


class EngineResult(BaseModel):
    success: bool
    action_type: str
    target: str | None = None
    error: str | None = None
    message: str | None = None
    player_input_echo: str | None = None
    room_after: BriefingRoom | None = None
    hard_state_changes: HardStateChanges | None = None
    soft_state_patches_applied: list[SoftStatePatch] = Field(default_factory=list)
    soft_state_patches_rejected: list[dict[str, Any]] = Field(default_factory=list)
    rolls: list[dict[str, Any]] = Field(default_factory=list)
    encounter_outcome: EncounterOutcome | None = None
    triggered_narration: list[str] = Field(default_factory=list)
    game_over: GameOverResult | None = None
    dialogue_exited: DialogueExitedResult | None = None
    will_reveal_readiness: dict[str, dict[str, WillRevealReadinessEntry]] | None = None
    revelations_applied: list[RevelationApplied] = Field(default_factory=list)
    npc_attitude_limits: dict[str, AttitudeLimitsCurrent] | None = None
    attitude_changes_applied: dict[str, AttitudeChange] = Field(default_factory=dict)
    attitude_changes_rejected: dict[str, dict[str, Any]] = Field(default_factory=dict)
    chain_info: ChainInfo | None = None
    revealed_hints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    combat_triggered: bool = False
    combat_log: list[CombatLogEntry] = Field(default_factory=list)
    costs_turn: bool = True
    soft_item_proposals: list[SoftItemProposal] = Field(default_factory=list)
    soft_content_takes: dict[str, dict[str, int]] = Field(default_factory=dict)
    soft_items_accepted: list[SoftItemAdjudication] = Field(default_factory=list)
    soft_items_rejected: list[dict[str, Any]] = Field(default_factory=list)
