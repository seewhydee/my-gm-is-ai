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

"""Drift guard for the shared GMBriefing reference.

Both LLM prompts (ruling.j2, prose.j2) document the briefing by including
``briefing_reference.j2``.  These tests make sure that every field of the
Pydantic briefing models stays documented there, so the template cannot
silently drift away from the schema again.
"""

import inspect
from pathlib import Path

from pydantic import BaseModel

import mgmai.models.briefing as briefing_module
from mgmai.models.corpus import DialogueGuidelines

TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "mgmai" / "templates"
)


def _briefing_models() -> list[type[BaseModel]]:
    models = [
        obj
        for _, obj in inspect.getmembers(briefing_module, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel
    ]
    # Embedded verbatim in DialogueActiveNpc.dialogue.
    models.append(DialogueGuidelines)
    return models


def test_every_briefing_field_is_documented() -> None:
    reference = (TEMPLATE_DIR / "briefing_reference.j2").read_text()
    missing = [
        f"{model.__name__}.{field_name}"
        for model in _briefing_models()
        for field_name in model.model_fields
        if f"`{field_name}`" not in reference
    ]
    assert not missing, (
        f"Fields missing from briefing_reference.j2: {missing}"
    )


def test_both_prompts_include_the_reference() -> None:
    for name in ("ruling.j2", "prose.j2"):
        text = (TEMPLATE_DIR / name).read_text()
        assert 'include "briefing_reference.j2"' in text, (
            f"{name} no longer includes briefing_reference.j2"
        )
