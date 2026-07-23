#!/usr/bin/env python3
"""Generate the SRD 5e data-pack manifest for adventure-module authors.

Reads the JSON data files under ``mgmai/data/srd_5e/`` and writes a
human-readable manifest to ``schema/srd-5e-pack.md``.  The manifest
lists every available ID (and display name) without exposing full
mechanical stats, so scenario authors can reference pack IDs without
digging into the code tree.

Usage:
    python scripts/generate_datapack_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "mgmai" / "data" / "srd_5e"
OUT_PATH = REPO_ROOT / "schema" / "srd-5e-pack.md"


def _load_json(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _classify_gear(gear: dict) -> dict[str, list[tuple[str, str]]]:
    """Return ``{heading: [(id, name), ...]}`` grouped by category."""
    buckets: dict[str, list[tuple[str, str]]] = {
        "Simple Melee Weapons": [],
        "Simple Ranged Weapons": [],
        "Martial Melee Weapons": [],
        "Martial Ranged Weapons": [],
        "Light Armor": [],
        "Medium Armor": [],
        "Heavy Armor": [],
        "Shield": [],
        "Potions": [],
    }
    for gid, entry in gear.items():
        name = entry.get("name", gid)
        tags = entry.get("tags", [])
        eb = entry.get("equip_block", {}) or {}
        etags = eb.get("equip_tags", []) or []
        props = eb.get("properties", []) or []
        desc = entry.get("description", "")

        if "potion" in tags:
            buckets["Potions"].append((gid, name))
        elif "shield" in tags:
            buckets["Shield"].append((gid, name))
        elif "armor" in tags:
            if "heavy" in desc.lower():
                buckets["Heavy Armor"].append((gid, name))
            elif "medium" in desc.lower():
                buckets["Medium Armor"].append((gid, name))
            else:
                buckets["Light Armor"].append((gid, name))
        elif "weapon" in etags:
            is_martial = "martial" in desc.lower()
            is_ranged = "ranged" in props or "ranged" in desc.lower()
            if is_martial:
                key = "Martial Ranged Weapons" if is_ranged else "Martial Melee Weapons"
            else:
                key = "Simple Ranged Weapons" if is_ranged else "Simple Melee Weapons"
            buckets[key].append((gid, name))
    return {k: v for k, v in buckets.items() if v}


def _classify_conditions(conditions: dict) -> dict[str, list[tuple[str, str]]]:
    """Return ``{heading: [(id, name), ...]}`` for conditions."""
    standard: list[tuple[str, str]] = []
    exhaustion: list[tuple[str, str]] = []
    for cid, entry in conditions.items():
        name = entry.get("name", cid)
        if cid.startswith("exhaustion-"):
            exhaustion.append((cid, name))
        else:
            standard.append((cid, name))
    buckets: dict[str, list[tuple[str, str]]] = {}
    if standard:
        buckets["Conditions"] = standard
    if exhaustion:
        buckets["Exhaustion Levels"] = exhaustion
    return buckets


def _section(title: str, buckets: dict[str, list[tuple[str, str]]]) -> str:
    lines: list[str] = []
    for heading, items in buckets.items():
        lines.append(f"### {heading}\n")
        lines.append("| ID | Name |")
        lines.append("|-----|------|")
        for item_id, name in items:
            lines.append(f"| `{item_id}` | {name} |")
        lines.append("")
    return "\n".join(lines)


def generate() -> str:
    gear = _load_json("gear")
    conditions = _load_json("conditions")

    parts: list[str] = [
        "# SRD 5e Data-Pack Manifest\n",
        "This file is **auto-generated** by "
        "`scripts/generate_datapack_manifest.py`.  Do not edit by hand.\n",
        "Adventure-module authors can reference any ID listed below in "
        "their corpus, rooms, inventories, and character sheets without "
        "re-defining the item.  The engine pulls the full definition from "
        "its built-in data pack.\n",
        f"**{len(gear)} gear items** and "
        f"**{len(conditions)} conditions** are currently available.\n",
        "---\n",
        "## Gear\n",
        "Each ID below is a valid reference for items, equipment, "
        "and consumables.\n",
    ]
    parts.append(_section("Gear", _classify_gear(gear)))

    parts.append("---\n")
    parts.append("## Conditions\n")
    parts.append(
        "Each ID below is a valid reference for status effects "
        "and the `status_effects` block.\n"
    )
    parts.append(_section("Conditions", _classify_conditions(conditions)))

    return "".join(parts)


def main() -> None:
    manifest = generate()
    OUT_PATH.write_text(manifest, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}  "
          f"({len(manifest.splitlines())} lines)")


if __name__ == "__main__":
    main()
