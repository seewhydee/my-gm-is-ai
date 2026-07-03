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

from mgmai.models.corpus import ModuleCorpus, RESERVED_ROOM_STATE_FIELDS
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
        """Load corpus, hard state, and soft state from an adventure directory.

        Validates cross-references after all three files are loaded.
        """
        adventure_dir = Path(adventure_dir)
        self._adventure_dir = adventure_dir

        corpus_path = adventure_dir / "corpus.json"
        hard_path = adventure_dir / "hard-state.json"
        soft_path = adventure_dir / "soft-state.json"

        self.corpus = self.load_corpus(corpus_path)
        self.hard_state = self.load_hard_state(hard_path)
        self.soft_state = self.load_soft_state(soft_path)

        # Reset in-memory once-reaction tracking on every reload so that
        # once-reactions are not carried over between saves or tests.
        from mgmai.engine.event_bus import reset_disabled_once

        reset_disabled_once()

        self.validate_cross_references()
        self._validate_stats_system()
        self._validate_player_stats()
        self._init_player_combat_defaults()

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

        for field, value in player_overrides.items():
            if field not in PlayerState.model_fields:
                continue  # forward compatibility: ignore unknown fields
            try:
                setattr(self.hard_state.player, field, value)
            except ValidationError as e:
                raise ValueError(f"Invalid value for '{field}': {e}") from e

        self.validate_cross_references()
        self._validate_stats_system()
        self._validate_player_stats()
        self._init_player_combat_defaults()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

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
        for entity_id, state in self.hard_state.entity_states.items():
            if entity_id not in self.corpus.entities:
                # Already reported above; skip field check for unknown entities
                continue
            declared = self.corpus.entities[entity_id].state_fields
            for field_name in state:
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
            _check_ids(room.contains, self.corpus.entities, "entity")

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
            declared_set = set(self.corpus.flags_declared)
            for flag in self.hard_state.flags:
                if flag not in declared_set:
                    errors.append(f"Hard state has undeclared flag {flag}")

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
        self.hard_state = HardGameState.model_validate(data["hard"])
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

        return adv_path or ""

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

        if errors:
            raise ValueError("\n".join(errors))

        if changes.player_location is not None:
            self.hard_state.player.location = changes.player_location

        for item in changes.inventory_added:
            self.hard_state.player.inventory.append(item)

        for item in changes.inventory_removed:
            if item in self.hard_state.player.inventory:
                self.hard_state.player.inventory.remove(item)

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

    def apply_soft_patches(self, patches: list[SoftStatePatch | dict[str, Any]]) -> None:
        """Apply a list of validated ``SoftStatePatch`` objects to soft state."""
        if self.soft_state is None:
            raise StateNotLoadedError("Soft state has not been loaded")

        for patch in patches:
            if isinstance(patch, dict):
                patch = SoftStatePatch.model_validate(patch)

            field = patch.field
            if field == "room_note":
                target = patch.target_id
                if target is None:
                    raise ValueError("room_note patch requires target_id")
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
                if not isinstance(patch.new_value, str):
                    raise ValueError(f"soft_inventory_add has invalid value {type(patch.new_value).__name__}")
                self.soft_state.soft_inventory.append(patch.new_value)

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
