"""Skill progression service for core and custom learned abilities.

Core skills are seeded globally and displayed for every character at level 0.
Custom skills are created only when gameplay needs a repeatable learned ability
that does not fit a core skill. XP is additive; temporary penalties should be
handled later through modifiers instead of reducing skill XP.
"""

import re
from typing import Any, Dict, List, Optional

from models import Character, CharacterSkill, SkillDefinition, db

from .constants import (
    CORE_SKILLS,
    LEGACY_CORE_SKILL_ALIASES,
    MAX_CUSTOM_SKILLS_PER_CHARACTER,
    MAX_SKILL_LEVEL,
    SKILL_XP_BASE_COST,
    SKILL_XP_CURVE_EXPONENT,
)


def skill_xp_required_for_level(level: int) -> int:
    """Return XP needed to advance from a skill level to the next level."""

    if level < 0 or level >= MAX_SKILL_LEVEL:
        return 0
    if level == 0:
        return 20
    return int(round(SKILL_XP_BASE_COST * (level ** SKILL_XP_CURVE_EXPONENT)))


def total_skill_xp_required_for_level(level: int) -> int:
    """Return total lifetime XP required for a skill level."""

    level = max(0, min(int(level), MAX_SKILL_LEVEL))
    return sum(skill_xp_required_for_level(current_level) for current_level in range(0, level))


def skill_level_from_total_xp(total_xp: int) -> int:
    """Derive skill level from total lifetime XP."""

    total_xp = max(0, int(total_xp))

    level = 0
    while level < MAX_SKILL_LEVEL:
        next_level_total = total_skill_xp_required_for_level(level + 1)
        if total_xp < next_level_total:
            break
        level += 1

    return level


def _normalize_skill_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _skill_name_key(name: str) -> str:
    """Return a loose comparison key for skill names and legacy aliases."""

    normalized = _normalize_skill_name(name).lower()
    normalized = normalized.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _coerce_xp_amount(amount: Any) -> int:
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("XP amount must be an integer.") from exc

    if amount < 0:
        raise ValueError("XP amount must not be negative.")

    return amount


def _coerce_short_code(value: Optional[str], fallback_name: str) -> str:
    """Normalize custom skill short codes for compact UI chips."""

    raw_value = (value or "").strip().upper()
    raw_value = re.sub(r"[^A-Z0-9]", "", raw_value)
    if len(raw_value) >= 3:
        return raw_value[:3]

    fallback = re.sub(r"[^A-Z0-9]", "", fallback_name.upper())
    return (fallback[:3] or "CUS").ljust(3, "X")


def _get_character(character_id: int) -> Character:
    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")
    return character


def _find_skill_definition(skill_name: str) -> Optional[SkillDefinition]:
    """Find an active skill by fuzzy normalized name."""

    normalized_key = _skill_name_key(skill_name)
    for skill in SkillDefinition.query.filter_by(is_active=True).all():
        if _skill_name_key(skill.name) == normalized_key:
            return skill
    return None


def _legacy_names_for_core_skill(core_name: str) -> List[str]:
    return [
        legacy_name
        for legacy_name, canonical_name in LEGACY_CORE_SKILL_ALIASES.items()
        if canonical_name == core_name
    ]


def _merge_legacy_skill_into_core(legacy_skill: SkillDefinition, core_skill: SkillDefinition) -> None:
    """Move legacy per-character skill progress onto the canonical core skill."""

    if legacy_skill.id == core_skill.id:
        return

    for legacy_character_skill in list(legacy_skill.character_skills):
        existing_character_skill = CharacterSkill.query.filter_by(
            character_id=legacy_character_skill.character_id,
            skill_id=core_skill.id,
        ).first()

        if existing_character_skill:
            existing_character_skill.skill_xp = max(
                int(existing_character_skill.skill_xp or 0),
                int(legacy_character_skill.skill_xp or 0),
            )
            existing_character_skill.skill_level = max(
                int(existing_character_skill.skill_level or 0),
                int(legacy_character_skill.skill_level or 0),
            )
            existing_character_skill.bonus_modifier = max(
                int(existing_character_skill.bonus_modifier or 0),
                int(legacy_character_skill.bonus_modifier or 0),
            )
            db.session.delete(legacy_character_skill)
        else:
            legacy_character_skill.skill_id = core_skill.id

    legacy_skill.is_active = False
    legacy_skill.is_custom = True


def ensure_core_skill_definitions() -> None:
    """Seed or update core skills and migrate legacy German skill names."""

    for skill_data in CORE_SKILLS:
        existing = _find_skill_definition(skill_data["name"])
        legacy_skills = [
            _find_skill_definition(legacy_name)
            for legacy_name in _legacy_names_for_core_skill(skill_data["name"])
        ]
        legacy_skills = [skill for skill in legacy_skills if skill]

        if not existing and legacy_skills:
            existing = legacy_skills.pop(0)
            existing.name = skill_data["name"]

        if existing:
            existing.category = skill_data["category"]
            existing.linked_attribute = skill_data["linked_attribute"]
            existing.description = skill_data["description"]
            existing.icon = skill_data["icon"]
            existing.short_code = skill_data["short_code"]
            existing.is_custom = False
            existing.is_active = True
            for legacy_skill in legacy_skills:
                _merge_legacy_skill_into_core(legacy_skill, existing)
            continue

        db.session.add(SkillDefinition(
            name=skill_data["name"],
            category=skill_data["category"],
            linked_attribute=skill_data["linked_attribute"],
            description=skill_data["description"],
            icon=skill_data["icon"],
            short_code=skill_data["short_code"],
            is_custom=False,
            is_active=True,
        ))

    db.session.commit()


def _get_or_create_character_skill(character: Character, skill: SkillDefinition) -> CharacterSkill:
    """Return the character progress row for a skill, creating it if needed."""

    character_skill = CharacterSkill.query.filter_by(
        character_id=character.id,
        skill_id=skill.id,
    ).first()

    if character_skill:
        return character_skill

    character_skill = CharacterSkill(
        character_id=character.id,
        skill_id=skill.id,
        skill_level=0,
        skill_xp=0,
        bonus_modifier=0,
    )
    db.session.add(character_skill)
    db.session.flush()
    return character_skill


def _serialize_skill_progression_from_values(level_value: int, xp_value: int) -> Dict[str, Any]:
    """Serialize skill progress from raw level and XP values."""

    level = max(0, min(int(level_value or 0), MAX_SKILL_LEVEL))
    total_xp = max(total_skill_xp_required_for_level(level), int(xp_value or 0))
    current_level_xp = total_skill_xp_required_for_level(level)
    next_level_xp = total_skill_xp_required_for_level(level + 1) if level < MAX_SKILL_LEVEL else current_level_xp
    xp_into_level = max(0, total_xp - current_level_xp)
    xp_needed_this_level = max(0, next_level_xp - current_level_xp)
    xp_remaining = max(0, next_level_xp - total_xp) if level < MAX_SKILL_LEVEL else 0
    progress_percent = (
        int((xp_into_level / xp_needed_this_level) * 100)
        if xp_needed_this_level > 0
        else 100
    )

    return {
        "level": level,
        "max_level": MAX_SKILL_LEVEL,
        "total_xp": total_xp,
        "current_level_xp": current_level_xp,
        "next_level_xp": next_level_xp,
        "xp_into_level": xp_into_level,
        "xp_needed_this_level": xp_needed_this_level,
        "xp_remaining": xp_remaining,
        "progress_percent": max(0, min(100, progress_percent)),
        "is_max_level": level >= MAX_SKILL_LEVEL,
    }


def _serialize_skill_progression(character_skill: CharacterSkill) -> Dict[str, Any]:
    return _serialize_skill_progression_from_values(
        level_value=int(character_skill.skill_level or 0),
        xp_value=int(character_skill.skill_xp or 0),
    )


def _serialize_skill_definition(skill: SkillDefinition, character_skill: Optional[CharacterSkill] = None) -> Dict[str, Any]:
    """Serialize a skill definition plus optional character progress."""

    if character_skill:
        level = int(character_skill.skill_level or 0)
        bonus_modifier = int(character_skill.bonus_modifier or 0)
        progression = _serialize_skill_progression(character_skill)
    else:
        level = 0
        bonus_modifier = 0
        progression = _serialize_skill_progression_from_values(0, 0)

    icon = skill.icon or skill.short_code or "SKL"
    return {
        "id": skill.id,
        "name": skill.name,
        "category": skill.category,
        "linked_attribute": skill.linked_attribute,
        "description": skill.description or "",
        "icon": icon,
        "short_code": skill.short_code or _coerce_short_code(None, skill.name),
        "is_custom": bool(skill.is_custom),
        "level": level,
        "bonus_modifier": bonus_modifier,
        "progression": progression,
    }


def serialize_character_skills(character_or_id: Character | int) -> List[Dict[str, Any]]:
    """Return all core skills and learned custom skills for a character."""

    character_id = character_or_id.id if isinstance(character_or_id, Character) else int(character_or_id)
    character_skills = (
        CharacterSkill.query
        .join(SkillDefinition, CharacterSkill.skill_id == SkillDefinition.id)
        .filter(CharacterSkill.character_id == character_id, SkillDefinition.is_active.is_(True))
        .all()
    )
    character_skill_by_skill_id = {
        character_skill.skill_id: character_skill
        for character_skill in character_skills
    }
    core_skills = (
        SkillDefinition.query
        .filter(SkillDefinition.is_active.is_(True), SkillDefinition.is_custom.is_(False))
        .order_by(SkillDefinition.category.asc(), SkillDefinition.name.asc())
        .all()
    )
    custom_skills = (
        SkillDefinition.query
        .join(CharacterSkill, CharacterSkill.skill_id == SkillDefinition.id)
        .filter(
            CharacterSkill.character_id == character_id,
            SkillDefinition.is_active.is_(True),
            SkillDefinition.is_custom.is_(True),
        )
        .order_by(SkillDefinition.name.asc())
        .all()
    )

    serialized = []
    for skill in core_skills:
        serialized.append(_serialize_skill_definition(
            skill,
            character_skill_by_skill_id.get(skill.id),
        ))

    for skill in custom_skills:
        serialized.append(_serialize_skill_definition(
            skill,
            character_skill_by_skill_id.get(skill.id),
        ))

    return serialized


def create_custom_skill(
    character_id: int,
    name: str,
    linked_attribute: str,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    short_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or attach a custom skill for a character."""

    try:
        character = _get_character(character_id)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    skill_name = _normalize_skill_name(name)
    if len(skill_name) < 3:
        return {"success": False, "message": "Custom skill name is too short."}

    existing = _find_skill_definition(skill_name)
    if existing:
        character_skill = _get_or_create_character_skill(character, existing)
        db.session.commit()
        return {
            "success": True,
            "message": f"Skill already exists: {existing.name}",
            "skill": serialize_character_skills(character.id),
            "details": {
                "skill_id": existing.id,
                "character_skill_id": character_skill.id,
                "created": False,
            },
        }

    custom_count = (
        CharacterSkill.query
        .join(SkillDefinition, CharacterSkill.skill_id == SkillDefinition.id)
        .filter(CharacterSkill.character_id == character.id, SkillDefinition.is_custom.is_(True))
        .count()
    )
    if custom_count >= MAX_CUSTOM_SKILLS_PER_CHARACTER:
        return {
            "success": False,
            "message": f"Custom skill limit reached ({MAX_CUSTOM_SKILLS_PER_CHARACTER}).",
        }

    skill = SkillDefinition(
        name=skill_name,
        category="Custom",
        linked_attribute=linked_attribute,
        description=description or f"Custom learned skill: {skill_name}.",
        icon=icon,
        short_code=_coerce_short_code(short_code, skill_name),
        is_custom=True,
        is_active=True,
    )
    db.session.add(skill)
    db.session.flush()
    character_skill = _get_or_create_character_skill(character, skill)
    db.session.commit()

    return {
        "success": True,
        "message": f"Created custom skill: {skill.name}",
        "skill": serialize_character_skills(character.id),
        "details": {
            "skill_id": skill.id,
            "character_skill_id": character_skill.id,
            "created": True,
        },
    }


def add_skill_xp(
    character_id: int,
    skill_name: str,
    amount: int,
    reason: Optional[str] = None,
    allow_create: bool = False,
    linked_attribute: Optional[str] = None,
    category: str = "Custom",
    icon: Optional[str] = None,
    short_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Add XP to a core or custom skill, optionally creating a custom skill."""

    try:
        character = _get_character(character_id)
        amount = _coerce_xp_amount(amount)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    skill = _find_skill_definition(skill_name)
    if not skill and allow_create:
        created = create_custom_skill(
            character_id=character.id,
            name=skill_name,
            linked_attribute=linked_attribute or "intelligence",
            description=f"Custom {category.lower()} skill created through gameplay.",
            icon=icon,
            short_code=short_code,
        )
        if not created.get("success"):
            return created
        skill = _find_skill_definition(skill_name)

    if not skill:
        return {
            "success": False,
            "message": f"Skill not found: {skill_name}",
            "skills": serialize_character_skills(character.id),
        }

    character_skill = _get_or_create_character_skill(character, skill)
    old_level = max(0, int(character_skill.skill_level or 0))
    old_xp = max(total_skill_xp_required_for_level(old_level), int(character_skill.skill_xp or 0))
    new_xp = old_xp + amount
    new_level = skill_level_from_total_xp(new_xp)

    character_skill.skill_xp = new_xp
    character_skill.skill_level = new_level
    db.session.commit()

    return {
        "success": True,
        "message": f"Added {amount} XP to {skill.name}.",
        "skills": serialize_character_skills(character.id),
        "details": {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "amount": amount,
            "reason": reason,
            "old_xp": old_xp,
            "new_xp": new_xp,
            "old_level": old_level,
            "new_level": new_level,
            "levels_gained": max(0, new_level - old_level),
        },
    }
