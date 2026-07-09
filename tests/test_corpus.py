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
    ConditionExpression,
    Credits,
    DialogueGuidelines,
    EncounterRule,
    GameOverCondition,
    GameOverTrigger,
    Entity,
    Exit,
    Interaction,
    Mechanic,
    ModuleCorpus,
    Resolvable,
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
        assert len(sample_corpus.mechanics) == 0
        assert len(sample_corpus.game_over_conditions) == 1

    def test_sample_corpus_dialogue_path_ids_populated(self, sample_corpus: ModuleCorpus) -> None:
        korbar = sample_corpus.entities.get("korbar")
        assert korbar is not None
        assert korbar.dialogue is not None
        for path_id, path in korbar.dialogue.dialogue_paths.items():
            assert path.id == path_id
            assert isinstance(path, Resolvable)

    def test_sample_corpus_on_examine_events_load(self, sample_corpus: ModuleCorpus) -> None:
        for room in sample_corpus.rooms.values():
            for event in room.on_examine:
                assert event.id is not None
                assert isinstance(event, Resolvable)
        for entity in sample_corpus.entities.values():
            for event in entity.on_examine:
                assert event.id is not None
                assert isinstance(event, Resolvable)

    def test_sample_corpus_interactions_are_strict_interactions(self, sample_corpus: ModuleCorpus) -> None:
        for room in sample_corpus.rooms.values():
            for inter in room.interactions:
                assert isinstance(inter, Interaction)
                assert inter.id is not None
                assert inter.description is not None
        for entity in sample_corpus.entities.values():
            for inter in entity.interactions:
                assert isinstance(inter, Interaction)
                assert inter.id is not None
                assert inter.description is not None

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
            for entity_id in room.contains:
                assert entity_id in all_entity_ids, f"Room references unknown entity '{entity_id}'"

    def test_exit_targets_are_rooms(self, sample_corpus: ModuleCorpus) -> None:
        room_ids = set(sample_corpus.rooms.keys())
        for room in sample_corpus.rooms.values():
            for exit_ in room.exits:
                assert exit_.target_room in room_ids, (
                    f"Exit '{exit_.id}' targets unknown room '{exit_.target_room}'"
                )

    def test_entities_in_contains_exist(self, sample_corpus: ModuleCorpus) -> None:
        entity_ids = set(sample_corpus.entities.keys())
        for room in sample_corpus.rooms.values():
            for entity_id in room.contains:
                assert entity_id in entity_ids, (
                    f"Room contains unknown entity '{entity_id}'"
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
            "description": "Unlock the padlock",
            "result": {"narrative": "The padlock springs open."},
        })
        assert i.result is not None
        assert i.check is None

    def test_with_check_success_failure(self) -> None:
        i = Interaction.model_validate({
            "id": "search_corner",
            "description": "Search the corner",
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
                "description": "Bad",
                "check": {"threshold": 0.5, "repeatable": True},
                "result": {"narrative": "Should not have both."},
            })

    def test_result_with_set_flag(self) -> None:
        i = Interaction.model_validate({
            "id": "do_thing",
            "description": "Do thing",
            "result": {
                "narrative": "Done.",
                "set_flag": {"thing_done": True},
                "add_item": ["sword"],
                "remove_item": ["key"],
                "reveals": "You see the way out.",
            },
        })
        assert i.result is not None
        assert i.result.set_flag == {"thing_done": True}
        assert i.result.add_item == ["sword"]
        assert i.result.remove_item == ["key"]
        assert i.result.reveals == "You see the way out."

    def test_result_with_set_room_state(self) -> None:
        i = Interaction.model_validate({
            "id": "record_entry",
            "description": "Record entry",
            "result": {
                "narrative": "Recorded.",
                "set_room_state": {"room_a": {"_entered_from": "room_b"}},
            },
        })
        assert i.result is not None
        assert i.result.set_room_state == {"room_a": {"_entered_from": "room_b"}}

    def test_empty_interaction_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Interaction.model_validate({
                "id": "look",
                "description": "Look around the room",
            })
        assert "check" in str(exc_info.value) or "result" in str(exc_info.value)

    def test_with_condition(self) -> None:
        i = Interaction.model_validate({
            "id": "open_secret_door",
            "description": "Open the secret door",
            "condition": {"require": "flag:secret_door_found == true"},
            "result": {"narrative": "The secret door slides open.", "set_flag": {"secret_door_open": True}},
        })
        assert i.condition is not None
        assert i.condition.require == "flag:secret_door_found == true"
        assert i.result is not None
        assert i.result.narrative == "The secret door slides open."

    def test_requires_id_and_description(self) -> None:
        with pytest.raises(ValidationError):
            Interaction(result=Result(narrative="Missing id and description"))
        with pytest.raises(ValidationError):
            Interaction(id="x", result=Result(narrative="Missing description"))
        with pytest.raises(ValidationError):
            Interaction(description="x", result=Result(narrative="Missing id"))


class TestResolvable:
    def test_base_resolvable_has_optional_id_and_description(self) -> None:
        r = Resolvable(result=Result(narrative="No id needed"))
        assert r.id is None
        assert r.description is None

    def test_resolvable_requires_check_or_result(self) -> None:
        with pytest.raises(ValidationError):
            Resolvable(description="Empty")

    def test_resolvable_check_requires_success(self) -> None:
        with pytest.raises(ValidationError):
            Resolvable(check=RollCheck(threshold=0.5, repeatable=True))

    def test_resolvable_check_and_result_mutually_exclusive(self) -> None:
        with pytest.raises(ValidationError):
            Resolvable(
                check=RollCheck(threshold=0.5, repeatable=True),
                result=Result(narrative="Both"),
            )

    def test_dialogue_path_id_populated_from_dict_key(self) -> None:
        guidelines = DialogueGuidelines(
            guidelines="test",
            attitude_limits=AttitudeLimits(min=-5, max=5),
            dialogue_paths={
                "flatter": Resolvable(
                    description="Flatter the spider",
                    result=Result(narrative="The spider preens."),
                ),
            },
        )
        assert guidelines.dialogue_paths["flatter"].id == "flatter"

    def test_dialogue_path_id_preserved_when_supplied(self) -> None:
        guidelines = DialogueGuidelines(
            guidelines="test",
            attitude_limits=AttitudeLimits(min=-5, max=5),
            dialogue_paths={
                "flatter": Resolvable(
                    id="ignored",
                    description="Flatter the spider",
                    result=Result(narrative="The spider preens."),
                ),
            },
        )
        # Dict key wins over any supplied id.
        assert guidelines.dialogue_paths["flatter"].id == "flatter"


class TestResult:
    def test_set_player_location(self) -> None:
        r = Result.model_validate({"set_player_location": "bag_floor"})
        assert r.set_player_location == "bag_floor"

    def test_has_any_effect_with_location(self) -> None:
        r = Result(set_player_location="bag_floor")
        assert r.has_any_effect() is True

    def test_has_any_effect_without_location(self) -> None:
        r = Result()
        assert r.has_any_effect() is False

    def test_has_any_effect_with_start_combat_true(self) -> None:
        r = Result(start_combat=[])
        assert r.has_any_effect() is True

    def test_has_any_effect_with_game_over(self) -> None:
        r = Result(game_over=GameOverTrigger(type="lose", trigger_id="test"))
        assert r.has_any_effect() is True

    def test_has_any_effect_with_both_dispatch_fields(self) -> None:
        r = Result(
            start_combat=[],
            game_over=GameOverTrigger(type="win", trigger_id="test"),
        )
        assert r.has_any_effect() is True

    def test_has_any_effect_with_only_narrative(self) -> None:
        r = Result(narrative="Hello")
        assert r.has_any_effect() is True

    def test_start_combat_defaults_to_none(self) -> None:
        r = Result()
        assert r.start_combat is None

    def test_start_combat_none_does_not_count_as_effect(self) -> None:
        r = Result(start_combat=None)
        assert r.has_any_effect() is False

    def test_game_over_defaults_to_none(self) -> None:
        r = Result()
        assert r.game_over is None

    def test_game_over_deserializes_from_dict(self) -> None:
        r = Result.model_validate({"game_over": {"type": "lose", "trigger_id": "test"}})
        assert r.game_over == GameOverTrigger(type="lose", trigger_id="test")

    def test_game_over_rejects_invalid_type(self) -> None:
        with pytest.raises(ValidationError):
            Result.model_validate(
                {"game_over": {"type": "invalid", "trigger_id": "test"}}
            )

    def test_game_over_rejects_missing_trigger_id(self) -> None:
        with pytest.raises(ValidationError):
            Result.model_validate({"game_over": {"type": "lose"}})

    def test_start_combat_rejects_non_list(self) -> None:
        with pytest.raises(ValidationError):
            Result.model_validate({"start_combat": "not-a-list"})

    def test_result_with_all_dispatch_fields_serializes_roundtrip(self) -> None:
        r = Result(
            narrative="You die.",
            start_combat=[],
            game_over=GameOverTrigger(type="lose", trigger_id="spider"),
            set_flag={"spider_fled": True},
        )
        data = r.model_dump()
        r2 = Result.model_validate(data)
        assert r2.narrative == "You die."
        assert r2.start_combat == []
        assert r2.game_over == GameOverTrigger(type="lose", trigger_id="spider")
        assert r2.set_flag == {"spider_fled": True}


class TestMechanic:
    def test_encounter(self) -> None:
        m = Mechanic.model_validate({
            "rules": [
                {
                    "condition": {"require": "flag:has_weapon == true"},
                    "result": {"narrative": "The spider flees!"},
                },
            ],
        })
        assert m.rules is not None
        assert len(m.rules) == 1

    def test_neither_rules_nor_reactions_raises(self) -> None:
        # A Mechanic must carry at least one of 'rules' or 'reactions'.
        with pytest.raises(ValidationError):
            Mechanic.model_validate({
            })


class TestGameOverCondition:
    def test_win_condition_valid(self) -> None:
        c = GameOverCondition.model_validate({
            "type": "win",
            "condition": {"require": "flag:escaped == true"},
            "trigger_id": "escape",
            "narrative": "You are free!",
        })
        assert c.type == "win"
        assert c.condition is not None
        assert c.trigger_id == "escape"
        assert c.narrative == "You are free!"

    def test_lose_condition_valid(self) -> None:
        c = GameOverCondition.model_validate({
            "type": "lose",
            "condition": {"require": "flag:dead == true"},
            "trigger_id": "death",
        })
        assert c.type == "lose"
        assert c.narrative is None

    def test_missing_condition_raises(self) -> None:
        with pytest.raises(ValidationError):
            GameOverCondition.model_validate({
                "type": "win",
                "trigger_id": "x",
            })

    def test_missing_trigger_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            GameOverCondition.model_validate({
                "type": "win",
                "condition": {"require": "flag:x == true"},
            })


class TestEntity:
    def test_npc_with_dialogue(self) -> None:
        e = Entity.model_validate({
            "type": "npc",
            "description": "A friendly dwarf.",
            "state_fields": {"alive": {"type": "boolean", "description": "Is alive."}},
            "dialogue": {
                "guidelines": "Gruff but kind.",
                "attitude_limits": {"min": -5, "max": 10, "step_per_turn": 3, "initial": 0},
            },
        })
        assert e.type == "npc"
        assert e.dialogue is not None
        assert e.dialogue.attitude_limits.min == -5

    def test_item_with_tags(self) -> None:
        e = Entity.model_validate({
            "type": "item",
            "name": "Rusty Sword",
            "description": "A rusty sword.",
            "tags": ["weapon", "mundane"],
        })
        assert e.type == "item"
        assert e.name == "Rusty Sword"
        assert e.tags == ["weapon", "mundane"]

    def test_item_without_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "item",
                "description": "A nameless item.",
            })

    def test_non_item_without_name_ok(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A feature needs no name.",
        })
        assert e.name is None

    def test_npc_with_aggro(self) -> None:
        e = Entity.model_validate({
            "type": "npc",
            "description": "A hungry spider.",
            "state_fields": {"alive": {"type": "boolean", "description": "Is alive."}},
            "aggro": [
                {
                    "condition": {"require": "flag:has_weapon == true"},
                    "result": {"narrative": "The spider flees!"},
                },
            ],
        })
        assert e.aggro is not None
        assert len(e.aggro) == 1

    def test_feature_in_multiple_rooms(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A giant axe spanning multiple rooms.",
        })
        assert e.type == "feature"
        assert e.description == "A giant axe spanning multiple rooms."

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity.model_validate({
                "type": "monster",
                "description": "Not a valid type.",
            })

    def test_will_reveal_entry(self) -> None:
        g = DialogueGuidelines.model_validate({
            "guidelines": "Friendly.",
            "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2, "initial": 0},
            "will_reveal": {
                "secret1": {
                    "description": "A hidden treasure.",
                    "conditions": ["entity:korbar.attitude >= 3"],
                    "set_flag": {"treasure_known": True},
                },
            },
        })
        assert "secret1" in g.will_reveal
        reveal = g.will_reveal["secret1"]
        assert reveal.description == "A hidden treasure."
        assert reveal.conditions == ["entity:korbar.attitude >= 3"]
        assert reveal.set_flag == {"treasure_known": True}

    def test_will_reveal_with_set_entity_state(self) -> None:
        g = DialogueGuidelines.model_validate({
            "guidelines": "Mysterious.",
            "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2, "initial": 0},
            "will_reveal": {
                "trap_warning": {
                    "description": "Warns about a trap.",
                    "conditions": ["entity:mysterious_npc.attitude >= 3"],
                    "set_entity_state": {"spike_trap": {"disarmed": True}},
                },
            },
        })
        reveal = g.will_reveal["trap_warning"]
        assert reveal.set_entity_state == {"spike_trap": {"disarmed": True}}

    @pytest.mark.parametrize("entity_type,extra_field,extra_data", [
        ("feature", "dialogue", {"guidelines": "Creaky.", "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2}}),
        ("item", "dialogue", {"guidelines": "Chatty.", "attitude_limits": {"min": 0, "max": 5, "step_per_turn": 2}}),
        ("item", "aggro", [{"condition": {"require": "flag:x == true"}, "result": {}}]),
        ("player", "aggro", [{"condition": {"require": "flag:x == true"}, "result": {}}]),
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
        assert e.dialogue is None
        assert e.aggro is None

    def test_entity_with_interactions(self) -> None:
        e = Entity.model_validate({
            "type": "feature",
            "description": "A mysterious altar.",
            "interactions": [
                {
                    "id": "pray_at_altar",
                    "description": "Pray at the altar",
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
        assert e.condition is None
        assert e.one_way is False

    def test_exit_with_condition(self) -> None:
        e = Exit.model_validate({
            "id": "gated_exit",
            "direction": "Through the gate",
            "target_room": "beyond",
            "condition": {"require": "flag:gate_open == true"},
        })
        assert e.condition is not None
        assert e.condition.require == "flag:gate_open == true"



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
                    "effect": {
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
        assert reaction.effect.result is not None
        assert reaction.effect.result.narrative == "Welcome to the trap room."

    def test_room_with_interactions(self) -> None:
        r = Room.model_validate({
            "name": "Puzzle Room",
            "description": "A room with puzzles.",
            "interactions": [
                {
                    "id": "pull_lever",
                    "description": "Pull the lever",
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

    def test_room_with_contains(self) -> None:
        r = Room.model_validate({
            "name": "Guard Room",
            "description": "A room with guards.",
            "contains": ["guard_1", "guard_2", "captain"],
        })
        assert r.contains == ["guard_1", "guard_2", "captain"]
        assert r.contains_map == {"guard_1": 1, "guard_2": 1, "captain": 1}

    def test_room_with_mixed_contains(self) -> None:
        r = Room.model_validate({
            "name": "Treasury",
            "description": "A room full of gold.",
            "contains": ["goblin", "chest", {"gold_coin": 50}],
        })
        assert r.contains == ["goblin", "chest", {"gold_coin": 50}]
        assert r.contains_map == {"goblin": 1, "chest": 1, "gold_coin": 50}

    def test_contains_duplicate_ids_sum_counts(self) -> None:
        r = Room.model_validate({
            "name": "Treasury",
            "description": "A room full of gold.",
            "contains": ["gold_coin", {"gold_coin": 50}],
        })
        assert r.contains_map == {"gold_coin": 51}

    def test_contains_multi_key_object_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Room.model_validate({
                "name": "Treasury",
                "description": "A room full of gold.",
                "contains": [{"gold_coin": 50, "silver_coin": 30}],
            })

    def test_entity_with_mixed_contains(self) -> None:
        from mgmai.models.corpus import Entity
        e = Entity.model_validate({
            "type": "feature",
            "description": "A chest.",
            "contains": ["rusty_key", {"gold_coin": 10}],
        })
        assert e.contains_map == {"rusty_key": 1, "gold_coin": 10}


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


class TestAttitudeLimits:
    def test_defaults(self) -> None:
        a = AttitudeLimits.model_validate({"min": -5, "max": 10, "step_per_turn": 3})
        assert a.min == -5
        assert a.max == 10
        assert a.step_per_turn == 3

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

    def test_boolean_initial(self) -> None:
        s = StateFieldDecl.model_validate({
            "type": "boolean", "description": "Hidden?", "initial": True
        })
        assert s.initial is True

    def test_number_initial(self) -> None:
        s = StateFieldDecl.model_validate({
            "type": "number", "description": "HP.", "initial": 14
        })
        assert s.initial == 14

    def test_string_initial(self) -> None:
        s = StateFieldDecl.model_validate({
            "type": "string", "description": "Title.", "initial": "Novice"
        })
        assert s.initial == "Novice"

    def test_initial_defaults_to_none(self) -> None:
        s = StateFieldDecl.model_validate({"type": "boolean", "description": "X."})
        assert s.initial is None

    def test_boolean_initial_rejects_number(self) -> None:
        with pytest.raises(ValidationError, match="must be a boolean"):
            StateFieldDecl.model_validate({
                "type": "boolean", "description": "X.", "initial": 1
            })

    def test_number_initial_rejects_boolean(self) -> None:
        with pytest.raises(ValidationError, match="must be a number"):
            StateFieldDecl.model_validate({
                "type": "number", "description": "X.", "initial": True
            })

    def test_string_initial_rejects_number(self) -> None:
        with pytest.raises(ValidationError, match="must be a string"):
            StateFieldDecl.model_validate({
                "type": "string", "description": "X.", "initial": 42
            })


class TestFlagsDeclared:
    def test_plain_strings(self) -> None:
        c = ModuleCorpus.model_validate({
            "adventure": {"title": "T", "introduction": "I."},
            "rooms": {},
            "entities": {},
            "flags_declared": ["a", "b"],
        })
        assert c.flags_initial == {"a": False, "b": False}

    def test_single_key_dicts(self) -> None:
        c = ModuleCorpus.model_validate({
            "adventure": {"title": "T", "introduction": "I."},
            "rooms": {},
            "entities": {},
            "flags_declared": [{"a": True}, {"b": False}],
        })
        assert c.flags_initial == {"a": True, "b": False}

    def test_mixed_entries(self) -> None:
        c = ModuleCorpus.model_validate({
            "adventure": {"title": "T", "introduction": "I."},
            "rooms": {},
            "entities": {},
            "flags_declared": ["plain", {"true_flag": True}],
        })
        assert c.flags_initial == {"plain": False, "true_flag": True}

    def test_multi_key_dict_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one key"):
            ModuleCorpus.model_validate({
                "adventure": {"title": "T", "introduction": "I."},
                "rooms": {},
                "entities": {},
                "flags_declared": [{"a": True, "b": False}],
            })

    def test_non_boolean_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be a boolean"):
            ModuleCorpus.model_validate({
                "adventure": {"title": "T", "introduction": "I."},
                "rooms": {},
                "entities": {},
                "flags_declared": [{"a": "yes"}],
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


class TestEncounterRule:
    def test_result_death(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:unarmed == true"},
            "result": {
                "game_over": {"type": "lose", "trigger_id": "test_npc"},
            },
        })
        assert r.condition.require == "flag:unarmed == true"
        assert r.check is None
        assert r.result is not None
        assert r.result.game_over == GameOverTrigger(type="lose", trigger_id="test_npc")

    def test_result_flee(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:has_weapon == true"},
            "result": {
                "narrative": "It flees!",
                "set_flag": {"fled": True},
            },
        })
        assert r.result is not None
        assert r.result.narrative == "It flees!"
        assert r.result.set_flag == {"fled": True}

    def test_result_combat(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "entity:spider.alive == true"},
            "result": {
                "narrative": "It attacks!",
                "start_combat": [],
            },
        })
        assert r.result is not None
        assert r.result.start_combat == []

    def test_check_roll_with_success_and_failure(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:injured == true"},
            "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
            "success": {
                "narrative": "You drive it away.",
                "set_flag": {"fled": True},
            },
            "failure": {
                "narrative": "It overpowers you.",
                "game_over": {"type": "lose", "trigger_id": "npc"},
            },
        })
        assert r.check is not None
        assert r.result is None
        assert r.success is not None
        assert r.failure is not None
        assert r.success.narrative == "You drive it away."
        assert r.failure.game_over == GameOverTrigger(type="lose", trigger_id="npc")

    def test_check_stat_check_with_alter_stat_on_failure(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:falling == true"},
            "check": {"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
            "failure": {
                "alter_stat": {"STR": {"value": -4}, "CON": {"value": -4}},
                "narrative": "You land badly.",
            },
        })
        assert r.check is not None
        assert r.result is None
        assert r.failure is not None
        assert r.failure.alter_stat == {"STR": StatModifier(value=-4), "CON": StatModifier(value=-4)}

    def test_both_check_and_result_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            EncounterRule.model_validate({
                "condition": {"require": "flag:x == true"},
                "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
                "result": {"narrative": "Ambiguous!"},
            })

    def test_neither_check_nor_result_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            EncounterRule.model_validate({
                "condition": {"require": "flag:x == true"},
            })

    def test_stat_check_branch_with_start_combat(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "entity:spider.alive == true"},
            "check": {"type": "stat_check", "stat": "DEX", "target": 10, "repeatable": True},
            "success": {
                "narrative": "It attacks!",
                "start_combat": [],
            },
            "failure": {"narrative": "It flees."},
        })
        assert r.success is not None
        assert r.success.start_combat == []
        assert r.failure is not None
        assert r.failure.start_combat is None

    def test_result_with_start_combat_only(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "entity:npc.alive == true"},
            "result": {"start_combat": []},
        })
        assert r.check is None
        assert r.result is not None
        assert r.result.start_combat == []
        assert r.result.narrative is None

    def test_check_branch_with_game_over_on_failure(self) -> None:
        r = EncounterRule.model_validate({
            "condition": {"require": "flag:weak == true"},
            "check": {"type": "roll", "threshold": 0.5, "repeatable": True},
            "success": {"narrative": "You escape."},
            "failure": {
                "narrative": "The beast crushes you.",
                "game_over": {"type": "lose", "trigger_id": "beast"},
            },
        })
        assert r.failure is not None
        assert r.failure.game_over == GameOverTrigger(type="lose", trigger_id="beast")


class TestStatsBlock:
    def test_valid(self) -> None:
        sb = StatsBlock.model_validate({
            "definitions": {
                "STR": {"name": "Strength"},
            },
            "system": "5e",
        })
        assert sb.definitions["STR"].name == "Strength"
        assert sb.system == "5e"

    def test_default_system(self) -> None:
        sb = StatsBlock.model_validate({
            "definitions": {"STR": {"name": "Strength"}},
        })
        assert sb.system == "5e"

    def test_unsupported_system_raises(self) -> None:
        sb = StatsBlock.model_validate({
            "definitions": {"STR": {"name": "Strength"}},
            "system": "gurps",
        })
        from mgmai.engine.systems import get_system
        with pytest.raises(ValueError, match="Unknown system"):
            get_system(sb.system)

    def test_definitions_can_hold_six_stats(self) -> None:
        stat_names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        sb = StatsBlock.model_validate({
            "definitions": {
                s: {"name": s}
                for s in stat_names
            },
        })
        assert len(sb.definitions) == 6


class TestStatCheck:
    def test_minimal(self) -> None:
        sc = StatCheck.model_validate({"stat": "STR", "target": 12, "repeatable": False})
        assert sc.stat == "STR"
        assert sc.target == 12
        assert sc.repeatable is False
        assert sc.type == "stat_check"

    def test_full(self) -> None:
        sc = StatCheck.model_validate({
            "stat": "STR",
            "target": 15,
            "modifier": 2,
            "advantage": True,
            "repeatable": True,
        })
        assert sc.modifier == 2
        assert sc.model_extra == {"advantage": True}

    def test_modifier_defaults_to_zero(self) -> None:
        sc = StatCheck.model_validate({"stat": "DEX", "target": 10, "repeatable": True})
        assert sc.modifier == 0

    def test_extra_fields_allow_advantage(self) -> None:
        sc = StatCheck.model_validate({"stat": "CHA", "target": 14, "repeatable": False, "advantage": True})
        assert sc.model_extra == {"advantage": True}


class TestInteractionWithCheck:
    def test_with_roll_check(self) -> None:
        inter = Interaction.model_validate({
            "id": "test_roll",
            "description": "Test roll",
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
            "description": "Test stat",
            "check": {"type": "stat_check", "stat": "STR", "target": 12, "repeatable": True},
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
                "description": "Bad interaction",
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


class TestCombatGroupModel:
    """Entity.combat_group is npc-only; Result.start_combat serializes correctly."""

    def test_combat_group_on_npc_ok(self) -> None:
        e = Entity.model_validate({
            "type": "npc",
            "description": "A goblin.",
            "state_fields": {"alive": {"type": "boolean", "description": "Alive?"}},
            "combat_group": "goblin_band",
        })
        assert e.combat_group == "goblin_band"

    def test_combat_group_on_non_npc_raises(self) -> None:
        with pytest.raises(ValidationError, match="combat_group"):
            Entity.model_validate({
                "type": "feature",
                "description": "A feature.",
                "combat_group": "bad_features",
            })

    def test_result_start_combat_roundtrip(self) -> None:
        r = Result(
            start_combat=["goblin_1", "goblin_2"],
            narrative="The ambush springs!",
        )
        data = r.model_dump()
        r2 = Result.model_validate(data)
        assert r2.start_combat == ["goblin_1", "goblin_2"]
