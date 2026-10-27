import pytest

from sidequest_common.leveling import level_for_xp, level_progress, total_xp_for_level, xp_to_next_level


def test_curve_matches_mee6() -> None:
    # MEE6: 100 XP for level 1, 155 more for level 2, 220 more for level 3.
    assert [xp_to_next_level(n) for n in range(4)] == [100, 155, 220, 295]
    assert total_xp_for_level(3) == 475


@pytest.mark.parametrize(
    ("xp", "level", "into", "needed"),
    [
        (0, 0, 0, 100),
        (99, 0, 99, 100),
        (100, 1, 0, 155),  # exactly on the boundary levels up
        (254, 1, 154, 155),
        (255, 2, 0, 220),
    ],
)
def test_progress_at_boundaries(xp: int, level: int, into: int, needed: int) -> None:
    assert level_progress(xp) == (level, into, needed)


def test_progress_round_trips_total() -> None:
    for level in range(60):
        assert level_for_xp(total_xp_for_level(level)) == level
        assert level_for_xp(total_xp_for_level(level + 1) - 1) == level


def test_negative_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        level_progress(-1)
    with pytest.raises(ValueError):
        xp_to_next_level(-1)
