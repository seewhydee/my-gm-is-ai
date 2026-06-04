from __future__ import annotations

import pytest

from mgmai.engine.conditions import (
    evaluate,
    evaluate_condition_string,
    parse_condition_string,
    evaluate_require,
)
from mgmai.models.corpus import ConditionExpression, ModuleCorpus
from mgmai.models.hard_state import HardGameState, PlayerState
from mgmai.models.soft_state import SoftGameState


def make_hard_state(**overrides) -> HardGameState:
    defaults = {
        "player": {"location": "axe_head", "inventory": []},
        "flags": {
            "injured": False,
            "stunned": False,
            "my_flag": True,
            "other_flag": False,
        },
        "room_states": {
            "axe_head": {"visited": True},
            "bag_floor": {"visited": False},
        },
        "entity_states": {
            "player": {"alive": True},
            "spider": {"alive": True, "fled": False},
            "korbar": {"alive": True, "told_secret": False},
        },
        "turn_count": 0,
        "game_over": None,
    }
    defaults.update(overrides)
    return HardGameState.model_validate(defaults)


def make_soft_state(**overrides) -> SoftGameState:
    defaults: dict = {
        "soft_inventory": [],
        "room_notes": {},
        "entity_notes": {},
        "npc_attitudes": {"korbar": 5, "spider": -5, "stuck_fly": 0},
        "npc_revelations": {},
        "turn_history": [],
        "dialogue_state": {},
    }
    defaults.update(overrides)
    return SoftGameState.model_validate(defaults)


def make_corpus(**overrides) -> ModuleCorpus:
    base = {
        "adventure": {
            "title": "Test Adventure",
            "introduction": "Test intro.",
        },
        "rooms": {},
        "entities": {
            "sword": {
                "type": "item",
                "description": "A sword.",
                "tags": ["weapon"],
            },
            "shield": {
                "type": "item",
                "description": "A shield.",
                "tags": ["armor"],
            },
            "magic_sword": {
                "type": "item",
                "description": "A magic sword.",
                "tags": ["weapon", "magic"],
            },
            "korbar": {
                "type": "npc",
                "description": "A dwarf.",
                "dialogue_guidelines": {
                    "personality": "Grumpy.",
                    "attitude_limits": {"min": -5, "max": 10, "step_per_turn": 3, "initial": 0},
                },
            },
        },
    }
    base.update(overrides)
    return ModuleCorpus.model_validate(base)


class TestParseConditionString:
    def test_flag_true(self) -> None:
        domain, key, op, value = parse_condition_string("flag:my_flag == true")
        assert domain == "flag"
        assert key == "my_flag"
        assert op == "=="
        assert value == "true"

    def test_flag_false(self) -> None:
        domain, key, op, value = parse_condition_string("flag:my_flag == false")
        assert domain == "flag"
        assert op == "=="
        assert value == "false"

    def test_inventory(self) -> None:
        domain, key, op, value = parse_condition_string("inventory:rusty_key")
        assert domain == "inventory"
        assert key == "rusty_key"
        assert op is None
        assert value is None

    def test_tag(self) -> None:
        domain, key, op, value = parse_condition_string("tag:weapon")
        assert domain == "tag"
        assert key == "weapon"
        assert op is None
        assert value is None

    def test_entity_with_op(self) -> None:
        domain, key, op, value = parse_condition_string(
            "entity:player.alive == true"
        )
        assert domain == "entity"
        assert key == "player.alive"
        assert op == "=="
        assert value == "true"

    def test_room_with_op(self) -> None:
        domain, key, op, value = parse_condition_string(
            "room:axe_head.visited == false"
        )
        assert domain == "room"
        assert key == "axe_head.visited"
        assert op == "=="
        assert value == "false"

    def test_attitude_gte(self) -> None:
        domain, key, op, value = parse_condition_string("attitude:korbar >= 4")
        assert domain == "attitude"
        assert key == "korbar"
        assert op == ">="
        assert value == "4"

    def test_attitude_gt(self) -> None:
        domain, key, op, value = parse_condition_string("attitude:korbar > 2")
        assert op == ">"

    def test_attitude_lte(self) -> None:
        domain, key, op, value = parse_condition_string("attitude:korbar <= 3")
        assert op == "<="

    def test_attitude_lt(self) -> None:
        domain, key, op, value = parse_condition_string("attitude:korbar < 0")
        assert op == "<"

    def test_garbage_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_condition_string("garbage")

    def test_no_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_condition_string("key == value")

    def test_hyphen_in_id(self) -> None:
        domain, key, op, value = parse_condition_string("flag:door-opened == true")
        assert domain == "flag"
        assert key == "door-opened"

    def test_topic_domain(self) -> None:
        domain, key, op, value = parse_condition_string("topic:abandonment")
        assert domain == "topic"
        assert key == "abandonment"
        assert op is None
        assert value is None

    def test_item_domain(self) -> None:
        domain, key, op, value = parse_condition_string("item:rusty_key")
        assert domain == "item"
        assert key == "rusty_key"
        assert op is None
        assert value is None


class TestEvaluateConditionStringFlag:
    def test_flag_true_match(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert evaluate_condition_string("flag:my_flag == true", hs, ss, None)

    def test_flag_true_mismatch(self) -> None:
        hs = make_hard_state(flags={"my_flag": False})
        ss = make_soft_state()
        assert not evaluate_condition_string("flag:my_flag == true", hs, ss, None)

    def test_flag_false_match(self) -> None:
        hs = make_hard_state(flags={"my_flag": False})
        ss = make_soft_state()
        assert evaluate_condition_string("flag:my_flag == false", hs, ss, None)

    def test_flag_false_mismatch(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert not evaluate_condition_string("flag:my_flag == false", hs, ss, None)

    def test_flag_missing_returns_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string("flag:nonexistent == true", hs, ss, None)

    def test_flag_case_insensitive_bool(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert evaluate_condition_string("flag:my_flag == True", hs, ss, None)
        assert evaluate_condition_string("flag:my_flag == FALSE", hs, ss, None) is False

    def test_flag_missing_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="flag condition requires operator"):
            evaluate_condition_string("flag:my_flag", hs, ss, None)

    def test_flag_numeric_value_with_op_works(self) -> None:
        hs = make_hard_state(flags={"count": True})
        ss = make_soft_state()
        assert evaluate_condition_string("flag:count == true", hs, ss, None)


class TestEvaluateConditionStringInventory:
    def test_inventory_has_item(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["rusty_key"]})
        ss = make_soft_state()
        assert evaluate_condition_string("inventory:rusty_key", hs, ss, None)

    def test_inventory_missing_item(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string("inventory:rusty_key", hs, ss, None)

    def test_inventory_empty(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": []})
        ss = make_soft_state()
        assert not evaluate_condition_string("inventory:rusty_key", hs, ss, None)

    def test_inventory_with_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="inventory condition must not have operator"):
            evaluate_condition_string("inventory:rusty_key == true", hs, ss, None)


class TestEvaluateConditionStringTag:
    def test_tag_weapon_found(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["sword"]})
        ss = make_soft_state()
        corpus = make_corpus()
        assert evaluate_condition_string("tag:weapon", hs, ss, corpus)

    def test_tag_weapon_not_found(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["shield"]})
        ss = make_soft_state()
        corpus = make_corpus()
        assert not evaluate_condition_string("tag:weapon", hs, ss, corpus)

    def test_tag_magic_found(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["magic_sword"]})
        ss = make_soft_state()
        corpus = make_corpus()
        assert evaluate_condition_string("tag:magic", hs, ss, corpus)
        assert evaluate_condition_string("tag:weapon", hs, ss, corpus)

    def test_tag_empty_inventory(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        corpus = make_corpus()
        assert not evaluate_condition_string("tag:weapon", hs, ss, corpus)

    def test_tag_item_not_in_corpus_ignored(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["bogus"]})
        ss = make_soft_state()
        corpus = make_corpus()
        assert not evaluate_condition_string("tag:weapon", hs, ss, corpus)

    def test_tag_missing_corpus_raises(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["sword"]})
        ss = make_soft_state()
        with pytest.raises(ValueError, match="tag condition requires corpus"):
            evaluate_condition_string("tag:weapon", hs, ss, None)

    def test_tag_with_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        corpus = make_corpus()
        with pytest.raises(ValueError, match="tag condition must not have operator"):
            evaluate_condition_string("tag:weapon == true", hs, ss, corpus)


class TestEvaluateConditionStringEntity:
    def test_entity_alive_true(self) -> None:
        hs = make_hard_state(entity_states={"player": {"alive": True}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:player.alive == true", hs, ss, None)

    def test_entity_alive_false(self) -> None:
        hs = make_hard_state(entity_states={"spider": {"alive": False}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:spider.alive == false", hs, ss, None)

    def test_entity_state_true_with_true_string(self) -> None:
        hs = make_hard_state(entity_states={"player": {"alive": "true"}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:player.alive == true", hs, ss, None)

    def test_entity_nonexistent_entity_returns_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string(
            "entity:ghost.alive == true", hs, ss, None
        )

    def test_entity_unknown_field_returns_false(self) -> None:
        hs = make_hard_state(entity_states={"player": {"alive": True}})
        ss = make_soft_state()
        assert not evaluate_condition_string(
            "entity:player.nonexistent == true", hs, ss, None
        )

    def test_entity_no_dot_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="entity condition key must be entity.field"):
            evaluate_condition_string("entity:player", hs, ss, None)

    def test_entity_missing_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="entity condition requires operator"):
            evaluate_condition_string("entity:player.alive", hs, ss, None)

    def test_entity_numeric_field_equals(self) -> None:
        hs = make_hard_state(entity_states={"boss": {"hp": 10}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:boss.hp == 10", hs, ss, None)

    def test_entity_string_field_equals(self) -> None:
        hs = make_hard_state(entity_states={"chest": {"state": "locked"}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:chest.state == locked", hs, ss, None)

    def test_entity_numeric_float_int_equality(self) -> None:
        hs = make_hard_state(entity_states={"boss": {"hp": 10.0}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:boss.hp == 10", hs, ss, None)
        assert evaluate_condition_string("entity:boss.hp == 10.0", hs, ss, None)


class TestEvaluateConditionStringRoom:
    def test_room_visited_true(self) -> None:
        hs = make_hard_state(room_states={"axe_head": {"visited": True}})
        ss = make_soft_state()
        assert evaluate_condition_string("room:axe_head.visited == true", hs, ss, None)

    def test_room_visited_false(self) -> None:
        hs = make_hard_state(room_states={"bag_floor": {"visited": False}})
        ss = make_soft_state()
        assert evaluate_condition_string("room:bag_floor.visited == false", hs, ss, None)

    def test_room_nonexistent_returns_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string(
            "room:nonexistent.visited == true", hs, ss, None
        )

    def test_room_unknown_field_returns_false(self) -> None:
        hs = make_hard_state(room_states={"axe_head": {"visited": True}})
        ss = make_soft_state()
        assert not evaluate_condition_string(
            "room:axe_head.nonexistent == true", hs, ss, None
        )

    def test_room_no_dot_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="room condition key must be room_id.field"):
            evaluate_condition_string("room:axe_head", hs, ss, None)

    def test_room_missing_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="room condition requires operator"):
            evaluate_condition_string("room:axe_head.visited", hs, ss, None)

    def test_room_numeric_field(self) -> None:
        hs = make_hard_state(room_states={"dungeon": {"depth": 5}})
        ss = make_soft_state()
        assert evaluate_condition_string("room:dungeon.depth >= 3", hs, ss, None)


class TestEvaluateConditionStringAttitude:
    def test_attitude_gte_true(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": 5})
        assert evaluate_condition_string("attitude:korbar >= 4", hs, ss, None)

    def test_attitude_gte_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": 1})
        assert not evaluate_condition_string("attitude:korbar >= 4", hs, ss, None)

    def test_attitude_gte_boundary(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": 2})
        assert evaluate_condition_string("attitude:korbar >= 2", hs, ss, None)

    def test_attitude_gt(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": 5})
        assert evaluate_condition_string("attitude:korbar > 2", hs, ss, None)
        assert not evaluate_condition_string("attitude:korbar > 5", hs, ss, None)

    def test_attitude_lte(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": 3})
        assert evaluate_condition_string("attitude:korbar <= 3", hs, ss, None)
        assert not evaluate_condition_string("attitude:korbar <= 2", hs, ss, None)

    def test_attitude_lt(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"korbar": -3})
        assert evaluate_condition_string("attitude:korbar < 0", hs, ss, None)
        assert not evaluate_condition_string("attitude:korbar < -5", hs, ss, None)

    def test_attitude_negative_values(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={"spider": -5})
        assert evaluate_condition_string("attitude:spider == -5", hs, ss, None)

    def test_attitude_nonexistent_npc_returns_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string(
            "attitude:nonexistent >= 0", hs, ss, None
        )

    def test_attitude_missing_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="attitude condition requires operator"):
            evaluate_condition_string("attitude:korbar", hs, ss, None)

    def test_attitude_defaults_to_corpus_initial(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(npc_attitudes={})
        corpus = make_corpus()
        # korbar's attitude_limits.initial is 0 in the fixture corpus
        assert evaluate_condition_string("attitude:korbar >= 0", hs, ss, corpus)
        assert not evaluate_condition_string("attitude:korbar >= 1", hs, ss, corpus)


class TestEvaluateConditionStringTopic:
    def test_topic_present(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(dialogue_state={"topics_discussed": ["abandonment"]})
        assert evaluate_condition_string("topic:abandonment", hs, ss, None)

    def test_topic_missing(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state(dialogue_state={"topics_discussed": []})
        assert not evaluate_condition_string("topic:abandonment", hs, ss, None)

    def test_topic_with_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="topic condition must not have operator"):
            evaluate_condition_string("topic:abandonment == true", hs, ss, None)


class TestEvaluateConditionStringItem:
    def test_item_present(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["rusty_key"]})
        ss = make_soft_state()
        assert evaluate_condition_string("item:rusty_key", hs, ss, None)

    def test_item_missing(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        assert not evaluate_condition_string("item:rusty_key", hs, ss, None)

    def test_item_with_operator_raises(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        with pytest.raises(ValueError, match="item condition must not have operator"):
            evaluate_condition_string("item:rusty_key == true", hs, ss, None)


class TestEvaluateConditionExpression:
    def test_require_true(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"require": "flag:my_flag == true"})
        assert evaluate(condition, hs, ss)

    def test_require_false(self) -> None:
        hs = make_hard_state(flags={"my_flag": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"require": "flag:my_flag == true"})
        assert not evaluate(condition, hs, ss)

    def test_unless_blocks_when_true(self) -> None:
        hs = make_hard_state(flags={"injured": True})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"unless": "flag:injured == true"})
        assert not evaluate(condition, hs, ss)

    def test_unless_passes_when_false(self) -> None:
        hs = make_hard_state(flags={"injured": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"unless": "flag:injured == true"})
        assert evaluate(condition, hs, ss)

    def test_any_one_true(self) -> None:
        hs = make_hard_state(flags={"a": False, "b": True, "c": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "any": ["flag:a == true", "flag:b == true", "flag:c == true"]
        })
        assert evaluate(condition, hs, ss)

    def test_any_none_true(self) -> None:
        hs = make_hard_state(flags={"a": False, "b": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "any": ["flag:a == true", "flag:b == true"]
        })
        assert not evaluate(condition, hs, ss)

    def test_any_empty_returns_false(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"any": []})
        assert not evaluate(condition, hs, ss)

    def test_any_with_nested_conditions(self) -> None:
        hs = make_hard_state(flags={"injured": False})
        ss = make_soft_state(npc_attitudes={"korbar": 0})
        condition = ConditionExpression.model_validate({
            "any": [
                {"require": "flag:injured == true"},
                {"require": "attitude:korbar >= 0"},
            ]
        })
        assert evaluate(condition, hs, ss)

    def test_any_mixed_strings_and_expressions(self) -> None:
        hs = make_hard_state(flags={"injured": False, "my_flag": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "any": [
                "flag:my_flag == true",
                {"unless": "flag:injured == true"},
            ]
        })
        assert evaluate(condition, hs, ss)

    def test_all_all_true(self) -> None:
        hs = make_hard_state(flags={"a": True, "b": True})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "all": ["flag:a == true", "flag:b == true"]
        })
        assert evaluate(condition, hs, ss)

    def test_all_one_false(self) -> None:
        hs = make_hard_state(flags={"a": True, "b": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "all": ["flag:a == true", "flag:b == true"]
        })
        assert not evaluate(condition, hs, ss)

    def test_all_empty_returns_true(self) -> None:
        hs = make_hard_state()
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"all": []})
        assert evaluate(condition, hs, ss)

    def test_all_with_nested_conditions(self) -> None:
        hs = make_hard_state(flags={"injured": False})
        ss = make_soft_state(npc_attitudes={"korbar": 5})
        condition = ConditionExpression.model_validate({
            "all": [
                {"unless": "flag:injured == true"},
                {"require": "attitude:korbar >= 3"},
            ]
        })
        assert evaluate(condition, hs, ss)

    def test_deeply_nested(self) -> None:
        hs = make_hard_state(flags={"a": True, "b": False, "c": True})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "all": [
                "flag:a == true",
                {
                    "any": [
                        "flag:b == true",
                        "flag:c == true",
                    ]
                }
            ]
        })
        assert evaluate(condition, hs, ss)

    def test_raw_string_condition(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert evaluate("flag:my_flag == true", hs, ss)

    def test_bare_string_in_list(self) -> None:
        hs = make_hard_state(flags={"a": True})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({"all": ["flag:a == true"]})
        assert evaluate(condition, hs, ss)


class TestEvaluateWithSampleCorpus:
    def test_independent_fixtures(
        self, sample_corpus: ModuleCorpus
    ) -> None:
        hs = HardGameState.model_validate({
            "player": {"location": "axe_head", "inventory": ["toenail_sword"]},
            "flags": {
                "injured": False,
                "stunned": False,
                "spider_fled": False,
                "handkerchief_noticed": False,
                "handkerchief_moved": False,
                "padlock_unlocked": False,
            },
            "room_states": {
                "axe_head": {"visited": True},
                "axe_handle_upper": {"visited": False},
                "axe_handle_lower": {"visited": False},
                "bag_floor": {"visited": False},
                "secret_compartment": {"visited": False},
            },
            "entity_states": {
                "player": {"alive": True},
                "stuck_fly": {"alive": True},
                "spider": {"alive": True, "fled": False},
                "korbar": {"alive": True, "told_secret": False},
            },
            "turn_count": 0,
            "game_over": None,
        })
        ss = SoftGameState.model_validate({
            "soft_inventory": [],
            "room_notes": {},
            "entity_notes": {},
            "npc_attitudes": {"korbar": 3, "stuck_fly": 0, "spider": -5},
            "npc_revelations": {},
            "turn_history": [],
            "dialogue_state": {
                "active_npc": None,
                "conversation_log": [],
                "topics_discussed": [],
                "entered_turn": 0,
                "stall_counter": 0,
            },
        })

        assert evaluate_condition_string("tag:weapon", hs, ss, sample_corpus)
        assert not evaluate_condition_string("tag:armor", hs, ss, sample_corpus)
        assert evaluate_condition_string("flag:injured == false", hs, ss, sample_corpus)
        assert evaluate_condition_string("attitude:korbar >= 2", hs, ss, sample_corpus)

    def test_corpus_entities(self, sample_corpus: ModuleCorpus) -> None:
        assert "toenail_sword" in sample_corpus.entities
        assert sample_corpus.entities["toenail_sword"].tags == ["weapon"]
        assert "rusty_key" in sample_corpus.entities

    def test_real_world_trigger_condition(
        self, sample_corpus: ModuleCorpus
    ) -> None:
        hs = HardGameState.model_validate({
            "player": {"location": "bag_floor", "inventory": ["toenail_sword"]},
            "flags": {
                "injured": False,
                "stunned": False,
                "spider_fled": False,
                "handkerchief_noticed": False,
                "handkerchief_moved": False,
                "padlock_unlocked": False,
            },
            "room_states": {
                "axe_head": {"visited": True},
                "axe_handle_upper": {"visited": True},
                "axe_handle_lower": {"visited": True},
                "bag_floor": {"visited": True},
                "secret_compartment": {"visited": False},
            },
            "entity_states": {
                "player": {"alive": True},
                "stuck_fly": {"alive": False},
                "spider": {"alive": True, "fled": True},
                "korbar": {"alive": True, "told_secret": False},
            },
            "turn_count": 10,
            "game_over": None,
        })
        ss = SoftGameState.model_validate({
            "soft_inventory": ["cork"],
            "room_notes": {},
            "entity_notes": {},
            "npc_attitudes": {"korbar": 6, "stuck_fly": 0, "spider": -5},
            "npc_revelations": {},
            "turn_history": [],
            "dialogue_state": {
                "active_npc": None,
                "conversation_log": [],
                "topics_discussed": [],
                "entered_turn": 0,
                "stall_counter": 0,
            },
        })

        assert evaluate_condition_string(
            "attitude:korbar >= 4", hs, ss, sample_corpus
        )

        assert evaluate_condition_string(
            "flag:injured == false", hs, ss, sample_corpus
        )

        assert evaluate_condition_string(
            "entity:player.alive == true", hs, ss, sample_corpus
        )

        assert not evaluate_condition_string(
            "entity:stuck_fly.alive == true", hs, ss, sample_corpus
        )

        assert evaluate_condition_string(
            "entity:spider.fled == true", hs, ss, sample_corpus
        )

        assert evaluate_condition_string(
            "attitude:korbar >= 2", hs, ss, sample_corpus
        )


class TestEdgeCases:
    def test_comparison_bool_with_numeric_op_raises(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        with pytest.raises(ValueError, match="Comparison operator"):
            evaluate_condition_string("flag:my_flag >= true", hs, ss, None)

    def test_comparison_numeric_value(self) -> None:
        hs = make_hard_state(
            entity_states={"boss": {"hp": 5}},
            room_states={"pit": {"depth": 3}},
        )
        ss = make_soft_state(npc_attitudes={"npc": -2})

        assert evaluate_condition_string("entity:boss.hp >= 3", hs, ss, None)
        assert evaluate_condition_string("entity:boss.hp <= 10", hs, ss, None)
        assert evaluate_condition_string("room:pit.depth > 2", hs, ss, None)
        assert evaluate_condition_string("room:pit.depth < 5", hs, ss, None)
        assert evaluate_condition_string("attitude:npc < 0", hs, ss, None)
        assert evaluate_condition_string("attitude:npc >= -3", hs, ss, None)

    def test_equality_with_string(self) -> None:
        hs = make_hard_state(
            entity_states={"chest": {"state": "open"}},
            room_states={"tower": {"weather": "stormy"}},
        )
        ss = make_soft_state(npc_attitudes={"npc": 0})
        assert evaluate_condition_string("entity:chest.state == open", hs, ss, None)
        assert not evaluate_condition_string("entity:chest.state == closed", hs, ss, None)
        assert evaluate_condition_string("room:tower.weather == stormy", hs, ss, None)
        assert evaluate_condition_string("attitude:npc == 0", hs, ss, None)

    def test_operator_comparison_with_string_value_raises(self) -> None:
        hs = make_hard_state(
            entity_states={"chest": {"state": "open"}}
        )
        ss = make_soft_state()
        with pytest.raises(ValueError, match="Cannot interpret"):
            evaluate_condition_string("entity:chest.state >= open", hs, ss, None)

    def test_flag_equals_non_bool_string(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert not evaluate_condition_string("flag:my_flag == banana", hs, ss, None)

    def test_entity_state_bool_true_value(self) -> None:
        hs = make_hard_state(entity_states={"player": {"alive": True}})
        ss = make_soft_state()
        assert evaluate_condition_string("entity:player.alive == true", hs, ss, None)

    def test_entity_state_truthy_non_bool(self) -> None:
        hs = make_hard_state(entity_states={"obj": {"active": 1}})
        ss = make_soft_state()
        assert not evaluate_condition_string("entity:obj.active == true", hs, ss, None)
        assert evaluate_condition_string("entity:obj.active == 1", hs, ss, None)

    def test_float_comparisons(self) -> None:
        hs = make_hard_state(
            entity_states={"boss": {"hp": 3.5}},
        )
        ss = make_soft_state()
        assert evaluate_condition_string("entity:boss.hp >= 3.0", hs, ss, None)
        assert evaluate_condition_string("entity:boss.hp <= 4.0", hs, ss, None)
        assert not evaluate_condition_string("entity:boss.hp >= 4.0", hs, ss, None)

    def test_boolean_true_comparison_with_numeric_op_raises(self) -> None:
        hs = make_hard_state(entity_states={"player": {"alive": True}})
        ss = make_soft_state()
        with pytest.raises(ValueError, match="Cannot compare boolean"):
            evaluate_condition_string("entity:player.alive >= 0", hs, ss, None)

    def test_evaluate_require_convenience(self) -> None:
        hs = make_hard_state(flags={"my_flag": True})
        ss = make_soft_state()
        assert evaluate_require("flag:my_flag == true", hs, ss)
        assert not evaluate_require("flag:my_flag == false", hs, ss)

    def test_condition_expression_with_all_mixed_uses_corpus_for_tag(self) -> None:
        hs = make_hard_state(
            player={"location": "axe_head", "inventory": ["sword"]},
            flags={"injured": False},
        )
        ss = make_soft_state()
        corpus = make_corpus()
        condition = ConditionExpression.model_validate({
            "all": [
                "tag:weapon",
                {"unless": "flag:injured == true"},
            ]
        })
        assert evaluate(condition, hs, ss, corpus)

    def test_condition_expression_with_all_mixed_tag_fails_when_injured(self) -> None:
        hs = make_hard_state(
            player={"location": "axe_head", "inventory": ["sword"]},
            flags={"injured": True},
        )
        ss = make_soft_state()
        corpus = make_corpus()
        condition = ConditionExpression.model_validate({
            "all": [
                "tag:weapon",
                {"unless": "flag:injured == true"},
            ]
        })
        assert not evaluate(condition, hs, ss, corpus)

    def test_any_evaluates_all_when_all_false(self) -> None:
        # When every item in an `any` is False, Python's any() must evaluate
        # all of them — it only short-circuits on the first True.
        hs = make_hard_state(flags={"a": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "any": ["flag:a == true", "bad:syntax:here"]
        })
        with pytest.raises(ValueError):
            evaluate(condition, hs, ss)

    def test_unless_with_tag_condition(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["sword"]})
        ss = make_soft_state()
        corpus = make_corpus()
        condition = ConditionExpression.model_validate({
            "unless": "tag:weapon"
        })
        assert not evaluate(condition, hs, ss, corpus)

    def test_unless_with_inventory_condition(self) -> None:
        hs = make_hard_state(player={"location": "axe_head", "inventory": ["rusty_key"]})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "unless": "inventory:rusty_key"
        })
        assert not evaluate(condition, hs, ss)

    def test_all_short_circuits(self) -> None:
        hs = make_hard_state(flags={"a": False})
        ss = make_soft_state()
        condition = ConditionExpression.model_validate({
            "all": ["flag:a == true", "bad:syntax:here"]
        })
        assert not evaluate(condition, hs, ss)
