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
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from mgmai.datapack import load_pack

IMMEDIATE_ALLOWED_EVENTS = frozenset({
    "interaction.used",
    "traversal.attempted",
    "traversal.succeeded",
    "room.entered",
})

RESERVED_ROOM_STATE_FIELDS = frozenset({"visited", "is_current"})

# Default initial values for reserved state fields used by the world-state
# generator when a field declaration omits an explicit ``initial``.
RESERVED_STATE_FIELD_DEFAULTS: dict[str, Any] = {
    "alive": True,
    "following": False,
    "open": False,
    "visited": False,
}

# Reserved entity state fields.  These need NOT be declared in an entity's
# ``state_fields`` unless the author overrides the default initial value
# (see corpus.md).  ``location`` is also reserved, but it is derived from
# containment and managed separately, so it is not listed here.
RESERVED_ENTITY_STATE_FIELDS = frozenset({
    "alive",
    "attitude",
    "hidden",
    "following",
    "open",
    "current_hp",
})

# Default values for reserved entity state fields when they are not declared
# (``current_hp`` is context-sensitive and handled separately below).
RESERVED_ENTITY_STATE_FIELD_DEFAULTS: dict[str, Any] = {
    "alive": True,
    "attitude": 0,
    "hidden": False,
    "following": False,
    "open": False,
}


def reserved_entity_field_default(
    field_name: str, entity: "Entity | None" = None
) -> Any:
    """Default value of a reserved entity state field.

    Returns the documented default for reserved fields that are valid
    without a declaration, or ``None`` if *field_name* is not a reserved
    entity state field.  ``current_hp`` defaults to the entity's combat
    block HP when it has one, else 0.
    """
    if field_name == "current_hp":
        if entity is not None and entity.combat is not None:
            return entity.combat.hp
        return 0
    return RESERVED_ENTITY_STATE_FIELD_DEFAULTS.get(field_name)

# A flags_declared entry is either a plain string (starts false) or a
# single-key dict mapping a flag id to its initial boolean value.
FlagDecl = Union[str, Dict[str, bool]]


def _normalize_contains(contains: List[Union[str, Dict[str, int]]]) -> Dict[str, int]:
    """Normalise a mixed-type contains list into a {entity_id: count} map.

    Plain strings count as 1. Dict elements must be single-key count objects.
    Duplicate IDs have their counts summed.
    """
    result: Dict[str, int] = {}
    for entry in contains:
        if isinstance(entry, str):
            result[entry] = result.get(entry, 0) + 1
        elif isinstance(entry, dict):
            if len(entry) != 1:
                raise ValueError(
                    "Each count-object in 'contains' must have exactly one key"
                )
            for eid, count in entry.items():
                if not isinstance(count, int) or count < 1:
                    raise ValueError(
                        f"Count for '{eid}' in 'contains' must be a positive integer"
                    )
                result[eid] = result.get(eid, 0) + count
        else:
            raise ValueError(
                "Each entry in 'contains' must be a string or a single-key count-object"
            )
    return result


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



class StatModifier(BaseModel):
    mode: Literal["delta", "set"] = "delta"
    value: int


class ApplyStatusEffect(BaseModel):
    """Apply a status effect (e.g. poisoned) to a target.

    The status effect's definition (scope, duration, system effects) comes
    from the corpus ``status_effects`` block, overlaid on the engine's
    built-in defaults (see ``StatusEffectDef``).  ``target`` is ``"player"``
    or an entity ID.
    """
    id: str
    rounds: int = 1
    target: str = "player"


class StatusEffectDef(BaseModel):
    """Definition of a status effect (e.g. poisoned, stunned).

    Status effects live in the top-level corpus ``status_effects`` block,
    keyed by status effect ID (the key is canonical; ``name`` is cosmetic).
    The SRD conditions are built-in engine defaults (``DEFAULT_STATUS_EFFECTS``,
    loaded from the bundled data pack); a corpus entry with the same ID
    replaces the default wholesale.

    - ``scope: "combat"`` — ticks at the start of the afflicted
      combatant's turn; cleared at combat end.
    - ``scope: "persistent"`` — ticks on ``turn.end`` (turn-costing
      actions only); survives combat end.
    - ``duration: "rounds"`` — decrements on each tick, expires at zero.
    - ``duration: "until_turn_start"`` — removed on the afflicted's
      first tick (legacy ``prone`` behavior).
    - ``duration: "until_cleared"`` — never ticks down; removed only by
      curing, combat end (combat-scoped), or a manual Result.
    """
    name: str = ""
    description: str = ""
    scope: Literal["combat", "persistent"] = "combat"
    duration: Literal["rounds", "until_cleared", "until_turn_start"] = "rounds"
    skip_turn: bool = False
    tick_effect: Optional[Result] = None
    system_effects: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class EquipBlock(BaseModel):
    """Describes how an item interacts with the equipment system.

    Only present on item-type entities.  ``None`` means the item cannot
    be equipped (keys, potions, quest items, etc.).

    Core fields are system-agnostic; extra top-level keys are accepted
    so individual RPG systems can attach their own mechanics (e.g. 5e
    ``ac_override``, ``ac_bonus``).
    """
    model_config = ConfigDict(extra="allow")

    equip_tags: list[str]
    incompatible_with: list[str] = Field(default_factory=list)
    stat_effects: Dict[str, StatModifier] = Field(default_factory=dict)
    max_equipped: int | None = 1
    damage_expr: str = "1d8"
    hit_bonus: int = 0
    properties: list[str] = Field(default_factory=list)
    damage_type: str = ""

    def effects_summary(self) -> str:
        """Compact mechanical-effects summary, shared by briefing and /inv."""
        parts: list[str] = []
        for stat_key, mod in self.stat_effects.items():
            if mod.mode == "set":
                parts.append(f"{stat_key} = {mod.value}")
            else:
                sign = "+" if mod.value >= 0 else ""
                parts.append(f"{stat_key} {sign}{mod.value}")
        # 5e-specific extras are stored as extra fields; use getattr so
        # non-5e systems (or items without them) still work.
        ac_override = getattr(self, "ac_override", None)
        if ac_override is not None:
            parts.append(f"AC {ac_override}")
        ac_bonus = getattr(self, "ac_bonus", 0)
        if ac_bonus != 0:
            parts.append(f"AC {'+' if ac_bonus >= 0 else ''}{ac_bonus}")
        if "weapon" in self.equip_tags:
            parts.append(f"{self.damage_expr} damage")
            if self.hit_bonus != 0:
                parts.append(
                    f"{'+' if self.hit_bonus >= 0 else ''}{self.hit_bonus} to hit"
                )
        return ", ".join(parts)


class ConsumableBlock(BaseModel):
    """Describes how an item is consumed (potion drunk, scroll read, …).

    Only present on item-type entities.  Usable in combat via the
    ``use_item`` combat action, which consumes the player's action.
    """
    heal: str = ""                              # dice expression, e.g. "2d4+2"
    cure_status_effects: list[str] = Field(default_factory=list)
    destroy: bool = True                        # consume one count on use

    def effects_summary(self) -> str:
        """Compact plain-English summary for briefings and display."""
        parts: list[str] = []
        if self.heal:
            parts.append(f"heals {self.heal}")
        if self.cure_status_effects:
            parts.append(f"cures {', '.join(self.cure_status_effects)}")
        return ", ".join(parts)


class Result(BaseModel):
    narrative: Optional[str] = None
    add_item: Optional[List[str]] = None
    add_item_count: Optional[Dict[str, int]] = None
    remove_item: Optional[List[str]] = None
    remove_item_count: Optional[Dict[str, int]] = None
    set_flag: Optional[Dict[str, bool]] = None
    alter_stat: Optional[Dict[str, StatModifier]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None
    set_room_state: Optional[Dict[str, Dict[str, Any]]] = None
    adjust_attitude: Optional[Dict[str, int]] = None
    reveals: Optional[str] = None
    apply_status_effect: Optional[ApplyStatusEffect] = None
    then_check: Optional[CheckResolution] = None
    player_damage: Optional[str] = None
    player_heal: Optional[str] = None
    set_player_location: Optional[str] = None
    game_over: Optional[GameOverTrigger] = None
    start_combat: Optional[List[str]] = None

    def has_any_effect(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in (
                "narrative", "add_item", "add_item_count",
                "remove_item", "remove_item_count",
                "set_flag", "alter_stat", "set_entity_state", "set_room_state",
                "adjust_attitude", "reveals", "then_check",
                "player_damage", "player_heal", "set_player_location",
            )
        ) or self.game_over is not None or self.start_combat is not None


class RollCheck(BaseModel):
    type: Literal["roll"] = "roll"
    threshold: float = Field(ge=0.0, le=1.0)
    repeatable: bool


class StatCheck(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["stat_check"] = "stat_check"
    stat: str
    target: int
    modifier: int = 0
    save: bool = False
    repeatable: bool


CheckType = RollCheck | StatCheck


class Checkable(BaseModel):
    """A probabilistic check with success/failure branches.

    Shared by GatedCheck, Resolvable, Interaction, OnExamineEvent,
    and CheckResolution. Subclasses add their own fields
    (condition, result, gating, using_results, id, rigorous_only, ...)
    and validators that tighten optionality per their semantics.
    """
    skip_check_if: Optional[ConditionExpression] = None
    check: Optional[CheckType] = None
    success: Optional[Result] = None
    failure: Optional[Result] = None


class CheckResolution(Checkable):
    """A self-contained check resolution: a check plus its outcome branches.

    Carried by Result.then_check, resolved immediately after the parent
    result's own effects. Used both as a follow-up (fail STR -> roll DEX to
    catch the key) and as the sole content of a result (a reaction whose
    effect is just a check).
    """
    check: CheckType
    success: Result
    tag: Optional[str] = None

    @model_validator(mode="after")
    def require_check_and_success(self) -> "CheckResolution":
        if self.check is None:
            raise ValueError("CheckResolution requires 'check'")
        if self.success is None:
            raise ValueError("CheckResolution requires 'success'")
        return self


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
        return self


class GatedCheck(Checkable):
    """A check gated by a condition. Used for take checks and traversal checks."""

    check: CheckType
    gating: Optional[ConditionExpression] = None
    using_results: Optional[Dict[str, UsingResultOverride]] = None


class Resolvable(Checkable):
    """The shared primitive for id-bearing, condition-gated resolution nodes.

    Base for Interaction (room/entity), OnExamineEvent, and the entries
    of an NPC's dialogue_paths.  Subclasses tighten optionality per
    their context (e.g. Interaction requires id and description).
    """
    id: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[ConditionExpression] = None
    result: Optional[Result] = None
    using_results: Optional[Dict[str, UsingResultOverride]] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> "Resolvable":
        has_check = self.check is not None
        has_result = self.result is not None
        if not has_check and not has_result:
            raise ValueError(
                "Resolvable must have at least one of 'check' or 'result'")
        if has_check and has_result:
            raise ValueError(
                "Resolvable must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError(
                "Resolvable with 'check' must also have 'success'")
        return self


class Interaction(Resolvable):
    """A room/entity-scoped Resolvable with required id and description."""
    id: str = Field(...)
    description: str = Field(...)


class Exit(BaseModel):
    id: str
    direction: str
    target_room: str
    condition: Optional[ConditionExpression] = None
    one_way: bool = False
    traversal_check: Optional[GatedCheck] = None


class OnExamineEvent(Resolvable):
    """A Resolvable tied to the examine action, with rigorous-only gating."""
    rigorous_only: bool = False


class GameOverTrigger(BaseModel):
    type: Literal["win", "lose"]
    trigger_id: str


class GameOverCondition(BaseModel):
    """A cross-cutting win/loss predicate polled once at end of turn.

    For outcomes owned by a single result (a specific killing blow, a fatal
    choice), prefer inline ``Result.game_over``.  Use this only for terminal
    states reachable from several paths with no single inline home.
    """
    type: Literal["win", "lose"]
    condition: ConditionExpression
    trigger_id: str
    narrative: Optional[str] = None


class ReactionEffects(BaseModel):
    result: Optional[Result] = None
    trigger_encounter: Optional[str] = None
    trigger_dialogue: Optional[str] = None

    @model_validator(mode="after")
    def check_non_empty(self) -> ReactionEffects:
        has_result = self.result is not None and self.result.has_any_effect()
        has_reaction = any(
            f is not None
            for f in (self.trigger_encounter, self.trigger_dialogue)
        )
        if not has_result and not has_reaction:
            raise ValueError("ReactionEffects must have at least one effect set")
        return self


class Reaction(BaseModel):
    id: str
    on: str
    condition: Optional[ConditionExpression] = None
    effect: ReactionEffects
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
    contains: List[Union[str, Dict[str, int]]] = Field(default_factory=list)
    soft_item_guidance: Optional[str] = None
    exits: List[Exit] = Field(default_factory=list)
    interactions: List[Interaction] = Field(default_factory=list)
    on_examine: List[OnExamineEvent] = Field(default_factory=list)
    is_start_room: bool = False
    reactions: List[Reaction] = Field(default_factory=list)
    state_fields: Dict[str, StateFieldDecl] = Field(default_factory=dict)
    _contains_map: Dict[str, int] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _build_contains_map(self) -> "Room":
        self._contains_map = _normalize_contains(self.contains)
        return self

    @property
    def contains_map(self) -> Dict[str, int]:
        """Normalised {entity_id: count} view of ``contains``.

        Runtime code must use this property or the runtime maps in
        ``HardGameState``; never iterate the raw ``contains`` list directly.
        """
        return dict(self._contains_map)


class StateFieldDecl(BaseModel):
    type: Literal["boolean", "number", "string"]
    description: str
    initial: Any = None

    @model_validator(mode="after")
    def validate_initial_type(self) -> "StateFieldDecl":
        if self.initial is None:
            return self
        if self.type == "boolean":
            if not isinstance(self.initial, bool):
                raise ValueError(
                    f"initial must be a boolean for type 'boolean', got {self.initial!r}"
                )
        elif self.type == "number":
            if isinstance(self.initial, bool) or not isinstance(self.initial, (int, float)):
                raise ValueError(
                    f"initial must be a number for type 'number', got {self.initial!r}"
                )
        elif self.type == "string":
            if not isinstance(self.initial, str):
                raise ValueError(
                    f"initial must be a string for type 'string', got {self.initial!r}"
                )
        return self


class AttitudeLimits(BaseModel):
    min: int = 0
    max: int = 0
    step_per_turn: int = 1


class WillRevealEntry(BaseModel):
    description: str
    conditions: List[str] = Field(default_factory=list)
    set_flag: Optional[Dict[str, bool]] = None
    set_entity_state: Optional[Dict[str, Dict[str, Any]]] = None


class DialogueGuidelines(BaseModel):
    guidelines: str
    attitude_limits: AttitudeLimits = Field(default_factory=AttitudeLimits)
    will_reveal: Dict[str, WillRevealEntry] = Field(default_factory=dict)
    dialogue_paths: Dict[str, Resolvable] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_dialogue_path_ids(self) -> "DialogueGuidelines":
        for path_id, resolvable in self.dialogue_paths.items():
            resolvable.id = path_id
        return self


class EncounterRule(Checkable):
    """An ordered encounter resolution node.

    When condition matches:
    - If ``check`` is set, resolve it (roll or stat check) and apply the
      chosen branch's Result (success/failure).
    - Otherwise apply ``result`` directly.
    Either branch Result or the rule's ``result`` may carry ``start_combat``
    or ``game_over`` to dispatch combat / game-over to the engine.
    """
    condition: Optional[ConditionExpression] = None
    result: Optional[Result] = None
    # Inherited from Checkable:
    #   skip_check_if, check (CheckType), success (Result), failure (Result)

    @model_validator(mode="after")
    def check_xor_result(self) -> "EncounterRule":
        has_check = self.check is not None
        has_result = self.result is not None
        if has_check == has_result:
            raise ValueError(
                "EncounterRule must have exactly one of 'check' or 'result'")
        return self





class AbilityAttack(BaseModel):
    """Attack-roll ability effect (e.g. Fire Bolt).

    Player casters roll with the named ability score's modifier (plus
    proficiency bonus when ``proficient``); NPC casters use their combat
    block's ``atk`` bonus instead (NPCs have no ability scores).
    """
    stat: str
    proficient: bool = True
    damage: str
    damage_type: str = ""


class AbilitySave(BaseModel):
    """Save-based ability effect (e.g. Poison Spray, a breath weapon).

    The target saves: the player rolls with stat modifier plus save
    proficiency as usual; NPC targets roll ``d20 + save_bonus`` from
    their combat block.
    """
    stat: str
    dc: int
    damage: str = ""                 # dice expr; "" = no damage
    damage_type: str = ""
    half_on_success: bool = True     # successful save halves damage
    apply_status_effect_on_failure: Optional[ApplyStatusEffect] = None


class Ability(BaseModel):
    """A named combat ability (spell, class feature, monster power).

    Exactly one effect: ``attack`` (attack roll), ``save`` (target saves),
    or ``heal`` (dice expression).  ``uses_per_combat`` of -1 means
    unlimited use (cantrip-style).
    """
    name: str
    description: str = ""
    target: Literal["self", "ally", "enemy"]
    uses_per_combat: int = -1
    attack: Optional[AbilityAttack] = None
    save: Optional[AbilitySave] = None
    heal: str = ""

    @model_validator(mode="after")
    def _check_shape(self) -> "Ability":
        kinds = sum([
            self.attack is not None,
            self.save is not None,
            bool(self.heal),
        ])
        if kinds != 1:
            raise ValueError(
                "Ability must have exactly one effect: attack, save, or heal"
            )
        if self.heal and self.target == "enemy":
            raise ValueError("heal abilities must target self or ally")
        return self

    def effect_summary(self) -> str:
        """Compact plain-English summary for briefings."""
        if self.attack is not None:
            dtype = f" {self.attack.damage_type}" if self.attack.damage_type else ""
            return f"attack ({self.attack.stat}) for {self.attack.damage}{dtype} damage"
        if self.save is not None:
            half = ", half on success" if self.save.half_on_success else ""
            dmg = f"{self.save.damage} damage" if self.save.damage else "no damage"
            return f"{self.save.stat} save DC {self.save.dc}: {dmg}{half}"
        return f"heals {self.heal}"


class FollowerConfig(BaseModel):
    blacklist: List[str] = Field(default_factory=list)


class Entity(BaseModel):
    type: Literal["player", "feature", "npc", "item"]
    name: Optional[str] = None
    description: str
    soft_item_guidance: Optional[str] = None
    contains: List[Union[str, Dict[str, int]]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    take_check: Optional[GatedCheck] = None
    interactions: List[Interaction] = Field(default_factory=list)
    on_examine: List[OnExamineEvent] = Field(default_factory=list)
    dialogue: Optional[DialogueGuidelines] = None
    aggro: Optional[List[EncounterRule]] = None
    state_fields: Dict[str, StateFieldDecl] = Field(default_factory=dict)
    follower: Optional[FollowerConfig] = None
    combat: Optional[CombatBlock] = None
    combat_group: Optional[str] = None
    equip_block: Optional[EquipBlock] = None
    consumable: Optional[ConsumableBlock] = None
    max_stack: Optional[int] = None
    reactions: List[Reaction] = Field(default_factory=list)
    _contains_map: Dict[str, int] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _build_contains_map(self) -> "Entity":
        self._contains_map = _normalize_contains(self.contains)
        return self

    @property
    def contains_map(self) -> Dict[str, int]:
        """Normalised {entity_id: count} view of ``contains``.

        Runtime code must use this property or the runtime maps in
        ``HardGameState``; never iterate the raw ``contains`` list directly.
        """
        return dict(self._contains_map)

    @model_validator(mode="after")
    def check_type_specific_fields(self) -> Entity:
        if self.type != "npc" and self.dialogue is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'dialogue'. "
                f"Only 'npc' entities may carry dialogue.")
        if self.type != "npc" and self.aggro is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'aggro'. "
                f"Only 'npc' entities may carry aggro.")
        if self.type != "npc" and self.combat is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'combat'. "
                f"Only 'npc' entities may carry combat.")
        if self.type != "npc" and self.combat_group is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'combat_group'. "
                f"Only 'npc' entities may carry combat_group.")
        if self.type != "item" and self.equip_block is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'equip_block'. "
                f"Only 'item' entities may carry equip_block.")
        if self.type != "item" and self.consumable is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'consumable'. "
                f"Only 'item' entities may carry consumable.")
        if self.type != "item" and self.max_stack is not None:
            raise ValueError(
                f"Entity type '{self.type}' must not have 'max_stack'. "
                f"Only 'item' entities may carry max_stack.")
        if self.type == "item" and self.max_stack is not None and self.max_stack < 1:
            raise ValueError(
                "Item 'max_stack' must be >= 1 if set.")
        if self.type == "item" and not self.name:
            raise ValueError(
                "Item entities must have a non-empty 'name' "
                "(used for inventory display and LLM briefings).")
        return self


class Mechanic(BaseModel):
    """A named bundle of game logic not tied to a specific room or entity.

    A Mechanic is one of exactly two kinds, distinguished by which field is
    populated:

    - Encounter (``rules``): an event-driven encounter fired by a
      ``trigger_encounter`` effect (or NPC aggro).  ``condition`` optionally
      gates whether the encounter may fire.
    - Reaction-Only (``reactions``): a bundle of event-driven reactions with
      no encounter rules.

    Game-over predicates are no longer a Mechanic kind: event-local outcomes
    use inline ``Result.game_over`` and cross-cutting ones use the top-level
    ``ModuleCorpus.game_over_conditions`` list.
    """
    condition: Optional[ConditionExpression] = None
    rules: Optional[List[EncounterRule]] = None
    reactions: List[Reaction] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_shape(self) -> Mechanic:
        is_encounter = self.rules is not None
        is_reaction_only = bool(self.reactions)
        if not is_encounter and not is_reaction_only:
            raise ValueError(
                "Mechanic must have at least one of: 'rules' or 'reactions'")
        return self


class StatDefinition(BaseModel):
    name: str


class CombatAIBlock(BaseModel):
    """Rule-of-thumb combat AI configuration for an NPC.

    All NPC combat decisions are made deterministically by the engine —
    no LLM is involved.  When ``ai`` is absent, defaults apply: enemies
    retaliate against their last attacker (falling back to the player),
    allies attack the player's target, and nobody flees.
    """
    targeting: Literal["last_attacker", "player", "lowest_hp", "random"] = (
        "last_attacker"
    )
    flee_below_hp_pct: Optional[int] = Field(default=None, ge=1, le=99)
    passive: bool = False
    # Per-ability usage rules, keyed by ability id (see CombatBlock.abilities).
    ability_rules: dict[str, "AbilityAIRule"] = Field(default_factory=dict)


class AbilityAIRule(BaseModel):
    """Usage constraints for one NPC ability (evaluated each turn).

    ``cooldown_rounds`` makes the ability unusable for that many rounds
    after each use; ``use_below_own_hp_pct`` only allows it while the
    NPC is below the given HP percentage.
    """
    cooldown_rounds: int = Field(default=0, ge=0)
    use_below_own_hp_pct: Optional[int] = Field(default=None, ge=1, le=100)


def _validate_combat_safe_effects(
    effects: list[CheckResolution], path: str
) -> None:
    """Restrict on-hit CheckResolution results to combat-safe effects."""
    prohibited = {
        "add_item",
        "add_item_count",
        "remove_item",
        "remove_item_count",
        "set_entity_state",
        "set_room_state",
        "adjust_attitude",
        "set_player_location",
        "start_combat",
    }

    def _is_set(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (list, dict)):
            return len(value) > 0
        return True

    def _check_result(result: Result | None, path: str) -> None:
        if result is None:
            return
        for field in prohibited:
            if _is_set(getattr(result, field)):
                raise ValueError(
                    f"Prohibited field '{field}' in on-hit result at {path}"
                )
        if result.then_check is not None:
            _check_check_resolution(result.then_check, f"{path}.then_check")

    def _check_check_resolution(chk: CheckResolution, path: str) -> None:
        _check_result(chk.success, f"{path}.success")
        _check_result(chk.failure, f"{path}.failure")

    for i, effect in enumerate(effects):
        _check_check_resolution(effect, f"{path}[{i}]")


class NPCAttackDef(BaseModel):
    """A named attack option in an NPC's combat block (e.g. a wolf's bite).

    ``name`` is a verb phrase used in narration prefixes ("bites",
    "slashes with its claws"); it defaults to ``id``.
    """
    id: str
    name: Optional[str] = None
    atk: int
    dmg: str = "1d6"
    dmg_type: str = ""
    ranged: bool = False
    on_hit_effects: list[CheckResolution] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_on_hit_effects(self) -> "NPCAttackDef":
        _validate_combat_safe_effects(self.on_hit_effects, "on_hit_effects")
        return self


class CombatBlock(BaseModel):
    """NPC combat stat block (5e-flavoured but corpus-agnostic).

    All values are pre-computed by the adventure author.  NPCs without
    this block cannot participate in HP-based combat.

    Attack options come in two forms: a single implicit "basic attack"
    built from the block-level ``atk`` / ``dmg`` / ``on_hit_effects``
    (when ``attacks`` is absent), or an explicit ``attacks`` list with a
    ``multiattack`` sequence naming the attacks performed each turn.
    """
    hp: int = Field(gt=0)
    ac: int
    atk: Optional[int] = None
    dmg: str = "1d6"
    dmg_type: str = ""
    ranged: bool = False
    initiative_mod: int = 0
    flee_dc: int = 10
    resistances: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)
    attacks: list[NPCAttackDef] = Field(default_factory=list)
    multiattack: list[str] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    save_bonus: int = 0
    on_hit_effects: list[CheckResolution] = Field(default_factory=list)
    ai: Optional[CombatAIBlock] = None

    @model_validator(mode="after")
    def _validate_on_hit_effects(self) -> "CombatBlock":
        _validate_combat_safe_effects(self.on_hit_effects, "on_hit_effects")
        return self

    @model_validator(mode="after")
    def _validate_attacks(self) -> "CombatBlock":
        if self.attacks:
            if self.on_hit_effects:
                raise ValueError(
                    "CombatBlock: 'on_hit_effects' is forbidden when 'attacks' "
                    "is present; put on-hit effects on individual attacks"
                )
            ids = [a.id for a in self.attacks]
            if len(set(ids)) != len(ids):
                raise ValueError("CombatBlock: duplicate attack ids")
            for atk_id in self.multiattack:
                if atk_id not in ids:
                    raise ValueError(
                        f"CombatBlock.multiattack references unknown attack "
                        f"'{atk_id}'"
                    )
        else:
            if self.atk is None:
                raise ValueError(
                    "CombatBlock.atk is required when 'attacks' is absent"
                )
            if self.multiattack:
                raise ValueError("CombatBlock.multiattack requires 'attacks'")
        return self


class StatsBlock(BaseModel):
    definitions: Dict[str, StatDefinition]
    system: str = "5e"


class ModuleCorpus(BaseModel):
    adventure: Adventure
    rooms: Dict[str, Room]
    entities: Dict[str, Entity]
    mechanics: Dict[str, Mechanic] = Field(default_factory=dict)
    game_over_conditions: List[GameOverCondition] = Field(default_factory=list)
    flags_declared: Optional[List[FlagDecl]] = None
    stats: Optional[StatsBlock] = None
    abilities: Dict[str, Ability] = Field(default_factory=dict)
    status_effects: Dict[str, StatusEffectDef] = Field(default_factory=dict)

    def effective_status_effects(self) -> Dict[str, StatusEffectDef]:
        """Built-in default status effects overlaid by the corpus block.

        A corpus entry replaces the built-in default of the same ID
        wholesale (no field-level merge).
        """
        return {**DEFAULT_STATUS_EFFECTS, **self.status_effects}

    def effective_gear(self) -> Dict[str, "Entity"]:
        """The full gear catalog: SRD data-pack items overlaid by corpus
        item entities.

        A corpus item entity whose ID matches a pack entry replaces the
        pack entry wholesale (no field-level merge).  Corpus item
        entities with non-pack IDs are included as-is.
        """
        gear = dict(DEFAULT_GEAR)
        for eid, entity in self.entities.items():
            if entity.type == "item":
                gear[eid] = entity
        return gear

    @field_validator("flags_declared", mode="before")
    @classmethod
    def _validate_flags_declared(cls, v: Any) -> Optional[List[FlagDecl]]:
        if v is None:
            return None
        result: List[FlagDecl] = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                if len(item) != 1:
                    raise ValueError(
                        "Each flags_declared dict entry must have exactly one key"
                    )
                for key, value in item.items():
                    if not isinstance(key, str):
                        raise ValueError(
                            f"flags_declared dict key must be a string, got {key!r}"
                        )
                    if not isinstance(value, bool):
                        raise ValueError(
                            f"flags_declared value for '{key}' must be a boolean, "
                            f"got {value!r}"
                        )
                result.append(item)
            else:
                raise ValueError(
                    f"flags_declared entries must be strings or single-key dicts, "
                    f"got {item!r}"
                )
        return result

    @property
    def flags_initial(self) -> Dict[str, bool]:
        """Canonical {flag_id: initial_value} view of flags_declared."""
        if self.flags_declared is None:
            return {}
        result: Dict[str, bool] = {}
        for item in self.flags_declared:
            if isinstance(item, str):
                result[item] = False
            else:
                result.update(item)
        return result


# Built-in default status effects, overlaid wholesale by corpus entries of the
# same ID (see ModuleCorpus.effective_status_effects).  Loaded from the
# engine-bundled SRD data pack (mgmai/data/srd_5e/conditions.json, keyed by
# system ID) rather than hardcoded, so the pack is read and validated with the
# same models as corpus files.  Defined at the end of the module because
# ``StatusEffectDef.tick_effect`` references ``Result``, whose own forward
# references only resolve once the module is complete.
StatusEffectDef.model_rebuild()
DEFAULT_STATUS_EFFECTS: Dict[str, StatusEffectDef] = {
    effect_id: StatusEffectDef.model_validate(entry)
    for effect_id, entry in load_pack("5e", "conditions").items()
}

# Built-in SRD gear (weapons, armor, standard consumables) as item-entity
# templates, loaded from the engine-bundled data pack
# (mgmai/data/srd_5e/gear.json).  Templates are minted into
# ``corpus.entities`` at load time (StateManager._materialize_pack_gear);
# a corpus entity with the same ID replaces the pack template wholesale
# (see ModuleCorpus.effective_gear).
DEFAULT_GEAR: Dict[str, Entity] = {
    gear_id: Entity.model_validate(entry)
    for gear_id, entry in load_pack("5e", "gear").items()
}
