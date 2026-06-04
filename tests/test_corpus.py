import pytest
from pydantic import ValidationError

from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    AttitudeLimits,
    Behavior,
    BranchOutcome,
    Check,
    ConditionExpression,
    Credits,
    DialogueGuidelines,
    DialogueExit,
    EncounterRule,
    Entity,
    Exit,
    FleeEffect,
    Interaction,
    Mechanic,
    ModuleCorpus,
    OnEnterEvent,
    ParameterSignature,
    Result,
    Room,
    StateFieldDecl,
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
        assert len(sample_corpus.mechanics) == 1

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

    def test_spans_rooms_are_rooms(self, sample_corpus: ModuleCorpus) -> None:
        room_ids = set(sample_corpus.rooms.keys())
        for entity in sample_corpus.entities.values():
            if entity.spans_rooms is not None:
                for room_id in entity.spans_rooms:
                    assert room_id in room_ids, (
                        f"Entity spans unknown room '{room_id}'"
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
        assert c.any_of is not None
        assert len(c.any_of) == 2
        assert c.any_of[0] == "flag:a == true"

    def test_any_with_nested_objects(self) -> None:
        c = ConditionExpression.model_validate({
            "any": [
                "flag:x == true",
                {"all": ["flag:y == true", "flag:z == true"]},
            ]
        })
        assert c.any_of is not None
        assert len(c.any_of) == 2
        assert isinstance(c.any_of[1], ConditionExpression)
        assert c.any_of[1].all_of is not None
        assert len(c.any_of[1].all_of) == 2  # type: ignore[arg-type]

    def test_all_with_plain_strings(self) -> None:
        c = ConditionExpression.model_validate({
            "all": ["flag:a == true", "flag:b == true", "flag:c == true"]
        })
        assert c.all_of is not None
        assert len(c.all_of) == 3
        assert c.all_of[0] == "flag:a == true"
        assert c.all_of[1] == "flag:b == true"
        assert c.all_of[2] == "flag:c == true"

    def test_all_with_nesting(self) -> None:
        c = ConditionExpression.model_validate({
            "all": [
                "flag:a == true",
                {"unless": "flag:b == true"},
            ]
        })
        assert c.all_of is not None
        assert len(c.all_of) == 2
        assert isinstance(c.all_of[1], ConditionExpression)
        assert c.all_of[1].unless == "flag:b == true"  # type: ignore[union-attr]

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
        assert c.any_of is not None
        assert len(c.any_of) == 2

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

    def test_with_condition(self) -> None:
        i = Interaction.model_validate({
            "id": "open_secret_door",
            "label": "Open the secret door",
            "condition": {"require": "flag:secret_door_found == true"},
            "result": {"narrative": "The secret door slides open.", "set_flag": {"secret_door_open": True}},
        })
        assert i.condition is not None
        assert i.condition.require == "flag:secret_door_found == true"
        assert i.result is not None
        assert i.result.narrative == "The secret door slides open."


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

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
                "id": "bad",
                "description": "Invalid type.",
                "type": "draw",
                "condition": {"require": "flag:x == true"},
                "trigger_id": "x",
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

    def test_will_reveal_with_set_entity_state(self) -> None:
        g = DialogueGuidelines.model_validate({
            "personality": "Mysterious.",
            "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2, "initial": 0},
            "will_reveal": {
                "trap_warning": {
                    "description": "Warns about a trap.",
                    "conditions": ["attitude:mysterious_npc >= 3"],
                    "set_entity_state": {"spike_trap": {"disarmed": True}},
                },
            },
        })
        reveal = g.will_reveal["trap_warning"]
        assert reveal.set_entity_state == {"spike_trap": {"disarmed": True}}

    def test_feature_with_dialogue_guidelines_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "feature",
                "description": "A talking door.",
                "dialogue_guidelines": {
                    "personality": "Creaky.",
                    "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2},
                },
            })

    def test_item_with_dialogue_guidelines_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "item",
                "description": "A talking sword.",
                "dialogue_guidelines": {
                    "personality": "Chatty.",
                    "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2},
                },
            })

    def test_item_with_behavior_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "item",
                "description": "An aggressive sword.",
                "behavior": {
                    "encounter_rules": [
                        {
                            "condition": {"require": "flag:x == true"},
                            "outcome": "flee",
                        },
                    ],
                },
            })

    def test_player_with_behavior_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "player",
                "description": "The player character.",
                "behavior": {
                    "encounter_rules": [
                        {
                            "condition": {"require": "flag:x == true"},
                            "outcome": "flee",
                        },
                    ],
                },
            })

    def test_player_entity_type(self) -> None:
        e = Entity.model_validate({
            "type": "player",
            "description": "The player character.",
        })
        assert e.type == "player"
        assert e.dialogue_guidelines is None
        assert e.behavior is None

    def test_trap_entity_type(self) -> None:
        e = Entity.model_validate({
            "type": "trap",
            "description": "A spike trap hidden in the floor.",
            "state_fields": {"triggered": {"type": "boolean", "description": "Whether the trap has triggered."}},
        })
        assert e.type == "trap"
        assert e.state_fields["triggered"].type == "boolean"

    def test_entity_with_interactions(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A mysterious altar.",
            "interactions": [
                {
                    "id": "pray_at_altar",
                    "label": "Pray at the altar",
                    "result": {"narrative": "You feel a divine presence."},
                },
            ],
        })
        assert len(e.interactions) == 1
        assert e.interactions[0].id == "pray_at_altar"

    def test_entity_with_soft_items(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A dead adventurer.",
            "soft_items": ["rusty coin", "torn map", "empty flask"],
        })
        assert e.soft_items == ["rusty coin", "torn map", "empty flask"]


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

    def test_traversal_trigger_encounter(self) -> None:
        e = Exit.model_validate({
            "id": "exit_webs",
            "direction": "Through the webs",
            "target_room": "bag_floor",
            "on_traverse": {
                "trigger_encounter": "spider",
            },
        })
        assert e.on_traverse.trigger_encounter == "spider"

    def test_traversal_skip_if(self) -> None:
        e = Exit.model_validate({
            "id": "gated_exit",
            "direction": "Through the gate",
            "target_room": "beyond",
            "on_traverse": {
                "narrative": "The gate slams behind you.",
                "skip_if": {"require": "flag:gate_held == true"},
                "narrative_skip": "You slip through, holding the gate open.",
            },
        })
        assert e.on_traverse.skip_if is not None
        assert e.on_traverse.skip_if.require == "flag:gate_held == true"
        assert e.on_traverse.narrative_skip == "You slip through, holding the gate open."


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

    def test_room_with_soft_items(self) -> None:
        r = Room.model_validate({
            "name": "Cavern",
            "description": "A dark cavern.",
            "soft_items": ["rock", "loose stone", "stale bread"],
        })
        assert r.soft_items == ["rock", "loose stone", "stale bread"]

    def test_room_with_entities_present(self) -> None:
        r = Room.model_validate({
            "name": "Guard Room",
            "description": "A room with guards.",
            "entities_present": ["guard_1", "guard_2", "captain"],
        })
        assert r.entities_present == ["guard_1", "guard_2", "captain"]


class TestCheck:
    def test_check_threshold_bounds(self) -> None:
        Check.model_validate({"threshold": 0.0, "repeatable": True})
        Check.model_validate({"threshold": 1.0, "repeatable": True})

    def test_check_threshold_out_of_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Check.model_validate({"threshold": 1.5, "repeatable": True})
        with pytest.raises(ValidationError):
            Check.model_validate({"threshold": -0.1, "repeatable": True})

    def test_type_defaults_to_roll(self) -> None:
        c = Check.model_validate({"threshold": 0.5, "repeatable": True})
        assert c.type == "roll"

    def test_type_invalid_raises(self) -> None:
        with pytest.raises(ValidationError):
            Check.model_validate({"threshold": 0.5, "type": "dice"})

    def test_with_note(self) -> None:
        c = Check.model_validate({
            "threshold": 0.75,
            "repeatable": False,
            "note": "This is an optional designer note explaining the check.",
        })
        assert c.note == "This is an optional designer note explaining the check."
        assert c.threshold == 0.75
        assert c.repeatable is False

    def test_note_is_optional(self) -> None:
        c = Check.model_validate({
            "threshold": 0.3,
            "repeatable": True,
        })
        assert c.note is None


class TestAttitudeLimits:
    def test_defaults(self) -> None:
        a = AttitudeLimits.model_validate({"min": -5, "max": 10, "step_per_turn": 3})
        assert a.initial == 0

    def test_custom_initial(self) -> None:
        a = AttitudeLimits.model_validate({
            "min": -5, "max": 10, "step_per_turn": 3, "initial": 2
        })
        assert a.initial == 2

    def test_step_per_turn_defaults_to_one(self) -> None:
        a = AttitudeLimits.model_validate({"min": -5, "max": 10})
        assert a.step_per_turn == 1


class TestStateFieldDecl:
    def test_valid_boolean_type(self) -> None:
        s = StateFieldDecl.model_validate({"type": "boolean", "description": "Is alive."})
        assert s.type == "boolean"
        assert s.description == "Is alive."

    def test_valid_number_type(self) -> None:
        s = StateFieldDecl.model_validate({"type": "number", "description": "HP."})
        assert s.type == "number"

    def test_valid_string_type(self) -> None:
        s = StateFieldDecl.model_validate({"type": "string", "description": "Flavour text."})
        assert s.type == "string"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldDecl.model_validate({"type": "integer", "description": "HP."})

    def test_missing_description_raises(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldDecl.model_validate({"type": "boolean"})


class TestOnEnterEvent:
    def test_isolated_basic_event(self) -> None:
        event = OnEnterEvent.model_validate({"id": "event_1"})
        assert event.id == "event_1"
        assert event.condition is None
        assert event.narrative is None

    def test_with_trigger_dialogue(self) -> None:
        event = OnEnterEvent.model_validate({
            "id": "greet_korbar",
            "trigger_dialogue": "korbar",
        })
        assert event.trigger_dialogue == "korbar"

    def test_with_set_entity_state(self) -> None:
        event = OnEnterEvent.model_validate({
            "id": "kill_door",
            "set_entity_state": {"secret_door": {"alive": False}},
        })
        assert event.set_entity_state == {"secret_door": {"alive": False}}

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            OnEnterEvent.model_validate({"narrative": "Hello."})

    def test_with_set_flag(self) -> None:
        event = OnEnterEvent.model_validate({
            "id": "event_flag",
            "set_flag": {"visited_room": True, "alarm_triggered": False},
        })
        assert event.set_flag == {"visited_room": True, "alarm_triggered": False}

    def test_narrative_in_isolation(self) -> None:
        event = OnEnterEvent.model_validate({
            "id": "event_narrate",
            "narrative": "The door creaks open slowly.",
        })
        assert event.narrative == "The door creaks open slowly."

    def test_all_fields_combined(self) -> None:
        event = OnEnterEvent.model_validate({
            "id": "full_event",
            "condition": {"require": "flag:x == true"},
            "narrative": "Something stirs in the darkness.",
            "set_flag": {"monster_awake": True},
            "set_entity_state": {"monster": {"awake": True}},
            "trigger_dialogue": "monster",
        })
        assert event.condition.require == "flag:x == true"
        assert event.narrative == "Something stirs in the darkness."
        assert event.set_flag == {"monster_awake": True}
        assert event.trigger_dialogue == "monster"


class TestBranchOutcome:
    def test_basic(self) -> None:
        b = BranchOutcome.model_validate({
            "outcome": "success",
            "set_flags": {"door_open": True},
            "narrative": "The door swings open.",
        })
        assert b.outcome == "success"
        assert b.set_flags == {"door_open": True}
        assert b.narrative == "The door swings open."

    def test_minimal_outcome_only(self) -> None:
        b = BranchOutcome.model_validate({"outcome": "death"})
        assert b.outcome == "death"
        assert b.set_flags is None
        assert b.narrative is None

    def test_missing_outcome_raises(self) -> None:
        with pytest.raises(ValidationError):
            BranchOutcome.model_validate({
                "set_flags": {"x": True},
            })


class TestCredits:
    def test_all_fields(self) -> None:
        c = Credits.model_validate({
            "author": "A. N. Author",
            "source": "Original",
            "license": "CC BY-SA 4.0",
        })
        assert c.author == "A. N. Author"
        assert c.source == "Original"
        assert c.license == "CC BY-SA 4.0"

    def test_empty_credits(self) -> None:
        c = Credits.model_validate({})
        assert c.author is None
        assert c.source is None
        assert c.license is None


class TestAdventure:
    def test_isolated(self) -> None:
        a = Adventure.model_validate({
            "title": "Test Adventure",
            "introduction": "You find yourself in a dark room.",
            "atmosphere": {"setting": "A mysterious dungeon.", "tone": "Dark and foreboding."},
            "credits": {"author": "Alice", "license": "MIT"},
        })
        assert a.title == "Test Adventure"
        assert a.introduction == "You find yourself in a dark room."
        assert a.atmosphere.setting == "A mysterious dungeon."
        assert a.credits.author == "Alice"

    def test_minimal(self) -> None:
        a = Adventure.model_validate({
            "title": "Minimal",
            "introduction": "Start.",
        })
        assert a.title == "Minimal"
        assert a.credits is None
        assert a.atmosphere is None


class TestAtmosphere:
    def test_basic(self) -> None:
        a = Atmosphere.model_validate({
            "setting": "A whimsical world.",
            "tone": "Lighthearted and fun.",
        })
        assert a.setting == "A whimsical world."
        assert a.tone == "Lighthearted and fun."

    def test_missing_setting_raises(self) -> None:
        with pytest.raises(ValidationError):
            Atmosphere.model_validate({"tone": "Dark."})

    def test_missing_tone_raises(self) -> None:
        with pytest.raises(ValidationError):
            Atmosphere.model_validate({"setting": "A world."})


class TestParameterSignature:
    def test_basic(self) -> None:
        p = ParameterSignature.model_validate({
            "target": ["entity", "soft_item"],
            "using": ["entity"],
        })
        assert p.target == ["entity", "soft_item"]
        assert p.using == ["entity"]

    def test_empty(self) -> None:
        p = ParameterSignature.model_validate({})
        assert p.target is None
        assert p.using is None


class TestFleeEffect:
    def test_basic(self) -> None:
        f = FleeEffect.model_validate({
            "set_flags": {"spider_fled": True},
            "effect": "The spider scurries away into the shadows.",
        })
        assert f.set_flags == {"spider_fled": True}
        assert f.effect == "The spider scurries away into the shadows."

    def test_missing_set_flags_raises(self) -> None:
        with pytest.raises(ValidationError):
            FleeEffect.model_validate({"effect": "x"})

    def test_missing_effect_raises(self) -> None:
        with pytest.raises(ValidationError):
            FleeEffect.model_validate({"set_flags": {"x": True}})


class TestEncounterRule:
    def test_outcome_death(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:unarmed == true"},
            "outcome": "death",
        })
        assert r.outcome == "death"
        assert r.condition.require == "flag:unarmed == true"

    def test_outcome_flee(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:has_weapon == true"},
            "outcome": "flee",
        })
        assert r.outcome == "flee"

    def test_outcome_roll(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:injured == true"},
            "outcome": "roll",
            "threshold": 0.5,
            "narrative": "The spider lunges!",
            "set_flags": {"spider_attacked": True},
        })
        assert r.outcome == "roll"
        assert r.threshold == 0.5
        assert r.narrative == "The spider lunges!"
        assert r.set_flags == {"spider_attacked": True}

    def test_with_on_success(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:injured == true"},
            "outcome": "roll",
            "threshold": 0.5,
            "on_success": {
                "outcome": "success",
                "set_flags": {"spider_fled": True},
                "narrative": "You drive the spider away.",
            },
        })
        assert r.on_success is not None
        assert r.on_success.outcome == "success"
        assert r.on_success.set_flags == {"spider_fled": True}

    def test_with_on_failure(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:injured == true"},
            "outcome": "roll",
            "threshold": 0.7,
            "on_failure": {
                "outcome": "death",
                "narrative": "The spider overpowers you.",
            },
        })
        assert r.on_failure is not None
        assert r.on_failure.outcome == "death"
        assert r.on_failure.narrative == "The spider overpowers you."


class TestBehavior:
    def test_triggers_on_empty(self) -> None:
        b = Behavior.model_validate({
            "triggers_on": [],
            "encounter_rules": [
                {
                    "condition": {"require": "flag:x == true"},
                    "outcome": "flee",
                },
            ],
        })
        assert b.triggers_on == []
        assert len(b.encounter_rules) == 1

    def test_triggers_on_non_empty(self) -> None:
        b = Behavior.model_validate({
            "triggers_on": ["exit_through_webs", "attack"],
            "encounter_rules": [
                {
                    "condition": {"require": "flag:x == true"},
                    "outcome": "flee",
                },
            ],
        })
        assert b.triggers_on == ["exit_through_webs", "attack"]

    def test_with_on_flee(self) -> None:
        b = Behavior.model_validate({
            "triggers_on": ["exit_through_webs"],
            "encounter_rules": [
                {
                    "condition": {"require": "flag:has_weapon == true"},
                    "outcome": "flee",
                },
            ],
            "on_flee": {
                "set_flags": {"spider_fled": True},
                "effect": "It scurries away.",
            },
        })
        assert b.on_flee is not None
        assert b.on_flee.set_flags == {"spider_fled": True}
