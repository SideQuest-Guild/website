"""MEE6-compatible leveling curve.

Going from level ``n`` to ``n + 1`` costs ``5n^2 + 50n + 100`` XP; XP is stored as a running total.
"""

from typing import NamedTuple


class LevelProgress(NamedTuple):
    """Where a running XP total sits on the curve."""

    level: int
    xp_into_level: int
    xp_for_next_level: int


def xp_to_next_level(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1``."""
    if level < 0:
        msg = "level must be >= 0"
        raise ValueError(msg)
    return 5 * level * level + 50 * level + 100


def total_xp_for_level(level: int) -> int:
    """Total XP needed to reach ``level`` from zero."""
    return sum(xp_to_next_level(n) for n in range(level))


def level_progress(xp: int) -> LevelProgress:
    """Level reached with ``xp`` total, plus progress toward the next one."""
    if xp < 0:
        msg = "xp must be >= 0"
        raise ValueError(msg)
    level = 0
    remaining = xp
    while remaining >= (cost := xp_to_next_level(level)):
        remaining -= cost
        level += 1
    return LevelProgress(level=level, xp_into_level=remaining, xp_for_next_level=cost)


def level_for_xp(xp: int) -> int:
    """Level reached with ``xp`` total."""
    return level_progress(xp).level
