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

"""LLM integration test: conditions, on-hit effects, multiattack,
immunity, and player abilities in the venom pit.

A driver LLM plays the player against the real GM LLM on the
``venom_pit`` fixture.  Hard assertions verify the engine mechanics
(on-hit saves, conditions, multiattack sequences, damage immunity,
attack/heal abilities); an advisory LLM judge records a
narration-quality verdict in the artifact (it does not gate the test).

RNG note: several mechanics are chance-gated (the viper must hit, the
player must fail a save).  Following the combat-arena precedent, the
mechanic-specific assertions are conditional where RNG decides whether
the path was exercised at all, and emit warnings when it wasn't.
"""

from __future__ import annotations

import warnings

import pytest

from tests.integration.helpers import assert_combat_concluded, combat_log_entries
from tests.integration.runner import run_scenario
from tests.integration.test_combat_arena import (
    _record_judge_verdict,
    _stop_when_combat_ended,
)

pytestmark = pytest.mark.llm


# ------------------------------------------------------------------
# Scenario 1: poison on-hit effect + antidote cure
# ------------------------------------------------------------------

POISON_DIRECTIVE = """\
You are in a vermin-infested pit with your ally Willa.  She is hanging
back to guard your gear — you are on your own for this fight.

- Attack the pit viper with your longsword and keep attacking until it
  is dead.
- Its bite is venomous: if the GM says you are poisoned, drink an
  Antidote on your next turn.  You carry 2.
- Do not attack the other creatures.  Do not flee.
"""


def _build_passive_willa_state_manager(venom_pit_dir):
    """Load the pit with Willa passive so the viper always targets the
    player: she never hits it, so its last-attacker AI falls back to the
    player and the poison save path is exercised on nearly every run.
    """
    from mgmai.state.manager import StateManager

    sm = StateManager(adventure_dir=str(venom_pit_dir))
    sm.hard_state.entity_states["willa"]["passive"] = True
    return sm


@pytest.mark.llm
def test_poisoned_and_cured(
    gm_client,
    driver_client,
    judge_client,
    venom_pit_dir,
    artifacts_dir,
    tmp_path,
):
    """Viper poison on-hit effects fire; the driver cures with an antidote."""
    sm = _build_passive_willa_state_manager(venom_pit_dir)
    result = run_scenario(
        scenario_name="poisoned_and_cured",
        gm_client=gm_client,
        driver_client=driver_client,
        state_manager=sm,
        artifacts_dir=artifacts_dir,
        directive=POISON_DIRECTIVE,
        max_turns=18,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat concluded (win or graceful loss).
    assert_combat_concluded(result, {"pit_viper"})

    # The viper landed at least one bite on the player (Willa is
    # passive, so it always targets the player — a whiffed run is
    # possible but very unlikely).
    viper_hits = [
        e for e in combat_log_entries(result, actor="pit_viper", action="attack")
        if e.get("hit") and e.get("target") in (None, "player")
    ]
    assert viper_hits, (
        "Viper never hit the player; poison on-hit path untested; "
        f"see artifact: {result.artifacts_path}"
    )

    # Every viper hit carries the CON-save poison on-hit effect.
    failed_save = False
    for e in viper_hits:
        effects = e.get("on_hit_effects") or []
        assert effects, (
            "Viper hit without on_hit_effects; see artifact: "
            f"{result.artifacts_path}"
        )
        for fx in effects:
            assert fx.get("save_stat") == "CON" and fx.get("damage_type") == "poison", (
                f"Unexpected on-hit effect {fx!r}; see artifact: "
                f"{result.artifacts_path}"
            )
            if fx.get("save_success") is False:
                failed_save = True

    # If a save was failed, the player was poisoned and the driver was
    # told to drink an antidote.
    if failed_save:
        has_antidote = any(
            e.get("target") == "antidote"
            for e in combat_log_entries(result, actor="player", action="use_item")
        )
        assert has_antidote, (
            "Player was poisoned but never drank an antidote; "
            f"see artifact: {result.artifacts_path}"
        )
    else:
        warnings.warn(
            "Player never failed a poison save; antidote path untested "
            f"this run; see artifact: {result.artifacts_path}",
            stacklevel=2,
        )

    # Conditions are combat-scoped: none may linger after combat.
    player_final = (result.final_status or {}).get("player", {})
    assert player_final.get("conditions", {}) == {}, (
        f"Player conditions linger after combat: "
        f"{player_final.get('conditions')}; see artifact: {result.artifacts_path}"
    )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 2: multiattack + stun on-hit effect
# ------------------------------------------------------------------

CRAWLER_DIRECTIVE = """\
You are in a vermin-infested pit with your ally Willa.

- Attack the carrion crawler with your longsword and keep attacking
  until it is dead.
- Every round it lashes out with its paralysing tentacles and then
  bites.  If you are stunned and lose a turn, shake it off and keep
  fighting.
- Do not attack the other creatures.  Do not flee.
"""


@pytest.mark.llm
def test_multiattack_and_stun(
    gm_client,
    driver_client,
    judge_client,
    venom_pit_dir,
    artifacts_dir,
    tmp_path,
):
    """Crawler performs its tentacles+bite sequence; stun is handled."""
    result = run_scenario(
        scenario_name="multiattack_and_stun",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=venom_pit_dir,
        artifacts_dir=artifacts_dir,
        directive=CRAWLER_DIRECTIVE,
        max_turns=15,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat concluded (win or graceful loss).
    assert_combat_concluded(result, {"carrion_crawler"})

    # In some round the crawler performed both named attacks.  (Its
    # multiattack sequence stops early only if the target drops, which
    # cannot happen from full HP against its small damage dice.)
    crawler_attacks = list(
        combat_log_entries(result, actor="carrion_crawler", action="attack")
    )
    rounds: dict[int, set] = {}
    for e in crawler_attacks:
        rounds.setdefault(e.get("round"), set()).add(e.get("attack_id"))
    assert any(
        {"tentacles", "bite"} <= ids for ids in rounds.values()
    ), (
        f"Crawler never completed its tentacles+bite multiattack; "
        f"rounds seen: {rounds}; see artifact: {result.artifacts_path}"
    )

    # Stun path: a failed tentacle CON save stuns the player; the
    # player's next turn must then be logged as 'stunned'.
    failed_turn = None
    for ti, t in enumerate(result.turns):
        for e in t.combat_log:
            if (
                e.get("actor") == "carrion_crawler"
                and e.get("attack_id") == "tentacles"
                and e.get("hit")
                and e.get("target") in (None, "player")
            ):
                for fx in e.get("on_hit_effects") or []:
                    if fx.get("save_success") is False:
                        failed_turn = ti
    stunned_after = any(
        e.get("actor") == "player" and e.get("action") == "stunned"
        for t in result.turns[failed_turn + 1:]
        for e in t.combat_log
    ) if failed_turn is not None else False

    if failed_turn is None:
        warnings.warn(
            "Player never failed a tentacle save; stun path untested "
            f"this run; see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
    elif failed_turn == len(result.turns) - 1:
        warnings.warn(
            "Stun applied on the final turn; no later turn to observe "
            f"the lost turn; see artifact: {result.artifacts_path}",
            stacklevel=2,
        )
    else:
        assert stunned_after, (
            "Player failed a tentacle save but no 'stunned' turn was "
            f"logged afterwards; see artifact: {result.artifacts_path}"
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 3: slashing immunity + mid-combat weapon swap
# ------------------------------------------------------------------

JELLY_DIRECTIVE = """\
You are in a vermin-infested pit with your ally Willa.  Before you
quivers an ochre jelly — you suspect slashing blades cannot hurt it.

- Attack the ochre jelly with your longsword, and keep swinging the
  longsword at it for your first TWO attacks to be sure your slashes
  really do nothing.
- Then swap weapons: sheathe your longsword and draw your war hammer
  (bludgeoning — the only thing in your pack that can pulp the jelly).
- Keep attacking the jelly with the war hammer until it is destroyed.
- Do not attack the other creatures.  Do not flee.
"""


@pytest.mark.llm
def test_immunity_weapon_swap(
    gm_client,
    driver_client,
    judge_client,
    venom_pit_dir,
    artifacts_dir,
    tmp_path,
):
    """Slashing immunity is logged; the driver swaps to the war hammer."""
    result = run_scenario(
        scenario_name="immunity_weapon_swap",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=venom_pit_dir,
        artifacts_dir=artifacts_dir,
        directive=JELLY_DIRECTIVE,
        max_turns=22,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat concluded.  Note: if the GM/engine cannot perform a
    # mid-combat weapon swap, the jelly can never die (it is immune to
    # the only other damage the party deals) and this fails on the turn
    # cap — that is the intended signal for this scenario.
    assert_combat_concluded(result, {"ochre_jelly"})

    # At least one longsword hit was nullified by the jelly's immunity.
    player_attacks = list(
        combat_log_entries(result, actor="player", action="attack")
    )
    immune_hits = [e for e in player_attacks if e.get("mitigation") == "immune"]
    assert immune_hits, (
        "No player attack was nullified by slashing immunity; "
        f"see artifact: {result.artifacts_path}"
    )
    for e in immune_hits:
        assert (e.get("damage") or 0) == 0, (
            f"Immune hit dealt {e.get('damage')} damage; "
            f"see artifact: {result.artifacts_path}"
        )

    last = result.last_turn
    if (last.status.player_hp or 0) > 0:
        # Win path: after the immunity was observed, the player swapped
        # to the war hammer and dealt bludgeoning damage with it.
        bludgeon_hits = [
            e for e in player_attacks if e.get("damage_type") == "bludgeoning"
        ]
        assert bludgeon_hits, (
            "Player never dealt bludgeoning damage; weapon swap did not "
            f"happen; see artifact: {result.artifacts_path}"
        )
        player_final = (result.final_status or {}).get("player", {})
        equipped = player_final.get("equipped", [])
        assert "war_hammer" in equipped and "longsword" not in equipped, (
            f"Expected war_hammer equipped after the swap, got {equipped}; "
            f"see artifact: {result.artifacts_path}"
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)


# ------------------------------------------------------------------
# Scenario 4: player attack + heal abilities
# ------------------------------------------------------------------

ABILITIES_DIRECTIVE = """\
You are in a vermin-infested pit with your ally Willa, facing a
carrion crawler.

- Use your Power Strike ability on the crawler (you can use it twice
  per combat), then finish it with longsword attacks.
- Watch Willa's health: if she drops below half HP, use your Healing
  Hands ability on her.
- Do not attack the other creatures.  Do not flee.
"""


@pytest.mark.llm
def test_player_abilities(
    gm_client,
    driver_client,
    judge_client,
    venom_pit_dir,
    artifacts_dir,
    tmp_path,
):
    """Driver uses Power Strike (attack ability) and Healing Hands (heal)."""
    result = run_scenario(
        scenario_name="player_abilities",
        gm_client=gm_client,
        driver_client=driver_client,
        adventure_dir=venom_pit_dir,
        artifacts_dir=artifacts_dir,
        directive=ABILITIES_DIRECTIVE,
        max_turns=18,
        config_dir=tmp_path,
        stop_when=_stop_when_combat_ended,
    )

    assert result.artifacts_path is not None
    assert result.artifacts_path.is_file()

    # Combat concluded (win or graceful loss).
    assert_combat_concluded(result, {"carrion_crawler"})

    # Power Strike (an attack-roll ability) was used at least once and
    # never more than its 2 uses per combat.
    power_strikes = [
        e for e in combat_log_entries(result, actor="player", action="attack")
        if e.get("attack_id") == "power_strike"
    ]
    assert power_strikes, (
        "Driver never used Power Strike; see artifact: "
        f"{result.artifacts_path}"
    )
    assert len(power_strikes) <= 2, (
        f"Power Strike used {len(power_strikes)} times "
        f"(uses_per_combat=2); see artifact: {result.artifacts_path}"
    )

    # Healing Hands: if Willa ever dropped below half HP (8) while
    # alive, the driver was told to heal her.  Her HP is visible in the
    # driver's per-turn situation line.
    willa_hurt = any(
        (t.status.combatants.get("willa") or {}).get("alive")
        and ((t.status.combatants.get("willa") or {}).get("hp") or 999) < 8
        for t in result.turns
    )
    if willa_hurt:
        has_heal = any(
            e.get("attack_id") == "healing_hands" and e.get("target") == "willa"
            for e in combat_log_entries(result, actor="player", action="heal")
        )
        assert has_heal, (
            "Willa dropped below half HP but the driver never healed her "
            f"with Healing Hands; see artifact: {result.artifacts_path}"
        )
    else:
        warnings.warn(
            "Willa never dropped below half HP; Healing Hands path "
            f"untested this run; see artifact: {result.artifacts_path}",
            stacklevel=2,
        )

    # Advisory judge verdict (recorded in the artifact; not a gate).
    _record_judge_verdict(judge_client, result)
