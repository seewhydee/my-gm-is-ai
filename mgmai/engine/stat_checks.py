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

"""Stat check computation utilities.

The system-specific maths (modifier formula, dice, advantage/disadvantage)
now live in :mod:`mgmai.engine.systems`.  This module retains thin
backward-compatible shims — ``roll_d20``, ``compute_5e_modifier``,
``compute_modifier`` — so existing call sites and tests keep working, plus
the narrative-prefix formatters which are system-agnostic.

``random`` is imported (though no longer called directly here) because test
code monkeypatches ``mgmai.engine.stat_checks.random.randint``; since
``random`` is a shared module object, that patch steers the system's dice
too.
"""

import random  # noqa: F401  — kept as a monkeypatch anchor for tests
from typing import Any

from mgmai.models.corpus import StatModifier
from mgmai.engine.systems import get_system


def roll_d20(advantage: bool = False, disadvantage: bool = False) -> int:
    """Roll 1d20 with optional advantage or disadvantage.

    Delegates to the active 5e resolution system.  Kept for backward
    compatibility with call sites and tests that address this module
    directly.
    """
    return get_system("5e").roll_die(20, advantage=advantage, disadvantage=disadvantage)


def compute_5e_modifier(stat_value: int) -> int:
    """D&D 5e-style ability modifier, via the 5e resolution system."""
    return get_system("5e").compute_modifier(stat_value)


def compute_modifier(stat_value: int, system: str) -> int:
    """Compute a stat modifier given a resolution system identifier."""
    return get_system(system).compute_modifier(stat_value)


def format_stat_check_prefix(rolls: list[dict[str, Any]]) -> str:
    """Return a markdown-formatted prefix summarizing any stat checks.

    The prefix is intended to be prepended to the narration shown to the
    player after a player action that involved one or more stat checks.
    Only rolls with ``check_type == "stat_check"`` (or legacy
    ``type == "stat_check"``) are summarised.  If no such rolls exist, an
    empty string is returned.

    Example output::

        **[STR check: failed]**

        **[DEX check: success]**

    """
    summaries: list[str] = []
    for roll in rolls:
        check_type = roll.get("check_type") or roll.get("type")
        if check_type != "stat_check":
            continue
        stat = roll.get("stat")
        success = roll.get("success")
        if stat is None or success is None:
            continue
        outcome = "success" if success else "failed"
        summaries.append(f"**[{stat} check: {outcome}]**")

    if not summaries:
        return ""

    return "\n\n".join(summaries) + "\n\n"


def format_combat_prefix(
    combat_log: list[dict[str, Any]],
    corpus: Any = None,
) -> str:
    """Return a markdown-formatted prefix summarizing combat events.

    The prefix is prepended to LLM Call 2 narration after a combat turn.
    Example output::

        **Spider attacks you: hit for 3 damage.**
        **You attack Goblin: miss.**

    Returns an empty string if there are no combat log entries.
    """
    if not combat_log:
        return ""

    summaries: list[str] = []
    for entry in combat_log:
        actor = entry.get("actor", "?")
        action = entry.get("action", "?")
        target = entry.get("target", "?")

        if action == "death":
            if actor == "player":
                summaries.append("**You have been slain!**")
            else:
                name = _entity_name(actor, corpus)
                summaries.append(f"**{name} is dead!**")
        elif action == "attack":
            hit = entry.get("hit")
            damage = entry.get("damage")
            crit = entry.get("critical")

            if actor == "player":
                if entry.get("attack_name"):
                    # Player ability attacks read "You use Fire Bolt on …"
                    name = f"You use {entry['attack_name']} on"
                else:
                    name = "You attack"
            elif entry.get("attack_name"):
                # Named attacks carry a verb phrase ("bites", "slashes").
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
                summaries.append(f"**{name} {target_name}: hit{dmg_str}.**")

                # On-hit effect summaries
                for eh in entry.get("on_hit_effects") or []:
                    save_stat = eh.get("save_stat", "?")
                    save_success = eh.get("save_success")
                    eh_damage = eh.get("damage", 0)
                    eh_type = eh.get("damage_type", "")
                    eh_expr = eh.get("damage_expr") or ""
                    type_str = f" {eh_type}" if eh_type else ""
                    if save_success:
                        if eh_damage == 0:
                            summaries.append(f"**{save_stat} save: success — no{type_str} damage.**")
                        elif isinstance(eh_expr, str) and eh_expr.startswith("half("):
                            summaries.append(f"**{save_stat} save: success — half{type_str} damage ({eh_damage}).**")
                        else:
                            summaries.append(f"**{save_stat} save: success — {eh_damage}{type_str} damage.**")
                    else:
                        summaries.append(f"**{save_stat} save: failed — {eh_damage}{type_str} damage.**")
            else:
                summaries.append(f"**{name} {target_name}: miss.**")
        elif action == "flee":
            if actor != "player":
                summaries.append(f"**{_entity_name(actor, corpus)} flees!**")
            elif entry.get("hit"):
                summaries.append("**You break away from combat!**")
            else:
                summaries.append("**You fail to escape!**")
        elif action == "stunned":
            if actor == "player":
                summaries.append("**You are stunned and cannot act!**")
            else:
                summaries.append(
                    f"**{_entity_name(actor, corpus)} is stunned and cannot act.**"
                )
        elif action == "use_item":
            name = _entity_name(target, corpus)
            healed = entry.get("damage") or 0
            if healed:
                summaries.append(f"**You use {name}: healed {healed} HP.**")
            else:
                summaries.append(f"**You use {name}.**")
        elif action == "ability_save":
            caster = "You" if actor == "player" else _entity_name(actor, corpus)
            abil = entry.get("attack_name") or "an ability"
            tgt = "you" if target == "player" else _entity_name(target, corpus)
            dmg = entry.get("damage") or 0
            oh = (entry.get("on_hit_effects") or [{}])[0]
            outcome = "resists" if oh.get("save_success") else "fails to resist"
            summaries.append(
                f"**{caster} uses {abil}: {tgt} {outcome} — {dmg} damage.**"
            )
        elif action == "heal":
            caster = "You" if actor == "player" else _entity_name(actor, corpus)
            abil = entry.get("attack_name") or "an ability"
            healed = entry.get("damage") or 0
            if target == actor:
                summaries.append(f"**{caster} uses {abil}: healed {healed} HP.**")
            else:
                tgt = "you" if target == "player" else _entity_name(target, corpus)
                summaries.append(
                    f"**{caster} uses {abil} on {tgt}: healed {healed} HP.**"
                )

    if not summaries:
        return ""

    return "\n\n".join(summaries) + "\n\n"


def _entity_name(entity_id: str, corpus: Any) -> str:
    """Resolve an entity id to a display name using the corpus."""
    if corpus and hasattr(corpus, "entities"):
        entity = corpus.entities.get(entity_id)
        if entity:
            return getattr(entity, "name", entity_id) or entity_id
    return entity_id


def format_stat_change_prefix(
    stat_modifiers: dict[str, StatModifier],
    old_stat_values: dict[str, int],
) -> str:
    """Return a markdown-formatted prefix summarizing any stat changes.

    The prefix is intended to be prepended to the narration shown to the
    player after a player action that altered stats.  If no modifiers
    exist, an empty string is returned.

    Example output::

        **[STR -4 (now 6)]**

        **[INT set to 3]**

    """
    summaries: list[str] = []
    for stat_key, mod in stat_modifiers.items():
        old_val = old_stat_values.get(stat_key)
        if mod.mode == "set":
            summaries.append(f"**[{stat_key} set to {mod.value}]**")
        elif old_val is not None:
            new_val = old_val + mod.value
            sign = "+" if mod.value >= 0 else ""
            summaries.append(f"**[{stat_key} {sign}{mod.value} (now {new_val})]**")

    if not summaries:
        return ""

    return "\n\n".join(summaries) + "\n\n"


def format_hp_change_prefix(
    player_hp_delta: int | None,
    current_hp: int,
    max_hp: int,
) -> str:
    """Return a markdown-formatted prefix for HP changes (damage or healing).

    Example output::

        **[Took 9 damage (HP 18/27)]**

        **[Healed 5 HP (HP 27/27)]**

    Returns an empty string if there is no HP delta.
    """
    if player_hp_delta is None or player_hp_delta == 0:
        return ""
    if player_hp_delta < 0:
        return f"**[Took {abs(player_hp_delta)} damage (HP {current_hp}/{max_hp})]**\n\n"
    return f"**[Healed {player_hp_delta} HP (HP {current_hp}/{max_hp})]**\n\n"
