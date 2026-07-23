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

"""Tests for game/commands.py — slash-command dispatcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mgmai.game.commands import Commands


@pytest.fixture
def state_loader() -> MagicMock:
    m = MagicMock()
    m.loaded = True
    m._adventure_dir = MagicMock()
    m._adventure_dir.name = "bag-of-holding"
    return m


@pytest.fixture
def render() -> MagicMock:
    return MagicMock()


@pytest.fixture
def exit_fn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def commands(state_loader, render, exit_fn) -> Commands:
    return Commands(state_loader, render, exit_fn)


class TestHandleRouting:
    """Command routing: handle() dispatches to the correct handler."""

    def test_non_slash_returns_false(self, commands) -> None:
        assert commands.handle("look around") is False
        assert commands.handle("") is False
        assert commands.handle("  not a command  ") is False

    def test_unknown_slash_returns_false(self, commands) -> None:
        assert commands.handle("/foobar") is False

    def test_help_dispatches(self, commands, render) -> None:
        assert commands.handle("/help") is True
        render.assert_called_once()
        assert "Available Commands" in render.call_args[0][0]

    def test_help_alias_h(self, commands, render) -> None:
        assert commands.handle("/h") is True
        render.assert_called_once()
        assert "Available Commands" in render.call_args[0][0]

    def test_exit_dispatches(self, commands, exit_fn) -> None:
        assert commands.handle("/exit") is True
        exit_fn.assert_called_once()

    def test_exit_alias_quit(self, commands, exit_fn) -> None:
        assert commands.handle("/quit") is True
        exit_fn.assert_called_once()

    def test_exit_alias_q(self, commands, exit_fn) -> None:
        assert commands.handle("/q") is True
        exit_fn.assert_called_once()


class TestDebugToggle:
    """Toggle debug mode via /debug."""

    def test_debug_toggles(self, commands) -> None:
        import logging
        # get_level() reads root logger level; toggle direction depends on it.
        # Set root level to INFO so first toggle goes ON.
        logging.getLogger("mgmai").setLevel(logging.INFO)
        assert commands.debug is False
        commands.handle("/debug")
        assert commands.debug is True


class TestSave:
    """Save command: /save [filename]."""

    def test_save_default_filename(self, commands, state_loader) -> None:
        commands.handle("/save")
        state_loader.save.assert_called_once()
        assert "save.json" in state_loader.save.call_args[0][0]

    def test_save_custom_filename(self, commands, state_loader) -> None:
        commands.handle("/save mygame.json")
        state_loader.save.assert_called_once()
        assert "mygame.json" in state_loader.save.call_args[0][0]

    def test_save_not_loaded(self, state_loader, render, exit_fn) -> None:
        state_loader.loaded = False
        cmds = Commands(state_loader, render, exit_fn)
        cmds.handle("/save")
        render.assert_called_once()
        assert "No game to save" in render.call_args[0][0]


class TestLoad:
    """Load command: /load <filename>."""

    def test_load_without_filename_shows_usage(self, commands, render) -> None:
        commands.handle("/load")
        render.assert_called_once()
        assert "Usage" in render.call_args[0][0]

    def test_load_calls_state_load_save(self, commands, state_loader) -> None:
        commands.handle("/load save.json")
        state_loader.load_save.assert_called_once()

    def test_load_calls_on_load_callback(self, state_loader, render, exit_fn) -> None:
        on_load = MagicMock()
        cmds = Commands(state_loader, render, exit_fn, on_load=on_load)
        cmds.handle("/load save.json")
        on_load.assert_called_once()

    def test_load_file_not_found(self, commands, state_loader, render) -> None:
        state_loader.load_save.side_effect = FileNotFoundError
        commands.handle("/load missing.json")
        render.assert_called_once()
        assert "not found" in render.call_args[0][0]

    def test_load_other_error(self, commands, state_loader, render) -> None:
        state_loader.load_save.side_effect = ValueError("bad format")
        commands.handle("/load bad.json")
        render.assert_called_once()
        assert "Load failed" in render.call_args[0][0]


class TestModel:
    """Model command: /model — show and switch model config."""

    @pytest.fixture
    def model_commands(self, state_loader, render, exit_fn, tmp_path) -> Commands:
        return Commands(state_loader, render, exit_fn, config_dir=str(tmp_path))

    def test_model_no_config(self, model_commands, render) -> None:
        model_commands.handle("/model")
        render.assert_called()
        assert "not available" in render.call_args[0][0]

    def test_model_shows_config_details(self, state_loader, render, exit_fn, tmp_path) -> None:
        from mgmai.llm.model_config import ModelConfig

        config = ModelConfig(
            name="test-model",
            base_url="https://api.example.com",
            label="Test Model",
            ruling_temperature=0.3,
            prose_temperature=0.7,
            supports_json_mode=True,
            request_timeout=30,
            ruling_max_tokens=512,
            prose_max_tokens=1024,
        )
        cmds = Commands(state_loader, render, exit_fn, model_config=config,
                        config_dir=str(tmp_path))
        with patch("builtins.input", side_effect=[EOFError]):
            cmds.handle("/model")
        # Aggregate all render calls; model details appear across multiple prints
        all_output = " ".join(
            c[0][0] for c in render.call_args_list
        )
        assert "test-model" in all_output
        assert "https://api.example.com" in all_output
        assert "0.3" in all_output
        assert "0.7" in all_output

    def test_model_switch_keeps_current(self, state_loader, render, exit_fn, tmp_path) -> None:
        """Enter empty choice → no switch."""
        from mgmai.llm.model_config import ModelConfig

        config = ModelConfig(name="deepseek-v4-flash", base_url="https://api.example.com")
        cmds = Commands(state_loader, render, exit_fn, model_config=config,
                        config_dir=str(tmp_path))

        with patch("builtins.input", return_value=""):
            cmds.handle("/model")
        # Should not crash; model unchanged


class TestNonCommandPassthrough:
    """Non-command input returns False for the game loop to handle."""

    def test_normal_text(self, commands) -> None:
        assert commands.handle("look around") is False

    def test_empty_string(self, commands) -> None:
        assert commands.handle("") is False

    def test_whitespace_only(self, commands) -> None:
        assert commands.handle("   ") is False


class TestInventoryCommand:
    """Inventory command: /inv, /inventory, and bare i/inv/inventory."""

    def test_slash_inv_dispatches(self, commands, render) -> None:
        assert commands.handle("/inv") is True
        render.assert_called_once()

    def test_slash_inventory_alias(self, commands, render) -> None:
        assert commands.handle("/inventory") is True
        render.assert_called_once()

    def test_slash_i_alias(self, commands, render) -> None:
        assert commands.handle("/i") is True
        render.assert_called_once()

    def test_bare_i(self, commands, render) -> None:
        assert commands.handle("i") is True
        render.assert_called_once()

    def test_bare_inv(self, commands, render) -> None:
        assert commands.handle("inv") is True
        render.assert_called_once()

    def test_bare_inventory(self, commands, render) -> None:
        assert commands.handle("inventory") is True
        render.assert_called_once()

    def test_bare_i_case_insensitive(self, commands, render) -> None:
        assert commands.handle("I") is True
        render.assert_called_once()

    def test_inv_with_loaded_state(self, state_manager, monkeypatch) -> None:
        """Render inventory with actual state items, using corpus names."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        hard = state_manager.hard_state
        hard.player.inventory = {"rusty_key": 1}
        hard.player.equipped = ["toenail_sword"]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/inv")

        output = "\n".join(rendered)
        assert "Equipped" in output
        assert "Toenail Sword" in output
        assert "Carried" in output
        assert "Rusty Key" in output
        assert "1d6 damage" in output
        assert "toenail_sword" not in output
        assert "rusty_key" not in output

    def test_inv_with_stack_count(self, state_manager, monkeypatch) -> None:
        """Render inventory shows quantity for items with count > 1."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        hard = state_manager.hard_state
        hard.player.inventory = {"rusty_key": 5}

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/inv")

        output = "\n".join(rendered)
        assert "Rusty Key (x5)" in output

    def test_inv_empty(self, state_manager, monkeypatch) -> None:
        """Render inventory when carrying nothing."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        hard = state_manager.hard_state
        hard.player.inventory = {}
        hard.player.equipped = []

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/inv")

        output = "\n".join(rendered)
        assert "carrying nothing" in output

    def test_inv_no_game_loaded(self, render, exit_fn) -> None:
        """Inventory command when no game is loaded shows error."""
        state = MagicMock()
        state.hard_state = None
        state.soft_state = None
        state.corpus = None
        from mgmai.game.commands import Commands
        cmds = Commands(state, render, exit_fn)
        cmds.handle("/inv")
        render.assert_called_once()
        assert "No game loaded" in render.call_args[0][0]

    def test_inv_escapes_markup_in_soft_items(self, state_manager, monkeypatch) -> None:
        """Soft inventory strings (LLM-sourced) must not leak as Rich markup."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", True)
        state_manager.soft_state.soft_inventory = ["evil [red]rock[/red]"]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/inv")

        output = "\n".join(rendered)
        assert "\\[red]" in output
        assert "\\[/red]" in output

    def test_inv_negative_bonus_formatting(self, state_manager, monkeypatch) -> None:
        """Negative AC/attack bonuses render with a minus, not '+-'."""
        from mgmai.models.corpus import EquipBlock
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        hard = state_manager.hard_state
        hard.player.inventory = {}
        sword = state_manager.corpus.entities["toenail_sword"]
        hard.player.equipped = ["toenail_sword"]
        # ac_bonus is a 5e-specific extra, so rebuild the block with extras.
        sword.equip_block = EquipBlock(
            equip_tags=["weapon"],
            damage_expr="1d6",
            hit_bonus=-1,
            ac_bonus=-2,
        )

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/inv")

        output = "\n".join(rendered)
        assert "AC -2" in output
        assert "-1 to hit" in output
        assert "+-" not in output


class TestCharCommand:
    """Character stats command: /c, /char, and bare c/char/sheet."""

    @pytest.fixture
    def char_cmds(self, state_manager, monkeypatch):
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.game.commands import Commands
        rendered: list[str] = []
        return Commands(state_manager, rendered.append, lambda: None), rendered

    def test_slash_c_dispatches(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("/c") is True
        assert "does not use a stats system" in rendered[0]

    def test_slash_char_dispatches(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("/char") is True
        assert "does not use a stats system" in rendered[0]

    def test_slash_sheet_dispatches(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("/sheet") is True
        assert "does not use a stats system" in rendered[0]

    def test_bare_c(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("c") is True
        assert "does not use a stats system" in rendered[0]

    def test_bare_char(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("char") is True
        assert "does not use a stats system" in rendered[0]

    def test_bare_sheet(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("sheet") is True
        assert "does not use a stats system" in rendered[0]

    def test_bare_c_case_insensitive(self, char_cmds) -> None:
        cmds, rendered = char_cmds
        assert cmds.handle("C") is True
        assert "does not use a stats system" in rendered[0]

    def test_no_stats_system(self, state_manager, monkeypatch) -> None:
        """When corpus.stats is None, show a graceful message."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")
        output = "\n".join(rendered)
        assert "does not use a stats system" in output

    def test_no_player_stats(self, state_manager, monkeypatch) -> None:
        """When corpus.stats exists but player.stats is None, show graceful message."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        state_manager.hard_state.player.stats = None
        state_manager.corpus.stats = StatsBlock(
            definitions={"STR": StatDefinition(name="Strength")},
            system="5e",
        )
        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")
        output = "\n".join(rendered)
        assert "No character stats" in output

    def test_with_stats(self, state_manager, monkeypatch) -> None:
        """Full character stats display."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        state_manager.corpus.stats = StatsBlock(
            definitions={
                "STR": StatDefinition(name="Strength"),
                "DEX": StatDefinition(name="Dexterity"),
                "CON": StatDefinition(name="Constitution"),
            },
            system="5e",
        )
        state_manager.hard_state.player.stats = {"STR": 14, "DEX": 12, "CON": 10}
        state_manager.hard_state.player.current_hp = 8
        state_manager.hard_state.player.max_hp = 10
        state_manager.hard_state.player.ac = 12
        state_manager.hard_state.player.proficiency_bonus = 2
        state_manager.hard_state.player.level = 3
        state_manager.hard_state.player.save_proficiencies = ["DEX", "CON"]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")

        output = "\n".join(rendered)
        assert "Stats" in output
        assert "Strength" in output
        assert "14" in output
        assert "+2" in output
        assert "Dexterity" in output
        assert "Constitution" in output
        assert "Combat" in output
        assert "8 / 10" in output
        assert "AC" in output
        assert "Prof" in output
        assert "+2" in output
        assert "Level:  3" in output
        assert "Saves" in output
        assert "DEX" in output
        assert "CON" in output

    def test_with_skill_proficiencies(self, state_manager, monkeypatch) -> None:
        """Character display lists proficient skills with total modifiers."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        state_manager.corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="Dexterity")},
            system="5e",
        )
        state_manager.hard_state.player.stats = {"DEX": 14}
        state_manager.hard_state.player.proficiency_bonus = 2
        state_manager.hard_state.player.skill_proficiencies = ["acrobatics"]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")

        output = "\n".join(rendered)
        assert "Skills" in output
        # DEX 14 -> +2, proficiency +2 -> +4
        assert "Acrobatics (+4)" in output

    def test_no_skills_line_without_proficiencies(self, state_manager, monkeypatch) -> None:
        """No Skills line when the player has no skill proficiencies."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        state_manager.corpus.stats = StatsBlock(
            definitions={"DEX": StatDefinition(name="Dexterity")},
            system="5e",
        )
        state_manager.hard_state.player.stats = {"DEX": 14}

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")

        output = "\n".join(rendered)
        assert "Skills" not in output

    def test_weapon_proficiencies_line(self, state_manager, monkeypatch) -> None:
        """Character display lists weapon proficiencies (categories title-cased)."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        state_manager.corpus.stats = StatsBlock(
            definitions={"STR": StatDefinition(name="Strength")},
            system="5e",
        )
        state_manager.hard_state.player.stats = {"STR": 12}
        state_manager.hard_state.player.weapon_proficiencies = [
            "simple", "martial", "longsword",
        ]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")

        output = "\n".join(rendered)
        assert "Weapons" in output
        assert "Simple" in output
        assert "Martial" in output
        assert "longsword" in output

    def test_weapon_proficiencies_clause_line(self, state_manager, monkeypatch) -> None:
        """Clauses render as 'Category (prop/prop)'."""
        monkeypatch.setattr("mgmai.game.display.RICH_AVAILABLE", False)
        from mgmai.models.corpus import StatsBlock, StatDefinition
        from mgmai.models.hard_state import WeaponProfClause
        state_manager.corpus.stats = StatsBlock(
            definitions={"STR": StatDefinition(name="Strength")},
            system="5e",
        )
        state_manager.hard_state.player.stats = {"STR": 12}
        state_manager.hard_state.player.weapon_proficiencies = [
            "simple",
            WeaponProfClause(category="martial", properties=["finesse", "light"]),
        ]

        from mgmai.game.commands import Commands
        rendered: list[str] = []
        cmds = Commands(state_manager, rendered.append, lambda: None)
        cmds.handle("/c")

        output = "\n".join(rendered)
        assert "Weapons" in output
        assert "Simple" in output
        assert "Martial (finesse/light)" in output

    def test_no_game_loaded(self, render, exit_fn) -> None:
        """Char command when no game is loaded shows error."""
        state = MagicMock()
        state.hard_state = None
        state.soft_state = None
        state.corpus = None
        from mgmai.game.commands import Commands
        cmds = Commands(state, render, exit_fn)
        cmds.handle("/c")
        render.assert_called_once()
        assert "No game loaded" in render.call_args[0][0]
