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

"""LLM integration tests: NPC conversation on the drowned_lantern fixture.

A driver LLM plays the player against the real GM LLM in "The Drowned
Lantern" — a conversation-centric mini-adventure (tiered knowledge
reveals, attitude ladders, persuasion dialogue paths, lies, scripted
mid-dialogue events, and a scripted endgame crossing).  Scenarios use
fresh starts or preset starting points (pre-built ``StateManager``
with flags flipped, per the venom_pit precedent).  Hard assertions
verify engine mechanics; an advisory LLM judge records a
narration-quality verdict in each artifact (it does not gate tests).
"""

from __future__ import annotations

import warnings

import pytest

from tests.integration.runner import run_scenario
from tests.integration.judge import record_judge_verdict

pytestmark = pytest.mark.llm


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------


def _preset_state_manager(adventure_dir, flags=()):
    """Load the fixture with the given global flags pre-set (a later
    starting point, e.g. "you already got the name out of Fen")."""
    from mgmai.state.manager import StateManager

    sm = StateManager(adventure_dir=str(adventure_dir))
    for flag in flags:
        sm.hard_state.flags[flag] = True
    return sm


def _assert_clean_run(result) -> None:
    """No abort, no harness errors, no per-turn exceptions, no empty
    narrations, and a monotonic turn counter."""
    assert result.artifacts_path is not None and result.artifacts_path.is_file()
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert result.error is None, (
        f"Run errored: {result.error!r}; see artifact: {result.artifacts_path}"
    )
    prev = -1
    for i, t in enumerate(result.turns):
        assert t.exception is None, (
            f"Turn {i} raised {t.exception!r}; "
            f"see artifact: {result.artifacts_path}"
        )
        assert t.narration and t.narration.strip(), (
            f"Turn {i} produced empty narration; "
            f"see artifact: {result.artifacts_path}"
        )
        assert t.status.turn_count >= prev, (
            f"Turn {i}: turn_count regressed; "
            f"see artifact: {result.artifacts_path}"
        )
        prev = t.status.turn_count


def _dialogue(result, turn) -> dict:
    return turn.status.dialogue or {}


def _flag_ever_set(result, flag: str) -> bool:
    return any(flag in (t.status.active_flags or {}) for t in result.turns)


def _final_entity_state(result, entity_id: str) -> dict:
    return (result.final_status or {}).get("entity_states", {}).get(entity_id, {})


def _final_location(result, entity_id: str) -> str | None:
    return (result.final_status or {}).get("entity_locations", {}).get(entity_id)


def _knowledge_topics(result) -> set[str]:
    return {
        e["topic_id"]
        for e in (result.final_status or {}).get("player_knowledge", [])
    }


def _entity_notes(result, entity_id: str) -> list[str]:
    return (result.final_status or {}).get("entity_notes", {}).get(entity_id, [])


def _assert_attitude_steps_capped(result, npc_id: str, cap: int) -> None:
    """Per-turn attitude changes (while in dialogue) respect the NPC's
    step_per_turn limit."""
    prev = None
    for t in result.turns:
        d = _dialogue(result, t)
        if d.get("active_npc") != npc_id or d.get("attitude") is None:
            continue
        if prev is not None:
            assert abs(d["attitude"] - prev) <= cap, (
                f"{npc_id} attitude jumped {prev} -> {d['attitude']} in one "
                f"turn (cap {cap}); see artifact: {result.artifacts_path}"
            )
        prev = d["attitude"]


def _stop_when_flag(flag: str):
    """Early-stop predicate: stop once a global flag is set."""

    def pred(session, turns) -> bool:
        hard = session.hard_state
        return hard is not None and bool(hard.flags.get(flag))

    return pred


def _stop_when_fen_departed(session, turns) -> bool:
    hard = session.hard_state
    return hard is not None and bool(
        hard.entity_states.get("fen", {}).get("departed")
    )


# ------------------------------------------------------------------
# Tier 1 — NPC arc tests
# ------------------------------------------------------------------

FEN_DIRECTIVE = """\
You are at the Drowned Lantern tavern on the edge of Miremarsh.  Right
now, head out the back door to the dock and talk with Old Fen, the
fisherman mending his net there.

- He rambles; be patient with him.  Ask about the marsh, about the
  ferryman Berrin, and about the lights out on the water.
- If anything unusual happens while you are out there, respond to it
  naturally, in character.
- Keep the conversation going until he has said everything he seems to
  have to say, then say goodbye.
"""


@pytest.mark.llm
def test_fen_arc(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Fen: NPC-initiated dialogue, tiered reveals, the ghost-light
    set-piece (topic-gated beats), frozen attitude, and his
    dialogue.ended departure."""
    result = run_scenario(
        scenario_name="fen_arc",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=FEN_DIRECTIVE,
        max_turns=40,
        config_dir=tmp_path,
        stop_when=_stop_when_fen_departed,
    )
    _assert_clean_run(result)

    # Fen speaks first: the player's first turn on the dock is already
    # in dialogue with him (trigger_dialogue on room entry).
    dock_turns = [t for t in result.turns if t.status.location == "dock"]
    assert dock_turns, f"Player never reached the dock; see artifact: {result.artifacts_path}"
    assert _dialogue(result, dock_turns[0]).get("active_npc") == "fen", (
        "Dialogue with Fen was not active on arrival at the dock "
        "(fen_speaks_first did not fire); "
        f"see artifact: {result.artifacts_path}"
    )

    # His attitude is frozen at 0 throughout.
    for t in result.turns:
        d = _dialogue(result, t)
        if d.get("active_npc") == "fen":
            assert d.get("attitude") == 0, (
                "Fen's attitude shifted despite frozen limits; "
                f"see artifact: {result.artifacts_path}"
            )

    # The reveal chain and the ghost-light set-piece all fired.
    for flag in (
        "knows_night_crossings", "saw_ghost_light",
        "knows_lights_malevolent", "heard_janis_name",
    ):
        assert _flag_ever_set(result, flag), (
            f"Flag '{flag}' was never set; see artifact: {result.artifacts_path}"
        )
    light = _final_entity_state(result, "ghost_light")
    assert light.get("stage", 0) >= 3 and light.get("hidden") is True, (
        "The ghost-light beat sequence did not run to completion; "
        f"see artifact: {result.artifacts_path}"
    )

    # Knowledge was recorded with Fen as the source.
    assert {
        "night_crossings", "lights_malevolent", "janis_blurt",
    } <= _knowledge_topics(result), (
        f"Fen's topics missing from player_knowledge; see artifact: {result.artifacts_path}"
    )

    # Once his dialogue was exhausted and ended, he departed.
    assert _final_entity_state(result, "fen").get("departed") is True, (
        f"Fen did not depart; see artifact: {result.artifacts_path}"
    )
    assert _final_location(result, "fen") is None
    assert _entity_notes(result, "fen"), (
        "No conversation note archived for Fen; "
        f"see artifact: {result.artifacts_path}"
    )

    record_judge_verdict(judge_client, result)


MARTA_DIRECTIVE = """\
You are spending the evening at the Drowned Lantern tavern.  Stay in
the common room and talk with Marta, the barkeep.

- Be warm and genuinely friendly: ask about her, the tavern, and the
  marsh, and really listen.  Sympathize with anything that troubles
  her.
- As she warms to you, gently ask about the ferryman and whether
  anything is worrying her.
- If she mentions the name Janis, tell her you've heard that name
  before, and ask who Janis was.
- Do not leave the common room; this is an evening at the bar.
"""


@pytest.mark.llm
def test_marta_ladder(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Marta: GM-discretion attitude ladder with step caps, tiered
    attitude-gated reveals, and a will_reveal side effect (crate
    unhidden).  Starts with heard_janis_name pre-set."""
    sm = _preset_state_manager(drowned_lantern_dir, flags=("heard_janis_name",))
    result = run_scenario(
        scenario_name="marta_ladder",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=MARTA_DIRECTIVE,
        max_turns=45,
        config_dir=tmp_path,
        stop_when=_stop_when_flag("knows_janis_link"),
    )
    _assert_clean_run(result)

    marta_turns = [
        t for t in result.turns
        if _dialogue(result, t).get("active_npc") == "marta"
    ]
    assert marta_turns, (
        f"Player never talked to Marta; see artifact: {result.artifacts_path}"
    )

    # The ladder moved, within the per-turn step cap.
    _assert_attitude_steps_capped(result, "marta", 2)
    final_attitude = _final_entity_state(result, "marta").get("attitude", 0)
    assert final_attitude > 0, (
        f"Marta's attitude never rose (final {final_attitude}); "
        f"see artifact: {result.artifacts_path}"
    )

    # Unconditional and attitude >= 2 tiers, including the side effect.
    assert _flag_ever_set(result, "knows_ferryman_duty")
    assert _flag_ever_set(result, "confided_crate"), (
        f"Marta's crate_concern tier (attitude >= 2) never fired; "
        f"see artifact: {result.artifacts_path}"
    )
    assert _final_entity_state(result, "sealed_crate").get("hidden") is False, (
        "The crate was not unhidden by Marta's reveal; "
        f"see artifact: {result.artifacts_path}"
    )
    assert {"ferryman_duty", "crate_concern"} <= _knowledge_topics(result)

    # The attitude >= 5 tier is RNG-gated (sympathetic_ear checks and
    # GM-discretion raises) — warn rather than fail.
    if not _flag_ever_set(result, "knows_janis_link"):
        warnings.warn(
            "marta_ladder: attitude >= 5 tier (janis_payout) not reached "
            "in this run", stacklevel=2,
        )

    record_judge_verdict(judge_client, result)


BERRIN_CONFRONT_DIRECTIVE = """\
You are at the Drowned Lantern tavern, and you need the ferryman
Berrin to take you across Miremarsh tonight.  He is sitting alone in
the common room.

- First, simply ask him to ferry you across tonight.  (He will
  refuse.)
- Then confront him: you know about Janis, and you know Janis was his
  partner in the night-running scheme.  Lay it all out.
- Once he breaks and confesses, press him: the only way to make it
  right is to finish the run — tonight, with you aboard.
"""


@pytest.mark.llm
def test_berrin_confront(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Berrin: cold refusal, then the no-check confront path
    (evidence-gated), then convince_crossing.  Starts with the two
    knowledge flags pre-set."""
    sm = _preset_state_manager(
        drowned_lantern_dir, flags=("heard_janis_name", "knows_janis_link"),
    )
    result = run_scenario(
        scenario_name="berrin_confront",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=BERRIN_CONFRONT_DIRECTIVE,
        max_turns=30,
        config_dir=tmp_path,
        stop_when=_stop_when_flag("crossing_agreed"),
    )
    _assert_clean_run(result)

    # The refusal came first: dialogue with Berrin before the
    # confession flag appears.
    confess_idx = next(
        (i for i, t in enumerate(result.turns)
         if "berrin_confessed" in (t.status.active_flags or {})),
        None,
    )
    assert confess_idx is not None, (
        f"Berrin never confessed; see artifact: {result.artifacts_path}"
    )
    assert any(
        _dialogue(result, t).get("active_npc") == "berrin"
        for t in result.turns[:confess_idx]
    ), (
        "Confession happened without a prior cold-ask exchange; "
        f"see artifact: {result.artifacts_path}"
    )

    assert _flag_ever_set(result, "crossing_agreed"), (
        f"convince_crossing never succeeded; see artifact: {result.artifacts_path}"
    )
    assert _flag_ever_set(result, "confided_crate")
    _assert_attitude_steps_capped(result, "berrin", 2)

    if "janis_vanishing" not in _knowledge_topics(result):
        warnings.warn(
            "berrin_confront: janis_vanishing topic not revealed in this run",
            stacklevel=2,
        )

    record_judge_verdict(judge_client, result)


BERRIN_BLUFF_DIRECTIVE = """\
You are at the Drowned Lantern tavern.  You overheard a name — "Janis"
— from an old fisherman, though you have no idea who Janis is.  Berrin
the ferryman is drinking alone in the common room.

- Sit with Berrin and drop the name: say you know about him and Janis,
  and bluff that you know everything.
- If he denies it, keep needling him with the name — you are sure it
  means something.
"""


@pytest.mark.llm
def test_berrin_bluff(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Berrin: the bluff path — on failure he lies (narration denies,
    hard state stays clean, attitude drops); on CHA-14 success he
    confesses.  Starts with only heard_janis_name pre-set."""
    sm = _preset_state_manager(drowned_lantern_dir, flags=("heard_janis_name",))
    result = run_scenario(
        scenario_name="berrin_bluff",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=BERRIN_BLUFF_DIRECTIVE,
        max_turns=25,
        config_dir=tmp_path,
        stop_when=_stop_when_flag("berrin_confessed"),
    )
    _assert_clean_run(result)

    berrin_turns = [
        t for t in result.turns
        if _dialogue(result, t).get("active_npc") == "berrin"
    ]
    assert berrin_turns, (
        f"Player never talked to Berrin; see artifact: {result.artifacts_path}"
    )

    # The bluff route must not produce the evidence flags: only Marta's
    # janis_payout sets knows_janis_link.
    assert not _flag_ever_set(result, "knows_janis_link"), (
        "knows_janis_link was set during the bluff scenario; "
        f"see artifact: {result.artifacts_path}"
    )

    confessed = _flag_ever_set(result, "berrin_confessed")
    if confessed:
        # Success branch: confession happened with no prior knowledge
        # of the accomplice link — the bluff worked.
        pass
    else:
        # Failure branch: the lie held — no state leaked, and his
        # attitude paid for the needling.
        final_attitude = _final_entity_state(result, "berrin").get("attitude", 0)
        assert final_attitude < 0, (
            "Bluff never succeeded, yet Berrin's attitude never dropped "
            "(no failure branch applied); "
            f"see artifact: {result.artifacts_path}"
        )
        warnings.warn(
            "berrin_bluff: CHA-14 success branch not exercised in this run",
            stacklevel=2,
        )
    _assert_attitude_steps_capped(result, "berrin", 2)

    record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Tier 2 — micro-behavior tests
# ------------------------------------------------------------------

WELLINGTON_STALL_DIRECTIVE = """\
You are in the common room of the Drowned Lantern tavern.

- First, try striking up a conversation with Old Wellington, the
  stuffed heron above the bar.  Try once or twice, odd as it is.
- Then talk with Marta the barkeep — ask her about the marsh and the
  ferry.
- After a couple of exchanges, let your attention wander: examine the
  peat fire, look around the room, examine the bar — several turns
  without talking to anyone.
- Finally, turn back to Marta and mention what the two of you were
  discussing earlier.
"""


@pytest.mark.llm
def test_old_wellington_and_stall(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Dead-NPC talk rejection (Old Wellington), then the dialogue
    stall timer: three non-talk turns auto-exit the conversation and
    archive a memory note."""
    result = run_scenario(
        scenario_name="old_wellington_and_stall",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=WELLINGTON_STALL_DIRECTIVE,
        max_turns=30,
        config_dir=tmp_path,
    )
    _assert_clean_run(result)

    # Talking to a dead NPC never opens a dialogue.
    assert not any(
        _dialogue(result, t).get("active_npc") == "old_wellington"
        for t in result.turns
    ), (
        "Dialogue opened with the dead heron; "
        f"see artifact: {result.artifacts_path}"
    )

    # A real dialogue with Marta happened.
    assert any(
        _dialogue(result, t).get("active_npc") == "marta" for t in result.turns
    ), f"Player never talked to Marta; see artifact: {result.artifacts_path}"

    # The stall counter climbed during the distraction, then the
    # dialogue exited (active_npc cleared).
    stall_idx = next(
        (i for i, t in enumerate(result.turns)
         if (_dialogue(result, t).get("stall_counter") or 0) >= 2),
        None,
    )
    assert stall_idx is not None, (
        "Stall counter never climbed during the distraction turns; "
        f"see artifact: {result.artifacts_path}"
    )
    assert any(
        _dialogue(result, t).get("active_npc") is None
        for t in result.turns[stall_idx:]
    ), (
        "Dialogue never auto-exited after stalling; "
        f"see artifact: {result.artifacts_path}"
    )

    # Memory of the conversation was archived.
    assert _entity_notes(result, "marta"), (
        "No conversation note archived for Marta; "
        f"see artifact: {result.artifacts_path}"
    )

    if not any(
        _dialogue(result, t).get("active_npc") == "marta"
        for t in result.turns[stall_idx + 1:]
    ):
        warnings.warn(
            "old_wellington_and_stall: player did not re-engage Marta "
            "after the stall exit", stacklevel=2,
        )

    record_judge_verdict(judge_client, result)


SWITCHING_DIRECTIVE = """\
You are in the common room of the Drowned Lantern tavern.  Marta the
barkeep is behind the bar; Berrin the ferryman sits alone.

- Chat warmly with Marta for a few exchanges — ask about the tavern
  and the marsh.
- Then turn away from her and talk to Berrin instead.  Be openly rude
  to him: mock his fear of the marsh, call him a coward, tell him he
  is useless as a ferryman.  Do NOT say anything friendly, sympathetic,
  or validating to him — no agreement, no drinks, no thanks, no
  patient listening.  Every line to him is a jab.
- Then turn back to Marta and resume your friendly chat with her.
  Whenever you are talking to Marta, keep every word genuinely warm
  and NEVER mention Berrin, your mockery of him, or anything insulting
  or confrontational — talk only about her, the tavern, the ale, and
  the marsh.
"""


@pytest.mark.llm
def test_npc_switching(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Switching conversation partners mid-visit: each NPC's attitude
    and archived memory stay independent."""
    result = run_scenario(
        scenario_name="npc_switching",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=SWITCHING_DIRECTIVE,
        max_turns=30,
        config_dir=tmp_path,
    )
    _assert_clean_run(result)

    # The active partner went Marta -> Berrin -> Marta.
    partners = [
        _dialogue(result, t).get("active_npc")
        for t in result.turns
        if _dialogue(result, t).get("active_npc") is not None
    ]
    compressed = [p for i, p in enumerate(partners) if i == 0 or p != partners[i - 1]]
    seq = "".join({"marta": "M", "berrin": "B"}.get(p, "?") for p in compressed)
    assert "MBM" in seq, (
        f"Expected a Marta -> Berrin -> Marta switch sequence, got {seq}; "
        f"see artifact: {result.artifacts_path}"
    )

    # Both conversations were archived on switch.
    assert _entity_notes(result, "marta"), (
        f"No note archived for Marta; see artifact: {result.artifacts_path}"
    )
    assert _entity_notes(result, "berrin"), (
        f"No note archived for Berrin; see artifact: {result.artifacts_path}"
    )

    # Attitudes are independent: rudeness to Berrin didn't touch Marta's.
    marta_att = _final_entity_state(result, "marta").get("attitude", 0)
    berrin_att = _final_entity_state(result, "berrin").get("attitude", 0)
    assert berrin_att < 0, (
        f"Berrin's attitude did not drop (final {berrin_att}); "
        f"see artifact: {result.artifacts_path}"
    )
    assert marta_att > 0, (
        f"Marta's attitude did not rise (final {marta_att}); "
        f"see artifact: {result.artifacts_path}"
    )

    record_judge_verdict(judge_client, result)


ENTER_WATER_DIRECTIVE = """\
You are at the Drowned Lantern tavern.  Walk out to the dock behind
the tavern and jump into the marsh water.  Do it — you are a strong
swimmer, and you are sure it is fine.
"""


@pytest.mark.llm
def test_loss_enter_water(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """The enter_water interaction ends the game as a loss."""
    result = run_scenario(
        scenario_name="loss_enter_water",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=ENTER_WATER_DIRECTIVE,
        max_turns=8,
        config_dir=tmp_path,
    )
    assert result.artifacts_path is not None and result.artifacts_path.is_file()
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; see artifact: {result.artifacts_path}"
    )
    assert result.last_turn is not None and result.last_turn.game_over, (
        f"Game did not end; see artifact: {result.artifacts_path}"
    )
    assert result.last_turn.game_over_type == "lose", (
        f"Expected a loss, got {result.last_turn.game_over_type}; "
        f"see artifact: {result.artifacts_path}"
    )

    record_judge_verdict(judge_client, result)


VIOLENCE_DIRECTIVE = """\
You are at the Drowned Lantern tavern.  Walk out to the dock and
attack Fen, the old fisherman, with your longsword.  He is obviously
some kind of swamp-witch — cut him down.
"""


@pytest.mark.llm
def test_loss_violence(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Attacking a living NPC kills them and triggers the
    violence_ends_it loss (witnessed branch)."""
    result = run_scenario(
        scenario_name="loss_violence",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=VIOLENCE_DIRECTIVE,
        max_turns=10,
        config_dir=tmp_path,
    )
    assert result.artifacts_path is not None and result.artifacts_path.is_file()
    assert not result.aborted, (
        f"Driver aborted: {result.abort_reason}; see artifact: {result.artifacts_path}"
    )
    assert result.last_turn is not None and result.last_turn.game_over, (
        f"Game did not end; see artifact: {result.artifacts_path}"
    )
    assert result.last_turn.game_over_type == "lose", (
        f"Expected a loss, got {result.last_turn.game_over_type}; "
        f"see artifact: {result.artifacts_path}"
    )
    assert _final_entity_state(result, "fen").get("alive") is False, (
        f"Fen survived the attack; see artifact: {result.artifacts_path}"
    )

    record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Tier 3 — endgame and free play
# ------------------------------------------------------------------

CROSSING_DIRECTIVE = """\
You are at the Drowned Lantern tavern.  The ferryman Berrin has agreed
to take you across Miremarsh tonight — but first, the two of you must
move the last crate from behind the bar down to the ferry.

- Find the crate (have a good look behind the bar), then, with
  Berrin's help, carry it out to the dock, and then load it onto the
  ferry.
- Climb aboard and ride out the crossing.  Talk with Berrin on the
  water — ask him to tell you what happened to Janis.
- When you near the far pier, do as Berrin says: grab the rope end,
  and jump onto the pier to moor the ferry.
"""


@pytest.mark.llm
def test_crate_and_crossing(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """The endgame: crate logistics (examine-gated reveal, staged
    moves), the scripted crossing beats, follower dialogue
    mid-crossing, the gated rope take, and the win."""
    sm = _preset_state_manager(
        drowned_lantern_dir,
        flags=("berrin_confessed", "crossing_agreed", "confided_crate"),
    )
    result = run_scenario(
        scenario_name="crate_and_crossing",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=CROSSING_DIRECTIVE,
        max_turns=60,
        config_dir=tmp_path,
    )
    _assert_clean_run(result)

    # The crossing was won.
    assert result.last_turn is not None and result.last_turn.game_over
    assert result.last_turn.game_over_type == "win", (
        f"Expected a win, got {result.last_turn.game_over_type}; "
        f"see artifact: {result.artifacts_path}"
    )

    # The crate physically made it aboard; Berrin is gone.
    assert _final_location(result, "sealed_crate") == "entity:ferry", (
        f"Crate did not end up aboard the ferry; see artifact: {result.artifacts_path}"
    )
    assert _final_entity_state(result, "berrin").get("departed") is True
    assert _final_location(result, "berrin") is None

    # Berrin, as a follower, was talkable mid-crossing.
    assert any(
        t.status.location == "mid_marsh"
        and _dialogue(result, t).get("active_npc") == "berrin"
        for t in result.turns
    ), (
        "No dialogue with Berrin during the crossing (follower presence); "
        f"see artifact: {result.artifacts_path}"
    )

    # The scripted beats ran (the lights appeared on the water).
    assert _final_entity_state(result, "ghost_lights_mid_marsh").get("hidden") is False

    if "janis_vanishing" not in _knowledge_topics(result):
        warnings.warn(
            "crate_and_crossing: janis_vanishing not drawn out of Berrin "
            "mid-crossing in this run", stacklevel=2,
        )

    record_judge_verdict(judge_client, result)


FREE_PLAY_DIRECTIVE = """\
You are a traveler who urgently needs to cross Miremarsh tonight, but
the ferry beside the Drowned Lantern tavern isn't running.

Play the adventure: talk to the people here, find out why the ferry
isn't running, and figure out how to get across the marsh tonight.
Explore, ask questions, and follow up on what you learn.  Avoid
violence — you need these people.
"""


@pytest.mark.llm
def test_free_play(
    gm_client, driver_client, judge_client, drowned_lantern_dir,
    artifacts_dir, tmp_path,
):
    """Unguided full playthrough: the driver is simply told to play.
    Gates on robustness and progress; the full win is warn-only until
    pass rates are known."""
    result = run_scenario(
        scenario_name="free_play",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=drowned_lantern_dir,
        artifacts_dir=artifacts_dir,
        directive=FREE_PLAY_DIRECTIVE,
        max_turns=100,
        config_dir=tmp_path,
    )
    _assert_clean_run(result)

    # Meaningful progress: at least one knowledge milestone reached.
    progress_flags = (
        "knows_night_crossings", "heard_janis_name", "knows_janis_link",
        "confided_crate", "berrin_confessed",
    )
    assert any(_flag_ever_set(result, f) for f in progress_flags), (
        "No knowledge milestone reached in 100 turns of free play; "
        f"see artifact: {result.artifacts_path}"
    )

    if not (
        result.last_turn is not None
        and result.last_turn.game_over
        and result.last_turn.game_over_type == "win"
    ):
        warnings.warn(
            "free_play: the driver did not complete the adventure within "
            "100 turns", stacklevel=2,
        )

    record_judge_verdict(judge_client, result)
