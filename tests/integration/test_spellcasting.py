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

"""LLM integration tests for SRD spellcasting through the harness.

The scenarios use the ``spell_arena`` fixture (the player is a level-1
wizard with ``fire_bolt`` / ``mage_armor`` / ``magic_missile`` from the
SRD spell pack) and the scripted single-turn ``run_indicator_turn``
harness: a hand-written ``PlayerAction`` is resolved by the real engine
against a preset ``CombatState`` (Call 1 is bypassed so the mechanical
outcome is controlled) and the real GM prose call narrates the segment.

Each scenario grants exactly the pack spells it exercises — the bonus
spell list must stay minimal, because any granted bonus-action ability
(e.g. ``produce_flame``) keeps the player turn open after the main
action, changing the round flow.  Multi-segment scenarios CHAIN
``run_indicator_turn`` calls on one shared ``StateManager`` so budget
flags, concentration, and statuses persist between segments.

Representative spells were chosen for the LLM-harness edge cases they
exercise:

- ``hold_person`` — save → ``paralyzed`` status, the target's skipped
  turn (``stunned`` entry), concentration engaged, and — in the last
  scenario — damage breaking concentration and clearing the sustained
  status (``concentration_check`` / ``concentration_end`` entries).
- ``faerie_fire`` / ``invisibility`` / ``blur`` — save/on-cast statuses
  that change attack-roll modifiers (advantage on the player's next
  attack, disadvantage against the buffed player); the narration must
  reflect outcomes driven by those modifiers.
- ``produce_flame`` — a bonus-action *attack* cantrip that keeps the
  turn open, unlike the heal/on-cast bonus actions exercised elsewhere.
- ``magic_missile`` without a slot — the engine rejection surfaced
  through the narration path.
- ``barkskin`` — out-of-combat casting (``ac_base`` replacement).

Dice are pinned per segment (``seed=7``; ``seed=82`` for the
concentration-break scenario); the expectations below were derived by
running the identical engine sequences offline with those seeds.  The
assertions are structural plus pinned rolls (the ``ability_save`` entry
carries ``save_roll``/``save_total``, attacks carry
``attack_roll``/``attack_total``/``hit``), so they hold deterministically
while the narration itself stays a live GM call.
"""

from __future__ import annotations

import pytest

from mgmai.engine.systems import get_system_for_corpus
from mgmai.models.combat import CombatState
from mgmai.state.manager import StateManager
from tests.integration.indicator_runner import run_indicator_turn
from tests.integration.judge import record_judge_verdict

pytestmark = pytest.mark.llm

# Pinned dice for the scripted segments (see module docstring).
_SEED = 7
_BREAK_SEED = 82

_GRUNT = ["player", "goblin_grunt"]


def _sm(adventure_dir) -> StateManager:
    return StateManager(adventure_dir=str(adventure_dir))


def _sm_in_combat(adventure_dir, combatants) -> StateManager:
    """Load the fixture with the player mid-combat, acting first."""
    sm = _sm(adventure_dir)
    sm.hard_state.combat = CombatState(
        active=True,
        combatants=list(combatants),
        initiative_order=list(combatants),
        current_index=0,
        round_number=1,
    )
    return sm


def _grant(sm, *spells, slots=None) -> None:
    """Grant SRD pack spells (and slots) beyond the fixture's baseline
    ``fire_bolt`` / ``mage_armor`` / ``magic_missile``."""
    player = sm.hard_state.player
    for aid in spells:
        if aid not in player.abilities:
            player.abilities = list(player.abilities) + [aid]
    player.spell_slots = dict(slots or {1: 2, 2: 2})


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
    seed=_SEED,
):
    """Run one scripted segment and apply the shared hard assertions:
    the artifact was written, no harness error, and the real GM prose
    call produced narration for the segment (a rejected cast is a
    normal narration, not a harness error)."""
    result = run_indicator_turn(
        scenario_name=scenario_name,
        gm_client=gm_client,
        state_manager=sm,
        action=action,
        player_input=player_input,
        config_dir=config_dir,
        artifacts_dir=artifacts_dir,
        seed=seed,
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


def _cast(ability_id, target, detail):
    return {
        "action_type": "use_ability",
        "ability_id": ability_id,
        "target": target,
        "detail": detail,
    }


def _goblin_statuses(sm) -> dict:
    return sm.hard_state.entity_states["goblin_grunt"].get("status_effects") or {}


# ------------------------------------------------------------------
# Scenario 1: hold_person — save → paralyzed, skipped turn, concentration
# ------------------------------------------------------------------


@pytest.mark.llm
def test_hold_person_paralyzes_and_skips_turn(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A failed WIS save against hold_person applies ``paralyzed``, the
    goblin's turn is consumed (``stunned`` entry), concentration engages,
    and the level-2 slot is spent — all surfaced through the harness."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, "hold_person")

    seg = _segment(
        "spellcasting_hold_person",
        gm_client,
        sm,
        _cast("hold_person", "goblin_grunt", "Hold the goblin in place!"),
        "hold person on the goblin",
        tmp_path,
        artifacts_dir,
    )
    assert (seg.engine_result or {}).get("success") is True

    saves = list(_entries(seg, actor="player", action="ability_save"))
    assert len(saves) == 1
    save = saves[0]
    assert save["attack_id"] == "hold_person"
    assert save["spell_id"] == "hold_person" and save["spell_level"] == 2
    assert save["on_hit_effects"][0]["save_stat"] == "WIS"
    assert save["on_hit_effects"][0]["save_dc"] == 13  # 8 + prof 2 + INT 16 (+3)
    assert save["on_hit_effects"][0]["save_roll"] == 11
    assert save["on_hit_effects"][0]["save_success"] is False
    assert save["on_hit_effects"][0]["status_effect"] == "paralyzed"

    # The paralyzed goblin loses its turn — a stunned entry, no attack.
    assert len(list(_entries(seg, actor="goblin_grunt", action="stunned"))) == 1
    assert not list(_entries(seg, actor="goblin_grunt", action="attack"))

    assert _combat(sm).concentration == {"player": "hold_person"}
    assert sm.hard_state.player.status_effects == {"concentrating": 1}
    assert _goblin_statuses(sm)["paralyzed"] == 9  # ticked at its turn start
    assert sm.hard_state.player.spell_slots == {1: 2, 2: 1}

    record_judge_verdict(judge_client, seg)


# ------------------------------------------------------------------
# Scenario 2: faerie_fire — save status, then an attack under advantage
# ------------------------------------------------------------------


@pytest.mark.llm
def test_faerie_fire_marks_target_then_attack(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """faerie_fire applies the ``faerie_fire`` status on a failed DEX
    save (attack rolls against the target gain advantage); the follow-up
    attack in the next round lands under the pinned dice.  The goblin's
    round-1 attack misses, so concentration is never tested."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, "faerie_fire")

    seg1 = _segment(
        "spellcasting_faerie_fire",
        gm_client,
        sm,
        _cast("faerie_fire", "goblin_grunt", "Outline the goblin in light!"),
        "faerie fire on the goblin",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    saves = list(_entries(seg1, actor="player", action="ability_save"))
    assert len(saves) == 1
    assert saves[0]["attack_id"] == "faerie_fire"
    assert saves[0]["spell_id"] == "faerie_fire" and saves[0]["spell_level"] == 1
    assert saves[0]["on_hit_effects"][0]["save_stat"] == "DEX"
    assert saves[0]["on_hit_effects"][0]["save_roll"] == 11
    assert saves[0]["on_hit_effects"][0]["save_success"] is False
    assert saves[0]["on_hit_effects"][0]["status_effect"] == "faerie_fire"
    assert _goblin_statuses(sm)["faerie_fire"] == 9

    # Round-1 goblin attack misses (roll 5 + 4 = 9 vs AC 12) — no
    # concentration save.
    gob = list(_entries(seg1, actor="goblin_grunt", action="attack"))
    assert len(gob) == 1
    assert gob[0]["attack_roll"] == 5 and gob[0]["hit"] is False
    assert _combat(sm).concentration == {"player": "faerie_fire"}
    assert sm.hard_state.player.spell_slots == {1: 1, 2: 2}

    # Round 2: fire bolt (spell attack +5) lands: roll 11 → total 16 vs
    # AC 13, 7 damage; the goblin is down to 4 HP.
    seg2 = _segment(
        "spellcasting_faerie_fire_attack",
        gm_client,
        sm,
        _cast("fire_bolt", "goblin_grunt", "Bolt the goblin!"),
        "attack the goblin with fire bolt",
        tmp_path,
        artifacts_dir,
    )
    atks = list(_entries(seg2, actor="player", action="attack"))
    assert len(atks) == 1
    assert atks[0]["attack_id"] == "fire_bolt" and atks[0]["spell_id"] == "fire_bolt"
    assert atks[0]["round"] == 2
    assert atks[0]["attack_roll"] == 11 and atks[0]["attack_total"] == 16
    assert atks[0]["hit"] is True and atks[0]["damage"] == 7
    assert sm.hard_state.entity_states["goblin_grunt"]["current_hp"] == 4
    # Concentration held through the miss; the status is still active.
    assert _combat(sm).concentration == {"player": "faerie_fire"}
    assert "faerie_fire" in _goblin_statuses(sm)

    record_judge_verdict(judge_client, seg2)


# ------------------------------------------------------------------
# Scenario 3: produce_flame — bonus-action attack cantrip, turn stays open
# ------------------------------------------------------------------


@pytest.mark.llm
def test_produce_flame_bonus_action_keeps_turn_open(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """A bonus-action *attack* cantrip (produce_flame) deals its damage
    without ending the turn; the main action then closes it.  The NPC
    turns run only after the second segment."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, "produce_flame")

    seg1 = _segment(
        "spellcasting_produce_flame_ba",
        gm_client,
        sm,
        _cast("produce_flame", "goblin_grunt", "Hurl a flame at the goblin!"),
        "produce flame at the goblin",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    ba = list(_entries(seg1, actor="player", action="attack"))
    assert len(ba) == 1
    assert ba[0]["attack_id"] == "produce_flame"
    assert ba[0]["spell_id"] == "produce_flame" and ba[0]["spell_level"] == 0
    assert ba[0]["round"] == 1
    assert ba[0]["attack_roll"] == 11 and ba[0]["attack_total"] == 16
    assert ba[0]["hit"] is True and ba[0]["damage"] == 3
    assert not list(_entries(seg1, actor="goblin_grunt")), (
        "NPC turns ran after the bonus-action segment"
    )
    budget = _combat(sm).player_budget
    assert budget.bonus_action_used is True
    assert budget.action_used is False
    assert budget.slot_cast_this_turn is False  # cantrip
    assert sm.hard_state.player.spell_slots == {1: 2, 2: 2}
    assert _combat(sm).turn_continuation is True
    assert _combat(sm).round_number == 1

    # Main action: fire bolt closes the turn and the goblin attacks.
    seg2 = _segment(
        "spellcasting_produce_flame_main",
        gm_client,
        sm,
        _cast("fire_bolt", "goblin_grunt", "Bolt the goblin!"),
        "attack the goblin with fire bolt",
        tmp_path,
        artifacts_dir,
    )
    main = list(_entries(seg2, actor="player", action="attack"))
    assert len(main) == 1 and main[0]["round"] == 1
    assert main[0]["hit"] is True and main[0]["damage"] == 3
    gob = list(_entries(seg2, actor="goblin_grunt", action="attack"))
    assert len(gob) == 1
    assert gob[0]["round"] == 1
    assert gob[0]["attack_roll"] == 13 and gob[0]["attack_total"] == 17
    assert gob[0]["hit"] is True and gob[0]["damage"] == 6
    assert sm.hard_state.player.current_hp == 2
    assert _combat(sm).turn_continuation is False
    assert _combat(sm).round_number == 2

    record_judge_verdict(judge_client, seg2)


# ------------------------------------------------------------------
# Scenario 4: blur — self on-cast buff; enemy attacks at disadvantage
# ------------------------------------------------------------------


@pytest.mark.llm
def test_blur_self_buff_disadvantages_enemy_attacks(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Casting blur on self applies the ``blur`` status
    (``disadvantage_against``) plus ``concentrating``; the goblin's
    attack rolls at disadvantage and misses under the pinned dice."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, "blur")

    seg = _segment(
        "spellcasting_blur",
        gm_client,
        sm,
        _cast("blur", "player", "Blur my form!"),
        "cast blur on myself",
        tmp_path,
        artifacts_dir,
    )
    assert (seg.engine_result or {}).get("success") is True
    casts = list(_entries(seg, actor="player", action="ability_on_cast"))
    assert len(casts) == 1
    assert casts[0]["attack_id"] == "blur" and casts[0]["spell_id"] == "blur"
    assert casts[0]["spell_level"] == 2
    assert casts[0]["on_hit_effects"][0]["status_effect"] == "blur"

    assert sm.hard_state.player.status_effects == {"concentrating": 1, "blur": 10}
    assert _combat(sm).concentration == {"player": "blur"}
    assert sm.hard_state.player.spell_slots == {1: 2, 2: 1}

    # The goblin's attack is disadvantaged; the pinned lower roll (5)
    # misses (5 + 4 = 9 vs AC 12).
    gob = list(_entries(seg, actor="goblin_grunt", action="attack"))
    assert len(gob) == 1
    assert gob[0]["attack_roll"] == 5 and gob[0]["hit"] is False
    assert _combat(sm).turn_continuation is False
    assert _combat(sm).round_number == 2

    record_judge_verdict(judge_client, seg)


# ------------------------------------------------------------------
# Scenario 5: invisibility — on-cast buff persists through an attack
# ------------------------------------------------------------------


@pytest.mark.llm
def test_invisibility_on_cast_persists_through_attack(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Casting invisibility on self applies ``invisible`` (attack rolls
    against the caster have disadvantage, the caster's have advantage).
    The engine does not end the spell when the caster attacks (a
    documented simplification), so the round-2 fire bolt keeps the
    advantage — the persistence is part of the surfaced behavior."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, "invisibility")

    seg1 = _segment(
        "spellcasting_invisibility",
        gm_client,
        sm,
        _cast("invisibility", "player", "Vanish from sight!"),
        "cast invisibility on myself",
        tmp_path,
        artifacts_dir,
    )
    assert (seg1.engine_result or {}).get("success") is True
    casts = list(_entries(seg1, actor="player", action="ability_on_cast"))
    assert len(casts) == 1
    assert casts[0]["attack_id"] == "invisibility"
    assert casts[0]["on_hit_effects"][0]["status_effect"] == "invisible"
    assert sm.hard_state.player.status_effects == {
        "concentrating": 1, "invisible": 10,
    }
    # The invisible player's attacker is disadvantaged; the pinned roll
    # misses.
    gob = list(_entries(seg1, actor="goblin_grunt", action="attack"))
    assert len(gob) == 1 and gob[0]["attack_roll"] == 5 and gob[0]["hit"] is False

    # Round 2: the attack resolves under the higher of two d20s (11),
    # and the invisible status survives the attack.
    seg2 = _segment(
        "spellcasting_invisibility_attack",
        gm_client,
        sm,
        _cast("fire_bolt", "goblin_grunt", "Bolt the goblin!"),
        "attack the goblin with fire bolt",
        tmp_path,
        artifacts_dir,
    )
    atks = list(_entries(seg2, actor="player", action="attack"))
    assert len(atks) == 1
    assert atks[0]["round"] == 2
    assert atks[0]["attack_roll"] == 11 and atks[0]["attack_total"] == 16
    assert atks[0]["hit"] is True and atks[0]["damage"] == 7
    assert sm.hard_state.entity_states["goblin_grunt"]["current_hp"] == 4
    assert sm.hard_state.player.status_effects == {
        "concentrating": 1, "invisible": 9,  # ticked, but still active
    }
    assert _combat(sm).concentration == {"player": "invisibility"}

    record_judge_verdict(judge_client, seg2)


# ------------------------------------------------------------------
# Scenario 6: leveled spell with no slot — rejected through the pipeline
# ------------------------------------------------------------------


@pytest.mark.llm
def test_leveled_spell_without_slot_rejected_gracefully(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Casting magic missile with no level-1 slots is rejected up front
    by the engine; the harness still narrates the failed cast and the
    combat state is untouched (no log entries, no slot consumption)."""
    sm = _sm_in_combat(spell_arena_dir, _GRUNT)
    _grant(sm, slots={1: 0, 2: 2})  # fire_bolt/mage_armor/magic_missile baseline

    seg = _segment(
        "spellcasting_no_slot",
        gm_client,
        sm,
        _cast("magic_missile", "goblin_grunt", "Unleash the darts!"),
        "cast magic missile at the goblin",
        tmp_path,
        artifacts_dir,
    )
    result = seg.engine_result or {}
    assert result.get("success") is False
    assert "No level-1 spell slots remaining" in result.get("error", "")
    assert not result.get("combat_log")
    assert sm.hard_state.player.spell_slots == {1: 0, 2: 2}
    budget = _combat(sm).player_budget
    assert budget.action_used is False and budget.slot_cast_this_turn is False
    assert _combat(sm).round_number == 1

    record_judge_verdict(judge_client, seg)


# ------------------------------------------------------------------
# Scenario 7: barkskin — out-of-combat casting (ac_base replacement)
# ------------------------------------------------------------------


@pytest.mark.llm
def test_barkskin_out_of_combat(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """Outside combat, a self/ally on-cast spell resolves directly:
    barkskin applies its persistent status, spends the level-2 slot,
    and raises the player's AC to 17 + DEX modifier without entering
    combat."""
    sm = _sm(spell_arena_dir)
    _grant(sm, "barkskin")

    seg = _segment(
        "spellcasting_barkskin_ooc",
        gm_client,
        sm,
        _cast("barkskin", "player", "Toughen my skin to bark!"),
        "cast barkskin on myself",
        tmp_path,
        artifacts_dir,
    )
    assert (seg.engine_result or {}).get("success") is True
    assert sm.hard_state.player.status_effects == {"barkskin": 1}
    assert sm.hard_state.player.spell_slots == {1: 2, 2: 1}
    assert sm.hard_state.combat is None, "OOC cast must not start combat"

    corpus = sm.corpus
    ac = get_system_for_corpus(corpus).compute_player_ac(sm.hard_state, corpus)
    assert ac == 19  # ac_base 17 + DEX 14 (+2)

    record_judge_verdict(judge_client, seg)


# ------------------------------------------------------------------
# Scenario 8: damage breaks concentration and clears the sustained status
# ------------------------------------------------------------------


@pytest.mark.llm
def test_damage_breaks_concentration_clears_status(
    gm_client,
    judge_client,
    spell_arena_dir,
    artifacts_dir,
    tmp_path,
):
    """When a concentrating caster takes damage and fails the
    Constitution save, concentration ends and the spell's sustained
    status effects are removed: the hobgoblin's hit drops the player to
    2 HP, the CON save fails (6 + 2 = 8 < DC 10), and the goblin's
    ``paralyzed`` clears — logged as ``concentration_check`` +
    ``concentration_end`` (seed 82, derived offline)."""
    sm = _sm_in_combat(spell_arena_dir, ["player", "goblin_grunt", "hobgoblin"])
    _grant(sm, "hold_person")

    seg = _segment(
        "spellcasting_concentration_break",
        gm_client,
        sm,
        _cast("hold_person", "goblin_grunt", "Hold the goblin in place!"),
        "hold person on the goblin",
        tmp_path,
        artifacts_dir,
        seed=_BREAK_SEED,
    )
    assert (seg.engine_result or {}).get("success") is True

    # Paralyzed on the failed save, then the goblin's turn is skipped.
    saves = list(_entries(seg, actor="player", action="ability_save"))
    assert len(saves) == 1
    assert saves[0]["on_hit_effects"][0]["save_roll"] == 5
    assert saves[0]["on_hit_effects"][0]["status_effect"] == "paralyzed"
    assert len(list(_entries(seg, actor="goblin_grunt", action="stunned"))) == 1

    # Hobgoblin hits for 6 (roll 16 + 5 = 21 vs AC 12); the player fails
    # the CON save (6 + 2 = 8 < DC 10) and concentration drops.
    hob = list(_entries(seg, actor="hobgoblin", action="attack"))
    assert len(hob) == 1
    assert hob[0]["hit"] is True and hob[0]["damage"] == 6
    assert sm.hard_state.player.current_hp == 2

    check = list(_entries(seg, actor="player", action="concentration_check"))
    assert len(check) == 1
    assert check[0]["on_hit_effects"][0]["save_stat"] == "CON"
    assert check[0]["on_hit_effects"][0]["save_dc"] == 10
    assert check[0]["on_hit_effects"][0]["save_roll"] == 6
    assert check[0]["on_hit_effects"][0]["save_total"] == 8
    assert check[0]["on_hit_effects"][0]["save_success"] is False

    ended = list(_entries(seg, actor="player", action="concentration_end"))
    assert len(ended) == 1
    assert ended[0]["attack_id"] == "hold_person"

    # The sustained status is cleared from the goblin and the caster no
    # longer concentrates.
    assert sm.hard_state.player.status_effects == {}
    assert _goblin_statuses(sm) == {}
    assert _combat(sm).concentration == {}
    assert _combat(sm).round_number == 2

    record_judge_verdict(judge_client, seg)
