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

"""Rest mode — the LLM-free bookkeeping UI entered after a rest resolves.

Rest mode is a **single-step, menu-driven** controller: each call to
:meth:`RestMode.handle` processes one line of input and returns the text
to display next.  It never calls ``input()`` — the game loop (REPL or
:class:`~mgmai.game.headless.HeadlessSession`) feeds it one line at a
time, so headless tests and future non-terminal front-ends drive it the
same way as a human at a terminal.

Mutations go through the deterministic engine helpers in
:mod:`mgmai.engine.rest_helpers` (``spend_hit_die`` /
``set_prepared_spells``); no LLM is called and no turn is consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mgmai.engine.rest_helpers import set_prepared_spells, spend_hit_die

if TYPE_CHECKING:
    from mgmai.models.actions import EngineResult
    from mgmai.models.corpus import ModuleCorpus
    from mgmai.models.hard_state import HardGameState


def _ordinal(n: int) -> str:
    """English ordinal suffix: 1st, 2nd, 3rd, …, 11th, 21st, …"""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


@dataclass
class RestMenuSnapshot:
    """Read-only snapshot of the rest menu for button-based front-ends.

    ``options`` lists the choices accepted by ``handle(str(index))`` in
    numbering order (1-based).  In the ``prepare`` state they are the
    spellbook entries (toggle buttons); ``prepared`` holds the working
    selection so a button UI can mark toggles without parsing menu
    text.  Confirm is always ``handle("0")``.  The ``exited`` state is
    the post-"Done" condition: no menu remains and the front-end
    should tear its keyboard down.
    """

    kind: str            # "short" | "long"
    state: str           # "top" | "prepare" | "spend" | "exited"
    summary: str         # rest result summary
    status_line: str     # HP / hit dice / slots
    feedback: str
    options: list[str] = field(default_factory=list)
    prepared: list[str] = field(default_factory=list)


class RestMode:
    """Modal controller for post-rest bookkeeping.

    Built when a ``rest`` action resolves successfully; cleared when the
    player chooses *done*.  The controller holds a working copy of the
    prepared-spell selection (``_prepared``) so toggles are reversible
    until confirmed.
    """

    def __init__(
        self,
        kind: str,
        result: EngineResult,
        hard: HardGameState,
        corpus: ModuleCorpus,
    ) -> None:
        self.kind = kind
        self._hard = hard
        self._corpus = corpus
        self._summary = result.message or f"{kind.title()} rest complete."
        self._state = "top"
        # Working copy of the prepared selection.  Drop any prepared ID
        # that is not in the spellbook (only possible from a pre-invalid
        # save/char-sheet, which the validator only warns about): keeping
        # it would soft-lock the menu, since it cannot be toggled off and
        # confirm would reject it forever.
        spellbook = hard.player.spellbook
        self._prepared: list[str] = [
            a for a in hard.player.abilities if not spellbook or a in spellbook
        ]
        self._exited = False
        # Feedback from the most recent handle() step (validation
        # errors, spend results); surfaced via menu() snapshots.
        self._feedback = ""

    @property
    def exited(self) -> bool:
        return self._exited

    def initial_text(self) -> str:
        """The entry summary + top menu (rendered when rest mode starts)."""
        return self._top_menu()

    def menu(self) -> RestMenuSnapshot:
        """Structured snapshot of the current menu (for button UIs)."""
        if self._exited:
            return RestMenuSnapshot(
                kind=self.kind, state="exited", summary=self._summary,
                status_line=self._status_line(), feedback=self._feedback,
            )
        if self._state == "prepare":
            spellbook = self._hard.player.spellbook
            return RestMenuSnapshot(
                kind=self.kind, state="prepare", summary=self._summary,
                status_line=self._status_line(), feedback=self._feedback,
                options=[self._ability_name(aid) for aid in spellbook],
                prepared=list(self._prepared),
            )
        if self._state == "spend":
            options = ["Spend another hit die", "Done"]
        else:
            options = self._top_options()
        return RestMenuSnapshot(
            kind=self.kind, state=self._state, summary=self._summary,
            status_line=self._status_line(), feedback=self._feedback,
            options=list(options),
        )

    def handle(self, line: str) -> str:
        """Process one input line; return the text to display next."""
        if self._state == "top":
            return self._handle_top(line)
        if self._state == "prepare":
            return self._handle_prepare(line)
        if self._state == "spend":
            return self._handle_spend(line)
        return self._top_menu()

    # ------------------------------------------------------------------
    # top menu
    # ------------------------------------------------------------------

    def _top_options(self) -> list[str]:
        """Top-menu choices, in numbered order.  *Done* is always last.

        "Prepare spells" is hidden when the player has no spellbook
        (spontaneous casters and non-casters — `abilities` is already
        the whole list, so there is nothing to re-prepare).
        """
        options: list[str] = []
        if self._hard.player.spellbook:
            options.append("Prepare spells")
        options.append("Spend hit dice")
        options.append("Done")
        return options

    def _top_menu(self, feedback: str = "") -> str:
        self._feedback = feedback
        label = "Long rest" if self.kind == "long" else "Short rest"
        lines = [f"── {label} ──"]
        lines.append(self._summary)
        lines.append(self._status_line())
        if feedback:
            lines.append(feedback)
        lines.append("")
        for idx, option in enumerate(self._top_options(), 1):
            lines.append(f"[{idx}] {option}")
        return "\n".join(lines)

    def _status_line(self) -> str:
        p = self._hard.player
        parts: list[str] = []
        if p.current_hp is not None:
            max_hp = p.max_hp
            parts.append(f"HP {p.current_hp}/{max_hp}" if max_hp else f"HP {p.current_hp}")
        if p.hit_dice is not None:
            parts.append(f"Hit Dice {p.hit_dice.current}/{p.hit_dice.max}")
        if p.spell_slots:
            slots = ", ".join(
                f"{_ordinal(lvl)} ×{n}"
                for lvl, n in sorted(p.spell_slots.items())
            )
            parts.append(f"slots: {slots}")
        return "  ".join(parts) if parts else ""

    def _handle_top(self, line: str) -> str:
        options = self._top_options()
        choice = line.strip()
        try:
            idx = int(choice)
        except ValueError:
            idx = -1
        if not 1 <= idx <= len(options):
            valid = ", ".join(str(i) for i in range(1, len(options) + 1))
            return self._top_menu(
                feedback=f"Invalid choice '{line}'. Pick {valid}."
            )
        option = options[idx - 1]
        if option == "Prepare spells":
            self._state = "prepare"
            return self._prepare_menu()
        if option == "Spend hit dice":
            return self._spend_one()
        self._exited = True
        label = "long rest" if self.kind == "long" else "short rest"
        return f"You finish your {label} and ready yourself to continue."

    # ------------------------------------------------------------------
    # prepare spells
    # ------------------------------------------------------------------

    def _prepare_menu(self, feedback: str = "") -> str:
        self._feedback = feedback
        spellbook = self._hard.player.spellbook
        if not spellbook:
            return self._top_menu(
                feedback="You have no spellbook — nothing to prepare."
            )
        lines = ["Prepare spells (toggle a number, 0/Enter to confirm):"]
        for idx, aid in enumerate(spellbook, 1):
            mark = "[x]" if aid in self._prepared else "[ ]"
            name = self._ability_name(aid)
            lines.append(f"  {mark} {idx}  {name}")
        if feedback:
            lines.append(feedback)
        lines.append("  0 or Enter to confirm.")
        return "\n".join(lines)

    def _handle_prepare(self, line: str) -> str:
        spellbook = self._hard.player.spellbook
        choice = line.strip()
        if choice == "" or choice == "0":
            ok, msg = set_prepared_spells(
                self._hard, self._corpus, self._prepared
            )
            if not ok:
                return self._prepare_menu(feedback=msg)
            self._state = "top"
            return self._top_menu(feedback=msg)
        try:
            idx = int(choice)
        except ValueError:
            return self._prepare_menu(feedback=f"Invalid input '{line}'.")
        if idx < 1 or idx > len(spellbook):
            return self._prepare_menu(feedback=f"No spell {idx}.")
        aid = spellbook[idx - 1]
        if aid in self._prepared:
            self._prepared.remove(aid)
        else:
            self._prepared.append(aid)
        return self._prepare_menu()

    # ------------------------------------------------------------------
    # spend hit dice
    # ------------------------------------------------------------------

    def _spend_one(self) -> str:
        ok, msg, _healed = spend_hit_die(self._hard, self._corpus)
        if not ok:
            # Back at the top menu — keep the controller state in sync
            # with what is displayed (also reached from the spend
            # submenu, where leaving the state as "spend" would desync).
            self._state = "top"
            return self._top_menu(feedback=msg)
        self._state = "spend"
        return self._spend_menu(feedback=msg)

    def _spend_menu(self, feedback: str = "") -> str:
        self._feedback = feedback
        lines = [feedback]
        lines.append(self._status_line())
        lines.append("")
        lines.append("[1] Spend another hit die")
        lines.append("[2] Done")
        return "\n".join(lines)

    def _handle_spend(self, line: str) -> str:
        choice = line.strip()
        if choice == "1":
            return self._spend_one()
        if choice == "2":
            self._state = "top"
            return self._top_menu()
        return self._spend_menu(feedback=f"Invalid choice '{line}'. Pick 1 or 2.")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _ability_name(self, aid: str) -> str:
        ability = self._corpus.abilities.get(aid)
        if ability is not None and getattr(ability, "name", None):
            return f"{ability.name} ({aid})"
        return aid
