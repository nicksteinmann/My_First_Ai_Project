from typing import Any, Dict, List, Optional

from models import db, Character, CharacterResource

from .constants import (
    BASE_RESOURCE_GAIN_PER_LEVEL,
    CLASS_RESOURCE_MULTIPLIERS,
    MAX_CHARACTER_LEVEL,
    XP_BASE_COST,
    XP_CURVE_EXPONENT,
)


class XpOperationResult:
    def __init__(
        self,
        success: bool,
        message: str,
        progression: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.progression = progression
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "progression": self.progression,
            "details": self.details,
        }


def xp_required_for_level(level: int) -> int:
    if level < 1 or level >= MAX_CHARACTER_LEVEL:
        return 0
    return int(round(XP_BASE_COST * (level ** XP_CURVE_EXPONENT)))


def total_xp_required_for_level(level: int) -> int:
    level = max(1, min(int(level), MAX_CHARACTER_LEVEL))
    return sum(xp_required_for_level(current_level) for current_level in range(1, level))


def level_from_total_xp(total_xp: int) -> int:
    total_xp = max(0, int(total_xp))

    level = 1
    while level < MAX_CHARACTER_LEVEL:
        next_level_total = total_xp_required_for_level(level + 1)
        if total_xp < next_level_total:
            break
        level += 1

    return level


def _get_character(character_id: int) -> Character:
    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")
    return character


def _get_or_create_resources(character: Character) -> CharacterResource:
    if character.resources:
        return character.resources

    resources = CharacterResource(character_id=character.id)
    db.session.add(resources)
    db.session.flush()
    return resources


def _coerce_xp_amount(amount: Any) -> int:
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("XP amount must be an integer.") from exc

    if amount < 0:
        raise ValueError("XP amount must not be negative.")

    return amount


def _resource_gain_for_level(character: Character) -> Dict[str, int]:
    multipliers = CLASS_RESOURCE_MULTIPLIERS.get(character.class_name, {})
    gains = {}

    for resource_name, base_gain in BASE_RESOURCE_GAIN_PER_LEVEL.items():
        multiplier = float(multipliers.get(resource_name, 1.0))
        gains[resource_name] = max(0, int(round(base_gain * multiplier)))

    return gains


def _apply_level_up_resource_gains(character: Character, levels_gained: int) -> Dict[str, int]:
    resources = _get_or_create_resources(character)
    per_level_gains = _resource_gain_for_level(character)
    total_gains = {
        resource_name: value * levels_gained
        for resource_name, value in per_level_gains.items()
    }

    resources.hp_max = int(resources.hp_max) + total_gains["hp"]
    resources.mana_max = int(resources.mana_max) + total_gains["mana"]
    resources.energy_max = int(resources.energy_max) + total_gains["energy"]

    if character.status != "dead":
        resources.hp_current = min(int(resources.hp_current) + total_gains["hp"], int(resources.hp_max))

    resources.mana_current = min(int(resources.mana_current) + total_gains["mana"], int(resources.mana_max))
    resources.energy_current = min(int(resources.energy_current) + total_gains["energy"], int(resources.energy_max))

    return total_gains


def serialize_level_progression(character: Character) -> Dict[str, Any]:
    level = max(1, min(int(character.level or 1), MAX_CHARACTER_LEVEL))
    total_xp = max(0, int(character.xp or 0))
    current_level_xp = total_xp_required_for_level(level)
    next_level_xp = total_xp_required_for_level(level + 1) if level < MAX_CHARACTER_LEVEL else current_level_xp
    xp_into_level = max(0, total_xp - current_level_xp)
    xp_needed_this_level = max(0, next_level_xp - current_level_xp)
    xp_remaining = max(0, next_level_xp - total_xp) if level < MAX_CHARACTER_LEVEL else 0
    progress_percent = (
        int((xp_into_level / xp_needed_this_level) * 100)
        if xp_needed_this_level > 0
        else 100
    )

    return {
        "level": level,
        "max_level": MAX_CHARACTER_LEVEL,
        "total_xp": total_xp,
        "current_level_xp": current_level_xp,
        "next_level_xp": next_level_xp,
        "xp_into_level": xp_into_level,
        "xp_needed_this_level": xp_needed_this_level,
        "xp_remaining": xp_remaining,
        "progress_percent": max(0, min(100, progress_percent)),
        "is_max_level": level >= MAX_CHARACTER_LEVEL,
    }


def add_xp(character_id: int, amount: int, reason: Optional[str] = None) -> XpOperationResult:
    character = _get_character(character_id)
    old_level = max(1, min(int(character.level or 1), MAX_CHARACTER_LEVEL))
    old_xp = max(0, int(character.xp or 0))

    try:
        amount = _coerce_xp_amount(amount)
    except ValueError as exc:
        return XpOperationResult(False, str(exc), serialize_level_progression(character))

    if old_level >= MAX_CHARACTER_LEVEL:
        character.level = MAX_CHARACTER_LEVEL
        character.xp = old_xp + amount
        db.session.commit()
        return XpOperationResult(
            True,
            f"Added {amount} XP. Character is already at maximum level.",
            serialize_level_progression(character),
            {
                "amount": amount,
                "reason": reason,
                "old_xp": old_xp,
                "new_xp": int(character.xp),
                "old_level": old_level,
                "new_level": MAX_CHARACTER_LEVEL,
                "levels_gained": 0,
                "resource_gains": {},
            },
        )

    character.xp = old_xp + amount
    new_level = level_from_total_xp(character.xp)
    levels_gained = max(0, new_level - old_level)
    level_ups: List[int] = []
    resource_gains = {}

    if levels_gained:
        character.level = new_level
        level_ups = list(range(old_level + 1, new_level + 1))
        resource_gains = _apply_level_up_resource_gains(character, levels_gained)
    else:
        character.level = old_level

    db.session.commit()

    return XpOperationResult(
        True,
        f"Added {amount} XP.",
        serialize_level_progression(character),
        {
            "amount": amount,
            "reason": reason,
            "old_xp": old_xp,
            "new_xp": int(character.xp),
            "old_level": old_level,
            "new_level": int(character.level),
            "levels_gained": levels_gained,
            "level_ups": level_ups,
            "resource_gains": resource_gains,
        },
    )
