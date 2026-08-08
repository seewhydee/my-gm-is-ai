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
    ExamineAction,
    GearAction,
    InteractAction,
    MoveAction,
    RestAction,
    TalkAction,
    TransferAction,
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
    # Out of combat, self/ally abilities are restricted to heal/on_cast/
    # cure_status effects (attack/save/auto_damage and concentration need
    # a live CombatState).  Enemy-targeted abilities skip this check: they
    # start combat (mirroring interact/attack) and resolve on the
    # player's first combat turn, where the effect_kind is legal.
    if not in_combat and kind != "enemy":
        effect_kind = entry.get("effect_kind")
        if effect_kind not in ("heal", "on_cast", "cure_status"):
            return (
                f"Invalid ability_id '{action.ability_id}' outside combat: "
                f"'{action.ability_id}' has a {effect_kind} effect, which needs "
                f"a combatant to resolve against. Outside combat only healing, "
                f"on-cast (buff), and cure-status abilities work; attack/save "
                f"effects require starting combat first."
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


def validate_dialogue_path(action: TalkAction, briefing: GMBriefing, corpus) -> str | None:
    """Reject ``dialogue_path`` IDs unknown to the target NPC.

    The resolver hard-fails the entire turn on an unknown dialogue path
    (silently freezing the conversation while narration continues), so
    an unknown ID earns a corrective retry here.  If the retry does not
    fix it, the caller strips the field and lets the conversation
    proceed freeform rather than failing the turn.
    """
    path_id = action.dialogue_path
    if not path_id or corpus is None:
        return None
    entity = corpus.entities.get(action.target)
    if entity is None or entity.dialogue is None:
        # Can't judge (dead/missing NPCs are the resolver's business).
        return None
    paths = entity.dialogue.dialogue_paths
    if path_id in paths:
        return None
    available = (
        ", ".join(sorted(paths))
        if paths
        else "none (this NPC has no dialogue paths)"
    )
    return (
        f"Unknown dialogue_path {path_id!r} for NPC '{action.target}'. "
        f"Available dialogue paths: {available}. Do NOT invent path IDs; "
        "omit 'dialogue_path' for normal conversation."
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
    left to the engine (when in doubt, return ``None``).  The budget is
    checked in :func:`_validate_budget`.
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


def _validate_budget(action, briefing: GMBriefing) -> str | None:
    """Reject actions that consume budget the player no longer has (§3.3).

    Each action's cost is judged against the briefing's remaining budget
    (``action_available`` / ``bonus_action_available`` /
    ``free_interaction_available``, derived from ``CombatState``): a
    second action, a second bonus action, or a second free interaction
    with the corrective retry.
    """
    combat = briefing.combat_state
    if combat is None:
        return None

    action_used = not combat.action_available
    ba_used = not combat.bonus_action_available
    free_used = not combat.free_interaction_available

    def _no_action(what: str) -> str:
        return (
            f"Invalid {what}: the player has no action left this turn. "
            f"Rule the attempt as 'wait' (pass, ending the turn), or if "
            f"the bonus action is still available, a bonus-action ability "
            f"instead."
        )

    if isinstance(action, CombatAction):
        if (
            action.combat_action != "maneuver"
            and (action.equip_target is not None or action.unequip_target is not None)
            and free_used
        ):
            # Attack-carried equip/unequip always costs the free object
            # interaction (§4.2).
            return (
                "Invalid attack-carried equip: the free object "
                "interaction was already used this turn. Do not attach "
                "equip_target/unequip_target to the attack."
            )
        if action.combat_action == "attack" and action_used:
            # A second attack is only the bonus-action off-hand attack
            # (Light property).
            if not combat.off_hand_attack_available:
                return (
                    "Invalid combat action: the action was already used "
                    "this turn, and no bonus-action off-hand attack (Light "
                    "property) is available. Rule the attempt as 'wait' "
                    "(pass) or a bonus-action ability instead."
                )
        elif action_used:
            return _no_action("combat action")
    elif isinstance(action, UseAbilityAction):
        entry = next(
            (
                a
                for a in combat.abilities
                if str(a.get("id")) == action.ability_id
            ),
            None,
        )
        casting_time = (
            (entry.get("casting_time") or "action") if entry else "action"
        )
        if casting_time == "bonus_action":
            if ba_used:
                return (
                    f"Invalid use_ability '{action.ability_id}': the bonus "
                    f"action was already used this turn, or no legal "
                    f"bonus-action option remains. Cast it as the main "
                    f"action instead (or rule a different action)."
                )
            if combat.bonus_action_options and (
                action.ability_id not in combat.bonus_action_options
            ):
                return (
                    f"Invalid use_ability '{action.ability_id}': it is not "
                    f"a legal bonus-action option right now (see "
                    f"bonus_action_options)."
                )
        elif action_used:
            return _no_action("use_ability")
    elif isinstance(action, MoveAction):
        if action_used:
            return _no_action("move (flee)")
    elif isinstance(action, TransferAction):
        if action_used:
            return _no_action("transfer")
    elif isinstance(action, ExamineAction):
        if action.rigorous and action_used:
            return _no_action("rigorous examine")
    elif isinstance(action, InteractAction):
        cost = getattr(action, "interaction_cost", "action") or "action"
        if cost == "free":
            if free_used:
                return (
                    "Invalid interaction_cost \"free\": the free object "
                    "interaction was already used this turn. Rule it as an "
                    "action-cost interaction (interaction_cost \"action\") "
                    "if the action is still available."
                )
            usable_ids = {
                str(u.get("id"))
                for u in combat.usable_items
                if u.get("id") is not None
            }
            # Mirrors the engine-side rule (resolver
            # _resolve_combat_environmental): an interaction with a
            # carried item — potions and other usable items included —
            # always requires an action.
            carried_ids = set(briefing.player_state.hard_inventory) | {
                item.id for item in briefing.player_state.equipped_items
            }
            if action.target in usable_ids or action.target in carried_ids:
                return (
                    f"Invalid interaction_cost \"free\" on "
                    f"'{action.target}': items you carry (potions and "
                    f"other usable items) always require an action to "
                    f"use. Set interaction_cost to \"action\"."
                )
        elif action_used:
            return _no_action("interact")
    elif isinstance(action, GearAction):
        if free_used and action_used:
            return (
                "Invalid gear action: no object interaction remains this "
                "turn (the free interaction and the action are both used). "
                "Rule the attempt as 'wait' (pass, ending the turn)."
            )
    return None


def _validate_maneuver(action: CombatAction, briefing: GMBriefing) -> str | None:
    """Target checks for the target-requiring maneuvers (Grapple / Shove /
    Help): the target must be a living enemy combatant.  Dodge and Escape
    take no target.  (``disengage`` predates the budget model.)"""
    combat = briefing.combat_state
    if combat is None:
        return None
    if action.maneuver not in ("grapple", "shove", "help"):
        return None
    enemies = _enemy_ids(briefing)
    if action.target in enemies:
        return None
    return (
        f"Invalid maneuver '{action.maneuver}' target '{action.target}': "
        f"'{action.maneuver}' requires a living enemy combatant ID. Valid "
        f"enemy IDs: {', '.join(enemies) if enemies else 'none'}."
    )


def validate_improvised_weapon_budget(action, briefing: GMBriefing) -> str | None:
    """Soft-fail check for the optional ``set_improvised_weapon`` pickup.

    Picking up an improvised weapon consumes an object interaction (§4.3).
    Mirrors the engine backstop; like :func:`validate_positioning_assertion`,
    an error here strips the patch (never the corrective retry) so the core
    action proceeds.
    """
    combat = briefing.combat_state
    if combat is None:
        return None
    patches = getattr(action, "soft_state_patches", None) or []
    if not any(
        p.field == "set_improvised_weapon" and p.new_value is not None
        for p in patches
    ):
        return None
    if not combat.free_interaction_available and not combat.action_available:
        return (
            "The set_improvised_weapon pickup consumes an object "
            "interaction, and both the free interaction and the action are "
            "already used this turn — the pickup cannot be part of this "
            "action."
        )
    return None


def _validate_soft_patches(action, briefing: GMBriefing, corpus) -> str | None:
    """Check ``soft_state_patches`` whose validity is knowable up front.

    Currently this covers ``set_improvised_weapon``: the keyword and
    damage type are chosen from fixed system-defined lists, and
    ``source_item`` must name a carried soft item, so an invalid choice
    is provably wrong and earns a corrective retry.
    """
    patches = getattr(action, "soft_state_patches", None) or []
    if not patches or corpus is None:
        return None
    from mgmai.engine.systems import get_system_for_corpus

    system = get_system_for_corpus(corpus)
    for patch in patches:
        if patch.field != "set_improvised_weapon" or patch.new_value is None:
            continue
        value = patch.new_value
        if not isinstance(value, dict):
            return (
                "set_improvised_weapon's value must be an object with a "
                "'keyword' field (or null to clear the weapon)."
            )
        keyword = value.get("keyword")
        if not isinstance(keyword, str) or system.improvised_weapon_stats(keyword) is None:
            valid = ", ".join(system.improvised_weapon_keywords())
            return (
                f"Unknown improvised weapon keyword {keyword!r}. "
                f"Choose one of: {valid}."
            )
        damage_type = value.get("damage_type")
        if (
            damage_type is not None
            and damage_type not in system.improvised_weapon_damage_types
        ):
            valid = ", ".join(system.improvised_weapon_damage_types)
            return (
                f"Invalid improvised weapon damage_type {damage_type!r}. "
                f"Choose one of: {valid} (or omit it for the default)."
            )
        source_item = value.get("source_item")
        if source_item is not None:
            carried = briefing.player_state.soft_inventory
            if source_item not in carried:
                return (
                    f"Improvised weapon source_item {source_item!r} is not "
                    f"in the player's soft inventory "
                    f"({', '.join(carried) or 'empty'}). Omit 'source_item' "
                    f"for an object picked up from the environment."
                )
    return None


def validate_interact(action: InteractAction, briefing: GMBriefing) -> str | None:
    """Out-of-combat interact rulings: the interaction must actually be
    offered by the target (or by the room).  A wrong-target ruling would
    otherwise sail through validation and fail at resolution, wasting the
    turn — so flag it here, naming the right target when we can."""
    interaction_id = action.interaction_id
    if not interaction_id or interaction_id == "attack":
        return None  # generic interactions are always available
    room = briefing.current_room
    if room is None:
        return None
    room_offers = {i.id for i in (room.interactions_available or [])}
    if interaction_id in room_offers:
        return None  # room-scoped interactions match any target (resolver behavior)
    # Map every visible entity — and every entity nested in one — to the
    # interactions it offers.
    offers: dict[str, set[str]] = {}
    target_types: dict[str, str] = {}
    for ent in room.entities_visible or []:
        offers.setdefault(ent.id, set()).update(
            i.id for i in (ent.interactions_available or [])
        )
        target_types[ent.id] = ent.type
        for cont in ent.contains or []:
            offers.setdefault(cont.id, set()).update(
                i.id for i in (cont.interactions_available or [])
            )
            target_types[cont.id] = cont.type
    if action.target not in offers:
        return None  # unknown target (inventory item etc.) — resolver reports it
    offered_by = sorted(
        eid for eid, ids in offers.items() if interaction_id in ids
    )
    if action.target in offered_by:
        return None
    if offered_by:
        return (
            f"Invalid interact target '{action.target}': interaction "
            f"'{interaction_id}' is not offered by '{action.target}'. It is "
            f"offered by: {', '.join(offered_by)}. Target that entity instead."
        )
    # Offered nowhere: name what the target DOES offer, plus the right
    # action kind for the common category confusions (talk vs interact,
    # take vs interact).
    available = offers.get(action.target) or set()
    if available:
        avail_txt = f" It offers: {', '.join(sorted(available))}."
    else:
        avail_txt = " It offers no interactions."
    target_type = target_types.get(action.target)
    if target_type == "npc":
        hint = " To converse with an NPC, use a talk action instead."
    elif target_type == "item":
        hint = (
            " To pick up an item, use a transfer action with taken_items "
            "instead."
        )
    else:
        hint = ""
    return (
        f"Invalid interaction_id '{interaction_id}': '{action.target}' "
        f"does not offer it.{avail_txt}{hint} Choose an interaction from "
        "the target's interactions_available, or a different action."
    )


def validate_ruling_action(action, briefing: GMBriefing, corpus=None) -> str | None:
    """Check a parsed PlayerAction for semantic consistency with the briefing.

    Returns ``None`` when the action is consistent (or when the briefing
    lacks the data needed to judge it).  Otherwise returns a short error
    string addressed to the model, suitable for the corrective retry prompt.
    """
    patch_error = _validate_soft_patches(action, briefing, corpus)
    if patch_error is not None:
        return patch_error
    # Hallucinated dialogue paths are rejected in and out of combat:
    # the resolver hard-fails the whole turn on an unknown path.
    if isinstance(action, TalkAction):
        path_error = validate_dialogue_path(action, briefing, corpus)
        if path_error is not None:
            return path_error
    if briefing.combat_state is None:
        if isinstance(action, UseAbilityAction):
            return _validate_use_ability(action, briefing)
        if isinstance(action, InteractAction):
            return validate_interact(action, briefing)
        return None
    # Budget-aware rejection (second action / second bonus action / second
    # free interaction) runs before the target-level checks.
    budget_error = _validate_budget(action, briefing)
    if budget_error is not None:
        return budget_error
    if isinstance(action, CombatAction):
        if action.combat_action == "attack":
            return _validate_attack(action, briefing)
        if action.combat_action == "maneuver":
            return _validate_maneuver(action, briefing)
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

    def _is_living(cid: str) -> bool:
        # Mirror engine ``_living_combatant``: the player is alive while in
        # combat; non-player combatants additionally require current_hp > 0.
        c = combatants.get(cid)
        if c is None:
            return False
        if cid == "player":
            return True
        return (c.get("current_hp") or 0) > 0

    valid_ids = ", ".join(sorted(cid for cid in combatants if _is_living(cid))) or "none"
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
            if not isinstance(cid, str) or not _is_living(cid):
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
