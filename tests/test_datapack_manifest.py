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

"""Verify that the SRD 5e data-pack manifest (schema/srd-5e-pack.md) is
in sync with the actual data files under mgmai/data/srd_5e/.

If this test fails, run:
    python scripts/generate_datapack_manifest.py
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "schema" / "srd-5e-pack.md"


class TestDatapackManifestSync:
    def test_manifest_is_up_to_date(self) -> None:
        from scripts.generate_datapack_manifest import generate

        expected = generate()
        actual = MANIFEST_PATH.read_text(encoding="utf-8")
        assert actual == expected, (
            "schema/srd-5e-pack.md is out of date.  "
            "Run: python scripts/generate_datapack_manifest.py"
        )

    def test_manifest_lists_all_gear_ids(self) -> None:
        import json

        from mgmai.datapack import load_pack

        gear = load_pack("5e", "gear")
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        for gear_id in gear:
            assert f"`{gear_id}`" in manifest_text, (
                f"gear ID {gear_id!r} missing from manifest"
            )

    def test_manifest_lists_all_condition_ids(self) -> None:
        from mgmai.datapack import load_pack

        conditions = load_pack("5e", "conditions")
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        for cond_id in conditions:
            assert f"`{cond_id}`" in manifest_text, (
                f"condition ID {cond_id!r} missing from manifest"
            )

    def test_manifest_does_not_leak_stats(self) -> None:
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        for keyword in ("damage_expr", "damage_type", "equip_block",
                        "ac_override", "ac_bonus", "hit_bonus",
                        "system_effects", "advantage", "disadvantage"):
            assert keyword not in manifest_text, (
                f"manifest should not expose stat keyword {keyword!r}"
            )
