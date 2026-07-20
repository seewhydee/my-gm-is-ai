# My GM is AI — integration tests for the reaction / event-bus pipeline
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import pytest

from mgmai.engine.engine import resolve
from mgmai.engine.event_bus import MAX_RECURSION_DEPTH
from mgmai.engine.resolver import resolve_action
from mgmai.models.actions import HardStateChanges, InteractAction, TalkAction
from mgmai.models.corpus import (
    ConditionExpression,
    GameOverTrigger,
    Interaction,
    Mechanic,
    ModuleCorpus,
    Reaction,
    ReactionEffects,
    Result,
)
from mgmai.state.manager import StateManager
from tests.helpers import _mk_encounter_rule


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


class TestReactionTriggerEncounter:
    """Deferred reactions can trigger encounters via trigger_encounter."""

    def test_deferred_trigger_encounter_runs_mechanic_rules(self, state_manager):
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

    def test_deferred_trigger_dialogue_starts_dialogue(self, state_manager):
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

    def test_reaction_game_over_sets_hard_state(self, state_manager):
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

    def test_ends_dialogue_emits_single_event(self, state_manager):
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

    def test_dialogue_path_check_source_type(self, state_manager):
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

    def test_then_check_in_reaction_emits_event(self, state_manager):
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

    def test_reaction_encounter_combat_log_propagated(self, state_manager, monkeypatch):
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

    def test_recursion_capped_at_max_depth(self, state_manager):
        from mgmai.models.corpus import CheckResolution, RollCheck
        from mgmai.models.actions import WaitAction

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

    def test_second_trigger_encounter_suppressed(self, state_manager):
        from mgmai.models.actions import WaitAction

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

    def test_dialogue_path_result_then_check_emits_event(self, state_manager):
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

    def test_then_check_depth_4_is_capped(self, state_manager):
        """A then_check nested 4 deep stops at the 4th level."""
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

    def test_then_check_inside_interaction_inherits_source_type(self, state_manager):
        """A then_check in an interaction failure branch emits with source_type='interaction'."""
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

    def test_result_only_interaction_then_check_fires(self, state_manager):
        """A result-only interaction with a then_check fires it."""
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

    def test_on_examine_result_then_check_fires(self, state_manager):
        """An on_examine event whose result has a then_check fires it."""
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

    def test_deferred_encounter_branch_emits_event(self, state_manager, monkeypatch):
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

    def test_encounter_branched_context_carries_branch(self, state_manager, monkeypatch):
        """The encounter.branched event context identifies which branch."""
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

    def test_result_with_start_combat_does_not_crash(self, state_manager):
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

    def test_result_with_game_over_does_not_crash(self, state_manager):
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

    def test_result_with_both_dispatch_fields_no_crash(self, state_manager):
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

    def test_reaction_encounter_start_combat_multi_enemy(self, state_manager):
        from mgmai.models.corpus import Mechanic, CombatBlock
        from tests.helpers import _mk_encounter_rule
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "bag_floor"

        # Give korbar and spider combat blocks for this encounter.
        corpus.entities["korbar"].combat = CombatBlock(hp=10, ac=10, atk=2, dmg="1d6")
        corpus.entities["spider"].combat = CombatBlock(hp=15, ac=14, atk=5, dmg="1d4+3")
        hard.entity_states["korbar"]["current_hp"] = 10
        hard.entity_states["spider"]["current_hp"] = 15
        hard.room_contains["bag_floor"]["spider"] = 1
        # Boost player HP so the surprise round can't kill them (which
        # would clear hard.combat and make the test flaky).
        hard.player.current_hp = 100

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
        self, state_manager
    ):
        from mgmai.models.corpus import Mechanic
        from tests.helpers import _mk_encounter_rule
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

        from mgmai.models.actions import WaitAction
        action = WaitAction(action_type="wait", detail="wait")
        engine_result = resolve(action, state_manager)
        assert engine_result.combat_triggered is False
        assert hard.combat is None


class TestCombatEvents:
    """combat.started and combat.ended events are emitted and dispatched.

    Covers all three combat-entry paths (direct attack, action-triggered
    encounter, reaction-triggered encounter) and all three combat-ended
    reasons (victory, defeat, fled).
    """

    @pytest.fixture
    def combat_sm(self) -> StateManager:
        """A state manager with one room, one combat-capable goblin, and an
        exit for flee tests."""
        from tests.helpers import build_state_manager

        corpus = ModuleCorpus.model_validate({
            "adventure": {"title": "Combat Events", "introduction": "Test."},
            "stats": {
                "system": "5e",
                "definitions": {
                    "STR": {"name": "Strength"},
                    "DEX": {"name": "Dexterity"},
                    "CON": {"name": "Constitution"},
                    "INT": {"name": "Intelligence"},
                    "WIS": {"name": "Wisdom"},
                    "CHA": {"name": "Charisma"},
                },
            },
            "rooms": {
                "arena": {
                    "name": "Arena",
                    "description": "A small arena.",
                    "contains": ["goblin"],
                    "exits": [
                        {"id": "exit_north", "direction": "north", "target_room": "safe_room"},
                    ],
                },
                "safe_room": {
                    "name": "Safe Room",
                    "description": "A safe room.",
                },
            },
            "entities": {
                "goblin": {
                    "type": "npc",
                    "description": "A scrawny goblin.",
                    "state_fields": {
                        "alive": {"type": "boolean", "description": "Alive?"},
                        "current_hp": {"type": "number", "description": "HP"},
                    },
                    "combat": {
                        "hp": 7,
                        "ac": 12,
                        "atk": 4,
                        "dmg": "1d6+2",
                        "initiative_mod": 2,
                        "flee_dc": 10,
                    },
                },
            },
        })
        sm = build_state_manager(corpus)
        sm.hard_state.player.location = "arena"
        sm.hard_state.player.stats = {
            "STR": 16, "DEX": 14, "CON": 14,
            "INT": 10, "WIS": 10, "CHA": 10,
        }
        sm._init_player_combat_defaults()
        sm.hard_state.player.current_hp = 30
        sm.hard_state.player.max_hp = 30
        sm.hard_state.player.ac = 14
        sm.hard_state.entity_states["goblin"]["current_hp"] = 7
        sm.hard_state.entity_states["player"] = {"alive": True}
        sm.hard_state.room_contains["arena"] = {"goblin": 1}
        return sm

    # -- combat.started emission ---------------------------------------

    def test_combat_started_on_direct_attack(self, combat_sm, monkeypatch):
        """A direct interact/attack on a combat NPC emits combat.started."""
        import random
        # Player goes first and misses; goblin misses too — combat stays
        # active so we can verify the state.
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        from mgmai.models.actions import InteractAction
        action = InteractAction(
            action_type="interact",
            target="goblin",
            interaction_id="attack",
            detail="Attack!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert result.combat_triggered
        # The combat.started event is in the resolver's events list; it
        # was dispatched by the engine.  Verify via a flag set by a
        # reaction (next test) or by checking that combat is active.
        assert combat_sm.hard_state.combat is not None

    def test_combat_started_reaction_fires(self, combat_sm, monkeypatch):
        """A reaction on combat.started fires when combat begins."""
        import random
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="combat_start_reaction",
            on="combat.started",
            effect=ReactionEffects(result=Result(
                set_flag={"combat_started_flag": True},
                narrative="Combat begins!",
            )),
        ))

        from mgmai.models.actions import InteractAction
        action = InteractAction(
            action_type="interact",
            target="goblin",
            interaction_id="attack",
            detail="Attack!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert combat_sm.hard_state.flags.get("combat_started_flag") is True
        assert "Combat begins!" in result.triggered_narration

    def test_combat_started_reaction_fires_via_encounter(self, combat_sm, monkeypatch):
        """combat.started fires when an encounter triggers combat."""
        import random
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="combat_start_reaction",
            on="combat.started",
            effect=ReactionEffects(result=Result(
                set_flag={"combat_started_flag": True},
            )),
        ))
        # Trigger combat via a turn.start reaction that fires an encounter.
        combat_sm.corpus.mechanics["ambush"] = Mechanic(
            id="ambush",
            rules=[_mk_encounter_rule(
                condition=ConditionExpression(
                    require="entity:player.alive == true"
                ),
                outcome="combat",
                start_combat=["goblin"],
            )],
        )
        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="ambush_trigger",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="ambush"),
        ))

        from mgmai.models.actions import ExamineAction
        action = ExamineAction(
            action_type="examine", target="arena", detail="look around"
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert result.combat_triggered
        assert combat_sm.hard_state.flags.get("combat_started_flag") is True

    # -- combat.ended: victory ----------------------------------------

    def _set_active_combat(self, combat_sm, initiative=None):
        """Put the state manager into an active combat with the goblin."""
        from mgmai.models.combat import CombatState
        combat_sm.hard_state.combat = CombatState(
            active=True,
            combatants=["player", "goblin"],
            initiative_order=initiative or ["player", "goblin"],
            current_index=0,
            round_number=1,
        )

    def test_combat_ended_victory(self, combat_sm, monkeypatch):
        """Killing the last enemy emits combat.ended with reason 'victory'."""
        import random
        self._set_active_combat(combat_sm)
        # Roll 20 → crit, max damage dice → kill the goblin (7 HP).
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        monkeypatch.setattr(random, "random", lambda: 0.5)

        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="victory_reaction",
            on="combat.ended",
            condition=ConditionExpression(require="event:reason == victory"),
            effect=ReactionEffects(result=Result(
                set_flag={"victory_flag": True},
                narrative="Victory!",
            )),
        ))

        from mgmai.models.actions import CombatAction
        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Finishing blow!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert combat_sm.hard_state.combat is None
        assert combat_sm.hard_state.flags.get("victory_flag") is True
        assert "Victory!" in result.triggered_narration

    # -- combat.ended: fled -------------------------------------------

    def test_combat_ended_fled(self, combat_sm, monkeypatch):
        """Successfully fleeing emits combat.ended with reason 'fled'."""
        import random
        self._set_active_combat(combat_sm)
        # DEX 14 → +2, flee DC 10. Roll 12 + 2 = 14 ≥ 10 → success.
        monkeypatch.setattr(random, "randint", lambda a, b: 12)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        # Use a mechanic-scoped (global) reaction because the player
        # moves to a new room during fleeing, so room-scoped reactions
        # on the arena would no longer match.
        combat_sm.corpus.mechanics["fled_tracker"] = Mechanic(
            id="fled_tracker",
            reactions=[Reaction(
                id="fled_reaction",
                on="combat.ended",
                condition=ConditionExpression(require="event:reason == fled"),
                effect=ReactionEffects(result=Result(
                    set_flag={"fled_flag": True},
                )),
            )],
        )

        from mgmai.models.actions import MoveAction
        action = MoveAction(
            action_type="move",
            target="exit_north",
            detail="Run away!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert combat_sm.hard_state.combat is None
        assert combat_sm.hard_state.flags.get("fled_flag") is True

    # -- combat.ended: defeat -----------------------------------------

    def test_combat_ended_defeat(self, combat_sm, monkeypatch):
        """Player death in combat emits combat.ended with reason 'defeat'."""
        import random
        self._set_active_combat(combat_sm)
        combat_sm.hard_state.player.current_hp = 1
        # Player misses (1), goblin crits (20 → 2d6+2 = 14 damage).
        rand_vals = iter([1, 20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        monkeypatch.setattr(random, "random", lambda: 0.5)

        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="defeat_reaction",
            on="combat.ended",
            condition=ConditionExpression(require="event:reason == defeat"),
            effect=ReactionEffects(result=Result(
                set_flag={"defeat_flag": True},
            )),
        ))

        from mgmai.models.actions import CombatAction
        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Last stand!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert combat_sm.hard_state.combat is None
        assert combat_sm.hard_state.flags.get("defeat_flag") is True

    # -- combat.ended without condition fires for any reason ----------

    def test_combat_ended_unconditional_reaction(self, combat_sm, monkeypatch):
        """A reaction on combat.ended without a condition fires for any
        reason."""
        import random
        self._set_active_combat(combat_sm)
        rand_vals = iter([20, 6, 6])
        monkeypatch.setattr(random, "randint", lambda a, b: next(rand_vals))
        monkeypatch.setattr(random, "random", lambda: 0.5)

        combat_sm.corpus.rooms["arena"].reactions.append(Reaction(
            id="any_end_reaction",
            on="combat.ended",
            effect=ReactionEffects(result=Result(
                set_flag={"combat_ended_flag": True},
            )),
        ))

        from mgmai.models.actions import CombatAction
        action = CombatAction(
            action_type="combat",
            combat_action="attack",
            target="goblin",
            detail="Attack!",
        )
        result = resolve(action, combat_sm)
        assert result.success
        assert combat_sm.hard_state.flags.get("combat_ended_flag") is True

    # -- dialogue.ended reason 'combat' -------------------------------

    def test_dialogue_ended_reason_combat(self, combat_sm, monkeypatch):
        """Starting combat while in dialogue emits dialogue.ended with
        reason 'combat'."""
        import random
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        monkeypatch.setattr(random, "random", lambda: 0.5)

        # Give the goblin dialogue so we can enter dialogue first.
        from mgmai.models.corpus import DialogueGuidelines
        combat_sm.corpus.entities["goblin"].dialogue = DialogueGuidelines(
            guidelines="The goblin snarls.",
        )

        combat_sm.corpus.mechanics["dialogue_combat_tracker"] = Mechanic(
            id="dialogue_combat_tracker",
            reactions=[
                Reaction(
                    id="track_dialogue_end",
                    on="dialogue.ended",
                    condition=ConditionExpression(
                        require="event:reason == combat"
                    ),
                    effect=ReactionEffects(result=Result(
                        set_flag={"dialogue_ended_by_combat": True},
                    )),
                ),
            ],
        )

        from mgmai.models.actions import TalkAction, InteractAction
        # Enter dialogue with the goblin.
        talk = TalkAction(
            action_type="talk",
            target="goblin",
            utterance="Hello goblin.",
            detail="Talk to the goblin.",
        )
        result = resolve(talk, combat_sm)
        assert result.success
        assert combat_sm.soft_state.dialogue_state.active_npc == "goblin"

        # Attack the goblin — should exit dialogue with reason 'combat'
        # and start combat.
        attack = InteractAction(
            action_type="interact",
            target="goblin",
            interaction_id="attack",
            detail="Attack!",
        )
        result = resolve(attack, combat_sm)
        assert result.success
        assert result.combat_triggered
        assert combat_sm.hard_state.flags.get("dialogue_ended_by_combat") is True
