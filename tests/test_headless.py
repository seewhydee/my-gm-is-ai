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

    def test_fallback_returns_narration(self, state_manager, tmp_path) -> None:
        """When LLM Call 1 fails to parse twice, _run_turn returns the
        fallback narration — the same text a REPL player sees."""
        from mgmai.game.loop import FALLBACK_NARRATION

        rd = RecordingDisplay()
        llm = FakeLLMClient(
            ruling_response="not valid json",
            prose_response=_prose_json(),
        )
        loop = GameLoop(state_manager, llm, display=rd, config_dir=tmp_path)
        result = loop._run_turn("garbage")
        assert result == FALLBACK_NARRATION
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
        # The autosave path the session *would* use must resolve inside
        # the sandbox, proving it never falls back to ./autosave.json.
        resolved = session.session.get_autosave_path()
        assert resolved is not None
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

    def _chained_combat_session(self, state_manager, tmp_path, end_combat=False):
        """Session in combat whose two-segment chained turn resolves one
        engine ``wait`` per segment (each resolution overwrites
        ``_last_result``; with ``end_combat`` the second segment also
        ends combat mid-turn)."""
        from mgmai.models.combat import CombatState

        hard = state_manager.hard_state
        hard.combat = CombatState(
            active=True, combatants=["player"], initiative_order=["player"],
        )

        rulings = [
            json.dumps({
                "action_type": "wait",
                "detail": "first segment",
                "follow_up": "second segment",
                "soft_state_patches": [],
            }),
            _wait_action_json("second segment"),
        ]
        proses = [_prose_json("First."), _prose_json("Second.")]
        llm = FakeLLMClient()
        llm._ruling_iter = iter(rulings)
        llm._prose_iter = iter(proses)
        seg = {"n": 0}

        def _ruling(sp, up):
            return next(llm._ruling_iter)

        def _prose(sp, up):
            out = next(llm._prose_iter)
            seg["n"] += 1
            if end_combat and seg["n"] == 2:
                # Combat ends during the second segment's resolution
                # (e.g. the player's death) — afterwards hard.combat
                # is gone, but its log entries still belong to the turn.
                hard.combat = None
            return out

        llm.call_ruling = _ruling
        llm.call_prose = _prose
        return HeadlessSession(
            llm_client=llm, state_manager=state_manager, config_dir=tmp_path,
        )

    def test_submit_captures_combat_log_across_chain_segments(
        self, state_manager, tmp_path
    ) -> None:
        """A chained turn's combat_log covers ALL engine resolutions,
        not just the last segment's ``_last_result``."""
        session = self._chained_combat_session(state_manager, tmp_path)
        transcript = session.submit("wait, then wait again")
        # One engine "wait" entry per segment (the old _last_result-only
        # capture would see just the second).
        waits = [e for e in transcript.combat_log if e["action"] == "wait"]
        assert len(waits) == 2

    def test_submit_captures_combat_log_when_combat_ends_mid_turn(
        self, state_manager, tmp_path
    ) -> None:
        """Entries stay capturable when combat ends during the turn
        (``hard.combat`` is None afterwards)."""
        session = self._chained_combat_session(
            state_manager, tmp_path, end_combat=True
        )
        transcript = session.submit("wait, then wait again")
        waits = [e for e in transcript.combat_log if e["action"] == "wait"]
        assert len(waits) == 2

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

    def test_fallback_turn_does_not_record_stale_result(
        self, state_manager, tmp_path
    ) -> None:
        """A turn where LLM Call 1 double-fails must not inherit the
        previous turn's success/ruled_action (the fallback path clears
        ``_last_result``/``_last_action``)."""
        from mgmai.game.loop import FALLBACK_NARRATION

        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("A quiet moment."),
        )
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        ok = session.submit("wait")
        assert ok.success is not None

        llm._ruling = "not valid json"
        bad = session.submit("garbage")
        assert bad.narration == FALLBACK_NARRATION
        assert bad.success is None
        assert bad.ruled_action is None

    def test_ruling_retries_recorded_in_transcript(
        self, state_manager, tmp_path
    ) -> None:
        """A corrective ruling retry (first output invalid) is exposed
        on the turn's transcript."""
        rulings = ["not valid json", _wait_action_json()]
        llm = FakeLLMClient(prose_response=_prose_json("Time passes."))
        llm._ruling_iter = iter(rulings)
        llm.call_ruling = lambda sp, up: next(llm._ruling_iter)
        session = HeadlessSession(
            llm_client=llm,
            state_manager=state_manager,
            config_dir=tmp_path,
        )
        transcript = session.submit("wait")
        assert len(transcript.ruling_retries) == 1
        assert "invalid" in transcript.ruling_retries[0].lower()

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
        assert sm.hard_state.player.inventory.get("potion_of_healing") == 2
        assert "flame_strike" in sm.hard_state.player.abilities

        # The player's longsword and potions come from the SRD data pack
        # (not declared in the fixture corpus).
        assert sm.corpus.entities["longsword"].equip_block.damage_expr == "1d8"
        assert sm.corpus.entities["potion_of_healing"].interactions[0].result.player_heal == "2d4+2"

        # Four enemies and one ally are defined.
        assert "goblin_grunt" in sm.corpus.entities
        assert "goblin_runner" in sm.corpus.entities
        assert "goblin_shaman" in sm.corpus.entities
        assert "bugbear" in sm.corpus.entities
        assert "korbar" in sm.corpus.entities

        # Korbar is a follower with HP 22 and alive.
        korbar_state = sm.hard_state.entity_states.get("korbar", {})
        assert korbar_state.get("alive") is True
        assert korbar_state.get("following") is True
        assert korbar_state.get("current_hp") == 22

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
        assert sm.hard_state.player.inventory.get("warhammer") == 1
        assert sm.hard_state.player.equipped == ["longsword"]
        assert "power_strike" in sm.hard_state.player.abilities
        assert "healing_hands" in sm.hard_state.player.abilities

        # The player's weapons and healing potions come from the SRD
        # data pack (not declared in the fixture corpus).
        assert sm.corpus.entities["longsword"].equip_block.damage_expr == "1d8"
        assert sm.corpus.entities["warhammer"].equip_block.damage_type == "bludgeoning"
        assert sm.hard_state.player.inventory.get("potion_of_healing") == 2

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
        drink = next(i for i in antidote.interactions if i.id == "drink")
        assert drink.result.cure_status_effects == ["poisoned"]

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

    def test_indicator_hall_loads(self):
        """StateManager successfully loads the indicator_hall fixture."""
        from pathlib import Path

        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "indicator_hall"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # Player starts in the hall with the cudgel equipped.
        assert sm.hard_state.player.location == "hall"
        assert sm.hard_state.player.equipped == ["cudgel"]

        # The pillar's shove check always succeeds (target 3 vs STR 16),
        # so the single-check scenario deterministically produces
        # exactly one check indicator.
        pillar = sm.corpus.entities["cracked_pillar"]
        shove = next(i for i in pillar.interactions if i.id == "shove")
        assert shove.check.stat == "STR"
        assert shove.check.target == 3

        # The bridge's cross check always fails (target 30 vs DEX 10)
        # and chains into an always-failing CON check with damage, so
        # the multi-indicator scenario deterministically produces two
        # check indicators plus an hp indicator.
        bridge = sm.corpus.entities["rickety_bridge"]
        cross = next(i for i in bridge.interactions if i.id == "cross")
        assert cross.check.stat == "DEX"
        assert cross.check.target == 30
        then = cross.failure.then_check
        assert then.check.stat == "CON"
        assert then.check.target == 30
        assert then.failure.player_damage == "1d4"

        # The golem is a durable sparring partner; the dummy dies to
        # any hit (1 HP).
        assert sm.corpus.entities["sparring_golem"].combat.hp == 40
        dummy = sm.corpus.entities["battered_dummy"]
        assert dummy.combat.hp == 1
        dummy_state = sm.hard_state.entity_states.get("battered_dummy", {})
        assert dummy_state.get("alive") is True
        assert dummy_state.get("current_hp") == 1

    def test_spell_arena_loads(self):
        """StateManager successfully loads the spell_arena fixture."""
        from pathlib import Path

        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "spell_arena"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # The player is a 1st-level wizard with two 1st-level slots.
        player = sm.hard_state.player
        assert player.location == "arena"
        assert player.spellcasting_ability == "INT"
        assert player.spell_slots == {1: 2}
        assert player.abilities == ["fire_bolt", "mage_armor", "magic_missile"]

        # The spells come from the SRD spell pack (not declared in the
        # fixture corpus), minted into corpus.abilities at load time.
        assert sm.corpus.abilities["fire_bolt"].spell_level == 0
        magic_missile = sm.corpus.abilities["magic_missile"]
        assert magic_missile.spell_level == 1
        assert magic_missile.auto_damage.damage == "3d4+3"
        mage_armor = sm.corpus.abilities["mage_armor"]
        assert mage_armor.on_cast is not None
        assert mage_armor.on_cast.id == "mage_armor"

        # Two enemies are defined.
        assert sm.corpus.entities["goblin_grunt"].combat.hp == 11
        assert sm.corpus.entities["hobgoblin"].combat.hp == 18

    def test_drowned_lantern_loads(self):
        """StateManager successfully loads the drowned_lantern fixture."""
        from pathlib import Path

        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "drowned_lantern"
        sm = StateManager(adventure_dir=str(fixture))

        assert sm.hard_state is not None
        assert sm.corpus is not None
        assert sm.soft_state is not None

        # Player starts in the common room with the longsword equipped.
        player = sm.hard_state.player
        assert player.location == "common_room"
        assert player.current_hp == 24
        assert player.ac == 13
        assert player.equipped == ["longsword"]
        # The longsword comes from the SRD data pack (not declared in
        # the fixture corpus).
        assert sm.corpus.entities["longsword"].equip_block.damage_expr == "1d8"

        # The six rooms exist, with common_room as the start room.
        assert set(sm.corpus.rooms) == {
            "common_room", "dock", "mid_marsh", "far_shore", "muddy_track",
            "in_the_water",
        }
        assert sm.corpus.rooms["common_room"].is_start_room is True

        # The three conversational NPCs have dialogue blocks and
        # attitude declarations; Fen's attitude is frozen at 0/0.
        for npc_id in ("berrin", "marta", "fen"):
            npc = sm.corpus.entities[npc_id]
            assert npc.dialogue is not None
            assert "attitude" in npc.state_fields
        assert sm.corpus.entities["fen"].dialogue.attitude_limits.max == 0
        # Berrin has the four persuasion paths.
        assert set(sm.corpus.entities["berrin"].dialogue.dialogue_paths) == {
            "ask_crossing_cold", "bluff_janis", "confront_janis",
            "convince_crossing",
        }

        # Old Wellington starts dead; the crate starts hidden in the bar.
        assert sm.hard_state.entity_states["old_wellington"]["alive"] is False
        assert sm.hard_state.entity_states["sealed_crate"]["hidden"] is True
        assert "sealed_crate" in sm.hard_state.entity_contains["bar"]
        assert "rope_end" in sm.hard_state.entity_contains["ferry"]

        # Knowledge flags are seeded false; sequence counters start at 0.
        assert sm.hard_state.flags.get("heard_janis_name") is False
        assert sm.hard_state.room_states["mid_marsh"]["crossing_stage"] == 0
        assert sm.hard_state.room_states["far_shore"]["approach_stage"] == 0


# ------------------------------------------------------------------
# TurnTranscript engine-outcome fields (success / engine_error /
# ruled_action) and dialogue_path degradation
# ------------------------------------------------------------------


def _talk_action_json(target: str, dialogue_path: str | None = None) -> str:
    return json.dumps({
        "action_type": "talk",
        "target": target,
        "utterance": "Tell me what you know.",
        "dialogue_path": dialogue_path,
        "detail": f"Player asks {target} for information",
        "follow_up": None,
        "soft_state_patches": [],
    })


def _drowned_lantern_session(llm, tmp_path) -> HeadlessSession:
    from pathlib import Path

    fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "drowned_lantern"
    return HeadlessSession(
        llm_client=llm, adventure_dir=str(fixture), config_dir=tmp_path,
    )


class TestTranscriptEngineOutcome:
    """A turn can fail silently (narration still flows); the transcript
    must expose the engine outcome so artifacts reveal it."""

    def test_successful_turn_records_outcome(self, state_manager, tmp_path) -> None:
        llm = FakeLLMClient(
            ruling_response=_wait_action_json(),
            prose_response=_prose_json("Time passes."),
        )
        session = HeadlessSession(
            llm_client=llm, state_manager=state_manager, config_dir=tmp_path,
        )
        transcript = session.submit("I wait.")
        assert transcript.success is True
        assert transcript.engine_error is None
        assert transcript.ruled_action["action_type"] == "wait"
        # Serialized form carries the new fields too.
        d = transcript.to_dict()
        assert d["success"] is True and d["ruled_action"] is not None

    def test_failed_turn_records_engine_error(self, tmp_path) -> None:
        """Talking to a dead NPC fails resolution; the transcript must
        surface it (the narration itself gives no hint)."""
        llm = FakeLLMClient(
            ruling_response=_talk_action_json("old_wellington"),
            prose_response=_prose_json("The heron stares glassily back."),
        )
        session = _drowned_lantern_session(llm, tmp_path)
        transcript = session.submit("I talk to the stuffed heron.")
        assert transcript.success is False
        assert "old_wellington" in (transcript.engine_error or "")
        assert transcript.ruled_action["target"] == "old_wellington"


class TestDialoguePathDegradation:
    """A hallucinated dialogue_path earns a corrective retry; if the
    retry insists, the path is stripped and the conversation proceeds
    freeform instead of the turn hard-failing."""

    def test_bogus_path_stripped_after_retry(self, tmp_path) -> None:
        bad_talk = _talk_action_json("marta", dialogue_path="tell_secrets")
        llm = FakeLLMClient(
            ruling_response=bad_talk,  # same bogus path on every attempt
            prose_response=_prose_json("Marta shrugs noncommittally."),
        )
        session = _drowned_lantern_session(llm, tmp_path)
        transcript = session.submit("Marta, tell me your secrets.")

        # The corrective retry fired, feeding the validation error back.
        assert len(llm.ruling_calls) == 2
        assert "tell_secrets" in llm.ruling_calls[1][1]

        # The turn degraded gracefully instead of failing.
        assert transcript.success is True
        assert transcript.engine_error is None
        assert transcript.ruled_action["dialogue_path"] is None
        assert session.soft_state.dialogue_state.active_npc == "marta"
        warnings = transcript.warnings
        assert any("dialogue_path" in w for w in warnings)

    def test_valid_path_no_retry(self, tmp_path) -> None:
        good_talk = _talk_action_json("marta", dialogue_path="sympathetic_ear")
        llm = FakeLLMClient(
            ruling_response=good_talk,
            prose_response=_prose_json("Marta thaws a little."),
        )
        session = _drowned_lantern_session(llm, tmp_path)
        transcript = session.submit("I lend Marta a sympathetic ear.")

        assert len(llm.ruling_calls) == 1
        assert transcript.success is True
        assert transcript.ruled_action["dialogue_path"] == "sympathetic_ear"


# ------------------------------------------------------------------
# Briefing dialogue-path condition filtering
# ------------------------------------------------------------------


class TestDialoguePathFiltering:
    """The briefing exposes only currently-available dialogue paths
    (condition-gated ones filtered), so the ruling GM cannot select a
    path whose conditions are unmet."""

    def _berrin_paths(self, sm):
        from mgmai.engine.utils import build_briefing_entity

        ent = build_briefing_entity(
            "berrin", 1, sm.hard_state, sm.soft_state, sm.corpus,
        )
        return set(ent.dialogue_paths)

    def test_paths_filtered_by_flag_conditions(self, tmp_path) -> None:
        from pathlib import Path

        from mgmai.state.manager import StateManager

        fixture = Path(__file__).resolve().parent / "integration" / "fixtures" / "drowned_lantern"
        sm = StateManager(adventure_dir=str(fixture))

        # Pre-leverage: only the cold-ask path is available.
        assert self._berrin_paths(sm) == {"ask_crossing_cold"}

        # With the name heard, the bluff route opens up.
        sm.hard_state.flags["heard_janis_name"] = True
        assert self._berrin_paths(sm) == {"ask_crossing_cold", "bluff_janis"}

        # With the accomplice link known, the confront route opens too.
        sm.hard_state.flags["knows_janis_link"] = True
        assert self._berrin_paths(sm) == {
            "ask_crossing_cold", "bluff_janis", "confront_janis",
        }

        # After the confession, cold-ask and bluff close and
        # convince_crossing opens (confront stays available — it has no
        # post-confession guard by design, only bluff does).
        sm.hard_state.flags["berrin_confessed"] = True
        assert self._berrin_paths(sm) == {"confront_janis", "convince_crossing"}
