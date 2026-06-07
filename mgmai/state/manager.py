from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
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

        self._validate_cross_references()
        self._validate_player_stats()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_cross_references(self) -> None:
        """Run cross-reference checks between corpus and state files."""
        if self.corpus is None or self.hard_state is None or self.soft_state is None:
            raise StateNotLoadedError("Corpus and state must be loaded before validation")

        errors: list[str] = []

        # Every room referenced in hard_state.room_states must exist in corpus
        for room_id in self.hard_state.room_states:
            if room_id not in self.corpus.rooms:
                errors.append(
                    f"hard_state.room_states references unknown room: {room_id}"
                )

        # Every entity referenced in hard_state.entity_states must exist in corpus
        for entity_id in self.hard_state.entity_states:
            if entity_id not in self.corpus.entities:
                errors.append(
                    f"hard_state.entity_states references unknown entity: {entity_id}"
                )

        # Every field in hard_state.entity_states must match declared state_fields
        for entity_id, state in self.hard_state.entity_states.items():
            if entity_id not in self.corpus.entities:
                # Already reported above; skip field check for unknown entities
                continue
            declared = self.corpus.entities[entity_id].state_fields
            for field_name in state:
                if field_name not in declared:
                    errors.append(
                        f"Entity '{entity_id}' has undeclared state field: {field_name}"
                    )

        # Player location must be a valid room
        if self.hard_state.player.location not in self.corpus.rooms:
            errors.append(
                f"Player location '{self.hard_state.player.location}' is not a valid room"
            )

        # Inventory items must exist in corpus
        for item_id in self.hard_state.player.inventory:
            if item_id not in self.corpus.entities:
                errors.append(
                    f"Player inventory references unknown entity: {item_id}"
                )

        # Every entity in every room's entities_present must exist in corpus
        for room_id, room in self.corpus.rooms.items():
            for entity_id in room.entities_present:
                if entity_id not in self.corpus.entities:
                    errors.append(
                        f"Room '{room_id}' references unknown entity: {entity_id}"
                    )

        # Soft state: room_notes keys must be valid rooms
        for room_id in self.soft_state.room_notes:
            if room_id not in self.corpus.rooms:
                errors.append(
                    f"soft_state.room_notes references unknown room: {room_id}"
                )

        # Soft state: entity_notes keys must be valid entities
        for entity_id in self.soft_state.entity_notes:
            if entity_id not in self.corpus.entities:
                errors.append(
                    f"soft_state.entity_notes references unknown entity: {entity_id}"
                )

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
                    f"entity type is '{entity.type}', not 'npc'"
                )
                continue
            value = state["attitude"]
            guidelines = entity.dialogue_guidelines
            if guidelines is not None:
                if value < guidelines.attitude_limits.min:
                    errors.append(
                        f"hard_state.entity_states['{entity_id}'].attitude = {value} is below "
                        f"minimum {guidelines.attitude_limits.min}"
                    )
                if value > guidelines.attitude_limits.max:
                    errors.append(
                        f"hard_state.entity_states['{entity_id}'].attitude = {value} is above "
                        f"maximum {guidelines.attitude_limits.max}"
                    )

        # Validate flags against corpus declaration if provided
        if self.corpus.flags_declared is not None:
            declared_set = set(self.corpus.flags_declared)
            for flag in self.hard_state.flags:
                if flag not in declared_set:
                    errors.append(
                        f"hard_state.flags contains undeclared flag: {flag}"
                    )

        # Soft state: npc_revelations keys must be NPC entities
        for npc_id in self.soft_state.npc_revelations:
            if npc_id not in self.corpus.entities:
                errors.append(
                    f"soft_state.npc_revelations references unknown entity: {npc_id}"
                )
            elif self.corpus.entities[npc_id].type != "npc":
                errors.append(
                    f"soft_state.npc_revelations references non-NPC entity: {npc_id}"
                )
            else:
                guidelines = self.corpus.entities[npc_id].dialogue_guidelines
                will_reveal = guidelines.will_reveal if guidelines else {}
                for revelation in self.soft_state.npc_revelations[npc_id]:
                    if isinstance(revelation, dict):
                        topic_id = revelation.get("topic_id")
                    else:
                        topic_id = revelation.topic_id
                    if topic_id not in will_reveal:
                        errors.append(
                            f"NPC '{npc_id}' revelation topic_id "
                            f"'{topic_id}' is not in will_reveal"
                        )

        if errors:
            raise ValueError("\n".join(errors))

    def _validate_player_stats(self) -> None:
        if self.corpus is None or self.hard_state is None:
            return
        corpus = self.corpus
        hard = self.hard_state

        if corpus.stats is None:
            if hard.player.stats is not None:
                raise ValueError(
                    "player.stats is present but corpus has no stats block"
                )
            return

        if hard.player.stats is None:
            raise ValueError(
                "corpus defines stats but player.stats is missing"
            )

        for stat_key in hard.player.stats:
            if stat_key not in corpus.stats.definitions:
                raise ValueError(
                    f"Player stat '{stat_key}' is not defined in corpus.stats.definitions"
                )

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

    def save_state(
        self,
        save_dir: str | Path,
        filename: str = "save.json",
        latest_narration: str | None = None,
    ) -> Path:
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

        save_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
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
                            f"corpus adventure_id '{corpus_id}'."
                        )

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
        for room_id in changes.room_state_changes:
            if corpus is None or room_id not in corpus.rooms:
                errors.append(f"room_state_changes references unknown room: {room_id}")

        for entity_id, entity_changes in changes.entity_state_changes.items():
            if corpus is None or entity_id not in corpus.entities:
                errors.append(
                    f"entity_state_changes references unknown entity: {entity_id}"
                )
            else:
                declared = corpus.entities[entity_id].state_fields
                for field_name in entity_changes:
                    if field_name not in declared:
                        errors.append(
                            f"Entity '{entity_id}' state change has undeclared field: "
                            f"{field_name}"
                        )

        if errors:
            raise ValueError("\n".join(errors))

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
                    raise ValueError(
                        f"room_note patch new_value must be a string, got {type(patch.new_value).__name__}"
                    )
                self.soft_state.room_notes[target].append(patch.new_value)

            elif field == "entity_note":
                target = patch.entity_id
                if target is None:
                    raise ValueError("entity_note patch requires entity_id")
                if target not in self.soft_state.entity_notes:
                    self.soft_state.entity_notes[target] = []
                if not isinstance(patch.new_value, str):
                    raise ValueError(
                        f"entity_note patch new_value must be a string, got {type(patch.new_value).__name__}"
                    )
                self.soft_state.entity_notes[target].append(patch.new_value)

            elif field == "soft_inventory_add":
                if not isinstance(patch.new_value, str):
                    raise ValueError(
                        f"soft_inventory_add patch new_value must be a string, got {type(patch.new_value).__name__}"
                    )
                self.soft_state.soft_inventory.append(patch.new_value)

            elif field == "soft_inventory_remove":
                value = patch.new_value
                if not isinstance(value, str):
                    raise ValueError(
                        f"soft_inventory_remove patch new_value must be a string, got {type(value).__name__}"
                    )
                if value in self.soft_state.soft_inventory:
                    self.soft_state.soft_inventory.remove(value)

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
