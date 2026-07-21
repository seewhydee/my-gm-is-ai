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

"""Status-effect mutation helpers — the single path for status-effect changes.

Every status-effect mutation (Result application, save failures, consumable
curing, tick expiry, auto-clear, combat-end clearing) routes through
:func:`apply_status_effect` / :func:`remove_status_effect`, so the
``status_effect.applied`` / ``status_effect.cleared`` events cannot be forgotten
by any path.

Events are not dispatched here directly: the helpers append
``(event_type, context)`` tuples to a caller-supplied *events* list, and
the caller dispatches them through the existing machinery (the resolver's
``resolution.events`` dispatched at end of turn, the combat result's
``"events"`` list forwarded by its callers, or ``_dispatch_events`` in
the engine).  When no event sink is available (pure utility contexts),
the mutation still happens and the event is only logged — matching how
other engine-owned mutations behave there.
"""

from __future__ import annotations

import logging
from typing import Any

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState

log = logging.getLogger(__name__)


def emit_status_effect_event(
    events: list[tuple[str, dict[str, Any]]] | None,
    event_type: str,
    context: dict[str, Any],
) -> None:
    """Append a status-effect event to *events*, or log when there is no sink."""
    if events is not None:
        events.append((event_type, context))
    else:
        log.debug("%s not dispatched (no event sink): %s", event_type, context)


def apply_status_effect(
    target_id: str,
    effect_id: str,
    rounds: int,
    hard: HardGameState,
    corpus: ModuleCorpus | None,
    source: str,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> None:
    """Apply *effect_id* to *target_id* for *rounds* rounds.

    Reapplication keeps the maximum of the existing and new remaining
    rounds.  Unknown status-effect IDs (not in
    ``corpus.effective_status_effects()``) pass through with a debug log —
    adventures may forward-declare status effects.  *source* records the
    provenance (``"result"``, ``"save_failure"``, …) on the emitted
    ``status_effect.applied`` event.
    """
    if corpus is not None and effect_id not in corpus.effective_status_effects():
        log.debug(
            "apply_status_effect: '%s' is not a defined status effect (passing through)",
            effect_id,
        )
    if target_id == "player":
        effects = hard.player.status_effects
    else:
        effects = hard.entity_states.setdefault(target_id, {}).setdefault(
            "status_effects", {}
        )
    effects[effect_id] = max(effects.get(effect_id, 0), rounds)
    emit_status_effect_event(
        events,
        "status_effect.applied",
        {
            "target_id": target_id,
            "status_effect_id": effect_id,
            "rounds": effects[effect_id],
            "source": source,
        },
    )


def remove_status_effect(
    target_id: str,
    effect_id: str,
    hard: HardGameState,
    corpus: ModuleCorpus | None,
    reason: str,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> None:
    """Remove *effect_id* from *target_id* if present.

    *reason* records the provenance (``"expired"``, ``"combat_end"``,
    ``"consumable"``, ``"auto_clear"``, ``"manual"``) on the emitted
    ``status_effect.cleared`` event.  No-op (and no event) when the target
    does not have the status effect.
    """
    if target_id == "player":
        effects = hard.player.status_effects
    else:
        effects = hard.entity_states.get(target_id, {}).get("status_effects", {})
    if effect_id not in effects:
        return
    del effects[effect_id]
    emit_status_effect_event(
        events,
        "status_effect.cleared",
        {
            "target_id": target_id,
            "status_effect_id": effect_id,
            "reason": reason,
        },
    )
