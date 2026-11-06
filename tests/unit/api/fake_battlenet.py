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

from sidequest_api.domain.characters import services as characters_services
from sidequest_api.domain.items import services as items_services

API = "https://us.api.blizzard.com"
BETA = "static-1.60.1_70399-forever-us"
PATCH = "static-1.60.2_71000-forever-us"
THUNDERFURY = "Thunderfury, Blessed Blade of the Windseeker"
RECORDED = Path(__file__).parent / "fixtures" / "battlenet"
TERRORSKULL = "terrorskull-gloomstep"
ROSTER = json.loads((RECORDED / "guild" / "sidequest" / "roster.json").read_text())


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
    Terrorskull Gloomstep's recorded documents, renamed). ``documents`` maps any other API path (such as
    ``/data/wow/talent-tree/1089/playable-specialization/574``) to the JSON body to answer it with; see
    ``recorded_document`` for loading one recorded under ``fixtures/battlenet/``. ``down`` makes every request answer
    503; ``failing`` makes only the paths ending with one of its strings answer 503.
    """
    return {
        "version": BETA,
        "items": {19019: THUNDERFURY},
        "search": [(19019, THUNDERFURY)],
        "roster": copy.deepcopy(ROSTER["members"]),
        "profiles": {TERRORSKULL},
        "documents": {},
        "down": False,
        "failing": set(),
        "requests": [],
    }


@pytest.fixture(autouse=True)
def forget_battlenet_state() -> None:
    """The data version and the search cache are process-wide; tests must not see each other's."""
    items_services._data_version = None
    items_services._search_cache.clear()
    characters_services._missing.clear()


def _profile_document(path: str, battlenet: dict) -> httpx.Response:
    """A character profile document: Terrorskull Gloomstep's recording, under the requested character's name."""
    slug, _, part = path.removeprefix("/profile/wow/character/").partition("/")
    if slug not in battlenet["profiles"]:
        return httpx.Response(404, json={"code": 404})
    recorded = RECORDED / "wow" / "character" / (f"{TERRORSKULL}/{part}.json" if part else f"{TERRORSKULL}.json")
    if not recorded.exists():
        return httpx.Response(404, json={"code": 404})
    name, surname = (word.capitalize() for word in slug.split("-", 1))
    body = json.loads(recorded.read_text().replace("Terrorskull", name).replace("Gloomstep", surname))
    return httpx.Response(200, json=body)


def recorded_document(name: str) -> dict:
    """The body recorded at ``fixtures/battlenet/<name>.json``, such as ``static/talent-tree/1089/574``."""
    return json.loads((RECORDED / f"{name}.json").read_text())


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
