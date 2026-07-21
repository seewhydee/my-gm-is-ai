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
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator
from mgmai.models.combat import CombatState


class PlayerState(BaseModel):
    location: str
    inventory: Dict[str, int] = Field(default_factory=dict)
    equipped: list[str] = Field(default_factory=list)
    stats: Optional[Dict[str, int]] = None
    level: int = 1
    current_hp: Optional[int] = None
    max_hp: Optional[int] = None
    ac: Optional[int] = None
    proficiency_bonus: Optional[int] = None
    save_proficiencies: list[str] = Field(default_factory=list)
    # Active status effects (status effect id -> rounds remaining); combat-scoped.
    status_effects: Dict[str, int] = Field(default_factory=dict)
    # IDs of combat abilities the player knows (corpus.abilities keys).
    abilities: list[str] = Field(default_factory=list)

class GameOverState(BaseModel):
    type: str  # "win" or "lose"
    trigger: str

class HardGameState(BaseModel):
    player: PlayerState
    flags: Dict[str, bool] = Field(default_factory=dict)
    room_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    entity_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Runtime containment maps, initialised from the corpus at load time.
    # {room_id: {entity_id: count}}
    room_contains: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    # {container_entity_id: {entity_id: count}}
    entity_contains: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    turn_count: int = 0
    game_over: Optional[GameOverState] = None
    combat: Optional[CombatState] = None

    @model_validator(mode="after")
    def check_turn_count_non_negative(self) -> HardGameState:
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")
        return self
