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

"""Shared status/combat view-models.

Structured, front-end-agnostic views of the game status: computed once
from engine state, then rendered per front-end (Rich terminal panel,
Telegram chat message, headless snapshot).  Nothing here renders —
data assembly only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mgmai.state.manager import StateManager

# ------------------------------------------------------------------
# Post-turn status snapshot (headless transcript / automation)
# ------------------------------------------------------------------


@dataclass
class StatusSnapshot:
    """Compact, JSON-serialisable view of the post-turn game status."""

    turn_count: int
    location: str
    in_combat: bool
    combat_round: int | None
    player_hp: int | None
    player_max_hp: int | None
    # {combatant_id: {"hp", "max_hp", "side": "party"|"enemy", "alive",
    #                 "status_effects": {status_effect: rounds},
    #                 "status_effect_names": {status_effect: display name},
    #                 "fled": bool}}
    combatants: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_flags: dict[str, bool] = field(default_factory=dict)
    # Dialogue soft state for this turn: {"active_npc", "attitude",
    # "topics_discussed", "stall_counter", "entered_turn", "log_length"}.
    # Empty dict when no dialogue state is available.
    dialogue: dict[str, Any] = field(default_factory=dict)
    # Action economy for the player's current combat turn: the five
    # TurnBudget booleans plus "reactions_spent" (sorted combatant ids),
    # "action_weapon_id", and "turn_continuation".  Empty dict when not
    # in combat.
    player_budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_count": self.turn_count,
            "location": self.location,
            "in_combat": self.in_combat,
            "combat_round": self.combat_round,
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "combatants": self.combatants,
            "active_flags": self.active_flags,
            "dialogue": self.dialogue,
            "player_budget": self.player_budget,
        }


def snapshot_status(state_manager: StateManager) -> StatusSnapshot:
    """Build a ``StatusSnapshot`` from a ``StateManager``."""
    hard = state_manager.hard_state
    corpus = state_manager.corpus
    if hard is None:
        return StatusSnapshot(
            turn_count=0, location="", in_combat=False,
            combat_round=None, player_hp=None, player_max_hp=None,
        )

    combat = hard.combat
    combatants: dict[str, dict[str, Any]] = {}
    if combat is not None:
        effect_defs = corpus.effective_status_effects() if corpus else {}

        def _effect_label(c: str) -> str:
            cdef = effect_defs.get(c)
            return cdef.name if cdef is not None and cdef.name else c

        allies = set(combat.allies)
        for cid in combat.combatants:
            if cid == "player":
                hp = hard.player.current_hp or 0
                max_hp = hard.player.max_hp or 0
                side = "party"
                status_effects = dict(hard.player.status_effects or {})
                fled = False
            else:
                state = hard.entity_states.get(cid, {})
                hp = int(state.get("current_hp") or 0)
                ent = corpus.entities.get(cid) if corpus else None
                max_hp = (ent.combat.hp if ent and ent.combat else 0)
                side = "party" if cid in allies else "enemy"
                status_effects = dict(state.get("status_effects") or {})
                fled = bool(state.get("fled"))
            combatants[cid] = {
                "hp": hp,
                "max_hp": max_hp,
                "side": side,
                "alive": hp > 0,
                "status_effects": status_effects,
                "status_effect_names": {c: _effect_label(c) for c in status_effects},
                "fled": fled,
                # Positioning: engagement partners (combatant ids) and
                # the pending impede flag.
                "engaged_with": sorted(
                    p[1] if p[0] == cid else p[0]
                    for p in (combat.engagement or [])
                    if cid in p
                ),
                "impeded": cid in (combat.impeded or []),
            }

    player_budget: dict[str, Any] = {}
    if combat is not None:
        player_budget = {
            **combat.player_budget.model_dump(),
            "reactions_spent": sorted(combat.reactions_spent),
            "action_weapon_id": combat.action_weapon_id,
            "turn_continuation": combat.turn_continuation,
        }

    dialogue: dict[str, Any] = {}
    soft = state_manager.soft_state
    if soft is not None:
        ds = soft.dialogue_state
        dialogue = {
            "active_npc": ds.active_npc,
            "attitude": (
                hard.entity_states.get(ds.active_npc, {}).get("attitude")
                if ds.active_npc is not None
                else None
            ),
            "topics_discussed": list(ds.topics_discussed),
            "stall_counter": ds.stall_counter,
            "entered_turn": ds.entered_turn,
            "log_length": len(ds.conversation_log),
        }

    return StatusSnapshot(
        turn_count=hard.turn_count,
        location=hard.player.location,
        in_combat=combat is not None and combat.active,
        combat_round=combat.round_number if combat is not None else None,
        player_hp=hard.player.current_hp,
        player_max_hp=hard.player.max_hp,
        combatants=combatants,
        active_flags={k: v for k, v in hard.flags.items() if v},
        dialogue=dialogue,
        player_budget=player_budget,
    )


# Back-compat alias: promoted out of mgmai/game/headless.py, where this
# name lives in existing imports.
_snapshot_status = snapshot_status


# ------------------------------------------------------------------
# Combat panel view-model
# ------------------------------------------------------------------


@dataclass
class CombatantRow:
    """One combatant's row in the combat panel (data, no rendering)."""

    cid: str
    name: str
    hp: int
    max_hp: int
    status_effects: dict[str, int]
    # Display text for status effects, e.g. "Poisoned 2, Stunned 1"
    # (StatusEffectDef.name when set, raw ID otherwise).
    status_effects_text: str
    fled: bool
    # Engagement partners as display names.
    engaged_with: list[str]
    impeded: bool
    # Damage mitigations the party discovered by landing hits, e.g.
    # "resists piercing; vulnerable to fire" (from the combat log, so
    # nothing the player hasn't learned is leaked).
    mitigation_text: str

    @property
    def dead(self) -> bool:
        return self.hp <= 0


@dataclass
class CombatView:
    """Structured combat status panel, rendered per front-end."""

    round_number: int
    initiative_order: list[str]
    current_cid: str | None
    party: list[CombatantRow]
    enemies: list[CombatantRow]
    # One-line player resource summary: AC, weapon, ability uses, items.
    footer: str


def combat_player_footer(hard: Any, corpus: Any, combat: Any) -> str:
    """One-line summary of the player's combat-relevant resources:
    AC, equipped weapon, ability uses left, and usable items."""
    parts: list[str] = []
    try:
        from mgmai.engine.combat import compute_player_ac
        ac = compute_player_ac(hard, corpus) if corpus else hard.player.ac
    except Exception:  # noqa: BLE001 — display must never crash a turn
        ac = hard.player.ac
    if ac is not None:
        parts.append(f"AC {ac}")
    if corpus:
        for item_id in hard.player.equipped:
            entity = corpus.entities.get(item_id)
            if (
                entity
                and entity.equip_block
                and "weapon" in entity.equip_block.equip_tags
            ):
                dmg = entity.equip_block.damage_expr + (
                    f" {entity.equip_block.damage_type}"
                    if entity.equip_block.damage_type
                    else ""
                )
                parts.append(f"{entity.name or item_id} ({dmg})")
                break
        for aid in hard.player.abilities:
            ability = corpus.abilities.get(aid)
            if ability is None:
                continue
            if ability.spell_level is not None and ability.spell_level >= 1:
                # Leveled spells draw on the slot pool, not uses.
                slots = hard.player.spell_slots.get(ability.spell_level, 0)
                parts.append(
                    f"{ability.name} (level {ability.spell_level} slots: {slots})"
                )
            elif ability.uses_per_combat < 0:
                parts.append(ability.name)
            else:
                used = (combat.ability_uses.get("player", {}) or {}).get(aid, 0)
                remaining = ability.uses_per_combat - used
                parts.append(f"{ability.name} {remaining}/{ability.uses_per_combat}")
        items: list[str] = []
        for item_id, count in (hard.player.inventory or {}).items():
            if count <= 0:
                continue
            entity = corpus.entities.get(item_id)
            if entity is not None and entity.interactions:
                items.append(f"{entity.name or item_id} x{count}")
        parts.append("Items: " + (", ".join(items) if items else "none"))
    return " · ".join(parts)


def build_combat_view(hard: Any, corpus: Any) -> CombatView:
    """Assemble the combat panel data from engine state.

    Rows show status effects, fled/dead state, engagement, impede, and
    discovered damage mitigations; the footer summarizes the player's
    combat resources.  Rendering (bars, columns, widths) is the
    front-end's job.
    """
    combat = hard.combat
    effect_defs = corpus.effective_status_effects() if corpus else {}

    def _effect_label(c: str) -> str:
        cdef = effect_defs.get(c)
        return cdef.name if cdef is not None and cdef.name else c

    def _status_effects_text(status_effects: dict) -> str:
        """e.g. 'poisoned 2, stunned 1' (StatusEffectDef.name when set)"""
        return ", ".join(f"{_effect_label(c)} {n}" for c, n in status_effects.items())

    def _cid_name(cid: str) -> str:
        """Display name for a combatant id (engagement partners)."""
        if cid == "player":
            return "Player"
        ent = corpus.entities.get(cid) if corpus else None
        return (ent.name or cid) if ent else cid

    # Damage mitigations the party has discovered by landing hits on
    # each enemy (damage type -> mitigation), taken from the combat
    # log so nothing unlearned is revealed.
    discovered: dict[str, dict[str, str]] = {}
    for entry in combat.log or []:
        target = getattr(entry, "target", None)
        mitigation = getattr(entry, "mitigation", None)
        damage_type = getattr(entry, "damage_type", "") or ""
        if target and target != "player" and mitigation and damage_type:
            discovered.setdefault(target, {})[damage_type] = mitigation

    def _mitigation_text(cid: str) -> str:
        """e.g. 'resists piercing; vulnerable to fire'"""
        parts: list[str] = []
        for damage_type, mitigation in discovered.get(cid, {}).items():
            if mitigation == "resisted":
                parts.append(f"resists {damage_type}")
            elif mitigation == "vulnerable":
                parts.append(f"vulnerable to {damage_type}")
            elif mitigation == "immune":
                parts.append(f"immune to {damage_type}")
        return "; ".join(parts)

    def _row_data(cid: str) -> CombatantRow:
        # Positioning: engagement partners (display names) and the
        # pending impede flag, shown as row markers.
        engaged_with = sorted(
            _cid_name(p[1] if p[0] == cid else p[0])
            for p in (combat.engagement or [])
            if cid in p
        )
        impeded = cid in (combat.impeded or [])
        if cid == "player":
            status_effects = dict(hard.player.status_effects or {})
            return CombatantRow(
                cid=cid,
                name="Player",
                hp=hard.player.current_hp or 0,
                max_hp=hard.player.max_hp or 0,
                status_effects=status_effects,
                status_effects_text=_status_effects_text(status_effects),
                fled=False,
                engaged_with=engaged_with,
                impeded=impeded,
                mitigation_text="",
            )
        entity = corpus.entities.get(cid) if corpus else None
        state = hard.entity_states.get(cid, {})
        status_effects = dict(state.get("status_effects") or {})
        return CombatantRow(
            cid=cid,
            name=(entity.name or cid) if entity else cid,
            hp=int(state.get("current_hp") or 0),
            max_hp=(entity.combat.hp if entity and entity.combat else 0),
            status_effects=status_effects,
            status_effects_text=_status_effects_text(status_effects),
            fled=bool(state.get("fled")),
            engaged_with=engaged_with,
            impeded=impeded,
            mitigation_text=_mitigation_text(cid),
        )

    # Current actor in the initiative order.  The panel renders while
    # awaiting the player's command, so this is normally the player.
    current_cid = None
    if 0 <= combat.current_index < len(combat.initiative_order):
        current_cid = combat.initiative_order[combat.current_index]

    party_ids = [
        c for c in combat.combatants
        if c == "player" or c in combat.allies
    ]
    enemy_ids = [c for c in combat.combatants if c not in party_ids]

    return CombatView(
        round_number=combat.round_number,
        initiative_order=list(combat.initiative_order),
        current_cid=current_cid,
        party=[_row_data(c) for c in party_ids],
        enemies=[_row_data(c) for c in enemy_ids],
        footer=combat_player_footer(hard, corpus, combat),
    )


# ------------------------------------------------------------------
# Exits formatting (shared by the turn pipeline and intro panels)
# ------------------------------------------------------------------


def format_exits(room: Any, indent: int = 0) -> str:
    """Format a room's visible exits as a string suitable for appending
    to narration.  ``room`` is a BriefingRoom or a corpus Room.

    Returns an empty string if there are no visible exits.
    """
    exits: list = getattr(room, "exits_available", None)
    if exits is None:
        exits = getattr(room, "exits", [])

    visible: list = []
    for e in exits:
        hidden = getattr(e, "hidden", False)
        if hidden:
            continue
        direction = getattr(e, "direction", "")
        one_way = getattr(e, "one_way", False)
        label = f"* {direction}"
        if one_way:
            label += " (one-way)"
        visible.append(label)

    if not visible:
        return ""

    prefix = " " * indent
    lines = [f"\n\n{prefix}**Exits:**"]
    for v in visible:
        lines.append(f"{prefix}{v}")
    return "\n".join(lines)
