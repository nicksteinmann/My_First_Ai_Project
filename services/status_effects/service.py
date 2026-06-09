"""Character status effect service.

Status effects are tracked as named conditions with duration, source text, and
lightweight gameplay modifiers for MVP combat/check integration.
"""

import json
from typing import Any, Dict, Optional

from models import db, Character, CharacterStatusEffect, StatusEffectDefinition
from services.resources.service import get_resources, remove_resource


STATUS_EFFECT_ICONS = {
    "poisoned": "poison",
    "poison": "poison",
    "bleeding": "bleeding",
    "bleed": "bleeding",
    "stunned": "stunned",
    "stun": "stunned",
    "blessed": "blessed",
    "blessing": "blessed",
    "burning": "burning",
    "burned": "burning",
    "frozen": "frozen",
    "chilled": "frozen",
    "sleeping": "sleeping",
    "asleep": "sleeping",
    "frightened": "fear",
    "feared": "fear",
    "cursed": "curse",
    "curse": "curse",
    "exhausted": "fatigue",
    "fatigued": "fatigue",
    "overloaded": "overloaded",
    "overencumbered": "overloaded",
    "hidden": "hidden",
    "invisible": "hidden",
    "regenerating": "healing",
    "healing": "healing",
    "shielded": "shielded",
    "protected": "shielded",
    "slowed": "slowed",
}

EFFECT_TYPE_ICONS = {
    "buff": "blessed",
    "blessing": "blessed",
    "debuff": "warning",
    "condition": "warning",
    "poison": "poison",
    "injury": "bleeding",
}

DEFAULT_EFFECT_MODIFIERS = {
    "poisoned": {
        "check_bonus": -4,
        "attack_score_bonus": -4,
        "dodge_score_bonus": -3,
        "block_score_bonus": -2,
        "resource_tick": {"hp": 3},
        "tick_modes": ["time", "combat"],
    },
    "bleeding": {
        "check_bonus": -3,
        "dodge_score_bonus": -4,
        "block_score_bonus": -2,
        "resource_tick": {"hp": 4},
        "tick_modes": ["time", "combat"],
    },
    "burning": {
        "check_bonus": -2,
        "attack_score_bonus": -2,
        "dodge_score_bonus": -5,
        "block_score_bonus": -4,
        "resource_tick": {"hp": 5},
        "tick_modes": ["time", "combat"],
    },
    "stunned": {
        "check_bonus": -12,
        "attack_score_bonus": -100,
        "dodge_score_bonus": -12,
        "block_score_bonus": -12,
        "cannot_act": True,
        "tick_modes": ["combat"],
    },
    "blessed": {
        "check_bonus": 6,
        "attack_score_bonus": 4,
        "dodge_score_bonus": 2,
        "block_score_bonus": 2,
        "tick_modes": ["time", "combat"],
    },
    "fatigued": {
        "check_bonus": -3,
        "attack_score_bonus": -3,
        "dodge_score_bonus": -5,
        "block_score_bonus": -2,
        "resource_tick": {"energy": 4},
        "tick_modes": ["time", "combat"],
    },
    "slowed": {
        "check_bonus": -2,
        "attack_score_bonus": -2,
        "dodge_score_bonus": -6,
        "block_score_bonus": -2,
        "tick_modes": ["time", "combat"],
    },
    "shielded": {
        "check_bonus": 1,
        "dodge_score_bonus": 2,
        "block_score_bonus": 8,
        "tick_modes": ["time", "combat"],
    },
    "frozen": {
        "check_bonus": -5,
        "attack_score_bonus": -4,
        "dodge_score_bonus": -8,
        "block_score_bonus": -5,
        "tick_modes": ["time", "combat"],
    },
}


class StatusEffectOperationResult:
    """Serializable result for status-effect tool operations."""

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
        """Return a tool-response friendly representation."""

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
    """Validate and normalize a status effect name."""

    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("Status effect name is required.")
    return normalized


def _coerce_duration(duration_turns: Any) -> int:
    """Validate a positive turn duration."""

    try:
        duration = int(duration_turns)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration must be an integer.") from exc

    if duration <= 0:
        raise ValueError("Duration must be greater than 0.")

    return duration


def _status_effect_icon(name: str, effect_type: str) -> str:
    """Return a compact UI icon key for a status effect."""

    normalized_name = (name or "").strip().lower()
    normalized_type = (effect_type or "").strip().lower()

    for keyword, icon in STATUS_EFFECT_ICONS.items():
        if keyword in normalized_name:
            return icon

    return EFFECT_TYPE_ICONS.get(normalized_type, "warning")


def _normalized_modifier_key(name: str, effect_type: str) -> str:
    normalized_name = (name or "").strip().lower()
    normalized_type = (effect_type or "").strip().lower()
    if normalized_name in DEFAULT_EFFECT_MODIFIERS:
        return normalized_name
    if normalized_type in DEFAULT_EFFECT_MODIFIERS:
        return normalized_type
    return normalized_name or normalized_type


def _default_modifiers_for(name: str, effect_type: str) -> dict:
    key = _normalized_modifier_key(name, effect_type)
    return dict(DEFAULT_EFFECT_MODIFIERS.get(key, {"tick_modes": ["combat", "time"]}))


def _parse_modifiers_json(value) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _get_or_create_definition(
    name: str,
    effect_type: str,
    description: Optional[str] = None,
    default_duration_turns: int = 1,
) -> StatusEffectDefinition:
    """Find or create the reusable definition for a status effect."""

    definition = StatusEffectDefinition.query.filter_by(name=name).first()
    if definition:
        if not definition.modifiers_json:
            definition.modifiers_json = json.dumps(_default_modifiers_for(name, effect_type))
            db.session.flush()
        return definition

    definition = StatusEffectDefinition(
        name=name,
        effect_type=(effect_type or "condition").strip().lower() or "condition",
        description=description or "",
        default_duration_turns=default_duration_turns,
        modifiers_json=json.dumps(_default_modifiers_for(name, effect_type)),
    )
    db.session.add(definition)
    db.session.flush()
    return definition


def serialize_status_effects(character_id: int) -> list[Dict[str, Any]]:
    """Return active character status effects for UI and prompt context."""

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
            "icon": _status_effect_icon(
                definition.name if definition else "",
                definition.effect_type if definition else "",
            ),
            "duration_remaining": row.duration_remaining,
            "source_text": row.source_text or "",
            "modifiers": _parse_modifiers_json(definition.modifiers_json if definition else None),
        })

    return effects


def get_status_effects(character_id: int) -> list[Dict[str, Any]]:
    """Validate the character exists and return active status effects."""

    _get_character(character_id)
    return serialize_status_effects(character_id)


def get_status_effect_modifier_bundle(character_id: int) -> Dict[str, Any]:
    """Aggregate active status-effect modifiers into one combat/check bundle."""

    bundle = {
        "check_bonus": 0.0,
        "attack_score_bonus": 0.0,
        "dodge_score_bonus": 0.0,
        "block_score_bonus": 0.0,
        "damage_multiplier": 1.0,
        "cannot_act": False,
        "active_names": [],
    }

    rows = CharacterStatusEffect.query.filter_by(character_id=character_id).all()
    for row in rows:
        definition = db.session.get(StatusEffectDefinition, row.status_effect_id)
        if not definition:
            continue
        modifiers = _parse_modifiers_json(definition.modifiers_json)
        bundle["active_names"].append(definition.name)
        bundle["check_bonus"] += float(modifiers.get("check_bonus", 0) or 0)
        bundle["attack_score_bonus"] += float(modifiers.get("attack_score_bonus", 0) or 0)
        bundle["dodge_score_bonus"] += float(modifiers.get("dodge_score_bonus", 0) or 0)
        bundle["block_score_bonus"] += float(modifiers.get("block_score_bonus", 0) or 0)
        bundle["damage_multiplier"] *= float(modifiers.get("damage_multiplier", 1.0) or 1.0)
        bundle["cannot_act"] = bundle["cannot_act"] or bool(modifiers.get("cannot_act", False))

    return bundle


def tick_status_effects(character_id: int, tick_mode: str = "time", ticks: int = 1) -> Dict[str, Any]:
    """Advance active status effects, apply resource ticks, and remove expired ones."""

    character = _get_character(character_id)
    resources_before = get_resources(character_id)
    rows = CharacterStatusEffect.query.filter_by(character_id=character.id).all()
    removed_effect_ids = []
    ticked_effects = []

    for _ in range(max(0, int(ticks or 0))):
        current_rows = list(rows)
        for row in current_rows:
            definition = db.session.get(StatusEffectDefinition, row.status_effect_id)
            if not definition:
                continue

            modifiers = _parse_modifiers_json(definition.modifiers_json)
            tick_modes = modifiers.get("tick_modes", ["combat", "time"])
            if tick_mode not in tick_modes:
                continue

            resource_tick = modifiers.get("resource_tick", {})
            if isinstance(resource_tick, dict):
                for resource_name, amount in resource_tick.items():
                    amount_int = max(0, int(amount or 0))
                    if amount_int <= 0:
                        continue
                    remove_resource(character_id, resource_name, amount_int)

            row.duration_remaining = max(0, int(row.duration_remaining or 0) - 1)
            ticked_effects.append({
                "id": row.id,
                "name": definition.name,
                "tick_mode": tick_mode,
                "duration_remaining": row.duration_remaining,
            })

        for row in list(rows):
            if int(row.duration_remaining or 0) > 0:
                continue
            removed_effect_ids.append(row.id)
            db.session.delete(row)
            rows.remove(row)

    db.session.commit()
    return {
        "success": True,
        "tick_mode": tick_mode,
        "ticks": max(0, int(ticks or 0)),
        "ticked_effects": ticked_effects,
        "removed_effect_ids": removed_effect_ids,
        "status_effects": serialize_status_effects(character.id),
        "resources_before": resources_before,
        "resources_after": get_resources(character.id),
    }


def apply_status_effect(
    character_id: int,
    name: str,
    effect_type: str = "condition",
    duration_turns: int = 1,
    description: Optional[str] = None,
    source_text: Optional[str] = None,
) -> StatusEffectOperationResult:
    """Apply or refresh a character status effect."""

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
    """Remove a character status effect by id or name."""

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
