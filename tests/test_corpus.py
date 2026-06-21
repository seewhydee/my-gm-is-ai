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

import pytest
from pydantic import ValidationError

from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    AttitudeLimits,
    Behavior,
    BranchOutcome,
    ConditionExpression,
    Credits,
    DialogueGuidelines,
    EncounterRule,
    Entity,
    Exit,
    FleeEffect,
    Interaction,
    Mechanic,
    ModuleCorpus,
    ParameterSignature,
    Reaction,
    ReactionEffects,
    Result,
    RollCheck,
    Room,
    StateFieldDecl,
    StatCheck,
    StatDefinition,
    StatModifier,
    StatsBlock,
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

    def test_result_with_set_room_state(self) -> None:
        i = Interaction.model_validate({
            "id": "record_entry",
            "label": "Record entry",
            "result": {
                "narrative": "Recorded.",
                "set_room_state": {"room_a": {"_entered_from": "room_b"}},
            },
        })
        assert i.result is not None
        assert i.result.set_room_state == {"room_a": {"_entered_from": "room_b"}}

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

    @pytest.mark.parametrize("entity_type,extra_field,extra_data", [
        ("feature", "dialogue_guidelines", {"personality": "Creaky.", "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2}}),
        ("item", "dialogue_guidelines", {"personality": "Chatty.", "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2}}),
        ("item", "behavior", {"encounter_rules": [{"condition": {"require": "flag:x == true"}, "outcome": "flee"}]}),
        ("player", "behavior", {"encounter_rules": [{"condition": {"require": "flag:x == true"}, "outcome": "flee"}]}),
    ])
    def test_invalid_field_for_entity_type_raises(self, entity_type, extra_field, extra_data) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": entity_type,
                "description": "Test entity.",
                extra_field: extra_data,
            })

    def test_player_entity_type(self) -> None:
        e = Entity.model_validate({
            "type": "player",
            "description": "The player character.",
        })
        assert e.type == "player"
        assert e.dialogue_guidelines is None
        assert e.behavior is None

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

    def test_room_with_reactions(self) -> None:
        r = Room.model_validate({
            "name": "Trap Room",
            "description": "A room with a trap.",
            "reactions": [
                {
                    "id": "event_welcome",
                    "on": "room.entered",
                    "condition": {"require": "flag:trap_armed == true"},
                    "effects": {
                        "result": {
                            "narrative": "Welcome to the trap room.",
                            "set_flag": {"visited_trap_room": True},
                        },
                    },
                },
            ],
        })
        assert len(r.reactions) == 1
        reaction = r.reactions[0]
        assert reaction.condition is not None
        assert reaction.condition.require == "flag:trap_armed == true"
        assert reaction.effects.result is not None
        assert reaction.effects.result.narrative == "Welcome to the trap room."

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


class TestRollCheck:
    def test_threshold_bounds(self) -> None:
        RollCheck.model_validate({"threshold": 0.0, "repeatable": True})
        RollCheck.model_validate({"threshold": 1.0, "repeatable": True})

    def test_threshold_out_of_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RollCheck.model_validate({"threshold": 1.5, "repeatable": True})
        with pytest.raises(ValidationError):
            RollCheck.model_validate({"threshold": -0.1, "repeatable": True})

    def test_type_defaults_to_roll(self) -> None:
        c = RollCheck.model_validate({"threshold": 0.5, "repeatable": True})
        assert c.type == "roll"

    def test_with_note(self) -> None:
        c = RollCheck.model_validate({
            "threshold": 0.75,
            "repeatable": False,
            "note": "This is an optional designer note explaining the check.",
        })
        assert c.note == "This is an optional designer note explaining the check."
        assert c.threshold == 0.75
        assert c.repeatable is False

    def test_note_is_optional(self) -> None:
        c = RollCheck.model_validate({
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

    def test_missing_outcome_defaults_to_none(self) -> None:
        b = BranchOutcome.model_validate({
            "set_flags": {"x": True},
        })
        assert b.outcome == "none"
        assert b.set_flags == {"x": True}

    def test_with_alter_stat(self) -> None:
        b = BranchOutcome.model_validate({
            "outcome": "flee",
            "set_flags": {"spider_fled": True},
            "alter_stat": {
                "STR": {"value": -4},
                "DEX": {"value": -4},
                "CON": {"value": -4},
            },
            "narrative": "The spider flees, but you are badly hurt.",
        })
        assert b.alter_stat == {
            "STR": StatModifier(value=-4),
            "DEX": StatModifier(value=-4),
            "CON": StatModifier(value=-4),
        }


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
        assert a.id is None

    def test_with_id(self) -> None:
        a = Adventure.model_validate({
            "id": "test-adv",
            "title": "Test Adventure",
            "introduction": "Start.",
        })
        assert a.id == "test-adv"


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

    def test_with_alter_stat(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:falling == true"},
            "outcome": "stat_check",
            "check": {"type": "stat_check", "stat": "DEX", "dc": 10, "repeatable": True},
            "alter_stat": {"CON": {"value": -2}},
            "on_failure": {
                "outcome": "flee",
                "alter_stat": {"STR": {"value": -4}, "CON": {"value": -4}},
                "narrative": "You land badly.",
            },
        })
        assert r.alter_stat == {"CON": StatModifier(value=-2)}
        assert r.on_failure is not None
        assert r.on_failure.alter_stat == {"STR": StatModifier(value=-4), "CON": StatModifier(value=-4)}


class TestBehavior:
    def test_encounter_rules(self) -> None:
        b = Behavior.model_validate({
            "encounter_rules": [
                {
                    "condition": {"require": "flag:x == true"},
                    "outcome": "flee",
                },
            ],
        })
        assert len(b.encounter_rules) == 1

    def test_with_on_flee(self) -> None:
        b = Behavior.model_validate({
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


class TestStatsBlock:
    def test_valid(self) -> None:
        sb = StatsBlock.model_validate({
            "definitions": {
                "STR": {"name": "Strength", "description": "Physical might"},
            },
            "system": "5e",
        })
        assert sb.definitions["STR"].name == "Strength"
        assert sb.system == "5e"

    def test_default_system(self) -> None:
        sb = StatsBlock.model_validate({
            "definitions": {"STR": {"name": "Strength", "description": ""}},
        })
        assert sb.system == "5e"

    def test_unsupported_system_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unknown RPG system"):
            StatsBlock.model_validate({
                "definitions": {"STR": {"name": "Strength", "description": ""}},
                "system": "gurps",
            })

    def test_definitions_can_hold_six_stats(self) -> None:
        stat_names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        sb = StatsBlock.model_validate({
            "definitions": {
                s: {"name": s, "description": f"The {s} stat"}
                for s in stat_names
            },
        })
        assert len(sb.definitions) == 6


class TestStatCheck:
    def test_minimal(self) -> None:
        sc = StatCheck.model_validate({"stat": "STR", "dc": 12, "repeatable": False})
        assert sc.stat == "STR"
        assert sc.dc == 12
        assert sc.repeatable is False
        assert sc.type == "stat_check"

    def test_full(self) -> None:
        sc = StatCheck.model_validate({
            "stat": "STR",
            "dc": 15,
            "modifier": 2,
            "resolution_params": {"5e": {"advantage": True}},
            "opposed_by": "entity:spider.DEX",
            "repeatable": True,
            "note": "A strength check",
            "skill": "athletics",
        })
        assert sc.modifier == 2
        assert sc.resolution_params == {"5e": {"advantage": True}}
        assert sc.opposed_by == "entity:spider.DEX"
        assert sc.skill == "athletics"

    def test_modifier_defaults_to_zero(self) -> None:
        sc = StatCheck.model_validate({"stat": "DEX", "dc": 10, "repeatable": True})
        assert sc.modifier == 0

    def test_resolution_params_optional(self) -> None:
        sc = StatCheck.model_validate({"stat": "CHA", "dc": 14, "repeatable": False})
        assert sc.resolution_params is None


class TestInteractionWithCheck:
    def test_with_roll_check(self) -> None:
        inter = Interaction.model_validate({
            "id": "test_roll",
            "label": "Test",
            "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
            "success": {"narrative": "Pass"},
            "failure": {"narrative": "Fail"},
        })
        assert inter.check is not None
        assert inter.check.type == "roll"
        assert isinstance(inter.check, RollCheck)

    def test_with_stat_check(self) -> None:
        inter = Interaction.model_validate({
            "id": "test_stat",
            "label": "Test",
            "check": {"type": "stat_check", "stat": "STR", "dc": 12, "repeatable": True},
            "success": {"narrative": "Pass"},
            "failure": {"narrative": "Fail"},
        })
        assert inter.check is not None
        assert inter.check.type == "stat_check"
        assert isinstance(inter.check, StatCheck)
        assert inter.check.stat == "STR"

    def test_check_and_result_mutually_exclusive_raises(self) -> None:
        with pytest.raises(ValidationError, match="must have either check"):
            Interaction.model_validate({
                "id": "bad",
                "label": "Bad",
                "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
                "result": {"narrative": "Result"},
            })


class TestModuleCorpusWithStats:
    def test_without_stats(self) -> None:
        mc = ModuleCorpus.model_validate({
            "adventure": {"title": "T", "introduction": "I"},
            "rooms": {},
            "entities": {},
        })
        assert mc.stats is None

    def test_with_stats(self) -> None:
        mc = ModuleCorpus.model_validate({
            "adventure": {"title": "T", "introduction": "I"},
            "rooms": {},
            "entities": {},
            "stats": {
                "definitions": {
                    "STR": {"name": "Strength", "description": ""},
                },
            },
        })
        assert mc.stats is not None
        assert mc.stats.definitions["STR"].name == "Strength"
