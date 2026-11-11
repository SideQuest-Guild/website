"""Regenerate ``api/src/sidequest_api/domain/characters/battlenet_recipe_map.json`` for a new game build.

Battle.net's character professions endpoint (``characters.professions(slug)``) answers known recipes by
``SkillLineAbility`` row id, a different id space from the game's recipe spell id (the id the addon's crafter
contract, ``ProfessionRecipe.recipe_id``, and Battle.net's own profession skill-tier endpoint all use). This script
pulls wago.tools' client data tables for a build and writes the exact ``SkillLineAbility id -> (spell id, created
item id)`` mapping, limited to the game's profession skill lines (Alchemy, Blacksmithing, ..., First Aid).

Usage: ``python tools/generate_battlenet_recipe_map.py <build>``, e.g. ``1.60.1.70790``. Run from the repo's
``website/`` directory (or anywhere; the output path is resolved relative to this script).
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

WAGO_BASE = "https://wago.tools/db2"
# A browser User-Agent: wago.tools 403s urllib's default ("Python-urllib/...").
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Forever's profession skill lines (Battle.net's profession document ``id`` is this same skill line id), pulled
# from a recorded ``/data/wow/profession/index`` document. Excludes "Test Profession [DNT]" (2933).
PROFESSION_SKILL_LINES = {129, 164, 165, 171, 182, 185, 186, 197, 202, 333, 356, 393}
CREATE_ITEM_EFFECT = 24  # SPELL_EFFECT_CREATE_ITEM
OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "api"
    / "src"
    / "sidequest_api"
    / "domain"
    / "characters"
    / "battlenet_recipe_map.json"
)


def _fetch_csv(table: str, build: str) -> csv.DictReader:
    request = urllib.request.Request(f"{WAGO_BASE}/{table}/csv?build={build}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")
    return csv.DictReader(io.StringIO(body))


def _created_items(build: str) -> dict[int, int]:
    """Spell id -> the item its first create-item effect produces, for every spell that has one."""
    created: dict[int, int] = {}
    for row in _fetch_csv("SpellEffect", build):
        if row["Effect"] != str(CREATE_ITEM_EFFECT):
            continue
        item_id = int(row["EffectItemType"])
        if not item_id:
            continue
        created.setdefault(int(row["SpellID"]), item_id)
    return created


def build_map(build: str) -> dict[str, dict[str, int | None]]:
    created_items = _created_items(build)
    mapping: dict[str, dict[str, int | None]] = {}
    for row in _fetch_csv("SkillLineAbility", build):
        try:
            skill_line = int(row["SkillLine"])
        except ValueError:
            continue
        if skill_line not in PROFESSION_SKILL_LINES:
            continue
        spell_id = int(row["Spell"])
        if not spell_id:
            continue
        mapping[row["ID"]] = {"spell": spell_id, "item": created_items.get(spell_id)}
    return dict(sorted(mapping.items(), key=lambda kv: int(kv[0])))


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <build>, e.g. 1.60.1.70790", file=sys.stderr)
        raise SystemExit(2)
    build = sys.argv[1]
    mapping = build_map(build)
    document = {
        "build": build,
        "source": (
            "https://wago.tools/db2/SkillLineAbility/csv (Spell) + "
            "https://wago.tools/db2/SpellEffect/csv (EffectItemType, Effect=24)"
        ),
        "recipes": mapping,
    }
    OUTPUT_PATH.write_text(json.dumps(document, indent=2) + "\n")
    print(f"Wrote {len(mapping)} recipes to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
