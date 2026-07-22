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

"""Engine-bundled data packs.

A *data pack* is a directory of JSON files shipped with the engine under
``mgmai/data/``, one directory per RPG system (e.g. ``srd_5e`` holds the
D&D 5e SRD content).  Packs carry chunky reference content — conditions,
gear, spells — so adventure and character-sheet authors reference pack
IDs instead of re-authoring SRD material per corpus.

Resolution is layered: consumers merge pack defaults with corpus entries
by ID, a corpus entry replacing the pack entry of the same ID wholesale
(see ``ModuleCorpus.effective_status_effects``).  This module only
locates and parses the JSON into raw dicts; parsing into pydantic models
happens at the consumer, which keeps this module free of model imports
(and thus free of import cycles with ``mgmai.models``).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib import resources
from typing import Any

log = logging.getLogger(__name__)

#: RPG system ID (``corpus.stats.system``) -> pack directory under
#: ``mgmai/data/``.
_PACK_DIRS = {
    "5e": "srd_5e",
}


@lru_cache(maxsize=None)
def load_pack(system_id: str, kind: str) -> dict[str, Any]:
    """Load the raw JSON mapping of pack file ``kind`` for ``system_id``.

    Returns ``{}`` when the system has no pack of that kind.  Results are
    cached for the process lifetime; treat the returned mapping as
    read-only.
    """
    dirname = _PACK_DIRS.get(system_id)
    if dirname is None:
        log.debug("no data pack registered for system %r", system_id)
        return {}
    ref = resources.files("mgmai") / "data" / dirname / f"{kind}.json"
    try:
        with ref.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.debug("data pack file not found: %s", ref)
        return {}
