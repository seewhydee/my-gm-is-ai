# My GM is AI — reaction / event-bus tests for Option B turn boundary
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import pytest

from mgmai.engine.event_bus import (
    MAX_RECURSION_DEPTH,
    _disabled_once,
    _resolve_self,
    dispatch_reactions,
    find_matching_reactions,
    reset_disabled_once,
)
from mgmai.engine.engine import _derive_state_events
from mgmai.engine.engine import resolve
from mgmai.engine.resolver import _apply_result, resolve_action
from mgmai.models.actions import HardStateChanges, InteractAction, TalkAction
from mgmai.models.corpus import (
    ConditionExpression,
    Entity,
    GameOverTrigger,
    Interaction,
    Mechanic,
    Reaction,
    ReactionEffects,
    Result,
    Room,
    StatModifier,
)
from mgmai.models.hard_state import HardGameState
from mgmai.state.manager import StateManager
from tests.helpers import _mk_encounter_rule


@pytest.fixture
def fresh_state_manager(state_manager):
    """Return a StateManager with a deep-copied corpus so tests can mutate it."""
    import copy
    manager = StateManager()
    manager.corpus = copy.deepcopy(state_manager.corpus)
    manager.hard_state = copy.deepcopy(state_manager.hard_state)
    manager.soft_state = copy.deepcopy(state_manager.soft_state)
    manager._adventure_dir = state_manager._adventure_dir
    return manager


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
            effect=ReactionEffects(
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
            description="Greet Korbar",
            result=Result(narrative="Korbar grunts noncommittally."),
        ))

        # Add an immediate reaction to the room that sets a flag on
        # interaction.used.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="imm_interact",
            on="interaction.used",
            phase="immediate",
            effect=ReactionEffects(
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
            effect=ReactionEffects(
                result=Result(set_flag={"turn_start_flag": True})
            ),
        ))

        # Add a conditional interaction that requires the flag.
        korbar = corpus.entities["korbar"]
        korbar.interactions.append(Interaction(
            id="conditional_greet",
            description="Conditional greet",
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
            effect=ReactionEffects(result=Result(narrative="Korbar reacts")),
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
        saved_reactions = list(entity.reactions)
        entity.reactions.clear()
        entity.reactions.append(Reaction(
            id="dead_react",
            on="room.entered",
            effect=ReactionEffects(result=Result(narrative="ghost")),
        ))
        hard.entity_states.setdefault("korbar", {})["alive"] = False

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "dead_react" not in ids
        entity.reactions.clear()
        entity.reactions.extend(saved_reactions)

    def test_fled_field_no_longer_suppresses_reactions(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        entity = corpus.entities["korbar"]
        saved_reactions = list(entity.reactions)
        entity.reactions.clear()
        entity.reactions.append(Reaction(
            id="fled_react",
            on="room.entered",
            effect=ReactionEffects(result=Result(narrative="gone")),
        ))
        hard.entity_states.setdefault("korbar", {})["fled"] = True

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "fled_react" in ids
        entity.reactions.clear()
        entity.reactions.extend(saved_reactions)

    def test_entity_not_active_when_location_null(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        entity = corpus.entities["korbar"]
        saved_reactions = list(entity.reactions)
        entity.reactions.clear()
        entity.reactions.append(Reaction(
            id="fled_react",
            on="room.entered",
            effect=ReactionEffects(result=Result(narrative="gone")),
        ))
        hard.room_contains["bag_floor"].pop("korbar", None)

        matches = find_matching_reactions(
            "room.entered", {"room_id": "bag_floor"}, hard, soft, corpus,
        )
        ids = [r.id for r, _ in matches]
        assert "fled_react" not in ids
        entity.reactions.clear()
        entity.reactions.extend(saved_reactions)

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
            effect=ReactionEffects(result=Result(narrative="room reacts")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
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
            effect=ReactionEffects(result=Result(narrative="mechanic reacts")),
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
            effect=ReactionEffects(result=Result(narrative="low")),
        ))
        room.reactions.append(Reaction(
            id="high_priority",
            on="flag.set",
            priority=1,
            effect=ReactionEffects(result=Result(narrative="high")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
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
            effect=ReactionEffects(result=Result(narrative="once")),
        ))

        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
        )
        assert len(matches) == 1

        # Dispatch (this disables the once reaction)
        dispatch_reactions(matches, hard, soft, corpus, state_manager)

        # Should not match anymore
        matches2 = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
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
            effect=ReactionEffects(result=Result(narrative="cond")),
        ))

        # spider_fled is False in fixture, so condition should NOT match
        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
        )
        assert not any(r.id == "conditional" for r, _ in matches)

        # Flip the flag
        hard.flags["spider_fled"] = True
        matches2 = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, hard, soft, corpus,
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
        assert ("flag.set", {"flag_id": "new_flag"}) in events

    def test_flag_cleared_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(
            player=PlayerState(location="room1"),
            flags={},
        )
        changes = HardStateChanges(flags_cleared=["old_flag"])
        old_flags = {"old_flag": True}
        events = _derive_state_events(changes, old_flags=old_flags, old_stats={}, old_entity_states={}, hard=hard)
        assert ("flag.cleared", {"flag_id": "old_flag"}) in events

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
        changes = HardStateChanges(inventory_added={"rusty_key": 1})
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert ("item.acquired", {"item_id": "rusty_key", "count": 1, "source": "interaction"}) in events

    def test_item_lost_event(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(inventory_removed={"rusty_key": 1})
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert ("item.lost", {"item_id": "rusty_key", "count": 1, "reason": "interaction"}) in events

    def test_item_event_provenance(self):
        """The derived source/reason comes from the provenance maps recorded
        where inventory is mutated (transfer / examine / equip / unequip)."""
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(
            inventory_added={"gift": 1, "sheathed_sword": 1},
            inventory_removed={"potion": 1, "blade": 1},
            inventory_added_sources={"gift": "transfer", "sheathed_sword": "unequip"},
            inventory_removed_reasons={"potion": "transfer", "blade": "equip"},
        )
        events = _derive_state_events(
            changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard,
        )
        assert ("item.acquired", {"item_id": "gift", "count": 1, "source": "transfer"}) in events
        assert ("item.acquired", {"item_id": "sheathed_sword", "count": 1, "source": "unequip"}) in events
        assert ("item.lost", {"item_id": "potion", "count": 1, "reason": "transfer"}) in events
        assert ("item.lost", {"item_id": "blade", "count": 1, "reason": "equip"}) in events

    def test_item_event_with_count(self):
        """item.acquired / item.lost include the count for stackable items."""
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges(
            inventory_added={"gold_coin": 50},
            inventory_removed={"arrow": 10},
            inventory_added_sources={"gold_coin": "transfer"},
            inventory_removed_reasons={"arrow": "transfer"},
        )
        events = _derive_state_events(
            changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard,
        )
        assert ("item.acquired", {"item_id": "gold_coin", "count": 50, "source": "transfer"}) in events
        assert ("item.lost", {"item_id": "arrow", "count": 10, "reason": "transfer"}) in events

    def test_no_events_for_empty_changes(self):
        from mgmai.models.hard_state import PlayerState
        hard = HardGameState(player=PlayerState(location="room1"))
        changes = HardStateChanges()
        events = _derive_state_events(changes, old_flags={}, old_stats={}, old_entity_states={}, hard=hard)
        assert events == []


class TestReactionTriggerEncounter:
    """Deferred reactions can trigger encounters via trigger_encounter."""

    def test_deferred_trigger_encounter_runs_mechanic_rules(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # Add a simple encounter mechanic that sets a flag when it fires.
        corpus.mechanics["test_ambush"] = Mechanic(
            id="test_ambush",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="flee",
                    set_flag={"ambush_fled": True},
                    narrative="The ambush flees.",
                )
            ],
        )

        # Add a room reaction that triggers the encounter on turn.start.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="trigger_ambush",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="test_ambush"),
        ))

        # A harmless wait action so the turn resolves.
        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("ambush_fled") is True
        assert "The ambush flees." in engine_result.triggered_narration


class TestReactionTriggerDialogue:
    """Reactions can start dialogue via trigger_dialogue."""

    def test_deferred_trigger_dialogue_starts_dialogue(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="korbar_approaches",
            on="turn.start",
            effect=ReactionEffects(trigger_dialogue="korbar"),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert soft.dialogue_state.active_npc == "korbar"


class TestReactionGameOver:
    """Reactions can end the game via game_over effect."""

    def test_reaction_game_over_sets_hard_state(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="sudden_death",
            on="turn.start",
            effect=ReactionEffects(
                result=Result(game_over=GameOverTrigger(type="lose", trigger_id="pitfall"))
            ),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert engine_result.game_over is not None
        assert engine_result.game_over.type == "lose"
        assert engine_result.game_over.trigger == "pitfall"
        assert hard.game_over is not None
        assert hard.game_over.type == "lose"


class TestDialogueEndedNoDuplicate:
    """dialogue.ended is emitted exactly once per exit."""

    def setup_method(self):
        reset_disabled_once()

    def test_ends_dialogue_emits_single_event(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # A non-once reaction on dialogue.ended adds an item.  If the event
        # were emitted twice, the item would appear twice in inventory.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="on_dialogue_end",
            on="dialogue.ended",
            effect=ReactionEffects(result=Result(add_item=["rusty_key"])),
        ))

        # Enter dialogue with Korbar.
        enter = TalkAction(
            action_type="talk",
            target="korbar",
            detail="talk to korbar",
        )
        resolve(enter, state_manager)
        assert soft.dialogue_state.active_npc == "korbar"

        # End dialogue.
        end = TalkAction(
            action_type="talk",
            target="korbar",
            ends_dialogue=True,
            detail="say goodbye",
        )
        engine_result = resolve(end, state_manager)

        assert engine_result.success is True
        assert soft.dialogue_state.active_npc is None
        # The item should have been added exactly once.
        assert hard.player.inventory.get("rusty_key") == 1


class TestTalkPathSourceType:
    """Dialogue path checks report source_type 'dialogue_path'."""

    def test_dialogue_path_check_source_type(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import Resolvable, RollCheck

        # Add a dialogue path with a roll check to Korbar.
        korbar = corpus.entities["korbar"]
        korbar.dialogue.dialogue_paths["ask_secret"] = Resolvable(
            description="Ask Korbar about the secret.",
            check=RollCheck(threshold=1.0, repeatable=True),
            success=Result(narrative="Korbar whispers the secret."),
        )

        # A reaction that only fires when the check event has source_type dialogue_path.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="track_dialogue_path_check",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == dialogue_path"),
            effect=ReactionEffects(result=Result(set_flag={"dialogue_path_check_seen": True})),
        ))

        action = TalkAction(
            action_type="talk",
            target="korbar",
            dialogue_path="ask_secret",
            detail="ask about secret",
        )
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("dialogue_path_check_seen") is True


class TestReactionChainCheckEvents:
    """Follow-up checks inside reaction results emit check.passed/check.failed events."""

    def test_then_check_in_reaction_emits_event(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, RollCheck

        # A reaction whose result contains a then_check.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="reaction_with_chain",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                narrative="The mechanism whirs.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="You dodge the needle."),
                ),
            )),
        ))

        # A second reaction that only fires if the then_check emits an event
        # with source_type "reaction".
        room.reactions.append(Reaction(
            id="track_reaction_check",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == reaction"),
            effect=ReactionEffects(result=Result(set_flag={"reaction_check_seen": True})),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("reaction_check_seen") is True


class TestReactionCombatLogPropagation:
    """Combat entries from reaction-triggered encounters propagate combat_log."""

    def test_reaction_encounter_combat_log_propagated(self, fresh_state_manager, monkeypatch):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.combat import CombatLogEntry, CombatState

        fake_log = [CombatLogEntry(round=1, actor="spider", action="surprise")]

        def fake_enter_combat(enemy_ids, hard, corpus, **kwargs):
            hard.combat = CombatState(
                active=True,
                combatants=["player"] + list(enemy_ids),
                initiative_order=["player"] + list(enemy_ids),
                round_number=1,
            )
            return {
                "hard_changes": HardStateChanges(),
                "combat_log": fake_log,
                "game_over": False,
            }

        # Patch combat entry helpers so the test focuses on log propagation,
        # not on enemy resolution.
        import mgmai.engine.combat as combat_module
        monkeypatch.setattr(combat_module, "enter_combat", fake_enter_combat)
        monkeypatch.setattr(
            combat_module,
            "resolve_combat_enemies",
            lambda seed_ids, explicit, hard, corpus: list(explicit or seed_ids),
        )

        corpus.mechanics["test_combat"] = Mechanic(
            id="test_combat",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="combat",
                    start_combat=["spider"],
                )
            ],
        )

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="trigger_combat",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="test_combat"),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert engine_result.combat_triggered is True
        assert any(
            entry.actor == "spider" and entry.action == "surprise"
            for entry in engine_result.combat_log
        )


class TestReactionRecursionDepthLimit:
    """The recursion limit caps chains of action-level events emitted by
    reactions (here, check.passed from then_check)."""

    def setup_method(self):
        reset_disabled_once()

    def test_recursion_capped_at_max_depth(self, fresh_state_manager):
        from mgmai.models.corpus import CheckResolution, RollCheck
        from mgmai.models.actions import WaitAction

        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        room = corpus.rooms["bag_floor"]
        room.reactions.clear()

        # Seed: a turn.start reaction whose then_check emits the first
        # check.passed event (source_type "reaction").
        room.reactions.append(Reaction(
            id="seed",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                narrative="seed_tick",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="seed_ok"),
                ),
            )),
        ))
        # Looper: a check.passed reaction whose own then_check re-emits
        # check.passed, matching itself.  Without the depth limit this would
        # recurse forever.
        room.reactions.append(Reaction(
            id="loop",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == reaction"),
            effect=ReactionEffects(result=Result(
                narrative="loop_tick",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="loop_ok"),
                ),
            )),
        ))

        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        narration = engine_result.triggered_narration
        # The seed fires once at depth 0; the looper fires at depths
        # 1..(MAX_RECURSION_DEPTH - 1), then recursion stops.
        assert narration.count("seed_tick") == 1
        assert narration.count("loop_tick") == MAX_RECURSION_DEPTH - 1


class TestEncounterOncePerTurnGuard:
    """Only one trigger_encounter fires per turn; later ones are suppressed."""

    def setup_method(self):
        reset_disabled_once()

    def test_second_trigger_encounter_suppressed(self, fresh_state_manager):
        from mgmai.models.actions import WaitAction

        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"
        corpus.rooms["bag_floor"].reactions.clear()

        corpus.mechanics["test_enc1"] = Mechanic(
            id="test_enc1",
            rules=[_mk_encounter_rule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="flee",
                set_flag={"enc1_fired": True},
                narrative="Encounter 1 fired.",
            )],
        )
        corpus.mechanics["test_enc2"] = Mechanic(
            id="test_enc2",
            rules=[_mk_encounter_rule(
                condition=ConditionExpression(require="entity:player.alive == true"),
                outcome="flee",
                set_flag={"enc2_fired": True},
                narrative="Encounter 2 fired.",
            )],
        )
        # Carrier mechanic holds two turn.end reactions.  turn.end is
        # dispatched with the shared per-turn encounter_fired_ref, so the
        # second trigger_encounter must be suppressed by the guard.
        corpus.mechanics["test_carrier"] = Mechanic(
            id="test_carrier",
            reactions=[
                Reaction(id="fire_enc1", on="turn.end", priority=0,
                         effect=ReactionEffects(trigger_encounter="test_enc1")),
                Reaction(id="fire_enc2", on="turn.end", priority=1,
                         effect=ReactionEffects(trigger_encounter="test_enc2")),
            ],
        )

        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        # First encounter fired.
        assert hard.flags.get("enc1_fired") is True
        assert "Encounter 1 fired." in engine_result.triggered_narration
        # Second encounter was suppressed by the once-per-turn guard.
        assert hard.flags.get("enc2_fired") is None
        assert "Encounter 2 fired." not in engine_result.triggered_narration


class TestTalkPathThenCheck:
    """Item 4: result-only dialogue paths emit then_check events.

    A dialogue path with a ``result`` (no check) containing a
    ``then_check`` must emit ``check.passed``/``check.failed`` for the
    follow-up check, with ``source_type='dialogue_path'``.
    """

    def test_dialogue_path_result_then_check_emits_event(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, Resolvable, RollCheck

        # A result-only dialogue path (no check) with a then_check.
        korbar = corpus.entities["korbar"]
        korbar.dialogue.dialogue_paths["rummage"] = Resolvable(
            description="Rummage through Korbar's pack.",
            result=Result(
                narrative="You find a trinket.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="You pocket it cleanly."),
                ),
            ),
        )

        # A reaction that only fires when the then_check emits an event
        # with source_type dialogue_path.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="track_dialogue_chain",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == dialogue_path"),
            effect=ReactionEffects(result=Result(set_flag={"dialogue_chain_seen": True})),
        ))

        action = TalkAction(
            action_type="talk",
            target="korbar",
            dialogue_path="rummage",
            detail="rummage",
        )
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("dialogue_chain_seen") is True


class TestThenCheckDepthCap:
    """then_check nesting stops at MAX_THEN_CHECK_DEPTH (3)."""

    def setup_method(self):
        reset_disabled_once()

    def test_then_check_depth_4_is_capped(self, fresh_state_manager):
        """A then_check nested 4 deep stops at the 4th level."""
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corp = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, RollCheck

        # Build a 4-deep then_check chain.
        # Each level sets a flag; the 4th (depth 3) should NOT fire.
        level4 = CheckResolution(
            check=RollCheck(threshold=1.0, repeatable=True),
            success=Result(narrative="level4", set_flag={"depth3_fired": True}),
        )
        level3 = CheckResolution(
            check=RollCheck(threshold=1.0, repeatable=True),
            success=Result(narrative="level3", then_check=level4),
        )
        level2 = CheckResolution(
            check=RollCheck(threshold=1.0, repeatable=True),
            success=Result(narrative="level2", then_check=level3),
        )
        level1 = CheckResolution(
            check=RollCheck(threshold=1.0, repeatable=True),
            success=Result(narrative="level1", then_check=level2),
        )

        reaction = Reaction(
            id="depth_test",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                then_check=level1,
            )),
        )
        corp.rooms["bag_floor"].reactions.append(reaction)

        from mgmai.models.actions import WaitAction
        result = resolve(WaitAction(action_type="wait", detail="wait"), state_manager)
        assert result.success is True
        # Depth 0 (level1), depth 1 (level2), depth 2 (level3) fire.
        # Depth 3 (level4) is stopped by MAX_THEN_CHECK_DEPTH=3.
        assert hard.flags.get("depth3_fired") is None


class TestThenCheckSourceTypeInheritance:
    """then_check events inherit source_type from the parent resolution."""

    def setup_method(self):
        reset_disabled_once()

    def test_then_check_inside_interaction_inherits_source_type(self, fresh_state_manager):
        """A then_check in an interaction failure branch emits with source_type='interaction'."""
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corp = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, RollCheck

        # An interaction that always fails, with a then_check on failure.
        room = corp.rooms["bag_floor"]
        room.interactions.append(Interaction(
            id="fail_interaction",
            description="Force a failure to test then_check",
            check=RollCheck(threshold=0.0, repeatable=True),
            success=Result(narrative="Passed."),
            failure=Result(
                narrative="It failed.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="then_check fired."),
                ),
            ),
        ))

        # Track the source_type on the then_check's emitted event.
        room.reactions.append(Reaction(
            id="track_interaction_then_check",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == interaction"),
            effect=ReactionEffects(result=Result(set_flag={"interaction_then_check_seen": True})),
        ))

        action = InteractAction(
            action_type="interact",
            target="korbar",
            interaction_id="fail_interaction",
            detail="try failing",
        )
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("interaction_then_check_seen") is True


class TestResolverThenCheckPaths:
    """then_check fires from result-only interaction and on-examine paths."""

    def setup_method(self):
        reset_disabled_once()

    def test_result_only_interaction_then_check_fires(self, fresh_state_manager):
        """A result-only interaction with a then_check fires it."""
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corp = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, RollCheck

        room = corp.rooms["bag_floor"]
        room.interactions.append(Interaction(
            id="result_then_check_inter",
            description="Interaction with result+then_check",
            result=Result(
                narrative="The mechanism triggers.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="You passed the then_check."),
                ),
            ),
        ))

        room.reactions.append(Reaction(
            id="track_result_then",
            on="check.passed",
            condition=ConditionExpression(require="event:source_id == result_then_check_inter"),
            effect=ReactionEffects(result=Result(set_flag={"result_then_check_seen": True})),
        ))

        action = InteractAction(
            action_type="interact",
            target="korbar",
            interaction_id="result_then_check_inter",
            detail="try",
        )
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("result_then_check_seen") is True

    def test_on_examine_result_then_check_fires(self, fresh_state_manager):
        """An on_examine event whose result has a then_check fires it."""
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corp = state_manager.corpus
        hard.player.location = "bag_floor"

        from mgmai.models.corpus import CheckResolution, OnExamineEvent, RollCheck

        room = corp.rooms["bag_floor"]
        room.on_examine.append(OnExamineEvent(
            id="examine_then_check_event",
            result=Result(
                narrative="You notice something odd.",
                then_check=CheckResolution(
                    check=RollCheck(threshold=1.0, repeatable=True),
                    success=Result(narrative="You recall a detail."),
                ),
            ),
        ))

        room.reactions.append(Reaction(
            id="track_examine_then",
            on="check.passed",
            condition=ConditionExpression(require="event:source_type == examine"),
            effect=ReactionEffects(result=Result(set_flag={"examine_then_check_seen": True})),
        ))

        from mgmai.models.actions import ExamineAction
        action = ExamineAction(
            action_type="examine",
            target="bag_floor",
            detail="look around",
        )
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("examine_then_check_seen") is True


class TestEncounterBranchedEvent:
    """Item 3a: branched encounters emit ``encounter.branched`` events."""

    def test_deferred_encounter_branch_emits_event(self, fresh_state_manager, monkeypatch):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # An encounter mechanic with a roll outcome and branches.
        corpus.mechanics["test_ambush"] = Mechanic(
            id="test_ambush",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="roll",
                    threshold=0.5,
                    success={"narrative": "You win!"},
                    failure={"narrative": "You scramble away."},
                )
            ],
        )

        # A room reaction that triggers the encounter on turn.start.
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="trigger_ambush",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="test_ambush"),
        ))

        # A reaction that fires on encounter.branched, regardless of branch.
        room.reactions.append(Reaction(
            id="track_branch",
            on="encounter.branched",
            effect=ReactionEffects(result=Result(set_flag={"saw_branched": True})),
        ))

        # Force the encounter roll to fail (0.9 >= 0.5 threshold).
        monkeypatch.setattr("random.random", lambda: 0.9)

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("saw_branched") is True

    def test_encounter_branched_context_carries_branch(self, fresh_state_manager, monkeypatch):
        """The encounter.branched event context identifies which branch."""
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        corpus.mechanics["test_ambush"] = Mechanic(
            id="test_ambush",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="roll",
                    threshold=0.5,
                    success={"narrative": "You win!"},
                    failure={"narrative": "You scramble away."},
                )
            ],
        )

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="trigger_ambush",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="test_ambush"),
        ))

        # Only fires on the failure branch.
        room.reactions.append(Reaction(
            id="track_failure",
            on="encounter.branched",
            condition=ConditionExpression(require="event:branch == failure"),
            effect=ReactionEffects(result=Result(set_flag={"saw_failure": True})),
        ))
        room.reactions.append(Reaction(
            id="track_success",
            on="encounter.branched",
            condition=ConditionExpression(require="event:branch == success"),
            effect=ReactionEffects(result=Result(set_flag={"saw_success": True})),
        ))

        # Force failure.
        monkeypatch.setattr("random.random", lambda: 0.9)

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)

        assert engine_result.success is True
        assert hard.flags.get("saw_failure") is True
        assert hard.flags.get("saw_success") is None


class TestReactionResultDispatchFields:
    """A reaction Result's ``game_over`` now takes effect (ends the game) via
    ``_apply_result``.  ``start_combat`` on a reaction Result is ignored at
    runtime and is a load-time validation error when the corpus is loaded
    through StateManager; this test mutates the corpus after load, so it only
    verifies the runtime no-op."""

    def test_result_with_start_combat_does_not_crash(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="test_trigger",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                narrative="It grows dark.",
                start_combat=[],
            )),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)
        assert engine_result.success is True
        assert engine_result.combat_triggered is False
        assert "It grows dark." in engine_result.triggered_narration

    def test_result_with_game_over_does_not_crash(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="test_go",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                narrative="The world ends.",
                game_over=GameOverTrigger(type="lose", trigger_id="test_doom"),
                set_flag={"doomed": True},
            )),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)
        assert engine_result.success is True
        assert engine_result.game_over is not None
        assert engine_result.game_over.type == "lose"
        assert engine_result.game_over.trigger == "test_doom"
        assert "The world ends." in engine_result.triggered_narration
        assert hard.flags.get("doomed") is True

    def test_result_with_both_dispatch_fields_no_crash(self, fresh_state_manager):
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="test_both",
            on="turn.start",
            effect=ReactionEffects(result=Result(
                narrative="Chaos!",
                start_combat=[],
                game_over=GameOverTrigger(type="win", trigger_id="test_win"),
                set_flag={"dispatch_test": True},
            )),
        ))

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)
        assert engine_result.success is True
        assert engine_result.combat_triggered is False
        assert engine_result.game_over is not None
        assert engine_result.game_over.type == "win"
        assert engine_result.game_over.trigger == "test_win"
        assert "Chaos!" in engine_result.triggered_narration
        assert hard.flags.get("dispatch_test") is True

class TestReactionEncounterMultiEnemy:
    """Reaction-fired encounters support start_combat and combat_group expansion."""

    def test_reaction_encounter_start_combat_multi_enemy(self, fresh_state_manager):
        from mgmai.models.corpus import Mechanic, CombatBlock
        from tests.helpers import _mk_encounter_rule
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # Give korbar and spider combat blocks for this encounter.
        corpus.entities["korbar"].combat = CombatBlock(hp=10, ac=10, atk=2, dmg="1d6")
        corpus.entities["spider"].combat = CombatBlock(hp=15, ac=14, atk=5, dmg="1d4+3")
        hard.entity_states["korbar"]["current_hp"] = 10
        hard.entity_states["spider"]["current_hp"] = 15
        hard.room_contains["bag_floor"]["spider"] = 1

        corpus.mechanics["band_attack"] = Mechanic(
            id="band_attack",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="combat",
                    start_combat=["spider", "korbar"],
                )
            ],
        )
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="band_attack_reaction",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="band_attack"),
        ))

        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()
        from mgmai.models.actions import ExamineAction
        # Vehicle action: a non-rigorous examine.  (A wait would now pass
        # the combat turn, resolving a full round of enemy attacks.)
        action = ExamineAction(
            action_type="examine", target="bag_floor", detail="look around"
        )
        engine_result = resolve(action, state_manager)
        assert engine_result.combat_triggered is True
        assert hard.combat is not None
        assert set(hard.combat.combatants) == {"player", "spider", "korbar"}

    def test_reaction_encounter_empty_start_combat_no_combat_started_event(
        self, fresh_state_manager, caplog
    ):
        from mgmai.models.corpus import Mechanic
        from tests.helpers import _mk_encounter_rule
        state_manager = fresh_state_manager
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        corpus.mechanics["empty_attack"] = Mechanic(
            id="empty_attack",
            rules=[
                _mk_encounter_rule(
                    condition=ConditionExpression(require="entity:player.alive == true"),
                    outcome="combat",
                )
            ],
        )
        room = corpus.rooms["bag_floor"]
        room.reactions.append(Reaction(
            id="empty_attack_reaction",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="empty_attack"),
        ))

        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()
        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)
        assert engine_result.combat_triggered is False
        assert hard.combat is None
        assert "start_combat produced no eligible combatants" in caplog.text
