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

"""Tests for engine/engine.py — main orchestrator."""

import json
from pathlib import Path

import pytest

from mgmai.engine.engine import resolve
from mgmai.models.actions import (
    ExamineAction,
    InteractAction,
    MoveAction,
    OocDiscussionAction,
    TalkAction,
    TransferAction,
    WaitAction,
)
from mgmai.models.corpus import (
    Adventure,
    Atmosphere,
    Interaction,
    ModuleCorpus,
    Reaction,
    ReactionEffects,
    Result,
    StatModifier,
)
from mgmai.state.manager import StateManager
from tests.helpers import (
    build_state_manager,
    make_encounter_trigger_corpus,
    _mk_cond,
    _mk_encounter_rule,
    _mk_hard_state,
    _mk_item_entity,
    _mk_reaction,
    _mk_room,
)


class TestEngineFullFlow:
    def test_resolve_move_success(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down the axe handle",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.action_type == "move"
        assert state_manager.hard_state.player.location == "axe_handle_upper"
        assert state_manager.hard_state.turn_count == 1
        assert result.room_after is not None
        assert result.room_after.id == "axe_handle_upper"

    def test_fall_damage_reduces_player_stats(self, monkeypatch):
        corpus = make_encounter_trigger_corpus(
            mechanic_id="fall_test",
            exit_id="exit_drop",
            target_room_id="target",
            reaction_event="traversal.attempted",
            encounter_outcome="roll",
            alter_stat={"DEX": StatModifier(value=-4), "CON": StatModifier(value=-4)},
            player_damage="3d6",
        )
        # Override the default encounter rule: roll outcome with threshold,
        # failure applies alter_stat + player_damage.  The helper builds a
        # simple flee rule, so we replace it.
        corpus.mechanics["fall_test"].rules = [
            _mk_encounter_rule(
                outcome="roll",
                threshold=0.50,
                condition=_mk_cond(require="entity:test_npc.alive == true"),
                failure=Result(
                    alter_stat={"DEX": StatModifier(value=-4), "CON": StatModifier(value=-4)},
                    player_damage="3d6",
                    narrative="You fall hard!",
                ),
            )
        ]
        manager = build_state_manager(corpus)
        # Ensure roll failure (>= 0.50).
        monkeypatch.setattr("random.random", lambda: 0.80)
        action = MoveAction(
            action_type="move",
            target="exit_drop",
            detail="Dropping",
        )
        result = resolve(action, manager)
        assert result.success is True
        # Encounter outcome is not "combat", so the room transition proceeds.
        assert manager.hard_state.player.location == "target"
        # Encounter failure applies -4 to DEX and CON.
        assert manager.hard_state.player.stats == {
            "STR": 10, "DEX": 6, "CON": 6,
            "INT": 10, "WIS": 10, "CHA": 10,
        }
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.stat_modifiers == {
            "DEX": StatModifier(mode="delta", value=-4),
            "CON": StatModifier(mode="delta", value=-4),
        }

    def test_resolve_move_fail(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_nonexistent",
            detail="Walking into nothing",
        )
        result = resolve(action, state_manager)
        assert result.success is False
        assert result.error is not None
        assert state_manager.hard_state.turn_count == 0

    def test_resolve_examine_non_rigorous(self, state_manager):
        action = ExamineAction(
            action_type="examine",
            target="padlock",
            detail="Looking at the padlock",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.costs_turn is False
        assert state_manager.hard_state.turn_count == 0

    def test_resolve_examine_rigorous_advances_turn(self, state_manager):
        action = ExamineAction(
            action_type="examine",
            target="padlock",
            rigorous=True,
            detail="Searching the padlock thoroughly",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.costs_turn is True
        assert state_manager.hard_state.turn_count == 1

    def test_resolve_wait(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Resting for a moment",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.hard_state.turn_count == 1

    def test_resolve_ooc_discussion(self, state_manager):
        action = OocDiscussionAction(
            action_type="ooc_discussion",
            detail="What am I seeing?",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.hard_state.turn_count == 0

    def test_resolve_interact(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        hard.flags["handkerchief_noticed"] = True
        action = InteractAction(
            action_type="interact",
            target="handkerchief",
            interaction_id="move_handkerchief",
            detail="Moving the handkerchief",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert hard.flags.get("handkerchief_moved") is True

    def test_room_entered_reaction_narration(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert any("sticky webs" in n for n in result.triggered_narration)

    def test_hard_state_changes_returned(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.player_location == "axe_handle_upper"

    def test_interaction_with_set_player_location_moves_player(self, state_manager):
        glyph = _mk_item_entity("glyph", description="A glowing glyph.")
        room_a = _mk_room(
            "room_a",
            "Room A",
            contains=["glyph"],
            interactions=[
                Interaction(
                    id="teleport",
                    description="Step on the glyph",
                    result=Result(
                        narrative="The glyph flares and you vanish.",
                        set_player_location="room_b",
                    ),
                ),
            ],
            is_start_room=True,
        )
        room_b = _mk_room("room_b", "Room B")
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="Test",
                introduction="Test",
                atmosphere=Atmosphere(setting="test", tone="neutral"),
            ),
            rooms={"room_a": room_a, "room_b": room_b},
            entities={"glyph": glyph},
            mechanics={},
            stats=None,
        )
        manager = build_state_manager(
            corpus,
            hard_state=_mk_hard_state(player_location="room_a"),
        )

        action = InteractAction(
            action_type="interact",
            target="glyph",
            interaction_id="teleport",
            detail="Stepping on the glyph",
        )
        result = resolve(action, manager)
        assert result.success is True
        assert manager.hard_state.player.location == "room_b"
        assert result.hard_state_changes is not None
        assert result.hard_state_changes.player_location == "room_b"

    def test_set_player_location_triggers_room_entered_reaction(
        self, state_manager
    ):
        # An interaction result that relocates the player must still go through
        # the normal room-transition code, firing room.entered reactions in the
        # destination room.  We use an action result here, not a nested
        # reaction, to avoid re-entrancy concerns.
        glyph = _mk_item_entity("glyph", description="A glowing glyph.")
        room_b = _mk_room(
            "room_b",
            "Room B",
            reactions=[
                _mk_reaction(
                    "welcome",
                    on="room.entered",
                    effect=ReactionEffects(
                        result=Result(
                            narrative="The room welcomes you.",
                            set_flag={"room_b_entered": True},
                        )
                    ),
                    phase="immediate",
                ),
            ],
        )
        room_a = _mk_room(
            "room_a",
            "Room A",
            contains=["glyph"],
            interactions=[
                Interaction(
                    id="teleport",
                    description="Step on the glyph",
                    result=Result(
                        narrative="The glyph flares and you vanish.",
                        set_player_location="room_b",
                    ),
                ),
            ],
            is_start_room=True,
        )
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="Test",
                introduction="Test",
                atmosphere=Atmosphere(setting="test", tone="neutral"),
            ),
            rooms={"room_a": room_a, "room_b": room_b},
            entities={"glyph": glyph},
            mechanics={},
            stats=None,
        )
        manager = build_state_manager(
            corpus,
            hard_state=_mk_hard_state(player_location="room_a"),
        )

        action = InteractAction(
            action_type="interact",
            target="glyph",
            interaction_id="teleport",
            detail="Stepping on the glyph",
        )
        result = resolve(action, manager)
        assert result.success is True
        assert manager.hard_state.player.location == "room_b"
        assert manager.hard_state.flags.get("room_b_entered") is True
        assert any("welcomes you" in n for n in result.triggered_narration)

    def test_turn_history_appended(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Waiting",
        )
        resolve(action, state_manager)
        assert len(state_manager.soft_state.turn_history) == 1
        assert state_manager.soft_state.turn_history[0].turn == 1

    def test_soft_patches_validated(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
            proposed_soft_state_patches=[
                SoftStatePatch(
                    field="room_note",
                    target_id="axe_head",
                    new_value="The room seems dusty.",
                    reason="Perception",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_applied) == 1

    def test_soft_patch_rejected(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
            proposed_soft_state_patches=[
                SoftStatePatch(
                    field="room_note",
                    target_id="nonexistent_room",
                    new_value="Something",
                    reason="Test",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_rejected) == 1


class TestEngineGameOver:
    def test_win_condition(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "axe_head"
        hard.flags["padlock_unlocked"] = True
        action = WaitAction(
            action_type="wait",
            detail="Checking surroundings",
        )
        result = resolve(action, state_manager)
        assert result.game_over is not None
        assert result.game_over.type == "win"

    def test_win_condition_via_turn_end_reaction_same_turn(self, state_manager):
        """A game-over condition satisfied by a turn.end reaction is caught the
        SAME turn: the end-of-turn poll runs after turn.end reactions settle,
        so the flag they set is seen immediately (the old mid-turn poll would
        have missed it until the next turn)."""
        import copy
        # Deep-copy the shared session corpus so this mutation cannot leak
        # into other tests using the same sample_corpus fixture object.
        state_manager.corpus = copy.deepcopy(state_manager.corpus)
        hard = state_manager.hard_state
        corpus = state_manager.corpus
        hard.player.location = "axe_head"
        assert hard.flags.get("padlock_unlocked") is not True

        # A turn.end reaction sets the flag the win_escape_bag game_over
        # condition checks (flag:padlock_unlocked == true).
        corpus.rooms["axe_head"].reactions.append(Reaction(
            id="unlock_on_turn_end",
            on="turn.end",
            effect=ReactionEffects(
                result=Result(set_flag={"padlock_unlocked": True})),
        ))

        action = WaitAction(
            action_type="wait",
            detail="Checking surroundings",
        )
        result = resolve(action, state_manager)
        assert hard.flags.get("padlock_unlocked") is True
        assert result.game_over is not None
        assert result.game_over.type == "win"

    def test_no_game_over_when_not_met(self, state_manager):
        action = WaitAction(
            action_type="wait",
            detail="Checking surroundings",
        )
        result = resolve(action, state_manager)
        assert result.game_over is None


class TestEngineDialogueIntegration:
    def test_talk_enters_dialogue(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Hello!",
            detail="Greeting Korbar",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert state_manager.soft_state.dialogue_state.active_npc == "korbar"

    def test_non_talk_action_exits_dialogue_on_stall(self, state_manager):
        """Regression test: non-talk action while in dialogue triggers stall exit.

        This used to raise UnboundLocalError because ``exit_dialogue`` was
        imported locally only inside combat branches, leaving the stall-exit
        path with an unbound local name.
        """
        from mgmai.engine.dialogue import enter_dialogue

        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        enter_dialogue(soft, "korbar", hard.turn_count, "Hello", "Greeting")
        soft.dialogue_state.stall_counter = 2

        action = WaitAction(
            action_type="wait",
            detail="Standing awkwardly silent",
        )
        result = resolve(action, state_manager)

        assert result.success is True
        assert result.dialogue_exited is not None
        assert result.dialogue_exited.npc_id == "korbar"
        assert soft.dialogue_state.active_npc is None

    def test_talk_ends_dialogue(self, state_manager):
        hard = state_manager.hard_state
        soft = state_manager.soft_state
        hard.player.location = "bag_floor"
        action1 = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Hello!",
            detail="Greeting Korbar",
        )
        resolve(action1, state_manager)
        action2 = TalkAction(
            action_type="talk",
            target="korbar",
            utterance="Goodbye",
            ends_dialogue=True,
            detail="Ending conversation",
        )
        result = resolve(action2, state_manager)
        assert result.success is True
        assert soft.dialogue_state.active_npc is None


class TestEngineChainHandling:
    def test_chain_depth_limit(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing",
            follow_up="Continue climbing",
        )
        result = resolve(action, state_manager, chain_depth=10)
        assert result.success is False
        assert result.chain_info is not None
        assert result.chain_info.termination_reason is not None

    def test_chain_info_in_result(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing",
            follow_up="Continue climbing",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.chain_info is not None
        assert result.chain_info.follow_up == "Continue climbing"


class TestEngineRoomAfter:
    def test_room_after_built_correctly(self, state_manager):
        action = MoveAction(
            action_type="move",
            target="exit_climb_down_handle",
            detail="Climbing down",
        )
        result = resolve(action, state_manager)
        assert result.room_after is not None
        assert result.room_after.id == "axe_handle_upper"
        assert result.room_after.name == "Axe Handle (Upper)"
        assert len(result.room_after.entities_visible) > 0
        assert len(result.room_after.exits_available) > 0

    def test_will_reveal_readiness(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        assert result.will_reveal_readiness is not None
        assert "korbar" in result.will_reveal_readiness

    def test_surfaced_soft_items_persisted_after_examine(self, state_manager):
        """Examining a soft item produces a proposal; accepting it surfaces the item."""
        from mgmai.engine.post_validate import apply_post_validation
        from mgmai.models.narration import SoftItemAdjudication

        action = ExamineAction(
            action_type="examine",
            target="loose stone",
            detail="Looking at stone",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_item_proposals) == 1

        adjudication = SoftItemAdjudication(
            item_name="loose stone",
            action="examine",
            accepted=True,
            source_id="axe_head",
        )
        result = apply_post_validation(
            None, None, state_manager, result, soft_item_adjudications=[adjudication]
        )
        assert "axe_head" in state_manager.soft_state.surfaced_soft_items
        assert "loose stone" in state_manager.soft_state.surfaced_soft_items["axe_head"]
        assert state_manager.soft_state.surfaced_soft_items["axe_head"]["loose stone"] == 0

    def test_surfaced_soft_items_persisted_after_take(self, state_manager):
        """Taking a soft item produces a proposal; accepting it adds to inventory and surfaces it."""
        from mgmai.engine.post_validate import apply_post_validation
        from mgmai.models.narration import SoftItemAdjudication

        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = TransferAction(
            action_type="transfer",
            target="rubbish_pile",
            taken_items=["stale sandwich"],
            detail="Taking a sandwich",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_item_proposals) == 1

        adjudication = SoftItemAdjudication(
            item_name="stale sandwich",
            action="take",
            accepted=True,
            source_id="rubbish_pile",
        )
        result = apply_post_validation(
            None, None, state_manager, result, soft_item_adjudications=[adjudication]
        )
        assert "stale sandwich" in state_manager.soft_state.soft_inventory
        assert "rubbish_pile" in state_manager.soft_state.surfaced_soft_items
        assert state_manager.soft_state.surfaced_soft_items["rubbish_pile"]["stale sandwich"] == 1

    def test_surfaced_soft_items_in_room_after(self, state_manager):
        """Surfaced items appear in the EngineResult.room_after briefing."""
        state_manager.soft_state.surfaced_soft_items["axe_head"] = {"loose stone": 0}
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        assert result.room_after is not None
        assert "loose stone" in result.room_after.soft_items

    def test_surfaced_entity_soft_items_in_room_after(self, state_manager):
        """Entity-level surfaced items appear in the entity's soft_items in room_after."""
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        state_manager.soft_state.surfaced_soft_items["rubbish_pile"] = {"lint": 1}
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        rubbish = next(
            e for e in result.room_after.entities_visible
            if e.id == "rubbish_pile"
        )
        assert any("lint" in s for s in rubbish.soft_items)

    def test_npc_attitude_limits(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        action = WaitAction(
            action_type="wait",
            detail="Checking atmosphere",
        )
        result = resolve(action, state_manager)
        assert result.npc_attitude_limits is not None
        assert "korbar" in result.npc_attitude_limits
        limits = result.npc_attitude_limits["korbar"]
        assert limits.min == -5
        assert limits.max == 10
        assert limits.step_per_turn == 3


class TestMultiCombatantEncounters:
    """Multi-enemy combat entry and empty-set reconciliation."""

    def test_encounter_start_combat_multi_enemy_combat(self):
        from tests.helpers import _mk_npc_entity, CombatBlock
        corpus = make_encounter_trigger_corpus(
            mechanic_id="ambush",
            encounter_outcome="combat",
            encounter_narrative="The ambush springs!",
        )
        # Add two combat-capable NPCs in the start room.
        corpus.entities["thug_1"] = _mk_npc_entity(
            "thug_1",
            state_fields={"alive": {"type": "boolean", "description": "Alive?"}, "current_hp": {"type": "number", "description": "HP"}},
            combat=CombatBlock(hp=10, ac=12, atk=3, dmg="1d6"),
        )
        corpus.entities["thug_2"] = _mk_npc_entity(
            "thug_2",
            state_fields={"alive": {"type": "boolean", "description": "Alive?"}, "current_hp": {"type": "number", "description": "HP"}},
            combat=CombatBlock(hp=10, ac=12, atk=3, dmg="1d6"),
        )
        corpus.rooms["start"].contains = ["thug_1", "thug_2"]
        corpus.mechanics["ambush"].rules[0].result.start_combat = ["thug_1", "thug_2"]

        manager = build_state_manager(corpus)
        hard = manager.hard_state
        hard.room_contains["start"] = {"thug_1": 1, "thug_2": 1}
        hard.entity_states["thug_1"] = {"alive": True, "current_hp": 10}
        hard.entity_states["thug_2"] = {"alive": True, "current_hp": 10}

        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()
        action = InteractAction(
            action_type="interact",
            target="thug_1",
            interaction_id="attack",
            detail="Attack thug_1",
        )
        # No explicit attack interaction -> encounter trigger on thug_1.
        # The NPC has no aggro, so it falls through to mechanic lookup (none).
        # Actually this won't trigger the mechanic.  Use a reaction instead.
        # Simpler: set the encounter trigger via a turn.start reaction.
        corpus.rooms["start"].reactions.append(_mk_reaction(
            "ambush_reaction",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="ambush"),
        ))
        action = WaitAction(action_type="wait", detail="Wait")
        result = resolve(action, manager)
        assert result.combat_triggered is True
        assert hard.combat is not None
        assert set(hard.combat.combatants) == {"player", "thug_1", "thug_2"}

    def test_mechanic_start_combat_without_combatants_does_not_enter_combat(self):
        corpus = make_encounter_trigger_corpus(
            mechanic_id="empty_combat",
            encounter_outcome="combat",
            encounter_narrative="Nothing happens.",
        )
        corpus.rooms["start"].reactions.append(_mk_reaction(
            "empty_combat_reaction",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="empty_combat"),
        ))
        manager = build_state_manager(corpus)
        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()

        action = WaitAction(action_type="wait", detail="Wait")
        result = resolve(action, manager)
        assert result.combat_triggered is False
        assert manager.hard_state.combat is None
        assert "Nothing happens." in result.triggered_narration

    def test_empty_combat_does_not_block_room_transition(self):
        corpus = make_encounter_trigger_corpus(
            mechanic_id="empty_combat",
            encounter_outcome="combat",
            encounter_narrative="A hollow threat.",
        )
        # Give the mechanic a result that also moves the player.
        corpus.mechanics["empty_combat"].rules[0].result.set_player_location = "target"
        corpus.rooms["start"].reactions.append(_mk_reaction(
            "empty_combat_reaction",
            on="turn.start",
            effect=ReactionEffects(trigger_encounter="empty_combat"),
        ))
        manager = build_state_manager(corpus)
        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()

        action = WaitAction(action_type="wait", detail="Wait")
        result = resolve(action, manager)
        assert result.combat_triggered is False
        assert manager.hard_state.player.location == "target"

    def test_encounter_state_change_visible_to_enemy_resolution(self):
        from tests.helpers import _mk_npc_entity, CombatBlock
        corpus = make_encounter_trigger_corpus(
            mechanic_id="unused",
            encounter_outcome="combat",
            encounter_narrative="A dead foe stirs!",
        )
        # Cultist has no combat block, so attacking it routes through aggro.
        corpus.entities["cultist"] = _mk_npc_entity(
            "cultist",
            state_fields={"alive": {"type": "boolean", "description": "Alive?"}},
            reactions=[],
        )
        corpus.entities["zombie"] = _mk_npc_entity(
            "zombie",
            state_fields={"alive": {"type": "boolean", "description": "Alive?"}, "current_hp": {"type": "number", "description": "HP"}},
            combat=CombatBlock(hp=10, ac=10, atk=2, dmg="1d6"),
            reactions=[],
        )
        # Give cultist aggro that revives zombie and triggers combat.
        from mgmai.models.corpus import EncounterRule
        corpus.entities["cultist"].aggro = [
            EncounterRule.model_validate({
                "condition": {"require": "entity:cultist.alive == true"},
                "result": {
                    "narrative": "The cultist chants and zombie rises!",
                    "start_combat": ["zombie"],
                    "set_entity_state": {
                        "zombie": {"alive": True, "current_hp": 10},
                    },
                },
            })
        ]
        corpus.rooms["start"].contains = ["cultist", "zombie"]

        manager = build_state_manager(corpus)
        hard = manager.hard_state
        hard.room_contains["start"] = {"cultist": 1, "zombie": 1}
        hard.entity_states["cultist"] = {"alive": True}
        hard.entity_states["zombie"] = {"alive": False, "current_hp": 0}

        from mgmai.engine.event_bus import reset_disabled_once
        reset_disabled_once()
        action = InteractAction(
            action_type="interact",
            target="cultist",
            interaction_id="attack",
            detail="Attack cultist",
        )
        result = resolve(action, manager)
        assert result.combat_triggered is True
        assert result.encounter_outcome is not None
        assert result.encounter_outcome.combat is True
        assert hard.combat is not None
        assert "zombie" in hard.combat.combatants
        assert hard.entity_states["zombie"]["alive"] is True
