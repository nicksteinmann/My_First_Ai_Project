from typing import Any, Dict, Optional

from models import db, Character, CharacterResource

from .constants import RESOURCE_ALIASES, RESOURCE_FIELDS


class ResourceOperationResult:
    def __init__(
        self,
        success: bool,
        message: str,
        resources: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.resources = resources
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "resources": self.resources,
            "details": self.details,
        }


def _normalize_resource_name(resource: str) -> str:
    normalized = (resource or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = RESOURCE_ALIASES.get(normalized, normalized)

    if normalized not in RESOURCE_FIELDS:
        raise ValueError(f"Unknown resource: {resource}")

    return normalized


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


def _serialize_resources(resources: CharacterResource, character: Optional[Character] = None) -> Dict[str, Any]:
    data = {}

    for resource_name, (current_field, max_field) in RESOURCE_FIELDS.items():
        current_value = int(getattr(resources, current_field))
        max_value = int(getattr(resources, max_field))
        data[resource_name] = {
            "current": current_value,
            "max": max_value,
            "percent": int((current_value / max_value) * 100) if max_value > 0 else 0,
        }

    if character:
        data["character_status"] = character.status

    return data


def _sync_character_life_status(character: Character, resources: CharacterResource) -> None:
    if int(resources.hp_current) <= 0:
        character.status = "dead"
    elif character.status == "dead" and int(resources.hp_current) > 0:
        character.status = "alive"


def _coerce_amount(amount: Any) -> int:
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Amount must be an integer.") from exc

    if amount < 0:
        raise ValueError("Amount must not be negative.")

    return amount


def _coerce_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Value must be an integer.") from exc


def get_resources(character_id: int) -> Dict[str, Any]:
    character = _get_character(character_id)
    resources = _get_or_create_resources(character)
    return _serialize_resources(resources, character)


def add_resource(character_id: int, resource: str, amount: int) -> ResourceOperationResult:
    character = _get_character(character_id)
    resources = _get_or_create_resources(character)

    try:
        resource_name = _normalize_resource_name(resource)
        amount = _coerce_amount(amount)
    except ValueError as exc:
        return ResourceOperationResult(False, str(exc), _serialize_resources(resources, character))

    current_field, max_field = RESOURCE_FIELDS[resource_name]
    old_value = int(getattr(resources, current_field))
    max_value = int(getattr(resources, max_field))
    new_value = min(old_value + amount, max_value)

    setattr(resources, current_field, new_value)
    _sync_character_life_status(character, resources)
    db.session.commit()

    return ResourceOperationResult(
        True,
        f"Added {amount} {resource_name}.",
        _serialize_resources(resources, character),
        {
            "resource": resource_name,
            "old_value": old_value,
            "new_value": new_value,
            "amount": amount,
        },
    )


def remove_resource(character_id: int, resource: str, amount: int) -> ResourceOperationResult:
    character = _get_character(character_id)
    resources = _get_or_create_resources(character)

    try:
        resource_name = _normalize_resource_name(resource)
        amount = _coerce_amount(amount)
    except ValueError as exc:
        return ResourceOperationResult(False, str(exc), _serialize_resources(resources, character))

    current_field, _max_field = RESOURCE_FIELDS[resource_name]
    old_value = int(getattr(resources, current_field))
    new_value = max(old_value - amount, 0)

    setattr(resources, current_field, new_value)
    _sync_character_life_status(character, resources)
    db.session.commit()

    return ResourceOperationResult(
        True,
        f"Removed {amount} {resource_name}.",
        _serialize_resources(resources, character),
        {
            "resource": resource_name,
            "old_value": old_value,
            "new_value": new_value,
            "amount": amount,
        },
    )


def set_resource(
    character_id: int,
    resource: str,
    current: Optional[int] = None,
    maximum: Optional[int] = None,
) -> ResourceOperationResult:
    character = _get_character(character_id)
    resources = _get_or_create_resources(character)

    try:
        resource_name = _normalize_resource_name(resource)
    except ValueError as exc:
        return ResourceOperationResult(False, str(exc), _serialize_resources(resources, character))

    current_field, max_field = RESOURCE_FIELDS[resource_name]
    old_current = int(getattr(resources, current_field))
    old_max = int(getattr(resources, max_field))

    try:
        new_max = old_max if maximum is None else _coerce_value(maximum)
        new_current = old_current if current is None else _coerce_value(current)
    except ValueError as exc:
        return ResourceOperationResult(False, str(exc), _serialize_resources(resources, character))

    if new_max < 0:
        return ResourceOperationResult(False, "Maximum must not be negative.", _serialize_resources(resources, character))

    if new_current < 0:
        return ResourceOperationResult(False, "Current value must not be negative.", _serialize_resources(resources, character))

    new_current = min(new_current, new_max)

    setattr(resources, max_field, new_max)
    setattr(resources, current_field, new_current)
    _sync_character_life_status(character, resources)
    db.session.commit()

    return ResourceOperationResult(
        True,
        f"Set {resource_name}.",
        _serialize_resources(resources, character),
        {
            "resource": resource_name,
            "old_current": old_current,
            "new_current": new_current,
            "old_max": old_max,
            "new_max": new_max,
        },
    )
