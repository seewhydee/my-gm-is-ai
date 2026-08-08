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

"""LLM integration tests for the combat action economy (turn budget).

The action economy (``TurnBudget`` on ``CombatState``: one action, one
bonus action, one free object interaction, one reaction, one slot spell
per turn — see ``mgmai/models/combat.py`` and ``resolve_combat_turn`` in
``mgmai/engine/combat.py``) is covered in two styles:

- Seven SCRIPTED scenarios use the single-turn ``run_indicator_turn``
  harness (same as ``test_combat_positioning.py``): a hand-written
  ``PlayerAction`` is resolved by the real engine against a preset
  ``CombatState`` (Call 1 is bypassed so the mechanical outcome is
  controlled) and the real GM prose call narrates the segment.

  A player turn that stays open (``turn_continuation``) spans several
  commands, so the multi-segment scenarios CHAIN several
  ``run_indicator_turn`` calls on one shared ``StateManager``: the
  harness resolves one fixed action per call, but the live combat state
  — budget flags, ``turn_continuation``, ``reactions_spent``,
  ``action_weapon_id`` — persists on the StateManager between calls,
  and each segment still gets the real GM prose call.  Assertions on
  the open/closed state of the turn read the live
  ``sm.hard_state.combat`` (the ``status.player_budget`` snapshot
  surface is exercised end-to-end by the playtest below).

  The fixtures declare no bonus-action ability and no Light weapons, so
  those are preset on the loaded player state (like the HP/AC presets
  elsewhere): the SRD spell pack's ``healing_word`` (leveled
  bonus-action spell) plus level-1 slots, and the SRD gear pack's
  ``shortsword`` + ``dagger`` for dual-wielding.

- One PLAYTEST scenario (``test_action_economy_playtest``) drives a
  player LLM against the real GM LLM with a directive that tempts
  over-budget play ("attack AND flame strike AND drink a potion every
  turn").  Hard gates are per-round invariants on the combat log (at
  most one action-costing player entry per round), graceful handling of
  rejected turns, and the ``status.player_budget`` snapshot structure;
  whether the GM actually had to reject an over-budget ruling is
  recorded as a warning, never a failure.

Dice are pinned with ``seed=7`` per segment (the harness seeds
``random`` immediately before ``resolve``); the scenario expectations
were derived by running the same engine sequences offline with that
seed.  The assertions are structural (entry shapes, budget flags, round
numbers), so they hold regardless of seeded hit/miss outcomes.

One deliberate contrivance: the third-attack rejection in
``test_off_hand_attack`` presets a mid-turn budget (action and bonus
action both spent, turn open) because the §3.3 auto-end rule closes the
player turn the moment both are spent — no organic third attack can
ever be attempted through the normal pipeline.  The rejection branch
itself is real engine behaviour (a ruling can only reach it with the
turn still open).
"""

from __future__ import annotations

import pytest

from mgmai.models.combat import CombatState
from mgmai.state.manager import StateManager
from tests.integration.helpers import assert_combat_concluded, record_warning
from tests.integration.indicator_runner import run_indicator_turn
from tests.integration.judge import record_judge_verdict
from tests.integration.runner import run_scenario
from tests.integration.test_combat_arena import _stop_when_combat_ended

pytestmark = pytest.mark.llm

# Pinned dice for the scripted scenarios (see module docstring).
_SEED = 7

_GRUNT_AND_BUGBEAR = ["player", "goblin_grunt", "bugbear"]


def _sm(adventure_dir) -> StateManager:
    return StateManager(adventure_dir=str(adventure_dir))


def _sm_in_combat(
    adventure_dir,
    combatants,
    *,
    allies=(),
    engagement=None,
) -> StateManager:
    """Load the fixture with the player mid-combat against the given
    combatants, acting first, with the given allies/engagement preset."""
    sm = _sm(adventure_dir)
    sm.hard_state.combat = CombatState(
        active=True,
        combatants=list(combatants),
        allies=list(allies),
        initiative_order=list(combatants),
        current_index=0,
        round_number=1,
        engagement=[list(pair) for pair in (engagement or [])],
    )
    return sm


def _grant_healing_word(sm) -> None:
    """Preset the SRD bonus-action spell (and level-1 slots for it) on
    the loaded player — the fixtures declare no bonus-action ability."""
    player = sm.hard_state.player
    if "healing_word" not in player.abilities:
        player.abilities = list(player.abilities) + ["healing_word"]
    player.spell_slots = {1: 2}


# ------------------------------------------------------------------
# Shared scripted-segment assertions
# ------------------------------------------------------------------


def _entries(result, *, actor=None, action=None):
    """Yield combat-log entries from a scripted segment's engine result."""
    for entry in (result.engine_result or {}).get("combat_log", []):
        if actor is not None and entry.get("actor") != actor:
            continue
        if action is not None and entry.get("action") != action:
            continue
        yield entry


def _segment(
    scenario_name,
    gm_client,
    sm,
    action,
    player_input,
    config_dir,
    artifacts_dir,
):
    """Run one scripted segment and apply the shared hard assertions:
    the artifact was written and the real GM prose call narrated the
    segment (an over-budget rejection is a normal narration, not a
    harness error)."""
    result = run_indicator_turn(
        scenario_name=scenario_name,
        gm_client=gm_client,
        state_manager=sm,
        action=action,
        player_input=player_input,
        config_dir=config_dir,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )
    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()
    assert result.error is None, (
        f"Segment raised {result.error!r}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.raw_narration and result.raw_narration.strip(), (
        f"Narrator produced empty narration; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.final_narration and result.final_narration.strip()
    return result


def _combat(sm) -> CombatState:
    combat = sm.hard_state.combat
    assert combat is not None, "Combat ended unexpectedly"
    return combat


def _assert_turn_open(sm, *, round_number) -> None:
    combat = _combat(sm)
    assert combat.turn_continuation is True
    assert combat.round_number == round_number


def _assert_turn_closed(sm, *, round_number) -> None:
    combat = _combat(sm)
    assert combat.turn_continuation is False
    assert combat.round_number == round_number


def _attack(target, detail, **extra):
    return {
        "action_type": "combat",
        "combat_action": "attack",
        "target": target,
        "detail": detail,
        **extra,
    }


def _cast(ability_id, target, detail):
    return {
        "action_type": "use_ability",
        "ability_id": ability_id,
        "target": target,
        "detail": detail,
    }


# ------------------------------------------------------------------
# Scenario 1: open-turn continuation — bonus action, then main action
# ------------------------------------------------------------------


@pytest.mark.llm
def test_open_turn_continuation(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A bonus-action cast followed by a main-action attack resolves as
    ONE player turn: both log entries land in the same round and the
    NPC turns run only after the second command."""
    sm = _sm_in_combat(combat_arena_dir, _GRUNT_AND_BUGBEAR)
    _grant_healing_word(sm)
    sm.hard_state.player.current_hp = 10  # injured, so the heal lands

    # Segment 1: the bonus action.  The action is still unused, so the
    # turn stays open — no NPC turns, no round advance.
    seg1 = _segment(
        "action_economy_open_turn",
        gm_client,
        sm,
        _cast("healing_word", "player", "Mutter a healing word over my wounds."),
        "cast healing word on myself",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    heals = list(_entries(seg1, actor="player", action="heal"))
    assert len(heals) == 1
    assert heals[0].get("attack_id") == "healing_word"
    assert heals[0].get("round") == 1
    assert not [
        e for e in _entries(seg1) if e.get("actor") in ("goblin_grunt", "bugbear")
    ], "NPC turns ran after the bonus-action segment"
    _assert_turn_open(sm, round_number=1)
    budget = _combat(sm).player_budget
    assert budget.bonus_action_used is True
    assert budget.action_used is False
    assert budget.slot_cast_this_turn is True
    assert sm.hard_state.player.spell_slots == {1: 1}

    # Segment 2: the main action, same player turn.  With the bonus
    # action spent and no other legal bonus option, the turn closes:
    # NPC turns run and the round advances.
    seg2 = _segment(
        "action_economy_open_turn",
        gm_client,
        sm,
        _attack("goblin_grunt", "Attack the goblin grunt."),
        "attack the goblin grunt",
        tmp_path,
        artifacts_dir,
    )
    assert (seg2.engine_result or {}).get("success") is True
    attacks = list(_entries(seg2, actor="player", action="attack"))
    assert len(attacks) == 1
    # Both segments' entries landed in the same round.
    assert attacks[0].get("round") == heals[0].get("round") == 1
    # NPC turns ran only after the second command.
    assert [
        e for e in _entries(seg2) if e.get("actor") in ("goblin_grunt", "bugbear")
    ], "No NPC turns after the turn-closing segment"
    _assert_turn_closed(sm, round_number=2)
    # Budget reset at turn end; the attack's consumption is evidenced by
    # the attack entry above and the turn closing.
    assert _combat(sm).player_budget.action_used is False

    record_judge_verdict(judge_client, seg2)


# ------------------------------------------------------------------
# Scenario 2: over-budget rejection — a second main action costs nothing
# ------------------------------------------------------------------


@pytest.mark.llm
def test_over_budget_rejection(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A second main action on an open turn is rejected gracefully:
    ``success: False`` with an engine error, the turn stays open, no
    NPC turns run, and the budget is unchanged — a following legal
    bonus action still closes the turn normally."""
    sm = _sm_in_combat(
        combat_arena_dir,
        ["player", "korbar", "goblin_grunt", "bugbear"],
        allies=["korbar"],
    )
    _grant_healing_word(sm)
    sm.hard_state.entity_states["korbar"]["current_hp"] = 12

    # Segment 1: the attack keeps the turn open (healing_word is a
    # legal bonus action while Korbar lives).
    seg1 = _segment(
        "action_economy_over_budget",
        gm_client,
        sm,
        _attack("goblin_grunt", "Attack the goblin grunt."),
        "attack the goblin grunt",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    _assert_turn_open(sm, round_number=1)
    budget = _combat(sm).player_budget
    assert budget.action_used is True and budget.bonus_action_used is False

    # Segment 2: a second main action — rejected, costing nothing.
    seg2 = _segment(
        "action_economy_over_budget",
        gm_client,
        sm,
        _attack("bugbear", "Attack the bugbear in the same breath."),
        "attack the bugbear too",
        tmp_path,
        artifacts_dir,
    )
    engine_result = seg2.engine_result or {}
    assert engine_result.get("success") is False
    assert "action was already used" in (engine_result.get("error") or "")
    assert engine_result.get("combat_log") == []
    # The turn is still open with the budget untouched: no NPC turns,
    # no round advance, no damage done.
    _assert_turn_open(sm, round_number=1)
    budget = _combat(sm).player_budget
    assert budget.action_used is True and budget.bonus_action_used is False
    assert sm.hard_state.entity_states["bugbear"]["current_hp"] == 22

    # Segment 3: the legal bonus action closes the turn normally,
    # proving the rejection left the turn intact.
    seg3 = _segment(
        "action_economy_over_budget",
        gm_client,
        sm,
        _cast("healing_word", "korbar", "Call a healing word to Korbar."),
        "cast healing word on Korbar",
        tmp_path,
        artifacts_dir,
    )
    assert (seg3.engine_result or {}).get("success") is True
    _assert_turn_closed(sm, round_number=2)
    # Budget reset at turn end; the bonus action's consumption is
    # evidenced by the turn closing (both budgets spent).
    assert _combat(sm).player_budget.bonus_action_used is False

    record_judge_verdict(judge_client, seg3)


# ------------------------------------------------------------------
# Scenario 3: dual-wielded Light weapons — bonus-action off-hand attack
# ------------------------------------------------------------------


@pytest.mark.llm
def test_off_hand_attack(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """With two Light weapons equipped, a second attack in the turn
    resolves as the bonus-action off-hand attack; a third attack is
    rejected once the action and the bonus action are both spent.

    The third-attack segment presets the mid-turn budget (both spent,
    turn open): the auto-end rule closes the turn as soon as both are
    spent, so the both-spent rejection branch is otherwise unreachable
    through the pipeline (see module docstring).
    """
    sm = _sm_in_combat(combat_arena_dir, _GRUNT_AND_BUGBEAR)
    player = sm.hard_state.player
    player.inventory = {"shortsword": 1, "dagger": 1, "potion_of_healing": 2}
    player.equipped = ["shortsword", "dagger"]

    # Segment 1: the Attack action with the (Light) shortsword keeps
    # the turn open — the off-hand dagger is a legal bonus action.
    seg1 = _segment(
        "action_economy_off_hand",
        gm_client,
        sm,
        _attack("goblin_grunt", "Attack the goblin grunt with my shortsword."),
        "attack the goblin grunt with my shortsword",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    attacks = list(_entries(seg1, actor="player", action="attack"))
    assert len(attacks) == 1 and attacks[0].get("round") == 1
    _assert_turn_open(sm, round_number=1)
    combat = _combat(sm)
    assert combat.player_budget.action_used is True
    assert combat.action_weapon_id == "shortsword"

    # Segment 2: the off-hand attack with the dagger — a second attack
    # entry in the same round, closing the turn.
    seg2 = _segment(
        "action_economy_off_hand",
        gm_client,
        sm,
        _attack("bugbear", "Slash the bugbear with my off-hand dagger."),
        "strike the bugbear with my off-hand dagger",
        tmp_path,
        artifacts_dir,
    )
    assert (seg2.engine_result or {}).get("success") is True
    off_hand = list(_entries(seg2, actor="player", action="attack"))
    assert len(off_hand) == 1 and off_hand[0].get("round") == 1
    combat = _combat(sm)
    # Budget and weapon bookkeeping reset at turn end; the off-hand
    # attack's bonus-action consumption is evidenced by the second
    # attack entry above and the turn closing.
    assert combat.player_budget.bonus_action_used is False
    assert combat.action_weapon_id is None
    _assert_turn_closed(sm, round_number=2)

    # Segment 3: a third attack with the action and the bonus action
    # both spent (mid-turn state preset) — rejected, costing nothing.
    combat.player_budget.action_used = True
    combat.player_budget.bonus_action_used = True
    combat.turn_continuation = True
    seg3 = _segment(
        "action_economy_off_hand",
        gm_client,
        sm,
        _attack("goblin_grunt", "Attack once more!"),
        "attack again",
        tmp_path,
        artifacts_dir,
    )
    engine_result = seg3.engine_result or {}
    assert engine_result.get("success") is False
    assert "both already used" in (engine_result.get("error") or "")
    assert engine_result.get("combat_log") == []
    assert _combat(sm).round_number == 2

    record_judge_verdict(judge_client, seg3)


# ------------------------------------------------------------------
# Scenario 4: reaction cap — one opportunity attack per round
# ------------------------------------------------------------------


@pytest.mark.llm
def test_reaction_cap(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Two enemies leaving the player's reach in the same round provoke
    only ONE player opportunity attack — the second is blocked by
    ``reactions_spent``.  The reaction refreshes when the player's turn
    cycles, so the next round's provocation lands again."""
    sm = _sm_in_combat(
        combat_arena_dir,
        _GRUNT_AND_BUGBEAR,
        engagement=[["goblin_grunt", "player"], ["bugbear", "player"]],
    )
    # The bugbear (22 HP) is listed first so the player's single OA
    # targets it rather than the frail grunt — the OA cannot drop it,
    # keeping the follow-up attack legal regardless of seeded damage.
    fall_back = {
        "positioning": {
            "engage": [],
            "disengage": [["bugbear", "player"], ["goblin_grunt", "player"]],
            "impede": [],
        },
    }

    # Segment 1: both enemies fall back; only one OA fires.
    seg1 = _segment(
        "action_economy_reaction_cap",
        gm_client,
        sm,
        _attack(
            "goblin_grunt",
            "Press the attack as the enemies fall back.",
            **fall_back,
        ),
        "attack the goblin grunt as they fall back",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    oas = list(_entries(seg1, actor="player", action="opportunity_attack"))
    assert len(oas) == 1
    assert oas[0].get("target") == "bugbear"
    assert oas[0].get("round") == 1
    # The declared action still proceeded after the OA.
    assert list(_entries(seg1, actor="player", action="attack"))
    _assert_turn_closed(sm, round_number=2)
    # The spent reaction is cleared at turn end (so the next turn's
    # briefing sees it fresh); the single OA above is the evidence the
    # cap held through this round's provocations.
    assert "player" not in _combat(sm).reactions_spent

    # Segment 2 (next round): same provocation — the refreshed reaction
    # fires again.  (Re-assert the engagement pairs; NPC attacks already
    # re-formed them, but be explicit like the unit suite.)
    _combat(sm).engagement = [["goblin_grunt", "player"], ["bugbear", "player"]]
    seg2 = _segment(
        "action_economy_reaction_cap",
        gm_client,
        sm,
        _attack(
            "goblin_grunt",
            "Again: press the attack as they fall back.",
            **fall_back,
        ),
        "attack again as they fall back",
        tmp_path,
        artifacts_dir,
    )
    assert (seg2.engine_result or {}).get("success") is True
    oas = list(_entries(seg2, actor="player", action="opportunity_attack"))
    assert len(oas) == 1
    assert oas[0].get("round") == 2
    assert "player" not in _combat(sm).reactions_spent

    record_judge_verdict(judge_client, seg2)


# ------------------------------------------------------------------
# Scenario 5: drinking a potion always costs the action
# ------------------------------------------------------------------


@pytest.mark.llm
def test_potion_costs_the_action(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Drinking a potion spends the action: a follow-up attack in the
    same turn is rejected (no off-hand attack without an Attack action),
    while the turn stays open for a legal bonus action."""
    sm = _sm_in_combat(
        combat_arena_dir,
        ["player", "korbar", "goblin_grunt", "bugbear"],
        allies=["korbar"],
    )
    _grant_healing_word(sm)
    sm.hard_state.player.current_hp = 10  # injured, so the potion lands

    # Segment 1: drink the potion (interaction_cost "action", the
    # ruling-layer default).  The heal resolves; the turn stays open
    # for the legal bonus action.
    seg1 = _segment(
        "action_economy_potion_action",
        gm_client,
        sm,
        {
            "action_type": "interact",
            "target": "potion_of_healing",
            "interaction_id": "drink",
            "detail": "I uncork a healing potion and drink it.",
        },
        "drink a healing potion",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    drinks = list(_entries(seg1, actor="player", action="interact"))
    assert len(drinks) == 1 and drinks[0].get("target") == "potion_of_healing"
    assert list(_entries(seg1, actor="player", action="heal"))
    assert sm.hard_state.player.inventory.get("potion_of_healing") == 1
    _assert_turn_open(sm, round_number=1)
    budget = _combat(sm).player_budget
    assert budget.action_used is True and budget.bonus_action_used is False

    # Segment 2: attack after the potion — rejected: the action is
    # spent and no off-hand attack exists without an Attack action.
    seg2 = _segment(
        "action_economy_potion_action",
        gm_client,
        sm,
        _attack("goblin_grunt", "Attack the goblin grunt."),
        "attack the goblin grunt",
        tmp_path,
        artifacts_dir,
    )
    engine_result = seg2.engine_result or {}
    assert engine_result.get("success") is False
    assert "action was already used" in (engine_result.get("error") or "")
    assert engine_result.get("combat_log") == []
    _assert_turn_open(sm, round_number=1)

    # Segment 3: the legal bonus action closes the turn normally.
    seg3 = _segment(
        "action_economy_potion_action",
        gm_client,
        sm,
        _cast("healing_word", "korbar", "Call a healing word to Korbar."),
        "cast healing word on Korbar",
        tmp_path,
        artifacts_dir,
    )
    assert (seg3.engine_result or {}).get("success") is True
    _assert_turn_closed(sm, round_number=2)

    record_judge_verdict(judge_client, seg3)


@pytest.mark.llm
def test_potion_never_a_free_interaction(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A potion ruled as the free object interaction is rejected —
    potions always require an action — costing nothing: the potion is
    not consumed and the budget is untouched."""
    sm = _sm_in_combat(combat_arena_dir, _GRUNT_AND_BUGBEAR)
    result = _segment(
        "action_economy_potion_free",
        gm_client,
        sm,
        {
            "action_type": "interact",
            "target": "potion_of_healing",
            "interaction_id": "drink",
            "interaction_cost": "free",
            "detail": "I quickly quaff the potion on the move.",
        },
        "quickly quaff the potion",
        tmp_path,
        artifacts_dir,
    )
    engine_result = result.engine_result or {}
    assert engine_result.get("success") is False
    assert "always require an action" in (engine_result.get("error") or "")
    assert engine_result.get("combat_log") == []
    # The rejection cost nothing: potion unconsumed, budget untouched,
    # no NPC turns, no round advance.
    assert sm.hard_state.player.inventory.get("potion_of_healing") == 2
    budget = _combat(sm).player_budget
    assert budget.model_dump() == {
        "action_used": False,
        "bonus_action_used": False,
        "free_interaction_used": False,
        "reaction_used": False,
        "slot_cast_this_turn": False,
    }
    assert _combat(sm).turn_continuation is False
    assert _combat(sm).round_number == 1

    record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 6: one slot spell per turn (the bonus-action slot rule)
# ------------------------------------------------------------------


@pytest.mark.llm
def test_slot_rule(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A leveled bonus-action spell followed by a leveled main-action
    spell is rejected (one slot spell per turn) without consuming the
    slot; a cantrip remains legal and closes the turn."""
    sm = _sm_in_combat(spell_arena_dir, ["player", "goblin_grunt", "hobgoblin"])
    _grant_healing_word(sm)
    # Roomier HP pool: the heal lands and the round-1 NPC retaliation
    # cannot drop the player regardless of seeded rolls.
    sm.hard_state.player.max_hp = 24
    sm.hard_state.player.current_hp = 20

    # Segment 1: healing word (leveled, bonus action).  The slot flag
    # is set; the turn stays open for the main action.
    seg1 = _segment(
        "action_economy_slot_rule",
        gm_client,
        sm,
        _cast("healing_word", "player", "Mutter a healing word over my wounds."),
        "cast healing word on myself",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    heals = list(_entries(seg1, actor="player", action="heal"))
    assert len(heals) == 1 and heals[0].get("attack_id") == "healing_word"
    _assert_turn_open(sm, round_number=1)
    budget = _combat(sm).player_budget
    assert budget.bonus_action_used is True
    assert budget.slot_cast_this_turn is True
    assert sm.hard_state.player.spell_slots == {1: 1}

    # Segment 2: magic missile (leveled, action) — rejected by the slot
    # rule, costing nothing (the slot is NOT consumed).
    seg2 = _segment(
        "action_economy_slot_rule",
        gm_client,
        sm,
        _cast("magic_missile", "goblin_grunt", "Magic missile the goblin grunt."),
        "cast magic missile at the goblin grunt",
        tmp_path,
        artifacts_dir,
    )
    engine_result = seg2.engine_result or {}
    assert engine_result.get("success") is False
    assert "one slot spell per turn" in (engine_result.get("error") or "")
    assert engine_result.get("combat_log") == []
    _assert_turn_open(sm, round_number=1)
    assert sm.hard_state.player.spell_slots == {1: 1}

    # Segment 3: a cantrip is still legal and closes the turn.
    seg3 = _segment(
        "action_economy_slot_rule",
        gm_client,
        sm,
        _cast("fire_bolt", "goblin_grunt", "Hurl a fire bolt at the goblin grunt."),
        "cast fire bolt at the goblin grunt",
        tmp_path,
        artifacts_dir,
    )
    assert (seg3.engine_result or {}).get("success") is True
    bolts = list(_entries(seg3, actor="player", action="attack"))
    assert len(bolts) == 1 and bolts[0].get("attack_id") == "fire_bolt"
    assert bolts[0].get("round") == 1
    assert [
        e for e in _entries(seg3) if e.get("actor") in ("goblin_grunt", "hobgoblin")
    ], "No NPC turns after the turn-closing segment"
    _assert_turn_closed(sm, round_number=2)

    record_judge_verdict(judge_client, seg3)


# ------------------------------------------------------------------
# Scenario 7: playtest — over-budget temptation through the LLM pipeline
# ------------------------------------------------------------------

ACTION_ECONOMY_DIRECTIVE = """\
You are fighting a battle in a gladiatorial arena alongside your ally
Korbar.  Four enemies face you: a goblin grunt, a goblin runner, a
goblin shaman, and a bugbear.

Your objective: DEFEAT ALL ENEMIES while doing AS MUCH AS POSSIBLE on
every turn.

Tactics:
- Every combat turn, try to COMBINE several things at once: attack an
  enemy with your longsword AND use your flame strike ability AND
  drink a healing potion — as many as you can get away with in a
  single turn.
- If the GM rules that something is not possible in one turn, do not
  argue — just do the remaining part on your next turn.
- The bugbear is vulnerable to fire — flame strike it when you can.
- Do NOT flee the arena.  Fight to the end.
"""

_ARENA_ENEMIES = {"goblin_grunt", "goblin_runner", "goblin_shaman", "bugbear"}

#: Player log actions that cost the action (an off-hand bonus attack is
#: impossible in the arena — no Light weapons exist there — and potion
#: "heal" entries are companions of the "interact" entry, so "heal" is
#: deliberately excluded to avoid double-counting one drink).
_ACTION_COSTING = {
    "attack",
    "ability_save",
    "ability_auto",
    "ability_on_cast",
    "maneuver",
    "dodge",
    "interact",
    "flee",
}

_BUDGET_KEYS = {
    "action_used",
    "bonus_action_used",
    "free_interaction_used",
    "reaction_used",
    "slot_cast_this_turn",
    "reactions_spent",
    "action_weapon_id",
    "turn_continuation",
}


@pytest.mark.llm
def test_action_economy_playtest(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver LLM is tempted into over-budget play; hard gates are
    per-round invariants on the combat log (at most one action-costing
    player entry per round), graceful rejection handling, and the
    ``status.player_budget`` snapshot structure."""
    result = run_scenario(
        scenario_name="action_economy_playtest",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=combat_arena_dir,
        artifacts_dir=artifacts_dir,
        directive=ACTION_ECONOMY_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat started and concluded cleanly (win or graceful loss).
    assert_combat_concluded(result, _ARENA_ENEMIES, accept_fled={"goblin_runner"})

    # One action per turn (hard gate): in every round, at most one
    # action-costing player entry — however the GM split the driver's
    # combo commands.
    costing_by_round: dict[int, list[dict]] = {}
    for t in result.turns:
        for entry in t.combat_log:
            if entry.get("actor") != "player":
                continue
            if entry.get("action") in _ACTION_COSTING:
                costing_by_round.setdefault(entry.get("round") or 0, []).append(entry)
    for rnd, entries in sorted(costing_by_round.items()):
        assert len(entries) <= 1, (
            f"Round {rnd}: {len(entries)} action-costing player entries "
            f"(one action per turn): {entries}; "
            f"see artifact: {result.artifacts_path}"
        )

    # Rejections are graceful (hard gate): any failed turn carries an
    # engine error string — a ruling rejection, never a silent failure
    # or an exception (exceptions are gated by assert_combat_concluded).
    for i, t in enumerate(result.turns, 1):
        if t.success is False:
            assert t.engine_error, (
                f"Turn {i} failed without an engine error; "
                f"see artifact: {result.artifacts_path}"
            )

    # Budget exposure (hard gate): every in-combat status snapshot
    # carries the player-budget surface.
    for t in result.turns:
        if not t.status.in_combat:
            continue
        assert _BUDGET_KEYS <= set(t.status.player_budget), (
            f"In-combat snapshot lacks player_budget keys: "
            f"{t.status.player_budget}; see artifact: {result.artifacts_path}"
        )

    # Over-budget attempts (advisory): the directive tempts them, but
    # whether the GM actually over-rules depends on its rulings — an
    # absent rejection only warns.  Either layer counts: an engine-level
    # rejection (success False) or a ruling that budget validation
    # rejected and sent to corrective retry (recorded as ruling_retries;
    # budget-validation messages all reference the turn's budget with
    # "this turn").
    def _budget_rejected(t) -> bool:
        if t.success is False:
            return True
        return any("this turn" in err for err in t.ruling_retries)

    if not any(_budget_rejected(t) for t in result.turns):
        record_warning(
            result,
            "No over-budget rejection occurred (GM never ruled an "
            "over-budget action); see artifact: " + str(result.artifacts_path),
            stacklevel=2,
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    record_judge_verdict(judge_client, result)
