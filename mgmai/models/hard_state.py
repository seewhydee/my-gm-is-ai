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

from mgmai.models.combat import CombatState


class WeaponProfClause(BaseModel):
    """A property-filtered weapon proficiency (5e).

    Proficient with any weapon whose proficiency category is ``category``
    (``"simple"`` or ``"martial"``) and whose ``properties`` include at
    least one of the listed ``properties`` (OR semantics).  This models
    class proficiencies such as the Rogue's "Martial weapons that have
    the Finesse or Light property" or the Monk's "Martial weapons that
    have the Light property".
    """
    category: Literal["simple", "martial"]
    properties: list[str] = Field(min_length=1)


class HitDice(BaseModel):
    """5e Hit Dice pool for the player.

    ``die`` is the hit-die type (e.g. ``"d6"``, ``"d8"``); ``current`` is
    the number of unspent dice; ``max`` is the total.  Short rests spend
    from ``current``; a long rest restores ``current`` to ``max`` (SRD
    5.2.1: all spent Hit Dice are regained).
    """

    die: str
    current: int
    max: int


class PlayerState(BaseModel):
    location: str
    inventory: dict[str, int] = Field(default_factory=dict)
    equipped: list[str] = Field(default_factory=list)
    stats: dict[str, int] | None = None
    level: int = 1
    current_hp: int | None = None
    max_hp: int | None = None
    ac: int | None = None
    proficiency_bonus: int | None = None
    save_proficiencies: list[str] = Field(default_factory=list)
    # 5e skill names the player is proficient in (e.g. "acrobatics");
    # matched case-insensitively by the resolution system.
    skill_proficiencies: list[str] = Field(default_factory=list)
    # 5e weapon proficiencies.  Each entry is either:
    #   - a weapon-category name ("simple", "martial"), or
    #   - an individual weapon entity ID, or
    #   - a WeaponProfClause ({"category", "properties"}) granting
    #     proficiency with weapons of that category that have at least
    #     one of the listed properties (OR).
    # A weapon the player is not proficient with can still be used, but
    # grants no proficiency bonus to the attack roll.  Unarmed strikes
    # are always proficient.
    weapon_proficiencies: list[str | WeaponProfClause] = Field(
        default_factory=list
    )
    # Active status effects (status effect id -> rounds remaining); combat-scoped.
    status_effects: dict[str, int] = Field(default_factory=dict)
    # IDs of abilities the player currently has available to cast/use
    # (the prepared subset for prepared casters; the whole list
    # otherwise).  CombatAction.ability_id, briefings, and validation
    # all read this as the castable set.
    abilities: list[str] = Field(default_factory=list)
    # Every ability the player knows / has in their spellbook.  For
    # prepared casters (cleric, wizard, ...), ``abilities`` is the
    # prepared subset and ``spellbook`` is the known superset; re-
    # preparation after a long rest swaps ``abilities``.  Empty for
    # spontaneous casters and non-casters, in which case ``abilities``
    # is the whole list and the prepare-spells menu is hidden.
    # Invariant when non-empty: ``abilities`` ⊆ ``spellbook``.
    spellbook: list[str] = Field(default_factory=list)
    # 5e spellcasting: the player's casting stat ("INT"/"WIS"/"CHA"); one
    # casting ability for all spells (per-spell overrides are a future
    # multiclass concern).
    spellcasting_ability: str | None = None
    # Spell level (1-9) -> slots remaining; empty = no leveled spells
    # (cantrips only).  Set directly by char-sheets and tests; recharged
    # only when rests land.  JSON object keys are strings, so saves show
    # {"1": 2}; pydantic coerces the keys back to int on model_validate.
    spell_slots: dict[int, int] = Field(default_factory=dict)
    # Spell level (1-9) -> maximum slots (the recharge ceiling).  Set by
    # char-sheets alongside ``spell_slots``; a long rest refills
    # ``spell_slots`` to this.  Absent (empty) when the character has no
    # leveled slots or no recharge source; same string-key JSON coercion
    # as ``spell_slots``.
    max_spell_slots: dict[int, int] = Field(default_factory=dict)
    # 5e Hit Dice pool.  Absent for non-5e characters or NPCs without
    # hit-dice tracking; a long rest restores ``current`` to ``max``
    # (SRD 5.2.1).
    hit_dice: HitDice | None = None

class GameOverState(BaseModel):
    type: str  # "win" or "lose"
    trigger: str

class HardGameState(BaseModel):
    player: PlayerState
    flags: dict[str, bool] = Field(default_factory=dict)
    room_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    entity_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Runtime containment maps, initialised from the corpus at load time.
    # {room_id: {entity_id: count}}
    room_contains: dict[str, dict[str, int]] = Field(default_factory=dict)
    # {container_entity_id: {entity_id: count}}
    entity_contains: dict[str, dict[str, int]] = Field(default_factory=dict)
    turn_count: int = 0
    game_over: GameOverState | None = None
    combat: CombatState | None = None

    @model_validator(mode="after")
    def check_turn_count_non_negative(self) -> HardGameState:
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")
        return self
