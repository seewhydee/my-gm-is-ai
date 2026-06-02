import pytest
from pydantic import ValidationError

from mgmai.models.corpus import (
    AttitudeLimits,
    Check,
    ConditionExpression,
    DialogueGuidelines,
    DialogueExit,
    EncounterRule,
    Entity,
    Exit,
    Interaction,
    Mechanic,
    ModuleCorpus,
    OnEnterEvent,
    Result,
    Room,
    TraversalEffect,
    WillRevealEntry,
)


class TestModuleCorpus:
    def test_load_sample_corpus(self, sample_corpus: ModuleCorpus) -> None:
        assert sample_corpus.adventure.title == "You're Trapped in a Bag of Holding!"
        assert sample_corpus.adventure.atmosphere is not None
        assert sample_corpus.adventure.atmosphere.setting
        assert len(sample_corpus.rooms) == 5
        assert len(sample_corpus.entities) > 0
        assert len(sample_corpus.mechanics) == 2

    def test_start_room_has_is_start_room(self, sample_corpus: ModuleCorpus) -> None:
        start_rooms = [r for r in sample_corpus.rooms.values() if r.is_start_room]
        assert len(start_rooms) == 1
        assert start_rooms[0].name == "Axe Head"

    def test_rooms_have_exits(self, sample_corpus: ModuleCorpus) -> None:
        for room_id, room in sample_corpus.rooms.items():
            assert len(room.exits) > 0, f"Room {room_id} has no exits"

    def test_entities_are_referenced_by_rooms(self, sample_corpus: ModuleCorpus) -> None:
        all_entity_ids = set(sample_corpus.entities.keys())
        for room in sample_corpus.rooms.values():
            for entity_id in room.entities_present:
                assert entity_id in all_entity_ids, f"Room references unknown entity '{entity_id}'"

    def test_exit_targets_are_rooms(self, sample_corpus: ModuleCorpus) -> None:
        room_ids = set(sample_corpus.rooms.keys())
        for room in sample_corpus.rooms.values():
            for exit_ in room.exits:
                assert exit_.target_room in room_ids, (
                    f"Exit '{exit_.id}' targets unknown room '{exit_.target_room}'"
                )


class TestConditionExpression:
    def test_require(self) -> None:
        c = ConditionExpression.model_validate({"require": "flag:x == true"})
        assert c.require == "flag:x == true"
        assert c.unless is None

    def test_unless(self) -> None:
        c = ConditionExpression.model_validate({"unless": "flag:injured == true"})
        assert c.unless == "flag:injured == true"

    def test_any_with_strings(self) -> None:
        c = ConditionExpression.model_validate({
            "any": ["flag:a == true", "flag:b == true"]
        })
        assert c.any is not None
        assert len(c.any) == 2
        assert c.any[0] == "flag:a == true"

    def test_any_with_nested_objects(self) -> None:
        c = ConditionExpression.model_validate({
            "any": [
                "flag:x == true",
                {"all": ["flag:y == true", "flag:z == true"]},
            ]
        })
        assert c.any is not None
        assert len(c.any) == 2
        assert isinstance(c.any[1], ConditionExpression)
        assert c.any[1].all is not None
        assert len(c.any[1].all) == 2  # type: ignore[arg-type]

    def test_all_with_nesting(self) -> None:
        c = ConditionExpression.model_validate({
            "all": [
                "flag:a == true",
                {"unless": "flag:b == true"},
            ]
        })
        assert c.all is not None
        assert len(c.all) == 2
        assert isinstance(c.all[1], ConditionExpression)
        assert c.all[1].unless == "flag:b == true"  # type: ignore[union-attr]

    def test_deeply_nested_any_all(self) -> None:
        data = {
            "any": [
                {"all": [
                    "flag:a == true",
                    {"any": ["flag:b == true", "flag:c == true"]},
                ]},
                "flag:d == true",
            ]
        }
        c = ConditionExpression.model_validate(data)
        assert c.any is not None
        assert len(c.any) == 2

    def test_missing_all_keys_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConditionExpression.model_validate({})

    def test_multiple_keys_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConditionExpression.model_validate({
                "require": "flag:x == true",
                "unless": "flag:y == true",
            })

    def test_require_and_any_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConditionExpression.model_validate({
                "require": "flag:x == true",
                "any": ["flag:y == true"],
            })


class TestInteraction:
    def test_with_result_only(self) -> None:
        i = Interaction.model_validate({
            "id": "unlock_padlock",
            "label": "Unlock the padlock",
            "result": {"narrative": "The padlock springs open."},
        })
        assert i.result is not None
        assert i.check is None

    def test_with_check_success_failure(self) -> None:
        i = Interaction.model_validate({
            "id": "search_corner",
            "label": "Search the corner",
            "check": {"threshold": 0.5, "repeatable": True},
            "success": {"narrative": "You find a coin."},
            "failure": {"narrative": "Nothing here."},
        })
        assert i.check is not None
        assert i.result is None

    def test_check_and_result_mutual_exclusion(self) -> None:
        with pytest.raises(ValidationError):
            Interaction.model_validate({
                "id": "bad_interaction",
                "label": "Bad",
                "check": {"threshold": 0.5, "repeatable": True},
                "result": {"narrative": "Should not have both."},
            })

    def test_result_with_set_flag(self) -> None:
        i = Interaction.model_validate({
            "id": "do_thing",
            "label": "Do thing",
            "result": {
                "narrative": "Done.",
                "set_flag": {"thing_done": True},
                "add_item": "sword",
                "remove_item": "key",
                "reveals": "You see the way out.",
            },
        })
        assert i.result is not None
        assert i.result.set_flag == {"thing_done": True}
        assert i.result.add_item == "sword"
        assert i.result.remove_item == "key"
        assert i.result.reveals == "You see the way out."

    def test_empty_interaction_is_valid(self) -> None:
        i = Interaction.model_validate({
            "id": "look",
            "label": "Look around",
        })
        assert i.result is None
        assert i.check is None

    def test_parameter_signature(self) -> None:
        i = Interaction.model_validate({
            "id": "attack",
            "label": "Attack",
            "parameter_signature": {"target": ["entity"], "using": ["entity", "soft_item"]},
        })
        assert i.parameter_signature is not None
        assert i.parameter_signature.target == ["entity"]
        assert i.parameter_signature.using == ["entity", "soft_item"]


class TestMechanic:
    def test_game_over_win(self) -> None:
        m = Mechanic.model_validate({
            "id": "win_escape",
            "type": "win",
            "description": "Escape the bag.",
            "condition": {"require": "flag:escaped == true"},
            "narrative": "You are free!",
            "trigger_id": "escape",
        })
        assert m.type == "win"
        assert m.condition is not None
        assert m.trigger_id == "escape"
        assert m.rules is None

    def test_game_over_lose(self) -> None:
        m = Mechanic.model_validate({
            "id": "lose_death",
            "type": "lose",
            "description": "The player dies.",
            "condition": {"require": "flag:dead == true"},
            "trigger_id": "death",
        })
        assert m.type == "lose"

    def test_encounter(self) -> None:
        m = Mechanic.model_validate({
            "id": "spider_encounter",
            "description": "A spider attacks.",
            "rules": [
                {
                    "condition": {"require": "flag:has_weapon == true"},
                    "outcome": "flee",
                },
            ],
        })
        assert m.rules is not None
        assert len(m.rules) == 1
        assert m.type is None

    def test_game_over_missing_condition_raises(self) -> None:
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
                "id": "bad_win",
                "type": "win",
                "description": "Bad win.",
                "trigger_id": "x",
            })

    def test_game_over_missing_trigger_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
                "id": "bad_win",
                "type": "win",
                "description": "Bad win.",
                "condition": {"require": "flag:x == true"},
            })

    def test_both_type_and_rules_raises(self) -> None:
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
                "id": "bad",
                "type": "win",
                "description": "Bad.",
                "condition": {"require": "flag:x == true"},
                "trigger_id": "x",
                "rules": [],
            })

    def test_neither_type_nor_rules_raises(self) -> None:
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
                "id": "bad",
                "description": "Just a description.",
            })


class TestEntity:
    def test_npc_with_dialogue(self) -> None:
        e = Entity.model_validate({
            "type": "npc",
            "description": "A friendly dwarf.",
            "state_fields": {"alive": {"type": "boolean", "description": "Is alive."}},
            "dialogue_guidelines": {
                "personality": "Gruff but kind.",
                "attitude_limits": {"min": -5, "max": 10, "step_per_turn": 3, "initial": 0},
            },
        })
        assert e.type == "npc"
        assert e.dialogue_guidelines is not None
        assert e.dialogue_guidelines.attitude_limits.min == -5

    def test_item_with_tags(self) -> None:
        e = Entity.model_validate({
            "type": "item",
            "description": "A rusty sword.",
            "tags": ["weapon", "mundane"],
            "draggable": True,
            "dragging_note": "It's heavy.",
        })
        assert e.type == "item"
        assert e.tags == ["weapon", "mundane"]
        assert e.draggable is True

    def test_npc_with_behavior(self) -> None:
        e = Entity.model_validate({
            "type": "npc",
            "description": "A hungry spider.",
            "state_fields": {"alive": {"type": "boolean", "description": "Is alive."}},
            "behavior": {
                "triggers_on": ["exit_through_webs"],
                "encounter_rules": [
                    {
                        "condition": {"require": "flag:has_weapon == true"},
                        "outcome": "flee",
                    },
                ],
                "on_flee": {"set_flags": {"spider_fled": True}, "effect": "It scurries away."},
            },
        })
        assert e.behavior is not None
        assert len(e.behavior.encounter_rules) == 1

    def test_feature_with_spans_rooms(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A giant axe spanning multiple rooms.",
            "spans_rooms": ["room1", "room2", "room3"],
        })
        assert e.spans_rooms == ["room1", "room2", "room3"]

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "monster",
                "description": "Not a valid type.",
            })

    def test_will_reveal_entry(self) -> None:
        g = DialogueGuidelines.model_validate({
            "personality": "Friendly.",
            "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2, "initial": 0},
            "will_reveal": {
                "secret1": {
                    "description": "A hidden treasure.",
                    "conditions": ["attitude:korbar >= 3"],
                    "set_flag": {"treasure_known": True},
                },
            },
        })
        assert "secret1" in g.will_reveal
        reveal = g.will_reveal["secret1"]
        assert reveal.description == "A hidden treasure."
        assert reveal.conditions == ["attitude:korbar >= 3"]
        assert reveal.set_flag == {"treasure_known": True}

    def test_dialogue_exit(self) -> None:
        g = DialogueGuidelines.model_validate({
            "personality": "Dying fly.",
            "attitude_limits": {"min": 0, "max": 1, "step_per_turn": 1, "initial": 0},
            "on_dialogue_exit": {
                "set_entity_state": {"stuck_fly": {"alive": False}},
                "narrative": "The fly dies.",
            },
        })
        assert g.on_dialogue_exit is not None
        assert g.on_dialogue_exit.set_entity_state == {"stuck_fly": {"alive": False}}


class TestExit:
    def test_basic_exit(self) -> None:
        e = Exit.model_validate({
            "id": "exit_north",
            "direction": "Walk north",
            "target_room": "room_north",
        })
        assert e.id == "exit_north"
        assert e.hidden is False
        assert e.one_way is False

    def test_one_way_hidden_exit(self) -> None:
        e = Exit.model_validate({
            "id": "secret_passage",
            "direction": "Slip through the crack",
            "target_room": "hidden_room",
            "hidden": True,
            "one_way": True,
        })
        assert e.hidden is True
        assert e.one_way is True

    def test_exit_with_conditions(self) -> None:
        e = Exit.model_validate({
            "id": "gated_exit",
            "direction": "Through the gate",
            "target_room": "beyond",
            "conditions": [{"require": "flag:gate_open == true"}],
        })
        assert len(e.conditions) == 1
        assert e.conditions[0].require == "flag:gate_open == true"

    def test_exit_with_traversal_effects(self) -> None:
        e = Exit.model_validate({
            "id": "fall",
            "direction": "Jump down",
            "target_room": "bottom",
            "on_traverse": {
                "set_flag": {"injured": True},
                "narrative": "You hurt yourself.",
            },
        })
        assert e.on_traverse.set_flag == {"injured": True}
        assert e.on_traverse.narrative == "You hurt yourself."


class TestRoom:
    def test_start_room(self) -> None:
        r = Room.model_validate({
            "name": "Start",
            "description": "A dim room.",
            "exits": [
                {"id": "e1", "direction": "north", "target_room": "room2"},
            ],
            "is_start_room": True,
        })
        assert r.is_start_room is True

    def test_room_with_on_enter(self) -> None:
        r = Room.model_validate({
            "name": "Trap Room",
            "description": "A room with a trap.",
            "on_enter": [
                {
                    "id": "event_welcome",
                    "condition": None,
                    "narrative": "Welcome to the trap room.",
                    "set_flag": {"visited_trap_room": True},
                },
            ],
        })
        assert len(r.on_enter) == 1
        event = r.on_enter[0]
        assert event.condition is None
        assert event.narrative == "Welcome to the trap room."

    def test_room_with_interactions(self) -> None:
        r = Room.model_validate({
            "name": "Puzzle Room",
            "description": "A room with puzzles.",
            "interactions": [
                {
                    "id": "pull_lever",
                    "label": "Pull the lever",
                    "result": {"narrative": "The wall slides open."},
                },
            ],
        })
        assert len(r.interactions) == 1
        assert r.interactions[0].id == "pull_lever"


class TestCheck:
    def test_check_threshold_bounds(self) -> None:
        Check.model_validate({"threshold": 0.0, "repeatable": True})
        Check.model_validate({"threshold": 1.0, "repeatable": True})

    def test_check_threshold_out_of_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Check.model_validate({"threshold": 1.5, "repeatable": True})
        with pytest.raises(ValidationError):
            Check.model_validate({"threshold": -0.1, "repeatable": True})


class TestAttitudeLimits:
    def test_defaults(self) -> None:
        a = AttitudeLimits.model_validate({"min": -5, "max": 10, "step_per_turn": 3})
        assert a.initial == 0

    def test_custom_initial(self) -> None:
        a = AttitudeLimits.model_validate({
            "min": -5, "max": 10, "step_per_turn": 3, "initial": 2
        })
        assert a.initial == 2
