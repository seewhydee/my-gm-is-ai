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

"""Deterministic helpers for rest-mode bookkeeping.

These are called by the game-layer rest mode (Part 2 of the rests
design) to mutate ``hard.player`` directly — spending Hit Dice to heal
and swapping the prepared-spell list.  No LLM, no turn consumed, no
``input()``: validation is synchronous and the caller can never leave
the menu in an invalid state.  They mirror how
``apply_status_effect`` / ``remove_status_effect`` mutate ``hard``
outside the ``HardStateChanges`` path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mgmai.engine.systems import get_system_for_corpus

if TYPE_CHECKING:
    from mgmai.models.corpus import ModuleCorpus
    from mgmai.models.hard_state import HardGameState


def _parse_die(die: str) -> int:
    """Parse a die type like ``"d8"`` / ``"D6"`` / ``"8"`` into its face count."""
    s = die.strip()
    if s and s[0] in "dD":
        s = s[1:]
    return int(s)


def spend_hit_die(
    hard: HardGameState, corpus: ModuleCorpus
) -> tuple[bool, str, int]:
    """Spend one Hit Die to heal (SRD 5.2.1 short rest).

    Rolls the die, adds the CON modifier, heals ``current_hp`` (clamped
    to max), and decrements ``hit_dice.current``.  Returns
    ``(success, message, hp_healed)``.  Fails (no mutation) when the
    player has no Hit Dice left or is already at full HP.
    """
    hd = hard.player.hit_dice
    if hd is None or hd.current <= 0:
        return False, "You have no Hit Dice left to spend.", 0

    system = get_system_for_corpus(corpus)
    faces = _parse_die(hd.die)
    roll = system.roll_die(faces)
    con_score = (hard.player.stats or {}).get("CON", 10)
    con_mod = system.compute_modifier(con_score)
    regained = max(1, roll + con_mod)

    max_hp = system.compute_player_max_hp(hard, corpus)
    current = hard.player.current_hp or 0
    heal = min(regained, max_hp - current)
    if heal <= 0:
        return False, "You are already at full HP.", 0

    hard.player.current_hp = current + heal
    hd.current -= 1
    sign = f"{con_mod:+d}" if con_mod else "0"
    msg = (
        f"You spend a {hd.die} (roll {roll} + CON {sign} = {regained}); "
        f"you regain {heal} HP."
    )
    return True, msg, heal


def set_prepared_spells(
    hard: HardGameState, corpus: ModuleCorpus, ability_ids: list[str]
) -> tuple[bool, str]:
    """Set the player's prepared abilities (the castable list).

    Validates every ID resolves to a corpus ability and, when a
    ``spellbook`` is declared, that each is in the spellbook.  Mutates
    ``hard.player.abilities``.  Returns ``(success, message)``.  On
    failure, ``abilities`` is left untouched.
    """
    spellbook = hard.player.spellbook
    known = set(corpus.abilities) | set(corpus.effective_spells())
    for aid in ability_ids:
        if aid not in known:
            return False, f"'{aid}' is not a known ability."
        if spellbook and aid not in spellbook:
            return (
                False,
                f"'{aid}' is not in your spellbook and cannot be prepared.",
            )
    hard.player.abilities = list(ability_ids)
    return True, "Spells prepared."
