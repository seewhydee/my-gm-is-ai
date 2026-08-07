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

"""Tests for game/session.py — the front-end-agnostic GameSession core."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from mgmai.game.headless import RecordingView
from mgmai.game.session import GameSession, TurnResult
from mgmai.state.manager import StateManager

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeLLMClient:
    """Returns predetermined JSON strings for ruling and prose calls."""

    def __init__(
        self,
        ruling_response: str | None = None,
        prose_response: str | None = None,
    ) -> None:
        self._ruling = ruling_response
        self._prose = prose_response
        self.ruling_calls: list[tuple[str, str]] = []
        self.prose_calls: list[tuple[str, str]] = []

    def call_ruling(self, system_prompt: str, user_prompt: str) -> str:
        self.ruling_calls.append((system_prompt, user_prompt))
        if self._ruling is None:
            raise RuntimeError("No ruling response configured")
        return self._ruling

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        self.prose_calls.append((system_prompt, user_prompt))
        if self._prose is None:
            raise RuntimeError("No prose response configured")
        return self._prose


def _wait_action_json(detail: str = "Waiting") -> str:
    return json.dumps({
        "action_type": "wait",
        "detail": detail,
        "follow_up": None,
        "soft_state_patches": [],
    })


def _prose_json(narration: str = "The GM narrates.") -> str:
    return json.dumps({
        "narration": narration,
        "npc_response": None,
        "knowledge_tags": None,
        "attitude_changes": None,
    })


def _wait_llm(narration: str = "Time passes.") -> FakeLLMClient:
    return FakeLLMClient(
        ruling_response=_wait_action_json(),
        prose_response=_prose_json(narration),
    )


def _make_session(state_manager, tmp_path, llm=None, **kw) -> GameSession:
    return GameSession(
        state_manager,
        llm or _wait_llm(),
        view=RecordingView(),
        config_dir=tmp_path,
        **kw,
    )


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


class TestGameSessionPublicAPI:
    def test_begin_renders_intro(self, state_manager, tmp_path) -> None:
        session = _make_session(state_manager, tmp_path)
        session.begin()
        intros = session._view.intros
        assert len(intros) == 1
        assert intros[0]["title"] == state_manager.corpus.adventure.title

    def test_submit_returns_turn_result(self, state_manager, tmp_path) -> None:
        session = _make_session(state_manager, tmp_path)
        result = session.submit("I wait")

        assert isinstance(result, TurnResult)
        assert result.narration == "Time passes."
        assert result.game_over is False
        assert result.game_over_type is None
        assert result.status.turn_count == 1
        assert result.success is True
        assert result.engine_error is None
        assert result.ruled_action["action_type"] == "wait"
        assert result.errors == []

    def test_finished_after_game_over(self, state_manager, tmp_path) -> None:
        # The bag-of-holding win mechanic is triggered by padlock_unlocked.
        state_manager.hard_state.flags["padlock_unlocked"] = True
        session = _make_session(state_manager, tmp_path)

        assert session.finished is False
        result = session.submit("do something")

        assert result.game_over is True
        assert result.game_over_type == "win"
        assert session.finished is True
        assert len(session._view.game_over_events) == 1

    def test_finished_after_exit_command(self, state_manager, tmp_path) -> None:
        session = _make_session(state_manager, tmp_path)
        result = session.submit("/quit")

        assert session.finished is True
        assert result.narration is None
        assert result.status.turn_count == 0  # no turn ran

    def test_game_over_turn_is_autosaved(self, state_manager, tmp_path) -> None:
        """Resume-after-restart must capture the final state."""
        state_manager.hard_state.flags["padlock_unlocked"] = True
        session = _make_session(state_manager, tmp_path)
        session.submit("do something")

        autosaves = list(tmp_path.rglob("autosave.json"))
        assert len(autosaves) == 1
        saved = json.loads(autosaves[0].read_text())
        assert saved["hard"]["game_over"] is not None

    def test_latest_narration_in_named_save(
        self, state_manager, tmp_path
    ) -> None:
        session = _make_session(state_manager, tmp_path)
        session.submit("I wait")
        session.submit("/save mysave.json")

        saves = [p for p in tmp_path.rglob("mysave.json")]
        assert len(saves) == 1
        saved = json.loads(saves[0].read_text())
        assert saved["latest_narration"] == "Time passes."


# ------------------------------------------------------------------
# Autosave plumbing (4.7)
# ------------------------------------------------------------------


class TestAutosavePlumbing:
    def test_no_cwd_fallback_without_dirs(
        self, state_manager, tmp_path, monkeypatch
    ) -> None:
        """With neither config_dir nor saves_dir there is no CWD-relative
        autosave.json fallback — autosave is simply disabled."""
        session = GameSession(
            state_manager, _wait_llm(), view=RecordingView(),
        )
        assert session.get_autosave_path() is None

        monkeypatch.chdir(tmp_path)
        session.submit("I wait")
        assert not (tmp_path / "autosave.json").exists()

    def test_saves_dir_override_wins(self, state_manager, tmp_path) -> None:
        sandbox = tmp_path / "chat-sandbox"
        session = GameSession(
            state_manager, _wait_llm(), view=RecordingView(),
            config_dir=tmp_path / "elsewhere",
            saves_dir=sandbox,
        )
        path = session.get_autosave_path()
        assert path == sandbox / "autosave.json"

        session.submit("I wait")
        assert (sandbox / "autosave.json").exists()
        assert not list((tmp_path / "elsewhere").rglob("autosave.json"))

    def test_rest_mode_steps_are_autosaved(self, tmp_path) -> None:
        """Rest bookkeeping mutates state outside the turn pipeline; it
        must be persisted so a restart never loses it."""
        from mgmai.models.hard_state import HardGameState, HitDice, PlayerState
        from mgmai.models.soft_state import SoftGameState
        from tests.helpers import build_state_manager, make_char_sheet_corpus

        corpus = make_char_sheet_corpus()
        player = PlayerState(
            location="axe_head",
            current_hp=4, max_hp=11,
            stats={"strength": 10, "dexterity": 10, "constitution": 10,
                   "intelligence": 10, "wisdom": 10, "charisma": 10},
            spell_slots={1: 0, 2: 1},
            max_spell_slots={1: 4, 2: 2},
            hit_dice=HitDice(die="d8", current=2, max=5),
            spellbook=["fire_bolt", "mage_armor", "magic_missile"],
            abilities=["fire_bolt", "mage_armor", "magic_missile"],
        )
        sm = build_state_manager(
            corpus, HardGameState(player=player), SoftGameState()
        )

        llm = FakeLLMClient(
            ruling_response=json.dumps({
                "action_type": "rest", "kind": "short", "detail": "camp",
                "follow_up": None, "soft_state_patches": [],
            }),
            prose_response=_prose_json("You take a short rest."),
        )
        session = GameSession(
            sm, llm, view=RecordingView(), config_dir=tmp_path,
        )

        session.submit("rest short")
        assert session.in_rest_mode is True
        assert session.rest_mode is not None

        # Spend a hit die (rest step 2), then read the autosave: the
        # bookkeeping mutation must already be persisted.
        session.submit("2")
        autosaves = list(tmp_path.rglob("autosave.json"))
        assert len(autosaves) == 1
        saved = json.loads(autosaves[0].read_text())
        assert saved["hard"]["player"]["hit_dice"]["current"] == 1

        # Done spending, then Done — rest mode exits and the final
        # state is persisted.
        session.submit("2")
        session.submit("3")
        assert session.in_rest_mode is False
        saved = json.loads(autosaves[0].read_text())
        assert saved["hard"]["player"]["hit_dice"]["current"] == 1


# ------------------------------------------------------------------
# Multi-session safety (4.6)
# ------------------------------------------------------------------


def _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state):
    manager = StateManager()
    manager.corpus = copy.deepcopy(sample_corpus)
    manager.hard_state = copy.deepcopy(sample_hard_state)
    manager.soft_state = copy.deepcopy(sample_soft_state)
    manager._adventure_dir = FIXTURES_DIR
    manager._init_contains_from_corpus()
    return manager


class TestMultiSessionSafety:
    def test_once_reactions_do_not_leak_across_sessions(
        self, sample_corpus, sample_hard_state, sample_soft_state
    ) -> None:
        """Two sessions in one process: firing a once-reaction in one
        must not disable it in the other (the old module-level set was
        shared and corrupted cross-session)."""
        from mgmai.engine.event_bus import dispatch_reactions, find_matching_reactions
        from mgmai.models.corpus import Reaction, ReactionEffects, Result

        m1 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)
        m2 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)

        for m in (m1, m2):
            room = m.corpus.rooms[m.hard_state.player.location]
            room.reactions.append(Reaction(
                id="once_react",
                on="flag.set",
                once=True,
                effect=ReactionEffects(result=Result(narrative="once")),
            ))

        # Fire in session 1.
        matches = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, m1.hard_state, m1.soft_state,
            m1.corpus, disabled_once=m1.disabled_once,
        )
        assert any(r.id == "once_react" for r, _ in matches)
        dispatch_reactions(matches, m1.hard_state, m1.soft_state, m1.corpus, m1)

        # Session 1: disabled.  Session 2: untouched.
        assert "once_react" in m1.disabled_once
        assert "once_react" not in m2.disabled_once
        matches2 = find_matching_reactions(
            "flag.set", {"flag_id": "x"}, m2.hard_state, m2.soft_state,
            m2.corpus, disabled_once=m2.disabled_once,
        )
        assert any(r.id == "once_react" for r, _ in matches2)

    def test_two_sessions_interleave_without_crosstalk(
        self, sample_corpus, sample_hard_state, sample_soft_state, tmp_path
    ) -> None:
        """Two GameSessions in one process run interleaved turns with
        independent state and separate autosave sandboxes."""
        m1 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)
        m2 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)
        s1 = GameSession(
            m1, _wait_llm("One."), view=RecordingView(),
            config_dir=tmp_path / "chat1",
        )
        s2 = GameSession(
            m2, _wait_llm("Two."), view=RecordingView(),
            config_dir=tmp_path / "chat2",
        )

        r1 = s1.submit("wait")
        r2 = s2.submit("wait")
        r1b = s1.submit("wait")

        assert r1.narration == "One."
        assert r2.narration == "Two."
        assert r1b.status.turn_count == 2
        assert r2.status.turn_count == 1  # no cross-talk
        assert m1.hard_state.turn_count == 2
        assert m2.hard_state.turn_count == 1

        # Autosaves landed in separate sandboxes.
        a1 = list((tmp_path / "chat1").rglob("autosave.json"))
        a2 = list((tmp_path / "chat2").rglob("autosave.json"))
        assert len(a1) == 1 and len(a2) == 1

    def test_loading_one_session_does_not_reset_another(
        self, sample_corpus, sample_hard_state, sample_soft_state
    ) -> None:
        """StateManager.load_all resets only that session's once-reaction
        set (the old global reset wiped every session's state)."""
        m1 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)
        m2 = _fresh_manager(sample_corpus, sample_hard_state, sample_soft_state)
        m1.disabled_once.add("some_once_reaction")
        m2.disabled_once.add("some_once_reaction")

        m1.load_all(FIXTURES_DIR)

        assert m1.disabled_once == set()
        assert m2.disabled_once == {"some_once_reaction"}
