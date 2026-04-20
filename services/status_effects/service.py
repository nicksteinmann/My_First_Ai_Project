from typing import Any, Dict, Optional

from models import db, Character, CharacterStatusEffect, StatusEffectDefinition


class StatusEffectOperationResult:
    def __init__(
        self,
        success: bool,
        message: str,
        status_effects: list[Dict[str, Any]],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.status_effects = status_effects
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "status_effects": self.status_effects,
            "details": self.details,
        }


def _get_character(character_id: int) -> Character:
    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")
    return character


def _normalize_effect_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("Status effect name is required.")
    return normalized


def _coerce_duration(duration_turns: Any) -> int:
    try:
        duration = int(duration_turns)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration must be an integer.") from exc

    if duration <= 0:
        raise ValueError("Duration must be greater than 0.")

    return duration


def _get_or_create_definition(
    name: str,
    effect_type: str,
    description: Optional[str] = None,
    default_duration_turns: int = 1,
) -> StatusEffectDefinition:
    definition = StatusEffectDefinition.query.filter_by(name=name).first()
    if definition:
        return definition

    definition = StatusEffectDefinition(
        name=name,
        effect_type=(effect_type or "condition").strip().lower() or "condition",
        description=description or "",
        default_duration_turns=default_duration_turns,
        modifiers_json=None,
    )
    db.session.add(definition)
    db.session.flush()
    return definition


def serialize_status_effects(character_id: int) -> list[Dict[str, Any]]:
    rows = (
        CharacterStatusEffect.query
        .filter_by(character_id=character_id)
        .order_by(CharacterStatusEffect.applied_at.asc())
        .all()
    )

    effects = []
    for row in rows:
        definition = db.session.get(StatusEffectDefinition, row.status_effect_id)

        effects.append({
            "id": row.id,
            "name": definition.name if definition else "Unknown Effect",
            "description": definition.description if definition else "",
            "effect_type": definition.effect_type if definition else "unknown",
            "duration_remaining": row.duration_remaining,
            "source_text": row.source_text or "",
        })

    return effects


def get_status_effects(character_id: int) -> list[Dict[str, Any]]:
    _get_character(character_id)
    return serialize_status_effects(character_id)


def apply_status_effect(
    character_id: int,
    name: str,
    effect_type: str = "condition",
    duration_turns: int = 1,
    description: Optional[str] = None,
    source_text: Optional[str] = None,
) -> StatusEffectOperationResult:
    try:
        character = _get_character(character_id)
        normalized_name = _normalize_effect_name(name)
        duration = _coerce_duration(duration_turns)
    except ValueError as exc:
        return StatusEffectOperationResult(False, str(exc), [])

    definition = _get_or_create_definition(
        name=normalized_name,
        effect_type=effect_type,
        description=description,
        default_duration_turns=duration,
    )

    existing = (
        CharacterStatusEffect.query
        .filter_by(character_id=character.id, status_effect_id=definition.id)
        .first()
    )

    if existing:
        existing.duration_remaining = max(existing.duration_remaining, duration)
        existing.source_text = source_text or existing.source_text
        status_effect_id = existing.id
    else:
        status_effect = CharacterStatusEffect(
            character_id=character.id,
            status_effect_id=definition.id,
            duration_remaining=duration,
            source_text=source_text or "",
        )
        db.session.add(status_effect)
        db.session.flush()
        status_effect_id = status_effect.id

    db.session.commit()

    return StatusEffectOperationResult(
        True,
        f"Applied status effect: {normalized_name}.",
        serialize_status_effects(character.id),
        {
            "status_effect_id": status_effect_id,
            "name": normalized_name,
            "duration_turns": duration,
        },
    )


def remove_status_effect(
    character_id: int,
    name: Optional[str] = None,
    status_effect_id: Optional[int] = None,
) -> StatusEffectOperationResult:
    try:
        character = _get_character(character_id)
    except ValueError as exc:
        return StatusEffectOperationResult(False, str(exc), [])

    effect = None

    if status_effect_id is not None:
        effect = (
            CharacterStatusEffect.query
            .filter_by(id=status_effect_id, character_id=character.id)
            .first()
        )
    elif name:
        definition = StatusEffectDefinition.query.filter_by(name=name.strip()).first()
        if definition:
            effect = (
                CharacterStatusEffect.query
                .filter_by(character_id=character.id, status_effect_id=definition.id)
                .first()
            )

    if not effect:
        return StatusEffectOperationResult(
            False,
            "Status effect not found.",
            serialize_status_effects(character.id),
        )

    db.session.delete(effect)
    db.session.commit()

    return StatusEffectOperationResult(
        True,
        "Removed status effect.",
        serialize_status_effects(character.id),
    )
