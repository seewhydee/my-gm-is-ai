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

"""Tests for scripts/validate_adventure.py."""

from __future__ import annotations

import copy

from scripts.validate_adventure import _validate_ids


class TestValidateIds:
    """Reserved-ID and room/entity disjointness checks."""

    def test_clean_corpus_has_no_id_errors(self, sample_corpus) -> None:
        assert _validate_ids(sample_corpus) == []

    def test_room_entity_collision_detected(self, sample_corpus) -> None:
        """An ID used as both a room and an entity is flagged."""
        corpus = copy.deepcopy(sample_corpus)
        # Reuse an arbitrary entity object under a room's ID.
        room_id = next(iter(corpus.rooms))
        corpus.entities[room_id] = next(iter(corpus.entities.values()))

        errors = _validate_ids(corpus)
        assert any("mutually disjoint" in e for e in errors)
        assert any(room_id in e for e in errors)

    def test_reserved_current_room_as_room(self, sample_corpus) -> None:
        corpus = copy.deepcopy(sample_corpus)
        corpus.rooms["current_room"] = next(iter(corpus.rooms.values()))

        errors = _validate_ids(corpus)
        assert any("Room ID 'current_room' is reserved" in e for e in errors)

    def test_reserved_current_room_as_entity(self, sample_corpus) -> None:
        corpus = copy.deepcopy(sample_corpus)
        corpus.entities["current_room"] = next(iter(corpus.entities.values()))

        errors = _validate_ids(corpus)
        assert any("Entity ID 'current_room' is reserved" in e for e in errors)
