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

import re
from typing import Any

from mgmai.models.corpus import (
    ConditionExpression,
    ModuleCorpus,
    reserved_entity_field_default,
)
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.models.actions import ConditionStatus
from mgmai.engine.utils import get_entity_location

DOMAINS = "flag|inventory|tag|entity|room|topic|stat|equipped|event"
CONDITION_RE = re.compile(
    rf"^({DOMAINS}):([\w.-]+)"
    rf"(?:\s*(==|!=|>=|>|<=|<)\s*(.+))?$"
)

TRUE_VALUES = frozenset({"true", "True"})
FALSE_VALUES = frozenset({"false", "False"})


def _entity_field_value(
    entity_id: str,
    field: str,
    hard_state: HardGameState,
    corpus: ModuleCorpus | None,
) -> Any:
    """Value of an entity state field, falling back to reserved defaults.

    Reserved state fields (``alive``, ``hidden``, ``attitude``, etc.) are
    valid without a declaration; when undeclared and never set, they read
    as their documented default.  Returns ``None`` for unknown entities
    or non-reserved unset fields.
    """
    field_val = hard_state.entity_states.get(entity_id, {}).get(field)
    if field_val is not None:
        return field_val
    if corpus is None or entity_id not in corpus.entities:
        return None
    return reserved_entity_field_default(field, corpus.entities.get(entity_id))


def parse_condition_string(
    raw: str,
) -> tuple[str, str, str | None, str | None]:
    """Parse a bare condition string into (domain, key, operator, value).

    Returns the operator and value as ``None`` for presence-only domains
    (``tag`` and ``equipped``). ``inventory`` supports operators for
    quantity comparisons (e.g. ``inventory:coins >= 30``); without an
    operator it checks presence (count > 0).
    """
    match = CONDITION_RE.match(raw)
    if match is None:
        raise ValueError(f"Could not parse condition string: {raw!r}")
    domain = match.group(1)
    key = match.group(2)
    operator = match.group(3)
    value = match.group(4)
    return domain, key, operator, value


def evaluate_condition_string(
    raw: str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None,
    event_ctx: dict | None = None,
) -> bool:
    """Evaluate a single bare condition string against game state.

    ``corpus`` is required for ``tag`` lookups and optional for other domains.
    """
    domain, key, op, value = parse_condition_string(raw)

    if domain == "flag":
        if op is None:
            raise ValueError(f"flag condition requires operator and value: {raw!r}")
        if value is None:
            raise ValueError(f"flag condition requires value: {raw!r}")
        flag_val = hard_state.flags.get(key)
        if flag_val is None:
            return False
        return _compare(flag_val, op, value)

    if domain == "inventory":
        count = hard_state.player.inventory.get(key, 0)
        if op is not None:
            if value is None:
                raise ValueError(f"inventory condition with operator requires value: {raw!r}")
            return _compare(count, op, value)
        return count > 0

    if domain == "tag":
        if op is not None:
            raise ValueError(f"tag condition must not have operator: {raw!r}")
        if corpus is None:
            raise ValueError(f"tag condition requires corpus: {raw!r}")
        for item_id in hard_state.player.inventory:
            entity = corpus.entities.get(item_id)
            if entity is not None and key in entity.tags:
                return True
        for item_id in hard_state.player.equipped:
            entity = corpus.entities.get(item_id)
            if entity is not None and key in entity.tags:
                return True
        return False

    if domain == "entity":
        if "." not in key:
            raise ValueError(f"entity condition key must be entity.field: {raw!r}")
        if op is None or value is None:
            raise ValueError(
                f"entity condition requires operator and value: {raw!r}"
            )
        entity_id, field = key.split(".", 1)
        if field == "location":
            loc = get_entity_location(entity_id, hard_state, corpus)
            if value.lower() == "null":
                if op == "==":
                    return loc is None
                if op == "!=":
                    return loc is not None
                raise ValueError(
                    f"location 'null' only supports == and !=: {raw!r}"
                )
            if loc is None:
                return False
            return _compare(loc, op, value)
        field_val = _entity_field_value(entity_id, field, hard_state, corpus)
        if field_val is None:
            return False
        return _compare(field_val, op, value)

    if domain == "room":
        if "." not in key:
            raise ValueError(f"room condition key must be room_id.field: {raw!r}")
        if op is None or value is None:
            raise ValueError(
                f"room condition requires operator and value: {raw!r}"
            )
        room_id, field = key.split(".", 1)
        if field == "is_current":
            return _compare(hard_state.player.location == room_id, op, value)
        room_state = hard_state.room_states.get(room_id)
        if room_state is None:
            return False
        field_val = room_state.get(field)
        if field_val is None:
            return False
        return _compare(field_val, op, value)

    if domain == "topic":
        if op is not None:
            raise ValueError(f"topic condition must not have operator: {raw!r}")
        return key in soft_state.dialogue_state.topics_discussed

    if domain == "stat":
        if op is None or value is None:
            raise ValueError(
                f"stat condition requires operator and value: {raw!r}"
            )
        stats = hard_state.player.stats
        if stats is None:
            return False
        stat_val = stats.get(key)
        if stat_val is None:
            return False
        return _compare(stat_val, op, value)

    if domain == "equipped":
        if op is not None:
            raise ValueError(f"equipped condition must not have operator: {raw!r}")
        # key can be an entity ID or a tag
        if key in hard_state.player.equipped:
            return True
        if corpus is not None:
            for item_id in hard_state.player.equipped:
                entity = corpus.entities.get(item_id)
                if entity is not None and key in entity.tags:
                    return True
        return False

    if domain == "event":
        if event_ctx is None:
            return False
        if op is None or value is None:
            raise ValueError(
                f"event condition requires operator and value: {raw!r}"
            )
        ctx_val = event_ctx.get(key)
        if ctx_val is None:
            return False
        return _compare(ctx_val, op, value)

    raise ValueError(f"Unknown condition domain: {domain}")


def _compare(actual: object, op: str, expected: str) -> bool:
    """Compare an actual value against an expected string using *op*."""
    if op == "==":
        return _equal(actual, expected)
    if op == "!=":
        return not _equal(actual, expected)

    if expected in TRUE_VALUES or expected in FALSE_VALUES:
        raise ValueError(
            f"Comparison operator {op!r} cannot be used with boolean value "
            f"{expected!r}"
        )

    actual_num: int | float
    if isinstance(actual, bool):
        raise ValueError(
            f"Cannot compare boolean {actual!r} with operator {op!r}"
        )
    if isinstance(actual, int):
        actual_num = actual
    elif isinstance(actual, float):
        actual_num = actual
    else:
        try:
            actual_num = int(actual)
        except (ValueError, TypeError):
            try:
                actual_num = float(actual)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Cannot interpret {actual!r} as numeric for comparison "
                    f"with {op!r}"
                )

    try:
        expected_num = int(expected)
    except ValueError:
        try:
            expected_num = float(expected)
        except ValueError:
            raise ValueError(
                f"Cannot interpret {expected!r} as numeric for comparison "
                f"with {op!r}"
            )

    if op == ">=":
        return actual_num >= expected_num
    if op == ">":
        return actual_num > expected_num
    if op == "<=":
        return actual_num <= expected_num
    if op == "<":
        return actual_num < expected_num

    raise ValueError(f"Unknown operator: {op!r}")


def _equal(actual: object, expected: str) -> bool:
    """Return whether *actual* equals *expected* as a condition value."""
    if expected in TRUE_VALUES:
        return actual is True or actual == "true"
    if expected in FALSE_VALUES:
        return actual is False or actual == "false"
    # Numeric equality to avoid false mismatches like 10.0 != "10".
    if not isinstance(actual, bool):
        try:
            actual_num = float(actual)
            expected_num = float(expected)
            return actual_num == expected_num
        except (ValueError, TypeError):
            pass
    return str(actual) == expected


def evaluate(
    condition: ConditionExpression | str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None = None,
    event_ctx: dict | None = None,
) -> bool:
    """Evaluate a ``ConditionExpression`` (or bare string) against game state.

    ``corpus`` is required when evaluating ``tag`` conditions.
    """
    if isinstance(condition, str):
        return evaluate_condition_string(condition, hard_state, soft_state, corpus, event_ctx)

    if condition.require is not None:
        return evaluate_condition_string(
            condition.require, hard_state, soft_state, corpus, event_ctx
        )

    if condition.unless is not None:
        return not evaluate_condition_string(
            condition.unless, hard_state, soft_state, corpus, event_ctx
        )

    if condition.any_of is not None:
        return any(
            evaluate(item, hard_state, soft_state, corpus, event_ctx)
            for item in condition.any_of
        )

    if condition.all_of is not None:
        return all(
            evaluate(item, hard_state, soft_state, corpus, event_ctx)
            for item in condition.all_of
        )

    return False


def evaluate_require(
    condition: ConditionExpression | str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None = None,
    event_ctx: dict | None = None,
) -> bool:
    """Convenience: evaluate exactly as ``evaluate`` would."""
    return evaluate(condition, hard_state, soft_state, corpus, event_ctx)


def get_condition_detail(
    raw: str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None = None,
    event_ctx: dict | None = None,
) -> ConditionStatus:
    """Evaluate a condition string and return status with current-value detail.

    The ``detail`` field gives a human-readable description of the current
    state value that the condition references, so an LLM can understand
    *why* a condition is or isn't met.
    """
    domain, key, op, value = parse_condition_string(raw)
    met = evaluate_condition_string(raw, hard_state, soft_state, corpus, event_ctx)

    if domain == "flag":
        current = hard_state.flags.get(key, False)
        detail = f"flag {key} = {current}"

    elif domain == "inventory":
        count = hard_state.player.inventory.get(key, 0)
        if op is not None:
            detail = f"inventory '{key}' count = {count} (need {op} {value})"
        else:
            detail = f"inventory contains '{key}': {count > 0} (count = {count})"

    elif domain == "tag":
        if corpus is not None:
            found = any(
                key in entity.tags
                for item_id in hard_state.player.inventory
                if (entity := corpus.entities.get(item_id)) is not None
            ) or any(
                key in entity.tags
                for item_id in hard_state.player.equipped
                if (entity := corpus.entities.get(item_id)) is not None
            )
        else:
            found = False
        detail = f"item with tag '{key}' in inventory or equipped: {found}"

    elif domain == "entity":
        if "." in key:
            entity_id, field = key.split(".", 1)
            if field == "location":
                current_val = get_entity_location(entity_id, hard_state, corpus)
            else:
                current_val = _entity_field_value(entity_id, field, hard_state, corpus)
        else:
            entity_id, field = key, "?"
            current_val = None
        detail = f"entity {entity_id}.{field} = {current_val}"

    elif domain == "room":
        if "." in key:
            room_id, field = key.split(".", 1)
            current_val = hard_state.room_states.get(room_id, {}).get(field)
        else:
            room_id, field = key, "?"
            current_val = None
        detail = f"room {room_id}.{field} = {current_val}"

    elif domain == "topic":
        discussed = key in soft_state.dialogue_state.topics_discussed
        detail = f"topic '{key}' discussed: {discussed}"

    elif domain == "stat":
        current_val = (hard_state.player.stats or {}).get(key)
        detail = f"stat {key} = {current_val}"

    elif domain == "equipped":
        in_equipped = key in hard_state.player.equipped
        if not in_equipped and corpus is not None:
            found_tag = any(
                key in entity.tags
                for item_id in hard_state.player.equipped
                if (entity := corpus.entities.get(item_id)) is not None
            )
        else:
            found_tag = False
        detail = f"equipped contains '{key}': {in_equipped or found_tag}"

    elif domain == "event":
        ctx_val = (event_ctx or {}).get(key)
        detail = f"event {key} = {ctx_val}"

    else:
        detail = f"unknown domain '{domain}' for '{raw}'"

    return ConditionStatus(condition=raw, met=met, detail=detail)
