# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stainlesschicken.com>
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

"""Unit tests for the shared status/combat view-models
(mgmai/game/status.py)."""

from __future__ import annotations

from mgmai.game.status import CombatantRow, CombatView, format_combat_panel


class TestFormatCombatPanel:
    """The plain-text combat panel (used by the integration-test driver
    so it sees the same combat info as a real player)."""

    def _view(self) -> CombatView:
        return CombatView(
            round_number=2,
            initiative_order=["player", "goblin_grunt", "bugbear"],
            current_cid="player",
            party=[
                CombatantRow(
                    cid="player",
                    name="Player",
                    hp=8,
                    max_hp=24,
                    status_effects={"poisoned": 2},
                    status_effects_text="Poisoned 2",
                    fled=False,
                    engaged_with=["Bugbear"],
                    impeded=False,
                    mitigation_text="",
                ),
                CombatantRow(
                    cid="korbar",
                    name="Korbar",
                    hp=0,
                    max_hp=22,
                    status_effects={},
                    status_effects_text="",
                    fled=False,
                    engaged_with=[],
                    impeded=False,
                    mitigation_text="",
                ),
            ],
            enemies=[
                CombatantRow(
                    cid="bugbear",
                    name="Bugbear",
                    hp=22,
                    max_hp=22,
                    status_effects={},
                    status_effects_text="",
                    fled=False,
                    engaged_with=["Player"],
                    impeded=True,
                    mitigation_text="immune to slashing; vulnerable to fire",
                ),
                CombatantRow(
                    cid="goblin_runner",
                    name="Goblin Runner",
                    hp=9,
                    max_hp=9,
                    status_effects={},
                    status_effects_text="",
                    fled=True,
                    engaged_with=[],
                    impeded=False,
                    mitigation_text="",
                ),
            ],
            footer=(
                "AC 14 · Longsword (1d8 slashing) · "
                "Flame Strike 2/2 · Items: Potion of Healing x2"
            ),
        )

    def test_header_and_initiative(self):
        text = format_combat_panel(self._view())
        assert "Combat round 2" in text
        assert "Initiative: player → goblin_grunt → bugbear" in text

    def test_rows_carry_hp_status_mitigation_engagement_impede(self):
        text = format_combat_panel(self._view())
        assert "Player: 8/24 HP [Poisoned 2] engaged with Bugbear" in text
        assert (
            "Bugbear: 22/22 HP "
            "(immune to slashing; vulnerable to fire) "
            "engaged with Player impeded" in text
        )

    def test_dead_and_fled_tags(self):
        text = format_combat_panel(self._view())
        assert "Korbar †: 0/22 HP" in text
        assert "Goblin Runner (fled): 9/9 HP" in text

    def test_footer_rendered_verbatim(self):
        text = format_combat_panel(self._view())
        assert "AC 14" in text
        assert "Longsword (1d8 slashing)" in text
        assert "Flame Strike 2/2" in text
        assert "Items: Potion of Healing x2" in text

    def test_empty_party_sections_omitted(self):
        view = CombatView(
            round_number=1,
            initiative_order=["player"],
            current_cid="player",
            party=[],
            enemies=[],
            footer="AC 14",
        )
        text = format_combat_panel(view)
        assert "Party" not in text
        assert "Enemies" not in text
        assert "AC 14" in text
