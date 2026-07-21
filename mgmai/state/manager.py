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

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

log = logging.getLogger(__name__)

from mgmai.models.corpus import (
    Entity,
    ModuleCorpus,
    RESERVED_ENTITY_STATE_FIELDS,
    RESERVED_ROOM_STATE_FIELDS,
    RESERVED_STATE_FIELD_DEFAULTS,
    StateFieldDecl,
)
from mgmai.models.hard_state import HardGameState, PlayerState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch, TurnHistoryEntry
from mgmai.models.actions import HardStateChanges


class StateNotLoadedError(RuntimeError):
    """Raised when an operation requires state that has not been loaded."""


class StateManager:
    """Loads, validates, holds, and persists game state.

    The StateManager is the single source of truth for the module corpus
    (read-only) and the mutable hard/soft game states.  Per plan.md, the
    engine receives direct references to the state objects and mutates them
    directly; the apply_* helpers here are conveniences for common engine
    operations.  No component other than the engine should modify state.
    """

    def __init__(self, adventure_dir: str | Path | None = None) -> None:
        self.corpus: ModuleCorpus | None = None
        self.hard_state: HardGameState | None = None
        self.soft_state: SoftGameState | None = None
        self._adventure_dir: Path | None = None
        self._config_dir: Path | None = None

        if adventure_dir is not None:
            self.load_all(adventure_dir)

    @property
    def loaded(self) -> bool:
        return all(
            x is not None
            for x in (self.corpus, self.hard_state, self.soft_state)
        )

    # ------------------------------------------------------------------
    # Load helpers
    # ------------------------------------------------------------------

    @staticmethod
    def load_corpus(path: str | Path) -> ModuleCorpus:
        """Load and validate the module corpus from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return ModuleCorpus.model_validate(data)

    @staticmethod
    def load_hard_state(path: str | Path) -> HardGameState:
        """Load and validate hard state from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return HardGameState.model_validate(data)

    @staticmethod
    def load_soft_state(path: str | Path) -> SoftGameState:
        """Load and validate soft state from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return SoftGameState.model_validate(data)

    def load_all(self, adventure_dir: str | Path) -> None:
        """Load corpus and soft state; generate or load hard state.

        If ``hard-state.json`` exists it is used as a world-state override;
        otherwise the initial world state is generated from the corpus.  The
        player block is resolved from ``default-player.json``, the optional
        ``hard-state.json`` player block, and finally ``--char-sheet`` (applied
        externally after ``load_all``).

        Validates cross-references after all files are loaded.
        """
        adventure_dir = Path(adventure_dir)
        self._adventure_dir = adventure_dir

        corpus_path = adventure_dir / "corpus.json"
        hard_path = adventure_dir / "hard-state.json"
        soft_path = adventure_dir / "soft-state.json"

        self.corpus = self.load_corpus(corpus_path)
        self.soft_state = self.load_soft_state(soft_path)

        start_room = self._find_start_room()
        player = self._resolve_player_block(start_room)

        if hard_path.is_file():
            self.hard_state = self.load_hard_state(hard_path)
            # Inject the cascaded player block into the override.
            self.hard_state.player = player
        else:
            self.hard_state = self._init_world_state_from_corpus(start_room)
            self.hard_state.player = player

        # Reset in-memory once-reaction tracking on every reload so that
        # once-reactions are not carried over between saves or tests.
        from mgmai.engine.event_bus import reset_disabled_once

        reset_disabled_once()

        self.validate_cross_references()
        self._validate_start_combat_scope()
        self._validate_stats_system()
        self._validate_player_stats()
        self._init_player_combat_defaults()
        self._init_contains_from_corpus()

    def _find_start_room(self) -> str:
        """Return the id of the unique room marked as the start room."""
        assert self.corpus is not None
        start_rooms = [
            rid for rid, room in self.corpus.rooms.items() if room.is_start_room
        ]
        if len(start_rooms) == 0:
            raise ValueError("No room is marked as is_start_room")
        if len(start_rooms) > 1:
            raise ValueError(f"Multiple rooms marked as start: {start_rooms}")
        return start_rooms[0]

    def _resolve_player_block(self, start_room: str) -> PlayerState:
        """Resolve the player block from default/hard-state sources.

        The cascade (lowest priority first) is:
        1. Base: location = start room; all other fields default/None.
        2. ``default-player.json`` (if present).
        3. ``hard-state.json``'s ``player`` block (if present).

        ``--char-sheet`` is applied afterwards by ``apply_char_sheet()``.
        """
        assert self.corpus is not None
        assert self._adventure_dir is not None

        corpus = self.corpus
        player = PlayerState(location=start_room)

        default_player_path = self._adventure_dir / "default-player.json"
        if default_player_path.is_file():
            try:
                data = json.loads(default_player_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in default-player.json: {e}") from e
            if not isinstance(data, dict):
                raise ValueError("default-player.json must be a JSON object")

            sheet_system = data.get("system")
            if corpus.stats is not None:
                if sheet_system is None:
                    raise ValueError(
                        "default-player.json must specify 'system' matching the "
                        "adventure's RPG system"
                    )
                expected = corpus.stats.system
                if sheet_system != expected:
                    raise ValueError(
                        f"default-player.json system '{sheet_system}' does not match "
                        f"adventure system '{expected}'"
                    )
            else:
                if sheet_system is not None:
                    raise ValueError(
                        "Adventure has no stat system; default-player.json must not "
                        "specify 'system'"
                    )

            if "player" not in data:
                raise ValueError("default-player.json must contain a 'player' object")
            player_overrides = data["player"]
            if not isinstance(player_overrides, dict):
                raise ValueError("'player' must be an object")

            if corpus.stats is None and player_overrides.get("stats") is not None:
                raise ValueError(
                    "Adventure has no stat system; default-player.json must not "
                    "specify 'player.stats'"
                )

            self._merge_player_overrides(player, player_overrides)

        hard_path = self._adventure_dir / "hard-state.json"
        if hard_path.is_file():
            try:
                data = json.loads(hard_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in hard-state.json: {e}") from e
            if isinstance(data, dict):
                player_override = data.get("player")
                if isinstance(player_override, dict):
                    self._merge_player_overrides(player, player_override)

        if corpus.stats is not None and player.stats is None:
            raise ValueError(
                "Scenario requires player data but none was provided "
                "(need default-player.json, hard-state.json player block, or --char-sheet)"
            )

        return player

    def _init_world_state_from_corpus(self, start_room: str) -> HardGameState:
        """Generate the world (non-player) portion of hard state from the corpus."""
        assert self.corpus is not None
        corpus = self.corpus

        room_states: dict[str, dict[str, Any]] = {}
        for rid, room in corpus.rooms.items():
            state: dict[str, Any] = {"visited": False}
            for field_name, decl in room.state_fields.items():
                if field_name in RESERVED_ROOM_STATE_FIELDS:
                    continue
                state[field_name] = self._resolve_initial_value(decl, field_name, None)
                if decl.initial is None and field_name not in RESERVED_STATE_FIELD_DEFAULTS:
                    log.warning(
                        "Room '%s' state field '%s' has no explicit initial; "
                        "using type default",
                        rid,
                        field_name,
                    )
            room_states[rid] = state

        entity_states: dict[str, dict[str, Any]] = {}
        for eid, entity in corpus.entities.items():
            if not entity.state_fields:
                continue
            state = {}
            for field_name, decl in entity.state_fields.items():
                state[field_name] = self._resolve_initial_value(decl, field_name, entity)
                if (
                    decl.initial is None
                    and field_name not in ("current_hp", "hidden")
                    and field_name not in RESERVED_STATE_FIELD_DEFAULTS
                ):
                    log.warning(
                        "Entity '%s' state field '%s' has no explicit initial; "
                        "using type default",
                        eid,
                        field_name,
                    )
            entity_states[eid] = state

        return HardGameState(
            player=PlayerState(location=start_room),
            flags=dict(corpus.flags_initial),
            room_states=room_states,
            entity_states=entity_states,
            turn_count=0,
            game_over=None,
            combat=None,
        )

    def _resolve_initial_value(
        self,
        decl: StateFieldDecl,
        field_name: str,
        entity: Entity | None,
    ) -> Any:
        """Resolve the initial value for a single declared state field."""
        if decl.initial is not None:
            return decl.initial

        # Context-sensitive reserved fields.
        if field_name == "current_hp":
            if entity is not None and entity.combat is not None:
                return entity.combat.hp
            return 0
        if field_name == "hidden":
            return False

        # Reserved fields with constant defaults.
        if field_name in RESERVED_STATE_FIELD_DEFAULTS:
            return RESERVED_STATE_FIELD_DEFAULTS[field_name]

        # Type defaults.
        type_defaults = {"boolean": False, "number": 0, "string": ""}
        return type_defaults[decl.type]

    def apply_char_sheet(self, path: str | Path) -> None:
        """Load and apply a custom player character sheet.

        The sheet must declare its RPG system (matching ``corpus.stats.system``
        when the adventure has one) and may override any field on
        ``PlayerState``. Unknown fields under ``"player"`` are ignored for
        forward compatibility. After merging, the state is fully re-validated.

        Raises:
            StateNotLoadedError: If no state is loaded.
            FileNotFoundError: If the sheet file does not exist.
            ValueError: If the sheet is malformed or incompatible with the
                loaded adventure.
        """
        if not self.loaded:
            raise StateNotLoadedError("State has not been loaded")

        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Character sheet file not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in character sheet: {e}") from e

        self._apply_char_sheet_data(data)

    def _apply_char_sheet_data(self, data: dict[str, Any]) -> None:
        """Apply an already-parsed character sheet dict to the loaded state."""
        if not isinstance(data, dict):
            raise ValueError("Character sheet must be a JSON object")

        assert self.corpus is not None
        assert self.hard_state is not None

        has_stats_system = self.corpus.stats is not None
        sheet_system = data.get("system")

        if has_stats_system:
            if sheet_system is None:
                raise ValueError(
                    "Character sheet must specify 'system' matching the "
                    "adventure's RPG system")
            expected = self.corpus.stats.system
            if sheet_system != expected:
                raise ValueError(
                    f"Character sheet system '{sheet_system}' does not match "
                    f"adventure system '{expected}'")
        else:
            if sheet_system is not None:
                raise ValueError(
                    "Adventure has no stat system; character sheet must not "
                    "specify 'system'")

        if "player" not in data:
            raise ValueError("Character sheet must contain a 'player' object")
        player_overrides = data["player"]
        if not isinstance(player_overrides, dict):
            raise ValueError("'player' must be an object")

        if not has_stats_system and player_overrides.get("stats") is not None:
            raise ValueError(
                "Adventure has no stat system; character sheet must not "
                "specify 'player.stats'")

        self._merge_player_overrides(self.hard_state.player, player_overrides)

        self.validate_cross_references()
        self._validate_start_combat_scope()
        self._validate_stats_system()
        self._validate_player_stats()
        self._init_player_combat_defaults()

    @staticmethod
    def _merge_player_overrides(player: PlayerState, overrides: dict[str, Any]) -> None:
        """Overlay *overrides* onto *player*, ignoring unknown fields."""
        for field, value in overrides.items():
            if field not in PlayerState.model_fields:
                continue  # forward compatibility: ignore unknown fields
            try:
                setattr(player, field, value)
            except ValidationError as e:
                raise ValueError(f"Invalid value for '{field}': {e}") from e

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _collect_corpus_flag_references(self) -> set[str]:
        """Collect every flag id referenced by the corpus."""
        assert self.corpus is not None
        refs: set[str] = set()
        from mgmai.engine.conditions import parse_condition_string
        from mgmai.models.corpus import (
            Checkable,
            ConditionExpression,
            EncounterRule,
            Entity,
            Exit,
            GatedCheck,
            Interaction,
            Mechanic,
            OnExamineEvent,
            Reaction,
            ReactionEffects,
            Result,
            Room,
            UsingResultOverride,
            WillRevealEntry,
        )

        def _from_condition(expr: ConditionExpression | None) -> None:
            if expr is None:
                return
            if expr.require is not None:
                _from_string(expr.require)
            if expr.unless is not None:
                _from_string(expr.unless)
            for field_name in ("any_of", "all_of"):
                items = getattr(expr, field_name)
                if items is not None:
                    for item in items:
                        if isinstance(item, ConditionExpression):
                            _from_condition(item)
                        elif isinstance(item, str):
                            _from_string(item)

        def _from_string(raw: str) -> None:
            try:
                domain, key, _, _ = parse_condition_string(raw)
            except ValueError:
                return
            if domain == "flag":
                refs.add(key)

        def _from_result(result: Result | None) -> None:
            if result is None:
                return
            if result.set_flag:
                refs.update(result.set_flag.keys())
            if result.then_check is not None:
                _from_checkable(result.then_check)

        def _from_checkable(checkable: Checkable | None) -> None:
            if checkable is None:
                return
            if checkable.skip_check_if is not None:
                _from_condition(checkable.skip_check_if)
            if checkable.success is not None:
                _from_result(checkable.success)
            if checkable.failure is not None:
                _from_result(checkable.failure)

        def _from_using_override(override: UsingResultOverride | None) -> None:
            if override is None:
                return
            if override.success is not None:
                _from_result(override.success)
            if override.failure is not None:
                _from_result(override.failure)
            if override.result is not None:
                _from_result(override.result)

        def _from_reaction(reaction: Reaction) -> None:
            _from_condition(reaction.condition)
            if reaction.effect.result is not None:
                _from_result(reaction.effect.result)

        def _from_interaction(interaction: Interaction | OnExamineEvent) -> None:
            _from_condition(interaction.condition)
            if interaction.using_results is not None:
                for override in interaction.using_results.values():
                    _from_using_override(override)
            if interaction.check is not None:
                _from_checkable(interaction)
            elif interaction.result is not None:
                _from_result(interaction.result)

        def _from_encounter_rule(rule: EncounterRule) -> None:
            _from_condition(rule.condition)
            if rule.check is not None:
                _from_checkable(rule)
            elif rule.result is not None:
                _from_result(rule.result)

        def _from_gated_check(gc: GatedCheck | None) -> None:
            if gc is None:
                return
            _from_condition(gc.gating)
            if gc.using_results is not None:
                for override in gc.using_results.values():
                    _from_using_override(override)

        def _from_will_reveal(entry: WillRevealEntry) -> None:
            for raw in entry.conditions:
                _from_string(raw)
            if entry.set_flag:
                refs.update(entry.set_flag.keys())

        def _from_exit(exit: Exit) -> None:
            _from_condition(exit.condition)
            if exit.traversal_check is not None:
                _from_gated_check(exit.traversal_check)

        def _from_room(room: Room) -> None:
            for exit in room.exits:
                _from_exit(exit)
            for interaction in room.interactions:
                _from_interaction(interaction)
            for event in room.on_examine:
                _from_interaction(event)
            for reaction in room.reactions:
                _from_reaction(reaction)

        def _from_entity(entity: Entity) -> None:
            for interaction in entity.interactions:
                _from_interaction(interaction)
            for event in entity.on_examine:
                _from_interaction(event)
            if entity.dialogue is not None:
                for path in entity.dialogue.dialogue_paths.values():
                    _from_interaction(path)
                for entry in entity.dialogue.will_reveal.values():
                    _from_will_reveal(entry)
            if entity.aggro is not None:
                for rule in entity.aggro:
                    _from_encounter_rule(rule)
            if entity.take_check is not None:
                _from_gated_check(entity.take_check)
            for reaction in entity.reactions:
                _from_reaction(reaction)

        def _from_mechanic(mechanic: Mechanic) -> None:
            _from_condition(mechanic.condition)
            if mechanic.rules is not None:
                for rule in mechanic.rules:
                    _from_encounter_rule(rule)
            for reaction in mechanic.reactions:
                _from_reaction(reaction)

        for room in self.corpus.rooms.values():
            _from_room(room)
        for entity in self.corpus.entities.values():
            _from_entity(entity)
        for mechanic in self.corpus.mechanics.values():
            _from_mechanic(mechanic)
        for goc in self.corpus.game_over_conditions:
            _from_condition(goc.condition)

        return refs

    def validate_cross_references(self) -> None:
        """Run cross-reference checks between corpus and state files."""
        if self.corpus is None or self.hard_state is None or self.soft_state is None:
            raise StateNotLoadedError("Corpus and state must be loaded before validation")

        errors: list[str] = []

        def _check_ids(list_to_validate, valid_ids, id_type):
            for idtag in list_to_validate:
                if idtag not in valid_ids:
                    errors.append(f"No matching {id_type}: {idtag}")

        # Every room and entity in hard_state.room_states must exist in corpus
        _check_ids(self.hard_state.room_states, self.corpus.rooms, "room")
        _check_ids(self.hard_state.entity_states, self.corpus.entities, "entity")

        # Every field in hard_state.entity_states must match declared state_fields
        # (reserved state fields are valid without a declaration).
        for entity_id, state in self.hard_state.entity_states.items():
            if entity_id not in self.corpus.entities:
                # Already reported above; skip field check for unknown entities
                continue
            declared = self.corpus.entities[entity_id].state_fields
            for field_name in state:
                if field_name in RESERVED_ENTITY_STATE_FIELDS:
                    continue
                if field_name not in declared:
                    errors.append(f"Entity '{entity_id}' has undeclared state field: {field_name}")

        # Every field in hard_state.room_states must match declared state_fields
        for room_id, state in self.hard_state.room_states.items():
            if room_id not in self.corpus.rooms:
                # Already reported above; skip field check for unknown rooms
                continue
            declared = self.corpus.rooms[room_id].state_fields
            if not declared:
                continue
            for field_name in state:
                if field_name in RESERVED_ROOM_STATE_FIELDS:
                    continue
                if field_name not in declared:
                    errors.append(f"Room '{room_id}' has undeclared state field: {field_name}")

        # Entities with combat blocks must declare current_hp in state_fields
        for entity_id, entity in self.corpus.entities.items():
            if entity.combat is not None:
                if "current_hp" not in entity.state_fields:
                    errors.append(
                        f"Entity '{entity_id}' has combat block but no "
                        f"'current_hp' in state_fields"
                    )

        # Player location must be a valid room
        if self.hard_state.player.location not in self.corpus.rooms:
            errors.append(f"No matching room: {self.hard_state.player.location}")

        # Inventory items, equipped items, and in-room entities must exist in corpus
        _check_ids(self.hard_state.player.inventory, self.corpus.entities, "entity")
        _check_ids(self.hard_state.player.equipped, self.corpus.entities, "entity")
        for room_id, room in self.corpus.rooms.items():
            _check_ids(room.contains_map.keys(), self.corpus.entities, "entity")

        # Validate corpus containment constraints (non-item count == 1,
        # non-stackable item count == 1, no self-reference, player excluded).
        for room_id, room in self.corpus.rooms.items():
            self._validate_contains_map(room_id, room.contains_map, "room")
        for entity_id, entity in self.corpus.entities.items():
            self._validate_contains_map(entity_id, entity.contains_map, "entity")

        # Validate soft state
        _check_ids(self.soft_state.room_notes,   self.corpus.rooms,    "room")
        _check_ids(self.soft_state.entity_notes, self.corpus.entities, "entity")

        # Validate entity_states attitude fields against corpus attitude_limits
        for entity_id, state in self.hard_state.entity_states.items():
            if "attitude" not in state:
                continue
            entity = self.corpus.entities.get(entity_id)
            if entity is None:
                continue
            if entity.type != "npc":
                errors.append(
                    f"hard_state.entity_states['{entity_id}'] has attitude but "
                    f"entity type is '{entity.type}', not 'npc'")
                continue
            value = state["attitude"]
            guidelines = entity.dialogue
            if guidelines is not None:
                if value < guidelines.attitude_limits.min:
                    errors.append(
                        f"hard_state.entity_states['{entity_id}'].attitude = {value} is below "
                        f"minimum {guidelines.attitude_limits.min}")
                if value > guidelines.attitude_limits.max:
                    errors.append(
                        f"hard_state.entity_states['{entity_id}'].attitude = {value} is above "
                        f"maximum {guidelines.attitude_limits.max}")

        # Validate flags against corpus declaration if provided
        if self.corpus.flags_declared is not None:
            declared_set = set(self.corpus.flags_initial.keys())
            for flag in self.hard_state.flags:
                if flag not in declared_set:
                    errors.append(f"Hard state has undeclared flag {flag}")

        # Cross-check: every flag referenced by the corpus must be declared.
        declared_flags = set(self.corpus.flags_initial.keys())
        declared_flags.update(self.hard_state.flags.keys())
        referenced_flags = self._collect_corpus_flag_references()
        for flag in sorted(referenced_flags - declared_flags):
            errors.append(f"Flag '{flag}' is referenced but not declared")

        # Soft state: player_knowledge entries must reference valid entities/sources
        for entry in self.soft_state.player_knowledge:
            if entry.source_type == "npc_dialogue" and entry.source_id is not None:
                if entry.source_id not in self.corpus.entities:
                    errors.append(f"No matching entity: {entry.source_id}")
                elif self.corpus.entities[entry.source_id].type != "npc":
                    errors.append(f"No matching entity: {entry.source_id}")
                else:
                    guidelines = self.corpus.entities[entry.source_id].dialogue
                    will_reveal = guidelines.will_reveal if guidelines else {}
                    if entry.topic_id not in will_reveal:
                        errors.append(
                            f"NPC '{entry.source_id}' knowledge topic_id "
                            f"'{entry.topic_id}' is not in will_reveal")

        if errors:
            raise ValueError("\n".join(errors))

    def _validate_start_combat_scope(self) -> None:
        """Validate that start_combat only appears on encounter results.

        Also validates referential integrity of explicit combatants and the
        combat_group membership rule (all members must be stat-blocked npcs).
        """
        if self.corpus is None:
            return

        from mgmai.models.corpus import (
            Checkable,
            EncounterRule,
            Entity,
            GatedCheck,
            Interaction,
            Mechanic,
            OnExamineEvent,
            Reaction,
            Resolvable,
            Result,
            Room,
            UsingResultOverride,
        )

        errors: list[str] = []

        def _check_checkable(checkable: Checkable | None, carrier: str, *, allowed: bool) -> None:
            if checkable is None:
                return
            if checkable.success is not None:
                _check_result(checkable.success, carrier, allowed=allowed)
            if checkable.failure is not None:
                _check_result(checkable.failure, carrier, allowed=allowed)

        def _check_result(result: Result | None, carrier: str, *, allowed: bool) -> None:
            if result is None:
                return
            has_combat = result.start_combat is not None
            if has_combat:
                if not allowed:
                    errors.append(
                        f"{carrier}: 'start_combat' is only "
                        f"allowed on encounter-rule results"
                    )
            if result.start_combat is not None:
                for cid in result.start_combat:
                    ent = self.corpus.entities.get(cid)
                    if ent is None:
                        errors.append(
                            f"{carrier}: start_combat entry '{cid}' is not a "
                            f"known entity"
                        )
                    elif ent.combat is None:
                        errors.append(
                            f"{carrier}: start_combat entry '{cid}' "
                            f"does not have a combat block"
                        )
            if result.then_check is not None:
                _check_checkable(result.then_check, carrier, allowed=allowed)

        def _check_using_override(override: UsingResultOverride | None, carrier: str, *, allowed: bool) -> None:
            if override is None:
                return
            _check_result(override.result, carrier, allowed=allowed)
            _check_result(override.success, carrier, allowed=allowed)
            _check_result(override.failure, carrier, allowed=allowed)

        def _check_interaction(interaction: Interaction | OnExamineEvent | Resolvable | None, carrier: str) -> None:
            if interaction is None:
                return
            inter_id = getattr(interaction, "id", None) or "?"
            carrier = f"{carrier} interaction '{inter_id}'"
            if interaction.check is not None:
                _check_checkable(interaction, carrier, allowed=False)
            elif interaction.result is not None:
                _check_result(interaction.result, carrier, allowed=False)
            if getattr(interaction, "using_results", None) is not None:
                for override in interaction.using_results.values():
                    _check_using_override(override, carrier, allowed=False)

        def _check_reaction(reaction: Reaction, carrier: str) -> None:
            effect = reaction.effect
            if effect.result is not None:
                _check_result(
                    effect.result,
                    f"{carrier} reaction '{reaction.id}'",
                    allowed=False,
                )

        def _check_encounter_rule(rule: EncounterRule, encounter_id: str) -> None:
            carrier = f"encounter rule in '{encounter_id}'"
            if rule.check is not None:
                _check_checkable(rule, carrier, allowed=True)
            elif rule.result is not None:
                _check_result(rule.result, carrier, allowed=True)

        def _check_gated_check(gc: GatedCheck | None, carrier: str) -> None:
            if gc is None:
                return
            if gc.using_results is not None:
                for override in gc.using_results.values():
                    _check_using_override(override, carrier, allowed=False)

        def _check_entity(entity: Entity, entity_id: str) -> None:
            for interaction in entity.interactions:
                _check_interaction(interaction, f"entity '{entity_id}'")
            for event in entity.on_examine:
                _check_interaction(event, f"entity '{entity_id}' on_examine")
            if entity.dialogue is not None:
                for path_id, path in entity.dialogue.dialogue_paths.items():
                    _check_interaction(path, f"entity '{entity_id}' dialogue path '{path_id}'")
            if entity.aggro is not None:
                for rule in entity.aggro:
                    _check_encounter_rule(rule, f"entity '{entity_id}' aggro")
            if entity.take_check is not None:
                _check_gated_check(entity.take_check, f"entity '{entity_id}' take_check")
            for reaction in entity.reactions:
                _check_reaction(reaction, f"entity '{entity_id}'")

        def _check_room(room: Room, room_id: str) -> None:
            for interaction in room.interactions:
                _check_interaction(interaction, f"room '{room_id}'")
            for event in room.on_examine:
                _check_interaction(event, f"room '{room_id}' on_examine")
            for reaction in room.reactions:
                _check_reaction(reaction, f"room '{room_id}'")

        def _check_mechanic(mechanic: Mechanic, mechanic_id: str) -> None:
            if mechanic.rules is not None:
                for rule in mechanic.rules:
                    _check_encounter_rule(rule, f"mechanic '{mechanic_id}'")
            for reaction in mechanic.reactions:
                _check_reaction(reaction, f"mechanic '{mechanic_id}'")

        for entity_id, entity in self.corpus.entities.items():
            _check_entity(entity, entity_id)
        for room_id, room in self.corpus.rooms.items():
            _check_room(room, room_id)
        for mechanic_id, mechanic in self.corpus.mechanics.items():
            _check_mechanic(mechanic, mechanic_id)

        # combat_group membership: every member must be an npc with a combat block.
        groups: dict[str, list[str]] = {}
        for eid, entity in self.corpus.entities.items():
            if entity.combat_group is not None:
                groups.setdefault(entity.combat_group, []).append(eid)
        for grp, members in groups.items():
            for eid in members:
                entity = self.corpus.entities[eid]
                if entity.type != "npc":
                    errors.append(
                        f"combat_group '{grp}': member '{eid}' has type "
                        f"'{entity.type}', only 'npc' entities may belong to a combat_group"
                    )
                if entity.combat is None:
                    errors.append(
                        f"combat_group '{grp}': member '{eid}' lacks a combat block"
                    )

        if errors:
            raise ValueError("\n".join(errors))

    def _validate_stats_system(self) -> None:
        """Validate the corpus's declared RPG system against the registry."""
        if self.corpus is None or self.corpus.stats is None:
            return
        from mgmai.engine.systems import get_system
        get_system(self.corpus.stats.system)  # raises ValueError for unknown

    def _validate_player_stats(self) -> None:
        if self.corpus is None or self.hard_state is None:
            return
        corpus = self.corpus
        hard = self.hard_state

        if corpus.stats is None:
            if hard.player.stats is not None:
                raise ValueError("Corpus stats block missing")
            return

        if hard.player.stats is None:
            raise ValueError("Player stats missing")

        for stat_key in hard.player.stats:
            if stat_key not in corpus.stats.definitions:
                raise ValueError(f"Player stat '{stat_key}' is not defined")

        if hard.player.skill_proficiencies:
            from mgmai.engine.systems import get_system_for_corpus

            system = get_system_for_corpus(corpus)
            for skill in hard.player.skill_proficiencies:
                if not system.is_known_check_stat(skill):
                    raise ValueError(
                        f"Player skill proficiency '{skill}' is not a known "
                        f"skill for system '{system.name}'"
                    )

    def _init_player_combat_defaults(self) -> None:
        """Initialise player combat stats (HP, AC, prof) if not already set.

        Uses the active resolution system to derive defaults from ability
        scores when a stats block is present.  Called after every load
        (including character sheet application) so the defaults are
        available from game start, not only on combat entry.
        """
        if self.corpus is None or self.hard_state is None:
            return

        from mgmai.engine.systems import get_system_for_corpus

        hard = self.hard_state
        system = get_system_for_corpus(self.corpus)

        if hard.player.stats:
            if hard.player.max_hp is None:
                hard.player.max_hp = system.compute_player_max_hp(
                    hard, self.corpus
                )
            # AC: cache the intrinsic (pre-gear) base.  The full gear-aware
            # AC is computed by system.compute_player_ac at use time; here we
            # only seed the base from DEX via the system's base_ac primitive.
            if hard.player.ac is None:
                hard.player.ac = system.base_ac(
                    hard.player.stats.get("DEX", 10)
                )
        if hard.player.current_hp is None:
            hard.player.current_hp = system.compute_player_max_hp(
                hard, self.corpus
            )
        if hard.player.max_hp is None:
            hard.player.max_hp = hard.player.current_hp
        if hard.player.proficiency_bonus is None:
            hard.player.proficiency_bonus = 2

    def _validate_singleton_target(
        self,
        eid: str,
        container_kind: str,
        container_id: str,
    ) -> list[str]:
        """Validate shared existence/player/self-containment constraints.

        Called by both corpus containment validation and runtime placement
        validation so the two paths cannot drift on the core rules.
        """
        errors: list[str] = []
        if self.corpus is None:
            return errors
        entity = self.corpus.entities.get(eid)
        if entity is None:
            errors.append(f"No matching entity: {eid}")
            return errors
        if entity.type == "player":
            errors.append(f"Cannot place player entity '{eid}'")
        if container_kind == "entity" and eid == container_id:
            errors.append(f"Entity '{eid}' cannot contain itself")
        return errors

    def _validate_contains_map(
        self,
        owner_id: str,
        contains_map: dict[str, int],
        owner_kind: str,
    ) -> None:
        """Validate a normalised contains map against corpus constraints."""
        errors: list[str] = []
        for eid, count in contains_map.items():
            errors.extend(
                self._validate_singleton_target(eid, owner_kind, owner_id)
            )
            entity = self.corpus.entities.get(eid)
            if entity is None or entity.type == "player":
                continue
            if entity.type != "item" and count != 1:
                errors.append(
                    f"{owner_kind.capitalize()} '{owner_id}' contains non-item entity "
                    f"'{eid}' with count {count}; only items may stack"
                )
                continue
            if entity.type == "item" and "stackable" not in entity.tags and count != 1:
                errors.append(
                    f"{owner_kind.capitalize()} '{owner_id}' contains "
                    f"non-stackable item '{eid}' with count {count}; "
                    f"must be exactly 1"
                )
                continue
        if errors:
            raise ValueError("\n".join(errors))

    def _init_contains_from_corpus(self) -> None:
        """Rebuild runtime containment maps from the corpus.

        Called once at load_all and for legacy saves in load_save.
        """
        if self.corpus is None or self.hard_state is None:
            return
        self.hard_state.room_contains = {
            room_id: dict(room.contains_map)
            for room_id, room in self.corpus.rooms.items()
        }
        self.hard_state.entity_contains = {
            entity_id: dict(entity.contains_map)
            for entity_id, entity in self.corpus.entities.items()
            if entity.contains_map
        }

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_hard_state(self) -> HardGameState:
        """Return the current hard state (direct reference)."""
        if self.hard_state is None:
            raise StateNotLoadedError("Hard state has not been loaded")
        return self.hard_state

    def get_soft_state(self) -> SoftGameState:
        """Return the current soft state (direct reference)."""
        if self.soft_state is None:
            raise StateNotLoadedError("Soft state has not been loaded")
        return self.soft_state

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self, save_dir: str | Path, filename: str = "save.json",
                   latest_narration: str | None = None) -> Path:
        """Serialize hard + soft state (and optional latest narration) to disk.

        Returns the path to the written file.
        """
        if self.hard_state is None or self.soft_state is None:
            raise StateNotLoadedError("State has not been loaded")

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename

        payload: dict[str, Any] = {
            "hard": self.hard_state.model_dump(mode="json"),
            "soft": self.soft_state.model_dump(mode="json"),
        }
        if self._adventure_dir is not None:
            payload["adventure_path"] = str(self._adventure_dir)
        if self.corpus is not None and self.corpus.adventure.id is not None:
            payload["adventure_id"] = self.corpus.adventure.id
        if latest_narration is not None:
            payload["latest_narration"] = latest_narration

        save_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        return save_path

    def save(self, path: str | Path) -> None:
        """Convenience method compatible with StateLoader interface.

        Write a save file at *path*.  The parent directory must exist.
        """
        path = Path(path)
        self.save_state(path.parent, path.name)

    def load_save(self, path: str | Path) -> str:
        """Convenience method compatible with StateLoader interface.

        Load hard + soft state from a save file and re-load the corpus
        from the adventure directory recorded inside the save.  Returns
        the adventure path that was reloaded.

        Raises ValueError if the save's adventure_id does not match the
        loaded corpus.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Save file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        adv_path = data.get("adventure_path")
        save_adventure_id = data.get("adventure_id")
        raw_hard = data.get("hard", {})
        self.hard_state = HardGameState.model_validate(raw_hard)
        self.soft_state = SoftGameState.model_validate(data["soft"])

        if adv_path:
            self._adventure_dir = Path(adv_path)
            corpus_path = self._adventure_dir / "corpus.json"
            if corpus_path.is_file():
                self.corpus = self.load_corpus(corpus_path)
                if save_adventure_id is not None:
                    corpus_id = self.corpus.adventure.id
                    if corpus_id is not None and corpus_id != save_adventure_id:
                        raise ValueError(
                            f"Save file adventure_id '{save_adventure_id}' does not match "
                            f"corpus adventure_id '{corpus_id}'.")

        # Legacy saves predating runtime containment maps are backfilled from
        # the corpus once. Saves written by the new engine always carry these
        # keys, so we only init when absent (not when empty).
        if "room_contains" not in raw_hard:
            self._init_contains_from_corpus()

        # Migrate legacy ``fled`` entity state: remove the ghost from all
        # containment, then drop the key.  Without this migration the removed
        # fled checks would let old ``fled: true`` entities become present.
        for eid, st in self.hard_state.entity_states.items():
            if "fled" not in st:
                continue
            if st.get("fled") is True:
                for contents in self.hard_state.room_contains.values():
                    contents.pop(eid, None)
                for contents in self.hard_state.entity_contains.values():
                    contents.pop(eid, None)
            del st["fled"]

        return adv_path or ""

    # ------------------------------------------------------------------
    # Inventory mutation helpers
    # ------------------------------------------------------------------

    def _validate_contains_delta(
        self,
        container_kind: str,
        container_id: str,
        entries: dict[str, int],
        is_add: bool,
    ) -> list[str]:
        """Validate a world containment delta and return collected errors."""
        errors: list[str] = []
        corpus = self.corpus
        if corpus is None:
            return errors

        if container_kind == "room":
            if container_id not in corpus.rooms:
                errors.append(f"No matching room: {container_id}")
                return errors
        else:
            if container_id not in corpus.entities:
                errors.append(f"No matching entity: {container_id}")
                return errors

        # Determine current counts in the target container.
        if container_kind == "room":
            current = self.hard_state.room_contains.get(container_id, {})
        else:
            current = self.hard_state.entity_contains.get(container_id, {})

        for item_id, count in entries.items():
            if count < 1:
                errors.append(
                    f"Containment delta count for '{item_id}' must be >= 1, got {count}"
                )
                continue
            entity = corpus.entities.get(item_id)
            if entity is None:
                errors.append(f"No matching entity: {item_id}")
                continue
            if entity.type != "item":
                errors.append(
                    f"Only item entities may be placed in containers; '{item_id}' is "
                    f"type '{entity.type}'"
                )
                continue

            stackable = "stackable" in entity.tags
            max_stack = entity.max_stack
            existing = current.get(item_id, 0)

            if is_add:
                new_count = existing + count
                if not stackable and new_count > 1:
                    errors.append(
                        f"Cannot add {count} of non-stackable item '{item_id}' to "
                        f"{container_kind} '{container_id}'"
                    )
                    continue
                if stackable and max_stack is not None and new_count > max_stack:
                    errors.append(
                        f"Cannot add {count} of stackable item '{item_id}' to "
                        f"{container_kind} '{container_id}': would exceed max_stack "
                        f"of {max_stack} (current {existing})"
                    )
                    continue
            else:
                if existing < count:
                    errors.append(
                        f"Cannot remove {count} of '{item_id}' from {container_kind} "
                        f"'{container_id}': only {existing} present"
                    )
                    continue

        return errors

    def _validate_placements(
        self,
        placements: dict[str, str | None],
    ) -> list[str]:
        """Validate direct entity placements derived from ``set_entity_state``.

        Placement is singleton-only (NPCs, features, non-stackable items).
        Values use the qualified prefix ``room:<id>`` or ``entity:<id>``;
        ``None`` means "remove from all containment".
        """
        errors: list[str] = []
        if self.corpus is None:
            return errors

        for eid, loc in placements.items():
            errors.extend(
                self._validate_singleton_target(eid, "room", "")
            )
            entity = self.corpus.entities.get(eid)
            if entity is None or entity.type == "player":
                continue
            if entity.type == "item" and "stackable" in entity.tags:
                errors.append(
                    f"'location' is for singleton entities; '{eid}' is stackable"
                )
                continue
            if loc is None:
                continue
            prefix, _, target = loc.partition(":")
            if prefix == "room":
                if target not in self.corpus.rooms:
                    errors.append(f"No matching room: {target}")
            elif prefix == "entity":
                if target not in self.corpus.entities:
                    errors.append(f"No matching entity: {target}")
                else:
                    errors.extend(
                        self._validate_singleton_target(eid, "entity", target)
                    )
            else:
                errors.append(f"Invalid location value: {loc}")
        return errors

    def _apply_placements(
        self,
        placements: dict[str, str | None],
    ) -> None:
        """Apply direct entity placements to runtime containment maps.

        Set-semantics: remove the entity from all current containers, then
        place it in the target at count 1.  ``None`` simply removes.
        """
        hard = self.hard_state
        for eid, loc in placements.items():
            for contents in hard.room_contains.values():
                contents.pop(eid, None)
            for contents in hard.entity_contains.values():
                contents.pop(eid, None)
            if loc is None:
                continue
            prefix, _, target = loc.partition(":")
            if prefix == "room":
                hard.room_contains.setdefault(target, {})[eid] = 1
            elif prefix == "entity":
                hard.entity_contains.setdefault(target, {})[eid] = 1

    def _apply_contains_deltas(self, changes: HardStateChanges) -> None:
        """Apply the four containment-delta fields to hard state."""
        for room_id, entries in changes.room_contains_added.items():
            target = self.hard_state.room_contains.setdefault(room_id, {})
            for item_id, count in entries.items():
                target[item_id] = target.get(item_id, 0) + count

        for room_id, entries in changes.room_contains_removed.items():
            target = self.hard_state.room_contains.setdefault(room_id, {})
            for item_id, count in entries.items():
                current = target.get(item_id, 0)
                new_count = current - count
                if new_count <= 0:
                    target.pop(item_id, None)
                else:
                    target[item_id] = new_count
            if not target:
                self.hard_state.room_contains.pop(room_id, None)

        for entity_id, entries in changes.entity_contains_added.items():
            target = self.hard_state.entity_contains.setdefault(entity_id, {})
            for item_id, count in entries.items():
                target[item_id] = target.get(item_id, 0) + count

        for entity_id, entries in changes.entity_contains_removed.items():
            target = self.hard_state.entity_contains.setdefault(entity_id, {})
            for item_id, count in entries.items():
                current = target.get(item_id, 0)
                new_count = current - count
                if new_count <= 0:
                    target.pop(item_id, None)
                else:
                    target[item_id] = new_count
            if not target:
                self.hard_state.entity_contains.pop(entity_id, None)

    def _entity_stackable_info(self, item_id: str) -> tuple[bool, int | None]:
        """Return (is_stackable, max_stack) for an item id.

        Unknown items are treated as non-stackable unique items.
        """
        if self.corpus is None or item_id not in self.corpus.entities:
            return False, None
        entity = self.corpus.entities[item_id]
        return "stackable" in entity.tags, entity.max_stack

    def _add_item_to_inventory(self, item_id: str, count: int) -> None:
        """Increment the inventory count for *item_id* by *count*.

        Raises ValueError for duplicate non-stackable items or exceeding
        max_stack for stackable items.
        """
        assert self.hard_state is not None
        inventory = self.hard_state.player.inventory
        stackable, max_stack = self._entity_stackable_info(item_id)
        current = inventory.get(item_id, 0)

        if not stackable:
            if current > 0:
                raise ValueError(
                    f"Cannot add non-stackable item '{item_id}': already in inventory")
            if count > 1:
                raise ValueError(
                    f"Cannot add non-stackable item '{item_id}' with count {count}")
            inventory[item_id] = 1
            return

        new_count = current + count
        if max_stack is not None and new_count > max_stack:
            raise ValueError(
                f"Cannot add {count} of stackable item '{item_id}': "
                f"would exceed max_stack of {max_stack} (current {current})")
        inventory[item_id] = new_count

    def _remove_item_from_inventory(self, item_id: str, count: int) -> None:
        """Decrement the inventory count for *item_id* by *count*.

        Raises ValueError if the inventory has fewer than *count*.
        """
        assert self.hard_state is not None
        inventory = self.hard_state.player.inventory
        current = inventory.get(item_id, 0)
        if count > current:
            raise ValueError(
                f"Cannot remove {count} of '{item_id}': only {current} in inventory")
        new_count = current - count
        if new_count <= 0:
            del inventory[item_id]
        else:
            inventory[item_id] = new_count

    # ------------------------------------------------------------------
    # Mutation helpers (called by the engine)
    # ------------------------------------------------------------------

    def apply_hard_changes(self, changes: HardStateChanges | dict[str, Any]) -> None:
        """Apply a ``HardStateChanges`` object to the current hard state."""
        if self.hard_state is None:
            raise StateNotLoadedError("Hard state has not been loaded")

        if isinstance(changes, dict):
            changes = HardStateChanges.model_validate(changes)

        # Pre-validate all changes so we fail atomically and report every
        # problem at once, matching the style of ``_validate_cross_references``.
        errors: list[str] = []
        corpus = self.corpus

        # ------------------------------------------------------------------
        # Intercept reserved ``location`` in set_entity_state before declared-
        # field validation (location is derived, not declared).  Translate it
        # into direct placements and strip it from the merge dict.  Setting a
        # location on a following entity stops the follow so the derived read
        # matches author intent.
        # ------------------------------------------------------------------
        for entity_id, entity_changes in changes.entity_state_changes.items():
            if "location" not in entity_changes:
                continue
            loc = entity_changes.pop("location")
            changes.entity_placements[entity_id] = loc
            cur = self.hard_state.entity_states.get(entity_id, {})
            if cur.get("following") is True or entity_changes.get("following") is True:
                entity_changes["following"] = False

        # --- room state field validation ---
        for room_id, room_changes in changes.room_state_changes.items():
            if corpus is None or room_id not in corpus.rooms:
                errors.append(f"No matching room: {room_id}")
            else:
                declared = corpus.rooms[room_id].state_fields
                if declared:
                    for field_name in room_changes:
                        if field_name in RESERVED_ROOM_STATE_FIELDS:
                            continue
                        if field_name not in declared:
                            errors.append(f"Room '{room_id}' state change has undeclared field: {field_name}")

        for entity_id, entity_changes in changes.entity_state_changes.items():
            if corpus is None or entity_id not in corpus.entities:
                errors.append(f"No matching entity: {entity_id}")
            else:
                declared = corpus.entities[entity_id].state_fields
                for field_name in entity_changes:
                    if field_name in RESERVED_ENTITY_STATE_FIELDS:
                        continue
                    if field_name not in declared:
                        errors.append(f"Entity '{entity_id}' state change has undeclared field {field_name}")

        for stat_key in changes.stat_modifiers:
            if corpus is None or corpus.stats is None:
                errors.append(f"stat_modifiers references '{stat_key}' but corpus has no stats block")
            elif stat_key not in corpus.stats.definitions:
                errors.append(f"stat_modifiers references undeclared stat: {stat_key}")

        if changes.player_location is not None:
            if corpus is None or changes.player_location not in corpus.rooms:
                errors.append(f"No matching room for player_location: {changes.player_location}")

        # Validate world containment deltas.
        for room_id, entries in changes.room_contains_added.items():
            errors.extend(
                self._validate_contains_delta(
                    "room", room_id, entries, is_add=True
                )
            )
        for room_id, entries in changes.room_contains_removed.items():
            errors.extend(
                self._validate_contains_delta(
                    "room", room_id, entries, is_add=False
                )
            )
        for entity_id, entries in changes.entity_contains_added.items():
            errors.extend(
                self._validate_contains_delta(
                    "entity", entity_id, entries, is_add=True
                )
            )
        for entity_id, entries in changes.entity_contains_removed.items():
            errors.extend(
                self._validate_contains_delta(
                    "entity", entity_id, entries, is_add=False
                )
            )

        # Validate direct placements derived from set_entity_state "location".
        errors.extend(self._validate_placements(changes.entity_placements))

        # Reject changes that target the same entity via both placement and
        # count-delta paths in one call.
        delta_targets: set[str] = set()
        for mapping in (
            changes.room_contains_added,
            changes.room_contains_removed,
            changes.entity_contains_added,
            changes.entity_contains_removed,
        ):
            for entries in mapping.values():
                delta_targets.update(entries)
        for eid in changes.entity_placements:
            if eid in delta_targets:
                errors.append(
                    f"Entity '{eid}' is moved by both 'location' and a "
                    f"containment delta in the same change; use one path"
                )

        if errors:
            raise ValueError("\n".join(errors))

        if changes.player_location is not None:
            self.hard_state.player.location = changes.player_location

        for item_id, count in changes.inventory_added.items():
            self._add_item_to_inventory(item_id, count)

        for item_id, count in changes.inventory_removed.items():
            self._remove_item_from_inventory(item_id, count)

        # Equipment changes: move IDs between inventory and equipped
        for item in changes.equipped_added:
            if item not in self.hard_state.player.equipped:
                self.hard_state.player.equipped.append(item)

        for item in changes.equipped_removed:
            if item in self.hard_state.player.equipped:
                self.hard_state.player.equipped.remove(item)

        for flag, value in changes.flags_set.items():
            self.hard_state.flags[flag] = value

        for flag in changes.flags_cleared:
            if flag in self.hard_state.flags:
                del self.hard_state.flags[flag]

        for room_id, room_changes in changes.room_state_changes.items():
            if room_id not in self.hard_state.room_states:
                self.hard_state.room_states[room_id] = {}
            self.hard_state.room_states[room_id].update(room_changes)

        for entity_id, entity_changes in changes.entity_state_changes.items():
            if entity_id not in self.hard_state.entity_states:
                self.hard_state.entity_states[entity_id] = {}
            self.hard_state.entity_states[entity_id].update(entity_changes)

        if changes.player_hp_delta is not None:
            self.hard_state.player.current_hp = (
                (self.hard_state.player.current_hp or 0) + changes.player_hp_delta
            )

        if changes.stat_modifiers and self.hard_state.player.stats is not None:
            for stat_key, mod in changes.stat_modifiers.items():
                if stat_key in self.hard_state.player.stats:
                    changes.old_stat_values.setdefault(
                        stat_key, self.hard_state.player.stats[stat_key]
                    )
                    if mod.mode == "set":
                        self.hard_state.player.stats[stat_key] = mod.value
                    else:
                        self.hard_state.player.stats[stat_key] += mod.value

        self._apply_contains_deltas(changes)
        self._apply_placements(changes.entity_placements)

    def apply_soft_patches(self, patches: list[SoftStatePatch | dict[str, Any]]) -> None:
        """Apply a list of validated ``SoftStatePatch`` objects to soft state."""
        if self.soft_state is None:
            raise StateNotLoadedError("Soft state has not been loaded")

        for patch in patches:
            if isinstance(patch, dict):
                patch = SoftStatePatch.model_validate(patch)

            field = patch.field
            if field == "room_note":
                # room_note attaches to the player's current room; the
                # validator (engine) ensures the room is valid.
                target = self.hard_state.player.location if self.hard_state else None
                if target is None:
                    raise ValueError("room_note patch requires a loaded hard state")
                if target not in self.soft_state.room_notes:
                    self.soft_state.room_notes[target] = []
                if not isinstance(patch.new_value, str):
                    raise ValueError(f"room_note patch has invalid value {type(patch.new_value).__name__}")
                self.soft_state.room_notes[target].append(patch.new_value)

            elif field == "entity_note":
                target = patch.entity_id
                if target is None:
                    raise ValueError("entity_note patch requires entity_id")
                if target not in self.soft_state.entity_notes:
                    self.soft_state.entity_notes[target] = []
                if not isinstance(patch.new_value, str):
                    raise ValueError(f"entity_note patch has invalid value {type(patch.new_value).__name__}")
                self.soft_state.entity_notes[target].append(patch.new_value)

            elif field == "soft_inventory_add":
                raise ValueError(
                    "soft_inventory_add is deprecated; soft items are now "
                    "adjudicated via soft_item_proposals / soft_item_adjudications"
                )

            elif field == "soft_inventory_remove":
                value = patch.new_value
                if not isinstance(value, str):
                    raise ValueError(f"soft_inventory_remove has invalid value {type(value).__name__}")
                if value in self.soft_state.soft_inventory:
                    self.soft_state.soft_inventory.remove(value)

            elif field == "appearance_note_add":
                if not isinstance(patch.new_value, str):
                    raise ValueError(f"appearance_note_add has invalid value {type(patch.new_value).__name__}")
                self.soft_state.appearance_notes.append(patch.new_value)

            elif field == "set_improvised_weapon":
                from mgmai.models.soft_state import ImprovisedWeapon
                if patch.new_value is None:
                    self.soft_state.improvised_weapon = None
                elif isinstance(patch.new_value, dict):
                    self.soft_state.improvised_weapon = ImprovisedWeapon.model_validate(patch.new_value)
                elif isinstance(patch.new_value, ImprovisedWeapon):
                    self.soft_state.improvised_weapon = patch.new_value
                else:
                    raise ValueError(f"set_improvised_weapon has invalid value type {type(patch.new_value).__name__}")

            else:
                # Should not reach here because SoftStatePatch validates the field,
                # but we keep it for defensiveness.
                raise ValueError(f"Unsupported soft state patch field: {field}")

    def append_turn_history(self, entry: TurnHistoryEntry | dict[str, Any]) -> None:
        """Append a turn log entry to soft state.

        The full turn_history is retained here for save/load and debugging.
        The Context Assembler is responsible for capping at 5 entries when
        building the GMBriefing.
        """
        if self.soft_state is None:
            raise StateNotLoadedError("Soft state has not been loaded")

        if isinstance(entry, dict):
            entry = TurnHistoryEntry.model_validate(entry)

        self.soft_state.turn_history.append(entry)

    def clear_expired_improvised_weapon(self) -> None:
        """Auto-clear improvised weapon if its clears_after_turn is true.

        Called by the engine before each player turn resolution.
        """
        if self.soft_state is None:
            return
        iw = self.soft_state.improvised_weapon
        if iw is not None and iw.clears_after_turn:
            self.soft_state.improvised_weapon = None
