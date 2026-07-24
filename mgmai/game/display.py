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

from typing import Any

from mgmai.engine.utils import is_exit_visible

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule

    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class Display:
    def __init__(self):
        if RICH_AVAILABLE:
            self._console = Console(highlight=False)

    # --- generic output ---

    def print(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print(text)
        else:
            print(text)

    def rule(self, title: str = "") -> None:
        if RICH_AVAILABLE:
            self._console.print(Rule(title))
        elif title:
            print(f"--- {title} ---")

    # --- game screens ---

    def render_intro(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        adv = corpus.adventure

        title = adv.title
        intro = adv.introduction

        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(Rule(characters="="))
            self._console.print()
            panel = Panel(
                f"[bold italic]{title}[/bold italic]\n\n{intro}",
                border_style="bold cyan",
                padding=(1, 2),
            )
            self._console.print(panel)
            self._console.print()
            if adv.credits:
                c = adv.credits
                parts = []
                if c.author:
                    parts.append(f"Author: {c.author}")
                if c.source:
                    parts.append(f"Source: {c.source}")
                if c.license:
                    parts.append(f"License: {c.license}")
                self._console.print(
                    Text(" | ".join(parts), style="dim italic")
                )
            self._console.print()
            self._console.print(Rule(characters="="))
            self._console.print()
            self._render_room(state_loader)
        else:
            print()
            print("=" * 60)
            print(title)
            print()
            print(intro)
            print()
            print("=" * 60)
            print()
            self._render_room(state_loader)

    def render_narration(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print()
            panel = Panel(
                Markdown(text),
                border_style="magenta",
                padding=(0, 1),
            )
            self._console.print(panel)
            self._console.print()
        else:
            print()
            print(text)
            print()

    def render_goodbye(self) -> None:
        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(
                Panel(
                    "Thanks for playing!",
                    border_style="dim cyan",
                )
            )
        else:
            print()
            print("Thanks for playing!")

    def render_error(self, text: str) -> None:
        if RICH_AVAILABLE:
            self._console.print(f"[bold red]Error:[/bold red] {text}")
        else:
            print(f"Error: {text}")

    def render_status(self, state_loader: Any) -> None:
        hard = state_loader.hard_state
        if hard is None:
            return

        # Combat status takes priority
        if hard.combat is not None and hard.combat.active:
            self._render_combat_status(hard, state_loader)
            return

        loc = hard.player.location
        turn = hard.turn_count
        active_flags = [k for k, v in hard.flags.items() if v]

        if RICH_AVAILABLE:
            parts = [f"[dim]Turn {turn}[/dim]"]
            parts.append(f"[dim]Location:[/dim] [cyan]{loc}[/cyan]")
            if active_flags:
                parts.append(f"[dim]Flags:[/dim] {', '.join(active_flags)}")
            self._console.print(f"  {' | '.join(parts)}")
        else:
            parts = [f"Turn {turn}", f"Location: {loc}"]
            if active_flags:
                parts.append(f"Flags: {', '.join(active_flags)}")
            print(f"  {' | '.join(parts)}")

    def _render_combat_status(self, hard: Any, state_loader: Any) -> None:
        """Render a compact combat status panel between turns.

        Layout adapts to the terminal width: narrow terminals get a
        single stacked column; wide ones (>= 100 cols) get a two-column
        Party-vs-Enemies layout with a wider HP bar.  Rows show active
        status effects and, for enemies, damage mitigations the party has
        already discovered by landing hits (derived from the combat log,
        so nothing the player hasn't learned is leaked).
        """
        corpus = state_loader.corpus
        combat = hard.combat

        if RICH_AVAILABLE:
            width = self._console.width
        else:
            import shutil
            width = shutil.get_terminal_size().columns
        wide = width >= 100
        bar_width = 14 if wide else 10

        def _hp_bar(current: int, max_hp: int) -> str:
            if max_hp <= 0:
                return " " * bar_width
            filled = max(0, min(bar_width, round(current / max_hp * bar_width)))
            empty = bar_width - filled
            return "█" * filled + "░" * empty

        effect_defs = corpus.effective_status_effects() if corpus else {}

        def _status_effects_text(status_effects: dict) -> str:
            """e.g. 'poisoned 2, stunned 1' (StatusEffectDef.name when set)"""
            def _label(c: str) -> str:
                cdef = effect_defs.get(c)
                return cdef.name if cdef is not None and cdef.name else c
            return ", ".join(f"{_label(c)} {n}" for c, n in status_effects.items())

        def _row_data(cid: str) -> dict:
            # Positioning: engagement partners (display names) and the
            # pending impede flag, shown as row markers.
            engaged_with = sorted(
                _cid_name(p[1] if p[0] == cid else p[0])
                for p in (combat.engagement or [])
                if cid in p
            )
            impeded = cid in (combat.impeded or [])
            if cid == "player":
                return {
                    "name": "Player",
                    "hp": hard.player.current_hp or 0,
                    "max_hp": hard.player.max_hp or 0,
                    "status_effects": dict(hard.player.status_effects or {}),
                    "fled": False,
                    "engaged_with": engaged_with,
                    "impeded": impeded,
                }
            entity = corpus.entities.get(cid) if corpus else None
            state = hard.entity_states.get(cid, {})
            return {
                "name": (entity.name or cid) if entity else cid,
                "hp": int(state.get("current_hp") or 0),
                "max_hp": (entity.combat.hp if entity and entity.combat else 0),
                "status_effects": dict(state.get("status_effects") or {}),
                "fled": bool(state.get("fled")),
                "engaged_with": engaged_with,
                "impeded": impeded,
            }

        def _cid_name(pid: str) -> str:
            """Display name for a combatant id (engagement partners)."""
            if pid == "player":
                return "Player"
            ent = corpus.entities.get(pid) if corpus else None
            return (ent.name or pid) if ent else pid

        def _positioning_text(d: dict) -> str:
            """e.g. '⚔ Goblin, Wolf (impeded)' — engagement partners and
            the pending impede flag."""
            parts: list[str] = []
            if d["engaged_with"]:
                parts.append(f"⚔ {', '.join(d['engaged_with'])}")
            if d["impeded"]:
                parts.append("(impeded)")
            return " ".join(parts)

        # Damage mitigations the party has discovered by landing hits on
        # each enemy (damage type -> mitigation), taken from the combat
        # log so nothing unlearned is revealed.
        discovered: dict[str, dict[str, str]] = {}
        for entry in combat.log or []:
            target = getattr(entry, "target", None)
            mitigation = getattr(entry, "mitigation", None)
            damage_type = getattr(entry, "damage_type", "") or ""
            if target and target != "player" and mitigation and damage_type:
                discovered.setdefault(target, {})[damage_type] = mitigation

        def _mitigation_text(cid: str) -> str:
            """e.g. 'resists piercing; vulnerable to fire'"""
            parts: list[str] = []
            for damage_type, mitigation in discovered.get(cid, {}).items():
                if mitigation == "resisted":
                    parts.append(f"resists {damage_type}")
                elif mitigation == "vulnerable":
                    parts.append(f"vulnerable to {damage_type}")
                elif mitigation == "immune":
                    parts.append(f"immune to {damage_type}")
            return "; ".join(parts)

        def _status_tag(d: dict) -> str:
            if d["fled"]:
                return "(fled)"
            if d["hp"] <= 0:
                return "†"
            return ""

        # Current actor in the initiative order.  The panel renders while
        # awaiting the player's command, so this is normally the player.
        current_cid = None
        if 0 <= combat.current_index < len(combat.initiative_order):
            current_cid = combat.initiative_order[combat.current_index]

        party = [
            c for c in combat.combatants
            if c == "player" or c in combat.allies
        ]
        enemies = [c for c in combat.combatants if c not in party]

        footer = self._combat_player_footer(hard, corpus, combat)

        if RICH_AVAILABLE:
            from rich.console import Group
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text

            init_parts: list[str] = []
            for c in combat.initiative_order:
                label = c
                if c == current_cid:
                    label = f"[bold underline]{label}[/bold underline]"
                if c == "player":
                    label = f"[cyan]{label}[/cyan]"
                init_parts.append(label)
            initiative_str = " → ".join(init_parts)

            def _rich_row(cid: str) -> str:
                d = _row_data(cid)
                name = f"{d['name']} {_status_tag(d)}".strip()
                padded = f"{name:<18}"
                if cid == "player":
                    padded = f"[bold bright_white]{padded}[/bold bright_white]"
                line = (
                    f"{padded} HP {_hp_bar(d['hp'], d['max_hp'])} "
                    f"{d['hp']}/{d['max_hp']}"
                )
                if d["status_effects"]:
                    line += f" [yellow]\\[{_status_effects_text(d['status_effects'])}][/yellow]"
                mit = _mitigation_text(cid)
                if mit:
                    line += f" [dim]({mit})[/dim]"
                pos = _positioning_text(d)
                if pos:
                    line += f" [dim]{pos}[/dim]"
                if d["hp"] <= 0 or d["fled"]:
                    line = f"[dim]{line}[/dim]"
                return line

            header = Text.from_markup(
                f"[bold]Combat: Round {combat.round_number}[/bold]\n"
                f"[dim]Initiative:[/dim] {initiative_str}"
            )
            footer_text = Text.from_markup(
                f"[dim]{footer}[/dim]\n[dim italic]It's your turn.[/dim italic]"
            )
            party_lines = ["[bold]Party[/bold]"] + [_rich_row(c) for c in party]
            enemy_lines = ["[bold]Enemies[/bold]"] + [_rich_row(c) for c in enemies]
            if wide:
                grid = Table.grid(padding=(0, 0, 0, 4))
                grid.add_column()
                grid.add_column()
                grid.add_row(
                    Text.from_markup("\n".join(party_lines)),
                    Text.from_markup("\n".join(enemy_lines)),
                )
                body: Any = grid
            else:
                lines = party_lines + [""] + enemy_lines
                body = Text.from_markup("\n".join(lines))

            self._console.print()
            self._console.print(
                Panel(
                    Group(header, "", body, "", footer_text),
                    border_style="red",
                    padding=(0, 1),
                )
            )
            self._console.print()
        else:
            print()
            print(f"=== Combat: Round {combat.round_number} ===")
            initiative_str = " -> ".join(
                f"»{c}«" if c == current_cid else c
                for c in combat.initiative_order
            )
            print(f"Initiative: {initiative_str}")
            print()

            def _plain_row(cid: str) -> str:
                d = _row_data(cid)
                name = f"{d['name']} {_status_tag(d)}".strip()
                line = (
                    f"  {name:<18} HP {_hp_bar(d['hp'], d['max_hp'])} "
                    f"{d['hp']}/{d['max_hp']}"
                )
                if d["status_effects"]:
                    line += f" [{_status_effects_text(d['status_effects'])}]"
                mit = _mitigation_text(cid)
                if mit:
                    line += f" ({mit})"
                pos = _positioning_text(d)
                if pos:
                    line += f" {pos}"
                return line

            print("Party:")
            for cid in party:
                print(_plain_row(cid))
            print()
            print("Enemies:")
            for cid in enemies:
                print(_plain_row(cid))
            print()
            print(f"  {footer}")
            print("  It's your turn.")
            print()

    def _combat_player_footer(self, hard: Any, corpus: Any, combat: Any) -> str:
        """One-line summary of the player's combat-relevant resources:
        AC, equipped weapon, ability uses left, and consumables."""
        parts: list[str] = []
        try:
            from mgmai.engine.combat import compute_player_ac
            ac = compute_player_ac(hard, corpus) if corpus else hard.player.ac
        except Exception:  # noqa: BLE001 — display must never crash a turn
            ac = hard.player.ac
        if ac is not None:
            parts.append(f"AC {ac}")
        if corpus:
            for item_id in hard.player.equipped:
                entity = corpus.entities.get(item_id)
                if (
                    entity
                    and entity.equip_block
                    and "weapon" in entity.equip_block.equip_tags
                ):
                    dmg = entity.equip_block.damage_expr + (
                        f" {entity.equip_block.damage_type}"
                        if entity.equip_block.damage_type
                        else ""
                    )
                    parts.append(f"{entity.name or item_id} ({dmg})")
                    break
            for aid in hard.player.abilities:
                ability = corpus.abilities.get(aid)
                if ability is None:
                    continue
                if ability.uses_per_combat < 0:
                    parts.append(ability.name)
                else:
                    used = (combat.ability_uses.get("player", {}) or {}).get(aid, 0)
                    remaining = ability.uses_per_combat - used
                    parts.append(f"{ability.name} {remaining}/{ability.uses_per_combat}")
            items: list[str] = []
            for item_id, count in (hard.player.inventory or {}).items():
                if count <= 0:
                    continue
                entity = corpus.entities.get(item_id)
                if entity is not None and entity.consumable:
                    items.append(f"{entity.name or item_id} x{count}")
            parts.append("Items: " + (", ".join(items) if items else "none"))
        return " · ".join(parts)
    def _render_character_sheet(self, state_loader: Any) -> None:
        hard = state_loader.hard_state
        corpus = state_loader.corpus
        if hard is None or corpus is None:
            return
        stats = hard.player.stats
        if stats is None or corpus.stats is None:
            return

        from mgmai.engine.stat_checks import compute_modifier

        stat_entries = sorted(stats.items())
        lines: list[str] = []

        # Layout: 3 columns -> 2 rows for 6 stats
        for i in range(0, len(stat_entries), 3):
            row_stats = stat_entries[i : i + 3]
            pair_parts = []
            for key, val in row_stats:
                mod = compute_modifier(val, corpus.stats.system)
                sign = "+" if mod >= 0 else ""
                pair_parts.append(f"{key} {val:>2} ({sign}{mod})")
            lines.append("   ".join(pair_parts))

        if RICH_AVAILABLE:
            body = "\n".join(lines)
            panel = Panel(
                body,
                title="Character Sheet",
                border_style="cyan",
                padding=(0, 1),
            )
            self._console.print(panel)
        else:
            print()
            print("┌─ Character Sheet ───────────────────────┐")
            for line in lines:
                print(f"│ {line.ljust(30)}│")
            print("└───────────────────────────────────┘")
            print()

    def render_game_over(self, result: Any) -> None:
        go_type = getattr(result, "type", "unknown")
        narrative = getattr(result, "narrative", None) or ""
        trigger = getattr(result, "trigger", "")

        if go_type == "win":
            title = "🎉 Victory!"
            style = "bold green"
            border = "green"
        elif go_type == "lose":
            title = "💀 Defeat"
            style = "bold red"
            border = "red"
        else:
            title = f"Game Over ({go_type})"
            style = "bold yellow"
            border = "yellow"

        text_parts = [f"[{style}]{title}[/{style}]"]
        if trigger:
            text_parts.append(f"[dim]Trigger:[/dim] {trigger}")
        if narrative:
            text_parts.append(f"\n{narrative}")

        if RICH_AVAILABLE:
            self._console.print()
            self._console.print(
                Panel(
                    "\n".join(text_parts),
                    border_style=border,
                    padding=(1, 2),
                )
            )
            self._console.print()
        else:
            print()
            print(title)
            if trigger:
                print(f"Trigger: {trigger}")
            if narrative:
                print(narrative)
            print()

    # --- helpers ---

    @staticmethod
    def format_exits(room: Any, indent: int = 0) -> str:
        """Format a room's visible exits as a string suitable for appending
        to narration.  ``room`` is a BriefingRoom or a corpus Room.

        Returns an empty string if there are no visible exits.
        """
        exits: list = getattr(room, "exits_available", None)
        if exits is None:
            exits = getattr(room, "exits", [])

        visible: list = []
        for e in exits:
            hidden = getattr(e, "hidden", False)
            if hidden:
                continue
            direction = getattr(e, "direction", "")
            one_way = getattr(e, "one_way", False)
            label = f"* {direction}"
            if one_way:
                label += " (one-way)"
            visible.append(label)

        if not visible:
            return ""

        prefix = " " * indent
        lines = [f"\n\n{prefix}**Exits:**"]
        for v in visible:
            lines.append(f"{prefix}{v}")
        return "\n".join(lines)

    def _render_room(self, state_loader: Any) -> None:
        corpus = state_loader.corpus
        hs = state_loader.hard_state
        room = corpus.rooms.get(hs.player.location)
        if room is None:
            self.print(f"[Unknown room: {hs.player.location}]")
            return

        visible_exits = []
        for e in room.exits:
            if not is_exit_visible(e, hs, state_loader.soft_state, corpus):
                continue
            visible_exits.append(e)

        if RICH_AVAILABLE:
            lines = [f"[bold bright_white]{room.name}[/bold bright_white]", ""]
            lines.append(room.description)
            lines.append("")

            if visible_exits:
                exit_lines = [
                    f"* {e.direction}" + (" [dim](one-way)[/dim]" if e.one_way else "")
                    for e in visible_exits
                ]
                lines.append("[bold]Exits:[/bold]")
                lines.extend(exit_lines)
            else:
                lines.append("[bold]Exits:[/bold] (none visible)")

            self._console.print()
            panel = Panel(
                "\n".join(lines),
                border_style="green",
                padding=(0, 1),
            )
            self._console.print(panel)
            self._console.print()
        else:
            print()
            print(f"--- {room.name} ---")
            print()
            print(room.description)
            print()
            if visible_exits:
                print("Exits:")
                for e in visible_exits:
                    parts = [f"  {e.direction}"]
                    if e.one_way:
                        parts.append("(one-way)")
                    print("  ".join(parts))
            print()
