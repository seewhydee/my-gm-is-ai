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
from typing import Optional
from pydantic import BaseModel, Field


class CombatLogEntry(BaseModel):
    """A single combat event — one actor's action within a round.

    Not every field is populated for every entry.  An attack entry carries
    the roll / total / AC / hit / damage chain; a death entry only carries
    actor + action + round.  On-hit effect results (saving throw, secondary
    damage) are carried in the ``on_hit_effects`` list.
    """
    round: int
    actor: str               # "player" or npc entity id
    action: str              # "attack", "flee", "death", etc.
    target: Optional[str] = None
    attack_roll: Optional[int] = None
    attack_total: Optional[int] = None
    ac: Optional[int] = None
    hit: Optional[bool] = None
    critical: Optional[bool] = None
    damage_roll: Optional[str] = None
    damage: Optional[int] = None
    remaining_hp: Optional[int] = None
    # On-hit saving throws and secondary damage
    on_hit_effects: list[dict] = Field(default_factory=list)
    # Damage typing and mitigation (resistance / vulnerability / immunity)
    damage_type: Optional[str] = None
    mitigation: Optional[str] = None   # "resisted" | "vulnerable" | "immune"
    # Named attack used (NPC attack definitions / multiattack)
    attack_id: Optional[str] = None
    attack_name: Optional[str] = None


class CombatState(BaseModel):
    """Mutable combat phase state stored on HardGameState.

    ``active`` is a convenience flag; combat is considered live when
    ``HardGameState.combat is not None``.  ``current_index`` points into
    ``initiative_order`` at the next actor whose turn the engine should
    process.  The player is only prompted when that actor is ``"player"``.
    """
    active: bool = False
    combatants: list[str] = Field(default_factory=list)        # entity IDs + "player"
    allies: list[str] = Field(default_factory=list)            # combatant IDs fighting on the player's side
    initiative_order: list[str] = Field(default_factory=list)  # sorted turn order
    current_index: int = 0                                     # index into initiative_order
    round_number: int = 0
    log: list[CombatLogEntry] = Field(default_factory=list)
    # Combat-AI bookkeeping: who last landed a hit on each combatant
    # (target id -> attacker id), and the player's most recent target.
    last_attacker: dict[str, str] = Field(default_factory=dict)
    player_last_target: Optional[str] = None
    # Ability bookkeeping: combatant id -> {ability id -> times used this
    # combat}, and NPC id -> {ability id -> rounds until usable again}.
    ability_uses: dict[str, dict[str, int]] = Field(default_factory=dict)
    npc_cooldowns: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Positioning: sorted symmetric "within melee reach" pairs of combatant
    # ids ([["goblin", "player"]]).  Pairs involving dead/fled combatants
    # are pruned immediately; the whole state is dropped at combat end.
    engagement: list[list[str]] = Field(default_factory=list)
    # Impede bookkeeping: enemy ids with a pending impede flag (consumed at
    # their next turn), and ids already impeded this combat (each enemy can
    # be impeded at most once per combat).
    impeded: list[str] = Field(default_factory=list)
    impede_used: list[str] = Field(default_factory=list)
