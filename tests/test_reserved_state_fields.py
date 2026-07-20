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

"""Tests for reserved entity state fields (alive, hidden, etc.).

Per corpus.md, reserved state fields need NOT be declared in an entity's
``state_fields`` unless the author overrides the default initial value.
These tests pin the engine behavior for undeclared reserved fields:
reads fall back to the documented defaults, and writes are accepted by
state validation.
"""

import pytest

from mgmai.engine.conditions import evaluate_condition_string
from mgmai.models.actions import HardStateChanges
from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    CombatBlock,
    Entity,
    ModuleCorpus,
    Room,
)
from tests.helpers import build_state_manager


def _npc(eid: str, combat: CombatBlock | None = None) -> Entity:
    """An NPC with no declared state fields (all reserved fields undeclared)."""
    return Entity(
        type="npc",
        id=eid,
        description="An NPC.",
        state_fields={},
        combat=combat,
    )


def _corpus(**entities: Entity) -> ModuleCorpus:
    room = Room(
        id="start",
        name="Start",
        description="A room.",
        contains=list(entities),
        is_start_room=True,
    )
    return ModuleCorpus(
        adventure=Adventure(
            title="Test",
            introduction="A test.",
            atmosphere=Atmosphere(setting="test", tone="neutral"),
        ),
        rooms={"start": room},
        entities=entities,
    )


def _eval(raw, sm):
    return evaluate_condition_string(
        raw, sm.hard_state, sm.soft_state, sm.corpus)


class TestReservedFieldReads:
    def test_undeclared_alive_reads_true(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert "alive" not in sm.hard_state.entity_states.get("npc", {})
        assert _eval("entity:npc.alive == true", sm) is True
        assert _eval("entity:npc.alive == false", sm) is False

    def test_undeclared_hidden_reads_false(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert _eval("entity:npc.hidden == false", sm) is True
        assert _eval("entity:npc.hidden == true", sm) is False

    def test_undeclared_attitude_reads_zero(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert _eval("entity:npc.attitude >= 0", sm) is True
        assert _eval("entity:npc.attitude >= 1", sm) is False

    def test_undeclared_following_reads_false(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert _eval("entity:npc.following == false", sm) is True

    def test_undeclared_current_hp_defaults_to_combat_hp(self):
        sm = build_state_manager(
            _corpus(npc=_npc("npc", combat=CombatBlock(
                hp=14, ac=10, atk=2, dmg="1d6"))))
        assert _eval("entity:npc.current_hp == 14", sm) is True
        assert _eval("entity:npc.current_hp <= 0", sm) is False

    def test_unknown_entity_reads_false(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert _eval("entity:ghost.alive == true", sm) is False

    def test_undeclared_custom_field_reads_false(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        assert _eval("entity:npc.cursed == true", sm) is False


class TestReservedFieldWrites:
    def test_set_alive_undeclared_accepted(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"alive": False}}))
        assert sm.hard_state.entity_states["npc"]["alive"] is False
        assert _eval("entity:npc.alive == true", sm) is False
        assert _eval("entity:npc.alive == false", sm) is True

    def test_set_current_hp_undeclared_accepted(self):
        sm = build_state_manager(
            _corpus(npc=_npc("npc", combat=CombatBlock(
                hp=14, ac=10, atk=2, dmg="1d6"))))
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"current_hp": 5}}))
        assert _eval("entity:npc.current_hp == 5", sm) is True

    def test_undeclared_custom_field_rejected(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        with pytest.raises(ValueError, match="undeclared field"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"npc": {"cursed": True}}))

    def test_cross_validation_accepts_reserved_fields(self):
        sm = build_state_manager(_corpus(npc=_npc("npc")))
        sm.hard_state.entity_states["npc"] = {
            "alive": True,
            "hidden": False,
            "attitude": 0,
            "following": False,
            "open": False,
            "current_hp": 0,
        }
        try:
            sm.validate_cross_references()
        except ValueError as e:
            assert "undeclared state field" not in str(e)
