"""A character's 3D model for Wowhead's model viewer, from its Battle.net appearance and Wowhead's item looks.

Battle.net's appearance document gives the race, body, barber choices (the same option and choice ids the viewer
uses) and the item in each worn slot. The viewer wants each item as ``[slot, display id]``, where the slot is the
item's inventory type except for weapons held in a hand, which go in the viewer's own main-hand (21) and off-hand
(22) slots. This follows Wowhead's paperdoll: a shield (14) or ranged weapon (15) in a hand keeps its own type.
"""

import asyncio
from typing import TYPE_CHECKING

from sidequest_api.lib.wowhead import ItemLook, item_look
from sidequest_common.schemas import CharacterModel, CharacterModelChoice, CharacterModelItem

if TYPE_CHECKING:
    import httpx
    from wow.models import AppearanceItem, CharacterAppearance

# Slots the viewer never draws on a body.
HIDDEN_SLOTS = frozenset({"NECK", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2"})
HAND_SLOTS = {"MAIN_HAND": 21, "OFF_HAND": 22}
OWN_SLOT_IN_HAND = frozenset({14, 15})  # shield, ranged
"""Inventory types the viewer draws in a hand under their own slot rather than 21/22."""
RANGED_SLOT = "RANGED"
CHARACTER_RACES = range(1, 9)
"""Forever's playable races (Human to Troll); the viewer's body model id is ``race * 2 - 1``, plus one if female."""


def _viewer_slot(item: AppearanceItem, look: ItemLook) -> int:
    hand = HAND_SLOTS.get(item.slot.type)
    if hand is not None and look.inventory_type not in OWN_SLOT_IN_HAND:
        return hand
    return look.inventory_type


async def build_character_model(appearance: CharacterAppearance, wowhead: httpx.AsyncClient) -> CharacterModel | None:
    """The viewer's options for this appearance, or ``None`` for a race the viewer's body ids don't cover.

    An item Wowhead has no look for is left off, so the character still draws without it. A ranged weapon is drawn
    only while both hands are empty: the viewer can only show it in hand, where it would cover the weapon held there.
    """
    race = appearance.playable_race.id
    if race not in CHARACTER_RACES:
        return None
    worn = [item for item in appearance.items if item.slot.type not in HIDDEN_SLOTS]
    looks = await asyncio.gather(*(item_look(wowhead, item.id) for item in worn))
    drawn = [(item, look) for item, look in zip(worn, looks, strict=True) if look is not None]
    hands_full = any(item.slot.type in HAND_SLOTS for item, _ in drawn)
    items = [
        CharacterModelItem(slot=_viewer_slot(item, look), display_id=look.display_id)
        for item, look in drawn
        if not (item.slot.type == RANGED_SLOT and hands_full)
    ]
    return CharacterModel(
        model_id=race * 2 - 1 + (appearance.gender.type == "FEMALE"),
        customizations=[
            CharacterModelChoice(option_id=custom.option.id, choice_id=custom.choice.id)
            for custom in appearance.customizations
        ],
        items=items,
    )
