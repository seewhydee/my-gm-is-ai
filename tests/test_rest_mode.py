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

"""Tests for rest mode: the engine helpers, the RestMode controller, and
the headless drive-through of a full rest end-to-end."""

from __future__ import annotations

import json

from mgmai.engine.engine import resolve
from mgmai.engine.rest_helpers import set_prepared_spells, spend_hit_die
from mgmai.game.headless import HeadlessSession
from mgmai.game.rest_mode import RestMode
from mgmai.models.actions import RestAction
from tests.helpers import build_state_manager, make_char_sheet_corpus
from tests.test_rests import _corpus, _hard, _player

_SPELLBOOK = ["fire_bolt", "mage_armor", "magic_missile"]


def _rest_mode(kind: str = "long", **player_kw) -> RestMode:
    from mgmai.models.hard_state import HitDice

    corpus = _corpus()
    defaults: dict = {
        "spellbook": list(_SPELLBOOK),
        "abilities": list(_SPELLBOOK),
        # Leave room to spend hit dice / heal.
        "current_hp": 3,
        "hit_dice": HitDice(die="d8", current=2, max=5),
    }
    defaults.update(player_kw)
    player = _player(**defaults)
    hard = _hard(player=player)
    sm = build_state_manager(corpus, hard)
    result = resolve(
        RestAction(action_type="rest", kind=kind, detail="camp"), sm,
    )
    # Reset HP/hit-dice so the rest mode has something to do (the long
    # rest above recharged them); we want to test the *menu* mutations.
    hard.player.current_hp = 4
    hard.player.hit_dice.current = 2
    return RestMode(kind, result, hard, corpus)


# ------------------------------------------------------------------
# Engine helpers
# ------------------------------------------------------------------


class TestSpendHitDie:
    def test_heals_and_decrements(self):
        corpus = _corpus()
        from mgmai.models.hard_state import HitDice

        hard = _hard(player=_player(
            current_hp=3, max_hp=20,
            hit_dice=HitDice(die="d8", current=3, max=5),
            spellbook=list(_SPELLBOOK), abilities=list(_SPELLBOOK),
        ))
        ok, msg, healed = spend_hit_die(hard, corpus)
        assert ok
        assert healed >= 1
        assert hard.player.current_hp == 3 + healed
        assert hard.player.hit_dice.current == 2
        assert "regain" in msg

    def test_no_hit_dice(self):
        corpus = _corpus()
        from mgmai.models.hard_state import HitDice

        hard = _hard(player=_player(
            hit_dice=HitDice(die="d8", current=0, max=5),
        ))
        ok, msg, healed = spend_hit_die(hard, corpus)
        assert not ok
        assert healed == 0
        assert "no Hit Dice" in msg
        assert hard.player.hit_dice.current == 0

    def test_at_full_hp(self):
        corpus = _corpus()
        from mgmai.models.hard_state import HitDice

        hard = _hard(player=_player(
            current_hp=11, max_hp=11,
            hit_dice=HitDice(die="d8", current=2, max=5),
        ))
        ok, msg, healed = spend_hit_die(hard, corpus)
        assert not ok
        assert healed == 0
        assert "full HP" in msg
        # Die not spent on failure.
        assert hard.player.hit_dice.current == 2

    def test_heal_clamps_to_max(self):
        corpus = _corpus()
        from mgmai.models.hard_state import HitDice

        hard = _hard(player=_player(
            current_hp=10, max_hp=11,
            hit_dice=HitDice(die="d8", current=1, max=5),
        ))
        ok, _msg, healed = spend_hit_die(hard, corpus)
        assert ok
        # Heal cannot exceed max-current (1), regardless of the roll.
        assert healed <= 1
        assert hard.player.current_hp == 11


class TestSetPreparedSpells:
    def test_success(self):
        corpus = _corpus()
        hard = _hard(player=_player(
            spellbook=list(_SPELLBOOK), abilities=list(_SPELLBOOK),
        ))
        ok, _msg = set_prepared_spells(hard, corpus, ["fire_bolt", "mage_armor"])
        assert ok
        assert hard.player.abilities == ["fire_bolt", "mage_armor"]

    def test_unknown_ability_rejected(self):
        corpus = _corpus()
        hard = _hard(player=_player(
            spellbook=list(_SPELLBOOK), abilities=list(_SPELLBOOK),
        ))
        ok, msg = set_prepared_spells(hard, corpus, ["fire_bolt", "wish"])
        assert not ok
        assert "wish" in msg
        assert hard.player.abilities == list(_SPELLBOOK)

    def test_not_in_spellbook_rejected(self):
        corpus = _corpus()
        # sacred_flame is a real spell (in the pack) but not in this
        # player's spellbook.
        hard = _hard(player=_player(
            spellbook=list(_SPELLBOOK), abilities=list(_SPELLBOOK),
        ))
        ok, msg = set_prepared_spells(hard, corpus, ["fire_bolt", "sacred_flame"])
        assert not ok
        assert "sacred_flame" in msg
        assert "spellbook" in msg
        assert hard.player.abilities == list(_SPELLBOOK)

    def test_empty_spellbook_allows_any_known(self):
        # Spontaneous casters / non-casters: no spellbook, so any
        # corpus ability is accepted (abilities is the whole list).
        corpus = _corpus()
        hard = _hard(player=_player(spellbook=[], abilities=["fire_bolt"]))
        ok, _msg = set_prepared_spells(hard, corpus, ["fire_bolt", "mage_armor"])
        assert ok
        assert hard.player.abilities == ["fire_bolt", "mage_armor"]


# ------------------------------------------------------------------
# RestMode controller
# ------------------------------------------------------------------


class TestRestModeTopMenu:
    def test_initial_text_shows_summary_and_menu(self):
        rm = _rest_mode()
        text = rm.initial_text()
        assert "── Long rest ──" in text
        assert "[1] Prepare spells" in text
        assert "[2] Spend hit dice" in text
        assert "[3] Done" in text

    def test_done_exits(self):
        rm = _rest_mode()
        text = rm.handle("3")
        assert rm.exited
        assert "finish" in text

    def test_invalid_choice_reprompts(self):
        rm = _rest_mode()
        text = rm.handle("9")
        assert not rm.exited
        assert "Invalid" in text
        assert "[3] Done" in text

    def test_slot_ordinals(self):
        rm = _rest_mode()
        rm._hard.player.spell_slots = {1: 4, 2: 2, 3: 1}
        text = rm.initial_text()
        assert "1st ×4" in text
        assert "2nd ×2" in text
        assert "3rd ×1" in text


class TestRestModePrepare:
    def test_toggle_then_confirm(self):
        rm = _rest_mode()
        rm.handle("1")            # enter prepare
        text = rm.handle("1")     # toggle fire_bolt off
        assert "[ ] 1  fire_bolt" in text or "[ ] 1  Fire Bolt" in text
        # Confirm: abilities should now exclude fire_bolt.
        rm.handle("0")
        assert rm._hard.player.abilities == ["mage_armor", "magic_missile"]

    def test_prepare_hidden_without_spellbook(self):
        rm = _rest_mode(spellbook=[], abilities=["fire_bolt"])
        text = rm.initial_text()
        assert "Prepare spells" not in text
        assert "[1] Spend hit dice" in text
        assert "[2] Done" in text
        # Done is the last option and exits.
        out = rm.handle("2")
        assert rm.exited
        assert "finish" in out


class TestRestModeSpend:
    def test_spend_then_done(self):
        rm = _rest_mode()
        hp_before = rm._hard.player.current_hp
        hd_before = rm._hard.player.hit_dice.current
        text = rm.handle("2")     # spend one die
        assert "regain" in text
        assert rm._hard.player.current_hp > hp_before
        assert rm._hard.player.hit_dice.current == hd_before - 1
        # Back to top via [2] (done with spending).
        text = rm.handle("2")
        assert "[3] Done" in text

    def test_spend_another(self):
        rm = _rest_mode()
        rm.handle("2")            # spend first
        hd_after_first = rm._hard.player.hit_dice.current
        text = rm.handle("1")     # spend another
        assert "regain" in text
        assert rm._hard.player.hit_dice.current == hd_after_first - 1

    def test_spend_failure_in_submenu_returns_to_top(self):
        rm = _rest_mode()
        # Force the failure to be "no dice" (a single d8 cannot fill HP).
        rm._hard.player.current_hp = 1
        rm._hard.player.hit_dice.current = 1
        rm.handle("2")                       # spend the only die -> submenu
        assert rm._hard.player.hit_dice.current == 0
        text = rm.handle("1")                # fails: no dice left
        assert "no Hit Dice" in text
        # The top menu is displayed AND the controller is back in the
        # top state (regression: displayed menu and state used to desync,
        # making Done unreachable from that screen).
        assert "[3] Done" in text
        rm.handle("3")
        assert rm.exited


# ------------------------------------------------------------------
# Structured menu snapshot (button-based front-ends)
# ------------------------------------------------------------------


class TestRestMenuSnapshot:
    def test_top_menu_snapshot(self):
        rm = _rest_mode()
        snap = rm.menu()
        assert snap.kind == "long"
        assert snap.state == "top"
        assert snap.options == ["Prepare spells", "Spend hit dice", "Done"]
        assert snap.summary  # rest result summary
        assert "HP" in snap.status_line
        assert snap.feedback == ""

    def test_short_rest_kind(self):
        rm = _rest_mode(kind="short")
        assert rm.menu().kind == "short"

    def test_prepare_snapshot_tracks_selection(self):
        rm = _rest_mode()
        rm.handle("1")  # enter prepare
        snap = rm.menu()
        assert snap.state == "prepare"
        # Options are the spellbook entries, in numbering order.
        assert len(snap.options) == 3
        assert snap.prepared == list(_SPELLBOOK)

        # Toggle fire_bolt off; the snapshot reflects the new selection.
        rm.handle("1")
        snap = rm.menu()
        assert snap.prepared == ["mage_armor", "magic_missile"]

    def test_spend_snapshot(self):
        rm = _rest_mode()
        rm.handle("2")  # spend one die -> submenu
        snap = rm.menu()
        assert snap.state == "spend"
        assert snap.options == ["Spend another hit die", "Done"]
        assert "regain" in snap.feedback

    def test_invalid_choice_feedback(self):
        rm = _rest_mode()
        rm.handle("9")
        snap = rm.menu()
        assert snap.state == "top"
        assert "Invalid" in snap.feedback

    def test_exited_snapshot(self):
        rm = _rest_mode()
        rm.handle("3")  # Done
        assert rm.exited
        snap = rm.menu()
        assert snap.state == "exited"
        assert snap.options == []

    def test_prepare_snapshot_option_ids(self):
        rm = _rest_mode()
        rm.handle("1")
        snap = rm.menu()
        # Toggle buttons check aid-in-prepared; options are display
        # labels, so the ids travel separately, in numbering order.
        assert snap.option_ids == _SPELLBOOK
        assert snap.prepared == list(_SPELLBOOK)

    def test_back_discards_selection_and_returns_to_top(self):
        rm = _rest_mode()
        rm.handle("1")  # enter prepare
        rm.handle("1")  # toggle fire_bolt off
        assert rm.menu().prepared == ["mage_armor", "magic_missile"]
        rm.handle("back")
        snap = rm.menu()
        assert snap.state == "top"
        # The working selection was discarded, not confirmed.
        rm.handle("1")
        assert rm.menu().prepared == list(_SPELLBOOK)


# ------------------------------------------------------------------
# Headless drive-through
# ------------------------------------------------------------------


class _FakeLLM:
    """Returns predetermined ruling/prose JSON, iterator-style."""

    def __init__(self, rulings, proses):
        self._rulings = list(rulings)
        self._proses = list(proses)
        self.ruling_calls = 0
        self.prose_calls = 0

    def call_ruling(self, system_prompt, user_prompt):
        self.ruling_calls += 1
        return self._rulings.pop(0)

    def call_prose(self, system_prompt, user_prompt):
        self.prose_calls += 1
        return self._proses.pop(0)

    def call(self, system_prompt, user_prompt, **kw):
        return self.call_prose(system_prompt, user_prompt)


def _rest_action_json(kind="long", detail="camp"):
    return json.dumps({
        "action_type": "rest", "kind": kind, "detail": detail,
        "follow_up": None, "soft_state_patches": [],
    })


def _wait_action_json(detail="wait"):
    return json.dumps({
        "action_type": "wait", "detail": detail,
        "follow_up": None, "soft_state_patches": [],
    })


def _prose_json(narration):
    return json.dumps({
        "narration": narration, "npc_response": None,
        "knowledge_tags": None, "attitude_changes": None,
    })


def _rest_prose_json(narration="You rest."):
    # A long rest heals, so the prose must carry the [MECH:hp_heal] marker
    # that build_indicators requires (else prose validation retries).
    return _prose_json(narration + " [MECH:hp_heal]")


def _caster_state_manager():
    """A StateManager with a prepared-caster player for rest-mode tests."""
    from mgmai.models.hard_state import HitDice

    corpus = make_char_sheet_corpus()
    player = _player(
        location="axe_head",
        spellbook=list(_SPELLBOOK),
        abilities=list(_SPELLBOOK),
        current_hp=4, max_hp=11,
        hit_dice=HitDice(die="d8", current=2, max=5),
    )
    return build_state_manager(corpus, _hard(player=player))


class TestHeadlessRestMode:
    def test_long_rest_enters_rest_mode(self, tmp_path):
        llm = _FakeLLM(
            rulings=[_rest_action_json()],
            proses=[_rest_prose_json("You camp for the night.")],
        )
        sm = _caster_state_manager()
        session = HeadlessSession(
            state_manager=sm, llm_client=llm, config_dir=tmp_path,
        )
        # Deplete slots/hp before the rest so recharge is visible.
        sm.hard_state.player.current_hp = 4
        sm.hard_state.player.spell_slots = {1: 0, 2: 1}

        transcript = session.submit("I take a long rest")
        assert "You camp for the night." in transcript.narration
        # The [MECH:hp] marker was placed (replaced with formatted text).
        assert "[MECH:hp]" not in transcript.narration
        # Recharge applied.
        assert sm.hard_state.player.current_hp == 11
        assert sm.hard_state.player.spell_slots == {1: 4, 2: 2}
        # Rest mode entered: an entry menu was rendered.
        assert session.display.rest_menus
        assert "[3] Done" in session.display.rest_menus[-1]
        assert session.session.rest_mode is not None

    def test_full_drive_through(self, tmp_path):
        # Long rest: recharge + prepare-spells flow + done.  (Hit-dice
        # spend is exercised separately — a long rest heals to full, so
        # there is nothing for a hit die to recover.)
        llm = _FakeLLM(
            rulings=[_rest_action_json()],
            proses=[_rest_prose_json("You rest.")],
        )
        sm = _caster_state_manager()
        session = HeadlessSession(
            state_manager=sm, llm_client=llm, config_dir=tmp_path,
        )
        sm.hard_state.player.current_hp = 4

        # 1. Long rest → enters rest mode.
        session.submit("rest long")
        assert session.session.rest_mode is not None
        assert sm.hard_state.player.current_hp == 11  # recharged to full

        # 2. Prepare spells → toggle fire_bolt off → confirm.
        t = session.submit("1")
        assert "Prepare spells" in t.narration
        session.submit("1")          # toggle fire_bolt off
        session.submit("0")          # confirm
        assert "fire_bolt" not in sm.hard_state.player.abilities
        assert "mage_armor" in sm.hard_state.player.abilities

        # 3. Done → exit rest mode.
        t = session.submit("3")
        assert session.session.rest_mode is None
        assert "finish" in t.narration

    def test_short_rest_spend_hit_dice(self, tmp_path):
        # A short rest does not auto-heal, so spending Hit Dice is the
        # point — this exercises the spend sub-menu headlessly.
        llm = _FakeLLM(
            rulings=[_rest_action_json(kind="short")],
            proses=[_prose_json("You take a short rest.")],
        )
        sm = _caster_state_manager()
        session = HeadlessSession(
            state_manager=sm, llm_client=llm, config_dir=tmp_path,
        )
        sm.hard_state.player.current_hp = 4
        hd_before = sm.hard_state.player.hit_dice.current

        session.submit("rest short")
        assert session.session.rest_mode is not None
        # Short rest: no auto-heal.
        assert sm.hard_state.player.current_hp == 4

        # Spend a hit die → heal, die consumed.
        t = session.submit("2")
        assert "regain" in t.narration
        assert sm.hard_state.player.hit_dice.current == hd_before - 1
        assert sm.hard_state.player.current_hp > 4

        # Done spending → back to top → done.
        session.submit("2")
        t = session.submit("3")
        assert session.session.rest_mode is None
        assert "finish" in t.narration

    def test_done_resumes_normal_play(self, tmp_path):
        llm = _FakeLLM(
            rulings=[_rest_action_json(), _wait_action_json()],
            proses=[_rest_prose_json("You rest."), _prose_json("Time passes.")],
        )
        sm = _caster_state_manager()
        session = HeadlessSession(
            state_manager=sm, llm_client=llm, config_dir=tmp_path,
        )
        session.submit("rest long")
        assert session.session.rest_mode is not None
        session.submit("3")              # done
        assert session.session.rest_mode is None
        # Normal play resumes: a wait turn runs the LLM pipeline.
        t = session.submit("I wait")
        assert t.narration == "Time passes."
        assert llm.ruling_calls == 2
