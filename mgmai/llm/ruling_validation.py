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

"""Semantic validation of ruling (LLM Call 1) outputs against the briefing.

``parse_player_action`` guarantees syntactic/schema validity only.  A ruling
can be well-formed JSON and still be nonsense — e.g. ``use_item`` with the
beneficiary in ``target`` instead of the item ID.  This module checks the
parsed PlayerAction against the GMBriefing data the model was shown and
returns a short, model-addressed error string (fed back verbatim in the
corrective retry) when the briefing clearly proves the ruling invalid.

The checks are deliberately conservative: when in doubt, return ``None``.
"""

from __future__ import annotations

from typing import Optional

from mgmai.models.actions import CombatAction, MoveAction
from mgmai.models.briefing import GMBriefing


def _enemy_ids(briefing: GMBriefing) -> list[str]:
    return [
        str(c.get("id"))
        for c in briefing.combat_state.combatants
        if c.get("side") == "enemy" and c.get("id") is not None
    ]


def _party_ids(briefing: GMBriefing) -> list[str]:
    return [
        str(c.get("id"))
        for c in briefing.combat_state.combatants
        if c.get("side") == "party" and c.get("id") is not None
    ]


def _validate_use_item(action: CombatAction, briefing: GMBriefing) -> Optional[str]:
    items = {
        str(i.get("id")): str(i.get("name") or i.get("id"))
        for i in briefing.combat_state.usable_items
        if i.get("id") is not None
    }
    if action.target in items:
        return None
    if items:
        listing = ", ".join(f"{iid} ({name})" for iid, name in items.items())
    else:
        listing = "none — the player has no usable items"
    return (
        f"Invalid use_item target '{action.target}'. For combat_action "
        f"\"use_item\", 'target' must be the ID of an item from "
        f"combat_state.usable_items. Valid item IDs: {listing}. The item "
        f"goes in 'target'; the user/drinker of the item is always the "
        f"player, so \"player\" (or any other beneficiary) is never a valid "
        f"use_item target."
    )


def _validate_attack(action: CombatAction, briefing: GMBriefing) -> Optional[str]:
    enemies = _enemy_ids(briefing)
    if action.target in enemies:
        return None
    return (
        f"Invalid attack target '{action.target}'. For combat_action "
        f"\"attack\", 'target' must be the ID of a combatant with "
        f"side \"enemy\" from combat_state.combatants. Valid enemy IDs: "
        f"{', '.join(enemies) if enemies else 'none'}."
    )


def _validate_use_ability(
    action: CombatAction, briefing: GMBriefing
) -> Optional[str]:
    abilities = {
        str(a.get("id")): a
        for a in briefing.combat_state.abilities
        if a.get("id") is not None
    }
    if action.ability_id not in abilities:
        if abilities:
            listing = ", ".join(abilities)
        else:
            listing = "none — the player has no abilities, so use_ability is not possible"
        return (
            f"Invalid ability_id '{action.ability_id}'. For combat_action "
            f"\"use_ability\", 'ability_id' must be an ID from "
            f"combat_state.abilities. Valid ability IDs: {listing}."
        )
    kind = abilities[action.ability_id].get("target")
    if kind == "self":
        if action.target != "player":
            return (
                f"Invalid target '{action.target}' for ability "
                f"'{action.ability_id}': that ability's target kind is "
                f"\"self\", so 'target' must be \"player\"."
            )
    elif kind == "ally":
        party = _party_ids(briefing)
        if action.target not in party:
            return (
                f"Invalid target '{action.target}' for ability "
                f"'{action.ability_id}': that ability's target kind is "
                f"\"ally\", so 'target' must be a party-side combatant ID. "
                f"Valid party IDs: {', '.join(party) if party else 'none'}."
            )
    elif kind == "enemy":
        enemies = _enemy_ids(briefing)
        if action.target not in enemies:
            return (
                f"Invalid target '{action.target}' for ability "
                f"'{action.ability_id}': that ability's target kind is "
                f"\"enemy\", so 'target' must be an enemy-side combatant "
                f"ID. Valid enemy IDs: {', '.join(enemies) if enemies else 'none'}."
            )
    return None


def _validate_move(action: MoveAction, briefing: GMBriefing) -> Optional[str]:
    exit_ids = [e.id for e in briefing.current_room.exits_available]
    if action.target in exit_ids:
        return None
    return (
        f"Invalid move target '{action.target}'. During combat, a 'move' "
        f"action means FLEEING the fight through an exit, so 'target' must "
        f"be an exit ID from current_room.exits_available. Valid exit IDs: "
        f"{', '.join(exit_ids) if exit_ids else 'none'}. Repositioning, "
        f"flanking, or maneuvering within the fight must instead be ruled "
        f"as a 'combat' action with combat_action \"attack\" and an "
        f"appropriate 'detail'."
    )


def validate_ruling_action(action, briefing: GMBriefing) -> Optional[str]:
    """Check a parsed PlayerAction for semantic consistency with the briefing.

    Returns ``None`` when the action is consistent (or when the briefing
    lacks the data needed to judge it).  Otherwise returns a short error
    string addressed to the model, suitable for the corrective retry prompt.
    """
    if briefing.combat_state is None:
        return None
    if isinstance(action, CombatAction):
        if action.combat_action == "use_item":
            return _validate_use_item(action, briefing)
        if action.combat_action == "attack":
            return _validate_attack(action, briefing)
        if action.combat_action == "use_ability":
            return _validate_use_ability(action, briefing)
    elif isinstance(action, MoveAction):
        return _validate_move(action, briefing)
    return None
