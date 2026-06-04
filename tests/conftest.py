import json
from pathlib import Path

import pytest

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


@pytest.fixture(scope="session")
def sample_corpus_dict() -> dict:
    path = BAG_OF_HOLDING / "corpus.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def sample_corpus(sample_corpus_dict: dict) -> ModuleCorpus:
    return ModuleCorpus.model_validate(sample_corpus_dict)


@pytest.fixture(scope="session")
def sample_hard_state() -> HardGameState:
    path = BAG_OF_HOLDING / "hard-state.json"
    return HardGameState.model_validate(json.loads(path.read_text()))


@pytest.fixture(scope="session")
def sample_soft_state() -> SoftGameState:
    path = BAG_OF_HOLDING / "soft-state.json"
    return SoftGameState.model_validate(json.loads(path.read_text()))
