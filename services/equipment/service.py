"""Equipment slot logic built on top of the inventory blob.

Equipped items are removed from normal containers and stored in equipment slots.
Items with a container profile, such as backpacks or pouches, add a dedicated
inventory container while equipped. Slot validation stays here so the LLM cannot
equip items by directly mutating JSON state.
"""

import json
import math
from copy import deepcopy
from typing import Any, Dict, Optional

from models import Character, CharacterSkill, SkillDefinition, db
from services.inventory.constants import DEFAULT_BASE_CONTAINER, HAND_CONTAINER_IDS, SIZE_ORDER
from services.inventory.repository import load_inventory_blob, save_inventory_blob
from services.status_effects import get_status_effect_modifier_bundle

from .constants import (
    BELT_ATTACHMENT_SLOTS,
    BELT_POUCH_SIZES,
    EQUIPMENT_SLOTS,
    HAND_SLOTS,
    SLOT_ALIASES,
    SLOT_LABELS,
)

DEFAULT_WEAPON_PROFILE = {
    "weapon_family": "improvised",
    "damage_type": "blunt",
    "base_damage_min": 4,
    "base_damage_max": 10,
    "scaling": {"strength": 0.55, "dexterity": 0.30},
    "skill_name": "Athletics",
    "attack_mode": "melee",
}

WEAPON_FAMILY_PROFILES = {
    "unarmed": {
        "damage_type": "blunt",
        "base_damage_min": 3,
        "base_damage_max": 8,
        "scaling": {"strength": 0.45, "dexterity": 0.20},
        "skill_name": "Athletics",
        "attack_mode": "melee",
    },
    "improvised": DEFAULT_WEAPON_PROFILE,
    "dagger": {
        "damage_type": "pierce",
        "base_damage_min": 8,
        "base_damage_max": 14,
        "scaling": {"dexterity": 0.70, "strength": 0.20},
        "skill_name": "Swordsmanship",
        "attack_mode": "melee",
    },
    "rapier": {
        "damage_type": "pierce",
        "base_damage_min": 8,
        "base_damage_max": 14,
        "scaling": {"dexterity": 0.75, "strength": 0.15},
        "skill_name": "Swordsmanship",
        "attack_mode": "melee",
    },
    "sword": {
        "damage_type": "slash",
        "base_damage_min": 10,
        "base_damage_max": 18,
        "scaling": {"strength": 0.55, "dexterity": 0.30},
        "skill_name": "Swordsmanship",
        "attack_mode": "melee",
    },
    "greatsword": {
        "damage_type": "slash",
        "base_damage_min": 14,
        "base_damage_max": 24,
        "scaling": {"strength": 0.80, "dexterity": 0.10},
        "skill_name": "Swordsmanship",
        "attack_mode": "melee",
    },
    "axe_hammer": {
        "damage_type": "blunt",
        "base_damage_min": 14,
        "base_damage_max": 24,
        "scaling": {"strength": 0.85, "constitution": 0.10},
        "skill_name": "Axes & Hammers",
        "attack_mode": "melee",
    },
    "mace_club": {
        "damage_type": "blunt",
        "base_damage_min": 12,
        "base_damage_max": 20,
        "scaling": {"strength": 0.80, "constitution": 0.10},
        "skill_name": "Axes & Hammers",
        "attack_mode": "melee",
    },
    "polearm": {
        "damage_type": "pierce",
        "base_damage_min": 12,
        "base_damage_max": 22,
        "scaling": {"strength": 0.65, "dexterity": 0.20},
        "skill_name": "Polearms",
        "attack_mode": "melee",
    },
    "bow": {
        "damage_type": "pierce",
        "base_damage_min": 10,
        "base_damage_max": 18,
        "scaling": {"dexterity": 0.80, "perception": 0.15},
        "skill_name": "Archery",
        "attack_mode": "ranged",
    },
    "crossbow": {
        "damage_type": "pierce",
        "base_damage_min": 12,
        "base_damage_max": 20,
        "scaling": {"dexterity": 0.70, "perception": 0.20},
        "skill_name": "Archery",
        "attack_mode": "ranged",
    },
    "staff": {
        "damage_type": "arcane",
        "base_damage_min": 10,
        "base_damage_max": 20,
        "scaling": {"intelligence": 0.65, "perception": 0.20},
        "skill_name": "Arcane Lore",
        "attack_mode": "magic",
    },
    "wand": {
        "damage_type": "arcane",
        "base_damage_min": 12,
        "base_damage_max": 22,
        "scaling": {"intelligence": 0.75, "perception": 0.15},
        "skill_name": "Arcane Lore",
        "attack_mode": "magic",
    },
}

WEAPON_NAME_KEYWORDS = (
    ("greatsword", "greatsword"),
    ("zweihandschwert", "greatsword"),
    ("warhammer", "axe_hammer"),
    ("battleaxe", "axe_hammer"),
    ("greataxe", "axe_hammer"),
    ("axe", "axe_hammer"),
    ("axt", "axe_hammer"),
    ("hammer", "axe_hammer"),
    ("club", "mace_club"),
    ("keule", "mace_club"),
    ("mace", "mace_club"),
    ("rapier", "rapier"),
    ("dagger", "dagger"),
    ("dolch", "dagger"),
    ("spear", "polearm"),
    ("halberd", "polearm"),
    ("polearm", "polearm"),
    ("bow", "bow"),
    ("bogen", "bow"),
    ("crossbow", "crossbow"),
    ("staff", "staff"),
    ("stab", "staff"),
    ("wand", "wand"),
    ("sword", "sword"),
    ("schwert", "sword"),
)

ARMOR_CLASS_BONUSES = {
    "light": {"dodge_bonus": 8.0, "block_bonus": -4.0},
    "medium": {"dodge_bonus": 2.0, "block_bonus": 2.0},
    "heavy": {"dodge_bonus": -8.0, "block_bonus": 10.0},
}

ATTRIBUTE_KEYS = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "perception",
    "charisma",
)

RARITY_QUALITY_TIERS = {
    "common": 0,
    "mundane": 0,
    "simple": 0,
    "uncommon": 1,
    "fine": 1,
    "quality": 1,
    "masterwork": 2,
    "rare": 2,
    "epic": 3,
    "mythic": 3,
    "legendary": 4,
    "artifact": 4,
}

LEVEL_BAND_THRESHOLDS = (
    10,
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
)

RARITY_LEVEL_ATTRIBUTE_BONUSES = {
    "common":     (0, 0, 0, 1, 1, 2, 2, 3, 4, 5),
    "uncommon":   (0, 1, 1, 2, 3, 4, 5, 6, 7, 8),
    "fine":       (0, 1, 1, 2, 3, 4, 5, 6, 7, 8),
    "quality":    (0, 1, 1, 2, 3, 4, 5, 6, 7, 8),
    "rare":       (0, 1, 2, 3, 4, 5, 6, 8, 10, 12),
    "masterwork": (0, 1, 2, 3, 4, 5, 6, 8, 10, 12),
    "epic":       (0, 2, 3, 5, 6, 8, 10, 12, 14, 16),
    "mythic":     (0, 2, 3, 5, 6, 8, 10, 12, 14, 16),
    "legendary":  (0, 2, 4, 6, 8, 10, 12, 14, 17, 20),
    "artifact":   (1, 3, 5, 8, 10, 13, 16, 19, 22, 26),
}

COMBAT_ATTRIBUTE_SOFT_CAP = 100.0
COMBAT_ATTRIBUTE_OVERCAP_WINDOW = 20.0


class EquipmentOperationResult:
    """Result object shared by equip and unequip operations."""

    def __init__(
        self,
        success: bool,
        message: str,
        equipment: Dict[str, Any],
        inventory: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.equipment = equipment
        self.inventory = inventory
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the operation result for tool responses."""

        return {
            "success": self.success,
            "message": self.message,
            "equipment": self.equipment,
            "inventory": self.inventory,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Inventory/equipment state helpers
# ---------------------------------------------------------------------------


def _get_containers(inventory_blob: Dict[str, Any]):
    """Return inventory containers, creating the base container if missing."""

    inventory_blob.setdefault("inventory", {})
    inventory_blob["inventory"].setdefault("containers", [deepcopy(DEFAULT_BASE_CONTAINER)])
    return inventory_blob["inventory"]["containers"]


def _get_equipment_state(inventory_blob: Dict[str, Any]) -> Dict[str, Any]:
    """Return equipment state and ensure every known slot exists."""

    equipment = inventory_blob.setdefault("equipment", {})
    slots = equipment.setdefault("slots", {})

    for slot in EQUIPMENT_SLOTS:
        slots.setdefault(slot, None)

    return equipment


def _normalize_slot(slot: Optional[str]) -> Optional[str]:
    """Normalize user/model slot names to canonical equipment slot ids."""

    if not slot:
        return None

    normalized = slot.strip().lower().replace("-", "_").replace(" ", "_")
    return SLOT_ALIASES.get(normalized, normalized)


# ---------------------------------------------------------------------------
# Item classification helpers
# ---------------------------------------------------------------------------


def _is_placeholder(item: Optional[Dict[str, Any]]) -> bool:
    """Return whether a slot item only marks a secondary occupied slot."""

    return bool(item and item.get("placeholder"))


def _normalized_item_type(item: Dict[str, Any]) -> str:
    return (item.get("item_type") or "").strip().lower()


def _normalized_item_size(item: Dict[str, Any]) -> str:
    return (item.get("size") or "small").strip().lower()


def _is_weapon(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) in ("weapon", "tool")


def _is_shield(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) == "shield"


def _is_backpack_item(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) in ("backpack", "rucksack")


def _is_belt_pouch(item: Dict[str, Any]) -> bool:
    """Return whether an item is small enough and container-like for belt slots."""

    if (
        _normalized_item_type(item) in ("pouch", "belt_pouch", "coin_pouch", "small_pouch")
        and _normalized_item_size(item) in BELT_POUCH_SIZES
    ):
        return True

    if (
        _normalized_item_type(item) in ("bag", "container")
        and _normalized_item_size(item) in BELT_POUCH_SIZES
        and _container_profile_from_item(item)
    ):
        return True

    return False


def _skill_name_key(value: str) -> str:
    normalized = (value or "").strip().lower()
    return "".join(ch for ch in normalized if ch.isalnum())


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _normalize_weapon_family(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "greataxe": "axe_hammer",
        "great_axe": "axe_hammer",
        "axe": "axe_hammer",
        "hammer": "axe_hammer",
        "club": "mace_club",
        "mace": "mace_club",
        "longsword": "sword",
        "katana": "sword",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in WEAPON_FAMILY_PROFILES else "improvised"


def _infer_weapon_family_from_item(item: Dict[str, Any]) -> str:
    explicit_family = item.get("weapon_family")
    if explicit_family:
        return _normalize_weapon_family(explicit_family)

    combat_profile = item.get("combat_profile")
    if isinstance(combat_profile, dict) and combat_profile.get("weapon_family"):
        return _normalize_weapon_family(combat_profile.get("weapon_family"))

    name = str(item.get("name", "")).lower()
    for keyword, family in WEAPON_NAME_KEYWORDS:
        if keyword in name:
            return family

    item_type = _normalized_item_type(item)
    if item_type == "weapon":
        return "improvised"
    return "unarmed"


def _parse_scaling(raw_scaling: Any, default_scaling: Dict[str, float]) -> Dict[str, float]:
    if isinstance(raw_scaling, str):
        try:
            raw_scaling = json.loads(raw_scaling)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_scaling = None
    if not isinstance(raw_scaling, dict):
        return dict(default_scaling)

    normalized = {}
    for key, value in raw_scaling.items():
        key_normalized = str(key or "").strip().lower()
        if key_normalized not in {"strength", "dexterity", "constitution", "intelligence", "perception", "charisma"}:
            continue
        normalized[key_normalized] = max(0.0, _coerce_float(value, 0.0))

    return normalized or dict(default_scaling)


def _build_weapon_profile(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not item:
        base = WEAPON_FAMILY_PROFILES["unarmed"]
        return {"weapon_family": "unarmed", "item_level": 1, **base}

    family = _infer_weapon_family_from_item(item)
    base_profile = dict(WEAPON_FAMILY_PROFILES.get(family, DEFAULT_WEAPON_PROFILE))
    combat_profile = item.get("combat_profile") if isinstance(item.get("combat_profile"), dict) else {}

    damage_type = str(
        combat_profile.get("damage_type")
        or item.get("damage_type")
        or base_profile["damage_type"]
    ).strip().lower()
    base_min = _coerce_int(combat_profile.get("base_damage_min", item.get("base_damage_min")), base_profile["base_damage_min"])
    base_max = _coerce_int(combat_profile.get("base_damage_max", item.get("base_damage_max")), base_profile["base_damage_max"])
    if base_max < base_min:
        base_max = base_min
    scaling = _parse_scaling(
        combat_profile.get("scaling", item.get("scaling")),
        base_profile["scaling"],
    )
    skill_name = str(combat_profile.get("skill_name") or item.get("skill_name") or base_profile["skill_name"]).strip() or base_profile["skill_name"]
    attack_mode = str(combat_profile.get("attack_mode") or item.get("attack_mode") or base_profile["attack_mode"]).strip().lower()
    item_level = _coerce_int(combat_profile.get("item_level", item.get("item_level")), 1)

    return {
        "weapon_family": family,
        "damage_type": damage_type,
        "base_damage_min": max(1, base_min),
        "base_damage_max": max(1, base_max),
        "scaling": scaling,
        "skill_name": skill_name,
        "item_level": max(1, min(100, item_level)),
        "attack_mode": attack_mode if attack_mode in {"melee", "ranged", "magic"} else base_profile["attack_mode"],
    }


def _find_main_hand_weapon(equipment_slots: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    main_hand = equipment_slots.get("main_hand")
    if main_hand and not _is_placeholder(main_hand):
        if _is_weapon(main_hand):
            return main_hand
    off_hand = equipment_slots.get("off_hand")
    if off_hand and not _is_placeholder(off_hand) and _is_weapon(off_hand):
        return off_hand
    return None


def _load_character_skill_level(character_id: int, skill_name: str) -> int:
    normalized = _skill_name_key(skill_name)
    for skill_def in SkillDefinition.query.filter_by(is_active=True).all():
        if _skill_name_key(skill_def.name) != normalized:
            continue
        row = CharacterSkill.query.filter_by(character_id=character_id, skill_id=skill_def.id).first()
        if row:
            return max(0, int(row.skill_level or 0))
        return 0
    return 0


def _attribute_value(attributes, key: str) -> int:
    return max(0, int(getattr(attributes, key, 0) or 0))


def normalize_combat_attribute_value(value: Any) -> float:
    """Return combat-facing attribute value with diminishing returns past 100."""

    numeric_value = max(0.0, float(value or 0.0))
    if numeric_value <= COMBAT_ATTRIBUTE_SOFT_CAP:
        return numeric_value

    overcap = numeric_value - COMBAT_ATTRIBUTE_SOFT_CAP
    scaled_overcap = (
        100.0
        * math.log1p(overcap)
        / math.log(COMBAT_ATTRIBUTE_SOFT_CAP + 1.0)
    )
    return COMBAT_ATTRIBUTE_SOFT_CAP + (
        scaled_overcap * (COMBAT_ATTRIBUTE_OVERCAP_WINDOW / 100.0)
    )


def _normalize_modifier_attribute_key(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "str": "strength",
        "dex": "dexterity",
        "con": "constitution",
        "int": "intelligence",
        "per": "perception",
        "cha": "charisma",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in ATTRIBUTE_KEYS else None


def _normalize_skill_bonus_name(value: Any) -> str:
    return str(value or "").strip()


def _load_modifier_dict(raw_value: Any) -> Dict[str, Any]:
    if raw_value in (None, ""):
        return {}
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _coerce_bonus_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _item_level_value(item: Optional[Dict[str, Any]]) -> int:
    if not item:
        return 1
    combat_profile = item.get("combat_profile") if isinstance(item.get("combat_profile"), dict) else {}
    return max(1, min(100, _coerce_int(combat_profile.get("item_level", item.get("item_level")), 1)))


def _item_quality_tier(item: Dict[str, Any]) -> int:
    raw_value = (
        item.get("quality")
        or item.get("rarity")
        or item.get("quality_tier")
        or item.get("rarity_tier")
    )
    if isinstance(raw_value, (int, float)):
        return max(0, min(4, int(raw_value)))
    normalized = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return RARITY_QUALITY_TIERS.get(normalized, 0)


def _normalized_item_rarity(item: Dict[str, Any]) -> str:
    raw_value = (
        item.get("quality")
        or item.get("rarity")
        or item.get("quality_tier")
        or item.get("rarity_tier")
    )
    normalized = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or "common"


def _item_level_band_index(item_level: int) -> int:
    level_value = max(1, min(100, int(item_level or 1)))
    for index, threshold in enumerate(LEVEL_BAND_THRESHOLDS):
        if level_value < threshold:
            return index
    return len(LEVEL_BAND_THRESHOLDS)


def _implicit_primary_attribute_bonus(item: Dict[str, Any]) -> int:
    item_level = _item_level_value(item)
    rarity = _normalized_item_rarity(item)
    band_index = _item_level_band_index(item_level)
    table = RARITY_LEVEL_ATTRIBUTE_BONUSES.get(rarity)
    if table is None:
        table = RARITY_LEVEL_ATTRIBUTE_BONUSES.get("common", (0,) * 10)
    return int(table[min(band_index, len(table) - 1)])


def _primary_scaling_attributes(profile: Dict[str, Any]) -> list[str]:
    scaling = profile.get("scaling", {}) if isinstance(profile, dict) else {}
    sorted_attributes = sorted(
        (
            (attribute_name, float(weight))
            for attribute_name, weight in scaling.items()
            if _normalize_modifier_attribute_key(attribute_name)
        ),
        key=lambda entry: entry[1],
        reverse=True,
    )
    return [attribute_name for attribute_name, _weight in sorted_attributes]


def _explicit_equipment_modifiers(item: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    stat_modifiers = _load_modifier_dict(item.get("stat_modifiers"))
    attribute_modifiers = _load_modifier_dict(item.get("attribute_modifiers"))
    resource_modifiers = _load_modifier_dict(item.get("resource_modifiers"))
    skill_modifiers = _load_modifier_dict(item.get("skill_modifiers"))

    if not attribute_modifiers and isinstance(stat_modifiers.get("attributes"), dict):
        attribute_modifiers = _load_modifier_dict(stat_modifiers.get("attributes"))
    if not resource_modifiers and isinstance(stat_modifiers.get("resources"), dict):
        resource_modifiers = _load_modifier_dict(stat_modifiers.get("resources"))
    if not skill_modifiers and isinstance(stat_modifiers.get("skills"), dict):
        skill_modifiers = _load_modifier_dict(stat_modifiers.get("skills"))

    normalized_attributes = {}
    for raw_key, raw_value in attribute_modifiers.items():
        key = _normalize_modifier_attribute_key(raw_key)
        if not key:
            continue
        normalized_attributes[key] = normalized_attributes.get(key, 0) + _coerce_bonus_int(raw_value)

    normalized_resources = {}
    for raw_key, raw_value in resource_modifiers.items():
        key = str(raw_key or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key not in {"hp_max", "mana_max", "energy_max"}:
            continue
        normalized_resources[key] = normalized_resources.get(key, 0) + _coerce_bonus_int(raw_value)

    normalized_skills = {}
    for raw_key, raw_value in skill_modifiers.items():
        key = _normalize_skill_bonus_name(raw_key)
        if not key:
            continue
        normalized_skills[key] = normalized_skills.get(key, 0) + _coerce_bonus_int(raw_value)

    return {
        "attributes": normalized_attributes,
        "resources": normalized_resources,
        "skills": normalized_skills,
    }


def _implicit_equipment_modifiers(item: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    primary_bonus = _implicit_primary_attribute_bonus(item)
    if primary_bonus <= 0:
        return {"attributes": {}, "resources": {}, "skills": {}}

    attribute_bonuses: Dict[str, int] = {}
    item_type = _normalized_item_type(item)
    armor_class = _extract_item_armor_class(item)

    if item_type in {"weapon", "tool"}:
        profile = _build_weapon_profile(item)
        primary_attributes = _primary_scaling_attributes(profile)
        if primary_attributes:
            attribute_bonuses[primary_attributes[0]] = primary_bonus
        if len(primary_attributes) > 1 and primary_bonus >= 4:
            secondary_attribute = primary_attributes[1]
            secondary_bonus = max(1, int(round(primary_bonus * 0.35)))
            attribute_bonuses[secondary_attribute] = attribute_bonuses.get(secondary_attribute, 0) + secondary_bonus
    elif item_type in {"armor", "shield", "helmet", "boots", "gloves", "clothing", "pants", "shoes", "cloak"}:
        attribute_bonuses["constitution"] = primary_bonus
        if armor_class == "light" and primary_bonus >= 3:
            secondary_bonus = max(1, int(round(primary_bonus * 0.30)))
            attribute_bonuses["dexterity"] = attribute_bonuses.get("dexterity", 0) + secondary_bonus
        elif armor_class == "heavy" and primary_bonus >= 3:
            secondary_bonus = max(1, int(round(primary_bonus * 0.30)))
            attribute_bonuses["strength"] = attribute_bonuses.get("strength", 0) + secondary_bonus
        elif armor_class == "medium" and primary_bonus >= 3:
            secondary_bonus = max(1, int(round(primary_bonus * 0.20)))
            attribute_bonuses["strength"] = attribute_bonuses.get("strength", 0) + secondary_bonus
            attribute_bonuses["dexterity"] = attribute_bonuses.get("dexterity", 0) + secondary_bonus
    elif item_type in {"ring", "amulet", "trinket"}:
        attribute_bonuses["charisma"] = max(1, int(round(primary_bonus * 0.75)))

    return {
        "attributes": attribute_bonuses,
        "resources": {},
        "skills": {},
    }


def _merge_modifier_maps(base: Dict[str, int], extra: Dict[str, int]) -> Dict[str, int]:
    merged = dict(base)
    for key, value in extra.items():
        merged[key] = merged.get(key, 0) + int(value or 0)
    return merged


def _item_total_equipment_modifiers(item: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    explicit = _explicit_equipment_modifiers(item)
    implicit = _implicit_equipment_modifiers(item)
    return {
        "attributes": _merge_modifier_maps(explicit["attributes"], implicit["attributes"]),
        "resources": _merge_modifier_maps(explicit["resources"], implicit["resources"]),
        "skills": _merge_modifier_maps(explicit["skills"], implicit["skills"]),
    }


def _display_attribute_label(attribute_key: str) -> str:
    labels = {
        "strength": "Strength",
        "dexterity": "Dexterity",
        "constitution": "Constitution",
        "intelligence": "Intelligence",
        "perception": "Perception",
        "charisma": "Charisma",
    }
    return labels.get(attribute_key, str(attribute_key or "").replace("_", " ").title())


def _display_resource_label(resource_key: str) -> str:
    labels = {
        "hp_max": "HP Max",
        "mana_max": "Mana Max",
        "energy_max": "Energy Max",
    }
    return labels.get(resource_key, str(resource_key or "").replace("_", " ").title())


def _signed_bonus_text(value: Any) -> str:
    numeric_value = int(value or 0)
    return f"+{numeric_value}" if numeric_value >= 0 else str(numeric_value)


def build_item_bonus_lines(item: Dict[str, Any]) -> list[str]:
    """Return UI-friendly bonus summary lines for one item."""

    modifiers = _item_total_equipment_modifiers(item or {})
    lines = []

    for attribute_key in ATTRIBUTE_KEYS:
        bonus_value = int(modifiers["attributes"].get(attribute_key, 0) or 0)
        if bonus_value:
            lines.append(f"{_signed_bonus_text(bonus_value)} {_display_attribute_label(attribute_key)}")

    for resource_key in ("hp_max", "mana_max", "energy_max"):
        bonus_value = int(modifiers["resources"].get(resource_key, 0) or 0)
        if bonus_value:
            lines.append(f"{_signed_bonus_text(bonus_value)} {_display_resource_label(resource_key)}")

    for skill_name in sorted(modifiers["skills"]):
        bonus_value = int(modifiers["skills"].get(skill_name, 0) or 0)
        if bonus_value:
            lines.append(f"{_signed_bonus_text(bonus_value)} {skill_name}")

    return lines


def build_item_tooltip(item: Dict[str, Any]) -> str:
    """Build one hover tooltip string for equipment or inventory items."""

    details = [item.get("name", "Unknown Item")]
    if item.get("description"):
        details.append(item["description"])

    bonus_lines = build_item_bonus_lines(item)
    details.extend(bonus_lines)

    details.append(f"Size: {str(item.get('size', 'small')).title()}")
    details.append(f"Volume: {float(item.get('volume', 0) or 0):.1f}")
    details.append(f"Weight: {float(item.get('weight', 0) or 0):.1f}")
    return " | ".join(details)


def _build_effective_equipment_bundle(
    character_id: int,
    attributes,
    items: list[Dict[str, Any]],
) -> Dict[str, Any]:
    base_attributes = {
        key: _attribute_value(attributes, key)
        for key in ATTRIBUTE_KEYS
    }
    attribute_bonuses = {key: 0 for key in ATTRIBUTE_KEYS}
    resource_bonuses = {"hp_max": 0, "mana_max": 0, "energy_max": 0}
    skill_bonuses: Dict[str, int] = {}
    contributing_items = []

    for item in items:
        modifiers = _item_total_equipment_modifiers(item)
        if not any(modifiers[group] for group in ("attributes", "resources", "skills")):
            continue

        for key, value in modifiers["attributes"].items():
            attribute_bonuses[key] = attribute_bonuses.get(key, 0) + int(value or 0)
        for key, value in modifiers["resources"].items():
            if key in resource_bonuses:
                resource_bonuses[key] += int(value or 0)
        for key, value in modifiers["skills"].items():
            skill_bonuses[key] = skill_bonuses.get(key, 0) + int(value or 0)

        contributing_items.append({
            "item_id": item.get("item_id"),
            "name": item.get("name"),
            "item_level": _item_level_value(item),
            "quality_tier": _item_quality_tier(item),
            "modifiers": modifiers,
        })

    effective_attributes = {
        key: max(0, base_attributes[key] + attribute_bonuses.get(key, 0))
        for key in ATTRIBUTE_KEYS
    }

    return {
        "character_id": character_id,
        "attributes": {
            key: {
                "base": base_attributes[key],
                "equipment_bonus": attribute_bonuses.get(key, 0),
                "effective": effective_attributes[key],
            }
            for key in ATTRIBUTE_KEYS
        },
        "resources": {
            key: {
                "equipment_bonus": int(resource_bonuses.get(key, 0)),
            }
            for key in resource_bonuses
        },
        "skills": {
            key: {
                "equipment_bonus": int(value),
            }
            for key, value in skill_bonuses.items()
            if int(value or 0) != 0
        },
        "attribute_values": effective_attributes,
        "skill_bonus_values": {
            key: int(value)
            for key, value in skill_bonuses.items()
            if int(value or 0) != 0
        },
        "contributing_items": contributing_items,
    }


def _extract_item_combat_stat(item: Dict[str, Any], key: str, fallback: float = 0.0) -> float:
    combat_profile = item.get("combat_profile") if isinstance(item.get("combat_profile"), dict) else {}
    if key in combat_profile:
        return _coerce_float(combat_profile.get(key), fallback)
    return _coerce_float(item.get(key), fallback)


def _extract_item_armor_class(item: Dict[str, Any]) -> Optional[str]:
    combat_profile = item.get("combat_profile") if isinstance(item.get("combat_profile"), dict) else {}
    raw = combat_profile.get("armor_class", item.get("armor_class"))
    normalized = str(raw or "").strip().lower()
    return normalized if normalized in ARMOR_CLASS_BONUSES else None


def _iter_equipped_items(slots: Dict[str, Any]):
    seen = set()
    for slot in EQUIPMENT_SLOTS:
        item = slots.get(slot)
        if not item or _is_placeholder(item):
            continue
        item_id = item.get("item_id") or f"{slot}:{item.get('name', '')}"
        if item_id in seen:
            continue
        seen.add(item_id)
        yield item


def _load_multi_skill_levels(character_id: int, names: list[str]) -> Dict[str, int]:
    wanted = {_skill_name_key(name): name for name in names if name}
    levels = {name: 0 for name in names}
    if not wanted:
        return levels
    for skill_def in SkillDefinition.query.filter_by(is_active=True).all():
        key = _skill_name_key(skill_def.name)
        canonical_name = wanted.get(key)
        if not canonical_name:
            continue
        row = CharacterSkill.query.filter_by(character_id=character_id, skill_id=skill_def.id).first()
        levels[canonical_name] = max(0, int(row.skill_level or 0)) if row else 0
    return levels


def get_effective_stats(character_id: int) -> Dict[str, Any]:
    """Return always-on effective attribute/resource/skill bonuses from equipped items."""

    character = db.session.get(Character, character_id)
    if not character:
        return {"success": False, "message": "Character not found."}

    attributes = character.attributes
    if not attributes:
        return {"success": False, "message": "Character attributes not found."}

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment.get("slots", {})
    items = list(_iter_equipped_items(slots))
    bundle = _build_effective_equipment_bundle(character_id, attributes, items)

    return {
        "success": True,
        "character_id": character_id,
        "attributes": bundle["attributes"],
        "resources": bundle["resources"],
        "skills": bundle["skills"],
        "contributing_items": bundle["contributing_items"],
    }


def get_defense_profile(character_id: int) -> Dict[str, Any]:
    """Return defense-related combat profile from armor, shield, attributes and skills."""

    character = db.session.get(Character, character_id)
    if not character:
        return {"success": False, "message": "Character not found."}

    attributes = character.attributes
    if not attributes:
        return {"success": False, "message": "Character attributes not found."}

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment.get("slots", {})
    items = list(_iter_equipped_items(slots))
    effective_bundle = _build_effective_equipment_bundle(character_id, attributes, items)
    skill_levels = _load_multi_skill_levels(character_id, ["Dodging", "Blocking"])
    dodging_skill = skill_levels.get("Dodging", 0) + int(effective_bundle["skill_bonus_values"].get("Dodging", 0))
    blocking_skill = skill_levels.get("Blocking", 0) + int(effective_bundle["skill_bonus_values"].get("Blocking", 0))

    armor_rating_total = 0.0
    item_dodge_bonus_total = 0.0
    item_block_bonus_total = 0.0
    block_threshold_bonus_total = 0.0
    class_dodge_bonus_total = 0.0
    class_block_bonus_total = 0.0

    for item in items:
        item_type = _normalized_item_type(item)
        if item_type in {"armor", "shield", "helmet", "boots", "gloves"}:
            armor_rating_total += max(0.0, _extract_item_combat_stat(item, "armor_rating", 0.0))
        item_dodge_bonus_total += _extract_item_combat_stat(item, "dodge_bonus", 0.0)
        item_block_bonus_total += _extract_item_combat_stat(item, "block_bonus", 0.0)
        block_threshold_bonus_total += _extract_item_combat_stat(item, "block_threshold_bonus", 0.0)

        armor_class = _extract_item_armor_class(item)
        if armor_class:
            class_dodge_bonus_total += ARMOR_CLASS_BONUSES[armor_class]["dodge_bonus"]
            class_block_bonus_total += ARMOR_CLASS_BONUSES[armor_class]["block_bonus"]

    dexterity = int(effective_bundle["attribute_values"]["dexterity"])
    strength = int(effective_bundle["attribute_values"]["strength"])
    constitution = int(effective_bundle["attribute_values"]["constitution"])
    combat_dexterity = normalize_combat_attribute_value(dexterity)
    combat_strength = normalize_combat_attribute_value(strength)
    combat_constitution = normalize_combat_attribute_value(constitution)
    level = max(1, min(100, int(character.level or 1)))
    status_bundle = get_status_effect_modifier_bundle(character_id)

    dodge_score = (
        12.0
        + (combat_dexterity * 1.15)
        + (dodging_skill * 0.95)
        + item_dodge_bonus_total
        + class_dodge_bonus_total
        + (level * 0.45)
        - (armor_rating_total * 0.10)
        + float(status_bundle.get("dodge_score_bonus", 0.0))
    )
    block_score = (
        10.0
        + (combat_strength * 0.55)
        + (combat_constitution * 0.95)
        + (blocking_skill * 1.05)
        + item_block_bonus_total
        + class_block_bonus_total
        + (level * 0.40)
        + (armor_rating_total * 0.45)
        + float(status_bundle.get("block_score_bonus", 0.0))
    )

    return {
        "success": True,
        "level": level,
        "armor": {
            "armor_rating_total": round(armor_rating_total, 3),
            "item_dodge_bonus_total": round(item_dodge_bonus_total, 3),
            "item_block_bonus_total": round(item_block_bonus_total, 3),
            "class_dodge_bonus_total": round(class_dodge_bonus_total, 3),
            "class_block_bonus_total": round(class_block_bonus_total, 3),
            "block_threshold_bonus_total": round(block_threshold_bonus_total, 3),
        },
        "skills": {
            "dodging": dodging_skill,
            "blocking": blocking_skill,
        },
        "effective_stats": effective_bundle,
        "combat_attributes": {
            "dexterity": round(combat_dexterity, 3),
            "strength": round(combat_strength, 3),
            "constitution": round(combat_constitution, 3),
        },
        "scores": {
            "dodge_score": round(dodge_score, 3),
            "block_score": round(block_score, 3),
            "best_defense_score": round(max(dodge_score, block_score), 3),
            "best_defense_type": "dodge" if dodge_score >= block_score else "block",
        },
        "status_effects": status_bundle,
    }


def preview_attack_outcome(attacker_character_id: int, defender_character_id: int) -> Dict[str, Any]:
    """Preview outcome probabilities for attacker vs defender with clear dodge/block zero-damage rules."""

    attack_profile = get_attack_profile(attacker_character_id)
    if not attack_profile.get("success"):
        return {"success": False, "message": attack_profile.get("message", "Attack profile unavailable.")}

    defense_profile = get_defense_profile(defender_character_id)
    if not defense_profile.get("success"):
        return {"success": False, "message": defense_profile.get("message", "Defense profile unavailable.")}

    attacker = db.session.get(Character, attacker_character_id)
    defender = db.session.get(Character, defender_character_id)
    if not attacker or not defender:
        return {"success": False, "message": "Attacker or defender not found."}

    offense_weighted_attribute = float(attack_profile["scaling"].get("weighted_attribute_score", 0.0))
    offense_skill_level = float(attack_profile["weapon"].get("skill_level", 0))
    offense_item_level = float(attack_profile["weapon"].get("item_level", 1))
    attacker_level = max(1, min(100, int(attacker.level or 1)))
    defender_level = max(1, min(100, int(defender.level or 1)))
    level_delta = attacker_level - defender_level

    attack_score = (
        12.0
        + (offense_weighted_attribute * 1.20)
        + (offense_skill_level * 0.95)
        + (offense_item_level * 0.70)
        + (attacker_level * 0.70)
    )
    if level_delta > 0:
        attack_score += (level_delta * 0.90)
    elif level_delta < 0:
        attack_score += (level_delta * 1.30)

    dodge_score = float(defense_profile["scores"]["dodge_score"])
    block_score = float(defense_profile["scores"]["block_score"])
    block_threshold_bonus = float(defense_profile["armor"]["block_threshold_bonus_total"])

    full_hit = 0
    partial_hit = 0
    zero_damage = 0
    sample_size = 20 * 20
    for attack_roll in range(1, 21):
        for defense_roll in range(1, 21):
            attack_total = attack_score + attack_roll
            dodge_total = dodge_score + defense_roll
            block_total = block_score + defense_roll
            defense_total = max(dodge_total, block_total)
            defense_type = "dodge" if dodge_total >= block_total else "block"
            margin = attack_total - defense_total

            if defense_type == "dodge" and dodge_total >= attack_total + 6:
                zero_damage += 1
                continue
            if defense_type == "block" and block_total >= attack_total + 6 + block_threshold_bonus:
                zero_damage += 1
                continue

            if margin >= 8:
                full_hit += 1
            elif margin >= 1:
                partial_hit += 1
            else:
                partial_hit += 1

    full_hit_pct = round((full_hit / sample_size) * 100.0, 2)
    partial_hit_pct = round((partial_hit / sample_size) * 100.0, 2)
    zero_damage_pct = round((zero_damage / sample_size) * 100.0, 2)

    return {
        "success": True,
        "attacker": {
            "character_id": attacker_character_id,
            "name": attacker.name,
            "level": attacker_level,
        },
        "defender": {
            "character_id": defender_character_id,
            "name": defender.name,
            "level": defender_level,
        },
        "scores": {
            "attack_score": round(attack_score, 3),
            "dodge_score": round(dodge_score, 3),
            "block_score": round(block_score, 3),
            "level_delta": level_delta,
        },
        "probabilities": {
            "full_hit_percent": full_hit_pct,
            "partial_hit_percent": partial_hit_pct,
            "zero_damage_percent": zero_damage_pct,
        },
        "rules": {
            "clear_dodge_zero_damage": "dodge_total >= attack_total + 6",
            "clear_block_zero_damage": "block_total >= attack_total + 6 + block_threshold_bonus",
            "best_defense_selected": "max(dodge_total, block_total)",
        },
    }


def get_attack_profile(character_id: int) -> Dict[str, Any]:
    """Return backend-derived attack profile from equipped weapon, attributes and skill levels."""

    character = db.session.get(Character, character_id)
    if not character:
        return {
            "success": False,
            "message": "Character not found.",
        }

    attributes = character.attributes
    if not attributes:
        return {
            "success": False,
            "message": "Character attributes not found.",
        }

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment.get("slots", {})
    weapon_item = _find_main_hand_weapon(slots)
    profile = _build_weapon_profile(weapon_item)
    effective_bundle = _build_effective_equipment_bundle(character_id, attributes, list(_iter_equipped_items(slots)))
    skill_level = _load_character_skill_level(character_id, profile["skill_name"])
    skill_level += int(effective_bundle["skill_bonus_values"].get(profile["skill_name"], 0))
    status_bundle = get_status_effect_modifier_bundle(character_id)
    character_level = max(1, min(100, int(character.level or 1)))
    item_level = int(profile["item_level"])
    scaling_contributions = {}
    combat_attribute_values = {}
    weighted_attribute_score = 0.0
    for attribute_name, multiplier in profile["scaling"].items():
        raw_attribute_value = float(
            effective_bundle["attribute_values"].get(attribute_name, _attribute_value(attributes, attribute_name))
        )
        combat_attribute_value = normalize_combat_attribute_value(raw_attribute_value)
        combat_attribute_values[attribute_name] = round(combat_attribute_value, 3)
        contribution = combat_attribute_value * float(multiplier)
        scaling_contributions[attribute_name] = round(contribution, 3)
        weighted_attribute_score += contribution

    weighted_attribute_score = max(0.0, weighted_attribute_score)
    level_factor = float(character_level) ** 1.05
    weapon_factor = 0.35 + 0.65 * ((float(item_level) / 100.0) ** 1.15)
    skill_factor = 0.40 + 0.60 * ((max(0.0, min(100.0, float(skill_level))) / 100.0) ** 1.10)
    normalized_weighted_attribute_score = normalize_combat_attribute_value(weighted_attribute_score)
    attribute_factor = 0.55 + 0.45 * ((normalized_weighted_attribute_score / 100.0) ** 1.05)
    total_factor = level_factor * weapon_factor * skill_factor * attribute_factor
    total_factor *= float(status_bundle.get("damage_multiplier", 1.0) or 1.0)
    base_min = int(profile["base_damage_min"])
    base_max = int(profile["base_damage_max"])
    final_min = max(1, int(round(base_min * total_factor)))
    final_max = max(final_min, int(round(base_max * total_factor)))

    return {
        "success": True,
        "weapon": {
            "item_id": weapon_item.get("item_id") if weapon_item else None,
            "name": weapon_item.get("name") if weapon_item else "Unarmed",
            "weapon_family": profile["weapon_family"],
            "item_level": item_level,
            "attack_mode": profile["attack_mode"],
            "damage_type": profile["damage_type"],
            "skill_name": profile["skill_name"],
            "skill_level": skill_level,
        },
        "damage": {
            "base_min": base_min,
            "base_max": base_max,
            "final_min": final_min,
            "final_max": final_max,
        },
        "scaling": {
            "weights": profile["scaling"],
            "attribute_values": {
                key: int(effective_bundle["attribute_values"].get(key, _attribute_value(attributes, key)))
                for key in profile["scaling"]
            },
            "combat_attribute_values": combat_attribute_values,
            "contributions": scaling_contributions,
            "weighted_attribute_score": round(weighted_attribute_score, 3),
            "normalized_weighted_attribute_score": round(normalized_weighted_attribute_score, 3),
            "level_factor": round(level_factor, 4),
            "weapon_factor": round(weapon_factor, 4),
            "skill_factor": round(skill_factor, 4),
            "attribute_factor": round(attribute_factor, 4),
            "total_factor": round(total_factor, 4),
        },
        "effective_stats": effective_bundle,
        "status_effects": status_bundle,
    }


# ---------------------------------------------------------------------------
# Inventory movement helpers
# ---------------------------------------------------------------------------


def _find_inventory_item(inventory_blob: Dict[str, Any], item_id: str):
    """Find an inventory item by id, exact name, or fuzzy name fragment."""

    normalized_item_id = (item_id or "").strip().lower()
    if not normalized_item_id:
        return None, None

    for container in _get_containers(inventory_blob):
        for item in container.get("items", []):
            existing_id = str(item.get("item_id", "")).lower().strip()
            existing_name = str(item.get("name", "")).lower().strip()

            if (
                existing_id == normalized_item_id
                or existing_name == normalized_item_id
                or normalized_item_id in existing_name
            ):
                return container, item

    return None, None


def _remove_one_from_container(container: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Remove one quantity from a container and return the equipped copy."""

    equipped_item = deepcopy(item)
    equipped_item["quantity"] = 1

    quantity = int(item.get("quantity", 1))
    if quantity > 1:
        item["quantity"] = quantity - 1
    else:
        container.get("items", []).remove(item)

    return equipped_item


def _used_volume(container: Dict[str, Any]) -> float:
    total = 0.0
    for item in container.get("items", []):
        total += float(item.get("volume", 0)) * int(item.get("quantity", 1))
    return total


def _size_fits(item_size: str, container_size: str) -> bool:
    return SIZE_ORDER.get(item_size, 0) <= SIZE_ORDER.get(container_size, 0)


def _find_container(inventory_blob: Dict[str, Any], container_id: str) -> Optional[Dict[str, Any]]:
    for container in _get_containers(inventory_blob):
        if container.get("container_id") == container_id:
            return container
    return None


def _remove_empty_hand_container(inventory_blob: Dict[str, Any], hand_slot: str) -> None:
    container = _find_container(inventory_blob, HAND_CONTAINER_IDS.get(hand_slot))
    if container and not container.get("items"):
        _get_containers(inventory_blob).remove(container)


def _hand_container_has_items(inventory_blob: Dict[str, Any], hand_slot: str) -> bool:
    container = _find_container(inventory_blob, HAND_CONTAINER_IDS.get(hand_slot))
    return bool(container and container.get("items"))


def _can_add_item(container: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """Return whether a container can accept an item by size and volume."""

    if container.get("source") == "hands" and item.get("hand_usage") != "none":
        return False

    if not _size_fits(item.get("size", "small"), container.get("max_item_size", "small")):
        return False

    required_volume = float(item.get("volume", 0)) * int(item.get("quantity", 1))
    available_volume = float(container.get("max_volume", 0)) - _used_volume(container)
    return required_volume <= available_volume


def _add_item_to_container(container: Dict[str, Any], item: Dict[str, Any]) -> None:
    """Add an item to a container, merging compatible stacks."""

    if item.get("stackable"):
        for existing in container.get("items", []):
            if (
                existing.get("name") == item.get("name")
                and existing.get("description") == item.get("description")
                and existing.get("size") == item.get("size")
                and float(existing.get("volume", 0)) == float(item.get("volume", 0))
                and float(existing.get("weight", 0)) == float(item.get("weight", 0))
                and existing.get("hand_usage") == item.get("hand_usage")
                and existing.get("stackable") is True
            ):
                existing["quantity"] = int(existing.get("quantity", 1)) + int(item.get("quantity", 1))
                return

    container.setdefault("items", []).append(item)


def _find_first_carried_container_with_space(inventory_blob: Dict[str, Any], item: Dict[str, Any]):
    for container in _get_containers(inventory_blob):
        if container.get("source") == "equipment" and _can_add_item(container, item):
            return container

    for container in _get_containers(inventory_blob):
        if container.get("source") == "hands" and _can_add_item(container, item):
            return container

    return None


# ---------------------------------------------------------------------------
# Slot inference and validation
# ---------------------------------------------------------------------------


def _infer_slot(item: Dict[str, Any], requested_slot: Optional[str], slots: Dict[str, Any]) -> str:
    """Infer the primary equipment slot for an item."""

    slot = _normalize_slot(requested_slot)

    if slot:
        if slot not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown equipment slot: {requested_slot}")
        return slot

    hand_usage = (item.get("hand_usage") or "none").strip().lower()
    item_type = (item.get("item_type") or "").strip().lower()
    slot_type = _normalize_slot(item.get("slot_type"))

    if slot_type:
        if slot_type not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown item slot_type: {item.get('slot_type')}")
        return slot_type

    if item_type == "shield" and not slots.get("backpack"):
        return "backpack"

    if _is_belt_pouch(item):
        for belt_slot in BELT_ATTACHMENT_SLOTS:
            if not slots.get(belt_slot):
                return belt_slot

    if hand_usage in ("one_handed", "two_handed"):
        if hand_usage == "one_handed" and slots.get("main_hand") and not slots.get("off_hand"):
            return "off_hand"
        return "main_hand"

    if item_type in ("weapon", "tool"):
        return "main_hand"
    if item_type in ("helmet", "headgear"):
        return "head"
    if item_type == "armor":
        return "torso_armor"
    if item_type in ("clothing", "shirt"):
        return "torso_clothing"
    if item_type in ("pants", "trousers"):
        return "legs_clothing"
    if item_type in ("boots", "shoes"):
        return "feet"
    if item_type in ("gloves", "glove"):
        return "gloves"
    if item_type == "belt":
        return "belt"
    if item_type in ("backpack", "bag", "container"):
        return "backpack"
    if item_type == "shield":
        return "backpack"
    if item_type == "cloak":
        return "cloak"
    if item_type == "ring":
        return "ring_left" if not slots.get("ring_left") else "ring_right"

    raise ValueError("Cannot infer equipment slot. Please provide a slot.")


def _target_slots_for_item(item: Dict[str, Any], primary_slot: str, slots: Dict[str, Any]):
    """Return all slots occupied by an item, including two-handed placeholders."""

    hand_usage = (item.get("hand_usage") or "none").strip().lower()

    if primary_slot in BELT_ATTACHMENT_SLOTS:
        return [primary_slot]

    if primary_slot == "backpack" and _is_shield(item):
        return [primary_slot]

    if hand_usage == "two_handed":
        return ["main_hand", "off_hand"]

    if hand_usage == "one_handed":
        if primary_slot not in HAND_SLOTS:
            raise ValueError("One-handed items must use main_hand or off_hand.")
        return [primary_slot]

    if primary_slot in HAND_SLOTS and not (_is_weapon(item) or _is_shield(item)):
        raise ValueError("Only hand-held items can use hand slots.")

    return [primary_slot]


def _validate_belt_attachment(item: Dict[str, Any], primary_slot: str, slots: Dict[str, Any]) -> None:
    """Validate weapons and small pouches attached to equipped belts."""

    if primary_slot not in BELT_ATTACHMENT_SLOTS:
        return

    if not slots.get("belt"):
        raise ValueError("A belt must be equipped before using belt attachment slots.")

    if _is_weapon(item):
        return

    if _is_belt_pouch(item) and _normalized_item_size(item) in BELT_POUCH_SIZES:
        return

    raise ValueError("Belt slots can only hold weapons or tiny/small pouches.")


def _validate_backpack_slot(item: Dict[str, Any], primary_slot: str) -> None:
    """Validate the backpack slot, including the shield-without-backpack rule."""

    if primary_slot != "backpack":
        return

    item_type = _normalized_item_type(item)
    if item_type in ("backpack", "rucksack", "bag", "container", "shield"):
        return

    raise ValueError("Backpack slot can only hold a backpack, container item, or shield.")


def _validate_target_slots(slots: Dict[str, Any], target_slots, item: Optional[Dict[str, Any]] = None):
    """Ensure all target slots are empty and item-specific rules pass."""

    for slot in target_slots:
        if slots.get(slot):
            raise ValueError(f"Equipment slot '{slot}' is already occupied.")

    if item:
        primary_slot = target_slots[0]
        _validate_belt_attachment(item, primary_slot, slots)
        _validate_backpack_slot(item, primary_slot)


def _validate_hand_containers_clear(inventory_blob: Dict[str, Any], target_slots) -> None:
    for slot in target_slots:
        if slot in HAND_CONTAINER_IDS and _hand_container_has_items(inventory_blob, slot):
            raise ValueError(f"Cannot equip item in {slot} while that hand is holding items.")


# ---------------------------------------------------------------------------
# Equipment-provided containers
# ---------------------------------------------------------------------------


def _container_profile_from_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Read a container profile from an equipped item, if it provides storage."""

    profile = item.get("container_profile") or item.get("container")
    if not isinstance(profile, dict):
        return None

    try:
        max_volume = float(profile.get("max_volume", 0))
    except (TypeError, ValueError):
        max_volume = 0

    if max_volume <= 0:
        return None

    return {
        "name": profile.get("name") or f"{item.get('name', 'Equipment')} Storage",
        "max_volume": max_volume,
        "max_item_size": profile.get("max_item_size") or "small",
    }


def _equipment_container_id(item: Dict[str, Any]) -> str:
    return f"equipment_{item.get('item_id')}"


def _attach_equipment_container(inventory_blob: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    """Attach an inventory container supplied by an equipped item."""

    profile = _container_profile_from_item(item)
    if not profile:
        return None

    container_id = _equipment_container_id(item)
    if _find_container(inventory_blob, container_id):
        return container_id

    stored_items = item.pop("stored_items", [])
    if not isinstance(stored_items, list):
        stored_items = []

    _get_containers(inventory_blob).append({
        "container_id": container_id,
        "name": profile["name"],
        "source": "equipment",
        "source_item_id": item.get("item_id"),
        "max_volume": profile["max_volume"],
        "max_item_size": profile["max_item_size"],
        "items": deepcopy(stored_items),
    })
    return container_id


# ---------------------------------------------------------------------------
# Equipped item lookup and serialization
# ---------------------------------------------------------------------------


def _find_equipped_item(slots: Dict[str, Any], slot: Optional[str], item_id: Optional[str]):
    """Find an equipped item by slot or by id/name."""

    normalized_slot = _normalize_slot(slot)
    normalized_item_id = (item_id or "").strip().lower()

    if normalized_slot:
        if normalized_slot not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown equipment slot: {slot}")

        item = slots.get(normalized_slot)
        if _is_placeholder(item):
            normalized_slot = item.get("primary_slot")
            item = slots.get(normalized_slot)
        return normalized_slot, item

    if normalized_item_id:
        for current_slot, item in slots.items():
            if not item or _is_placeholder(item):
                continue

            existing_id = str(item.get("item_id", "")).lower().strip()
            existing_name = str(item.get("name", "")).lower().strip()
            if (
                existing_id == normalized_item_id
                or existing_name == normalized_item_id
                or normalized_item_id in existing_name
            ):
                return current_slot, item

    return None, None


def _clean_equipment_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    """Strip slot-only metadata before returning an equipped item to inventory."""

    cleaned = deepcopy(item)
    cleaned.pop("equipped_slots", None)
    cleaned.pop("equipped_slot", None)
    cleaned.pop("placeholder", None)
    cleaned.pop("occupied_by", None)
    cleaned.pop("primary_slot", None)
    cleaned.pop("stored_items", None)
    cleaned["quantity"] = 1
    return cleaned


def get_equipment(character_id: int) -> Dict[str, Any]:
    """Return raw equipment state for a character."""

    inventory_blob = load_inventory_blob(character_id)
    return _get_equipment_state(inventory_blob)


def serialize_equipment(character_id: int):
    """Return UI/prompt-friendly equipment slot data."""

    equipment = get_equipment(character_id)
    slots = equipment.get("slots", {})
    serialized_slots = []
    equipped_labels = []

    for slot in EQUIPMENT_SLOTS:
        item = slots.get(slot)

        if _is_placeholder(item):
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": f"{item.get('name', 'Occupied')} (occupied)",
                "title": f"Occupied by {item.get('name', 'Occupied')}",
                "is_empty": False,
                "is_placeholder": True,
            })
            continue

        if item:
            label = item.get("name", "Unknown Item")
            equipped_labels.append(f"{SLOT_LABELS[slot]}: {label}")
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": label,
                "item_id": item.get("item_id"),
                "title": build_item_tooltip(item),
                "is_empty": False,
                "is_placeholder": False,
            })
        else:
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": None,
                "title": "",
                "is_empty": True,
                "is_placeholder": False,
            })

    return {
        "slots": serialized_slots,
        "labels": equipped_labels,
        "summary": ", ".join(equipped_labels) if equipped_labels else "None",
    }


# ---------------------------------------------------------------------------
# Public equipment operations
# ---------------------------------------------------------------------------


def equip_item(character_id: int, item_id: str, slot: Optional[str] = None) -> EquipmentOperationResult:
    """Equip one inventory item into a validated equipment slot."""

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment["slots"]

    source_container, source_item = _find_inventory_item(inventory_blob, item_id)
    if not source_item:
        return EquipmentOperationResult(False, f"Item '{item_id}' not found in inventory.", equipment, inventory_blob)

    try:
        primary_slot = _infer_slot(source_item, slot, slots)
        target_slots = _target_slots_for_item(source_item, primary_slot, slots)
        _validate_target_slots(slots, target_slots, source_item)
        _validate_hand_containers_clear(inventory_blob, target_slots)
    except ValueError as exc:
        return EquipmentOperationResult(False, str(exc), equipment, inventory_blob)

    equipped_item = _remove_one_from_container(source_container, source_item)
    equipped_item["equipped_slots"] = target_slots

    primary_slot = target_slots[0]
    slots[primary_slot] = equipped_item

    for secondary_slot in target_slots[1:]:
        slots[secondary_slot] = {
            "placeholder": True,
            "occupied_by": equipped_item.get("item_id"),
            "name": equipped_item.get("name"),
            "primary_slot": primary_slot,
        }

    for target_slot in target_slots:
        if target_slot in HAND_CONTAINER_IDS:
            _remove_empty_hand_container(inventory_blob, target_slot)

    equipment_container_id = _attach_equipment_container(inventory_blob, equipped_item)

    save_inventory_blob(character_id, inventory_blob)

    return EquipmentOperationResult(
        True,
        f"Equipped {equipped_item.get('name')} in {', '.join(target_slots)}.",
        equipment,
        inventory_blob,
        {
            "item_id": equipped_item.get("item_id"),
            "slots": target_slots,
            "equipment_container_id": equipment_container_id,
        },
    )


def unequip_item(
    character_id: int,
    slot: Optional[str] = None,
    item_id: Optional[str] = None,
    target_container_id: Optional[str] = None,
) -> EquipmentOperationResult:
    """Unequip one item and return it to an inventory container."""

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment["slots"]

    try:
        primary_slot, item = _find_equipped_item(slots, slot, item_id)
    except ValueError as exc:
        return EquipmentOperationResult(False, str(exc), equipment, inventory_blob)

    if not primary_slot or not item:
        return EquipmentOperationResult(False, "Equipped item not found.", equipment, inventory_blob)

    if primary_slot == "belt":
        occupied_belt_slots = [
            belt_slot for belt_slot in BELT_ATTACHMENT_SLOTS
            if slots.get(belt_slot)
        ]
        if occupied_belt_slots:
            return EquipmentOperationResult(
                False,
                "Cannot unequip belt while belt attachment slots are occupied.",
                equipment,
                inventory_blob,
                {"occupied_slots": occupied_belt_slots},
            )

    container_id = _equipment_container_id(item)
    equipment_container = _find_container(inventory_blob, container_id)
    if equipment_container and equipment_container.get("items"):
        return EquipmentOperationResult(
            False,
            f"Cannot unequip {item.get('name')} while its container is not empty.",
            equipment,
            inventory_blob,
            {"equipment_container_id": container_id},
        )

    inventory_item = _clean_equipment_metadata(item)
    target_container = (
        _find_container(inventory_blob, target_container_id)
        if target_container_id
        else _find_first_carried_container_with_space(inventory_blob, inventory_item)
    )
    if not target_container:
        return EquipmentOperationResult(False, "No carried container can hold the unequipped item.", equipment, inventory_blob)

    if not _can_add_item(target_container, inventory_item):
        return EquipmentOperationResult(
            False,
            f"Not enough space in container '{target_container.get('name')}'.",
            equipment,
            inventory_blob,
        )

    if equipment_container:
        _get_containers(inventory_blob).remove(equipment_container)

    for equipped_slot in item.get("equipped_slots", [primary_slot]):
        slots[equipped_slot] = None

    _add_item_to_container(target_container, inventory_item)
    save_inventory_blob(character_id, inventory_blob)

    return EquipmentOperationResult(
        True,
        f"Unequipped {inventory_item.get('name')}.",
        equipment,
        inventory_blob,
        {
            "item_id": inventory_item.get("item_id"),
            "target_container_id": target_container.get("container_id"),
        },
    )
