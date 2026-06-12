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

import copy
import json
from pathlib import Path

import pytest

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.state.manager import StateManager

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


@pytest.fixture(scope="session")
def sample_corpus_dict() -> dict:
    path = FIXTURES_DIR / "corpus.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def sample_corpus(sample_corpus_dict: dict) -> ModuleCorpus:
    return ModuleCorpus.model_validate(sample_corpus_dict)


@pytest.fixture(scope="session")
def sample_hard_state() -> HardGameState:
    path = FIXTURES_DIR / "hard-state.json"
    return HardGameState.model_validate(json.loads(path.read_text()))


@pytest.fixture(scope="session")
def sample_soft_state() -> SoftGameState:
    path = FIXTURES_DIR / "soft-state.json"
    return SoftGameState.model_validate(json.loads(path.read_text()))


@pytest.fixture
def state_manager(sample_corpus, sample_hard_state, sample_soft_state):
    """A fresh StateManager with sample data for each test function."""
    manager = StateManager()
    manager.corpus = sample_corpus
    manager.hard_state = copy.deepcopy(sample_hard_state)
    manager.soft_state = copy.deepcopy(sample_soft_state)
    manager._adventure_dir = BAG_OF_HOLDING
    return manager
