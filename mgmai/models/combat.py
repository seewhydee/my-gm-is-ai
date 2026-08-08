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

from pydantic import BaseModel, Field


class TurnBudget(BaseModel):
    """The player's per-turn action-economy budget (D&D 5e SRD 5.2.1).

    Reset when the player's turn cycles — at the start of the player's
    turn (``_begin_player_turn``) and again at turn end
    (``_end_player_turn``) so pre-resolution readers never see a stale
    spent budget.  ``reaction_used`` mirrors the player's reaction onto
    the budget; the briefing instead derives reaction availability from
    ``CombatState.reactions_spent``, which is cleared on the same cycle.
    """
    action_used: bool = False
    bonus_action_used: bool = False
    free_interaction_used: bool = False
    reaction_used: bool = False
    # One slot spell per turn (SRD 5.2.1): set when a leveled spell is cast
    # this turn; a leveled bonus-action spell and a leveled main-action
    # spell can't coexist.
    slot_cast_this_turn: bool = False


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
    target: str | None = None
    attack_roll: int | None = None
    attack_total: int | None = None
    ac: int | None = None
    hit: bool | None = None
    critical: bool | None = None
    damage_roll: str | None = None
    damage: int | None = None
    remaining_hp: int | None = None
    # On-hit saving throws and secondary damage
    on_hit_effects: list[dict] = Field(default_factory=list)
    # Damage typing and mitigation (resistance / vulnerability / immunity)
    damage_type: str | None = None
    mitigation: str | None = None   # "resisted" | "vulnerable" | "immune"
    # Named attack used (NPC attack definitions / multiattack)
    attack_id: str | None = None
    attack_name: str | None = None
    # Spell identity (set when the resolved ability is a spell)
    spell_id: str | None = None
    spell_level: int | None = None
    # Set on player "interact" entries when the target is a carried item
    # (potion, antidote) rather than a room feature — lets summaries
    # distinguish item use from feature manipulation.
    target_is_item: bool = False


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
    # Rolled initiative total per combatant, recorded at combat entry so
    # reinforcements merged mid-combat can be spliced into the right
    # initiative slot (empty for hand-built states and older saves).
    initiative_totals: dict[str, int] = Field(default_factory=dict)
    current_index: int = 0                                     # index into initiative_order
    round_number: int = 0
    log: list[CombatLogEntry] = Field(default_factory=list)
    # Combat-AI bookkeeping: who last landed a hit on each combatant
    # (target id -> attacker id), and the player's most recent target.
    last_attacker: dict[str, str] = Field(default_factory=dict)
    player_last_target: str | None = None
    # Ability bookkeeping: combatant id -> {ability id -> times used this
    # combat}, and NPC id -> {ability id -> rounds until usable again}.
    ability_uses: dict[str, dict[str, int]] = Field(default_factory=dict)
    npc_cooldowns: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Concentration: caster id -> spell id (one concentration spell per
    # caster).  Needs no explicit clearing — the map dies with
    # ``hard.combat = None`` at combat end.
    concentration: dict[str, str] = Field(default_factory=dict)
    # Positioning: sorted symmetric "within melee reach" pairs of combatant
    # ids ([["goblin", "player"]]).  Pairs involving dead/fled combatants
    # are pruned immediately; the whole state is dropped at combat end.
    engagement: list[list[str]] = Field(default_factory=list)
    # Impede bookkeeping: enemy ids with a pending impede flag (consumed at
    # their next turn), and ids already impeded this combat (each enemy can
    # be impeded at most once per combat).
    impeded: list[str] = Field(default_factory=list)
    impede_used: list[str] = Field(default_factory=list)
    # The player's per-turn action-economy budget (action / bonus action /
    # free object interaction / reaction / slot-cast flag).  Reset at the
    # start and at the end of each player turn.  See TurnBudget.
    player_budget: TurnBudget = Field(default_factory=TurnBudget)
    # Combatant ids that have spent their reaction since their own last
    # turn start (the player and every NPC).  An id is removed at the top
    # of that combatant's own turn.  Consumed by opportunity attacks.
    reactions_spent: set[str] = Field(default_factory=set)
    # Active grapples: grappled combatant id -> grappler id.  The grappled
    # party is stuck (can't leave reach) and must use the escape maneuver
    # (or an incapacitated grappler) to break free.
    grapples: dict[str, str] = Field(default_factory=dict)
    # Help-flagged enemy combatant ids: the next party-side attack against
    # a flagged enemy has advantage, then the flag is consumed (the
    # Help action, §5).
    help_flagged: list[str] = Field(default_factory=list)
    # The weapon used for the player's Attack *action* this turn (None when
    # the action wasn't an attack).  A second equipped Light weapon lets a
    # bonus-action off-hand attack with a different weapon (Light property).
    action_weapon_id: str | None = None
    # Set when a segment of the player's turn resolves but the turn stays
    # open (budget remains): the follow-up resolve_combat_turn call for the
    # player's next segment skips start-of-turn processing (status effects
    # tick once per round); cleared when the turn ends in _end_player_turn.
    turn_continuation: bool = False
