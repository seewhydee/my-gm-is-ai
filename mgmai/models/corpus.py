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
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator

IMMEDIATE_ALLOWED_EVENTS = frozenset({
    "interaction.used",
    "traversal.attempted",
    "room.entered",
})


class Credits(BaseModel):
    author: Optional[str] = None
    source: Optional[str] = None
    license: Optional[str] = None


class Atmosphere(BaseModel):
    setting: str
    tone: str


class Adventure(BaseModel):
    id: Optional[str] = None
    title: str
    credits: Optional[Credits] = None
    introduction: str
    atmosphere: Optional[Atmosphere] = None


class ConditionExpression(BaseModel):
    require: Optional[str] = None
    unless: Optional[str] = None
    any_of: Optional[List[Union[str, ConditionExpression]]] = Field(
        default=None, alias="any"
    )
    all_of: Optional[List[Union[str, ConditionExpression]]] = Field(
        default=None, alias="all"
    )

    @model_validator(mode="after")
    def check_exactly_one(self) -> ConditionExpression:
        present = [
            k
            for k in ("require", "unless", "any_of", "all_of")
            if getattr(self, k) is not None
        ]
        if len(present) != 1:
            raise ValueError(
                f"ConditionExpression must have exactly one of: "
                f"require, unless, any, all. Got: {present}"
            )
        return self


class ParameterSignature(BaseModel):
    target: Optional[List[str]] = None
    using: Optional[List[str]] = None


class StatModifier(BaseModel):
    mode: Literal["delta", "set"] = "delta"
    value: int


class EquipBlock(BaseModel):
    """Describes how an item interacts with the equipment system.

    Only present on item-type entities.  ``None`` means the item cannot
    be equipped (keys, potions, quest items, etc.).
    """
    equip_tags: list[str]
    incompatible_with: list[str] = Field(default_factory=list)
    equip_effects: Dict[str, StatModifier] = Field(default_factory=dict)
    ac_override: int | None = None
    ac_bonus: int = 0
    two_handed: bool = False
    max_equipped: int | None = 1
    damage_expr: str = "1d8"
    attack_bonus: int = 0


class ChainedCheck(BaseModel):
    check: CheckType
    success: Result
    failure: Optional[Result] = None


class Result(BaseModel):
    narrative: Optional[str] = None
    add_item: Optional[str] = None
    remove_item: Optional[str] = None
    set_flag: Optional[Dict[str, bool]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    set_room_state: Optional[Dict[str, Dict[str, Any]]] = None
    adjust_attitude: Optional[Dict[str, int]] = None
    reveals: Optional[str] = None
    chain_check: Optional[ChainedCheck] = None

    def has_any_effect(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in (
                "narrative", "add_item", "remove_item",
                "set_flag", "alter_stat", "set_entity_state", "set_room_state",
                "adjust_attitude", "reveals", "chain_check",
            )
        )


class RollCheck(BaseModel):
    type: Literal["roll"] = "roll"
    threshold: float = Field(ge=0.0, le=1.0)
    repeatable: bool
    note: Optional[str] = None


class StatCheck(BaseModel):
    type: Literal["stat_check"] = "stat_check"
    stat: str
    dc: int
    modifier: int = 0
    resolution_params: Optional[Dict[str, Any]] = None
    opposed_by: Optional[str] = None
    repeatable: bool
    note: Optional[str] = None
    skill: Optional[str] = None


CheckType = RollCheck | StatCheck


class UsingResultOverride(BaseModel):
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None
    result: Optional[Result] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> UsingResultOverride:
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check and has_result:
            raise ValueError("UsingResultOverride must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError("UsingResultOverride with 'check' must also have 'success'")
        return self


class TakeCheck(BaseModel):
    """A check required to take an item via a transfer action."""

    check: CheckType
    success: Optional[Result] = None
    failure: Optional[Result] = None

    @model_validator(mode="after")
    def check_success_on_check(self) -> "TakeCheck":
        if self.check is not None and self.success is None:
            raise ValueError("TakeCheck with 'check' must also have 'success'")
        return self


class Interaction(BaseModel):
    id: str
    label: str
    description: Optional[str] = None
    parameter_signature: Optional[ParameterSignature] = None
    condition: Optional[ConditionExpression] = None
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None
    result: Optional[Result] = None
    using_results: Optional[Dict[str, UsingResultOverride]] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> Interaction:
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check and has_result:
            raise ValueError("Interaction must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError("Interaction with 'check' must also have 'success'")
        return self


class TraversalEffect(BaseModel):
    set_flag: Optional[Dict[str, bool]] = None
    set_room_state: Optional[Dict[str, Dict[str, Any]]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    narrative: Optional[str] = None
    trigger_encounter: Optional[str] = None
    skip_if: Optional[ConditionExpression] = None
    narrative_skip: Optional[str] = None


class TraversalCheck(BaseModel):
    check: CheckType
    condition: Optional[ConditionExpression] = None
    skip_check_if: Optional[ConditionExpression] = None
    failure_narrative: Optional[str] = None


class Exit(BaseModel):
    id: str
    direction: str
    target_room: str
    conditions: List[ConditionExpression] = Field(default_factory=list)
    on_traverse: Optional[TraversalEffect] = None
    hidden: bool = False
    one_way: bool = False
    traversal_check: Optional[TraversalCheck] = None


class OnEnterEvent(BaseModel):
    id: str
    condition: Optional[ConditionExpression] = None
    narrative: Optional[str] = None
    set_flag: Optional[Dict[str, bool]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    set_room_state: Optional[Dict[str, Dict[str, Any]]] = None
    trigger_dialogue: Optional[str] = None


class OnExamineEvent(BaseModel):
    id: str
    condition: Optional[ConditionExpression] = None
    rigorous_only: bool = False
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None
    result: Optional[Result] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> OnExamineEvent:
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check and has_result:
            raise ValueError("OnExamineEvent must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError("OnExamineEvent with 'check' must also have 'success'")
        return self


class GameOverTrigger(BaseModel):
    type: Literal["win", "lose"]
    trigger_id: str


class ReactionEffects(BaseModel):
    result: Optional[Result] = None
    trigger_encounter: Optional[str] = None
    trigger_dialogue: Optional[str] = None
    game_over: Optional[GameOverTrigger] = None

    @model_validator(mode="after")
    def check_non_empty(self) -> ReactionEffects:
        has_result = self.result is not None and self.result.has_any_effect()
        has_reaction = any(
            f is not None
            for f in (self.trigger_encounter, self.trigger_dialogue, self.game_over)
        )
        if not has_result and not has_reaction:
            raise ValueError("ReactionEffects must have at least one effect set")
        return self


class Reaction(BaseModel):
    id: str
    on: str
    condition: Optional[ConditionExpression] = None
    effects: ReactionEffects
    once: bool = False
    priority: int = 0
    phase: Literal["immediate", "deferred"] = "deferred"

    @model_validator(mode="after")
    def validate_phase(self) -> Reaction:
        if self.phase == "immediate" and self.on not in IMMEDIATE_ALLOWED_EVENTS:
            raise ValueError(
                f"phase='immediate' is only allowed for events: "
                f"{sorted(IMMEDIATE_ALLOWED_EVENTS)}. Got: {self.on!r}"
            )
        return self


class Room(BaseModel):
    name: str
    description: str
    entities_present: List[str] = Field(default_factory=list)
    soft_items: List[str] = Field(default_factory=list)
    exits: List[Exit] = Field(default_factory=list)
    interactions: List[Interaction] = Field(default_factory=list)
    on_enter: List[OnEnterEvent] = Field(default_factory=list)
    on_examine: List[OnExamineEvent] = Field(default_factory=list)
    is_start_room: bool = False
    reactions: List[Reaction] = Field(default_factory=list)


class StateFieldDecl(BaseModel):
    type: Literal["boolean", "number", "string"]
    description: str


class AttitudeLimits(BaseModel):
    min: int
    max: int
    step_per_turn: int = 1
    initial: int = 0


class WillRevealEntry(BaseModel):
    description: str
    conditions: List[str] = Field(default_factory=list)
    set_flag: Optional[Dict[str, bool]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None


class DialogueExit(BaseModel):
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    set_flag: Optional[Dict[str, bool]] = None
    narrative: Optional[str] = None


class DialoguePath(BaseModel):
    description: str
    condition: Optional[ConditionExpression] = None
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None
    result: Optional[Result] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> "DialoguePath":
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check and has_result:
            raise ValueError(
                "DialoguePath must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError("DialoguePath with 'check' must also have 'success'")
        return self


class DialogueGuidelines(BaseModel):
    personality: str
    on_encounter: str = ""
    can: List[str] = Field(default_factory=list)
    cannot: List[str] = Field(default_factory=list)
    knows: List[str] = Field(default_factory=list)
    attitude_limits: AttitudeLimits
    will_reveal: Dict[str, WillRevealEntry] = Field(default_factory=dict)
    on_dialogue_exit: Optional[DialogueExit] = None
    dialogue_paths: Dict[str, DialoguePath] = Field(default_factory=dict)


class BranchOutcome(BaseModel):
    outcome: str
    set_flags: Optional[Dict[str, bool]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    narrative: Optional[str] = None


class EncounterRule(BaseModel):
    condition: ConditionExpression
    outcome: Literal["death", "flee", "roll", "stat_check", "combat"]
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    check: Optional[StatCheck] = None
    narrative: Optional[str] = None
    set_flags: Optional[Dict[str, bool]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    on_success: Optional[BranchOutcome] = None
    on_failure: Optional[BranchOutcome] = None


class FleeEffect(BaseModel):
    set_flags: Dict[str, bool]
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    effect: str


class Behavior(BaseModel):
    triggers_on: List[str] = Field(default_factory=list)
    encounter_rules: List[EncounterRule] = Field(default_factory=list)
    on_flee: Optional[FleeEffect] = None


class Entity(BaseModel):
    type: Literal["player", "feature", "npc", "item"]
    description: str
    spans_rooms: Optional[List[str]] = None
    soft_items: List[str] = Field(default_factory=list)
    contained_entities: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    draggable: bool = False
    dragging_note: Optional[str] = None
    take_check: Optional[TakeCheck] = None
    interactions: List[Interaction] = Field(default_factory=list)
    on_examine: List[OnExamineEvent] = Field(default_factory=list)
    dialogue_guidelines: Optional[DialogueGuidelines] = None
    behavior: Optional[Behavior] = None
    state_fields: Dict[str, StateFieldDecl] = Field(default_factory=dict)
    follower_blacklist: Optional[List[str]] = None
    combat: Optional[CombatBlock] = None
    equip_block: Optional[EquipBlock] = None
    reactions: List[Reaction] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_type_specific_fields(self) -> Entity:
        if self.type != "npc" and self.dialogue_guidelines is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'dialogue_guidelines'. "
                f"Only 'npc' entities may carry dialogue_guidelines.")
        if self.type != "npc" and self.behavior is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'behavior'. "
                f"Only 'npc' entities may carry behavior.")
        if self.type != "npc" and self.combat is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'combat'. "
                f"Only 'npc' entities may carry combat.")
        if self.type != "item" and self.equip_block is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'equip_block'. "
                f"Only 'item' entities may carry equip_block.")
        return self


class Mechanic(BaseModel):
    id: str
    description: str
    type: Optional[Literal["win", "lose"]] = None
    condition: Optional[ConditionExpression] = None
    narrative: Optional[str] = None
    trigger_id: Optional[str] = None
    rules: Optional[List[EncounterRule]] = None
    reactions: List[Reaction] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_shape(self) -> Mechanic:
        is_game_over = self.type is not None
        is_encounter = self.rules is not None
        if is_game_over and is_encounter:
            raise ValueError(
                "Mechanic must be either a game-over condition (type, condition, trigger_id) "
                "or an encounter (rules), not both")
        if is_game_over:
            if self.condition is None:
                raise ValueError("Game-over mechanic requires 'condition'")
            if self.trigger_id is None:
                raise ValueError("Game-over mechanic requires 'trigger_id'")
        if not is_game_over and not is_encounter:
            raise ValueError(
                "Mechanic must have either 'type' (game-over) or 'rules' (encounter)")
        return self


class StatDefinition(BaseModel):
    name: str
    description: str


class CombatBlock(BaseModel):
    """NPC combat stat block (5e-flavoured but corpus-agnostic).

    All values are pre-computed by the adventure author.  NPCs without
    this block cannot participate in HP-based combat.
    """
    hp: int = Field(gt=0)
    ac: int
    atk: int
    dmg: str = "1d6"
    initiative_mod: int = 0
    flee_dc: int = 10


class StatsBlock(BaseModel):
    definitions: Dict[str, StatDefinition]
    system: str = "5e"

    @model_validator(mode="after")
    def check_system(self) -> StatsBlock:
        supported = {"5e"}
        if self.system not in supported:
            raise ValueError(f"Unknown RPG system: {self.system!r}. ")
        return self


class ModuleCorpus(BaseModel):
    adventure: Adventure
    rooms: Dict[str, Room]
    entities: Dict[str, Entity]
    mechanics: Dict[str, Mechanic] = Field(default_factory=dict)
    flags_declared: Optional[List[str]] = None
    stats: Optional[StatsBlock] = None
