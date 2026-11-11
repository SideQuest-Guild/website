"""A fake Battle.net game data API for tests: items, item search, the guild roster and character profiles.

Import ``battlenet`` (what it serves) and ``forget_battlenet_state`` (autouse; clears the items and characters
domains' process-wide caches) into a test module, and pass ``transport(battlenet)`` to ``create_app`` as
``game_data_transport``. Roster and profile documents are real ones recorded from Battle.net, under
``fixtures/battlenet/``: the SideQuest roster, and every profile document of Terrorskull Gloomstep.
"""

import copy
import json
import zlib
from pathlib import Path

import httpx
import pytest

from sidequest_api.domain.auctions import services as auctions_services
from sidequest_api.domain.characters import services as characters_services
from sidequest_api.domain.items import services as items_services
from sidequest_api.domain.talents import services as talents_services

API = "https://us.api.blizzard.com"
BETA = "static-1.60.1_70399-forever-us"
PATCH = "static-1.60.2_71000-forever-us"
THUNDERFURY = "Thunderfury, Blessed Blade of the Windseeker"
RECORDED = Path(__file__).parent / "fixtures" / "battlenet"
TERRORSKULL = "terrorskull-gloomstep"
ROSTER = json.loads((RECORDED / "guild" / "sidequest" / "roster.json").read_text())

GUILD_ID = 228203
RULESET_ID = 2

# The 15 Forever auction houses, grouped by faction, as Battle.net's ruleset auctions index lists them (110-121,
# 123-125; 122 doesn't exist). Pulled from a real `/data/wow/ruleset/2/auctions/` recording.
ALLIANCE_HOUSE_IDS = (110, 111, 112, 119, 123)
HORDE_HOUSE_IDS = (113, 114, 115, 120, 124)
BLACKWATER_HOUSE_IDS = (116, 117, 118, 121, 125)
_HOUSE_NAMES = {
    **dict.fromkeys(ALLIANCE_HOUSE_IDS, "Alliance Auction House"),
    **dict.fromkeys(HORDE_HOUSE_IDS, "Horde Auction House"),
    **dict.fromkeys(BLACKWATER_HOUSE_IDS, "Blackwater Auction House"),
}


def guild_document(
    *,
    guild_id: int = GUILD_ID,
    ruleset_id: int = RULESET_ID,
    faction_type: str = "ALLIANCE",
    faction_name: str = "Alliance",
) -> dict:
    """A guild profile document shaped like Battle.net's ``/data/wow/guild/sidequest``, for the roster fixture's
    guild.
    """
    return {
        "_links": {"self": {"href": f"{API}/data/wow/guild/sidequest?namespace=profile-forever-us"}},
        "id": guild_id,
        "name": "SideQuest",
        "slug": "sidequest",
        "name_search": "sidequest",
        "faction": {"type": faction_type, "name": faction_name},
        "ruleset": {
            "key": {"href": f"{API}/data/wow/ruleset/{ruleset_id}?namespace=dynamic-forever-us"},
            "id": ruleset_id,
            "name": "Normal",
        },
        "achievement_points": 0,
        "member_count": len(ROSTER["members"]),
        "created_timestamp": 1730000000000,
        "roster": {"href": f"{API}/data/wow/guild/sidequest/roster?namespace=profile-forever-us"},
        "achievements": {"href": f"{API}/data/wow/guild/sidequest/achievements?namespace=profile-forever-us"},
        "activity": {"href": f"{API}/data/wow/guild/sidequest/activity?namespace=profile-forever-us"},
    }


def auction_entry(
    item_id: int,
    *,
    buyout: int | None = None,
    bid: int | None = None,
    quantity: int = 1,
    bonus_lists: list[int] | None = None,
    entry_id: int | None = None,
    time_left: str = "MEDIUM",
) -> dict:
    """One posted (non-commodity) auction, shaped like Battle.net's, for a house's ``auctions`` list."""
    item: dict[str, int | list[int]] = {"id": item_id}
    if bonus_lists:
        item["bonus_lists"] = bonus_lists
    entry = {"id": entry_id or item_id * 100 + quantity, "item": item, "quantity": quantity, "time_left": time_left}
    if buyout is not None:
        entry["buyout"] = buyout
    if bid is not None:
        entry["bid"] = bid
    return entry


def commodity_entry(
    item_id: int, *, unit_price: int, quantity: int, entry_id: int | None = None, time_left: str = "LONG"
) -> dict:
    """One posted commodity stack, shaped like Battle.net's, for a house's commodities ``auctions`` list."""
    return {
        "id": entry_id or item_id * 100 + quantity,
        "item": {"id": item_id},
        "quantity": quantity,
        "unit_price": unit_price,
        "time_left": time_left,
    }


def _default_auction_houses() -> dict:
    """Several Alliance houses (with real-shaped listings), one Horde and one Blackwater house (faction-ignored).

    Item ids, bonus lists and prices are drawn from a real ``/data/wow/ruleset/2/auctions/125`` (Blackwater)
    recording, reassigned across houses so cross-house aggregation (lowest price, quantity totals, variant
    folding) has real-shaped data to work with.
    """
    return {
        110: {
            "auctions": [
                auction_entry(14559, buyout=500, entry_id=1),  # single listing, quantity 1
                auction_entry(55555, buyout=900, quantity=3, entry_id=2),  # buyout // quantity = 300
                auction_entry(2079, buyout=1200, quantity=1, bonus_lists=[12729], entry_id=3),  # variant A
                auction_entry(
                    2079, buyout=1100, quantity=2, bonus_lists=[12730], entry_id=4
                ),  # variant B, folds with A
                auction_entry(99999, bid=100, entry_id=5),  # bid-only, ignored
            ],
            "commodities": [commodity_entry(2771, unit_price=2000, quantity=17, entry_id=6)],
        },
        111: {
            "auctions": [auction_entry(14559, buyout=450, entry_id=7)],  # cheaper than house 110: wins "lowest"
            "commodities": [commodity_entry(2771, unit_price=1800, quantity=10, entry_id=8)],
        },
        119: {"auctions": [], "commodities": []},
        123: {
            "auctions": [auction_entry(7364, buyout=10000, bonus_lists=[12919], entry_id=9)],
            "commodities": [
                commodity_entry(5075, unit_price=600, quantity=10, entry_id=10),
                commodity_entry(5075, unit_price=545, quantity=9, entry_id=11),  # folds with the row above
            ],
        },
        113: {  # Horde: cheaper than every Alliance house, must never affect Alliance prices
            "auctions": [auction_entry(14559, buyout=1, entry_id=12)],
            "commodities": [commodity_entry(2771, unit_price=1, quantity=999, entry_id=13)],
        },
        125: {  # Blackwater: same story
            "auctions": [auction_entry(14559, buyout=1, entry_id=14)],
            "commodities": [commodity_entry(2771, unit_price=1, quantity=999, entry_id=15)],
        },
    }


def roster_member(name: str, surname: str, *, rank: int, level: int = 10, class_id: int = 4) -> dict:
    """A roster entry shaped like Battle.net's, for a character the recorded roster doesn't have."""
    slug = f"{name}-{surname}".lower()
    character = copy.deepcopy(ROSTER["members"][0]["character"])
    character.update(
        name=name,
        surname=surname,
        slug=slug,
        level=level,
        id=zlib.crc32(slug.encode()),
        playable_class={**character["playable_class"], "id": class_id},
    )
    return {"character": character, "rank": rank}


API = "https://us.api.blizzard.com"
BETA = "static-1.60.1_70399-forever-us"
PATCH = "static-1.60.2_71000-forever-us"
THUNDERFURY = "Thunderfury, Blessed Blade of the Windseeker"


def _ref(kind: str, ref_id: int, name: str, version: str) -> dict:
    return {"key": {"href": f"{API}/data/wow/{kind}/{ref_id}?namespace={version}"}, "id": ref_id, "name": name}


def item_document(item_id: int, name: str, version: str) -> dict:
    """An item document shaped like Battle.net's, trimmed to what one two-handed epic sword carries."""
    media = {"key": {"href": f"{API}/data/wow/media/item/{item_id}?namespace={version}"}, "id": item_id}
    weapon_class = _ref("item-class", 2, "Weapon", version)
    sword = _ref("item-class/2/item-subclass", 8, "Sword", version)
    two_hand = {"type": "TWOHWEAPON", "name": "Two-Hand"}
    epic = {"type": "EPIC", "name": "Epic"}
    white = {"r": 255, "g": 255, "b": 255, "a": 1.0}
    return {
        "_links": {"self": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"}},
        "id": item_id,
        "name": name,
        "quality": epic,
        "level": 80,
        "required_level": 60,
        "media": media,
        "item_class": weapon_class,
        "item_subclass": sword,
        "inventory_type": two_hand,
        "is_equippable": True,
        "is_stackable": False,
        "max_count": 1,
        "purchase_price": 0,
        "purchase_quantity": 1,
        "sell_price": 123456,
        "preview_item": {
            "item": {"key": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"}, "id": item_id},
            "quality": epic,
            "name": name,
            "media": media,
            "item_class": weapon_class,
            "item_subclass": sword,
            "inventory_type": two_hand,
            "binding": {"type": "ON_ACQUIRE", "name": "Binds when picked up"},
            "weapon": {
                "damage": {
                    "min_value": 100,
                    "max_value": 200,
                    "display_string": "100 - 200 Damage",
                    "damage_class": {"type": "PHYSICAL", "name": "Physical"},
                },
                "attack_speed": {"value": 3500, "display_string": "Speed 3.50"},
                "dps": {"value": 42.9, "display_string": "(42.9 damage per second)"},
            },
            "stats": [
                {
                    "type": {"type": "STRENGTH", "name": "Strength"},
                    "value": 20,
                    "display": {"display_string": "+20 Strength", "color": white},
                }
            ],
            "requirements": {"level": {"value": 60, "display_string": "Requires Level 60"}},
            "durability": {"value": 120, "display_string": "Durability 120 / 120"},
            "level": {"value": 80, "display_string": "Item Level 80"},
        },
    }


def search_hit(item_id: int, name: str, version: str) -> dict:
    """One item search result shaped like Battle.net's: every locale's name, no tooltip."""
    return {
        "key": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"},
        "data": {
            "id": item_id,
            "name": {"en_US": name, "de_DE": name},
            "quality": {"type": "EPIC", "name": {"en_US": "Epic"}},
            "level": 80,
            "required_level": 60,
            "media": {"id": item_id},
            "item_class": {"id": 2, "name": {"en_US": "Weapon"}},
            "item_subclass": {"id": 8, "name": {"en_US": "Sword"}},
            "inventory_type": {"type": "TWOHWEAPON", "name": {"en_US": "Two-Hand"}},
            "is_equippable": True,
            "is_stackable": False,
            "max_count": 1,
            "purchase_price": 0,
            "purchase_quantity": 1,
            "sell_price": 123456,
        },
    }


@pytest.fixture
def battlenet() -> dict:
    """What the fake Battle.net serves, and every API request it saw. Tests change it between calls.

    ``roster`` is the guild roster's members; ``profiles`` the slugs with a published profile (each served from
    Terrorskull Gloomstep's recorded documents, renamed). ``guild`` is the site guild's profile document (faction,
    ruleset); see ``guild_document``. ``auction_houses`` maps house id to ``{"name": str, "auctions": [...],
    "commodities": [...]}`` for the ruleset auctions index/house/commodities routes; see ``auction_entry`` and
    ``commodity_entry`` to build real-shaped listings, and ``_default_auction_houses`` for the defaults (several
    other API path (such as ``/data/wow/talent-tree/1089/playable-specialization/574``) to the JSON body to answer
    it with; see ``recorded_document`` for loading one recorded under ``fixtures/battlenet/``. ``down`` makes every
    request answer 503; ``failing`` makes only the paths ending with one of its strings answer 503.
    ``profile_overrides`` maps a slug to ``{document_part: body}`` (such as ``{"professions": {...}}``), taking
    priority over the Terrorskull recording for that one document; a body of ``None`` answers 404 for it, so a
    test can give a character its own professions document, or make Battle.net 404 just one document part.
    """
    return {
        "version": BETA,
        "items": {19019: THUNDERFURY},
        "search": [(19019, THUNDERFURY)],
        "roster": copy.deepcopy(ROSTER["members"]),
        "profiles": {TERRORSKULL},
        "profile_overrides": {},
        "guild": guild_document(),
        "auction_houses": _default_auction_houses(),
        "documents": {},
        "down": False,
        "failing": set(),
        "requests": [],
    }


@pytest.fixture(autouse=True)
def forget_battlenet_state() -> None:
    """The data version, search/talent caches, and the auctions guild cache are process-wide; tests must not see
    each other's.
    """
    items_services._data_version = None
    items_services._search_cache.clear()
    characters_services._missing.clear()
    talents_services._tree_cache.clear()
    auctions_services._guild_cache = None


def _profile_document(path: str, battlenet: dict) -> httpx.Response:
    """A character profile document: Terrorskull Gloomstep's recording, under the requested character's name,
    unless ``battlenet["profile_overrides"]`` has a body (or ``None``, for a 404) for this slug and document part.
    """
    slug, _, part = path.removeprefix("/profile/wow/character/").partition("/")
    if slug not in battlenet["profiles"]:
        return httpx.Response(404, json={"code": 404})
    overrides = battlenet["profile_overrides"].get(slug, {})
    if part in overrides:
        body = overrides[part]
        return httpx.Response(404, json={"code": 404}) if body is None else httpx.Response(200, json=body)
    recorded = RECORDED / "wow" / "character" / (f"{TERRORSKULL}/{part}.json" if part else f"{TERRORSKULL}.json")
    if not recorded.exists():
        return httpx.Response(404, json={"code": 404})
    name, surname = (word.capitalize() for word in slug.split("-", 1))
    body = json.loads(recorded.read_text().replace("Terrorskull", name).replace("Gloomstep", surname))
    return httpx.Response(200, json=body)


def recorded_document(name: str) -> dict:
    """The body recorded at ``fixtures/battlenet/<name>.json``, such as ``static/talent-tree/1089/574``."""
    return json.loads((RECORDED / f"{name}.json").read_text())


def _auctions_index(ruleset_id: int, path: str, battlenet: dict) -> httpx.Response:
    """The ruleset's 15-house index, each house named from ``battlenet["auction_houses"]`` or its default."""
    houses = [
        {
            "id": house_id,
            "key": {"href": f"{API}/data/wow/ruleset/{ruleset_id}/auctions/{house_id}?namespace=dynamic-forever-us"},
            "name": battlenet["auction_houses"].get(house_id, {}).get("name", _HOUSE_NAMES[house_id]),
        }
        for house_id in sorted(_HOUSE_NAMES)
    ]
    body = {"_links": {"self": {"href": f"{API}{path}?namespace=dynamic-forever-us"}}, "auctions": houses}
    return httpx.Response(200, json=body)


def _auction_document(path: str, battlenet: dict) -> httpx.Response:
    """One ruleset auctions route: the index, one house, or one house's commodities."""
    ruleset_part, _, auctions_part = path.removeprefix("/data/wow/ruleset/").partition("/auctions")
    ruleset_id = int(ruleset_part)
    tail = auctions_part.strip("/")
    if not tail:
        return _auctions_index(ruleset_id, path, battlenet)
    segments = tail.split("/")
    house_id = int(segments[0])
    house = battlenet["auction_houses"].get(house_id, {})
    name = house.get("name", _HOUSE_NAMES.get(house_id, "Auction House"))
    if len(segments) == 1:
        body = {
            "_links": {"self": {"href": f"{API}{path}?namespace=dynamic-forever-us"}},
            "commodities": {
                "href": (
                    f"{API}/data/wow/ruleset/{ruleset_id}/auctions/{house_id}/commodities?namespace=dynamic-forever-us"
                )
            },
            "id": house_id,
            "name": name,
            "ruleset": {"href": f"{API}/data/wow/ruleset/{ruleset_id}?namespace=dynamic-forever-us"},
            "auctions": house.get("auctions", []),
        }
        return httpx.Response(200, json=body)
    if segments[1] == "commodities":
        body = {
            "_links": {"self": {"href": f"{API}{path}?namespace=dynamic-forever-us"}},
            "auctions": house.get("commodities", []),
        }
        return httpx.Response(200, json=body)
    return httpx.Response(404, json={"code": 404})


def transport(battlenet: dict) -> httpx.MockTransport:
    """Answer the game data client's requests from ``battlenet``, recording each one."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.battle.net":
            return httpx.Response(200, json={"access_token": "app-token", "token_type": "bearer", "expires_in": 86399})
        battlenet["requests"].append(request)
        if battlenet["down"] or any(request.url.path.endswith(suffix) for suffix in battlenet["failing"]):
            return httpx.Response(503, json={"code": 503})
        path, version = request.url.path, battlenet["version"]
        if path.startswith("/profile/wow/character/"):
            return _profile_document(path, battlenet)
        if path == "/data/wow/guild/sidequest/roster":
            return httpx.Response(200, json={**ROSTER, "members": battlenet["roster"]})
        if path == "/data/wow/guild/sidequest":
            return httpx.Response(200, json=battlenet["guild"])
        if path.startswith("/data/wow/ruleset/") and "/auctions" in path:
            return _auction_document(path, battlenet)
        if path in battlenet["documents"]:
            return httpx.Response(200, json=battlenet["documents"][path])
        if path == "/data/wow/search/item":
            hits = [search_hit(item_id, name, version) for item_id, name in battlenet["search"]]
            body = {"page": 1, "pageSize": 50, "maxPageSize": 1000, "pageCount": 1, "results": hits}
            return httpx.Response(200, json=body)
        kind, _, raw_id = path.removeprefix("/data/wow/").rpartition("/")
        item_id = int(raw_id) if raw_id.isdigit() else 0
        if item_id not in battlenet["items"]:
            return httpx.Response(404, json={"code": 404})
        if kind == "media/item":
            icon = {"key": "icon", "value": f"https://render.worldofwarcraft.com/forever-us/icons/56/{item_id}.jpg"}
            body = {
                "_links": {"self": {"href": f"{API}{path}"}},
                "id": item_id,
                "assets": [{**icon, "file_data_id": 1}],
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=item_document(item_id, battlenet["items"][item_id], version))

    return httpx.MockTransport(handler)
