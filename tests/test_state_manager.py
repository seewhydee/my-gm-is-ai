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

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mgmai.state.manager import StateManager, StateNotLoadedError
from mgmai.models.actions import HardStateChanges
from mgmai.models.corpus import Entity, ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState, SoftStatePatch, TurnHistoryEntry
from tests.helpers import (
    build_state_manager,
    make_char_sheet_corpus,
    make_char_sheet_state,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def manager() -> StateManager:
    return StateManager(FIXTURES_DIR)


class TestLoadAndValidation:
    def test_load_all_success(self) -> None:
        sm = StateManager(FIXTURES_DIR)
        assert sm.corpus is not None
        assert sm.hard_state is not None
        assert sm.soft_state is not None
        assert sm.corpus.adventure.title == "You're Trapped in a Bag of Holding!"
        assert sm.hard_state.player.location == "axe_head"
        assert sm.soft_state.dialogue_state.active_npc is None

    def test_load_individual_methods(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.validate_cross_references()
        assert sm.corpus.rooms["axe_head"].name == "Axe Head"

    def test_invalid_player_location(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.player.location = "nonexistent_room"
        with pytest.raises(ValueError, match="No matching room"):
            sm.validate_cross_references()

    def test_invalid_inventory_item(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.player.inventory["magic_wand"] = 1
        with pytest.raises(ValueError, match="No matching entity: "):
            sm.validate_cross_references()

    def test_invalid_room_state_room(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.room_states["void"] = {"visited": False}
        with pytest.raises(ValueError, match="No matching room: "):
            sm.validate_cross_references()

    def test_invalid_entity_state_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.entity_states["ghost"] = {"alive": True}
        with pytest.raises(ValueError, match="No matching entity"):
            sm.validate_cross_references()

    def test_undeclared_entity_state_field(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.entity_states["spider"]["magic_level"] = 9000
        with pytest.raises(ValueError, match="undeclared state field"):
            sm.validate_cross_references()

    def test_invalid_room_note_room(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.soft_state.room_notes["void"] = ["spooky"]
        with pytest.raises(ValueError, match="No matching room"):
            sm.validate_cross_references()

    def test_invalid_entity_note_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.soft_state.entity_notes["ghost"] = ["spooky"]
        with pytest.raises(ValueError, match="No matching entity: "):
            sm.validate_cross_references()

    def test_invalid_npc_attitudes_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.entity_states["battleaxe"] = {"attitude": 5}
        with pytest.raises(ValueError, match="not 'npc'"):
            sm.validate_cross_references()

    def test_npc_attitude_below_min(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        # korbar's attitude_limits.min is -5 in the sample corpus
        sm.hard_state.entity_states["korbar"]["attitude"] = -10
        with pytest.raises(ValueError, match="below minimum"):
            sm.validate_cross_references()

    def test_npc_attitude_above_max(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        # korbar's attitude_limits.max is 10 in the sample corpus
        sm.hard_state.entity_states["korbar"]["attitude"] = 15
        with pytest.raises(ValueError, match="above maximum"):
            sm.validate_cross_references()

    def test_invalid_player_knowledge_non_npc(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        from mgmai.models.soft_state import KnowledgeEntry
        sm.soft_state.player_knowledge = [
            KnowledgeEntry(
                topic_id="padlock_mechanism",
                description="test",
                source_type="npc_dialogue",
                source_id="battleaxe",
                turn_learned=1,
            ),
        ]
        with pytest.raises(ValueError, match="No matching entity: "):
            sm.validate_cross_references()

    def test_invalid_player_knowledge_topic(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        from mgmai.models.soft_state import KnowledgeEntry
        sm.soft_state.player_knowledge = [
            KnowledgeEntry(
                topic_id="fake_topic",
                description="Fake",
                source_type="npc_dialogue",
                source_id="korbar",
                turn_learned=1,
            ),
        ]
        with pytest.raises(ValueError, match="not in will_reveal"):
            sm.validate_cross_references()

    def test_multiple_errors_collected(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(FIXTURES_DIR / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(FIXTURES_DIR / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(FIXTURES_DIR / "soft-state.json")
        sm.hard_state.player.location = "bad_room"
        sm.hard_state.room_states["bad_room2"] = {}
        with pytest.raises(ValueError) as exc_info:
            sm.validate_cross_references()
        msg = str(exc_info.value)
        assert "bad_room" in msg
        assert "bad_room2" in msg


class TestGetState:
    def test_get_hard_state_is_direct_reference(self, manager: StateManager) -> None:
        snapshot = manager.get_hard_state()
        manager.hard_state.player.location = "bag_floor"
        assert snapshot.player.location == "bag_floor"

    def test_get_soft_state_is_direct_reference(self, manager: StateManager) -> None:
        snapshot = manager.get_soft_state()
        manager.soft_state.soft_inventory.append("rock")
        assert "rock" in snapshot.soft_inventory

    def test_get_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Hard state has not been loaded"):
            sm.get_hard_state()
        with pytest.raises(StateNotLoadedError, match="Soft state has not been loaded"):
            sm.get_soft_state()


class TestApplyHardChanges:
    def test_player_location(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(player_location="bag_floor"))
        assert manager.hard_state.player.location == "bag_floor"

    def test_inventory_add(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(inventory_added={"toenail_sword": 1}))
        assert "toenail_sword" in manager.hard_state.player.inventory
        assert manager.hard_state.player.inventory["toenail_sword"] == 1

    def test_inventory_remove(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = {"rusty_key": 1, "toenail_sword": 1}
        manager.apply_hard_changes(HardStateChanges(inventory_removed={"rusty_key": 1}))
        assert "rusty_key" not in manager.hard_state.player.inventory
        assert "toenail_sword" in manager.hard_state.player.inventory

    def test_inventory_remove_missing_raises(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = {}
        with pytest.raises(ValueError, match="Cannot remove"):
            manager.apply_hard_changes(HardStateChanges(inventory_removed={"missing": 1}))

    def test_inventory_add_quantity(self, manager: StateManager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.apply_hard_changes(HardStateChanges(inventory_added={"gold_coin": 5}))
        assert manager.hard_state.player.inventory["gold_coin"] == 5

    def test_inventory_add_quantity_to_existing(self, manager: StateManager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.hard_state.player.inventory["gold_coin"] = 5
        manager.apply_hard_changes(HardStateChanges(inventory_added={"gold_coin": 3}))
        assert manager.hard_state.player.inventory["gold_coin"] == 8

    def test_inventory_remove_quantity(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = {"gold_coin": 5}
        manager.apply_hard_changes(HardStateChanges(inventory_removed={"gold_coin": 3}))
        assert manager.hard_state.player.inventory["gold_coin"] == 2

    def test_inventory_non_stackable_duplicate_raises(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = {"toenail_sword": 1}
        with pytest.raises(ValueError, match="Cannot add non-stackable"):
            manager.apply_hard_changes(HardStateChanges(inventory_added={"toenail_sword": 1}))

    def test_inventory_max_stack_cap_raises(self, manager: StateManager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.corpus.entities["gold_coin"].max_stack = 10
        manager.hard_state.player.inventory = {"gold_coin": 8}
        with pytest.raises(ValueError, match="max_stack"):
            manager.apply_hard_changes(HardStateChanges(inventory_added={"gold_coin": 5}))

    def test_inventory_remove_shortfall_raises(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = {"gold_coin": 2}
        with pytest.raises(ValueError, match="Cannot remove"):
            manager.apply_hard_changes(HardStateChanges(inventory_removed={"gold_coin": 5}))

    def test_flags_set(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(flags_set={"spider_fled": True}))
        assert manager.hard_state.flags["spider_fled"] is True

    def test_flags_set_creates_new_flag(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(flags_set={"new_dynamic_flag": True}))
        assert manager.hard_state.flags["new_dynamic_flag"] is True

    def test_flags_cleared(self, manager: StateManager) -> None:
        manager.hard_state.flags["injured"] = True
        manager.apply_hard_changes(HardStateChanges(flags_cleared=["injured"]))
        assert "injured" not in manager.hard_state.flags

    def test_flags_cleared_unknown_is_noop(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(flags_cleared=["nonexistent_flag"]))
        assert "nonexistent_flag" not in manager.hard_state.flags

    def test_room_state_changes(self, manager: StateManager) -> None:
        manager.apply_hard_changes(
            HardStateChanges(room_state_changes={"axe_head": {"visited": True}})
        )
        assert manager.hard_state.room_states["axe_head"]["visited"] is True

    def test_room_state_changes_new_room(self, manager: StateManager) -> None:
        del manager.hard_state.room_states["secret_compartment"]
        manager.apply_hard_changes(
            HardStateChanges(room_state_changes={"secret_compartment": {"visited": True}})
        )
        assert manager.hard_state.room_states["secret_compartment"]["visited"] is True

    def test_room_state_changes_unknown_room_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValueError, match="No matching room: "):
            manager.apply_hard_changes(
                HardStateChanges(room_state_changes={"void": {"visited": True}})
            )

    def test_entity_state_changes(self, manager: StateManager) -> None:
        manager.apply_hard_changes(
            HardStateChanges(entity_state_changes={"spider": {"hidden": True}})
        )
        assert manager.hard_state.entity_states["spider"]["hidden"] is True

    def test_entity_state_changes_new_entity(self, manager: StateManager) -> None:
        del manager.hard_state.entity_states["korbar"]
        manager.apply_hard_changes(
            HardStateChanges(entity_state_changes={"korbar": {"alive": True}})
        )
        assert manager.hard_state.entity_states["korbar"]["alive"] is True

    def test_entity_state_changes_unknown_entity_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValueError, match="No matching entity: "):
            manager.apply_hard_changes(
                HardStateChanges(entity_state_changes={"ghost": {"alive": True}})
            )

    def test_apply_from_dict(self, manager: StateManager) -> None:
        manager.apply_hard_changes({"player_location": "bag_floor"})
        assert manager.hard_state.player.location == "bag_floor"

    def test_player_location_unknown_room_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValueError, match="No matching room for player_location: "):
            manager.apply_hard_changes(HardStateChanges(player_location="void"))

    def test_entity_state_changes_undeclared_field_raises(
        self, manager: StateManager
    ) -> None:
        with pytest.raises(ValueError, match="undeclared field"):
            manager.apply_hard_changes(
                HardStateChanges(entity_state_changes={"spider": {"magic_level": 9000}})
            )

    def test_room_state_changes_undeclared_field_raises(self) -> None:
        from mgmai.models.corpus import StateFieldDecl
        from tests.helpers import build_state_manager, make_char_sheet_corpus

        corpus = make_char_sheet_corpus()
        corpus.rooms["axe_head"].state_fields = {
            "is_lit": StateFieldDecl(type="boolean", description="Whether the room is lit."),
        }
        sm = build_state_manager(corpus)

        sm.apply_hard_changes(
            HardStateChanges(room_state_changes={"axe_head": {"is_lit": True}})
        )
        assert sm.hard_state.room_states["axe_head"]["is_lit"] is True

        with pytest.raises(ValueError, match="undeclared field"):
            sm.apply_hard_changes(
                HardStateChanges(room_state_changes={"axe_head": {"magic_level": 9000}})
            )

    def test_apply_hard_changes_collects_errors(self, manager: StateManager) -> None:
        with pytest.raises(ValueError) as exc_info:
            manager.apply_hard_changes(
                HardStateChanges(
                    room_state_changes={"void": {"visited": True}},
                    entity_state_changes={"ghost": {"alive": True}},
                )
            )
        msg = str(exc_info.value)
        assert "void" in msg
        assert "ghost" in msg

    def test_apply_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Hard state has not been loaded"):
            sm.apply_hard_changes(HardStateChanges())


class TestApplySoftPatches:
    def test_room_note(self, manager: StateManager) -> None:
        # room_note attaches to the player's current room (axe_head).
        patch = SoftStatePatch(
            field="room_note",
            new_value="The blade gleams.",
            reason="Player polished it.",
        )
        manager.apply_soft_patches([patch])
        assert "The blade gleams." in manager.soft_state.room_notes["axe_head"]

    def test_entity_note(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            entity_id="spider",
            field="entity_note",
            new_value="Left legs are wounded.",
            reason="Player attacked it.",
        )
        manager.apply_soft_patches([patch])
        assert "Left legs are wounded." in manager.soft_state.entity_notes["spider"]

    def test_appearance_note_add(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="appearance_note_add",
            new_value="A loose rock catches the player's eye.",
            reason="Player noticed it.",
        )
        manager.apply_soft_patches([patch])
        assert "A loose rock catches the player's eye." in manager.soft_state.appearance_notes

    def test_soft_inventory_remove(self, manager: StateManager) -> None:
        manager.soft_state.soft_inventory = ["rock", "cork"]
        patch = SoftStatePatch(
            field="soft_inventory_remove",
            new_value="rock",
            reason="Player dropped it.",
        )
        manager.apply_soft_patches([patch])
        assert "rock" not in manager.soft_state.soft_inventory
        assert "cork" in manager.soft_state.soft_inventory

    def test_soft_inventory_remove_missing_is_noop(self, manager: StateManager) -> None:
        manager.soft_state.soft_inventory = []
        patch = SoftStatePatch(
            field="soft_inventory_remove",
            new_value="rock",
            reason="Player dropped it.",
        )
        manager.apply_soft_patches([patch])
        assert manager.soft_state.soft_inventory == []

    def test_entity_note_missing_entity_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValidationError, match="requires entity_id"):
            SoftStatePatch(
                field="entity_note",
                new_value="Something.",
                reason="Test.",
            )

    def test_apply_from_dict(self, manager: StateManager) -> None:
        manager.apply_soft_patches([
            {
                "field": "appearance_note_add",
                "new_value": "A wisp of lint drifts by.",
                "reason": "Player noticed it.",
            }
        ])
        assert "A wisp of lint drifts by." in manager.soft_state.appearance_notes

    def test_apply_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Soft state has not been loaded"):
            sm.apply_soft_patches([])

    def test_room_note_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="room_note",
            new_value=123,
            reason="Test.",
        )
        with pytest.raises(ValueError, match="has invalid value"):
            manager.apply_soft_patches([patch])

    def test_entity_note_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            entity_id="spider",
            field="entity_note",
            new_value={"bad": "value"},
            reason="Test.",
        )
        with pytest.raises(ValueError, match="has invalid value"):
            manager.apply_soft_patches([patch])

    def test_soft_inventory_add_rejected(self, manager: StateManager) -> None:
        with pytest.raises(ValidationError):
            SoftStatePatch(
                field="soft_inventory_add",
                new_value="rock",
                reason="Test.",
            )

    def test_soft_inventory_remove_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="soft_inventory_remove",
            new_value=["list"],
            reason="Test.",
        )
        with pytest.raises(ValueError, match="has invalid value"):
            manager.apply_soft_patches([patch])


class TestAppendTurnHistory:
    def test_append(self, manager: StateManager) -> None:
        entry = TurnHistoryEntry(
            turn=1,
            player_input="Look around.",
            ruled_action={"action_type": "examine", "target": "axe_head"},
            engine_result_summary="Player looked around.",
            flags_changed=[],
            location_after="axe_head",
        )
        manager.append_turn_history(entry)
        assert len(manager.soft_state.turn_history) == 1
        assert manager.soft_state.turn_history[0].turn == 1

    def test_append_from_dict(self, manager: StateManager) -> None:
        manager.append_turn_history({
            "turn": 2,
            "player_input": "Move.",
            "ruled_action": {"action_type": "move", "target": "exit1"},
            "engine_result_summary": "Player moved.",
            "flags_changed": ["flag1"],
            "location_after": "room2",
        })
        assert len(manager.soft_state.turn_history) == 1
        assert manager.soft_state.turn_history[0].location_after == "room2"

    def test_append_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Soft state has not been loaded"):
            sm.append_turn_history({})

    def test_append_multiple(self, manager: StateManager) -> None:
        for i in range(3):
            manager.append_turn_history({
                "turn": i + 1,
                "player_input": f"Action {i}",
                "ruled_action": {"action_type": "wait"},
                "engine_result_summary": "Waited.",
                "flags_changed": [],
                "location_after": "axe_head",
            })
        assert len(manager.soft_state.turn_history) == 3


class TestSaveState:
    def test_save_and_structure(self, manager: StateManager, tmp_path: Path) -> None:
        save_path = manager.save_state(tmp_path)
        assert save_path.exists()
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert "hard" in data
        assert "soft" in data
        assert "adventure_path" in data
        assert data["hard"]["player"]["location"] == "axe_head"
        assert data["soft"]["dialogue_state"]["active_npc"] is None

    def test_save_dir_created(self, manager: StateManager, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "save_dir"
        save_path = manager.save_state(nested)
        assert save_path.exists()

    def test_save_before_load_raises(self, tmp_path: Path) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="State has not been loaded"):
            sm.save_state(tmp_path)

    def test_save_reflects_mutations(self, manager: StateManager, tmp_path: Path) -> None:
        manager.hard_state.player.location = "bag_floor"
        manager.soft_state.soft_inventory.append("rock")
        save_path = manager.save_state(tmp_path)
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert data["hard"]["player"]["location"] == "bag_floor"
        assert "rock" in data["soft"]["soft_inventory"]

    def test_save_with_latest_narration(self, manager: StateManager, tmp_path: Path) -> None:
        save_path = manager.save_state(
            tmp_path, latest_narration="You entered the room."
        )
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert data["latest_narration"] == "You entered the room."

    def test_save_with_custom_filename(self, manager: StateManager, tmp_path: Path) -> None:
        save_path = manager.save_state(tmp_path, filename="slot1.json")
        assert save_path.name == "slot1.json"
        assert save_path.exists()

    def test_save_includes_adventure_id(self, manager: StateManager, tmp_path: Path) -> None:
        assert manager.corpus is not None
        manager.corpus.adventure.id = "bag-of-holding"
        save_path = manager.save_state(tmp_path)
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert data.get("adventure_id") == "bag-of-holding"

    def test_save_no_adventure_id_when_none(self, manager: StateManager, tmp_path: Path) -> None:
        assert manager.corpus is not None
        manager.corpus.adventure.id = None
        save_path = manager.save_state(tmp_path)
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert "adventure_id" not in data

    def test_load_save_validates_adventure_id(self, manager: StateManager, tmp_path: Path) -> None:
        assert manager.corpus is not None
        manager.corpus.adventure.id = "bag-of-holding"
        save_path = manager.save_state(tmp_path)

        # Loading into a fresh manager with the same corpus should succeed
        fresh = StateManager()
        fresh.load_save(save_path)
        assert fresh.hard_state is not None

    def test_load_save_rejects_mismatched_id(self, manager: StateManager, tmp_path: Path) -> None:
        assert manager.corpus is not None
        manager.corpus.adventure.id = "bag-of-holding"
        save_path = manager.save_state(tmp_path)

        # Tamper with the save to change adventure_id
        data = json.loads(save_path.read_text(encoding="utf-8"))
        data["adventure_id"] = "wrong-adventure"
        save_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="does not match"):
            manager.load_save(save_path)

    def test_load_save_backward_compat_no_id(self, manager: StateManager, tmp_path: Path) -> None:
        assert manager.corpus is not None
        manager.corpus.adventure.id = "bag-of-holding"
        save_path = manager.save_state(tmp_path)

        # Remove adventure_id to simulate old save
        data = json.loads(save_path.read_text(encoding="utf-8"))
        del data["adventure_id"]
        save_path.write_text(json.dumps(data), encoding="utf-8")

        # Should load without error
        fresh = StateManager()
        fresh.load_save(save_path)
        assert fresh.hard_state is not None


class TestApplyCharSheet:
    @staticmethod
    def _make_sm() -> StateManager:
        """Build a StateManager with a minimal corpus for char sheet testing."""
        return build_state_manager(
            make_char_sheet_corpus(),
            hard_state=make_char_sheet_state(),
        )

    def test_applies_custom_stats(self) -> None:
        sm = self._make_sm()
        sm._apply_char_sheet_data({
            "system": "5e",
            "player": {
                "stats": {
                    "STR": 18,
                    "DEX": 14,
                    "CON": 12,
                    "INT": 10,
                    "WIS": 8,
                    "CHA": 16,
                }
            }
        })
        assert sm.hard_state.player.stats is not None
        assert sm.hard_state.player.stats["STR"] == 18
        assert sm.hard_state.player.stats["CHA"] == 16

    def test_missing_system_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(ValueError, match="must specify 'system'"):
            sm._apply_char_sheet_data({
                "player": {"stats": {"STR": 18}}
            })

    def test_system_mismatch_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(ValueError, match="does not match"):
            sm._apply_char_sheet_data({
                "system": "gurps",
                "player": {"stats": {"STR": 18}}
            })

    def test_unknown_stat_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(ValueError, match="not defined"):
            sm._apply_char_sheet_data({
                "system": "5e",
                "player": {"stats": {"STR": 18, "LUCK": 10}}
            })

    def test_generic_merge_location_and_inventory(self) -> None:
        sm = self._make_sm()
        sm._apply_char_sheet_data({
            "system": "5e",
            "player": {
                "location": "bag_floor",
                "inventory": {"toenail_sword": 1},
                "stats": {
                    "STR": 15,
                    "DEX": 14,
                    "CON": 13,
                    "INT": 10,
                    "WIS": 8,
                    "CHA": 12,
                }
            }
        })
        assert sm.hard_state.player.location == "bag_floor"
        assert "toenail_sword" in sm.hard_state.player.inventory
        assert sm.hard_state.player.stats["STR"] == 15

    def test_invalid_location_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(ValueError, match="No matching room"):
            sm._apply_char_sheet_data({
                "system": "5e",
                "player": {
                    "location": "void",
                    "stats": {
                        "STR": 15,
                        "DEX": 14,
                        "CON": 13,
                        "INT": 10,
                        "WIS": 8,
                        "CHA": 12,
                    }
                }
            })

    def test_invalid_inventory_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(ValueError, match="No matching entity: "):
            sm._apply_char_sheet_data({
                "system": "5e",
                "player": {
                    "inventory": {"magic_wand": 1},
                    "stats": {
                        "STR": 15,
                        "DEX": 14,
                        "CON": 13,
                        "INT": 10,
                        "WIS": 8,
                        "CHA": 12,
                    }
                }
            })

    def test_unknown_player_fields_ignored(self) -> None:
        sm = self._make_sm()
        sm._apply_char_sheet_data({
            "system": "5e",
            "player": {
                "future_field": 123,
                "stats": {
                    "STR": 15,
                    "DEX": 14,
                    "CON": 13,
                    "INT": 10,
                    "WIS": 8,
                    "CHA": 12,
                }
            }
        })
        assert not hasattr(sm.hard_state.player, "future_field")

    def test_stats_without_corpus_stats_raises(self) -> None:
        sm = StateManager(FIXTURES_DIR)
        with pytest.raises(ValueError, match="no stat system"):
            sm._apply_char_sheet_data({
                "system": "5e",
                "player": {"stats": {"STR": 18}}
            })

    def test_apply_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="State has not been loaded"):
            sm.apply_char_sheet("char_sheet.json")

    def test_file_not_found(self) -> None:
        sm = self._make_sm()
        with pytest.raises(FileNotFoundError, match="Character sheet file not found"):
            sm.apply_char_sheet("nonexistent.json")


class TestContainmentMaps:
    """Runtime containment map initialisation and mutation."""

    def test_load_all_rebuilds_room_contains_from_corpus(self) -> None:
        sm = StateManager(FIXTURES_DIR)
        assert "axe_head" in sm.hard_state.room_contains
        assert sm.hard_state.room_contains["axe_head"]["battleaxe"] == 1

    def test_load_all_rebuilds_entity_contains_from_corpus(self) -> None:
        # Build a corpus with an entity that contains another entity.
        from tests.helpers import make_char_sheet_corpus, _mk_item_entity
        from mgmai.models.corpus import Entity
        corpus = make_char_sheet_corpus()
        corpus.entities["chest"] = Entity(
            type="feature",
            description="A chest.",
            contains=["toenail_sword"],
        )
        corpus.entities["toenail_sword"] = _mk_item_entity(
            "toenail_sword", description="A sword.", name="Toenail Sword"
        )
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({
            "player": {"location": "axe_head"},
        })
        sm.soft_state = SoftGameState()
        sm._init_contains_from_corpus()
        assert sm.hard_state.entity_contains.get("chest") == {"toenail_sword": 1}

    def test_load_save_preserves_mutated_counts(self, manager, tmp_path) -> None:
        manager.hard_state.room_contains["axe_head"]["gold_coin"] = 20
        save_path = tmp_path / "save.json"
        manager.save(str(save_path))

        sm2 = StateManager()
        sm2.load_save(save_path)
        assert sm2.hard_state.room_contains["axe_head"]["gold_coin"] == 20

    def test_load_save_backfills_legacy_save(self, manager, tmp_path) -> None:
        save_path = tmp_path / "save.json"
        manager.save(str(save_path))

        # Strip containment keys to simulate a legacy save.
        data = json.loads(save_path.read_text())
        del data["hard"]["room_contains"]
        del data["hard"]["entity_contains"]
        save_path.write_text(json.dumps(data))

        sm2 = StateManager()
        sm2.load_save(save_path)
        assert "axe_head" in sm2.hard_state.room_contains
        assert sm2.hard_state.room_contains["axe_head"]["battleaxe"] == 1

    def test_apply_hard_changes_adds_room_contains(self, manager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.apply_hard_changes(HardStateChanges(
            room_contains_added={"axe_head": {"gold_coin": 50}}
        ))
        assert manager.hard_state.room_contains["axe_head"]["gold_coin"] == 50

    def test_apply_hard_changes_removes_room_contains(self, manager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.hard_state.room_contains["axe_head"]["gold_coin"] = 50
        manager.apply_hard_changes(HardStateChanges(
            room_contains_removed={"axe_head": {"gold_coin": 20}}
        ))
        assert manager.hard_state.room_contains["axe_head"]["gold_coin"] == 30

    def test_apply_hard_changes_deletes_zero_count_keys(self, manager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.hard_state.room_contains["axe_head"]["gold_coin"] = 5
        manager.apply_hard_changes(HardStateChanges(
            room_contains_removed={"axe_head": {"gold_coin": 5}}
        ))
        assert "gold_coin" not in manager.hard_state.room_contains["axe_head"]

    def test_apply_hard_changes_rejects_non_stackable_gt_one_in_world(self, manager) -> None:
        with pytest.raises(ValueError, match="non-stackable"):
            manager.apply_hard_changes(HardStateChanges(
                room_contains_added={"axe_head": {"toenail_sword": 2}}
            ))

    def test_apply_hard_changes_rejects_max_stack_overflow_in_world(self, manager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.corpus.entities["gold_coin"].max_stack = 10
        manager.hard_state.room_contains["axe_head"]["gold_coin"] = 8
        with pytest.raises(ValueError, match="max_stack"):
            manager.apply_hard_changes(HardStateChanges(
                room_contains_added={"axe_head": {"gold_coin": 5}}
            ))

    def test_apply_hard_changes_rejects_removing_more_than_present(self, manager) -> None:
        from tests.helpers import _mk_item_entity
        manager.corpus.entities["gold_coin"] = _mk_item_entity(
            "gold_coin", description="A coin.", tags=["stackable"]
        )
        manager.hard_state.room_contains["axe_head"]["gold_coin"] = 5
        with pytest.raises(ValueError, match="only 5 present"):
            manager.apply_hard_changes(HardStateChanges(
                room_contains_removed={"axe_head": {"gold_coin": 10}}
            ))

    def test_validate_cross_references_rejects_non_item_count_gt_one(self) -> None:
        from tests.helpers import _mk_room, _mk_npc_entity
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": _mk_room("start", "Start", contains=[{"npc": 2}]).model_dump(),
            },
            "entities": {
                "npc": _mk_npc_entity("npc").model_dump(),
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({"player": {"location": "start"}})
        sm.soft_state = SoftGameState()
        with pytest.raises(ValueError, match="non-item entity"):
            sm.validate_cross_references()

    def test_validate_cross_references_rejects_non_stackable_item_count_gt_one(self) -> None:
        from tests.helpers import _mk_room, _mk_item_entity
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": _mk_room("start", "Start", contains=[{"sword": 2}]).model_dump(),
            },
            "entities": {
                "sword": _mk_item_entity("sword", description="A sword.", name="Sword").model_dump(),
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({"player": {"location": "start"}})
        sm.soft_state = SoftGameState()
        with pytest.raises(ValueError, match="non-stackable item"):
            sm.validate_cross_references()

    def test_validate_cross_references_rejects_self_reference(self) -> None:
        from tests.helpers import make_char_sheet_corpus
        corpus = make_char_sheet_corpus()
        corpus.entities["chest"] = Entity(type="feature", description="A chest.", contains=["chest"])
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({"player": {"location": "axe_head"}})
        sm.soft_state = SoftGameState()
        with pytest.raises(ValueError, match="cannot contain itself"):
            sm.validate_cross_references()

    def test_validate_cross_references_rejects_player_in_contains(self) -> None:
        from tests.helpers import _mk_room, _mk_npc_entity
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": _mk_room("start", "Start", contains=["player"]).model_dump(),
            },
            "entities": {
                "player": Entity(type="player", description="The player.").model_dump(),
                "npc": _mk_npc_entity("npc").model_dump(),
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({"player": {"location": "start"}})
        sm.soft_state = SoftGameState()
        with pytest.raises(ValueError, match="Cannot place player entity"):
            sm.validate_cross_references()


class TestSaveLoadRoundtrip:
    """Verify state integrity across save → load cycle."""

    def test_roundtrip_preserves_core_state(self, manager, tmp_path) -> None:
        manager.hard_state.player.location = "bag_floor"
        manager.hard_state.player.inventory = {"rusty_key": 1, "toenail_sword": 1}
        manager.hard_state.flags["my_flag"] = True
        manager.hard_state.turn_count = 7
        manager.hard_state.entity_states["spider"]["alive"] = False

        save_path = tmp_path / "save.json"
        manager.save(str(save_path))

        sm2 = StateManager()
        sm2.load_save(save_path)

        assert sm2.hard_state.player.location == "bag_floor"
        assert "rusty_key" in sm2.hard_state.player.inventory
        assert "toenail_sword" in sm2.hard_state.player.inventory
        assert sm2.hard_state.flags.get("my_flag") is True
        assert sm2.hard_state.turn_count == 7
        assert sm2.hard_state.entity_states["spider"]["alive"] is False

    def test_roundtrip_preserves_soft_state(self, manager, tmp_path) -> None:
        manager.soft_state.soft_inventory = ["rock"]
        manager.soft_state.room_notes["axe_head"] = ["A note"]

        save_path = tmp_path / "save.json"
        manager.save(str(save_path))

        sm2 = StateManager()
        sm2.load_save(save_path)

        assert "rock" in sm2.soft_state.soft_inventory
        assert "A note" in sm2.soft_state.room_notes["axe_head"]


class TestStartCombatScopeValidation:
    """Load-time validation for start_combat/combat_group."""

    def _build_sm(self, corpus_dict):
        sm = StateManager()
        sm.corpus = ModuleCorpus.model_validate(corpus_dict)
        sm.hard_state = HardGameState.model_validate({
            "player": {"location": "room1"},
            "flags": {},
            "room_states": {"room1": {"visited": False}},
            "entity_states": {
                "goblin": {"alive": True, "current_hp": 7},
                "orc": {"alive": True, "current_hp": 15},
            },
            "turn_count": 0,
        })
        sm.soft_state = SoftGameState()
        return sm

    def _base_corpus(self):
        return {
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "room1": {
                    "name": "Room 1",
                    "description": "A room.",
                    "contains": ["goblin", "orc"],
                },
            },
            "entities": {
                "goblin": {
                    "type": "npc",
                    "description": "A goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {"hp": 7, "ac": 12, "atk": 4, "dmg": "1d6"},
                },
                "orc": {
                    "type": "npc",
                    "description": "An orc.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {"hp": 15, "ac": 13, "atk": 5, "dmg": "1d8"},
                },
                "scroll": {
                    "type": "item",
                    "name": "Scroll",
                    "description": "A scroll.",
                },
            },
        }

    def test_start_combat_on_interaction_result_rejected(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["interactions"] = [{
            "id": "provoke",
            "description": "Provoke",
            "result": {"narrative": "It attacks!", "start_combat": []},
        }]
        sm = self._build_sm(data)
        with pytest.raises(ValueError, match="only allowed on encounter-rule"):
            sm._validate_start_combat_scope()

    def test_start_combat_unknown_entity_rejected(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["aggro"] = [{
            "condition": {"require": "entity:goblin.alive == true"},
            "result": {"narrative": "Ambush!", "start_combat": ["dragon"]},
        }]
        sm = self._build_sm(data)
        with pytest.raises(ValueError, match="start_combat entry 'dragon' is not a known entity"):
            sm._validate_start_combat_scope()

    def test_start_combat_non_stat_blocked_rejected(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["aggro"] = [{
            "condition": {"require": "entity:goblin.alive == true"},
            "result": {"narrative": "Ambush!", "start_combat": ["scroll"]},
        }]
        sm = self._build_sm(data)
        with pytest.raises(ValueError, match="start_combat entry 'scroll' does not have a combat block"):
            sm._validate_start_combat_scope()

    def test_combat_group_member_without_combat_rejected(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["combat_group"] = "band"
        data["entities"]["orc"]["combat_group"] = "band"
        # Remove orc's combat block.
        del data["entities"]["orc"]["combat"]
        sm = self._build_sm(data)
        with pytest.raises(ValueError, match="combat_group 'band': member 'orc' lacks a combat block"):
            sm._validate_start_combat_scope()

    def test_valid_encounter_start_combat_passes(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["aggro"] = [{
            "condition": {"require": "entity:goblin.alive == true"},
            "result": {"narrative": "Ambush!", "start_combat": ["orc"]},
        }]
        sm = self._build_sm(data)
        sm._validate_start_combat_scope()  # should not raise

    def test_start_combat_source_only_passes(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["aggro"] = [{
            "condition": {"require": "entity:goblin.alive == true"},
            "result": {"narrative": "It lunges!", "start_combat": []},
        }]
        sm = self._build_sm(data)
        sm._validate_start_combat_scope()  # should not raise

    def test_start_combat_in_then_check_outside_encounter_rejected(self):
        data = self._base_corpus()
        data["entities"]["goblin"]["interactions"] = [{
            "id": "provoke",
            "description": "Provoke",
            "result": {
                "narrative": "It hesitates.",
                "then_check": {
                    "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
                    "success": {"narrative": "It attacks!", "start_combat": []},
                },
            },
        }]
        sm = self._build_sm(data)
        with pytest.raises(ValueError, match="only allowed on encounter-rule"):
            sm._validate_start_combat_scope()


class TestEntityPlacements:
    """Tests for location-derived direct entity placements."""

    @pytest.fixture
    def sm(self) -> StateManager:
        from tests.helpers import _mk_item_entity, _mk_npc_entity, _mk_room
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "room_a": _mk_room("room_a", "Room A", contains=["npc"]).model_dump(),
                "room_b": _mk_room("room_b", "Room B").model_dump(),
            },
            "entities": {
                "player": Entity(type="player", description="The player.").model_dump(),
                "npc": _mk_npc_entity(
                    "npc",
                    state_fields={"following": {"type": "boolean", "description": "Following?"}},
                ).model_dump(),
                "chest": Entity(type="feature", description="A chest.").model_dump(),
                "sword": _mk_item_entity("sword", description="A sword.", name="Sword").model_dump(),
                "coin": _mk_item_entity("coin", description="A coin.", tags=["stackable"]).model_dump(),
            },
        })
        hard = HardGameState.model_validate({
            "player": {"location": "room_a"},
            "entity_states": {
                "npc": {"alive": True},
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = hard
        sm.soft_state = SoftGameState()
        sm._init_contains_from_corpus()
        return sm

    def test_location_room_moves_entity(self, sm: StateManager) -> None:
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"location": "room:room_b"}}
        ))
        assert "npc" not in sm.hard_state.room_contains["room_a"]
        assert sm.hard_state.room_contains["room_b"]["npc"] == 1

    def test_location_null_removes_entity(self, sm: StateManager) -> None:
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"location": None}}
        ))
        assert "npc" not in sm.hard_state.room_contains["room_a"]
        assert all(
            "npc" not in contents
            for contents in sm.hard_state.room_contains.values()
        )
        assert all(
            "npc" not in contents
            for contents in sm.hard_state.entity_contains.values()
        )

    def test_location_entity_container(self, sm: StateManager) -> None:
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"sword": {"location": "entity:chest"}}
        ))
        assert sm.hard_state.entity_contains["chest"]["sword"] == 1

    def test_location_not_stored_in_entity_states(self, sm: StateManager) -> None:
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"location": "room:room_b"}}
        ))
        assert "location" not in sm.hard_state.entity_states["npc"]

    def test_location_rejects_stackable_item(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="stackable"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"coin": {"location": "room:room_b"}}
            ))

    def test_location_rejects_player(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="player entity"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"player": {"location": "room:room_b"}}
            ))

    def test_location_rejects_unknown_room(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="No matching room"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"npc": {"location": "room:void"}}
            ))

    def test_location_rejects_unknown_entity_container(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="No matching entity"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"npc": {"location": "entity:void"}}
            ))

    def test_location_rejects_self_containment(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="cannot contain itself"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"chest": {"location": "entity:chest"}}
            ))

    def test_location_rejects_invalid_prefix(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="Invalid location value"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"npc": {"location": "void"}}
            ))

    def test_location_clears_following(self, sm: StateManager) -> None:
        sm.hard_state.entity_states["npc"]["following"] = True
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"location": "room:room_b"}}
        ))
        assert sm.hard_state.entity_states["npc"]["following"] is False

    def test_location_wins_over_following_in_same_change(self, sm: StateManager) -> None:
        sm.hard_state.entity_states["npc"]["following"] = True
        sm.apply_hard_changes(HardStateChanges(
            entity_state_changes={"npc": {"location": "room:room_b", "following": True}}
        ))
        assert sm.hard_state.entity_states["npc"]["following"] is False
        assert sm.hard_state.room_contains["room_b"]["npc"] == 1

    def test_cross_path_conflict_rejected(self, sm: StateManager) -> None:
        with pytest.raises(ValueError, match="both 'location' and a containment delta"):
            sm.apply_hard_changes(HardStateChanges(
                entity_state_changes={"sword": {"location": "room:room_b"}},
                room_contains_added={"room_a": {"sword": 1}},
            ))

    def test_entity_placements_merge_by_overwrite(self) -> None:
        a = HardStateChanges(entity_placements={"npc": "room:room_a"})
        b = HardStateChanges(entity_placements={"npc": "room:room_b"})
        a.merge(b)
        assert a.entity_placements == {"npc": "room:room_b"}

    def test_entity_placements_counted_in_has_changes(self) -> None:
        hc = HardStateChanges(entity_placements={"npc": "room:room_a"})
        assert hc.has_changes() is True

    def test_entity_placements_field_roundtrips_via_model(self) -> None:
        hc = HardStateChanges(entity_placements={"npc": "room:room_a", "chest": None})
        data = hc.model_dump(mode="json")
        hc2 = HardStateChanges.model_validate(data)
        assert hc2.entity_placements == {"npc": "room:room_a", "chest": None}

    def test_save_migration_removes_fled_ghost(self, tmp_path: Path) -> None:
        from tests.helpers import _mk_npc_entity, _mk_room
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": _mk_room("start", "Start", contains=["npc"]).model_dump(),
            },
            "entities": {
                "npc": _mk_npc_entity("npc").model_dump(),
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({
            "player": {"location": "start"},
            "entity_states": {"npc": {"alive": True, "fled": True}},
            "room_contains": {"start": {"npc": 1}},
            "entity_contains": {},
        })
        sm.soft_state = SoftGameState()
        sm._adventure_dir = tmp_path
        save_path = sm.save_state(tmp_path)

        sm2 = StateManager()
        sm2.load_save(save_path)
        assert "fled" not in sm2.hard_state.entity_states["npc"]
        assert "npc" not in sm2.hard_state.room_contains.get("start", {})

    def test_save_migration_drops_false_fled(self, tmp_path: Path) -> None:
        from tests.helpers import _mk_npc_entity, _mk_room
        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Test", "introduction": "Test."},
            "rooms": {
                "start": _mk_room("start", "Start", contains=["npc"]).model_dump(),
            },
            "entities": {
                "npc": _mk_npc_entity("npc").model_dump(),
            },
        })
        sm = StateManager()
        sm.corpus = corpus
        sm.hard_state = HardGameState.model_validate({
            "player": {"location": "start"},
            "entity_states": {"npc": {"alive": True, "fled": False}},
            "room_contains": {"start": {"npc": 1}},
            "entity_contains": {},
        })
        sm.soft_state = SoftGameState()
        sm._adventure_dir = tmp_path
        save_path = sm.save_state(tmp_path)

        sm2 = StateManager()
        sm2.load_save(save_path)
        assert "fled" not in sm2.hard_state.entity_states["npc"]
        assert sm2.hard_state.room_contains["start"]["npc"] == 1
