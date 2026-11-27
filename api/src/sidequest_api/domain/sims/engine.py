"""wowsims/forever CLI integration: item resolution, SIML generation, and result parsing.

Ported from the wow-forever-sim skill's single-character prototype
(``~/.claude/skills/wow-forever-sim/sim.py``), generalised across every supported class/spec using each spec's
``ui/specs/<class>/<spec>/`` preset files instead of one hardcoded prot paladin. Like that prototype, the generated
setup carries no consumables, buffs, party buffs, raid buffs or debuffs: gear and talents only, against generic
level-60 targets built from the request.

Each spec's talents come from its ``defaults.siml`` (else the first ``talentsString`` in ``presets.ts``) and its
rotation from the file ``defaults.siml`` uses, the rotation written inline there, or ``apls/`` (JSON presets printed
as SIML with ``wowsimcli siml print``); see :func:`load_spec_preset`. :data:`UNSUPPORTED_SPECS` lists the specs with no
rotation this service can run (healers, and the specs whose rotation only the wowsims website builds), and
:func:`check_simmable` turns those and too-low levels into a 400 before a job is queued.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sidequest_common.schemas import CharacterGear, CharacterSheet, SimItem, SimMobType, SimRole, SimSlot

SLOT_ORDER: tuple[SimSlot, ...] = (
    "head",
    "neck",
    "shoulder",
    "back",
    "chest",
    "wrist",
    "hands",
    "waist",
    "legs",
    "feet",
    "finger1",
    "finger2",
    "trinket1",
    "trinket2",
    "main_hand",
    "off_hand",
    "ranged",
)
# Battle.net's slot names (CharacterGear.slot) -> our slot. SHIRT/TABARD carry no sim stats.
API_SLOTS: dict[str, SimSlot] = {
    "HEAD": "head",
    "NECK": "neck",
    "SHOULDER": "shoulder",
    "BACK": "back",
    "CHEST": "chest",
    "WRIST": "wrist",
    "HANDS": "hands",
    "WAIST": "waist",
    "LEGS": "legs",
    "FEET": "feet",
    "FINGER_1": "finger1",
    "FINGER_2": "finger2",
    "TRINKET_1": "trinket1",
    "TRINKET_2": "trinket2",
    "MAIN_HAND": "main_hand",
    "OFF_HAND": "off_hand",
    "RANGED": "ranged",
}
# A ring/trinket swap sent with no slot is tried in both of that pair's slots.
AMBIGUOUS_SLOT_PAIRS: dict[str, tuple[SimSlot, SimSlot]] = {
    "finger": ("finger1", "finger2"),
    "trinket": ("trinket1", "trinket2"),
}
MAX_COMPARISONS = 4
MAX_AMBIGUOUS_PER_ITEM = 2
# proto's ItemType/HandType enum numbers (proto/common.proto), used to derive an item's valid sim slot(s).
_ITEM_TYPE_SLOT: dict[int, tuple[SimSlot, ...]] = {
    1: ("head",),
    2: ("neck",),
    3: ("shoulder",),
    4: ("back",),
    5: ("chest",),
    6: ("wrist",),
    7: ("hands",),
    8: ("waist",),
    9: ("legs",),
    10: ("feet",),
    14: ("ranged",),
}
_ITEM_TYPE_FINGER = 11
_ITEM_TYPE_TRINKET = 12
_ITEM_TYPE_WEAPON = 13
# HandType: off hand, one hand (either hand); anything else (main hand only, two hand) goes in the main hand.
_WEAPON_SLOTS_BY_HAND_TYPE: dict[int, tuple[SimSlot, ...]] = {3: ("off_hand",), 2: ("main_hand", "off_hand")}
# WeaponType: held in off hand, shield; every spec can use these in the off hand without dual-wielding.
_OFF_HAND_ANYONE_WEAPON_TYPES = frozenset({5, 7})
# Mirrors wowsims' SpecCanDualWieldCapabilities: only these specs may put a weapon in the off hand.
DUAL_WIELD_SPECS: frozenset[tuple[str, str]] = frozenset(
    {
        ("warrior", "dps"),
        ("warrior", "protection"),
        ("rogue", "dps"),
        ("hunter", "dps"),
    }
)


def _weapon_slots(item: dict, *, dual_wield: bool) -> tuple[SimSlot, ...]:
    """A weapon's hand slot(s); only dual-wielders put weapons (not shields or held items) in the off hand."""
    hand_type = item.get("handType")
    default: tuple[SimSlot, ...] = ("main_hand",)
    slots = _WEAPON_SLOTS_BY_HAND_TYPE.get(hand_type, default) if isinstance(hand_type, int) else default
    if dual_wield or item.get("weaponType") in _OFF_HAND_ANYONE_WEAPON_TYPES:
        return slots
    return tuple(slot for slot in slots if slot != "off_hand")


# (class, spec) -> the SIML `spec` line value, which is the proto's Player.spec oneof field name.
SPEC_LINE: dict[tuple[str, str], str] = {
    ("paladin", "holy"): "holy_paladin",
    ("paladin", "protection"): "protection_paladin",
    ("paladin", "retribution"): "retribution_paladin",
    ("warrior", "dps"): "dps_warrior",
    ("warrior", "protection"): "protection_warrior",
    ("druid", "balance"): "balance_druid",
    ("druid", "feralcat"): "feral_cat_druid",
    ("druid", "feralbear"): "feral_bear_druid",
    ("druid", "restoration"): "restoration_druid",
    ("shaman", "elemental"): "elemental_shaman",
    ("shaman", "enhancement"): "enhancement_shaman",
    ("shaman", "restoration"): "restoration_shaman",
    ("priest", "dps"): "dps_priest",
    ("priest", "healer"): "healer_priest",
    ("rogue", "dps"): "rogue",
    ("hunter", "dps"): "hunter",
    ("mage", "dps"): "mage",
    ("warlock", "dps"): "warlock",
}
# (class, spec) -> the directory name under ui/specs/<class>/.
SPEC_DIR_NAME: dict[tuple[str, str], str] = {
    ("warrior", "dps"): "dps",
    ("priest", "dps"): "dps",
    ("hunter", "dps"): "dps",
    ("mage", "dps"): "dps",
    ("rogue", "dps"): "dps",
    ("warlock", "dps"): "dps",
}
ROLE_BY_SPEC: dict[tuple[str, str], SimRole] = {
    ("paladin", "protection"): "tank",
    ("warrior", "protection"): "tank",
    ("druid", "feralbear"): "tank",
    ("paladin", "holy"): "healer",
    ("priest", "healer"): "healer",
    ("druid", "restoration"): "healer",
    ("shaman", "restoration"): "healer",
}
# Specs the sim service can't run yet, and why, in words the bot shows the member. Enhancement and warlock rotations
# are built from TypeScript preset objects in the UI, which `wowsimcli` has no way to print; the healer specs have no
# rotation at all upstream (the site sims them through a healing model only); the JSON rotations of the others read
# variables (shield equipped, stealth opener, …) that the site's UI fills in and the files never define.
_TS_ROTATION = "its default rotation is built by the wowsims website, which this service can't run yet"
_NO_HEALER_ROTATION = "wowsims/forever has no healing rotation yet, so a healer's gear can't be compared"
_UI_VARIABLES = "its rotation needs settings the wowsims website fills in, which this service can't supply yet"
UNSUPPORTED_SPECS: dict[tuple[str, str], str] = {
    ("shaman", "enhancement"): _TS_ROTATION,
    ("warlock", "dps"): _TS_ROTATION,
    ("paladin", "holy"): _NO_HEALER_ROTATION,
    ("priest", "healer"): _NO_HEALER_ROTATION,
    ("druid", "restoration"): _NO_HEALER_ROTATION,
    ("shaman", "restoration"): _NO_HEALER_ROTATION,
}

RACE_SIML_NAME = {
    "Human": "human",
    "Dwarf": "dwarf",
    "Gnome": "gnome",
    "Night Elf": "night_elf",
    "Orc": "orc",
    "Tauren": "tauren",
    "Troll": "troll",
    "Undead": "undead",
    "Blood Elf": "blood_elf",
    "High Order Skyborne": "high_order_skyborne",
    "Windshaper Skyborne": "windshaper_skyborne",
}

# Generic level-60 "dungeon pug" target, same for every scenario: no real dungeon trash/boss model.
TARGET_ATTACK_POWER = 320
TARGET_BLOCK_VALUE = 54
TARGET_ARMOR = 3731
TARGET_HEALTH = 1_428_900
TARGET_MIN_BASE_DAMAGE = 700
TARGET_DAMAGE_SPREAD = 0.5
TARGET_SWING_SPEED = 2
TARGET_LEVEL = 60
HEALING_MODEL_HPS = 600
HEALING_MODEL_CADENCE_SECONDS = 1.5
HEALING_MODEL_CADENCE_VARIATION = 1.2
SIM_ITERATIONS = 5000
SIM_TIMEOUT_SECONDS = 120
STANDARD_ERRORS_FOR_NOISE = 2

_WOWHEAD_ITEM_RE = re.compile(r"item=(\d+)")


class SimEngineError(Exception):
    """A user-facing validation error: unknown character/item/spec, bad slot, unsimmable spec. 400s the request."""


def snake(text: str) -> str:
    """The SIML-name form of free text: lowercase, apostrophes dropped, runs of other punctuation as `_`."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower().replace("'", "")).strip("_")


def role_for(class_name: str, spec: str) -> SimRole:
    """tank, healer, or dps for a (class, spec) pair."""
    return ROLE_BY_SPEC.get((class_name, spec), "dps")


def spec_line(class_name: str, spec: str) -> str:
    """The SIML ``spec`` line value for (class, spec), or raise if the pair isn't one the sim supports."""
    try:
        return SPEC_LINE[(class_name, spec)]
    except KeyError:
        msg = f"unsupported class/spec: {class_name} {spec}"
        raise SimEngineError(msg) from None


# wowsims/forever models a level-60 character only. A few levels short still compares gear sensibly (the sim was used
# that way at 57); far below, the spell ranks and stats differ too much for the numbers to mean anything.
SIM_LEVEL = 60
MIN_LEVEL = 55


def check_simmable(class_name: str, spec: str, level: int) -> None:
    """Raise if (class, spec) or ``level`` is one this service can't sim, with the reason in the member's words."""
    spec_line(class_name, spec)
    if reason := UNSUPPORTED_SPECS.get((class_name, spec)):
        msg = f"{class_name.title()} {spec} can't be simmed: {reason}"
        raise SimEngineError(msg)
    if level < MIN_LEVEL:
        msg = f"the sim only models level {SIM_LEVEL} characters; level {MIN_LEVEL}+ is close enough, {level} isn't"
        raise SimEngineError(msg)


# Battle.net's talent-tree display name (lowercased), per class -> our spec key. Classes whose three trees are all
# dps (hunter, mage, rogue, warlock) aren't listed: any Battle.net spec maps to "dps" for them, below.
_BATTLENET_SPEC_MAP: dict[str, dict[str, str]] = {
    "paladin": {"holy": "holy", "protection": "protection", "retribution": "retribution"},
    "warrior": {"arms": "dps", "fury": "dps", "protection": "protection"},
    "shaman": {"elemental": "elemental", "enhancement": "enhancement", "restoration": "restoration"},
    "priest": {"shadow": "dps", "discipline": "healer", "holy": "healer"},
    "druid": {"balance": "balance", "restoration": "restoration"},  # feral is ambiguous: cat or bear, see below
}
_SINGLE_SPEC_CLASSES = frozenset({"hunter", "mage", "rogue", "warlock"})


def normalize_spec(class_name: str, battlenet_spec: str | None, override: str | None) -> str:
    """Our spec key (e.g. ``"protection"``) for a character, from its Battle.net spec and an optional override.

    Raises if the class/spec has no sim support, or (druid feral, with no override) is ambiguous: Battle.net's
    talent tree is "Feral Combat" for both cat and bear, so only ``override`` can say which.
    """
    if override:
        key = override.strip().lower()
        if (class_name, key) not in SPEC_LINE:
            msg = f"unsupported class/spec: {class_name} {key}"
            raise SimEngineError(msg)
        return key
    if class_name in _SINGLE_SPEC_CLASSES:
        return "dps"
    spec_lower = (battlenet_spec or "").strip().lower()
    mapped = _BATTLENET_SPEC_MAP.get(class_name, {}).get(spec_lower)
    if mapped:
        return mapped
    if class_name == "druid" and spec_lower == "feral combat":
        msg = "this character is Feral Combat, which is cat or bear for the sim: set spec to feralcat or feralbear"
        raise SimEngineError(msg)
    msg = f"couldn't tell this character's spec for the sim (Battle.net says {battlenet_spec!r}): set spec"
    raise SimEngineError(msg)


def spec_dir(wowsims_dir: Path, class_name: str, spec: str) -> Path:
    """``ui/specs/<class>/<spec-dir>`` for (class, spec)."""
    return wowsims_dir / "ui" / "specs" / class_name / SPEC_DIR_NAME.get((class_name, spec), spec)


@dataclass
class GearEntry:
    """One SIML gear row: an item (SIML name), its id and in-game name for display, and an optional suffix/enchant."""

    name: str
    item_id: int
    suffix: str | None = None
    enchant: str | None = None
    display_name: str = ""

    def row(self, slot: str) -> str:
        """This entry as a SIML gear row for ``slot``."""
        label = self.name
        if self.suffix:
            label += f" {self.suffix}"
        if self.enchant:
            label += f" + {self.enchant}"
        return f"  {slot} {label}"


@dataclass
class ResolvedSwap:
    """A :class:`SimItem` resolved against the item database."""

    entry: GearEntry
    candidate_slots: tuple[SimSlot, ...]
    notes: list[str] = field(default_factory=list)


class ItemDB:
    """The wowsims checkout's item/suffix/enchant name tables and item database, loaded once per checkout.

    Use :func:`item_db` to get the shared instance; the tables are a few MB of JSON, read on first use.
    """

    def __init__(self, wowsims_dir: Path) -> None:
        self.dir = wowsims_dir
        self._names: dict | None = None
        self._db: dict[int, dict] | None = None
        self._by_db_name: dict[str, int] | None = None
        self._name_by_id: dict[int, str] | None = None

    def names(self) -> dict:
        """``names.json``: SIML name -> id tables for items, suffixes and enchants."""
        if self._names is None:
            self._names = json.loads((self.dir / "sim/siml/names.json").read_text())
        return self._names

    def db(self) -> dict[int, dict]:
        """``db.json``'s items by id."""
        if self._db is None:
            raw = json.loads((self.dir / "assets/database/db.json").read_text())
            self._db = {item["id"]: item for item in raw["items"]}
        return self._db

    def _by_name(self) -> dict[str, int]:
        if self._by_db_name is None:
            self._by_db_name = {item["name"].casefold(): item_id for item_id, item in self.db().items()}
        return self._by_db_name

    def item_name_by_id(self, item_id: int) -> str | None:
        """The SIML name of ``item_id``, or ``None`` if the sim doesn't know the item."""
        if self._name_by_id is None:
            self._name_by_id = {}
            for name, candidate_id in self.names()["items"].items():
                self._name_by_id.setdefault(candidate_id, name)
        return self._name_by_id.get(item_id)

    def item_slots(self, item_id: int, *, dual_wield: bool) -> tuple[SimSlot, ...]:
        """The sim slot(s) ``item_id`` can go in, from its ``ItemType``/``HandType``/``WeaponType`` proto enum numbers.

        Without ``dual_wield``, weapons stay out of the off hand; shields and held-in-off-hand items still go there.
        """
        item = self.db().get(item_id)
        if not item:
            return ()
        item_type = item.get("type")
        if item_type == _ITEM_TYPE_FINGER:
            return AMBIGUOUS_SLOT_PAIRS["finger"]
        if item_type == _ITEM_TYPE_TRINKET:
            return AMBIGUOUS_SLOT_PAIRS["trinket"]
        if item_type == _ITEM_TYPE_WEAPON:
            return _weapon_slots(item, dual_wield=dual_wield)
        if isinstance(item_type, int):
            return _ITEM_TYPE_SLOT.get(item_type, ())
        return ()

    def resolve_item(self, ref: str) -> tuple[int, str]:
        """``ref`` (a numeric id, a wowhead URL, or a name) -> ``(item_id, siml_name)``, or raise with suggestions."""
        match = _WOWHEAD_ITEM_RE.search(ref)
        candidate = match.group(1) if match else ref
        if candidate.isdigit():
            item_id = int(candidate)
            name = self.item_name_by_id(item_id)
            if not name:
                msg = f"item id {item_id} is not in the sim database"
                raise SimEngineError(msg)
            return item_id, name
        snaked = snake(ref)
        if snaked in self.names()["items"]:
            return self.names()["items"][snaked], snaked
        item_id = self._by_name().get(ref.strip().casefold())
        if item_id is not None:
            name = self.item_name_by_id(item_id)
            if name:
                return item_id, name
        suggestions = [name for name in self.names()["items"] if snaked in name][:5]
        msg = f"unknown item {ref!r}"
        if suggestions:
            msg += f"; close matches: {', '.join(suggestions)}"
        raise SimEngineError(msg)

    def resolve_suffix(self, ref: str) -> str:
        """``ref`` as a SIML suffix name (``of_the_bear``), or raise with suggestions."""
        snaked = snake(ref)
        if snaked in self.names()["suffixes"]:
            return snaked
        suggestions = [name for name in self.names()["suffixes"] if snaked in name][:5]
        msg = f"unknown suffix {ref!r}"
        if suggestions:
            msg += f"; close matches: {', '.join(suggestions)}"
        raise SimEngineError(msg)

    def resolve_enchant(self, ref: str) -> str | None:
        """``ref`` as a SIML enchant name, or ``None`` if it has no match (caller notes the skip)."""
        snaked = snake(ref)
        if snaked in self.names()["enchants"]:
            return snaked
        matches = [name for name in self.names()["enchants"] if snaked and snaked in name]
        return matches[0] if len(matches) == 1 else None


@functools.cache
def item_db(wowsims_dir: Path) -> ItemDB:
    """The shared :class:`ItemDB` for a checkout."""
    return ItemDB(wowsims_dir)


def gear_from_sheet(sheet: CharacterSheet, db: ItemDB) -> tuple[dict[SimSlot, GearEntry], list[str]]:
    """The character's baseline gear from its Battle.net sheet, and notes for anything skipped."""
    gear: dict[SimSlot, GearEntry] = {}
    notes: list[str] = []
    for piece in sheet.gear:
        slot = API_SLOTS.get(piece.slot)
        if not slot:
            continue
        gear[slot] = _gear_entry_from_api(piece, db, notes)
    return gear, notes


def _gear_entry_from_api(piece: CharacterGear, db: ItemDB, notes: list[str]) -> GearEntry:
    name = db.item_name_by_id(piece.item_id)
    if not name:
        notes.append(f"{piece.name} (id {piece.item_id}) isn't in the sim database and was left unequipped")
        return GearEntry(name="", item_id=piece.item_id)
    suffix = None
    base = db.db().get(piece.item_id, {}).get("name", "")
    if base and piece.name != base and piece.name.startswith(base):
        suffix_text = piece.name[len(base) :].strip()
        try:
            suffix = db.resolve_suffix(suffix_text)
        except SimEngineError:
            notes.append(f"{piece.name}: couldn't map suffix {suffix_text!r}")
    enchant = None
    for enchant_text in piece.enchantments:
        enchant = db.resolve_enchant(enchant_text)
        if enchant is None:
            notes.append(f"{piece.name}: couldn't map enchant {enchant_text!r}; simmed without it")
        break
    return GearEntry(name=name, item_id=piece.item_id, suffix=suffix, enchant=enchant, display_name=piece.name)


def resolve_sim_item(item: SimItem, db: ItemDB, *, dual_wield: bool) -> ResolvedSwap:
    """A requested :class:`SimItem` resolved to a :class:`GearEntry` and the slot(s) it can go in for this spec."""
    item_id, name = db.resolve_item(item.item)
    notes: list[str] = []
    suffix = None
    if item.suffix:
        suffix = db.resolve_suffix(item.suffix)
    enchant = None
    if item.enchant:
        enchant = db.resolve_enchant(item.enchant)
        if enchant is None:
            notes.append(f"{item.item}: couldn't map enchant {item.enchant!r}; simmed without it")
    display_name = db.db().get(item_id, {}).get("name", name)
    entry = GearEntry(name=name, item_id=item_id, suffix=suffix, enchant=enchant, display_name=display_name)
    valid = db.item_slots(item_id, dual_wield=dual_wield)
    wanted_off_hand = item.slot == "off_hand" or (not item.slot and not valid)
    if wanted_off_hand and "off_hand" in db.item_slots(item_id, dual_wield=True) and "off_hand" not in valid:
        msg = f"{item.item} is a weapon for the off hand, and only warriors, rogues and hunters can dual-wield"
        raise SimEngineError(msg)
    if item.slot:
        if valid and item.slot not in valid:
            msg = f"{item.item} doesn't fit in {item.slot} (fits: {', '.join(valid)})"
            raise SimEngineError(msg)
        candidates: tuple[SimSlot, ...] = (item.slot,)
    else:
        candidates = valid
        if not candidates:
            msg = f"{item.item} needs a slot (couldn't tell which slot it fits)"
            raise SimEngineError(msg)
    return ResolvedSwap(entry=entry, candidate_slots=candidates, notes=notes)


def gear_siml(gear: dict[SimSlot, GearEntry]) -> str:
    """The ``gear:`` section for ``gear`` (slot -> entry), in the sim's slot order."""
    rows = [gear[slot].row(slot) for slot in SLOT_ORDER if gear.get(slot) and gear[slot].name]
    return "gear:\n" + "\n".join(rows) + "\n"


@dataclass
class SpecPreset:
    """A spec's default talents and rotation file, read from its ``ui/specs/<class>/<spec>`` preset files."""

    talents: str
    rotation: Path


def _default_apl_file(directory: Path) -> Path | None:
    apls = directory / "apls"
    if not apls.is_dir():
        return None
    for candidate in (apls / "default.apl.siml", apls / "default.apl.json"):
        if candidate.exists():
            return candidate
    files = sorted(apls.glob("*.apl.siml")) or sorted(apls.glob("*.apl.json"))
    return files[0] if files else None


# Sections and lines of a setup file that make up its rotation; everything else (gear, buffs, encounter…) is the
# preset's own scenario, which the generated setup replaces.
_ROTATION_SECTION_RE = re.compile(r'^(apl|prepull|priority|cooldowns|group "[^"]*"):')
_TOP_LEVEL_LINE_RE = re.compile(r"^\S")


def _inline_rotation(defaults_text: str) -> str | None:
    """The rotation written inline in a ``defaults.siml`` (its var/def lines and rotation sections), or ``None``."""
    kept: list[str] = []
    keeping = False
    for line in defaults_text.splitlines():
        if _TOP_LEVEL_LINE_RE.match(line):
            keeping = bool(_ROTATION_SECTION_RE.match(line)) or line.startswith(("var ", "def "))
        if keeping:
            kept.append(line)
    if not any(line.startswith("priority:") for line in kept):
        return None
    return "\n".join(kept) + "\n"


def _rotation_cache_file(class_name: str, spec: str) -> Path:
    directory = Path(tempfile.gettempdir()) / "sidequest-wowsims"
    directory.mkdir(exist_ok=True)
    return directory / f"{class_name}_{spec}.apl.siml"


async def _print_json_apl(wowsimcli: Path, apl_file: Path, spec: str, cwd: Path) -> str:
    """A JSON rotation preset as SIML text, via ``wowsimcli siml print``."""
    proc = await asyncio.create_subprocess_exec(
        str(wowsimcli),
        "siml",
        "print",
        "-kind",
        "apl",
        "-spec",
        spec,
        str(apl_file),
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"couldn't convert {apl_file.name} to SIML: {stderr.decode(errors='replace')[-500:]}"
        raise SimEngineError(msg)
    return stdout.decode()


_TALENTS_LINE_RE = re.compile(r'^talents\s+"([^"]*)"', re.MULTILINE)
_PRESET_TALENTS_RE = re.compile(r"talentsString:\s*'([-0-9]+)'")
_USE_APL_RE = re.compile(r'^use\s+"([^"]*apl[^"]*)"', re.MULTILINE)


def _talents_from_presets_ts(directory: Path) -> str | None:
    presets = directory / "presets.ts"
    if not presets.exists():
        return None
    match = _PRESET_TALENTS_RE.search(presets.read_text())
    return match.group(1) if match else None


async def load_spec_preset(wowsims_dir: Path, wowsimcli: Path, class_name: str, spec: str) -> SpecPreset:
    """The spec's default talents and a rotation file the generated setup can ``use``.

    The rotation is, in order: the file ``defaults.siml`` uses, the rotation written inline in ``defaults.siml``
    (copied to a cache file), the spec's default ``apls/*.apl.siml``, or its ``apls/*.apl.json`` printed as SIML into
    a cache file. A rotation file is used by path rather than pasted in, so its own ``var`` lines and relative
    ``use`` lines keep working.
    """
    directory = spec_dir(wowsims_dir, class_name, spec)
    line = spec_line(class_name, spec)
    defaults_file = directory / "defaults.siml"
    defaults_text = defaults_file.read_text() if defaults_file.exists() else ""
    talents_match = _TALENTS_LINE_RE.search(defaults_text)
    talents = talents_match.group(1) if talents_match else _talents_from_presets_ts(directory) or ""

    if use_match := _USE_APL_RE.search(defaults_text):
        return SpecPreset(talents=talents, rotation=(directory / use_match.group(1)).resolve())
    if inline := _inline_rotation(defaults_text):
        rotation = _rotation_cache_file(class_name, spec)
        rotation.write_text(f"siml 1\nspec {line}\n\n{inline}")
        return SpecPreset(talents=talents, rotation=rotation)
    apl_file = _default_apl_file(directory)
    if apl_file is None:
        msg = f"{class_name.title()} {spec} can't be simmed: the sim has no default rotation for it"
        raise SimEngineError(msg)
    if apl_file.suffix == ".siml":
        return SpecPreset(talents=talents, rotation=apl_file.resolve())
    rotation = _rotation_cache_file(class_name, spec)
    rotation.write_text(await _print_json_apl(wowsimcli, apl_file, line, wowsims_dir))
    return SpecPreset(talents=talents, rotation=rotation)


def build_siml(
    *,
    class_name: str,
    spec: str,
    race: str,
    talents: str,
    rotation: Path,
    gear: dict[SimSlot, GearEntry],
    targets: int,
    mob: str,
    duration: int,
    role: str,
    iterations: int = SIM_ITERATIONS,
) -> str:
    """The full ``.siml`` setup text for one (targets, mob) scenario."""
    race_name = RACE_SIML_NAME.get(race, "human")
    target_rows = "\n".join(
        f"""  targets(id={31146 + i},
      name="Mob {i + 1}",
      level={TARGET_LEVEL},
      mob_type={mob},
      stats(attack_power={TARGET_ATTACK_POWER}, block_value={TARGET_BLOCK_VALUE}, armor={TARGET_ARMOR},
          health={TARGET_HEALTH}),
      min_base_damage={TARGET_MIN_BASE_DAMAGE},
      damage_spread={TARGET_DAMAGE_SPREAD},
      swing_speed={TARGET_SWING_SPEED},
      parry_haste)"""
        for i in range(targets)
    )
    settings_lines = [
        f"  race {race_name}",
        "  reaction_time 100ms",
    ]
    if role == "tank":
        settings_lines += ["  in_front_of_target", "  distance_from_target 5", "  tanks player1"]
    settings_lines.append(
        f"  healing_model(hps={HEALING_MODEL_HPS}, cadence_seconds={HEALING_MODEL_CADENCE_SECONDS}, "
        f"cadence_variation={HEALING_MODEL_CADENCE_VARIATION})"
    )
    # The quotes in a `use` path can't be escaped in SIML; the rotation paths are ours (checkout or temp dir).
    return f"""siml 1
spec {spec_line(class_name, spec)}
talents "{talents}"
use "{rotation}"

settings:
{chr(10).join(settings_lines)}

{gear_siml(gear)}
sim: iterations {iterations}

encounter:
  duration {duration}
  duration_variation 10
{target_rows}
"""


async def run_scenario(wowsimcli: Path, siml_text: str, cwd: Path) -> dict:
    """Run one ``.siml`` setup through ``wowsimcli sim`` and return the player's raw metrics dict.

    A run longer than ``SIM_TIMEOUT_SECONDS`` is killed and fails the job.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".siml", delete=False) as handle:
        handle.write(siml_text)
        path = Path(handle.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "nice",
            "-n",
            "10",
            str(wowsimcli),
            "sim",
            "--infile",
            str(path),
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SIM_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            msg = f"sim timed out after {SIM_TIMEOUT_SECONDS}s"
            raise SimEngineError(msg) from None
        except asyncio.CancelledError:  # app shutting down: don't leave the sim running on its own
            proc.kill()
            raise
        if proc.returncode != 0:
            msg = f"sim failed: {stderr.decode(errors='replace')[-1000:]}"
            raise SimEngineError(msg)
        payload = json.loads(stdout)
        return payload["raidMetrics"]["parties"][0]["players"][0]
    finally:
        await asyncio.to_thread(path.unlink, missing_ok=True)


def metrics_from_player(player: dict, role: str) -> dict:
    """``{dps, tps, dtps, hps}`` (each ``float | None``) and their standard deviations, from one player's raw JSON."""

    def avg_sd(key: str) -> tuple[float | None, float]:
        block = player.get(key)
        if not block:
            return None, 0.0
        return block.get("avg"), block.get("stdev", 0.0)

    dps, dps_sd = avg_sd("dps")
    tps, tps_sd = avg_sd("threat")
    dtps, dtps_sd = avg_sd("dtps")
    hps, hps_sd = avg_sd("hps")
    return {
        "dps": dps,
        "tps": tps if role == "tank" else None,
        "dtps": dtps if role == "tank" else None,
        "hps": hps if (role == "healer" and hps) else None,
        "_sd": {"dps": dps_sd, "tps": tps_sd, "dtps": dtps_sd, "hps": hps_sd},
    }


def delta_pct(base: float | None, swapped: float | None) -> float | None:
    """``swapped`` as a percent change from ``base``, or ``None`` when either is missing or ``base`` is 0."""
    if base is None or swapped is None or base == 0:
        return None
    return 100 * (swapped - base) / base


def is_noise(base: float | None, swapped: float | None, base_sd: float, swapped_sd: float, iterations: int) -> bool:
    """Whether the change is within ``STANDARD_ERRORS_FOR_NOISE`` standard errors of the two means."""
    if base is None or swapped is None:
        return False
    standard_error = (base_sd**2 / iterations + swapped_sd**2 / iterations) ** 0.5
    return abs(swapped - base) <= STANDARD_ERRORS_FOR_NOISE * standard_error


def scenarios(targets: list[int], mobs: list[SimMobType]) -> list[tuple[int, SimMobType]]:
    """Every (targets, mob) pair to sim."""
    return list(itertools.product(targets, mobs))
