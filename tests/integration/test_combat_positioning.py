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

"""LLM integration tests for theater-of-the-mind combat positioning.

Two harness styles cover the positioning feature (engagement, OA-lite,
Disengage, impede):

- Five SCRIPTED scenarios use the single-turn ``run_indicator_turn``
  harness (same as ``test_narrative_indicators.py``): a hand-written
  ``PlayerAction`` — including a ``positioning`` assertion block, exactly
  as the ruling LLM would emit it — is resolved by the real engine
  against the ``combat_arena`` fixture with a preset ``CombatState``
  (Call 1 is bypassed so the mechanical outcome is controlled), the
  real GM prose call narrates the turn, and an advisory judge scores
  the narration.  Dice are pinned with a fixed seed, so the combat log,
  indicator text, and post-turn engagement state are deterministic.
- One PLAYTEST scenario (``test_positioning_playtest``) drives a player
  LLM against the real GM LLM with a mobility-focused directive, so the
  full ruling pipeline (Call 1 emitting ``positioning`` blocks) and the
  headless status snapshots are exercised end to end.  Only structural
  guarantees are hard gates there; whether the GM actually asserted
  positioning changes is recorded as a warning, never a failure.

Scripted scenario expectations were derived by running the engine
locally with ``random.seed(7)`` immediately before ``resolve`` — the
same seeding the harness applies — so e.g. the bugbear's opportunity
attack in ``positioning_opportunity_attack`` deterministically hits for
5 damage.
"""

from __future__ import annotations

import warnings

import pytest

from mgmai.game.headless import _snapshot_status
from mgmai.models.combat import CombatState
from mgmai.state.manager import StateManager

from tests.integration.helpers import assert_combat_concluded
from tests.integration.indicator_judge import judge_indicator_turn
from tests.integration.indicator_runner import run_indicator_turn
from tests.integration.judge import (
    JudgeError,
    format_verdict_for_failure,
    judge_scenario,
)
from tests.integration.runner import run_scenario

pytestmark = pytest.mark.llm

# Pinned dice for the scripted scenarios (see module docstring).
_SEED = 7

_ARENA_COMBATANTS = ["player", "goblin_grunt", "bugbear"]


def _sm(combat_arena_dir) -> StateManager:
    return StateManager(adventure_dir=str(combat_arena_dir))


def _sm_in_combat(
    combat_arena_dir,
    *,
    engagement: list[list[str]] | None = None,
    status_effects: dict[str, dict[str, int]] | None = None,
) -> StateManager:
    """Load the arena with the player mid-combat against the goblin
    grunt and the bugbear, acting first, with the given engagement pairs
    and NPC status effects preset."""
    sm = _sm(combat_arena_dir)
    sm.hard_state.combat = CombatState(
        active=True,
        combatants=list(_ARENA_COMBATANTS),
        initiative_order=list(_ARENA_COMBATANTS),
        current_index=0,
        round_number=1,
        engagement=engagement or [],
    )
    for cid, effects in (status_effects or {}).items():
        sm.hard_state.entity_states.setdefault(cid, {})["status_effects"] = effects
    return sm


# ------------------------------------------------------------------
# Shared scripted-turn assertions
# ------------------------------------------------------------------


def _combat_entries(result, *, actor=None, action=None):
    """Yield combat-log entries from a scripted turn's engine result."""
    for entry in (result.engine_result or {}).get("combat_log", []):
        if actor is not None and entry.get("actor") != actor:
            continue
        if action is not None and entry.get("action") != action:
            continue
        yield entry


def _assert_scripted_turn(result, *, expected_indicator_texts=()) -> None:
    """Hard assertions shared by the scripted positioning scenarios.

    The indicator formatted texts are deterministic engine output: the
    narrator receives them as markers and ``process_narration``
    prepends any unplaced ones, so each expected line must appear in
    the player-facing narration regardless of narrator behaviour.
    """
    assert result.error is None, (
        f"Turn raised {result.error!r}; see artifact: {result.artifacts_path}"
    )
    assert result.raw_narration and result.raw_narration.strip(), (
        f"Narrator produced empty narration; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.final_narration and result.final_narration.strip()

    # No leftover marker syntax in the player-facing text.
    assert "[MECH" not in result.final_narration, (
        f"Residual marker syntax in final narration:\n"
        f"{result.final_narration}\nsee artifact: {result.artifacts_path}"
    )

    formatted = [ind["formatted"] for ind in result.indicators]
    for text in expected_indicator_texts:
        assert text in formatted, (
            f"Expected indicator {text!r} not produced; got {formatted}; "
            f"see artifact: {result.artifacts_path}"
        )
        assert text in result.final_narration, (
            f"Expected line {text!r} missing from final narration:\n"
            f"{result.final_narration}\nsee artifact: {result.artifacts_path}"
        )


def _engagement_pairs(sm) -> set[frozenset]:
    """The current engagement pairs on the live combat state, as a set."""
    combat = sm.hard_state.combat
    assert combat is not None, "Combat ended unexpectedly"
    return {frozenset(p) for p in combat.engagement}


def _record_indicator_judge_verdict(judge_client, result) -> None:
    """Run the advisory indicator judge and record its verdict.

    Same contract as ``test_narrative_indicators``: the judge never
    gates the test; unparseable or negative verdicts only warn.
    """
    try:
        verdict = judge_indicator_turn(judge_client, result)
    except JudgeError as exc:
        warnings.warn(
            f"Judge LLM produced unparseable output: {exc}; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
        return
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        warnings.warn(
            "Advisory judge rejected the turn.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}",
            stacklevel=2,
        )


# ------------------------------------------------------------------
# Scenario 1: engagement exposure after a plain melee exchange
# ------------------------------------------------------------------

@pytest.mark.llm
def test_positioning_engagement_exposure(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Plain melee round → headless status snapshot exposes
    ``engaged_with``/``impeded`` on every combatant."""
    sm = _sm_in_combat(combat_arena_dir)
    result = run_indicator_turn(
        scenario_name="positioning_engagement_exposure",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin_grunt",
            "detail": "Attack the goblin grunt.",
        },
        player_input="attack the goblin grunt",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_scripted_turn(result)

    # Melee attacks auto-engage attacker <-> target: the player engaged
    # the grunt by attacking it; the bugbear engaged the player on its
    # own attack (engagement forms even though the seeded attack missed).
    assert _engagement_pairs(sm) == {
        frozenset(("player", "goblin_grunt")),
        frozenset(("player", "bugbear")),
    }

    # The headless status snapshot carries positioning on every
    # combatant: sorted ``engaged_with`` id lists and the ``impeded``
    # flag (the surface the playtest scenario inspects per turn).
    snap = _snapshot_status(sm)
    for cid in _ARENA_COMBATANTS:
        entry = snap.combatants[cid]
        assert "engaged_with" in entry and "impeded" in entry
    assert snap.combatants["player"]["engaged_with"] == [
        "bugbear", "goblin_grunt",
    ]
    assert snap.combatants["goblin_grunt"]["engaged_with"] == ["player"]
    assert snap.combatants["bugbear"]["engaged_with"] == ["player"]
    for cid in _ARENA_COMBATANTS:
        assert snap.combatants[cid]["impeded"] is False

    _record_indicator_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 2: directional disengage provokes an opportunity attack
# ------------------------------------------------------------------

@pytest.mark.llm
def test_positioning_opportunity_attack(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Scripted ruling with a ``positioning`` block: engaging the grunt
    while disengaging from the bugbear logs ``reposition`` entries and
    provokes an OA from the stationary bugbear before the attack."""
    sm = _sm_in_combat(combat_arena_dir, engagement=[["bugbear", "player"]])
    result = run_indicator_turn(
        scenario_name="positioning_opportunity_attack",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin_grunt",
            "detail": "Break away from the bugbear and strike the goblin grunt.",
            "positioning": {
                "engage": [["player", "goblin_grunt"]],
                "disengage": [["player", "bugbear"]],
                "impede": [],
            },
        },
        player_input="break away from the bugbear and attack the goblin grunt",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Seed 7 pins the bugbear's OA to a 5-damage hit.
    _assert_scripted_turn(
        result,
        expected_indicator_texts=[
            "**You reposition relative to Bugbear.**",
            "**Bugbear makes an opportunity attack on you: hit for 5 damage.**",
        ],
    )

    # Both assertion-driven engagement changes are logged as reposition
    # entries (engage player<->grunt, then disengage player<->bugbear).
    reposition = list(_combat_entries(result, actor="player", action="reposition"))
    assert [e.get("target") for e in reposition] == ["goblin_grunt", "bugbear"]

    # The OA: one basic attack from the stationary bugbear against the
    # moving player, carrying the full hit/damage/critical chain.
    oas = list(_combat_entries(result, actor="bugbear", action="opportunity_attack"))
    assert len(oas) == 1
    oa = oas[0]
    assert oa.get("target") == "player"
    assert oa.get("hit") is True
    assert oa.get("damage") == 5
    assert oa.get("critical") is False

    # OAs resolve before the declared action (a lethal OA cancels it).
    log = (result.engine_result or {}).get("combat_log", [])
    oa_idx = next(
        i for i, e in enumerate(log) if e.get("action") == "opportunity_attack"
    )
    atk_idx = next(
        i for i, e in enumerate(log)
        if e.get("actor") == "player" and e.get("action") == "attack"
    )
    assert oa_idx < atk_idx

    # No warnings: the whole positioning block was valid and applied.
    assert (result.engine_result or {}).get("warnings") == []

    _record_indicator_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 3: Disengage maneuver breaks engagement without OAs
# ------------------------------------------------------------------

@pytest.mark.llm
def test_positioning_disengage_maneuver(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A ``maneuver: disengage`` ruling (no target) breaks all of the
    player's pairs without provoking OAs; NPC turns then proceed.

    The grunt is preset stunned so it cannot re-engage on its turn,
    which makes the broken pair observable in the post-turn state.
    """
    sm = _sm_in_combat(
        combat_arena_dir,
        engagement=[["bugbear", "player"], ["goblin_grunt", "player"]],
        status_effects={"goblin_grunt": {"stunned": 2}},
    )
    result = run_indicator_turn(
        scenario_name="positioning_disengage_maneuver",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "maneuver",
            "maneuver": "disengage",
            "detail": "Carefully withdraw from melee.",
        },
        player_input="carefully withdraw from melee",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_scripted_turn(
        result,
        expected_indicator_texts=[
            "**You disengage, carefully withdrawing from melee.**",
        ],
    )

    # The maneuver is logged and provoked no opportunity attacks.
    maneuvers = list(_combat_entries(result, actor="player", action="maneuver"))
    assert len(maneuvers) == 1
    assert not list(_combat_entries(result, action="opportunity_attack")), (
        "Disengage provoked an opportunity attack; "
        f"see artifact: {result.artifacts_path}"
    )

    # The grunt's pair was broken and (being stunned) not re-formed;
    # the bugbear re-engaged the player on its own attack, proving NPC
    # turns proceeded normally after the maneuver.
    assert _engagement_pairs(sm) == {frozenset(("player", "bugbear"))}
    assert list(_combat_entries(result, actor="goblin_grunt", action="stunned"))

    _record_indicator_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 4: impede delays an enemy for a round
# ------------------------------------------------------------------

@pytest.mark.llm
def test_positioning_impede(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """An ``impede`` assertion (kick the brazier over) consumes the
    bugbear's turn: it closes in (``impeded`` log entry, no attack) and
    ends engaged with its AI target.  ``impede_used`` records the
    once-per-combat usage."""
    sm = _sm_in_combat(combat_arena_dir)
    result = run_indicator_turn(
        scenario_name="positioning_impede",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin_grunt",
            "detail": "Kick the brazier over toward the bugbear, then strike the grunt.",
            "positioning": {"engage": [], "disengage": [], "impede": ["bugbear"]},
        },
        player_input="kick the brazier over toward the bugbear and attack the goblin grunt",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_scripted_turn(
        result,
        expected_indicator_texts=[
            "**Bugbear is held up by an obstacle and spends its turn closing in.**",
        ],
    )

    # The bugbear's turn was consumed closing in: an ``impeded`` entry
    # and no attack (or ability) entry from it this turn.
    assert list(_combat_entries(result, actor="bugbear", action="impeded"))
    assert not list(_combat_entries(result, actor="bugbear", action="attack"))

    # Closing in engaged the bugbear with its AI target (the player).
    assert frozenset(("player", "bugbear")) in _engagement_pairs(sm)

    # The pending flag was consumed (the snapshot ``impeded`` flag is
    # only visible between the assertion and the enemy's turn — inside
    # one resolve call — so assert on the persistent bookkeeping).
    combat = sm.hard_state.combat
    assert combat.impeded == []
    assert combat.impede_used == ["bugbear"]

    _record_indicator_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 5: soft-fail — invalid positioning never costs the turn
# ------------------------------------------------------------------

@pytest.mark.llm
def test_positioning_soft_fail(
    gm_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A malformed ``positioning`` block is stripped entry by entry
    with warnings; the core attack proceeds normally.

    Note: this exercises the engine's apply-time degradation (the
    ``positioning ... dropped: ...`` warnings in ``result.warnings``).
    The Call-1 strip path (``"positioning assertion ignored: ..."`` in
    ``GameLoop._strip_invalid_positioning``) is bypassed here along
    with the rest of the ruling call, and is covered by the unit suite.
    """
    sm = _sm_in_combat(combat_arena_dir)
    grunt_hp_before = sm.hard_state.entity_states["goblin_grunt"]["current_hp"]
    result = run_indicator_turn(
        scenario_name="positioning_soft_fail",
        gm_client=gm_client,
        state_manager=sm,
        action={
            "action_type": "combat",
            "combat_action": "attack",
            "target": "goblin_grunt",
            "detail": "Attack the goblin grunt.",
            "positioning": {
                # Unknown combatant id.
                "engage": [["player", "ghost"]],
                # Pair is not currently engaged.
                "disengage": [["player", "goblin_grunt"]],
                # Impede may only name living enemy combatants.
                "impede": ["player"],
            },
        },
        player_input="attack the goblin grunt",
        config_dir=tmp_path,
        artifacts_dir=artifacts_dir,
        seed=_SEED,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    _assert_scripted_turn(result)

    engine_result = result.engine_result or {}
    assert engine_result.get("success") is True

    # Every malformed entry was dropped with a warning.
    warnings_out = engine_result.get("warnings") or []
    assert any(
        "positioning engage entry" in w and "ghost" in w for w in warnings_out
    ), f"missing engage warning: {warnings_out}"
    assert any(
        "positioning disengage entry" in w and "not currently engaged" in w
        for w in warnings_out
    ), f"missing disengage warning: {warnings_out}"
    assert any(
        "positioning impede entry" in w and "player" in w for w in warnings_out
    ), f"missing impede warning: {warnings_out}"

    # No positioning effects were applied...
    assert not list(_combat_entries(result, action="reposition"))
    assert not list(_combat_entries(result, action="opportunity_attack"))
    combat = sm.hard_state.combat
    assert combat.impeded == [] and combat.impede_used == []

    # ...but the core action proceeded: the seeded attack hit the grunt
    # for 6 damage.
    attacks = list(_combat_entries(result, actor="player", action="attack"))
    assert len(attacks) == 1 and attacks[0].get("hit") is True
    grunt_hp_after = sm.hard_state.entity_states["goblin_grunt"]["current_hp"]
    assert grunt_hp_after == grunt_hp_before - attacks[0]["damage"]

    _record_indicator_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 6: playtest — mobile fight through the full LLM pipeline
# ------------------------------------------------------------------

POSITIONING_DIRECTIVE = """\
You are fighting a battle in a gladiatorial arena alongside your ally
Korbar.  Four enemies face you: a goblin grunt, a goblin runner, a
goblin shaman, and a bugbear.

Your objective: DEFEAT ALL ENEMIES while fighting MOBILE.

Tactics:
- Open by attacking the goblin grunt with your longsword.
- Switch targets mid-fight — after the grunt, go for the bugbear, then
  the shaman — even while an enemy is right next to you.
- At least once, create an obstacle to slow an enemy down (kick over
  the brazier, topple a crate, scatter debris in its path), then
  attack someone else while it scrambles toward you.
- If you feel surrounded, carefully withdraw from melee to reposition
  before re-engaging.
- If your HP drops below half, drink a healing potion.
- Do NOT flee the arena.  Fight to the end.
"""

_ARENA_ENEMIES = {"goblin_grunt", "goblin_runner", "goblin_shaman", "bugbear"}

#: Log actions produced by the positioning system (not guaranteed in
#: any given playtest run — they depend on GM rulings — so they are
#: surfaced as warnings, never gates).
_POSITIONING_ACTIONS = ("reposition", "opportunity_attack", "maneuver", "impeded")


def _stop_when_combat_ended(session, turns):
    """Stop early once combat has been active and has since ended."""
    combat_was_active = any(t.status.in_combat for t in turns)
    return combat_was_active and not session.in_combat


@pytest.mark.llm
def test_positioning_playtest(
    gm_client,
    driver_client,
    judge_client,
    combat_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver LLM fights a mobile battle; the GM LLM sees engagement in
    its briefing and may assert ``positioning`` blocks.  Hard gates are
    structural (combat concludes; snapshots expose engagement); whether
    the GM actually repositioned anyone is recorded as a warning."""
    result = run_scenario(
        scenario_name="positioning_playtest",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=combat_arena_dir,
        artifacts_dir=artifacts_dir,
        directive=POSITIONING_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat started and concluded cleanly (win or graceful loss).
    assert_combat_concluded(result, _ARENA_ENEMIES, accept_fled={"goblin_runner"})

    # Engagement exposure (hard gate): every in-combat status snapshot
    # carries ``engaged_with``/``impeded`` on every combatant, and after
    # the melee exchanges at least one snapshot shows a live engagement
    # pair (any melee attack forms one, so this is all but guaranteed).
    saw_engagement = False
    for t in result.turns:
        if not t.status.in_combat:
            continue
        for cid, c in t.status.combatants.items():
            assert "engaged_with" in c and "impeded" in c, (
                f"Snapshot combatant '{cid}' lacks positioning fields: {c}; "
                f"see artifact: {result.artifacts_path}"
            )
            if c["engaged_with"]:
                saw_engagement = True
    assert saw_engagement, (
        "No status snapshot ever showed an engagement pair; "
        f"see artifact: {result.artifacts_path}"
    )

    # Positioning mechanics in the log (advisory): target switches and
    # the obstacle/withdraw tactics usually produce reposition / OA /
    # maneuver / impeded entries, but that depends on GM rulings and
    # driver choices, so their absence only warns.
    seen = {
        entry.get("action")
        for t in result.turns
        for entry in t.combat_log
    } & set(_POSITIONING_ACTIONS)
    if not seen:
        warnings.warn(
            "GM never exercised positioning mechanics (no reposition / "
            "opportunity_attack / maneuver / impeded log entries); "
            "see artifact: " + str(result.artifacts_path),
            stacklevel=2,
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    try:
        verdict = judge_scenario(judge_client, result)
    except JudgeError as exc:
        warnings.warn(
            f"Judge LLM produced unparseable output: {exc}; "
            f"see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
        return
    result.judge_verdict = verdict
    result.rewrite_artifact()
    if not verdict.get("pass"):
        warnings.warn(
            "Advisory judge rejected the run.\n"
            + format_verdict_for_failure(verdict)
            + f"\nSee artifact: {result.artifacts_path}",
            stacklevel=2,
        )
