from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState


class StateLoader:
    """Minimal state loader for Phase 7.

    This is a lightweight shim that loads corpus + state from an adventure
    directory.  It will be replaced by the full StateManager in Phase 2.
    """

    def __init__(self, adventure_path: str | Path):
        self.adventure_path = Path(adventure_path)
        self.corpus: Optional[ModuleCorpus] = None
        self.hard_state: Optional[HardGameState] = None
        self.soft_state: Optional[SoftGameState] = None

    @property
    def loaded(self) -> bool:
        return self.corpus is not None and self.hard_state is not None and self.soft_state is not None

    def load(self) -> None:
        if not self.adventure_path.is_dir():
            raise FileNotFoundError(
                f"Adventure directory not found: {self.adventure_path}"
            )

        corpus_file = self.adventure_path / "corpus.json"
        hard_file = self.adventure_path / "hard-state.json"
        soft_file = self.adventure_path / "soft-state.json"

        for f in (corpus_file, hard_file, soft_file):
            if not f.is_file():
                raise FileNotFoundError(f"Missing adventure file: {f}")

        self.corpus = ModuleCorpus.model_validate_json(corpus_file.read_text())
        self.hard_state = HardGameState.model_validate_json(hard_file.read_text())
        self.soft_state = SoftGameState.model_validate_json(soft_file.read_text())

    def save(self, path: str | Path) -> None:
        if not self.loaded:
            raise RuntimeError("Nothing to save: state not loaded")
        out = {
            "adventure_path": str(self.adventure_path),
            "hard": self.hard_state.model_dump(),
            "soft": self.soft_state.model_dump(),
        }
        Path(path).write_text(json.dumps(out, indent=2))

    def load_save(self, path: str | Path) -> str:
        data = json.loads(Path(path).read_text())
        adv_path = data.get("adventure_path", str(self.adventure_path))
        self.adventure_path = Path(adv_path)
        self.hard_state = HardGameState.model_validate(data["hard"])
        self.soft_state = SoftGameState.model_validate(data["soft"])
        self.corpus = ModuleCorpus.model_validate_json(
            (self.adventure_path / "corpus.json").read_text()
        )
        return adv_path
