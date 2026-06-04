import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mgmai.state.manager import StateManager, StateNotLoadedError
from mgmai.models.actions import HardStateChanges
from mgmai.models.soft_state import SoftStatePatch, TurnHistoryEntry


ADVENTURES_DIR = Path(__file__).resolve().parent.parent / "adventures"
BAG_OF_HOLDING = ADVENTURES_DIR / "bag-of-holding"


@pytest.fixture
def manager() -> StateManager:
    return StateManager(BAG_OF_HOLDING)


class TestLoadAndValidation:
    def test_load_all_success(self) -> None:
        sm = StateManager(BAG_OF_HOLDING)
        assert sm.corpus is not None
        assert sm.hard_state is not None
        assert sm.soft_state is not None
        assert sm.corpus.adventure.title == "You're Trapped in a Bag of Holding!"
        assert sm.hard_state.player.location == "axe_head"
        assert sm.soft_state.dialogue_state.active_npc is None

    def test_load_individual_methods(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm._validate_cross_references()
        assert sm.corpus.rooms["axe_head"].name == "Axe Head"

    def test_invalid_player_location(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.player.location = "nonexistent_room"
        with pytest.raises(ValueError, match="Player location"):
            sm._validate_cross_references()

    def test_invalid_inventory_item(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.player.inventory.append("magic_wand")
        with pytest.raises(ValueError, match="inventory references unknown"):
            sm._validate_cross_references()

    def test_invalid_room_state_room(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.room_states["void"] = {"visited": False}
        with pytest.raises(ValueError, match="room_states references unknown room"):
            sm._validate_cross_references()

    def test_invalid_entity_state_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.entity_states["ghost"] = {"alive": True}
        with pytest.raises(ValueError, match="entity_states references unknown entity"):
            sm._validate_cross_references()

    def test_undeclared_entity_state_field(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.entity_states["spider"]["magic_level"] = 9000
        with pytest.raises(ValueError, match="undeclared state field"):
            sm._validate_cross_references()

    def test_invalid_room_note_room(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.soft_state.room_notes["void"] = ["spooky"]
        with pytest.raises(ValueError, match="room_notes references unknown room"):
            sm._validate_cross_references()

    def test_invalid_entity_note_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.soft_state.entity_notes["ghost"] = ["spooky"]
        with pytest.raises(ValueError, match="entity_notes references unknown entity"):
            sm._validate_cross_references()

    def test_invalid_npc_attitudes_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.soft_state.npc_attitudes["battleaxe"] = 5
        with pytest.raises(ValueError, match="non-NPC entity"):
            sm._validate_cross_references()

    def test_invalid_npc_revelations_entity(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.soft_state.npc_revelations["battleaxe"] = []
        with pytest.raises(ValueError, match="non-NPC entity"):
            sm._validate_cross_references()

    def test_invalid_npc_revelations_topic(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.soft_state.npc_revelations["korbar"] = [
            {"topic_id": "fake_topic", "description": "Fake"}
        ]
        with pytest.raises(ValueError, match="not in will_reveal"):
            sm._validate_cross_references()

    def test_multiple_errors_collected(self) -> None:
        sm = StateManager()
        sm.corpus = StateManager.load_corpus(BAG_OF_HOLDING / "corpus.json")
        sm.hard_state = StateManager.load_hard_state(BAG_OF_HOLDING / "hard-state.json")
        sm.soft_state = StateManager.load_soft_state(BAG_OF_HOLDING / "soft-state.json")
        sm.hard_state.player.location = "bad_room"
        sm.hard_state.room_states["bad_room2"] = {}
        with pytest.raises(ValueError) as exc_info:
            sm._validate_cross_references()
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
        manager.apply_hard_changes(HardStateChanges(inventory_added=["toenail_sword"]))
        assert "toenail_sword" in manager.hard_state.player.inventory

    def test_inventory_remove(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = ["rusty_key", "toenail_sword"]
        manager.apply_hard_changes(HardStateChanges(inventory_removed=["rusty_key"]))
        assert "rusty_key" not in manager.hard_state.player.inventory
        assert "toenail_sword" in manager.hard_state.player.inventory

    def test_inventory_remove_missing_is_noop(self, manager: StateManager) -> None:
        manager.hard_state.player.inventory = []
        manager.apply_hard_changes(HardStateChanges(inventory_removed=["missing"]))
        assert manager.hard_state.player.inventory == []

    def test_flags_set(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(flags_set={"spider_fled": True}))
        assert manager.hard_state.flags["spider_fled"] is True

    def test_flags_set_creates_new_flag(self, manager: StateManager) -> None:
        manager.apply_hard_changes(HardStateChanges(flags_set={"new_dynamic_flag": True}))
        assert manager.hard_state.flags["new_dynamic_flag"] is True

    def test_flags_cleared(self, manager: StateManager) -> None:
        manager.hard_state.flags["injured"] = True
        manager.apply_hard_changes(HardStateChanges(flags_cleared=["injured"]))
        assert manager.hard_state.flags["injured"] is False

    def test_flags_cleared_unknown_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValueError, match="Cannot clear unknown flag"):
            manager.apply_hard_changes(HardStateChanges(flags_cleared=["nonexistent_flag"]))

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
        with pytest.raises(ValueError, match="unknown room"):
            manager.apply_hard_changes(
                HardStateChanges(room_state_changes={"void": {"visited": True}})
            )

    def test_entity_state_changes(self, manager: StateManager) -> None:
        manager.apply_hard_changes(
            HardStateChanges(entity_state_changes={"spider": {"fled": True}})
        )
        assert manager.hard_state.entity_states["spider"]["fled"] is True

    def test_entity_state_changes_new_entity(self, manager: StateManager) -> None:
        del manager.hard_state.entity_states["korbar"]
        manager.apply_hard_changes(
            HardStateChanges(entity_state_changes={"korbar": {"alive": True}})
        )
        assert manager.hard_state.entity_states["korbar"]["alive"] is True

    def test_entity_state_changes_unknown_entity_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValueError, match="unknown entity"):
            manager.apply_hard_changes(
                HardStateChanges(entity_state_changes={"ghost": {"alive": True}})
            )

    def test_apply_from_dict(self, manager: StateManager) -> None:
        manager.apply_hard_changes({"player_location": "bag_floor"})
        assert manager.hard_state.player.location == "bag_floor"

    def test_apply_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Hard state has not been loaded"):
            sm.apply_hard_changes(HardStateChanges())


class TestApplySoftPatches:
    def test_room_note(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="room_note",
            target_id="axe_head",
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

    def test_soft_inventory_add(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="soft_inventory_add",
            new_value="rock",
            reason="Player picked it up.",
        )
        manager.apply_soft_patches([patch])
        assert "rock" in manager.soft_state.soft_inventory

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

    def test_room_note_missing_target_raises(self, manager: StateManager) -> None:
        with pytest.raises(ValidationError, match="requires target_id"):
            SoftStatePatch(
                field="room_note",
                new_value="Something.",
                reason="Test.",
            )

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
                "field": "soft_inventory_add",
                "new_value": "lint",
                "reason": "Player picked it up.",
            }
        ])
        assert "lint" in manager.soft_state.soft_inventory

    def test_apply_before_load_raises(self) -> None:
        sm = StateManager()
        with pytest.raises(StateNotLoadedError, match="Soft state has not been loaded"):
            sm.apply_soft_patches([])

    def test_room_note_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="room_note",
            target_id="axe_head",
            new_value=123,
            reason="Test.",
        )
        with pytest.raises(ValueError, match="must be a string"):
            manager.apply_soft_patches([patch])

    def test_entity_note_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            entity_id="spider",
            field="entity_note",
            new_value={"bad": "value"},
            reason="Test.",
        )
        with pytest.raises(ValueError, match="must be a string"):
            manager.apply_soft_patches([patch])

    def test_soft_inventory_add_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="soft_inventory_add",
            new_value=123,
            reason="Test.",
        )
        with pytest.raises(ValueError, match="must be a string"):
            manager.apply_soft_patches([patch])

    def test_soft_inventory_remove_non_string_raises(self, manager: StateManager) -> None:
        patch = SoftStatePatch(
            field="soft_inventory_remove",
            new_value=["list"],
            reason="Test.",
        )
        with pytest.raises(ValueError, match="must be a string"):
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
