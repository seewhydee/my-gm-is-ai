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

from mgmai.models.actions import CombatAction, MoveAction, WaitAction
from mgmai.models.briefing import GMBriefing

#: Maximum positioning changes (engage + disengage + impede entries) the
#: engine applies from a single action's assertion block.  Mirrors
#: ``_MAX_POSITIONING_CHANGES`` in ``mgmai.engine.combat``.
_MAX_POSITIONING_CHANGES = 4


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
        f"{', '.join(exit_ids) if exit_ids else 'none'}. Repositioning "
        f"within the fight is expressed with the optional 'positioning' "
        f"field on a 'combat' or 'wait' action, or with combat_action "
        f"\"maneuver\" (Disengage)."
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


def validate_positioning_assertion(action, briefing: GMBriefing) -> Optional[str]:
    """Soft-fail check for the optional ``positioning`` embellishment.

    Mirrors the engine's apply-time validation
    (``mgmai.engine.combat._apply_positioning_assertions``) so malformed
    assertions are caught before resolution.  Unlike
    :func:`validate_ruling_action`, an error here must never trigger the
    corrective retry or raise ``LLMOutputError``: the caller strips the
    ``positioning`` block and lets the core action proceed.

    Returns ``None`` when the assertion is consistent with the briefing
    (or when the briefing lacks the data needed to judge it); otherwise a
    short error string addressed to the model.
    """
    positioning = getattr(action, "positioning", None)
    if positioning is None:
        return None
    combat = briefing.combat_state
    if combat is None:
        return (
            "Invalid 'positioning' field: positioning assertions are only "
            "valid during combat (combat_state is not present in the "
            "briefing). Omit 'positioning' outside combat."
        )
    if not isinstance(action, (CombatAction, WaitAction)):
        return (
            f"Invalid 'positioning' field on action_type "
            f"'{action.action_type}': positioning assertions are only "
            f"valid on 'combat' and 'wait' actions."
        )

    combatants: dict[str, dict] = {
        str(c.get("id")): c
        for c in combat.combatants
        if c.get("id") is not None
    }
    valid_ids = ", ".join(sorted(combatants)) or "none"
    # The briefing exposes the engagement map via each combatant's
    # engaged_with list; when it is absent (older/hand-built briefings),
    # skip the currently-engaged check rather than guessing.
    engagement_known = all("engaged_with" in c for c in combatants.values())

    def _pair_error(pair, kind: str) -> Optional[str]:
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]:
            return (
                f"Invalid positioning.{kind} entry {pair!r}: each entry "
                f"must be a pair of two distinct combatant IDs."
            )
        for cid in pair:
            if not isinstance(cid, str) or cid not in combatants:
                return (
                    f"Invalid positioning.{kind} entry {pair!r}: '{cid}' "
                    f"is not a living combatant. Valid combatant IDs: "
                    f"{valid_ids}."
                )
        return None

    engage_pairs = set()
    for pair in positioning.engage:
        error = _pair_error(pair, "engage")
        if error is not None:
            return error
        engage_pairs.add(frozenset(pair))

    for pair in positioning.disengage:
        error = _pair_error(pair, "disengage")
        if error is not None:
            return error
        if frozenset(pair) in engage_pairs:
            return (
                f"Invalid positioning: the pair {sorted(pair)} appears in "
                f"both 'engage' and 'disengage'. A pair may change in only "
                f"one direction per turn."
            )
        if engagement_known:
            mover, stationary = pair
            partners = combatants[mover].get("engaged_with") or []
            if stationary not in partners:
                return (
                    f"Invalid positioning.disengage entry {pair!r}: the "
                    f"pair is not currently engaged (see each combatant's "
                    f"engaged_with list in combat_state.combatants)."
                )

    seen_impede: set[str] = set()
    for cid in positioning.impede:
        entry = combatants.get(cid) if isinstance(cid, str) else None
        if entry is None or entry.get("side") != "enemy":
            return (
                f"Invalid positioning.impede entry {cid!r}: 'impede' may "
                f"only name living enemy combatants (side \"enemy\" from "
                f"combat_state.combatants) — not the player or allies. "
                f"Valid combatant IDs: {valid_ids}."
            )
        if entry.get("impeded") or entry.get("impede_used") or cid in seen_impede:
            return (
                f"Invalid positioning.impede entry {cid!r}: '{cid}' was "
                f"already impeded this combat (each enemy can be impeded "
                f"at most once per combat)."
            )
        seen_impede.add(cid)

    changes = (
        len(positioning.engage)
        + len(positioning.disengage)
        + len(positioning.impede)
    )
    if changes > _MAX_POSITIONING_CHANGES:
        return (
            f"Too many positioning changes ({changes}): at most "
            f"{_MAX_POSITIONING_CHANGES} entries total across 'engage', "
            f"'disengage', and 'impede' per turn."
        )
    return None
