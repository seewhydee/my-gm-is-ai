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


def _collect_addable_from_result(result, addable_entities: set[str]) -> None:
    if result is None:
        return
    if result.add_item:
        addable_entities.update(result.add_item)
    if result.add_item_count:
        addable_entities.update(result.add_item_count.keys())


def _collect_status_effect_refs(obj, refs: set[str]) -> None:
    """Recursively collect status-effect IDs referenced by ``apply_status_effect``
    and ``cure_status_effects`` anywhere in a serialized corpus."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "apply_status_effect" and isinstance(val, dict) and "id" in val:
                refs.add(val["id"])
            elif key == "cure_status_effects" and isinstance(val, list):
                refs.update(v for v in val if isinstance(v, str))
            else:
                _collect_status_effect_refs(val, refs)
    elif isinstance(obj, list):
        for item in obj:
            _collect_status_effect_refs(item, refs)


def validate_adventure(adventure_dir: Path) -> tuple[list[str], list[str]]:
    """Load and validate an adventure directory.

    Returns a ``(errors, warnings)`` pair.  Errors are structural
    problems; warnings are suspicious but legal (e.g. references to
    condition IDs the adventure may forward-declare).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Required files exist
    corpus_path = adventure_dir / "corpus.json"
    hard_path = adventure_dir / "hard-state.json"
    soft_path = adventure_dir / "soft-state.json"
    default_player_path = adventure_dir / "default-player.json"

    for required, label in (
        (corpus_path, "corpus.json"),
        (soft_path, "soft-state.json"),
    ):
        if not required.is_file():
            errors.append(f"Missing required file: {label}")

    if errors:
        return errors, warnings

    # 2. Load and validate via StateManager.
    #    hard-state.json is optional (world-state override); default-player.json
    #    is required iff the corpus declares a stat system.
    state_manager = StateManager()
    try:
        state_manager.load_all(adventure_dir)
    except ValueError as e:
        errors.append(f"Cross-reference validation failed: {e}")
        return errors, warnings
    except Exception as e:
        errors.append(f"Failed to load adventure: {e}")
        return errors, warnings

    corpus = state_manager.corpus
    hard = state_manager.hard_state
    if corpus is None or hard is None:
        errors.append("State loaded but corpus or hard state is None")
        return errors, warnings

    if corpus.stats is not None and not default_player_path.is_file() and not hard_path.is_file():
        errors.append(
            "Adventure has a stat system but neither default-player.json nor "
            "hard-state.json was found"
        )

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
    referenced_entities.update(hard.player.equipped)
    for room in corpus.rooms.values():
        referenced_entities.update(room.contains)
    # Also consider contains (items nested inside other entities)
    for entity in corpus.entities.values():
        referenced_entities.update(entity.contains)

    # Collect entity IDs that can be dynamically added by interactions
    addable_entities: set[str] = set()
    for room in corpus.rooms.values():
        for inter in room.interactions:
            if inter.result and inter.result.add_item:
                addable_entities.update(inter.result.add_item)
            if inter.success and inter.success.add_item:
                addable_entities.update(inter.success.add_item)
            if inter.failure and inter.failure.add_item:
                addable_entities.update(inter.failure.add_item)
            if inter.result and inter.result.add_item_count:
                addable_entities.update(inter.result.add_item_count.keys())
            if inter.success and inter.success.add_item_count:
                addable_entities.update(inter.success.add_item_count.keys())
            if inter.failure and inter.failure.add_item_count:
                addable_entities.update(inter.failure.add_item_count.keys())
    for entity in corpus.entities.values():
        for inter in entity.interactions:
            if inter.result and inter.result.add_item:
                addable_entities.update(inter.result.add_item)
            if inter.success and inter.success.add_item:
                addable_entities.update(inter.success.add_item)
            if inter.failure and inter.failure.add_item:
                addable_entities.update(inter.failure.add_item)
            if inter.result and inter.result.add_item_count:
                addable_entities.update(inter.result.add_item_count.keys())
            if inter.success and inter.success.add_item_count:
                addable_entities.update(inter.success.add_item_count.keys())
            if inter.failure and inter.failure.add_item_count:
                addable_entities.update(inter.failure.add_item_count.keys())
    # Also check on_examine events' add_item and set_entity_state (unhide)
    for entity in corpus.entities.values():
        for event in entity.on_examine:
            _collect_addable_from_result(event.result, addable_entities)
            _collect_addable_from_result(event.success, addable_entities)
    for room in corpus.rooms.values():
        for event in room.on_examine:
            _collect_addable_from_result(event.result, addable_entities)
            _collect_addable_from_result(event.success, addable_entities)

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

    # 9. CombatBlock validation
    from mgmai.engine.combat import parse_damage_dice
    from mgmai.engine.systems.five_e import FiveESystem
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
        for dt in [cb.dmg_type, *cb.resistances, *cb.vulnerabilities, *cb.immunities]:
            if dt and dt not in FiveESystem.DAMAGE_TYPES:
                errors.append(
                    f"Entity '{entity_id}' has unknown damage type: '{dt}'"
                )
        for atk_def in cb.attacks:
            try:
                parse_damage_dice(atk_def.dmg)
            except ValueError:
                errors.append(
                    f"Entity '{entity_id}' attack '{atk_def.id}' dmg is not a "
                    f"valid damage expression: '{atk_def.dmg}'"
                )
        if "current_hp" not in entity.state_fields:
            errors.append(
                f"Entity '{entity_id}' has CombatBlock but no 'current_hp' "
                f"declared in state_fields"
            )
        ai = cb.ai
        if ai is not None:
            if ai.targeting not in ("last_attacker", "player", "lowest_hp", "random"):
                errors.append(
                    f"Entity '{entity_id}' CombatAIBlock.targeting is invalid: "
                    f"'{ai.targeting}'"
                )
            if ai.flee_below_hp_pct is not None and not (1 <= ai.flee_below_hp_pct <= 99):
                errors.append(
                    f"Entity '{entity_id}' CombatAIBlock.flee_below_hp_pct must "
                    f"be between 1 and 99, got {ai.flee_below_hp_pct}"
                )

    # 10. EquipBlock damage-type validation
    for entity_id, entity in corpus.entities.items():
        eb = entity.equip_block
        if eb is not None and eb.damage_type and eb.damage_type not in FiveESystem.DAMAGE_TYPES:
            errors.append(
                f"Entity '{entity_id}' EquipBlock.damage_type is unknown: "
                f"'{eb.damage_type}'"
            )

    # 11. Ability validation
    for aid, ability in corpus.abilities.items():
        exprs = []
        if ability.attack is not None:
            exprs.append(("attack.damage", ability.attack.damage))
        if ability.save is not None and ability.save.damage:
            exprs.append(("save.damage", ability.save.damage))
        if ability.heal:
            exprs.append(("heal", ability.heal))
        for label, expr in exprs:
            try:
                parse_damage_dice(expr)
            except ValueError:
                errors.append(
                    f"Ability '{aid}' {label} is not a valid damage "
                    f"expression: '{expr}'"
                )
        if corpus.stats is not None:
            stats_used = []
            if ability.attack is not None:
                stats_used.append(ability.attack.stat)
            if ability.save is not None:
                stats_used.append(ability.save.stat)
            for st in stats_used:
                if st not in corpus.stats.definitions:
                    errors.append(
                        f"Ability '{aid}' references unknown stat '{st}'"
                    )
    for entity_id, entity in corpus.entities.items():
        cb = entity.combat
        if cb is None:
            continue
        for aid in cb.abilities:
            if aid not in corpus.abilities:
                errors.append(
                    f"Entity '{entity_id}' references unknown ability '{aid}'"
                )
        if cb.ai is not None:
            for aid in cb.ai.ability_rules:
                if aid not in cb.abilities:
                    errors.append(
                        f"Entity '{entity_id}' has ability_rules for '{aid}' "
                        f"but does not list it in abilities"
                    )

    # 12. Status-effect references (warning only — adventures may
    # forward-declare status-effect IDs; runtime application still works)
    defined_status_effects = set(corpus.effective_status_effects())
    status_effect_refs: set[str] = set()
    _collect_status_effect_refs(corpus.model_dump(), status_effect_refs)
    for effect_id in sorted(status_effect_refs - defined_status_effects):
        warnings.append(
            f"Reference to undefined status effect '{effect_id}' (not in the "
            f"corpus status_effects block or the built-in defaults)"
        )

    return errors, warnings


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
        help="Path to adventure directory (must contain corpus.json and soft-state.json; hard-state.json is optional)",
    )
    args = parser.parse_args()

    adventure_dir = Path(args.adventure)
    if not adventure_dir.is_dir():
        print(f"Error: Not a directory: {adventure_dir}")
        sys.exit(1)

    print(f"Validating adventure: {adventure_dir}")
    errors, warnings = validate_adventure(adventure_dir)

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for i, warn in enumerate(warnings, 1):
            print(f"  {i}. Warning: {warn}")

    if errors:
        print(f"\nFound {len(errors)} issue(s):")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        sys.exit(1)
    else:
        print("\nAll checks passed. Adventure is valid.")


if __name__ == "__main__":
    main()
