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
from mgmai.engine.event_bus import reset_disabled_once

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="Run live-LLM integration tests (requires MGMAI_API_KEY)",
    )
    parser.addoption(
        "--driver-model",
        default=None,
        help="Model name for the driver LLM in integration tests",
    )
    parser.addoption(
        "--judge-model",
        default=None,
        help="Model name for the judge LLM in integration tests",
    )
    parser.addoption(
        "--gm-model",
        default=None,
        help="Model name for the GM LLM in integration tests",
    )


def pytest_collection_modifyitems(config, items):
    """Skip llm-marked tests unless the user explicitly opts in.

    Opt-in paths:
      - targeting ``tests/integration`` explicitly, OR
      - passing ``-m llm`` (or any marker expr mentioning ``llm``), OR
      - passing ``--run-llm``

    This keeps the default ``pytest`` invocation fast and free of API
    costs while preserving the plan's stated UX of
    ``pytest tests/integration`` running the integration suite.
    """
    args = [str(a) for a in (config.args or [])]
    targeting_integration = any("tests/integration" in a for a in args)
    marker_expr = config.getoption("-m") or ""
    opted_in = (
        targeting_integration
        or "llm" in marker_expr
        or config.getoption("--run-llm")
    )
    if opted_in:
        return
    skip_llm = pytest.mark.skip(
        reason="LLM integration test; run with `pytest tests/integration`"
    )
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)


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
    manager._adventure_dir = FIXTURES_DIR
    manager._init_contains_from_corpus()
    reset_disabled_once()
    return manager
