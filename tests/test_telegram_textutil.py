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

"""Tests for mgmai/telegram/textutil.py — message chunking and markup
stripping.  Pure functions, no PTB."""

from __future__ import annotations

from mgmai.telegram.textutil import (
    TELEGRAM_MESSAGE_LIMIT,
    chunk_message,
    strip_rich_markup,
)


class TestStripRichMarkup:
    def test_strips_simple_tags(self):
        assert strip_rich_markup("[bold]Hello[/bold]") == "Hello"

    def test_strips_styled_and_closing_tags(self):
        assert (
            strip_rich_markup("[dim cyan]note[/dim cyan] [green]ok[/green]")
            == "note ok"
        )

    def test_keeps_literal_brackets(self):
        assert strip_rich_markup("Take [3] items") == "Take [3] items"

    def test_plain_text_unchanged(self):
        assert strip_rich_markup("nothing to strip") == "nothing to strip"


class TestChunkMessage:
    def test_short_text_single_chunk(self):
        assert chunk_message("hello") == ["hello"]

    def test_empty_text_single_chunk(self):
        assert chunk_message("") == [""]

    def test_exact_limit_single_chunk(self):
        text = "x" * TELEGRAM_MESSAGE_LIMIT
        assert chunk_message(text) == [text]

    def test_splits_on_paragraph_boundaries(self):
        paras = [f"para {i} " + "x" * 100 for i in range(20)]
        text = "\n\n".join(paras)
        chunks = chunk_message(text, limit=500)
        assert len(chunks) > 1
        assert all(len(c) <= 500 for c in chunks)
        # Splits happened only on boundaries, so rejoining restores text.
        assert "\n\n".join(chunks) == text

    def test_hard_split_fallback_for_oversize_paragraph(self):
        text = "y" * 1000
        chunks = chunk_message(text, limit=300)
        assert len(chunks) == 4
        assert all(len(c) <= 300 for c in chunks)
        assert "".join(chunks) == text

    def test_mixed_paragraphs_and_hard_split(self):
        text = "intro\n\n" + "z" * 700 + "\n\noutro"
        chunks = chunk_message(text, limit=300)
        assert chunks[0] == "intro"
        assert all(len(c) <= 300 for c in chunks)
        # The oversize paragraph's tail merges with the next paragraph.
        assert chunks[-1].endswith("outro")
        assert sum(c.count("z") for c in chunks) == 700
