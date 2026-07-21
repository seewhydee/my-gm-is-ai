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

"""Tests for the default-player.json cascade."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mgmai.state.manager import StateManager
from tests.helpers import FIXTURES_DIR, make_char_sheet_corpus


class TestDefaultPlayerCascade:
    def test_default_player_supplies_stats(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "5e",
            "player": {
                "stats": {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8},
                "level": 4,
                "max_hp": 27,
                "current_hp": 27,
                "ac": 11,
                "proficiency_bonus": 2,
                "save_proficiencies": ["DEX", "INT"],
            },
        })

        sm = StateManager()
        sm.load_all(work_dir)

        assert sm.hard_state.player.stats is not None
        assert sm.hard_state.player.stats["STR"] == 15
        assert sm.hard_state.player.level == 4
        assert sm.hard_state.player.max_hp == 27

    def test_hard_state_player_overrides_default_player(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "5e",
            "player": {
                "stats": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "level": 1,
                "max_hp": 10,
            },
        })
        _write_hard_state(work_dir, {
            "player": {
                "location": "axe_head",
                "level": 3,
            },
        })

        sm = StateManager()
        sm.load_all(work_dir)

        # hard-state.json overlay takes precedence
        assert sm.hard_state.player.level == 3
        # but stats from default-player.json are preserved
        assert sm.hard_state.player.stats is not None
        assert sm.hard_state.player.stats["STR"] == 10

    def test_char_sheet_overlays_default_player(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "5e",
            "player": {
                "stats": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "level": 2,
                "inventory": {"toenail_sword": 1},
            },
        })

        sm = StateManager()
        sm.load_all(work_dir)
        sm._apply_char_sheet_data({
            "system": "5e",
            "player": {
                "inventory": {"toenail_sword": 2},
            },
        })

        # Partial char-sheet overlays; default-player stats remain.
        assert sm.hard_state.player.stats is not None
        assert sm.hard_state.player.level == 2
        assert sm.hard_state.player.inventory.get("toenail_sword") == 2

    def test_missing_stats_system_in_default_player_raises(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "player": {
                "stats": {"STR": 10},
            },
        })

        sm = StateManager()
        with pytest.raises(ValueError, match="must specify 'system'"):
            sm.load_all(work_dir)

    def test_system_mismatch_raises(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "gurps",
            "player": {"stats": {"STR": 10}},
        })

        sm = StateManager()
        with pytest.raises(ValueError, match="does not match"):
            sm.load_all(work_dir)

    def test_stats_forbidden_when_corpus_has_no_stats(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        corpus.stats = None
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "player": {"stats": {"STR": 10}},
        })

        sm = StateManager()
        with pytest.raises(ValueError, match="no stat system"):
            sm.load_all(work_dir)

    def test_error_when_stats_required_but_no_player_data(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        # No default-player.json and no hard-state.json player block.

        sm = StateManager()
        with pytest.raises(ValueError, match="requires player data"):
            sm.load_all(work_dir)

    def test_statless_adventure_needs_no_default_player(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        corpus.stats = None
        work_dir = _write_corpus(tmp_path, corpus)

        sm = StateManager()
        sm.load_all(work_dir)

        assert sm.hard_state.player.location == "axe_head"
        assert sm.hard_state.player.stats is None

    def test_skill_proficiencies_load(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "5e",
            "player": {
                "stats": {"STR": 10, "DEX": 14, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "skill_proficiencies": ["acrobatics", "Sleight of Hand"],
            },
        })

        sm = StateManager()
        sm.load_all(work_dir)

        assert sm.hard_state.player.skill_proficiencies == [
            "acrobatics", "Sleight of Hand",
        ]

    def test_unknown_skill_proficiency_raises(self, tmp_path: Path) -> None:
        corpus = make_char_sheet_corpus()
        work_dir = _write_corpus(tmp_path, corpus)
        _write_default_player(work_dir, {
            "system": "5e",
            "player": {
                "stats": {"STR": 10, "DEX": 14, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "skill_proficiencies": ["juggling"],
            },
        })

        sm = StateManager()
        with pytest.raises(ValueError, match="not a known skill"):
            sm.load_all(work_dir)


def _write_corpus(tmp_path: Path, corpus) -> Path:
    work_dir = tmp_path / "adventure"
    work_dir.mkdir()
    shutil.copy(FIXTURES_DIR / "soft-state.json", work_dir / "soft-state.json")
    work_dir.joinpath("corpus.json").write_text(
        corpus.model_dump_json(indent=2), encoding="utf-8"
    )
    return work_dir


def _write_default_player(work_dir: Path, data: dict) -> None:
    work_dir.joinpath("default-player.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _write_hard_state(work_dir: Path, data: dict) -> None:
    work_dir.joinpath("hard-state.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
