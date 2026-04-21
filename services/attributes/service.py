"""Core attribute progression service.

Attributes are broad character stats such as strength or intelligence. They are
separate from skills: character level-ups can grant class-weighted attribute XP,
while direct attribute training still goes through explicit backend tools.
"""

import json
from typing import Any, Dict, List, Optional

from models import Character, CharacterAttribute, db

from .constants import (
    ATTRIBUTE_DEFINITIONS,
    ATTRIBUTE_KEYS,
    ATTRIBUTE_XP_BASE_COST,
    ATTRIBUTE_XP_CURVE_EXPONENT,
    CLASS_ATTRIBUTE_XP_WEIGHTS,
    DEFAULT_ATTRIBUTE_XP_WEIGHTS,
    MAX_ATTRIBUTE_LEVEL,
)


def attribute_xp_required_for_level(level: int) -> int:
    """Return XP needed to move an attribute from level N to N+1."""

    if level < 1 or level >= MAX_ATTRIBUTE_LEVEL:
        return 0
    return int(round(ATTRIBUTE_XP_BASE_COST * (level ** ATTRIBUTE_XP_CURVE_EXPONENT)))


def total_attribute_xp_required_for_level(level: int) -> int:
    """Return total lifetime XP required for an attribute level."""

    level = max(1, min(int(level), MAX_ATTRIBUTE_LEVEL))
    return sum(attribute_xp_required_for_level(current_level) for current_level in range(1, level))


def attribute_level_from_total_xp(total_xp: int) -> int:
    """Derive attribute level from total lifetime XP."""

    total_xp = max(0, int(total_xp))

    level = 1
    while level < MAX_ATTRIBUTE_LEVEL:
        next_level_total = total_attribute_xp_required_for_level(level + 1)
        if total_xp < next_level_total:
            break
        level += 1

    return level


def _get_or_create_attributes(character: Character) -> CharacterAttribute:
    if character.attributes:
        return character.attributes

    attributes = CharacterAttribute(character_id=character.id)
    db.session.add(attributes)
    db.session.flush()
    return attributes


def _load_attribute_xp(attributes: CharacterAttribute) -> Dict[str, int]:
    """Load attribute XP JSON and backfill from existing levels if needed."""

    try:
        raw_data = json.loads(attributes.attribute_xp_json or "{}")
    except (TypeError, ValueError):
        raw_data = {}

    xp_data = {}
    for attribute_key in ATTRIBUTE_KEYS:
        level = int(getattr(attributes, attribute_key, 1) or 1)
        fallback_xp = total_attribute_xp_required_for_level(level)
        xp_data[attribute_key] = max(fallback_xp, int(raw_data.get(attribute_key, fallback_xp) or 0))

    return xp_data


def _save_attribute_xp(attributes: CharacterAttribute, xp_data: Dict[str, int]) -> None:
    """Persist normalized attribute XP JSON."""

    normalized = {
        attribute_key: max(0, int(xp_data.get(attribute_key, 0)))
        for attribute_key in ATTRIBUTE_KEYS
    }
    attributes.attribute_xp_json = json.dumps(normalized, ensure_ascii=False)


def serialize_attribute_progression(attributes: CharacterAttribute, attribute_key: str) -> Dict[str, Any]:
    """Return progress data for one attribute."""

    xp_data = _load_attribute_xp(attributes)
    level = max(1, min(int(getattr(attributes, attribute_key, 1) or 1), MAX_ATTRIBUTE_LEVEL))
    total_xp = max(total_attribute_xp_required_for_level(level), int(xp_data.get(attribute_key, 0)))
    current_level_xp = total_attribute_xp_required_for_level(level)
    next_level_xp = (
        total_attribute_xp_required_for_level(level + 1)
        if level < MAX_ATTRIBUTE_LEVEL
        else current_level_xp
    )
    xp_into_level = max(0, total_xp - current_level_xp)
    xp_needed_this_level = max(0, next_level_xp - current_level_xp)
    xp_remaining = max(0, next_level_xp - total_xp) if level < MAX_ATTRIBUTE_LEVEL else 0
    progress_percent = (
        int((xp_into_level / xp_needed_this_level) * 100)
        if xp_needed_this_level > 0
        else 100
    )

    return {
        "level": level,
        "max_level": MAX_ATTRIBUTE_LEVEL,
        "total_xp": total_xp,
        "current_level_xp": current_level_xp,
        "next_level_xp": next_level_xp,
        "xp_into_level": xp_into_level,
        "xp_needed_this_level": xp_needed_this_level,
        "xp_remaining": xp_remaining,
        "progress_percent": max(0, min(100, progress_percent)),
        "is_max_level": level >= MAX_ATTRIBUTE_LEVEL,
    }


def serialize_attributes(character_or_attributes: Character | CharacterAttribute | None) -> List[Dict[str, Any]]:
    """Return all six attributes with level and XP progress metadata."""

    if character_or_attributes is None:
        return []

    attributes = (
        character_or_attributes.attributes
        if isinstance(character_or_attributes, Character)
        else character_or_attributes
    )

    if attributes is None:
        return []

    serialized = []
    for definition in ATTRIBUTE_DEFINITIONS:
        attribute_key = definition["key"]
        level = int(getattr(attributes, attribute_key, 0) or 0)
        progression = serialize_attribute_progression(attributes, attribute_key)
        serialized.append({
            "key": attribute_key,
            "label": definition["label"],
            "icon": definition["icon"],
            "level": level,
            "progression": progression,
        })

    return serialized


def _class_attribute_weights(class_name: str) -> Dict[str, float]:
    """Return class-specific attribute XP weights merged with defaults."""

    weights = dict(DEFAULT_ATTRIBUTE_XP_WEIGHTS)
    weights.update(CLASS_ATTRIBUTE_XP_WEIGHTS.get(class_name, {}))
    return weights


def _attribute_xp_grants_for_character_levels(class_name: str, from_level: int, to_level: int) -> Dict[str, int]:
    """Calculate attribute XP gained from character level intervals."""

    weights = _class_attribute_weights(class_name)
    grants = {attribute_key: 0 for attribute_key in ATTRIBUTE_KEYS}

    for character_level in range(from_level, to_level):
        base_xp = attribute_xp_required_for_level(character_level)
        for attribute_key in ATTRIBUTE_KEYS:
            weight = max(0.0, float(weights.get(attribute_key, 0.0)))
            grants[attribute_key] += int(round(base_xp * weight))

    return grants


def _normalize_attribute_key(attribute: str) -> str:
    """Normalize English/German aliases to canonical attribute keys."""

    normalized = (attribute or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "str": "strength",
        "staerke": "strength",
        "stärke": "strength",
        "dex": "dexterity",
        "geschick": "dexterity",
        "geschicklichkeit": "dexterity",
        "beweglichkeit": "dexterity",
        "con": "constitution",
        "konstitution": "constitution",
        "widerstandsfaehigkeit": "constitution",
        "widerstandsfähigkeit": "constitution",
        "int": "intelligence",
        "intelligenz": "intelligence",
        "per": "perception",
        "wahrnehmung": "perception",
        "cha": "charisma",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized not in ATTRIBUTE_KEYS:
        raise ValueError(f"Unknown attribute: {attribute}")

    return normalized


def _coerce_xp_amount(amount: Any) -> int:
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("XP amount must be an integer.") from exc

    if amount < 0:
        raise ValueError("XP amount must not be negative.")

    return amount


def _apply_attribute_xp(
    attributes: CharacterAttribute,
    xp_data: Dict[str, int],
    attribute_key: str,
    amount: int,
) -> Optional[Dict[str, int]]:
    """Apply XP to one attribute and return level-up details if it advanced."""

    old_level = int(getattr(attributes, attribute_key, 1) or 1)
    old_total_xp = max(total_attribute_xp_required_for_level(old_level), int(xp_data.get(attribute_key, 0)))
    new_total_xp = old_total_xp + amount
    new_level = attribute_level_from_total_xp(new_total_xp)

    xp_data[attribute_key] = new_total_xp

    if new_level > old_level:
        setattr(attributes, attribute_key, new_level)
        return {
            "old_level": old_level,
            "new_level": new_level,
            "levels_gained": new_level - old_level,
        }

    return None


def add_attribute_xp(
    character_id: int,
    attribute: Optional[str] = None,
    amount: Optional[int] = None,
    grants: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Add direct attribute XP, either to one attribute or a batch of grants."""

    character = db.session.get(Character, character_id)
    if not character:
        return {
            "success": False,
            "message": "Character not found.",
        }

    attributes = _get_or_create_attributes(character)
    xp_data = _load_attribute_xp(attributes)
    normalized_grants = {}

    try:
        if grants:
            for raw_attribute, raw_amount in grants.items():
                attribute_key = _normalize_attribute_key(raw_attribute)
                xp_amount = _coerce_xp_amount(raw_amount)
                normalized_grants[attribute_key] = normalized_grants.get(attribute_key, 0) + xp_amount
        else:
            attribute_key = _normalize_attribute_key(attribute or "")
            xp_amount = _coerce_xp_amount(amount)
            normalized_grants[attribute_key] = xp_amount
    except ValueError as exc:
        return {
            "success": False,
            "message": str(exc),
            "attributes": serialize_attributes(attributes),
        }

    level_ups = {}
    for attribute_key, xp_amount in normalized_grants.items():
        if xp_amount <= 0:
            continue

        level_up = _apply_attribute_xp(attributes, xp_data, attribute_key, xp_amount)
        if level_up:
            level_ups[attribute_key] = level_up

    _save_attribute_xp(attributes, xp_data)
    db.session.commit()

    return {
        "success": True,
        "message": "Added attribute XP.",
        "attribute_xp_grants": normalized_grants,
        "attribute_level_ups": level_ups,
        "reason": reason,
        "attributes": serialize_attributes(attributes),
    }


def grant_level_up_attribute_xp(character: Character, from_level: int, to_level: int) -> Dict[str, Any]:
    """Grant automatic attribute XP after character level-ups."""

    if to_level <= from_level:
        return {
            "attribute_xp_grants": {},
            "attribute_level_ups": {},
            "attributes": serialize_attributes(character),
        }

    attributes = _get_or_create_attributes(character)
    xp_data = _load_attribute_xp(attributes)
    xp_grants = _attribute_xp_grants_for_character_levels(
        class_name=character.class_name,
        from_level=from_level,
        to_level=to_level,
    )
    level_ups = {}

    for attribute_key, xp_amount in xp_grants.items():
        if xp_amount <= 0:
            continue

        level_up = _apply_attribute_xp(attributes, xp_data, attribute_key, xp_amount)
        if level_up:
            level_ups[attribute_key] = level_up

    _save_attribute_xp(attributes, xp_data)

    return {
        "attribute_xp_grants": {
            key: value for key, value in xp_grants.items() if value > 0
        },
        "attribute_level_ups": level_ups,
        "attributes": serialize_attributes(attributes),
    }
