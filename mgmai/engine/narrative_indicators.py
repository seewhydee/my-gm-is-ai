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

"""Marker-based inline mechanical indicators for AI narration.

The engine produces a list of :class:`NarrativeIndicator` objects for each
turn.  Each indicator carries a unique marker (e.g. ``[MECH:check:0]``) and
its canonically formatted text (e.g. ``**[STR check: failed]**``).

Indicators are injected into the Call 2 (prose) prompt so the LLM can place
them at narratively appropriate points inside its narration.  After Call 2
returns, :func:`process_narration` replaces any used markers with their
formatted text and prepends any unused ones as a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _format_single_combat_entry(entry: dict[str, Any], corpus: Any = None) -> str:
    """Format a single combat log entry as a bold markdown line.

    Mirrors the per-entry logic in :func:`format_combat_prefix`.
    Returns an empty string for unhandled action types.
    """
    actor = entry.get("actor", "?")
    action = entry.get("action", "?")
    target = entry.get("target", "?")

    if action == "death":
        if actor == "player":
            return "**You have been slain!**"
        name = _entity_name(actor, corpus)
        return f"**{name} is dead!**"

    if action == "attack":
        hit = entry.get("hit")
        damage = entry.get("damage")
        crit = entry.get("critical")

        if actor == "player":
            if entry.get("attack_name"):
                name = f"You use {entry['attack_name']} on"
            else:
                name = "You attack"
        elif entry.get("attack_name"):
            name = f"{_entity_name(actor, corpus)} {entry['attack_name']}"
        else:
            name = f"{_entity_name(actor, corpus)} attacks"

        if target == "player":
            target_name = "you"
        else:
            target_name = _entity_name(target, corpus)

        if hit:
            crit_str = " (CRIT!)" if crit else ""
            mit = entry.get("mitigation")
            mit_str = f" ({mit})" if mit else ""
            dmg_str = f" for {damage} damage{crit_str}{mit_str}" if damage is not None else ""
            lines = [f"**{name} {target_name}: hit{dmg_str}.**"]
            for eh in entry.get("on_hit_effects") or []:
                save_stat = eh.get("save_stat", "?")
                save_success = eh.get("save_success")
                eh_damage = eh.get("damage", 0)
                eh_type = eh.get("damage_type", "")
                eh_expr = eh.get("damage_expr") or ""
                type_str = f" {eh_type}" if eh_type else ""
                if save_success:
                    if eh_damage == 0:
                        lines.append(f"**{save_stat} save: success — no{type_str} damage.**")
                    elif isinstance(eh_expr, str) and eh_expr.startswith("half("):
                        lines.append(f"**{save_stat} save: success — half{type_str} damage ({eh_damage}).**")
                    else:
                        lines.append(f"**{save_stat} save: success — {eh_damage}{type_str} damage.**")
                else:
                    lines.append(f"**{save_stat} save: failed — {eh_damage}{type_str} damage.**")
            return "\n\n".join(lines)
        return f"**{name} {target_name}: miss.**"

    if action == "flee":
        if actor != "player":
            return f"**{_entity_name(actor, corpus)} flees!**"
        if entry.get("hit"):
            return "**You break away from combat!**"
        return "**You fail to escape!**"

    if action == "stunned":
        if actor == "player":
            return "**You are stunned and cannot act!**"
        return f"**{_entity_name(actor, corpus)} is stunned and cannot act.**"

    if action == "use_item":
        name = _entity_name(target, corpus)
        healed = entry.get("damage") or 0
        if healed:
            return f"**You use {name}: healed {healed} HP.**"
        return f"**You use {name}.**"

    if action == "ability_save":
        caster = "You" if actor == "player" else _entity_name(actor, corpus)
        abil = entry.get("attack_name") or "an ability"
        tgt = "you" if target == "player" else _entity_name(target, corpus)
        dmg = entry.get("damage") or 0
        oh = (entry.get("on_hit_effects") or [{}])[0]
        outcome = "resists" if oh.get("save_success") else "fails to resist"
        return f"**{caster} uses {abil}: {tgt} {outcome} — {dmg} damage.**"

    if action == "heal":
        caster = "You" if actor == "player" else _entity_name(actor, corpus)
        abil = entry.get("attack_name") or "an ability"
        healed = entry.get("damage") or 0
        if target == actor:
            return f"**{caster} uses {abil}: healed {healed} HP.**"
        tgt = "you" if target == "player" else _entity_name(target, corpus)
        return f"**{caster} uses {abil} on {tgt}: healed {healed} HP.**"

    return ""


def _entity_name(entity_id: str, corpus: Any) -> str:
    """Resolve an entity id to a display name using the corpus."""
    if corpus and hasattr(corpus, "entities"):
        entity = corpus.entities.get(entity_id)
        if entity:
            return getattr(entity, "name", entity_id) or entity_id
    return entity_id


@dataclass
class NarrativeIndicator:
    """A single mechanical event that the LLM may place inside narration."""

    marker: str
    """Unique placeholder string, e.g. ``[MECH:check:0]``."""

    formatted: str
    """Canonical markdown-formatted text, e.g. ``**[STR check: failed]**``."""

    category: str
    """Broad category: ``check``, ``hp``, ``stat``, or ``combat``."""

    @property
    def plain_description(self) -> str:
        """A plain-text description for the prompt (no markdown bolding).

        Strips surrounding ``**[...]**`` wrappers if present.
        """
        text = self.formatted
        if text.startswith("**[") and text.endswith("]**"):
            return text[3:-3]
        if text.startswith("**") and text.endswith("**"):
            return text[2:-2]
        return text


def build_indicators(
    result: Any,
    hard_state: Any,
    corpus: Any = None,
) -> list[NarrativeIndicator]:
    """Build ordered indicators from an :class:`EngineResult`.

    The order matches the turn's mechanical events so that unplaced
    markers fall back to a sensible top-of-turn listing.
    """
    indicators: list[NarrativeIndicator] = []

    # --- stat checks ---
    check_idx = 0
    for roll in result.rolls or []:
        check_type = roll.get("check_type") or roll.get("type")
        if check_type != "stat_check":
            continue
        stat = roll.get("stat")
        success = roll.get("success")
        if stat is None or success is None:
            continue
        outcome = "success" if success else "failed"
        indicators.append(
            NarrativeIndicator(
                marker=f"[MECH:check:{check_idx}]",
                formatted=f"**[{stat} check: {outcome}]**",
                category="check",
            )
        )
        check_idx += 1

    hc = result.hard_state_changes

    # --- HP change ---
    if hc and hc.player_hp_delta:
        current_hp = hard_state.player.current_hp or 0
        max_hp = hard_state.player.max_hp or 0
        if hc.player_hp_delta < 0:
            formatted = f"**[Took {abs(hc.player_hp_delta)} damage (HP {current_hp}/{max_hp})]**"
        else:
            formatted = f"**[Healed {hc.player_hp_delta} HP (HP {current_hp}/{max_hp})]**"
        indicators.append(
            NarrativeIndicator(
                marker="[MECH:hp]",
                formatted=formatted,
                category="hp",
            )
        )

    # --- stat modifiers ---
    if hc and hc.stat_modifiers:
        parts: list[str] = []
        for stat_key, mod in hc.stat_modifiers.items():
            old_val = hc.old_stat_values.get(stat_key)
            if mod.mode == "set":
                parts.append(f"{stat_key} set to {mod.value}")
            elif old_val is not None:
                new_val = old_val + mod.value
                sign = "+" if mod.value >= 0 else ""
                parts.append(f"{stat_key} {sign}{mod.value} (now {new_val})")
        if parts:
            formatted = "\n\n".join(f"**[{p}]**" for p in parts)
            indicators.append(
                NarrativeIndicator(
                    marker="[MECH:stat]",
                    formatted=formatted,
                    category="stat",
                )
            )

    # --- combat log entries ---
    if result.combat_log:
        for i, entry in enumerate(result.combat_log):
            entry_dict = entry if isinstance(entry, dict) else entry.model_dump()
            formatted = _format_single_combat_entry(entry_dict, corpus)
            if formatted:
                indicators.append(
                    NarrativeIndicator(
                        marker=f"[MECH:combat:{i}]",
                        formatted=formatted,
                        category="combat",
                    )
                )

    return indicators


def process_narration(
    narration: str,
    indicators: list[NarrativeIndicator],
) -> str:
    """Replace markers in *narration* with their formatted text.

    Any indicators whose markers are not found in the narration are
    prepended (in order) as a fallback, preserving backward-compatible
    behaviour when the LLM does not use markers.
    """
    result = narration
    placed_markers: set[str] = set()

    for ind in indicators:
        if ind.marker in result:
            result = result.replace(ind.marker, ind.formatted, 1)
            placed_markers.add(ind.marker)

    # Prepend unplaced indicators as fallback
    unplaced = [ind for ind in indicators if ind.marker not in placed_markers]
    if unplaced:
        prefix = "\n\n".join(ind.formatted for ind in unplaced) + "\n\n"
        result = prefix + result

    return result


def format_indicators_fallback(
    result: Any,
    hard_state: Any,
    corpus: Any = None,
) -> str:
    """Format all indicators as a single prepended prefix string.

    This is a convenience wrapper for code paths that do **not** go
    through the marker-based prose generation (e.g. the LLM Call 2
    fallback path in ``GameLoop._execute_turn``).
    """
    indicators = build_indicators(result, hard_state, corpus)
    if not indicators:
        return ""
    return "\n\n".join(ind.formatted for ind in indicators) + "\n\n"
