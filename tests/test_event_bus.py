# My GM is AI — reaction / event-bus tests for Option B turn boundary
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import pytest

from mgmai.engine.event_bus import (
    _disabled_once,
    _resolve_self,
    dispatch_reactions,
    find_matching_reactions,
    reset_disabled_once,
)
from mgmai.engine.engine import _derive_state_events
from mgmai.engine.engine import resolve
from mgmai.engine.resolver import _apply_result, resolve_action
from mgmai.models.actions import HardStateChanges, InteractAction
from mgmai.models.corpus import (
    ConditionExpression,
    Entity,
    Interaction,
    Mechanic,
    Reaction,
    ReactionEffects,
    Result,
    Room,
    StatModifier,
)
from mgmai.models.hard_state import HardGameState


class TestApplyResultAccumulator:
    """_apply_result must populate HardStateChanges, not mutate hard."""

    def test_set_entity_state_accumulates_not_mutates(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        original = dict(hard.entity_states.get("korbar", {}))

        result = Result(set_entity_state={"korbar": {"told_secret": True}})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)

        assert hard.entity_states.get("korbar") == original
        state_manager.apply_hard_changes(changes)
        assert hard.entity_states["korbar"]["told_secret"] is True

    def test_set_room_state_accumulates_not_mutates(self, state_manager):
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        room_id = "bag_floor"
        original = dict(hard.room_states.get(room_id, {}))

        result = Result(set_room_state={room_id: {"foo": "bar"}})
        changes = HardStateChanges()
        _apply_result(result, changes, [], [], hard, corpus)

        assert hard.room_states.get(room_id) == original
        state_manager.apply_hard_changes(changes)
        assert hard.room_states[room_id]["foo"] == "bar"


class TestDispatchReactionsAccumulator:
    """dispatch_reactions merges state mutations into a changes object."""

    def test_result_effects_merge_into_changes(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        reaction = Reaction(
            id="r1",
            on="turn.start",
            effects=ReactionEffects(
                result=Result(set_flag={"reaction_fired": True})
            ),
        )
        changes = HardStateChanges()
        dispatch_reactions(
            [(reaction, None)], hard, soft, corpus, state_manager,
            changes=changes,
        )
        assert changes.flags_set == {"reaction_fired": True}
        assert "reaction_fired" not in hard.flags

        state_manager.apply_hard_changes(changes)
        assert hard.flags["reaction_fired"] is True


class TestImmediateReactionsInResolver:
    """Immediate reactions fire synchronously when events are emitted."""

    def test_immediate_interaction_used_fires_before_check(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        # Add a harmless "greet" interaction to Korbar.
        korbar = corpus.entities["korbar"]
        korbar.interactions.append(Interaction(
            id="greet",
            label="Greet Korbar",
            result=Result(narrative="Korbar grunts noncommittally."),
        ))

        # Add an immediate reaction to the room that sets a flag on
        # interaction.used.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="imm_interact",
            on="interaction.used",
            phase="immediate",
            effects=ReactionEffects(
                result=Result(set_flag={"immediate_fired": True})
            ),
        ))

        # Put the player in bag_floor.
        hard.player.location = "bag_floor"
        action = InteractAction(
            action_type="interact",
            target="korbar",
            interaction_id="greet",
            detail="greet korbar",
        )

        result = resolve_action(action, hard, soft, corpus, state_manager)
        assert result.success is True
        # Immediate reaction effects are accumulated into the result so the
        # engine can apply them in a single batch at the end of the turn.
        assert result.immediate_changes.flags_set == {"immediate_fired": True}
        assert "immediate_fired" not in hard.flags


class TestOptionBTurnBoundary:
    """State-change events are derived once from the merged diff."""

    def test_turn_start_reaction_runs_before_action(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        # A turn.start reaction sets a flag that the action's interaction
        # condition requires.  If turn.start fires before the action, the
        # interaction succeeds; if after, it fails.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="turn_start_set_flag",
            on="turn.start",
            effects=ReactionEffects(
                result=Result(set_flag={"turn_start_flag": True})
            ),
        ))

        # Add a conditional interaction that requires the flag.
        korbar = corpus.entities["korbar"]
        korbar.interactions.append(Interaction(
            id="conditional_greet",
            label="Conditional greet",
            condition=ConditionExpression(require="flag:turn_start_flag == true"),
            result=Result(narrative="Korbar nods."),
        ))

        hard.player.location = "bag_floor"
        action = InteractAction(
            action_type="interact",
            target="korbar",
            interaction_id="conditional_greet",
            detail="greet korbar",
        )

        engine_result = resolve(action, state_manager)
        assert engine_result.success is True
        assert any("Korbar nods" in s for s in (engine_result.triggered_narration or []))


class TestFindMatchingReactions:
    """Test scoping, priority ordering, once flag, and alive/fled filtering."""

    def setup_method(self):
        reset_disabled_once()

    def test_entity_scoped_reaction(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # Korbar is in bag_floor, alive, not fled
        entity = corpus.entities["korbar"]
        entity.reactions.append(Reaction(
            id="korbar_react",
            on="room.entered",
            effects=ReactionEffects(result=Result(narrative="Korbar reacts")),
        ))

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "korbar_react" in ids

    def test_entity_not_active_when_dead(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        entity = corpus.entities["korbar"]
        entity.reactions.clear()
        entity.reactions.append(Reaction(
            id="dead_react",
            on="room.entered",
            effects=ReactionEffects(result=Result(narrative="ghost")),
        ))
        hard.entity_states.setdefault("korbar", {})["alive"] = False

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "dead_react" not in ids

    def test_entity_not_active_when_fled(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        entity = corpus.entities["korbar"]
        entity.reactions.clear()
        entity.reactions.append(Reaction(
            id="fled_react",
            on="room.entered",
            effects=ReactionEffects(result=Result(narrative="gone")),
        ))
        hard.entity_states.setdefault("korbar", {})["fled"] = True

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "fled_react" not in ids

    def test_room_scoped_reaction(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.clear()
        room.reactions.append(Reaction(
            id="room_react",
            on="flag.set",
            effects=ReactionEffects(result=Result(narrative="room reacts")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "room_react" in ids

    def test_mechanic_scoped_reaction(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus

        mech = corpus.mechanics.get("bag_win")
        if mech is None:
            pytest.skip("No bag_win mechanic in fixture")
        mech.reactions.clear()
        mech.reactions.append(Reaction(
            id="mech_react",
            on="turn.end",
            effects=ReactionEffects(result=Result(narrative="mechanic reacts")),
        ))

        matches = find_matching_reactions(
            "turn.end", {"turn_number": 1}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "mech_react" in ids

    def test_priority_ordering(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.clear()
        room.reactions.append(Reaction(
            id="low_priority",
            on="flag.set",
            priority=10,
            effects=ReactionEffects(result=Result(narrative="low")),
        ))
        room.reactions.append(Reaction(
            id="high_priority",
            on="flag.set",
            priority=1,
            effects=ReactionEffects(result=Result(narrative="high")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert ids.index("high_priority") < ids.index("low_priority")

    def test_once_flag_disables_after_firing(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.clear()
        room.reactions.append(Reaction(
            id="once_react",
            on="flag.set",
            once=True,
            effects=ReactionEffects(result=Result(narrative="once")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        assert len(matches) == 1

        # Dispatch (this disables the once reaction)
        dispatch_reactions(matches, hard, soft, corpus, state_manager)

        # Should not match anymore
        matches2 = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches2]
        assert "once_react" not in ids

    def test_condition_filtering(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.clear()
        room.reactions.append(Reaction(
            id="conditional",
            on="flag.set",
            condition=ConditionExpression(require="flag:spider_fled == true"),
            effects=ReactionEffects(result=Result(narrative="cond")),
        ))

        # spider_fled is False in fixture, so condition should NOT match
        matches = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        assert not any(r.id == "conditional" for r, _ in matches)

        # Flip the flag
        hard.flags["spider_fled"] = True
        matches2 = find_matching_reactions(
            "flag.set", {"flag_name": "x"}, hard, soft, corpus,
        )
        assert any(r.id == "conditional" for r, _ in matches2)


class TestSelfResolution:
    """Test 'self' replacement in entity-scoped reactions."""

    def test_self_in_trigger_encounter(self):
        from mgmai.models.corpus import GameOverTrigger
        effects = ReactionEffects(trigger_encounter="self")
        resolved = _resolve_self(effects, "spider")
        assert resolved.trigger_encounter == "spider"

    def test_self_in_trigger_dialogue(self):
        effects = ReactionEffects(trigger_dialogue="self")
        resolved = _resolve_self(effects, "korbar")
        assert resolved.trigger_dialogue == "korbar"

    def test_self_in_set_entity_state(self):
        effects = ReactionEffects(
            result=Result(set_entity_state={"self": {"alive": False}})
        )
        resolved = _resolve_self(effects, "spider")
        assert "spider" in resolved.result.set_entity_state
        assert "self" not in resolved.result.set_entity_state

    def test_self_in_adjust_attitude(self):
        effects = ReactionEffects(
            result=Result(adjust_attitude={"self": -5})
        )
        resolved = _resolve_self(effects, "korbar")
        assert "korbar" in resolved.result.adjust_attitude
        assert "self" not in resolved.result.adjust_attitude

    def test_no_owner_returns_unchanged(self):
        effects = ReactionEffects(trigger_encounter="self")
        resolved = _resolve_self(effects, None)
        assert resolved.trigger_encounter == "self"


class TestStateChangeEventDerivation:
    """Test _derive_state_events produces correct events from diffs."""

    def test_flag_set_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(
            player=PlayerState(location="room1"),
            flags={"new_flag": True},
        )
        changes = HardStateChanges(flags_set={"new_flag": True})
        old_flags = {}
        events = _derive_state_events(changes, old_stats={}, old_entity_states={}, hard=hard, old_flags=old_flags)
        assert ("flag.set", {"flag_name": "new_flag"}) in events

    def test_flag_cleared_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(
            player=PlayerState(location="room1"),
            flags={},
        )
        changes = HardStateChanges(flags_cleared=["old_flag"])
        old_flags = {"old_flag": True}
        events = _derive_state_events(changes, old_flags=old_flags, old_stats={}, old_entity_states={}, hard=hard)
        assert ("flag.cleared", {"flag_name": "old_flag"}) in events

    def test_entity_state_changed_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(
            entity_state_changes={"korbar": {"told_secret": True}}
        )
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert any(
            e[0] == "entity_state.changed"
            and e[1]["entity_id"] == "korbar"
            and e[1]["field"] == "told_secret"
            for e in events
        )

    def test_stat_changed_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(
            player=PlayerState(location="room1", stats={"STR": 15}),
        )
        changes = HardStateChanges(stat_modifiers={"STR": StatModifier(mode="delta", value=2)})
        old_stats = {"STR": 13}
        events = _derive_state_events(changes, old_flags={}, old_stats=old_stats, old_entity_states={}, hard=hard)
        assert any(
            e[0] == "stat.changed"
            and e[1]["stat_name"] == "STR"
            and e[1]["delta"] == 2
            for e in events
        )

    def test_attitude_changed_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(
            entity_state_changes={"korbar": {"attitude": -3}}
        )
        old_entity_states = {"korbar": {"attitude": 0}}
        events = _derive_state_events(
            changes, old_flags={}, old_stats={},
            old_entity_states=old_entity_states, hard=hard,
        )
        assert any(
            e[0] == "attitude.changed"
            and e[1]["npc_id"] == "korbar"
            and e[1]["delta"] == -3
            for e in events
        )

    def test_item_acquired_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(inventory_added=["rusty_key"])
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert ("item.acquired", {"item_id": "rusty_key", "source": "interaction"}) in events

    def test_item_lost_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(inventory_removed=["rusty_key"])
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert ("item.lost", {"item_id": "rusty_key", "reason": "interaction"}) in events

    def test_no_events_for_empty_changes(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges()
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert events == []
