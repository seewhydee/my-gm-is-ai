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
can be well-formed JSON and still be nonsense — e.g. ``attack`` with a
``target`` that is not an enemy combatant.  This module checks the
parsed PlayerAction against the GMBriefing data the model was shown and
returns a short, model-addressed error string (fed back verbatim in the
corrective retry) when the briefing clearly proves the ruling invalid.

The checks are deliberately conservative: when in doubt, return ``None``.
"""

from __future__ import annotations

from mgmai.models.actions import (
    CombatAction,
    GearAction,
    InteractAction,
    MoveAction,
    RestAction,
    TalkAction,
    UseAbilityAction,
    WaitAction,
)
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


def _validate_attack(action: CombatAction, briefing: GMBriefing) -> str | None:
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
    action: UseAbilityAction, briefing: GMBriefing
) -> str | None:
    """Validate ``use_ability`` in or out of combat.

    In combat, validates against ``combat_state.abilities`` and
    combatant lists.  Out of combat, validates against
    ``player_state.abilities`` and room-visible entities; self/ally
    heal/on-cast effects resolve directly, enemy-targeted abilities
    are allowed (they start combat per the engine), and attack/save/
    auto_damage effects still require combat.
    """
    in_combat = briefing.combat_state is not None
    if in_combat:
        abilities = {
            str(a.get("id")): a
            for a in briefing.combat_state.abilities
            if a.get("id") is not None
        }
    else:
        abilities = {
            str(a.get("id")): a
            for a in briefing.player_state.abilities
            if a.get("id") is not None
        }
    if action.ability_id not in abilities:
        if abilities:
            listing = ", ".join(abilities)
        else:
            listing = "none — the player has no abilities, so use_ability is not possible"
        source = "combat_state.abilities" if in_combat else "player_state.abilities"
        return (
            f"Invalid ability_id '{action.ability_id}'. For action_type "
            f"\"use_ability\", 'ability_id' must be an ID from "
            f"{source}. Valid ability IDs: {listing}."
        )
    entry = abilities[action.ability_id]
    kind = entry.get("target")
    if kind == "self":
        if action.target != "player":
            return (
                f"Invalid target '{action.target}' for ability "
                f"'{action.ability_id}': that ability's target kind is "
                f"\"self\", so 'target' must be \"player\"."
            )
    elif kind == "ally":
        if in_combat:
            party = _party_ids(briefing)
            if action.target not in party:
                return (
                    f"Invalid target '{action.target}' for ability "
                    f"'{action.ability_id}': that ability's target kind is "
                    f"\"ally\", so 'target' must be a party-side combatant ID. "
                    f"Valid party IDs: {', '.join(party) if party else 'none'}."
                )
        elif action.target != "player":
            allies = {
                str(e.id)
                for e in briefing.current_room.entities_visible
                if e.type == "npc" and e.state.get("alive") is not False
            }
            if action.target not in allies:
                return (
                    f"Invalid target '{action.target}' for ability "
                    f"'{action.ability_id}': that ability's target kind is "
                    f"\"ally\", so 'target' must be \"player\" or a living "
                    f"allied NPC in the current room. Valid NPC IDs: "
                    f"{', '.join(sorted(allies)) if allies else 'none'}."
                )
    elif kind == "enemy":
        if in_combat:
            enemies = _enemy_ids(briefing)
            if action.target not in enemies:
                return (
                    f"Invalid target '{action.target}' for ability "
                    f"'{action.ability_id}': that ability's target kind is "
                    f"\"enemy\", so 'target' must be an enemy-side combatant "
                    f"ID. Valid enemy IDs: {', '.join(enemies) if enemies else 'none'}."
                )
        else:
            if not action.target:
                return (
                    f"Invalid target for ability '{action.ability_id}': "
                    f"that ability's target kind is \"enemy\", so 'target' "
                    f"must be the ID of a visible enemy entity."
                )
    # Out of combat, self/ally abilities are restricted to heal/on_cast
    # effects (attack/save/auto_damage and concentration need a live
    # CombatState).  Enemy-targeted abilities skip this check: they
    # start combat (mirroring interact/attack) and resolve on the
    # player's first combat turn, where the effect_kind is legal.
    if not in_combat and kind != "enemy":
        effect_kind = entry.get("effect_kind")
        if effect_kind not in ("heal", "on_cast"):
            return (
                f"Invalid ability_id '{action.ability_id}' outside combat: "
                f"'{action.ability_id}' has a {effect_kind} effect, which needs "
                f"a combatant to resolve against. Outside combat only healing "
                f"and on-cast (buff) abilities work; attack/save effects "
                f"require starting combat first."
            )
        if entry.get("concentration"):
            return (
                f"Invalid ability_id '{action.ability_id}' outside combat: "
                f"'{action.ability_id}' requires concentration, which is only "
                f"tracked in combat. Cast it once combat has started."
            )
    slot_level = entry.get("slot_level")
    if slot_level is not None and slot_level >= 1:
        pool = (
            briefing.combat_state.spell_slots if in_combat
            else briefing.player_state.spell_slots
        ) or {}
        if pool.get(slot_level, 0) <= 0:
            return (
                f"Invalid ability_id '{action.ability_id}' for action_type "
                f"\"use_ability\": '{action.ability_id}' is a level-{slot_level} "
                f"spell and the player has no level-{slot_level} spell slots "
                f"remaining (see {'combat_state' if in_combat else 'player_state'}"
                f".spell_slots). Choose a different ability or a cantrip "
                f"(spell_level 0 spells cost no slot)."
            )
    return None


def _validate_move(action: MoveAction, briefing: GMBriefing) -> str | None:
    exit_ids = [e.id for e in briefing.current_room.exits_available]
    if action.target in exit_ids:
        return None
    return (
        f"Invalid move target '{action.target}'. During combat, a 'move' "
        f"action means FLEEING the fight through an exit, so 'target' must "
        f"be an exit ID from current_room.exits_available. Valid exit IDs: "
        f"{', '.join(exit_ids) if exit_ids else 'none'}. Repositioning "
        f"within the fight is expressed with the optional 'positioning' "
        f"field on a 'combat', 'wait', or 'interact' action, or with "
        f"combat_action \"maneuver\" (Disengage)."
    )


def _validate_talk(action: TalkAction, briefing: GMBriefing) -> str | None:
    return (
        "Invalid action_type 'talk' during combat: conversations are "
        "impossible in the middle of a fight — the engine cannot hold a "
        "dialogue while combat is active. Rule the player's speech as a "
        "'wait' action instead, putting the speech itself in 'detail' "
        "(this passes the player's combat turn; NPC turns proceed). "
        "Never convert a talk attempt into an attack."
    )


def _validate_rest(action: RestAction, briefing: GMBriefing) -> str | None:
    return (
        "Invalid action_type 'rest' during combat: you cannot rest in the "
        "middle of a fight. Rule the player's attempt as a 'wait' action "
        "instead, putting the intent in 'detail' (this passes the player's "
        "combat turn). A short or long rest is only possible outside "
        "combat."
    )


def _validate_gear(action: GearAction, briefing: GMBriefing) -> str | None:
    """Mirror the engine's combat gear restriction (weapon swaps only).

    The briefing exposes ``equip_tags`` only for currently equipped
    items, so only unequip targets can be judged here; equip targets are
    left to the engine (when in doubt, return ``None``).
    """
    tags_by_id = {
        item.id: set(item.equip_tags)
        for item in briefing.player_state.equipped_items
    }
    for target in action.unequip_targets:
        tags = tags_by_id.get(target)
        if tags is not None and "weapon" not in tags:
            return (
                f"Invalid gear action during combat: '{target}' is not a "
                f"weapon (its equip_tags lack \"weapon\"). Only weapon "
                f"swaps are possible in combat — changing armor or other "
                f"gear mid-fight is not allowed. Restrict 'equip_targets' "
                f"and 'unequip_targets' to weapons, or rule the attempt "
                f"as 'wait'."
            )
    return None


def validate_ruling_action(action, briefing: GMBriefing) -> str | None:
    """Check a parsed PlayerAction for semantic consistency with the briefing.

    Returns ``None`` when the action is consistent (or when the briefing
    lacks the data needed to judge it).  Otherwise returns a short error
    string addressed to the model, suitable for the corrective retry prompt.
    """
    if briefing.combat_state is None:
        if isinstance(action, UseAbilityAction):
            return _validate_use_ability(action, briefing)
        return None
    if isinstance(action, CombatAction):
        if action.combat_action == "attack":
            return _validate_attack(action, briefing)
    elif isinstance(action, UseAbilityAction):
        return _validate_use_ability(action, briefing)
    elif isinstance(action, MoveAction):
        return _validate_move(action, briefing)
    elif isinstance(action, TalkAction):
        return _validate_talk(action, briefing)
    elif isinstance(action, RestAction):
        return _validate_rest(action, briefing)
    elif isinstance(action, GearAction):
        return _validate_gear(action, briefing)
    return None


def validate_positioning_assertion(action, briefing: GMBriefing) -> str | None:
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
    if not isinstance(action, (CombatAction, WaitAction, InteractAction)):
        return (
            f"Invalid 'positioning' field on action_type "
            f"'{action.action_type}': positioning assertions are only "
            f"valid on 'combat', 'wait', and 'interact' actions."
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

    def _pair_error(pair, kind: str) -> str | None:
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
