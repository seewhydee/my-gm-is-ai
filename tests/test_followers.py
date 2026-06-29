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

"""Tests for NPC follower mechanic."""

import copy
import json
from pathlib import Path

import pytest

from mgmai.engine.engine import _build_room_after
from mgmai.engine.utils import get_following_npc_ids, inject_following_npcs
from mgmai.engine.resolver import (
    _find_entity_in_room_followers,
    resolve_examine,
    resolve_interact,
    resolve_talk,
    resolve_transfer,
)
from mgmai.engine.dialogue import check_room_change_exit
from mgmai.models.actions import (
    ExamineAction,
    InteractAction,
    TalkAction,
    TransferAction,
)
from mgmai.models.briefing import BriefingEntity
from mgmai.models.corpus import Interaction, Result, ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_hard(**overrides):
    data = json.loads((FIXTURES_DIR / "hard-state.json").read_text())
    for eid, fields in overrides.items():
        data.setdefault("entity_states", {}).setdefault(eid, {}).update(fields)
    return HardGameState.model_validate(data)


def _load_soft():
    return SoftGameState.model_validate(json.loads((FIXTURES_DIR / "soft-state.json").read_text()))


def _load_corpus(sample_corpus_dict):
    return ModuleCorpus.model_validate(sample_corpus_dict)


class TestGetFollowingNpcIds:
    def test_none_following(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard()
        assert get_following_npc_ids(hard, corpus) == []

    def test_korbar_following(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"following": True})
        assert "korbar" in get_following_npc_ids(hard, corpus)

    def test_following_ignores_dead(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"alive": False, "following": True})
        assert "korbar" not in get_following_npc_ids(hard, corpus)

    def test_following_ignores_non_npc(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(toenail_sword={"following": True})
        assert "toenail_sword" not in get_following_npc_ids(hard, corpus)


class TestInjectFollowingNpcs:
    @pytest.fixture
    def _setup(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"following": True})
        soft = _load_soft()
        return hard, corpus, soft

    def test_injects_follower(self, _setup):
        hard, corpus, soft = _setup
        entities: list[BriefingEntity] = []
        inject_following_npcs(entities, "axe_head", hard, soft, corpus)
        assert len(entities) == 1
        assert entities[0].id == "korbar"
        assert entities[0].type == "npc"

    def test_no_inject_if_already_present(self, _setup):
        hard, corpus, soft = _setup
        entities: list[BriefingEntity] = [
            BriefingEntity(
                id="korbar", name="Korbar", type="npc",
                description="test", state={}, entity_notes=[], soft_items=[],
            )
        ]
        inject_following_npcs(entities, "axe_head", hard, soft, corpus)
        assert len(entities) == 1

    def test_no_inject_if_not_following(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard()
        soft = _load_soft()
        entities: list[BriefingEntity] = []
        inject_following_npcs(entities, "axe_head", hard, soft, corpus)
        assert len(entities) == 0

    def test_no_inject_if_hidden(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(spider={"following": True, "hidden": True})
        soft = _load_soft()
        entities: list[BriefingEntity] = []
        inject_following_npcs(entities, "bag_floor", hard, soft, corpus)
        assert len(entities) == 0


class TestFindEntityInRoomFollowers:
    @pytest.fixture
    def _setup(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"following": True})
        return hard, corpus

    def test_finds_follower_not_in_entities_present(self, _setup):
        hard, corpus = _setup
        room = corpus.rooms["axe_head"]
        result = _find_entity_in_room_followers("korbar", "axe_head", room, hard, corpus)
        assert result is not None
        assert result.type == "npc"

    def test_still_finds_static_entity(self, _setup):
        hard, corpus = _setup
        room = corpus.rooms["bag_floor"]
        result = _find_entity_in_room_followers("korbar", "bag_floor", room, hard, corpus)
        assert result is not None

    def test_nonexistent_entity(self, _setup):
        hard, corpus = _setup
        room = corpus.rooms["axe_head"]
        result = _find_entity_in_room_followers("nonexistent", "axe_head", room, hard, corpus)
        assert result is None


class TestCheckRoomChangeExit:
    @pytest.fixture
    def _setup(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"following": True})
        soft = _load_soft()
        return hard, corpus, soft

    def test_follower_stays_in_dialogue(self, _setup):
        hard, corpus, soft = _setup
        soft.dialogue_state.active_npc = "korbar"
        result = check_room_change_exit(
            soft, "bag_floor", "axe_handle_lower", corpus, hard,
        )
        assert result is None

    def test_non_follower_exits_dialogue(self, _setup):
        hard, corpus, soft = _setup
        soft.dialogue_state.active_npc = "stuck_fly"
        result = check_room_change_exit(
            soft, "axe_handle_upper", "axe_handle_lower", corpus, hard,
        )
        assert result is not None


class TestResolveWithFollower:
    @pytest.fixture
    def _setup(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(korbar={"following": True})
        soft = _load_soft()
        return hard, soft, corpus

    def test_talk_to_follower_in_any_room(self, _setup):
        hard, soft, corpus = _setup
        hard.player.location = "axe_head"
        result = resolve_talk(
            TalkAction(action_type="talk", target="korbar", detail="Hello"),
            hard, soft, corpus,
        )
        assert result.success is True

    def test_examine_follower_in_any_room(self, _setup):
        hard, soft, corpus = _setup
        hard.player.location = "axe_head"
        result = resolve_examine(
            ExamineAction(action_type="examine", target="korbar", detail="Look"),
            hard, soft, corpus,
        )
        assert result.success is True

    def test_transfer_to_follower_in_any_room(self, _setup):
        hard, soft, corpus = _setup
        hard.player.location = "axe_head"
        hard.player.inventory = ["toenail_sword"]
        result = resolve_transfer(
            TransferAction(action_type="transfer", target="korbar", given_items=["toenail_sword"], detail="Give"),
            hard, soft, corpus,
        )
        assert result.success is True

    def test_interact_follower_in_any_room(self, _setup):
        hard, soft, corpus = _setup
        korbar = corpus.entities["korbar"]
        korbar.interactions.append(
            Interaction(id="greet", description="Greet Korbar", result=Result(narrative="Korbar nods."))
        )
        hard.player.location = "axe_head"
        result = resolve_interact(
            InteractAction(action_type="interact", target="korbar", interaction_id="greet", detail="Greet"),
            hard, soft, corpus,
        )
        assert result.success is True

    def test_move_keeps_follower_visible(self, _setup):
        hard, soft, corpus = _setup
        hard.player.location = "bag_floor"
        soft.dialogue_state.active_npc = "korbar"

        dialogue_exited = check_room_change_exit(
            soft, "bag_floor", "axe_handle_lower", corpus, hard,
        )
        assert dialogue_exited is None
        assert soft.dialogue_state.active_npc == "korbar"

        hard.player.location = "axe_handle_lower"
        room_after = _build_room_after("axe_handle_lower", hard, soft, corpus)
        visible_ids = [e.id for e in room_after.entities_visible]
        assert "korbar" in visible_ids


class TestBuildRoomAfterHidden:
    """_build_room_after filters hidden entities."""

    def test_hidden_entity_filtered(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(spider={"hidden": True})
        soft = _load_soft()
        room_after = _build_room_after("axe_handle_lower", hard, soft, corpus)
        visible_ids = [e.id for e in room_after.entities_visible]
        assert "spider" not in visible_ids

    def test_hidden_entity_appears_when_revealed(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard(spider={"hidden": False})
        soft = _load_soft()
        room_after = _build_room_after("axe_handle_lower", hard, soft, corpus)
        visible_ids = [e.id for e in room_after.entities_visible]
        assert "spider" in visible_ids

    def test_entity_without_hidden_field_appears(self, sample_corpus_dict):
        corpus = _load_corpus(sample_corpus_dict)
        hard = _load_hard()
        soft = _load_soft()
        room_after = _build_room_after("bag_floor", hard, soft, corpus)
        visible_ids = [e.id for e in room_after.entities_visible]
        assert "korbar" in visible_ids
