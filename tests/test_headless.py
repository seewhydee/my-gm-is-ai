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

"""Unit tests for the headless harness (mgmai/game/headless.py).

These tests use a FakeLLMClient so they run in the regular pytest
suite with no network access.  They verify:

- ``_run_turn`` returns the final narration string.
- ``RecordingDisplay`` records narration / status / errors / game-over
  without producing terminal output.
- ``HeadlessSession.submit()`` returns a ``TurnTranscript`` with the
  expected fields, and ``is_over`` reflects game-over state.
- Autosave lands inside the supplied ``config_dir`` sandbox.
"""

from __future__ import annotations

import json

import pytest

from mgmai.game.headless import (
    HeadlessSession,
    RecordingDisplay,
    TurnTranscript,
)
from mgmai.game.loop import GameLoop


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
        self.generic_calls: list[tuple[str, str]] = []

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

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.generic_calls.append((system_prompt, user_prompt))
        # Default behaviour identical to call_prose for testing convenience.
        return self.call_prose(system_prompt, user_prompt)


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


# ------------------------------------------------------------------
# _run_turn return value
# ------------------------------------------------------------------

class TestRunTurnReturnsNarration:
    def test_simple_turn_returns_narration(self, state_manager, tmp_path) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Time passes quietly."),
        )
        loop = GameLoop(state_manager, llm, display=RecordingDisplay(),
                        config_dir=tmp_path)
        result = loop._run_turn("I wait")
        assert result == "Time passes quietly."

    def test_fallback_returns_none(self, state_manager, tmp_path) -> None:
        """When LLM Call 1 fails to parse twice, _run_turn returns None;
        the fallback narration was still rendered to the display."""
        from mgmai.game.loop import FALLBACK_NARRATION

        rd = RecordingDisplay()
        llm = FakeLLMClient(
            ruling_response="not valid json",
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        result = loop._run_turn("garbage")
        assert result is None
        assert FALLBACK_NARRATION in rd.narrations

    def test_chain_returns_final_narration(self, state_manager, tmp_path) -> None:
        """A chained action returns the *final* narration, not the
        intermediate one."""
        responses = [
            json.dumps({
                "action_type": "wait",
                "detail": "wait",
                "follow_up": "look around",
                "soft_state_patches": [],
            }),
            _wait_action_json("look around"),
        ]
        prose_responses = [
            _prose_json("First link narration."),
            _prose_json("Final link narration."),
        ]
        llm = FakeLLMClient()
        llm._ruling_iter = iter(responses)
        llm._prose_iter = iter(prose_responses)
        llm.call_ruling = lambda sp, up: next(llm._ruling_iter)
        llm.call_prose = lambda sp, up: next(llm._prose_iter)

        rd = RecordingDisplay()
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        result = loop._run_turn("wait then look around")
        assert result == "Final link narration."


# ------------------------------------------------------------------
# RecordingDisplay
# ------------------------------------------------------------------

class TestRecordingDisplay:
    def test_records_narration_without_terminal_output(
        self, state_manager, tmp_path, capsys
    ) -> None:
        """render_narration records text and produces no stdout/stderr."""
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("A quiet moment."),
        )
        rd = RecordingDisplay()
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        loop._run_turn("wait")

        assert rd.narrations == ["A quiet moment."]
        captured = capsys.readouterr()
        # No terminal output produced (rich writes to the in-memory sink).
        assert "A quiet moment" not in captured.out
        assert "A quiet moment" not in captured.err

    def test_records_status_snapshots(self, state_manager, tmp_path) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Time passes."),
        )
        rd = RecordingDisplay()
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        loop._run_turn("wait")

        assert len(rd.status_snapshots) == 1
        snap = rd.status_snapshots[0]
        assert snap["turn_count"] == 1
        assert "location" in snap
        assert "in_combat" in snap

    def test_records_errors(self, state_manager, tmp_path) -> None:
        rd = RecordingDisplay()
        rd.render_error("Something broke.")
        assert rd.errors == ["Something broke."]

    def test_records_game_over(self, state_manager, tmp_path) -> None:
        """A game-over turn is captured by the display and the loop
        marks itself as not running."""
        # Trigger the bag-of-holding win mechanic.
        state_manager.hard_state.flags["padlock_unlocked"] = True
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("You win!"),
        )
        rd = RecordingDisplay()
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        loop._run_turn("do something")

        assert len(rd.game_over_events) == 1
        assert rd.game_over_events[0]["type"] == "win"
        assert loop._running is False


# ------------------------------------------------------------------
# HeadlessSession
# ------------------------------------------------------------------

class TestHeadlessSession:
    def test_requires_state_or_adventure(self, tmp_path) -> None:
        llm = FakeLLMClient()
        with pytest.raises(ValueError, match="state_manager or adventure_dir"):
            HeadlessSession(llm_client=llm, config_dir=tmp_path)

    def test_submit_returns_transcript(self, state_manager, tmp_path) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Quiet falls over the room."),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        transcript = session.submit("I wait")

        assert isinstance(transcript, TurnTranscript)
        assert transcript.command == "I wait"
        assert transcript.narration == "Quiet falls over the room."
        assert transcript.game_over is False
        assert transcript.exception is None
        assert transcript.status.turn_count == 1
        assert transcript.status.in_combat is False

    def test_is_over_after_game_over(self, state_manager, tmp_path) -> None:
        state_manager.hard_state.flags["padlock_unlocked"] = True
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("You win!"),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        assert session.is_over is False
        transcript = session.submit("do something")
        assert transcript.game_over is True
        assert transcript.game_over_type == "win"
        assert session.is_over is True

    def test_autosave_lands_in_config_dir(self, state_manager, tmp_path) -> None:
        """Autosave must be written under the supplied config_dir, not the CWD."""
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Time passes."),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        session.submit("wait")

        # Look for any autosave.json under tmp_path.
        autosaves = list(tmp_path.rglob("autosave.json"))
        assert len(autosaves) == 1, (
            f"expected exactly one autosave under {tmp_path}, found {autosaves}"
        )
        # The autosave path the loop *would* use must resolve inside the
        # sandbox, proving it never falls back to ./autosave.json.
        loop = session.loop
        resolved = loop._get_autosave_path()
        assert tmp_path in resolved.parents

    def test_submit_captures_exception_and_reraises(
        self, state_manager, tmp_path
    ) -> None:
        """If the loop raises, the transcript captures the exception
        and submit() re-raises it."""

        class ExplodingLLM(FakeLLMClient):
            def call_ruling(self, system_prompt, user_prompt):
                raise RuntimeError("boom")

        llm = ExplodingLLM(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        with pytest.raises(RuntimeError, match="boom"):
            session.submit("wait")

    def test_status_snapshot_without_turn(self, state_manager, tmp_path) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json(),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        snap = session.status_snapshot()
        assert snap.turn_count == 0
        assert snap.location == state_manager.hard_state.player.location
        assert snap.in_combat is False

    def test_snapshot_combatants_include_conditions_and_fled(
        self, state_manager
    ) -> None:
        from mgmai.game.headless import _snapshot_status
        from mgmai.models.combat import CombatState

        state_manager.hard_state.combat = CombatState(
            round_number=1,
            initiative_order=["player", "spider"],
            combatants=["player", "spider"],
            active=True,
        )
        state_manager.hard_state.player.status_effects = {"poisoned": 2}
        state_manager.hard_state.entity_states["spider"] = {
            "current_hp": 5,
            "status_effects": {"stunned": 1},
            "fled": True,
        }
        snap = _snapshot_status(state_manager)
        assert snap.combatants["player"]["status_effects"] == {"poisoned": 2}
        assert snap.combatants["player"]["fled"] is False
        assert snap.combatants["spider"]["status_effects"] == {"stunned": 1}
        assert snap.combatants["spider"]["fled"] is True
        # Display names come from StatusEffectDef.name (raw IDs are the keys).
        assert snap.combatants["player"]["status_effect_names"] == {
            "poisoned": "Poisoned"
        }
        assert snap.combatants["spider"]["status_effect_names"] == {
            "stunned": "Stunned"
        }

    def test_adventure_dir_loading(self, tmp_path) -> None:
        """HeadlessSession can load an adventure directory directly."""
        from tests.helpers import TEST_DIR

        mini = TEST_DIR / "fixtures" / "mini_adventure"
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("The torch flickers."),
        )
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        session = HeadlessSession(
            llm_client=llm,
            adventure_dir=mini,
            config_dir=sandbox,
        )
        transcript = session.submit("wait")
        assert transcript.narration == "The torch flickers."
        assert session.hard_state is not None
        assert session.hard_state.player.location == "start_room"


# ----------------------------------------------------------------------
# Integration fixture smoke tests
# ----------------------------------------------------------------------


class TestIntegrationFixtureSmoke:
    """Quick schema validation of integration-test fixtures.

    These run without any LLM calls and catch fixture drift before the
    paid integration suite runs.
    """

    def test_combat_arena_loads(self):
        """StateManager successfully loads the combat_arena fixture."""
        from pathlib import Path
        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "combat_arena"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # Player starts in the arena with expected equipment.
        assert sm.hard_state.player.location == "arena"
        assert sm.hard_state.player.current_hp == 24
        assert sm.hard_state.player.max_hp == 24
        assert sm.hard_state.player.inventory.get("health_potion") == 2
        assert "flame_strike" in sm.hard_state.player.abilities

        # Four enemies and one ally are defined.
        assert "goblin_grunt" in sm.corpus.entities
        assert "goblin_runner" in sm.corpus.entities
        assert "goblin_shaman" in sm.corpus.entities
        assert "bugbear" in sm.corpus.entities
        assert "gargan" in sm.corpus.entities

        # Gargan is a follower with HP 22 and alive.
        gargan_state = sm.hard_state.entity_states.get("gargan", {})
        assert gargan_state.get("alive") is True
        assert gargan_state.get("following") is True
        assert gargan_state.get("current_hp") == 22

        # Bugbear has piercing resistance, fire vulnerability.
        bugbear = sm.corpus.entities["bugbear"]
        assert bugbear.combat.resistances == ["piercing"]
        assert bugbear.combat.vulnerabilities == ["fire"]

        # Shaman has the heal ability and cooldown AI.
        shaman = sm.corpus.entities["goblin_shaman"]
        assert "mend_wounds" in shaman.combat.abilities
        mend = sm.corpus.abilities["mend_wounds"]
        assert mend.heal == "2d4+2"

        # Arena has an exit north to corridor.
        arena = sm.corpus.rooms["arena"]
        exits = {ex.id: ex.target_room for ex in arena.exits}
        assert exits.get("exit_north") == "corridor"

    def test_venom_pit_loads(self):
        """StateManager successfully loads the venom_pit fixture."""
        from pathlib import Path
        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "venom_pit"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # Player starts in the pit with expected gear and abilities.
        assert sm.hard_state.player.location == "pit"
        assert sm.hard_state.player.current_hp == 28
        assert sm.hard_state.player.max_hp == 28
        assert sm.hard_state.player.inventory.get("antidote") == 2
        assert sm.hard_state.player.inventory.get("war_hammer") == 1
        assert sm.hard_state.player.equipped == ["longsword"]
        assert "power_strike" in sm.hard_state.player.abilities
        assert "healing_hands" in sm.hard_state.player.abilities

        # Viper has a poison on-hit effect.
        viper = sm.corpus.entities["pit_viper"]
        assert len(viper.combat.on_hit_effects) == 1
        effect = viper.combat.on_hit_effects[0]
        assert effect.check.stat == "CON"
        assert effect.tag == "poison"
        assert effect.failure.apply_status_effect.id == "poisoned"

        # Crawler has a multiattack sequence with a stun on-hit effect.
        crawler = sm.corpus.entities["carrion_crawler"]
        assert crawler.combat.multiattack == ["tentacles", "bite"]
        tentacles = next(a for a in crawler.combat.attacks if a.id == "tentacles")
        assert tentacles.on_hit_effects[0].failure.apply_status_effect.id == "stunned"

        # Jelly is immune to slashing.
        jelly = sm.corpus.entities["ochre_jelly"]
        assert jelly.combat.immunities == ["slashing"]

        # Willa is a living follower.
        willa_state = sm.hard_state.entity_states.get("willa", {})
        assert willa_state.get("alive") is True
        assert willa_state.get("following") is True

        # Antidote cures poisoned.
        antidote = sm.corpus.entities["antidote"]
        assert antidote.consumable.cure_status_effects == ["poisoned"]

    def test_ambush_alley_loads(self):
        """StateManager successfully loads the ambush_alley fixture."""
        from pathlib import Path
        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "ambush_alley"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # Player starts in the market alley.
        assert sm.hard_state.player.location == "market_alley"
        assert sm.hard_state.player.current_hp == 28

        # Cutpurse declares the confront interaction, the whistle
        # reaction, and an aggro encounter that starts combat.
        cutpurse = sm.corpus.entities["cutpurse"]
        assert any(i.id == "confront" for i in cutpurse.interactions)
        assert any(r.id == "cutpurse_whistle" for r in cutpurse.reactions)
        assert cutpurse.aggro is not None
        assert cutpurse.aggro[0].result.start_combat == [
            "hired_thug", "frenzied_howler",
        ]
        assert cutpurse.aggro[0].result.set_flag == {"ambush_triggered": True}

        # Thug always targets the player; howler has a HP-gated ability.
        thug = sm.corpus.entities["hired_thug"]
        assert thug.combat.ai.targeting == "player"
        howler = sm.corpus.entities["frenzied_howler"]
        assert "frenzy" in howler.combat.abilities
        rule = howler.combat.ai.ability_rules["frenzy"]
        assert rule.use_below_own_hp_pct == 50

        # Pack mule is a passive follower.
        mule = sm.corpus.entities["pack_mule"]
        assert mule.combat.ai.passive is True
        mule_state = sm.hard_state.entity_states.get("pack_mule", {})
        assert mule_state.get("following") is True
