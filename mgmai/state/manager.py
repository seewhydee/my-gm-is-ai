from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import (
    DialogueState,
    SoftGameState,
    SoftStatePatch,
    TurnHistoryEntry,
)
from mgmai.models.actions import HardStateChanges


class StateManager:
    """Loads, validates, holds, and persists game state.

    The StateManager is the single source of truth for the module corpus
    (read-only) and the mutable hard/soft game states.  The engine mutates
    state through the dedicated apply_* methods; no other component should
    modify the underlying models directly.
    """

    def __init__(self, adventure_dir: Optional[Union[str, Path]] = None) -> None:
        self.corpus: Optional[ModuleCorpus] = None
        self.hard_state: Optional[HardGameState] = None
        self.soft_state: Optional[SoftGameState] = None
        self._adventure_dir: Optional[Path] = None

        if adventure_dir is not None:
            self.load_all(Path(adventure_dir))

    # ------------------------------------------------------------------
    # Load helpers
    # ------------------------------------------------------------------

    @staticmethod
    def load_corpus(path: Union[str, Path]) -> ModuleCorpus:
        """Load and validate the module corpus from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return ModuleCorpus.model_validate(data)

    @staticmethod
    def load_hard_state(path: Union[str, Path]) -> HardGameState:
        """Load and validate hard state from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return HardGameState.model_validate(data)

    @staticmethod
    def load_soft_state(path: Union[str, Path]) -> SoftGameState:
        """Load and validate soft state from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return SoftGameState.model_validate(data)

    def load_all(self, adventure_dir: Union[str, Path]) -> None:
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

        self._validate_cross_references()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_cross_references(self) -> None:
        """Run cross-reference checks between corpus and state files."""
        if self.corpus is None or self.hard_state is None or self.soft_state is None:
            raise RuntimeError("Corpus and state must be loaded before validation")

        # Every room referenced in hard_state.room_states must exist in corpus
        for room_id in self.hard_state.room_states:
            if room_id not in self.corpus.rooms:
                raise ValueError(
                    f"hard_state.room_states references unknown room: {room_id}"
                )

        # Every entity referenced in hard_state.entity_states must exist in corpus
        for entity_id in self.hard_state.entity_states:
            if entity_id not in self.corpus.entities:
                raise ValueError(
                    f"hard_state.entity_states references unknown entity: {entity_id}"
                )

        # Every field in hard_state.entity_states must match declared state_fields
        for entity_id, state in self.hard_state.entity_states.items():
            declared = self.corpus.entities[entity_id].state_fields
            for field_name in state:
                if field_name not in declared:
                    raise ValueError(
                        f"Entity '{entity_id}' has undeclared state field: {field_name}"
                    )

        # Player location must be a valid room
        if self.hard_state.player.location not in self.corpus.rooms:
            raise ValueError(
                f"Player location '{self.hard_state.player.location}' is not a valid room"
            )

        # Inventory items must exist in corpus
        for item_id in self.hard_state.player.inventory:
            if item_id not in self.corpus.entities:
                raise ValueError(
                    f"Player inventory references unknown entity: {item_id}"
                )

        # Every entity in every room's entities_present must exist in corpus
        for room_id, room in self.corpus.rooms.items():
            for entity_id in room.entities_present:
                if entity_id not in self.corpus.entities:
                    raise ValueError(
                        f"Room '{room_id}' references unknown entity: {entity_id}"
                    )

        # Soft state: room_notes keys must be valid rooms
        for room_id in self.soft_state.room_notes:
            if room_id not in self.corpus.rooms:
                raise ValueError(
                    f"soft_state.room_notes references unknown room: {room_id}"
                )

        # Soft state: entity_notes keys must be valid entities
        for entity_id in self.soft_state.entity_notes:
            if entity_id not in self.corpus.entities:
                raise ValueError(
                    f"soft_state.entity_notes references unknown entity: {entity_id}"
                )

        # Soft state: npc_attitudes keys must be NPC entities
        for npc_id in self.soft_state.npc_attitudes:
            if npc_id not in self.corpus.entities:
                raise ValueError(
                    f"soft_state.npc_attitudes references unknown entity: {npc_id}"
                )
            if self.corpus.entities[npc_id].type != "npc":
                raise ValueError(
                    f"soft_state.npc_attitudes references non-NPC entity: {npc_id}"
                )

        # Soft state: npc_revelations keys must be NPC entities
        for npc_id in self.soft_state.npc_revelations:
            if npc_id not in self.corpus.entities:
                raise ValueError(
                    f"soft_state.npc_revelations references unknown entity: {npc_id}"
                )
            if self.corpus.entities[npc_id].type != "npc":
                raise ValueError(
                    f"soft_state.npc_revelations references non-NPC entity: {npc_id}"
                )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_hard_state(self) -> HardGameState:
        """Return a deep copy of the current hard state."""
        if self.hard_state is None:
            raise RuntimeError("Hard state has not been loaded")
        return self.hard_state.model_copy(deep=True)

    def get_soft_state(self) -> SoftGameState:
        """Return a deep copy of the current soft state."""
        if self.soft_state is None:
            raise RuntimeError("Soft state has not been loaded")
        return self.soft_state.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self, save_dir: Union[str, Path]) -> Path:
        """Serialize hard + soft state to a JSON file in *save_dir*.

        Returns the path to the written file.
        """
        if self.hard_state is None or self.soft_state is None:
            raise RuntimeError("State has not been loaded")

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / "save.json"

        payload: Dict[str, Any] = {
            "hard": json.loads(self.hard_state.model_dump_json()),
            "soft": json.loads(self.soft_state.model_dump_json()),
        }
        if self._adventure_dir is not None:
            payload["adventure_path"] = str(self._adventure_dir)

        save_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return save_path

    # ------------------------------------------------------------------
    # Mutation helpers (called by the engine)
    # ------------------------------------------------------------------

    def apply_hard_changes(self, changes: Union[HardStateChanges, Dict[str, Any]]) -> None:
        """Apply a ``HardStateChanges`` object to the current hard state."""
        if self.hard_state is None:
            raise RuntimeError("Hard state has not been loaded")

        if isinstance(changes, dict):
            changes = HardStateChanges.model_validate(changes)

        if changes.player_location is not None:
            self.hard_state.player.location = changes.player_location

        for item in changes.inventory_added:
            self.hard_state.player.inventory.append(item)

        for item in changes.inventory_removed:
            if item in self.hard_state.player.inventory:
                self.hard_state.player.inventory.remove(item)

        for flag, value in changes.flags_set.items():
            self.hard_state.flags[flag] = value

        for flag in changes.flags_cleared:
            self.hard_state.flags[flag] = False

        for room_id, room_changes in changes.room_state_changes.items():
            if room_id not in self.hard_state.room_states:
                self.hard_state.room_states[room_id] = {}
            self.hard_state.room_states[room_id].update(room_changes)

        for entity_id, entity_changes in changes.entity_state_changes.items():
            if entity_id not in self.hard_state.entity_states:
                self.hard_state.entity_states[entity_id] = {}
            self.hard_state.entity_states[entity_id].update(entity_changes)

    def apply_soft_patches(self, patches: List[Union[SoftStatePatch, Dict[str, Any]]]) -> None:
        """Apply a list of validated ``SoftStatePatch`` objects to soft state."""
        if self.soft_state is None:
            raise RuntimeError("Soft state has not been loaded")

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
                self.soft_state.room_notes[target].append(patch.new_value)

            elif field == "entity_note":
                target = patch.entity_id
                if target is None:
                    raise ValueError("entity_note patch requires entity_id")
                if target not in self.soft_state.entity_notes:
                    self.soft_state.entity_notes[target] = []
                self.soft_state.entity_notes[target].append(patch.new_value)

            elif field == "soft_inventory_add":
                self.soft_state.soft_inventory.append(patch.new_value)

            elif field == "soft_inventory_remove":
                value = patch.new_value
                if value in self.soft_state.soft_inventory:
                    self.soft_state.soft_inventory.remove(value)

            else:
                # Should not reach here because SoftStatePatch validates the field,
                # but we keep it for defensiveness.
                raise ValueError(f"Unsupported soft state patch field: {field}")

    def append_turn_history(self, entry: Union[TurnHistoryEntry, Dict[str, Any]]) -> None:
        """Append a turn log entry to soft state."""
        if self.soft_state is None:
            raise RuntimeError("Soft state has not been loaded")

        if isinstance(entry, dict):
            entry = TurnHistoryEntry.model_validate(entry)

        self.soft_state.turn_history.append(entry)
