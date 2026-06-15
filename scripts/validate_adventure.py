#!/usr/bin/env python3
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

"""Adventure validation tool.

Loads a corpus + state files and runs validation checks without starting
the game or requiring an LLM. Useful for adventure authors to catch
structural problems before play-testing.

Usage:
    python scripts/validate_adventure.py <adventure_directory>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

parent = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent))

from mgmai.state.manager import StateManager


def validate_adventure(adventure_dir: Path) -> list[str]:
    """Load and validate an adventure directory.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    # 1. Required files exist
    corpus_path = adventure_dir / "corpus.json"
    hard_path = adventure_dir / "hard-state.json"
    soft_path = adventure_dir / "soft-state.json"

    for required, label in (
        (corpus_path, "corpus.json"),
        (hard_path, "hard-state.json"),
        (soft_path, "soft-state.json"),
    ):
        if not required.is_file():
            errors.append(f"Missing required file: {label}")

    if errors:
        return errors

    # 2. Load and validate via StateManager
    state_manager = StateManager()
    try:
        state_manager.load_all(adventure_dir)
    except ValueError as e:
        errors.append(f"Cross-reference validation failed: {e}")
        return errors
    except Exception as e:
        errors.append(f"Failed to load adventure: {e}")
        return errors

    corpus = state_manager.corpus
    hard = state_manager.hard_state
    if corpus is None or hard is None:
        errors.append("State loaded but corpus or hard state is None")
        return errors

    # 3. Adventure metadata checks
    adv = corpus.adventure
    if not adv.title or not adv.title.strip():
        errors.append("Adventure title is empty")
    if not adv.id or not adv.id.strip():
        errors.append("Adventure id is empty (recommended for save/load safety)")
    if not adv.introduction or not adv.introduction.strip():
        errors.append("Adventure introduction is empty")

    # 4. Start room exists and is marked
    start_rooms = [
        rid for rid, room in corpus.rooms.items() if room.is_start_room
    ]
    if len(start_rooms) == 0:
        errors.append("No room is marked as is_start_room")
    elif len(start_rooms) > 1:
        errors.append(f"Multiple rooms marked as start: {start_rooms}")

    if hard.player.location not in corpus.rooms:
        errors.append(
            f"Player location '{hard.player.location}' is not a valid room"
        )

    # 5. Exit target validation (cross-reference)
    for room_id, room in corpus.rooms.items():
        for ex in room.exits:
            if ex.target_room not in corpus.rooms:
                errors.append(
                    f"Room '{room_id}' exit '{ex.id}' targets unknown room: "
                    f"'{ex.target_room}'"
                )

    # 6. Orphaned entities (not present in any room and not in player inventory)
    referenced_entities = set(hard.player.inventory)
    for room in corpus.rooms.values():
        referenced_entities.update(room.entities_present)

    # Collect entity IDs that can be dynamically added by interactions
    addable_entities: set[str] = set()
    for room in corpus.rooms.values():
        for inter in room.interactions:
            if inter.result and inter.result.add_item:
                addable_entities.add(inter.result.add_item)
            if inter.success and inter.success.add_item:
                addable_entities.add(inter.success.add_item)
            if inter.failure and inter.failure.add_item:
                addable_entities.add(inter.failure.add_item)
    for entity in corpus.entities.values():
        for inter in entity.interactions:
            if inter.result and inter.result.add_item:
                addable_entities.add(inter.result.add_item)
            if inter.success and inter.success.add_item:
                addable_entities.add(inter.success.add_item)
            if inter.failure and inter.failure.add_item:
                addable_entities.add(inter.failure.add_item)

    for entity_id, entity in corpus.entities.items():
        if entity_id in referenced_entities:
            continue
        if entity_id == "player":
            continue
        if entity_id in addable_entities:
            continue
        errors.append(
            f"Entity '{entity_id}' is not present in any room, player inventory, "
            f"or interaction result"
        )

    # 7. Room connectivity — all rooms reachable from start room via exits
    if start_rooms:
        start = start_rooms[0]
        reachable = _find_reachable_rooms(start, corpus)
        all_rooms = set(corpus.rooms.keys())
        unreachable = all_rooms - reachable
        if unreachable:
            errors.append(
                f"Rooms unreachable from start room '{start}': {sorted(unreachable)}"
            )

    # 8. Interaction references
    for room_id, room in corpus.rooms.items():
        for inter in room.interactions:
            if inter.check is not None and inter.success is None:
                errors.append(
                    f"Room '{room_id}' interaction '{inter.id}' has check but no success branch"
                )

    for entity_id, entity in corpus.entities.items():
        for inter in entity.interactions:
            if inter.check is not None and inter.success is None:
                errors.append(
                    f"Entity '{entity_id}' interaction '{inter.id}' has check but no success branch"
                )

    # 9. Mechanics validation
    for mech_id, mech in corpus.mechanics.items():
        if mech.type is not None and mech.type not in ("win", "lose"):
            errors.append(
                f"Mechanic '{mech_id}' has invalid type '{mech.type}' (expected 'win' or 'lose')"
            )

    # 10. CombatBlock validation
    from mgmai.engine.combat import parse_damage_dice
    for entity_id, entity in corpus.entities.items():
        if entity.combat is None:
            continue
        cb = entity.combat
        if cb.hp <= 0:
            errors.append(
                f"Entity '{entity_id}' CombatBlock.hp must be positive, got {cb.hp}"
            )
        if cb.ac < 0:
            errors.append(
                f"Entity '{entity_id}' CombatBlock.ac must be non-negative, got {cb.ac}"
            )
        try:
            parse_damage_dice(cb.dmg)
        except ValueError:
            errors.append(
                f"Entity '{entity_id}' CombatBlock.dmg is not a valid damage "
                f"expression: '{cb.dmg}'"
            )
        if "current_hp" not in entity.state_fields:
            errors.append(
                f"Entity '{entity_id}' has CombatBlock but no 'current_hp' "
                f"declared in state_fields"
            )
        # Check current_hp is initialized in hard state
        if entity_id in hard.entity_states:
            if "current_hp" not in hard.entity_states[entity_id]:
                errors.append(
                    f"Entity '{entity_id}' has CombatBlock but 'current_hp' is "
                    f"not set in hard-state.json"
                )

    return errors


def _find_reachable_rooms(start_room: str, corpus) -> set[str]:
    """BFS to find all rooms reachable from the start room."""
    visited: set[str] = set()
    queue = [start_room]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        room = corpus.rooms.get(current)
        if room is None:
            continue
        for ex in room.exits:
            if ex.target_room not in visited:
                queue.append(ex.target_room)
    return visited


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an MGMAI adventure directory"
    )
    parser.add_argument(
        "adventure",
        help="Path to adventure directory (must contain corpus.json, hard-state.json, soft-state.json)",
    )
    args = parser.parse_args()

    adventure_dir = Path(args.adventure)
    if not adventure_dir.is_dir():
        print(f"Error: Not a directory: {adventure_dir}")
        sys.exit(1)

    print(f"Validating adventure: {adventure_dir}")
    errors = validate_adventure(adventure_dir)

    if errors:
        print(f"\nFound {len(errors)} issue(s):")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        sys.exit(1)
    else:
        print("\nAll checks passed. Adventure is valid.")


if __name__ == "__main__":
    main()
