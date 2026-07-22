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



from mgmai.engine.engine import resolve
from mgmai.engine.utils import present_entity_ids
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
            soft_state_patches=[
                SoftStatePatch(
                    field="room_note",
                    new_value="The room seems dusty.",
                    reason="Perception",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_applied) == 1
        # room_note attaches to the player's current room (axe_head).
        assert state_manager.soft_state.room_notes.get("axe_head") == [
            "The room seems dusty."
        ]

    def test_entity_note_on_present_entity_accepted(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        # rip_in_canvas is in axe_head (the player's starting room).
        action = WaitAction(
            action_type="wait",
            detail="Noting the rip",
            soft_state_patches=[
                SoftStatePatch(
                    field="entity_note",
                    entity_id="rip_in_canvas",
                    new_value="The rip is fraying at the edges.",
                    reason="Player inspected the rip.",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_applied) == 1
        assert state_manager.soft_state.entity_notes.get("rip_in_canvas") == [
            "The rip is fraying at the edges."
        ]

    def test_entity_note_on_player_accepted(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        action = WaitAction(
            action_type="wait",
            detail="Vowing",
            soft_state_patches=[
                SoftStatePatch(
                    field="entity_note",
                    entity_id="player",
                    new_value="Player vowed to find Korbar's party.",
                    reason="A promise worth remembering.",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_applied) == 1
        assert state_manager.soft_state.entity_notes.get("player") == [
            "Player vowed to find Korbar's party."
        ]

    def test_entity_note_on_absent_entity_rejected(self, state_manager):
        from mgmai.models.soft_state import SoftStatePatch
        # spider is in axe_handle_lower, not the player's current room
        # (axe_head).
        action = WaitAction(
            action_type="wait",
            detail="Noting the spider",
            soft_state_patches=[
                SoftStatePatch(
                    field="entity_note",
                    entity_id="spider",
                    new_value="The spider looks agitated.",
                    reason="Player recalls the spider.",
                ),
            ],
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_state_patches_rejected) == 1
        assert "not present in room" in result.soft_state_patches_rejected[0]["reason"]


class TestPresentEntityIds:
    """Unit tests for the shared present_entity_ids helper."""

    def test_includes_direct_and_transitively_nested(self) -> None:
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="T", introduction="x",
                atmosphere=Atmosphere(setting="s", tone="t"),
            ),
            rooms={"r1": _mk_room("r1", "Room 1")},
            entities={
                "chest": _mk_item_entity("chest", "A chest."),
                "rock": _mk_item_entity("rock", "A rock."),
                "gem": _mk_item_entity("gem", "A gem in the chest."),
                "key": _mk_item_entity("key", "A key inside the gem box."),
            },
        )
        hard = _mk_hard_state(player_location="r1")
        hard.room_contains = {"r1": {"chest": 1, "rock": 1}}
        # gem nested in chest; key nested two levels deep inside gem.
        hard.entity_contains = {"chest": {"gem": 1}, "gem": {"key": 1}}
        assert present_entity_ids(hard, corpus) == {"chest", "rock", "gem", "key"}

    def test_excludes_entities_in_other_rooms(self) -> None:
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="T", introduction="x",
                atmosphere=Atmosphere(setting="s", tone="t"),
            ),
            rooms={
                "r1": _mk_room("r1", "Room 1"),
                "r2": _mk_room("r2", "Room 2"),
            },
            entities={
                "rock": _mk_item_entity("rock", "A rock in r1."),
                "boulder": _mk_item_entity("boulder", "A boulder in r2."),
            },
        )
        hard = _mk_hard_state(player_location="r1")
        hard.room_contains = {"r1": {"rock": 1}, "r2": {"boulder": 1}}
        assert present_entity_ids(hard, corpus) == {"rock"}

    def test_zero_count_excluded(self) -> None:
        corpus = ModuleCorpus(
            adventure=Adventure(
                title="T", introduction="x",
                atmosphere=Atmosphere(setting="s", tone="t"),
            ),
            rooms={"r1": _mk_room("r1", "Room 1")},
            entities={
                "rock": _mk_item_entity("rock", "A rock."),
                "stick": _mk_item_entity("stick", "A stick."),
            },
        )
        hard = _mk_hard_state(player_location="r1")
        hard.room_contains = {"r1": {"rock": 1, "stick": 0}}
        assert present_entity_ids(hard, corpus) == {"rock"}


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

    def test_examine_acceptance_writes_no_soft_item_state(self, state_manager):
        """Examining a soft item produces a proposal; accepting it records nothing."""
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
        soft = state_manager.soft_state
        assert soft.soft_items_taken == {}
        assert soft.soft_contents == {}
        assert result.soft_items_accepted[0].item_name == "loose stone"

    def test_soft_items_taken_after_take(self, state_manager):
        """Accepting an ambient take adds to inventory and the extraction ledger."""
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
        soft = state_manager.soft_state
        assert "stale sandwich" in soft.soft_inventory
        assert soft.soft_items_taken["rubbish_pile"]["stale sandwich"] == 1
        assert soft.soft_contents == {}

    def test_soft_items_in_room_after(self, state_manager):
        """Extraction history and placed items appear in the room_after briefing."""
        state_manager.soft_state.soft_items_taken["axe_head"] = {"loose stone": 1}
        state_manager.soft_state.soft_contents["axe_head"] = {"pebble": 2}
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        assert result.room_after is not None
        assert result.room_after.soft_items_taken == ["loose stone (taken 1)"]
        assert result.room_after.soft_items_present == ["pebble x2"]

    def test_entity_soft_items_in_room_after(self, state_manager):
        """Entity-level soft items appear as two fields in room_after."""
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        state_manager.soft_state.soft_items_taken["rubbish_pile"] = {"lint": 1}
        state_manager.soft_state.soft_contents["rubbish_pile"] = {"cork": 2}
        action = WaitAction(
            action_type="wait",
            detail="Looking around",
        )
        result = resolve(action, state_manager)
        rubbish = next(
            e for e in result.room_after.entities_visible
            if e.id == "rubbish_pile"
        )
        assert rubbish.soft_items_taken == ["lint (taken 1)"]
        assert rubbish.soft_items_present == ["cork x2"]

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


class TestSoftContentFlow:
    """End-to-end placement and retrieval of soft items (soft_contents)."""

    def _accepted_give(self, state_manager, target_id, item, count=1):
        """Run a give action through resolve + accepted adjudication."""
        from mgmai.engine.post_validate import apply_post_validation
        from mgmai.models.narration import SoftItemAdjudication

        action = TransferAction(
            action_type="transfer",
            target=target_id,
            given_counts={item: count},
            detail=f"Giving {item} to {target_id}",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert len(result.soft_item_proposals) == 1
        proposal = result.soft_item_proposals[0]
        adjudication = SoftItemAdjudication(
            item_name=proposal.item_name,
            action="give",
            accepted=True,
            source_id=proposal.source_id,
            target_id=proposal.target_id,
            count=proposal.count,
        )
        return apply_post_validation(
            None, None, state_manager, result, soft_item_adjudications=[adjudication]
        )

    def test_give_to_entity_writes_soft_contents(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_inventory.append("cork")
        self._accepted_give(state_manager, "korbar", "cork")
        assert soft.soft_contents == {"korbar": {"cork": 1}}
        assert soft.soft_items_taken == {}
        assert "cork" not in soft.soft_inventory

    def test_give_to_room_is_a_legal_drop(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_inventory.append("stone")
        result = self._accepted_give(state_manager, "bag_floor", "stone")
        assert result.soft_items_rejected == []
        assert soft.soft_contents == {"bag_floor": {"stone": 1}}
        assert "stone" not in soft.soft_inventory

    def test_retrieval_from_feature_is_mechanical(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_contents["rubbish_pile"] = {"stone": 2}
        action = TransferAction(
            action_type="transfer",
            target="rubbish_pile",
            taken_items=["stone"],
            detail="Taking the stone back",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.soft_item_proposals == []
        assert result.soft_content_takes == {"rubbish_pile": {"stone": 1}}
        assert soft.soft_contents == {"rubbish_pile": {"stone": 1}}
        assert soft.soft_inventory == ["stone"]
        assert soft.soft_items_taken == {}
        # Turn history records the retrieval.
        assert "Retrieved" in soft.turn_history[-1].engine_result_summary

    def test_retrieval_prunes_zero_entries(self, state_manager):
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_contents["rubbish_pile"] = {"stone": 1}
        action = TransferAction(
            action_type="transfer",
            target="rubbish_pile",
            taken_items=["stone"],
            detail="Taking the stone back",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert soft.soft_contents == {}
        assert soft.soft_inventory == ["stone"]

    def test_retrieval_from_npc_uses_adjudication(self, state_manager):
        from mgmai.engine.post_validate import apply_post_validation
        from mgmai.models.narration import SoftItemAdjudication

        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_contents["korbar"] = {"cork": 1}
        action = TransferAction(
            action_type="transfer",
            target="korbar",
            taken_items=["cork"],
            detail="Taking the cork back",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.soft_content_takes == {}
        assert len(result.soft_item_proposals) == 1
        adjudication = SoftItemAdjudication(
            item_name="cork",
            action="take",
            accepted=True,
            source_id="korbar",
        )
        apply_post_validation(
            None, None, state_manager, result, soft_item_adjudications=[adjudication]
        )
        assert soft.soft_contents == {}
        assert soft.soft_items_taken == {}
        assert soft.soft_inventory == ["cork"]

    def test_shortfall_splits_mechanical_and_ambient(self, state_manager):
        from mgmai.engine.post_validate import apply_post_validation
        from mgmai.models.narration import SoftItemAdjudication

        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_contents["rubbish_pile"] = {"stone": 1}
        action = TransferAction(
            action_type="transfer",
            target="rubbish_pile",
            taken_counts={"stone": 2},
            detail="Taking two stones",
        )
        result = resolve(action, state_manager)
        assert result.success is True
        assert result.soft_content_takes == {"rubbish_pile": {"stone": 1}}
        assert len(result.soft_item_proposals) == 1
        assert result.soft_item_proposals[0].count == 1
        # The mechanical portion is already applied.
        assert soft.soft_contents == {}
        assert soft.soft_inventory == ["stone"]

        adjudication = SoftItemAdjudication(
            item_name="stone",
            action="take",
            accepted=True,
            source_id="rubbish_pile",
            count=1,
        )
        apply_post_validation(
            None, None, state_manager, result, soft_item_adjudications=[adjudication]
        )
        assert soft.soft_inventory == ["stone", "stone"]
        # Only the ambient remainder counts as extraction.
        assert soft.soft_items_taken == {"rubbish_pile": {"stone": 1}}

    def test_depletion_integrity_after_give(self, state_manager):
        """A give must not corrupt the depletion signal on the target."""
        hard = state_manager.hard_state
        hard.player.location = "bag_floor"
        soft = state_manager.soft_state
        soft.soft_inventory.append("cork")
        self._accepted_give(state_manager, "korbar", "cork")
        action = WaitAction(action_type="wait", detail="Looking at Korbar")
        result = resolve(action, state_manager)
        korbar = next(
            e for e in result.room_after.entities_visible if e.id == "korbar"
        )
        assert korbar.soft_items_present == ["cork x1"]
        assert korbar.soft_items_taken == []
        assert soft.soft_items_taken == {}


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
        from mgmai.models.actions import ExamineAction
        # Vehicle action: a non-rigorous examine.  (A wait would now pass
        # the combat turn, resolving a full round of enemy attacks.)
        action = ExamineAction(action_type="examine", target="start", detail="Look around")
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
