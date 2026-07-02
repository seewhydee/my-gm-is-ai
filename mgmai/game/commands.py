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

from __future__ import annotations

import getpass
import logging
from pathlib import Path
from typing import Any, Callable

from mgmai.llm.model_config import (
    get_known_model_labels,
    get_model_config,
    load_custom_models,
)
from mgmai.logging import get_level, set_level

_DEBUG_LEVEL = logging.DEBUG

try:
    from rich.markup import escape as _rich_escape

    import mgmai.game.display as _display

    def _escape(text: str) -> str:
        return _rich_escape(text) if _display.RICH_AVAILABLE else text
except ImportError:
    def _escape(text: str) -> str:
        return text

_BARE_INV_WORDS = frozenset({"i", "inv", "inventory"})
_BARE_CHAR_WORDS = frozenset({"c", "char", "character", "sheet"})

class Commands:
    def __init__(
        self,
        state_loader: Any,
        render: Callable[[str], None],
        exit_fn: Callable[[], None],
        debug: bool = False,
        on_load: Callable[[], None] | None = None,
        config_dir: str | Path | None = None,
        model_config: object | None = None,
        on_model_change: Callable[[str, object], None] | None = None,
    ):
        self._state = state_loader
        self._render = render
        self._exit = exit_fn
        self._debug = debug
        self._on_load = on_load
        self._config_dir = Path(config_dir) if config_dir else None
        self._model_config = model_config
        self._on_model_change = on_model_change

    @property
    def debug(self) -> bool:
        return self._debug

    def handle(self, raw: str) -> bool:
        stripped = raw.strip()
        if not stripped:
            return False

        if stripped.startswith("/"):
            parts = stripped[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            handler = {
                "help": self._cmd_help,
                "h": self._cmd_help,
                "exit": self._cmd_exit,
                "quit": self._cmd_exit,
                "q": self._cmd_exit,
                "save": self._cmd_save,
                "load": self._cmd_load,
                "debug": self._cmd_debug,
                "model": self._cmd_model,
                "i": self._cmd_inv,
                "inv": self._cmd_inv,
                "inventory": self._cmd_inv,
                "c": self._cmd_char,
                "char": self._cmd_char,
                "character": self._cmd_char,
                "sheet": self._cmd_char,
            }.get(cmd)

            if handler is None:
                return False

            handler(arg)
            return True

        if stripped.lower() in _BARE_INV_WORDS:
            self._cmd_inv("")
            return True

        if stripped.lower() in _BARE_CHAR_WORDS:
            self._cmd_char("")
            return True

        return False

    # --- command implementations ---

    def _cmd_help(self, _: str) -> None:
        text = """\
[bold]Available Commands[/bold]

  /help, /h             Show this help
  /exit, /quit, /q      Exit the game
  /save [filename]      Save game (default: save.json)
  /load <filename>      Load a saved game
  /debug                Toggle debug mode (shows GMBriefing/EngineResult)
  /model                Show current model details and switch model

[bold]Shortcuts[/bold]
  Classic interactive-fiction abbreviations are expanded automatically:
    n, s, e, w, u, d     Go in that direction
    x <target>           Examine <target> (x alone = look around)
    l                    Look around
    i, inv               Show inventory (engine-level, no turn used)
    c, char              Show character stats (engine-level, no turn used)
    z                    Wait
    t <npc>              Talk to <npc>

[bold]Tips[/bold]
  Type natural language to describe what your character does.
  The GM will interpret your intent and narrate the outcome.
  e.g. "look around", "what happened?"
  Use /i, /c, i, or c for free (no-turn) inventory or stats display.
  Use "check my inventory" if you want narrated commentary from the GM.
"""
        self._render(text)

    def _cmd_exit(self, _: str) -> None:
        self._exit()

    def _resolve_save_path(self, filename: str) -> Path:
        """Resolve a save filename to a path.

        Absolute paths are returned as-is.  Relative paths are placed in
        the config directory's ``saves/<adventure>/`` folder.
        """
        path = Path(filename)
        if path.is_absolute():
            return path
        return self._get_saves_dir() / filename

    def _get_saves_dir(self) -> Path:
        from mgmai.config import get_saves_dir

        adv_name = self._adventure_name()
        return get_saves_dir(adv_name, self._config_dir)

    def _adventure_name(self) -> str:
        if getattr(self._state, "_adventure_dir", None):
            return self._state._adventure_dir.name
        return "game"

    def _cmd_save(self, arg: str) -> None:
        if not self._state.loaded:
            self._render("[red]No game to save.[/red]")
            return
        filename = arg.strip() or "save.json"
        try:
            save_path = self._resolve_save_path(filename)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            self._state.save(str(save_path))
            self._render(f"[green]Game saved to {save_path}[/green]")
        except Exception as e:
            self._render(f"[red]Save failed: {e}[/red]")

    def _cmd_load(self, arg: str) -> None:
        filename = arg.strip()
        if not filename:
            self._render("[red]Usage: /load <filename>[/red]")
            return

        load_path = Path(filename)
        if not load_path.is_absolute():
            load_path = self._get_saves_dir() / filename

        try:
            adv_path = self._state.load_save(str(load_path))
            self._render(
                f"[green]Game loaded from {load_path} "
                f"(adventure: {adv_path})[/green]"
            )
            if self._on_load is not None:
                self._on_load()
        except FileNotFoundError:
            self._render(f"[red]Save file not found: {load_path}[/red]")
        except Exception as e:
            self._render(f"[red]Load failed: {e}[/red]")

    def _cmd_debug(self, _: str) -> None:
        if get_level() <= _DEBUG_LEVEL:
            set_level("INFO")
            self._debug = False
            self._render("[yellow]Debug mode: OFF[/yellow]")
        else:
            set_level("DEBUG")
            self._debug = True
            self._render("[yellow]Debug mode: ON[/yellow]")

    def _cmd_model(self, _: str) -> None:
        self._render("\n[bold]Current Model[/bold]\n")

        if self._model_config is None:
            self._render("  [dim]Model configuration not available.[/dim]")
            return

        mc = self._model_config
        self._render(f"  Name:               [cyan]{mc.name}[/cyan]")
        if mc.label and mc.label != mc.name:
            self._render(f"  Label:              {mc.label}")
        self._render(f"  Base URL:           [dim]{mc.base_url}[/dim]")

        rt = "API default" if mc.ruling_temperature is None else str(mc.ruling_temperature)
        pt = "API default" if mc.prose_temperature is None else str(mc.prose_temperature)
        self._render(f"  Ruling temperature: {rt}")
        self._render(f"  Prose temperature:  {pt}")

        self._render(f"  JSON mode:          {'on' if mc.supports_json_mode else 'off'}")
        self._render(f"  Request timeout:    {mc.request_timeout:.0f}s")
        self._render(f"  Max tokens (ruling): {mc.ruling_max_tokens}")
        self._render(f"  Max tokens (prose):  {mc.prose_max_tokens}")

        if mc.extra_body:
            import json
            self._render(f"  extra_body:         [dim]{json.dumps(mc.extra_body)}[/dim]")

        # --- Model switching ---
        from mgmai.config import (
            load_app_config,
            load_credentials,
            save_app_config,
            save_credentials,
        )

        app_config = load_app_config(self._config_dir)
        credentials = load_credentials(self._config_dir)
        custom_models = load_custom_models(self._config_dir)

        current_model = app_config.model_name or "deepseek-v4-flash"

        self._render("")
        known = get_known_model_labels(custom_models=custom_models)
        known_names = list(known.keys())
        self._render("[bold]Switch model[/bold]")
        self._render("  (Enter to keep current)\n")
        for i, (name, label) in enumerate(known.items(), 1):
            cfg = get_model_config(name, custom_models=custom_models)
            marker = " [dim](current)[/dim]" if name == current_model else ""
            self._render(f"  {i}. [cyan]{label}[/cyan]{marker} — {cfg.base_url}")
        self._render(f"  {len(known) + 1}. [yellow]Custom model...[/yellow]")

        try:
            choice = input("\n  Select model number: ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        if not choice:
            return

        try:
            idx = int(choice)
            if 1 <= idx <= len(known):
                new_model = known_names[idx - 1]
            elif idx == len(known) + 1:
                new_model = input("  Enter model name: ").strip()
                if not new_model:
                    self._render("[red]Model name cannot be empty.[/red]")
                    return
            else:
                self._render("[red]Invalid selection.[/red]")
                return
        except ValueError:
            new_model = choice

        # --- API key ---
        current_api = credentials.api_key or "(not set)"
        if current_api and current_api != "(not set)":
            current_api = current_api[:4] + "..." + current_api[-4:] if len(current_api) > 8 else "***"

        self._render(f"\n[bold]API Key[/bold]  [dim](current: {current_api})[/dim]")
        self._render("  (leave blank to keep current)")
        try:
            new_key = getpass.getpass("  Enter API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        if new_key:
            credentials.api_key = new_key
            try:
                save_credentials(credentials, self._config_dir)
                self._render("  [green]API key saved.[/green]")
            except OSError as e:
                self._render(f"  [yellow]Could not save API key: {e}[/yellow]")

        # --- Base URL ---
        try:
            model_cfg = get_model_config(new_model, custom_models=custom_models)
            default_url = model_cfg.base_url
        except ValueError:
            default_url = ""

        self._render(f"\n[bold]Base URL[/bold]")
        if default_url:
            self._render(f"  Default: [dim]{default_url}[/dim]")
            self._render("  (leave blank to use default)")
        else:
            self._render("  [yellow]A base URL is required for this model.[/yellow]")
        try:
            new_url = input("  Enter base URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            self._render("")
            return

        if not new_url and not default_url:
            self._render("[red]Base URL cannot be empty for a custom model.[/red]")
            return

        # --- Save config and hot-swap ---
        app_config.model_name = new_model
        app_config.base_url = new_url if new_url else default_url
        try:
            save_app_config(app_config, self._config_dir)
        except OSError as e:
            self._render(f"\n[red]Could not save config: {e}[/red]")
            return

        self._render(f"\n[green]Switched to [cyan]{new_model}[/cyan][/green]")

        if self._on_model_change:
            effective_url = new_url if new_url else None
            new_cfg = get_model_config(new_model, base_url=effective_url,
                                       custom_models=custom_models)
            self._on_model_change(credentials.api_key, new_cfg)
            self._model_config = new_cfg

    def _cmd_inv(self, _: str) -> None:
        hard = self._state.hard_state
        soft = self._state.soft_state
        corpus = self._state.corpus

        if hard is None or soft is None or corpus is None:
            self._render("[red]No game loaded.[/red]")
            return

        def _item_label(item_id: str) -> str:
            entity = corpus.entities.get(item_id)
            if entity is None:
                return _escape(item_id)
            return _escape(entity.name or item_id)

        lines: list[str] = []
        carried = list(hard.player.inventory)

        if hard.player.equipped:
            lines.append("[bold]Equipped[/bold]")
            for item_id in hard.player.equipped:
                entity = corpus.entities.get(item_id)
                eb = entity.equip_block if entity else None

                tags_str = ""
                if eb and eb.equip_tags:
                    tags_str = f" [dim]({', '.join(eb.equip_tags)})[/dim]"
                lines.append(f"  [cyan]{_item_label(item_id)}[/cyan]{tags_str}")

                if eb:
                    summary = eb.effects_summary()
                    if summary:
                        lines.append(f"    [dim]{_escape(summary)}[/dim]")
                if entity and entity.description:
                    lines.append(f"    [dim italic]{_escape(entity.description)}[/dim italic]")
            lines.append("")

        if carried:
            lines.append("[bold]Carried[/bold]")
            for item_id in carried:
                entity = corpus.entities.get(item_id)
                lines.append(f"  {_item_label(item_id)}")
                if entity and entity.description:
                    lines.append(f"    [dim italic]{_escape(entity.description)}[/dim italic]")
            lines.append("")

        if soft.soft_inventory:
            lines.append("[bold]Pockets / Misc[/bold]")
            for s in soft.soft_inventory:
                lines.append(f"  [dim]{_escape(s)}[/dim]")
            lines.append("")

        if not hard.player.equipped and not carried and not soft.soft_inventory:
            self._render("[dim]You are carrying nothing.[/dim]")
            return

        self._render("\n".join(lines))

    def _cmd_char(self, _: str) -> None:
        hard = self._state.hard_state
        corpus = self._state.corpus

        if hard is None or corpus is None:
            self._render("[red]No game loaded.[/red]")
            return

        if corpus.stats is None:
            self._render("[dim]This adventure does not use a stats system.[/dim]")
            return

        if hard.player.stats is None:
            self._render("[dim]No character stats defined.[/dim]")
            return

        from mgmai.engine.stat_checks import compute_modifier
        from mgmai.engine.combat import compute_player_ac, get_player_max_hp

        stats = hard.player.stats
        system = corpus.stats.system
        stat_defs = corpus.stats.definitions

        lines: list[str] = []

        # --- Stats grid ---
        stat_entries = sorted(stats.items(), key=lambda kv: kv[0])
        lines.append("[bold]Stats[/bold]")
        for i in range(0, len(stat_entries), 3):
            row_stats = stat_entries[i : i + 3]
            pair_parts = []
            for key, val in row_stats:
                mod = compute_modifier(val, system)
                sign = "+" if mod >= 0 else ""
                stat_name = stat_defs.get(key)
                label = stat_name.name if stat_name else key
                pair_parts.append(f"{label}: {val:>2} ({sign}{mod})")
            lines.append("  " + "   ".join(pair_parts))
        lines.append("")

        # --- Combat ---
        lines.append("[bold]Combat[/bold]")
        if hard.player.current_hp is not None:
            max_hp = hard.player.max_hp or get_player_max_hp(hard)
            lines.append(f"  HP:     {hard.player.current_hp} / {max_hp}")
        ac = compute_player_ac(hard, corpus)
        base_ac = hard.player.ac or 10
        if ac != base_ac:
            lines.append(f"  AC:     {ac} (base {base_ac}, gear +{ac - base_ac})")
        else:
            lines.append(f"  AC:     {ac}")
        prof = hard.player.proficiency_bonus or 2
        lines.append(f"  Prof:   +{prof}")
        lines.append(f"  Level:  {hard.player.level}")
        if hard.player.save_proficiencies:
            saves = ", ".join(hard.player.save_proficiencies)
            lines.append(f"  Saves:  {saves}")

        # --- Effective stats (only if gear changes them) ---
        from mgmai.engine.combat import compute_effective_stats
        effective = compute_effective_stats(hard, corpus)
        if effective and effective != hard.player.stats:
            lines.append("")
            lines.append("[bold]Effective (with gear)[/bold]")
            effective_entries = sorted(effective.items(), key=lambda kv: kv[0])
            for i in range(0, len(effective_entries), 3):
                row_stats = effective_entries[i : i + 3]
                pair_parts = []
                for key, val in row_stats:
                    mod = compute_modifier(val, system)
                    sign = "+" if mod >= 0 else ""
                    base_val = hard.player.stats.get(key, val)
                    if val != base_val:
                        delta = val - base_val
                        delta_sign = "+" if delta >= 0 else ""
                        pair_parts.append(f"{key}: {val} ({sign}{mod}) [dim]({delta_sign}{delta})[/dim]")
                    else:
                        pair_parts.append(f"{key}: {val} ({sign}{mod})")
                lines.append("  " + "   ".join(pair_parts))

        self._render("\n".join(lines))
