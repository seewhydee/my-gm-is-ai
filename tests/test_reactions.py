# My GM is AI — reaction model validation tests
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import pytest
from pydantic import ValidationError

from mgmai.models.corpus import (
    GameOverTrigger,
    Mechanic,
    Reaction,
    ReactionEffects,
    Result,
)
from tests.helpers import _mk_encounter_rule


class TestReactionEffects:
    def test_requires_at_least_one_effect(self):
        with pytest.raises(ValidationError, match="at least one effect"):
            ReactionEffects()

    def test_result_only(self):
        effects = ReactionEffects(result=Result(narrative="hello"))
        assert effects.result is not None
        assert effects.trigger_encounter is None

    def test_trigger_encounter_only(self):
        effects = ReactionEffects(trigger_encounter="spider")
        assert effects.trigger_encounter == "spider"
        assert effects.result is None

    def test_trigger_dialogue_only(self):
        effects = ReactionEffects(trigger_dialogue="korbar")
        assert effects.trigger_dialogue == "korbar"

    def test_game_over_only(self):
        effects = ReactionEffects(game_over=GameOverTrigger(type="lose", trigger_id="death"))
        assert effects.game_over is not None

    def test_empty_result_rejected(self):
        with pytest.raises(ValidationError, match="at least one effect"):
            ReactionEffects(result=Result())

    def test_combined_effects(self):
        effects = ReactionEffects(
            result=Result(set_flag={"x": True}),
            trigger_encounter="spider",
        )
        assert effects.result is not None
        assert effects.trigger_encounter == "spider"


class TestReaction:
    def test_basic_reaction(self):
        r = Reaction(
            id="r1",
            on="flag.set",
            effect=ReactionEffects(result=Result(set_flag={"y": True})),
        )
        assert r.id == "r1"
        assert r.on == "flag.set"
        assert r.phase == "deferred"
        assert r.once is False
        assert r.priority == 0

    def test_immediate_phase_valid_for_allowed_events(self):
        for event in ("interaction.used", "traversal.attempted", "room.entered"):
            r = Reaction(
                id=f"r_{event}",
                on=event,
                phase="immediate",
                effect=ReactionEffects(result=Result(narrative="x")),
            )
            assert r.phase == "immediate"

    def test_immediate_phase_rejected_for_disallowed_events(self):
        for event in ("flag.set", "turn.start", "turn.end", "stat.changed"):
            with pytest.raises(ValidationError, match="immediate"):
                Reaction(
                    id=f"r_{event}",
                    on=event,
                    phase="immediate",
                    effect=ReactionEffects(result=Result(narrative="x")),
                )

    def test_deferred_phase_allowed_for_any_event(self):
        r = Reaction(
            id="r1",
            on="flag.set",
            phase="deferred",
            effect=ReactionEffects(result=Result(narrative="x")),
        )
        assert r.phase == "deferred"

    def test_once_flag(self):
        r = Reaction(
            id="r1",
            on="room.entered",
            once=True,
            effect=ReactionEffects(result=Result(narrative="x")),
        )
        assert r.once is True

    def test_priority(self):
        r = Reaction(
            id="r1",
            on="room.entered",
            priority=10,
            effect=ReactionEffects(result=Result(narrative="x")),
        )
        assert r.priority == 10

    def test_condition(self):
        r = Reaction(
            id="r1",
            on="room.entered",
            condition={"require": "flag:x == true"},
            effect=ReactionEffects(result=Result(narrative="x")),
        )
        assert r.condition is not None


class TestMechanicReactionOnly:
    def test_reaction_only_mechanic_valid(self):
        m = Mechanic(
            id="m1",
            description="test",
            reactions=[
                Reaction(
                    id="r1",
                    on="flag.set",
                    effect=ReactionEffects(result=Result(set_flag={"x": True})),
                )
            ],
        )
        assert len(m.reactions) == 1

    def test_empty_mechanic_rejected(self):
        with pytest.raises(ValidationError, match="must have at least one"):
            Mechanic(id="m1")

    def test_game_over_mechanic_still_works(self):
        m = Mechanic(
            id="m1",
            type="lose",
            condition={"require": "flag:dead == true"},
            trigger_id="death",
        )
        assert m.type == "lose"

    def test_encounter_mechanic_still_works(self):
        from mgmai.models.corpus import ConditionExpression
        m = Mechanic(
            id="m1",
            rules=[_mk_encounter_rule(
                condition=ConditionExpression(require="flag:x == true"),
                outcome="death",
            )],
        )
        assert m.rules is not None

    def test_game_over_and_encounter_both_rejected(self):
        from mgmai.models.corpus import ConditionExpression
        with pytest.raises(ValidationError, match="not both"):
            Mechanic(
                id="m1",
                type="lose",
                condition={"require": "flag:dead == true"},
                trigger_id="death",
                rules=[_mk_encounter_rule(
                    condition=ConditionExpression(require="flag:x == true"),
                    outcome="death",
                )],
            )
