import json
from pathlib import Path

import pytest

from mgmai.models.corpus import ModuleCorpus

ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"


@pytest.fixture(scope="session")
def sample_corpus_dict() -> dict:
    path = ADVENTURES_DIR / "bag-of-holding" / "corpus.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def sample_corpus(sample_corpus_dict: dict) -> ModuleCorpus:
    return ModuleCorpus.model_validate(sample_corpus_dict)
