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

"""Tests for automatic hard-state world generation from the corpus."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mgmai.state.manager import StateManager
from tests.helpers import FIXTURES_DIR, _mk_npc_entity, make_char_sheet_corpus


def _build_corpus():
    """Return a stat-less corpus for testing world-state generation."""
    corpus = make_char_sheet_corpus()
    corpus.stats = None
    return corpus


def _write_and_load(tmp_path: Path, corpus) -> StateManager:
    """Write corpus.json + soft-state.json to a temp dir and load it."""
    work_dir = tmp_path / "adventure"
    work_dir.mkdir()
    shutil.copy(FIXTURES_DIR / "soft-state.json", work_dir / "soft-state.json")
    work_dir.joinpath("corpus.json").write_text(
        corpus.model_dump_json(indent=2), encoding="utf-8"
    )
    sm = StateManager()
    sm.load_all(work_dir)
    return sm


class TestWorldStateGeneration:
    def test_generated_world_state_matches_fixture_override(self, tmp_path: Path) -> None:
        """Removing hard-state.json should produce the same world state as the override."""
        work_dir = tmp_path / "adventure"
        work_dir.mkdir()
        for name in ("corpus.json", "soft-state.json", "default-player.json"):
            shutil.copy(FIXTURES_DIR / name, work_dir / name)

        sm = StateManager()
        sm.load_all(work_dir)

        expected_path = FIXTURES_DIR / "hard-state.json"
        expected = json.loads(expected_path.read_text())

        assert sm.hard_state.flags == expected["flags"]
        assert sm.hard_state.room_states == expected["room_states"]

        # The fixture predates the `hidden` field; generation includes it.
        generated_entities = dict(sm.hard_state.entity_states)
        assert generated_entities["spider"]["hidden"] is False
        del generated_entities["spider"]["hidden"]
        assert generated_entities == expected["entity_states"]

    def test_attitude_initial_from_state_field(self, tmp_path: Path) -> None:
        from mgmai.models.corpus import DialogueGuidelines

        corpus = _build_corpus()
        npc = _mk_npc_entity(
            "npc",
            state_fields={
                "attitude": {"type": "number", "description": "Disposition.", "initial": 3},
            },
        )
        npc.dialogue = DialogueGuidelines(
            guidelines="A test NPC.",
            attitude_limits={"min": -5, "max": 5},
        )
        corpus.entities["npc"] = npc

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.entity_states["npc"]["attitude"] == 3

    def test_current_hp_from_combat(self, tmp_path: Path) -> None:
        from mgmai.models.corpus import CombatBlock

        corpus = _build_corpus()
        corpus.entities["npc"] = _mk_npc_entity(
            "npc",
            state_fields={
                "current_hp": {"type": "number", "description": "HP."},
            },
            combat=CombatBlock(hp=42, ac=10, atk=0, dmg="1d4"),
        )

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.entity_states["npc"]["current_hp"] == 42

    def test_hidden_defaults_to_false(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.entities["npc"] = _mk_npc_entity(
            "npc",
            state_fields={
                "hidden": {"type": "boolean", "description": "Hidden?"},
            },
        )

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.entity_states["npc"]["hidden"] is False

    def test_author_defined_field_falls_back_to_type_default(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.entities["npc"] = _mk_npc_entity(
            "npc",
            state_fields={
                "cursed": {"type": "boolean", "description": "Cursed?"},
                "count": {"type": "number", "description": "Count."},
                "title": {"type": "string", "description": "Title."},
            },
        )

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.entity_states["npc"]["cursed"] is False
        assert sm.hard_state.entity_states["npc"]["count"] == 0
        assert sm.hard_state.entity_states["npc"]["title"] == ""

    def test_explicit_initial_overrides_reserved_default(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.entities["npc"] = _mk_npc_entity(
            "npc",
            state_fields={
                "alive": {"type": "boolean", "initial": False, "description": "Alive?"},
            },
        )

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.entity_states["npc"]["alive"] is False


class TestFlagGeneration:
    def test_plain_strings_start_false(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.flags_declared = ["plain_flag"]

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.flags == {"plain_flag": False}

    def test_dict_entries_start_with_given_value(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.flags_declared = [{"started": True}, {"off": False}]

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.flags == {"started": True, "off": False}

    def test_mixed_entries(self, tmp_path: Path) -> None:
        corpus = _build_corpus()
        corpus.flags_declared = ["plain", {"true_flag": True}]

        sm = _write_and_load(tmp_path, corpus)
        assert sm.hard_state.flags == {"plain": False, "true_flag": True}
