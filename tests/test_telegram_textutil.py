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
    md_to_telegram_html,
    rich_to_telegram_html,
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


class TestMdToTelegramHtml:
    def test_bold_converted(self):
        assert md_to_telegram_html("**Exits:**") == "<b>Exits:</b>"

    def test_multiple_bold_spans(self):
        assert (
            md_to_telegram_html("**a** and **b**")
            == "<b>a</b> and <b>b</b>"
        )

    def test_html_special_chars_escaped(self):
        assert (
            md_to_telegram_html("1 < 2 & 3 > 2")
            == "1 &lt; 2 &amp; 3 &gt; 2"
        )

    def test_bullet_asterisks_left_alone(self):
        assert (
            md_to_telegram_html("* Clamber down\n* Drop down")
            == "* Clamber down\n* Drop down"
        )

    def test_unbalanced_delimiters_stripped(self):
        # e.g. a chunk split mid-bold-span: never emit malformed HTML.
        assert md_to_telegram_html("**dangling") == "dangling"

    def test_escaped_bold_combo(self):
        assert (
            md_to_telegram_html("**INT check: <success>**")
            == "<b>INT check: &lt;success&gt;</b>"
        )


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


class TestRichToTelegramHtml:
    def test_bold_and_aliases(self):
        assert rich_to_telegram_html("[bold]Hi[/bold]") == "<b>Hi</b>"
        assert rich_to_telegram_html("[b]Hi[/b]") == "<b>Hi</b>"

    def test_italic_underline_strike_code(self):
        assert rich_to_telegram_html("[i]x[/i]") == "<i>x</i>"
        assert rich_to_telegram_html("[underline]x[/underline]") == "<u>x</u>"
        assert rich_to_telegram_html("[strike]x[/strike]") == "<s>x</s>"
        assert rich_to_telegram_html("[code]x[/code]") == "<code>x</code>"

    def test_colors_and_dim_unwrap(self):
        assert rich_to_telegram_html("[dim]x[/dim]") == "x"
        assert rich_to_telegram_html("[red]err[/red]") == "err"
        assert rich_to_telegram_html("[dim cyan]x[/dim cyan]") == "x"
        assert rich_to_telegram_html("[green]ok[/green]") == "ok"

    def test_combined_style_and_color_keeps_style(self):
        assert rich_to_telegram_html("[bold cyan]x[/bold cyan]") == "<b>x</b>"

    def test_nesting(self):
        assert rich_to_telegram_html(
            "[bold]a [italic]b[/italic] c[/bold]") == "<b>a <i>b</i> c</b>"

    def test_unclosed_opener_is_closed_at_end(self):
        assert rich_to_telegram_html("[bold]never closed") == \
            "<b>never closed</b>"

    def test_unmatched_closer_dropped(self):
        assert rich_to_telegram_html("x[/bold]") == "x"

    def test_bare_close_tag(self):
        assert rich_to_telegram_html("[bold]x[/]") == "<b>x</b>"

    def test_unknown_tag_stripped(self):
        assert rich_to_telegram_html("[wat]x[/wat]") == "x"

    def test_literal_brackets_kept(self):
        assert rich_to_telegram_html("Take [3] items") == "Take [3] items"

    def test_content_escaped(self):
        assert rich_to_telegram_html("[bold]<script> & co[/bold]") == \
            "<b>&lt;script&gt; &amp; co</b>"

    def test_mismatched_nesting_still_valid(self):
        # Closing a color unwraps nothing but must not break the bold.
        assert rich_to_telegram_html("[bold][cyan]x[/cyan][/bold]") == \
            "<b>x</b>"

    def test_empty_and_plain(self):
        assert rich_to_telegram_html("") == ""
        assert rich_to_telegram_html("plain") == "plain"
