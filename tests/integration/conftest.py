# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stainlesschicken.com>
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

"""Pytest fixtures for LLM integration tests.

CLI options (``--driver-model``, ``--judge-model``, ``--gm-model``,
``--run-llm``) and the default-skip behaviour for ``llm``-marked tests
live in ``tests/conftest.py`` so they are registered before
collection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mgmai.llm.client import LLMClient
from mgmai.llm.model_config import get_model_config

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def _resolve_model(request, opt_name: str) -> str:
    """Resolve a model name from CLI option or MGMAI_MODEL env var."""
    val = request.config.getoption(opt_name)
    if val:
        return val
    env = os.environ.get("MGMAI_MODEL")
    if not env:
        raise RuntimeError(
            f"No model configured: pass --{opt_name.replace('_', '-')} or set MGMAI_MODEL"
        )
    return env


def _make_client(request, opt_name: str) -> LLMClient:
    api_key = os.environ.get("MGMAI_API_KEY")
    if not api_key:
        pytest.skip("MGMAI_API_KEY not set; skipping LLM integration test")
    model_name = _resolve_model(request, opt_name)
    base_url = os.environ.get("MGMAI_BASE_URL")
    config = get_model_config(model_name, base_url=base_url)
    return LLMClient(api_key=api_key, config=config)


@pytest.fixture
def gm_client(request) -> LLMClient:
    """LLM client for the GM (ruling + prose calls)."""
    return _make_client(request, "--gm-model")


@pytest.fixture
def driver_client(request) -> LLMClient:
    """LLM client for the driver (player)."""
    return _make_client(request, "--driver-model")


@pytest.fixture
def judge_client(request) -> LLMClient:
    """LLM client for the judge."""
    return _make_client(request, "--judge-model")


@pytest.fixture
def artifacts_dir() -> Path:
    """Directory for transcript artifacts (created on demand)."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture
def combat_arena_dir() -> Path:
    """Path to the combat_arena fixture adventure."""
    return FIXTURES_DIR / "combat_arena"
