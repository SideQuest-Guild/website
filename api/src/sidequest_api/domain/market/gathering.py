"""A curated table of classic (level 1-60) gatherable trade materials: herbs, ores, leather, cloth, and fish.

WoW: Forever is set in the original Azeroth, so this is the original game's zone and skill data, hand-checked
against public wikis (``warcraft.wiki.gg``, Wowhead's Classic guides) as of late 2026. Forever may move a node,
retune a skill requirement, or add a material this table does not have; treat this as a best-effort reference,
not a live game data feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Gathered:
    """One gatherable material: the profession that gathers it, the skill it needs, and its best zones."""

    profession: str
    """``'Herbalism' | 'Mining' | 'Skinning' | 'Fishing' | 'Cloth'``."""
    skill: int
    """The gathering skill needed, 1-300. 0 for cloth (it drops from humanoids, not gathered with a skill)."""
    zones: tuple[str, ...]
    """Its best zones, Alliance-friendly first, up to 4."""


GATHER_PROFESSIONS: tuple[str, ...] = ("Herbalism", "Mining", "Skinning", "Fishing", "Cloth")
"""Gathering professions, in report order."""

ZONE_LEVELS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "Elwynn Forest": (1, 10),
        "Dun Morogh": (1, 10),
        "Westfall": (10, 20),
        "Loch Modan": (10, 20),
        "Darkshore": (10, 20),
        "Redridge Mountains": (15, 25),
        "Stonetalon Mountains": (15, 25),
        "Duskwood": (20, 30),
        "Wetlands": (20, 30),
        "Hillsbrad Foothills": (20, 30),
        "Ashenvale": (20, 30),
        "Thousand Needles": (25, 35),
        "Alterac Mountains": (30, 40),
        "Arathi Highlands": (30, 40),
        "Desolace": (30, 40),
        "Stranglethorn Vale": (30, 45),
        "Swamp of Sorrows": (35, 45),
        "Badlands": (35, 45),
        "Dustwallow Marsh": (35, 45),
        "Searing Gorge": (40, 45),
        "The Hinterlands": (40, 50),
        "Tanaris": (40, 50),
        "Feralas": (40, 50),
        "Blasted Lands": (45, 55),
        "Western Plaguelands": (45, 55),
        "Azshara": (42, 55),
        "Felwood": (48, 55),
        "Un'Goro Crater": (50, 55),
        "Burning Steppes": (50, 60),
        "Eastern Plaguelands": (55, 60),
        "Winterspring": (55, 60),
        "Silithus": (55, 60),
        "Blackrock Depths": (49, 56),
    }
)
"""Every zone used in ``GATHERED``, with its classic level range. Dungeons use their monster level range."""

GATHERED: Mapping[int, Gathered] = MappingProxyType(
    {
        # Herbalism: every classic herb, Silverleaf through Black Lotus, plus the Season of Mastery add Wintersbite.
        765: Gathered(profession="Herbalism", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2447: Gathered(
            profession="Herbalism", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")
        ),
        2449: Gathered(
            profession="Herbalism", skill=15, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Redridge Mountains")
        ),
        785: Gathered(
            profession="Herbalism", skill=50, zones=("Darkshore", "Loch Modan", "Redridge Mountains", "Westfall")
        ),
        2450: Gathered(
            profession="Herbalism", skill=70, zones=("Darkshore", "Loch Modan", "Redridge Mountains", "Westfall")
        ),
        3820: Gathered(
            profession="Herbalism", skill=85, zones=("Ashenvale", "Darkshore", "Hillsbrad Foothills", "Westfall")
        ),
        2453: Gathered(
            profession="Herbalism", skill=100, zones=("Ashenvale", "Darkshore", "Loch Modan", "Redridge Mountains")
        ),
        3355: Gathered(
            profession="Herbalism", skill=115, zones=("Ashenvale", "Duskwood", "Stonetalon Mountains", "Wetlands")
        ),
        3369: Gathered(
            profession="Herbalism", skill=120, zones=("Duskwood", "Wetlands", "Arathi Highlands", "Alterac Mountains")
        ),
        3356: Gathered(
            profession="Herbalism",
            skill=125,
            zones=("Ashenvale", "Duskwood", "Hillsbrad Foothills", "Stonetalon Mountains"),
        ),
        3357: Gathered(
            profession="Herbalism",
            skill=150,
            zones=("Ashenvale", "Hillsbrad Foothills", "Dustwallow Marsh", "Stranglethorn Vale"),
        ),
        3818: Gathered(
            profession="Herbalism",
            skill=160,
            zones=("Stranglethorn Vale", "Dustwallow Marsh", "Swamp of Sorrows", "Badlands"),
        ),
        3821: Gathered(
            profession="Herbalism",
            skill=170,
            zones=("Stranglethorn Vale", "Dustwallow Marsh", "Feralas", "Swamp of Sorrows"),
        ),
        3358: Gathered(
            profession="Herbalism",
            skill=185,
            zones=("Stranglethorn Vale", "Dustwallow Marsh", "Feralas", "Hillsbrad Foothills"),
        ),
        3819: Gathered(profession="Herbalism", skill=195, zones=("Alterac Mountains",)),
        4625: Gathered(
            profession="Herbalism", skill=205, zones=("Badlands", "Searing Gorge", "Tanaris", "Blasted Lands")
        ),
        8831: Gathered(
            profession="Herbalism", skill=210, zones=("Stranglethorn Vale", "Feralas", "Tanaris", "Badlands")
        ),
        8836: Gathered(
            profession="Herbalism", skill=220, zones=("Western Plaguelands", "Eastern Plaguelands", "Felwood")
        ),
        8838: Gathered(
            profession="Herbalism",
            skill=230,
            zones=("Feralas", "Western Plaguelands", "Eastern Plaguelands", "Un'Goro Crater"),
        ),
        8839: Gathered(profession="Herbalism", skill=235, zones=("Swamp of Sorrows", "Un'Goro Crater")),
        8845: Gathered(profession="Herbalism", skill=245, zones=("The Hinterlands",)),
        8846: Gathered(profession="Herbalism", skill=250, zones=("Ashenvale", "Felwood", "Desolace", "Blasted Lands")),
        13464: Gathered(
            profession="Herbalism", skill=260, zones=("Felwood", "Un'Goro Crater", "Eastern Plaguelands", "Feralas")
        ),
        13463: Gathered(
            profession="Herbalism",
            skill=270,
            zones=("Felwood", "Un'Goro Crater", "Western Plaguelands", "Eastern Plaguelands"),
        ),
        13465: Gathered(
            profession="Herbalism",
            skill=280,
            zones=("Winterspring", "Felwood", "Un'Goro Crater", "Western Plaguelands"),
        ),
        13466: Gathered(
            profession="Herbalism", skill=285, zones=("Eastern Plaguelands", "Western Plaguelands", "Felwood")
        ),
        13467: Gathered(profession="Herbalism", skill=290, zones=("Winterspring",)),
        13468: Gathered(
            profession="Herbalism",
            skill=300,
            zones=("Winterspring", "Eastern Plaguelands", "Burning Steppes", "Silithus"),
        ),
        # Mining: ore veins Copper through Thorium (plus Dark Iron), and the stones mined alongside them.
        2770: Gathered(profession="Mining", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2835: Gathered(profession="Mining", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2771: Gathered(
            profession="Mining",
            skill=65,
            zones=("Redridge Mountains", "Wetlands", "Hillsbrad Foothills", "Thousand Needles"),
        ),
        2836: Gathered(
            profession="Mining",
            skill=65,
            zones=("Redridge Mountains", "Wetlands", "Hillsbrad Foothills", "Thousand Needles"),
        ),
        2775: Gathered(
            profession="Mining",
            skill=75,
            zones=("Redridge Mountains", "Wetlands", "Hillsbrad Foothills", "Thousand Needles"),
        ),
        2772: Gathered(
            profession="Mining",
            skill=125,
            zones=("Arathi Highlands", "Badlands", "Swamp of Sorrows", "Thousand Needles"),
        ),
        2838: Gathered(
            profession="Mining",
            skill=125,
            zones=("Arathi Highlands", "Badlands", "Swamp of Sorrows", "Thousand Needles"),
        ),
        2776: Gathered(
            profession="Mining", skill=155, zones=("Arathi Highlands", "Badlands", "Searing Gorge", "Swamp of Sorrows")
        ),
        3858: Gathered(
            profession="Mining", skill=175, zones=("Badlands", "Tanaris", "The Hinterlands", "Un'Goro Crater")
        ),
        7912: Gathered(
            profession="Mining", skill=175, zones=("Badlands", "Tanaris", "The Hinterlands", "Un'Goro Crater")
        ),
        11370: Gathered(profession="Mining", skill=230, zones=("Blackrock Depths",)),
        7911: Gathered(
            profession="Mining", skill=230, zones=("Badlands", "Tanaris", "The Hinterlands", "Un'Goro Crater")
        ),
        10620: Gathered(
            profession="Mining", skill=245, zones=("Un'Goro Crater", "Winterspring", "Silithus", "Eastern Plaguelands")
        ),
        12365: Gathered(
            profession="Mining", skill=245, zones=("Un'Goro Crater", "Winterspring", "Silithus", "Eastern Plaguelands")
        ),
        # Skinning: leather and hides by the level of beast they come from, low to high.
        2934: Gathered(profession="Skinning", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2318: Gathered(profession="Skinning", skill=1, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        783: Gathered(profession="Skinning", skill=75, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2319: Gathered(
            profession="Skinning", skill=100, zones=("Westfall", "Loch Modan", "Redridge Mountains", "Duskwood")
        ),
        4232: Gathered(
            profession="Skinning", skill=100, zones=("Westfall", "Loch Modan", "Redridge Mountains", "Duskwood")
        ),
        4234: Gathered(
            profession="Skinning",
            skill=150,
            zones=("Wetlands", "Hillsbrad Foothills", "Stranglethorn Vale", "Duskwood"),
        ),
        4235: Gathered(
            profession="Skinning",
            skill=150,
            zones=("Wetlands", "Hillsbrad Foothills", "Stranglethorn Vale", "Duskwood"),
        ),
        4304: Gathered(
            profession="Skinning", skill=200, zones=("Stranglethorn Vale", "Tanaris", "Un'Goro Crater", "Feralas")
        ),
        8169: Gathered(
            profession="Skinning", skill=200, zones=("Stranglethorn Vale", "Tanaris", "Un'Goro Crater", "Feralas")
        ),
        8170: Gathered(profession="Skinning", skill=250, zones=("Tanaris", "Un'Goro Crater", "Silithus", "Felwood")),
        8171: Gathered(profession="Skinning", skill=250, zones=("Tanaris", "Un'Goro Crater", "Silithus", "Felwood")),
        # Fishing: raw fish used in cooking recipes and the three oil fish used in alchemy.
        6291: Gathered(profession="Fishing", skill=1, zones=("Elwynn Forest", "Loch Modan", "Dun Morogh", "Darkshore")),
        6289: Gathered(profession="Fishing", skill=1, zones=("Elwynn Forest", "Loch Modan", "Dun Morogh", "Darkshore")),
        6308: Gathered(
            profession="Fishing", skill=50, zones=("Duskwood", "Ashenvale", "Hillsbrad Foothills", "Darkshore")
        ),
        6361: Gathered(
            profession="Fishing", skill=50, zones=("Ashenvale", "Darkshore", "Hillsbrad Foothills", "Westfall")
        ),
        6358: Gathered(
            profession="Fishing", skill=75, zones=("Darkshore", "Hillsbrad Foothills", "Westfall", "Arathi Highlands")
        ),
        6359: Gathered(
            profession="Fishing",
            skill=105,
            zones=("Hillsbrad Foothills", "Wetlands", "Arathi Highlands", "Stranglethorn Vale"),
        ),
        8365: Gathered(
            profession="Fishing",
            skill=150,
            zones=("Swamp of Sorrows", "Stranglethorn Vale", "Arathi Highlands", "Dustwallow Marsh"),
        ),
        13422: Gathered(profession="Fishing", skill=205, zones=("Azshara", "Feralas", "Stranglethorn Vale", "Tanaris")),
        4603: Gathered(
            profession="Fishing",
            skill=205,
            zones=("Arathi Highlands", "Dustwallow Marsh", "Feralas", "Stranglethorn Vale"),
        ),
        13759: Gathered(profession="Fishing", skill=205, zones=("Azshara", "Felwood", "Feralas", "Winterspring")),
        13760: Gathered(
            profession="Fishing", skill=205, zones=("Azshara", "Feralas", "Un'Goro Crater", "Winterspring")
        ),
        13889: Gathered(
            profession="Fishing", skill=275, zones=("Burning Steppes", "Eastern Plaguelands", "Feralas", "Winterspring")
        ),
        # Cloth: dropped by humanoids, not gathered with a skill. Zones are where that level of humanoid is common.
        2589: Gathered(profession="Cloth", skill=0, zones=("Elwynn Forest", "Dun Morogh", "Loch Modan", "Westfall")),
        2592: Gathered(profession="Cloth", skill=0, zones=("Westfall", "Redridge Mountains", "Duskwood", "Loch Modan")),
        4306: Gathered(
            profession="Cloth",
            skill=0,
            zones=("Duskwood", "Hillsbrad Foothills", "Stranglethorn Vale", "Arathi Highlands"),
        ),
        4338: Gathered(profession="Cloth", skill=0, zones=("Arathi Highlands", "Badlands", "Desolace", "Tanaris")),
        14047: Gathered(
            profession="Cloth",
            skill=0,
            zones=("Western Plaguelands", "Eastern Plaguelands", "Burning Steppes", "Searing Gorge"),
        ),
        14256: Gathered(profession="Cloth", skill=0, zones=("Felwood", "Azshara", "Blasted Lands", "Silithus")),
    }
)
"""Every gatherable material this report knows, by item id."""
