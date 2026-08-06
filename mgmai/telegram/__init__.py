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

"""Telegram front-end for MGMAI (optional: requires the ``telegram``
extra, i.e. python-telegram-bot v21).

Importing this package is safe without python-telegram-bot installed —
the PTB import happens inside ``bot.main()``.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    from mgmai.telegram.bot import main as _main

    _main(argv)
