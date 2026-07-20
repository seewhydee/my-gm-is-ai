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

"""Shared assertion helpers for LLM integration scenario modules.

The original combat-arena scenarios (``test_combat_arena.py``) define
module-local helpers tied to the arena's enemy set.  These generic
versions serve the newer fixture-based scenario modules (venom_pit,
ambush_alley).  The arena module is deliberately left untouched.
"""

from __future__ import annotations


def enemy_dead_or_fled(result, enemy_id: str, *, accept_fled: bool = False) -> bool:
    """Check whether *enemy_id* died (and optionally fled) in the combat
    log across all turns."""
    for t in result.turns:
        for entry in t.combat_log:
            if entry.get("actor") == enemy_id:
                if entry.get("action") == "death":
                    return True
                if accept_fled and entry.get("action") == "flee":
                    return True
    return False


def assert_combat_concluded(result, enemies, *, accept_fled=()) -> None:
    """Hard assertions on a finished combat run (engine correctness).

    Generic version of the arena module's ``_assert_combat_concluded``:
    victory is NOT required — the player may legitimately die.  What is
    asserted is that combat started and ended cleanly, with no exceptions
    or empty narrations, and that the ending was handled gracefully.

    - ``enemies``: the set of enemy IDs in the fight.  On a win, each must
      have a death entry in the combat log (or a flee entry when listed in
      ``accept_fled``).
    - On a loss: game-over recorded as a loss and the player's death
      logged.
    """
    last = result.last_turn
    assert last is not None, "No turns were recorded"

    # Run was not aborted mid-stream.
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; "
        f"see artifact: {result.artifacts_path}"
    )

    # Combat was entered at some point during the run.
    any_in_combat = any(t.status.in_combat for t in result.turns)
    assert any_in_combat, (
        "Combat never started; see artifact: " + str(result.artifacts_path)
    )

    # Combat ended within the turn cap; combat_state cleared.
    assert not last.status.in_combat, (
        f"Combat still active after {result.turn_count} turns; "
        f"see artifact: {result.artifacts_path}"
    )

    # No unhandled exceptions.
    assert result.error is None, (
        f"Unhandled exception during run: {result.error!r}; "
        f"see artifact: {result.artifacts_path}"
    )
    for i, t in enumerate(result.turns, 1):
        assert t.exception is None, (
            f"Turn {i} raised {t.exception!r}; "
            f"see artifact: {result.artifacts_path}"
        )

    # No empty narrations.
    for i, t in enumerate(result.turns, 1):
        assert t.narration, (
            f"Turn {i} produced empty narration; "
            f"see artifact: {result.artifacts_path}"
        )

    # turn_count never regressed.  A *rejected* action legitimately does
    # not advance the counter, so equality is fine — only a decrease
    # indicates corruption.
    prev = -1
    for i, t in enumerate(result.turns, 1):
        assert t.status.turn_count >= prev, (
            f"Turn {i}: turn_count regressed ({prev} -> {t.status.turn_count}); "
            f"see artifact: {result.artifacts_path}"
        )
        prev = t.status.turn_count

    player_hp = last.status.player_hp or 0
    if player_hp > 0:
        # Player won: each enemy must have a death entry in the combat
        # log (or a flee entry for enemies in accept_fled).
        for eid in enemies:
            assert enemy_dead_or_fled(
                result, eid, accept_fled=eid in accept_fled
            ), (
                f"Player survived but enemy '{eid}' is neither dead nor "
                f"fled in the combat log; see artifact: {result.artifacts_path}"
            )
        assert player_hp <= (last.status.player_max_hp or 999), (
            f"Player HP exceeds max: {player_hp}/{last.status.player_max_hp}; "
            f"see artifact: {result.artifacts_path}"
        )
        assert not last.game_over or last.game_over_type == "win", (
            f"Game ended with type={last.game_over_type} (expected no game-over "
            f"or 'win'); see artifact: {result.artifacts_path}"
        )
    else:
        # Player lost: the loss must have been handled gracefully —
        # game-over recorded as a loss, player death logged.
        assert last.game_over and last.game_over_type == "lose", (
            f"Player at {player_hp} HP but game-over is "
            f"{last.game_over_type!r} (expected 'lose'); "
            f"see artifact: {result.artifacts_path}"
        )
        player_death_logged = any(
            entry.get("actor") == "player" and entry.get("action") == "death"
            for t in result.turns
            for entry in t.combat_log
        )
        assert player_death_logged, (
            "Player died but no 'death' combat-log entry for the player; "
            f"see artifact: {result.artifacts_path}"
        )


def combat_log_entries(result, *, actor=None, action=None):
    """Yield all combat-log entries across turns, filtered by actor/action."""
    for t in result.turns:
        for entry in t.combat_log:
            if actor is not None and entry.get("actor") != actor:
                continue
            if action is not None and entry.get("action") != action:
                continue
            yield entry
