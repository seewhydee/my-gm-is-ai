from __future__ import annotations

import re
from typing import Union

from mgmai.models.corpus import ConditionExpression, ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

DOMAINS = "flag|inventory|tag|entity|room|attitude|topic|item|stat"
CONDITION_RE = re.compile(
    rf"^({DOMAINS}):([\w.-]+)"
    rf"(?:\s*(==|>=|>|<=|<)\s*(.+))?$"
)

TRUE_VALUES = frozenset({"true", "True"})
FALSE_VALUES = frozenset({"false", "False"})


def parse_condition_string(
    raw: str,
) -> tuple[str, str, str | None, str | None]:
    """Parse a bare condition string into (domain, key, operator, value).

    Returns the operator and value as ``None`` for presence-only conditions
    (``inventory`` and ``tag``).
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
        if op is not None:
            raise ValueError(f"inventory condition must not have operator: {raw!r}")
        return key in hard_state.player.inventory

    if domain == "tag":
        if op is not None:
            raise ValueError(f"tag condition must not have operator: {raw!r}")
        if corpus is None:
            raise ValueError(f"tag condition requires corpus: {raw!r}")
        for item_id in hard_state.player.inventory:
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
        entity_state = hard_state.entity_states.get(entity_id)
        if entity_state is None:
            return False
        field_val = entity_state.get(field)
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
        room_state = hard_state.room_states.get(room_id)
        if room_state is None:
            return False
        field_val = room_state.get(field)
        if field_val is None:
            return False
        return _compare(field_val, op, value)

    if domain == "attitude":
        if op is None or value is None:
            raise ValueError(
                f"attitude condition requires operator and value: {raw!r}"
            )
        attitude_val = soft_state.npc_attitudes.get(key)
        if attitude_val is None and corpus is not None:
            entity = corpus.entities.get(key)
            if entity is not None and entity.dialogue_guidelines is not None:
                attitude_val = entity.dialogue_guidelines.attitude_limits.initial
        if attitude_val is None:
            return False
        return _compare(attitude_val, op, value)

    if domain == "topic":
        if op is not None:
            raise ValueError(f"topic condition must not have operator: {raw!r}")
        return key in soft_state.dialogue_state.topics_discussed

    if domain == "item":
        if op is not None:
            raise ValueError(f"item condition must not have operator: {raw!r}")
        return key in hard_state.player.inventory

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

    raise ValueError(f"Unknown condition domain: {domain}")


def _compare(actual: object, op: str, expected: str) -> bool:
    """Compare an actual value against an expected string using *op*."""
    if op == "==":
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


def evaluate(
    condition: ConditionExpression | str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None = None,
) -> bool:
    """Evaluate a ``ConditionExpression`` (or bare string) against game state.

    ``corpus`` is required when evaluating ``tag`` conditions.
    """
    if isinstance(condition, str):
        return evaluate_condition_string(condition, hard_state, soft_state, corpus)

    if condition.require is not None:
        return evaluate_condition_string(
            condition.require, hard_state, soft_state, corpus
        )

    if condition.unless is not None:
        return not evaluate_condition_string(
            condition.unless, hard_state, soft_state, corpus
        )

    if condition.any_of is not None:
        return any(
            evaluate(item, hard_state, soft_state, corpus)
            for item in condition.any_of
        )

    if condition.all_of is not None:
        return all(
            evaluate(item, hard_state, soft_state, corpus)
            for item in condition.all_of
        )

    return False


def evaluate_require(
    condition: ConditionExpression | str,
    hard_state: HardGameState,
    soft_state: SoftGameState,
    corpus: ModuleCorpus | None = None,
) -> bool:
    """Convenience: evaluate exactly as ``evaluate`` would."""
    return evaluate(condition, hard_state, soft_state, corpus)
