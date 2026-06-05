"""Stat check computation utilities."""


def compute_d20_modifier(stat_value: int) -> int:
    """D&D 5e-style ability modifier: (stat - 10) // 2, floored."""
    return (stat_value - 10) // 2


def compute_modifier(stat_value: int, resolution_system: str) -> int:
    """Compute a stat modifier given a resolution system identifier."""
    if resolution_system == "d20":
        return compute_d20_modifier(stat_value)
    raise ValueError(f"Unknown resolution system: {resolution_system!r}")
