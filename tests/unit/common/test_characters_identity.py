"""The addon's Forever identity (SQ.CanonicalName) mirrored site-side: canonical_character_name/character_key
must collapse every shape an export carries -- the current "First-Surname" link form, the raw "First Surname"
space form, and either with a stray "-<realm>" tail an addon before the Forever identity fix (v0.8.0 and
earlier) appended -- onto the same identity, so re-imports from an upgraded addon land on the character row a
pre-fix addon already created instead of a duplicate."""

import pytest

from sidequest_common.schemas.characters import canonical_character_name, character_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Legs-Behindhead", "Legs-Behindhead"),  # already-canonical link form
        ("Legs Behindhead", "Legs-Behindhead"),  # raw Forever space form
        ("Legs Behindhead-ShatteredHalls", "Legs-Behindhead"),  # pre-fix addon's mangled realm tail
        ("Legs-Behindhead-ShatteredHalls", "Legs-Behindhead"),  # mangled tail on the link form
        ("  Legs Behindhead  ", "Legs-Behindhead"),  # surrounding whitespace is trimmed first
        ("Bob-Whitemane", "Bob-Whitemane"),  # a plain non-Forever Name-Realm is unaffected
        ("Solo", "Solo"),  # a single token with nothing to split is kept as-is
    ],
)
def test_canonical_character_name_collapses_every_export_shape(raw: str, expected: str) -> None:
    assert canonical_character_name(raw) == expected


def test_character_key_is_the_canonical_name_lowercased() -> None:
    assert character_key("Legs Behindhead-ShatteredHalls") == "legs-behindhead"
    assert character_key("Legs-Behindhead") == "legs-behindhead"
    assert character_key("LEGS BEHINDHEAD") == "legs-behindhead"


def test_character_key_treats_legacy_and_fixed_addon_exports_as_the_same_identity() -> None:
    legacy_v0_8_0_export = "Legs Behindhead-ShatteredHalls"
    fixed_export = "Legs-Behindhead"
    assert character_key(legacy_v0_8_0_export) == character_key(fixed_export)
