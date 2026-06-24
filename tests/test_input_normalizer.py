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

from __future__ import annotations

import pytest

from mgmai.game.input_normalizer import normalize_player_input


class TestDirectionShortcuts:
    @pytest.mark.parametrize("shortcut,expected", [
        ("n", "go north"),
        ("s", "go south"),
        ("e", "go east"),
        ("w", "go west"),
        ("u", "go up"),
        ("d", "go down"),
    ])
    def test_cardinal_directions(self, shortcut: str, expected: str) -> None:
        assert normalize_player_input(shortcut) == expected

    @pytest.mark.parametrize("shortcut,expected", [
        ("N", "go north"),
        ("S", "go south"),
        ("U", "go up"),
        ("D", "go down"),
    ])
    def test_case_insensitive_directions(self, shortcut: str, expected: str) -> None:
        assert normalize_player_input(shortcut) == expected


class TestExamineShortcut:
    def test_x_alone(self) -> None:
        assert normalize_player_input("x") == "look around"

    def test_x_with_target(self) -> None:
        assert normalize_player_input("x spider") == "examine spider"

    def test_x_with_target_phrase(self) -> None:
        assert normalize_player_input("x rusty key") == "examine rusty key"

    def test_x_case_insensitive(self) -> None:
        assert normalize_player_input("X Spider") == "examine Spider"

    def test_x_extra_whitespace(self) -> None:
        assert normalize_player_input("  x   spider  ") == "examine spider"


class TestTalkShortcut:
    def test_t_with_target(self) -> None:
        assert normalize_player_input("t korbar") == "talk to korbar"

    def test_t_with_target_phrase(self) -> None:
        assert normalize_player_input("t the dwarf") == "talk to the dwarf"

    def test_t_alone_unchanged(self) -> None:
        """"t" alone is not a recognized shortcut form."""
        assert normalize_player_input("t") == "t"


class TestLookShortcut:
    def test_l(self) -> None:
        assert normalize_player_input("l") == "look around"


class TestWaitShortcut:
    def test_z(self) -> None:
        assert normalize_player_input("z") == "wait"


class TestNonShortcutInputs:
    def test_embedded_x_unchanged(self) -> None:
        """The user's specific example: 'x' inside a sentence must not expand."""
        text = "I mark the door with an x"
        assert normalize_player_input(text) == text

    def test_compound_direction_unchanged(self) -> None:
        """Shortcuts only expand on exact forms, not 'go n'."""
        text = "go n"
        assert normalize_player_input(text) == text

    def test_sentence_with_i_unchanged(self) -> None:
        text = "I think I saw something"
        assert normalize_player_input(text) == text

    def test_punctuated_shortcut_unchanged(self) -> None:
        text = "n."
        assert normalize_player_input(text) == text

    def test_hyphenated_x_unchanged(self) -> None:
        text = "x-ray"
        assert normalize_player_input(text) == text

    def test_unknown_input_unchanged(self) -> None:
        text = "frobnicate the widget"
        assert normalize_player_input(text) == text

    def test_empty_string(self) -> None:
        assert normalize_player_input("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_player_input("   ") == "   "
