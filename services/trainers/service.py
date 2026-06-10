"""Backend trainer discovery and paid lesson rules."""

from __future__ import annotations

import json
import re
from typing import Any

from models import Campaign, CampaignLocation, CampaignNPC, Character, CharacterAttribute, CharacterSkill, SkillDefinition, db
from services.attributes.service import add_attribute_xp
from services.currency.constants import CURRENCY_CONVERSION_RATES, GOLD_TO_COPPER
from services.currency.repository import load_currency, save_currency
from services.merchants.service import get_merchants_at_location
from services.skills.service import add_skill_xp
from services.world_data import find_world_location

SILVER_TO_COPPER = CURRENCY_CONVERSION_RATES["silver_to_copper"]

LOCATION_KIND_TIER = {
    "capital_city": 5,
    "capital_fortress": 5,
    "capital_port": 5,
    "city": 4,
    "port_city": 4,
    "mage_tower": 4,
    "forge_hold": 4,
    "town": 3,
    "fortress_town": 3,
    "pass_town": 3,
    "trade_crossing": 3,
    "port_town": 3,
    "tower_village": 3,
    "village": 2,
    "marsh_village": 2,
    "border_outpost": 2,
    "watch_fort": 2,
    "ranger_lodge": 2,
    "monastery": 2,
    "camp": 2,
    "canyon_hold": 2,
}

TRAINER_TIER_LEVEL_CAPS = {
    1: 20,
    2: 35,
    3: 55,
    4: 78,
    5: 100,
}

TRAINER_PATTERN_LABELS = {
    "combat_blade": "blade combat",
    "combat_axe": "axes and heavy striking",
    "combat_polearm": "polearms",
    "combat_ranged": "ranged weapons",
    "defense_guard": "guarded defense",
    "stealth_subtlety": "stealth and finesse",
    "utility_precision": "precision utility",
    "physical_craft": "physical craft",
    "knowledge_arcane": "arcane knowledge",
    "knowledge_nature": "nature lore",
    "knowledge_medicine": "medicine and treatment",
    "survival_field": "field survival",
    "social_presence": "social presence",
    "social_deceit": "social manipulation",
    "trade_craft": "trade craft",
}

TRAINER_ROLE_PROFILES = {
    "blacksmith": {
        "patterns": {"combat_axe", "defense_guard", "physical_craft", "trade_craft"},
        "specialties": {"Axes & Hammers", "Blocking"},
        "attributes": {"strength", "constitution"},
        "base_tier": 2,
        "scale_with_location": True,
    },
    "apothecary": {
        "patterns": {"knowledge_nature", "knowledge_medicine", "trade_craft"},
        "specialties": {"Herbalism", "Medicine"},
        "attributes": {"intelligence", "perception"},
        "base_tier": 2,
        "scale_with_location": True,
    },
    "herbalist": {
        "patterns": {"knowledge_nature", "knowledge_medicine", "survival_field"},
        "specialties": {"Herbalism", "Medicine", "Survival"},
        "attributes": {"intelligence", "perception"},
        "base_tier": 2,
        "scale_with_location": False,
    },
    "healer": {
        "patterns": {"knowledge_medicine", "social_presence"},
        "specialties": {"Medicine", "Insight"},
        "attributes": {"intelligence", "perception", "charisma"},
        "base_tier": 3,
        "scale_with_location": False,
    },
    "merchant": {
        "patterns": {"social_presence", "trade_craft"},
        "specialties": {"Persuasion", "Insight"},
        "attributes": {"charisma", "perception"},
        "base_tier": 1,
        "scale_with_location": True,
    },
    "innkeeper": {
        "patterns": {"social_presence", "trade_craft"},
        "specialties": {"Persuasion", "Insight"},
        "attributes": {"charisma", "constitution"},
        "base_tier": 1,
        "scale_with_location": True,
    },
    "woodcutter": {
        "patterns": {"combat_axe", "physical_craft", "survival_field"},
        "specialties": {"Axes & Hammers", "Athletics", "Survival"},
        "attributes": {"strength", "constitution"},
        "base_tier": 2,
        "scale_with_location": False,
    },
    "hunter": {
        "patterns": {"combat_ranged", "survival_field", "stealth_subtlety"},
        "specialties": {"Archery", "Survival", "Stealth"},
        "attributes": {"dexterity", "perception"},
        "base_tier": 2,
        "scale_with_location": False,
    },
    "ranger": {
        "patterns": {"combat_ranged", "survival_field", "stealth_subtlety", "knowledge_nature"},
        "specialties": {"Archery", "Survival", "Stealth", "Herbalism"},
        "attributes": {"dexterity", "perception", "constitution"},
        "base_tier": 3,
        "scale_with_location": False,
    },
    "guard": {
        "patterns": {"combat_blade", "combat_axe", "defense_guard"},
        "specialties": {"Swordsmanship", "Blocking", "Athletics"},
        "attributes": {"strength", "constitution"},
        "base_tier": 2,
        "scale_with_location": False,
    },
    "soldier": {
        "patterns": {"combat_blade", "combat_axe", "combat_polearm", "defense_guard"},
        "specialties": {"Swordsmanship", "Axes & Hammers", "Polearms", "Blocking"},
        "attributes": {"strength", "constitution", "dexterity"},
        "base_tier": 3,
        "scale_with_location": False,
    },
    "scholar": {
        "patterns": {"knowledge_arcane", "knowledge_nature", "social_presence"},
        "specialties": {"Arcane Lore", "Insight", "Persuasion"},
        "attributes": {"intelligence", "charisma"},
        "base_tier": 3,
        "scale_with_location": False,
    },
    "mage": {
        "patterns": {"knowledge_arcane", "utility_precision"},
        "specialties": {"Arcane Lore"},
        "attributes": {"intelligence", "perception"},
        "base_tier": 4,
        "scale_with_location": False,
    },
    "wizard": {
        "patterns": {"knowledge_arcane", "utility_precision"},
        "specialties": {"Arcane Lore"},
        "attributes": {"intelligence", "perception"},
        "base_tier": 4,
        "scale_with_location": False,
    },
    "priest": {
        "patterns": {"knowledge_medicine", "social_presence", "knowledge_arcane"},
        "specialties": {"Medicine", "Insight", "Persuasion"},
        "attributes": {"charisma", "intelligence", "perception"},
        "base_tier": 3,
        "scale_with_location": False,
    },
}

CORE_SKILL_PATTERNS = {
    "swordsmanship": "combat_blade",
    "axeshammers": "combat_axe",
    "polearms": "combat_polearm",
    "archery": "combat_ranged",
    "dodging": "stealth_subtlety",
    "blocking": "defense_guard",
    "stealth": "stealth_subtlety",
    "lockpicking": "utility_precision",
    "pickpocketing": "stealth_subtlety",
    "trapdisarming": "utility_precision",
    "climbing": "physical_craft",
    "athletics": "physical_craft",
    "arcanelore": "knowledge_arcane",
    "herbalism": "knowledge_nature",
    "medicine": "knowledge_medicine",
    "survival": "survival_field",
    "persuasion": "social_presence",
    "deception": "social_deceit",
    "intimidation": "social_presence",
    "insight": "social_presence",
}

ATTRIBUTE_NAME_LABELS = {
    "strength": "Strength",
    "dexterity": "Dexterity",
    "constitution": "Constitution",
    "intelligence": "Intelligence",
    "perception": "Perception",
    "charisma": "Charisma",
}


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_role(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_attribute_key(value: Any) -> str | None:
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
    return normalized if normalized in ATTRIBUTE_NAME_LABELS else None


def _load_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return decoded
    return fallback


def _npc_state_payload(npc: CampaignNPC) -> dict:
    payload = _load_json(getattr(npc, "state_json", None), {})
    return payload if isinstance(payload, dict) else {}


def _current_campaign_location(campaign: Campaign) -> CampaignLocation | None:
    if not campaign or not campaign.current_location_id:
        return None
    return db.session.get(CampaignLocation, campaign.current_location_id)


def _location_tier(location: CampaignLocation | None) -> int:
    world_location = find_world_location(location.world_location_id) if location and location.world_location_id else None
    kind = (
        (world_location or {}).get("kind")
        or getattr(location, "location_type", None)
        or "town"
    )
    normalized_kind = str(kind or "town").strip().lower().replace("-", "_").replace(" ", "_")
    return int(LOCATION_KIND_TIER.get(normalized_kind, 3))


def _currency_to_copper(currency: dict) -> int:
    if not isinstance(currency, dict):
        return 0
    return int(currency.get("gold", 0) or 0) * GOLD_TO_COPPER + int(currency.get("silver", 0) or 0) * SILVER_TO_COPPER + int(currency.get("copper", 0) or 0)


def _copper_to_currency(total_copper: int) -> dict[str, int]:
    remaining = max(0, int(total_copper or 0))
    gold = remaining // GOLD_TO_COPPER
    remaining -= gold * GOLD_TO_COPPER
    silver = remaining // SILVER_TO_COPPER
    remaining -= silver * SILVER_TO_COPPER
    return {"gold": gold, "silver": silver, "copper": remaining}


def _skill_definition_by_name(skill_name: str) -> SkillDefinition | None:
    normalized_target = _normalize_key(skill_name)
    for skill in SkillDefinition.query.filter_by(is_active=True).all():
        if _normalize_key(skill.name) == normalized_target:
            return skill
        aliases = _load_json(skill.aliases_json, [])
        if any(_normalize_key(alias) == normalized_target for alias in aliases if str(alias).strip()):
            return skill
    return None


def _serialize_trainer_profile(npc: CampaignNPC, profile: dict) -> dict:
    return {
        "trainer_npc_id": npc.id,
        "name": npc.name,
        "role": npc.role,
        "trainer_tier": int(profile.get("trainer_tier", 1) or 1),
        "max_trainable_level": int(profile.get("max_trainable_level", 20) or 20),
        "teachable_attributes": sorted(profile.get("attributes", [])),
        "skill_patterns": sorted(profile.get("patterns", [])),
        "skill_pattern_labels": [
            TRAINER_PATTERN_LABELS.get(pattern, pattern.replace("_", " "))
            for pattern in sorted(profile.get("patterns", []))
        ],
        "specialties": sorted(profile.get("specialties", [])),
    }


def _trainer_profile_for_npc(npc: CampaignNPC, location: CampaignLocation | None) -> dict | None:
    state_payload = _npc_state_payload(npc)
    trainer_override = state_payload.get("trainer_profile")
    if isinstance(trainer_override, dict):
        tier = max(1, min(5, int(trainer_override.get("trainer_tier", 1) or 1)))
        attributes = {
            attribute_key
            for attribute_key in (
                _normalize_attribute_key(value)
                for value in trainer_override.get("attributes", [])
            )
            if attribute_key
        }
        patterns = {
            str(value).strip().lower().replace("-", "_").replace(" ", "_")
            for value in trainer_override.get("patterns", [])
            if str(value).strip()
        }
        specialties = {
            str(value).strip()
            for value in trainer_override.get("specialties", [])
            if str(value).strip()
        }
        max_level = int(trainer_override.get("max_trainable_level", TRAINER_TIER_LEVEL_CAPS.get(tier, 20)) or TRAINER_TIER_LEVEL_CAPS.get(tier, 20))
        if not patterns and not specialties and not attributes:
            return None
        return {
            "trainer_tier": tier,
            "max_trainable_level": max_level,
            "attributes": attributes,
            "patterns": patterns,
            "specialties": specialties,
        }

    role_profile = TRAINER_ROLE_PROFILES.get(_normalize_role(npc.role))
    if not role_profile:
        return None

    location_tier = _location_tier(location)
    base_tier = int(role_profile.get("base_tier", 1) or 1)
    if role_profile.get("scale_with_location", False):
        trainer_tier = max(base_tier, location_tier)
    else:
        trainer_tier = base_tier
    trainer_tier = max(1, min(5, trainer_tier))
    return {
        "trainer_tier": trainer_tier,
        "max_trainable_level": TRAINER_TIER_LEVEL_CAPS.get(trainer_tier, 20),
        "attributes": set(role_profile.get("attributes", set())),
        "patterns": set(role_profile.get("patterns", set())),
        "specialties": set(role_profile.get("specialties", set())),
    }


def _infer_custom_skill_pattern(skill: SkillDefinition) -> str:
    allowed_domains = {
        str(value).strip().lower().replace("-", "_")
        for value in _load_json(skill.allowed_domains_json, [])
        if str(value).strip()
    }
    name_key = _normalize_key(skill.name)
    linked_attribute = _normalize_attribute_key(skill.linked_attribute) or "intelligence"

    if any(token in name_key for token in ("axe", "wood", "lumber", "smith", "forge", "hammer")):
        return "physical_craft"
    if any(token in name_key for token in ("bow", "arrow", "hunt", "track")):
        return "combat_ranged"
    if any(token in name_key for token in ("stealth", "shadow", "sneak", "pick")):
        return "stealth_subtlety"
    if any(token in name_key for token in ("herb", "remedy", "salve", "potion", "heal", "medic")):
        return "knowledge_nature" if "medicine" not in name_key else "knowledge_medicine"
    if any(token in name_key for token in ("rune", "arcane", "spell", "sigil", "ritual")):
        return "knowledge_arcane"
    if "social" in allowed_domains or linked_attribute == "charisma":
        return "social_presence"
    if "crafting" in allowed_domains or "trade_service" in allowed_domains:
        return "trade_craft" if linked_attribute == "intelligence" else "physical_craft"
    if "survival" in allowed_domains or "exploration" in allowed_domains:
        return "survival_field"
    if "magic" in allowed_domains or "knowledge" in allowed_domains:
        return "knowledge_arcane" if linked_attribute == "intelligence" else "knowledge_nature"
    if "utility" in allowed_domains or linked_attribute == "dexterity":
        return "utility_precision"
    if linked_attribute in {"strength", "constitution"}:
        return "physical_craft"
    if linked_attribute == "perception":
        return "survival_field"
    return "trade_craft"


def _skill_pattern(skill: SkillDefinition) -> str:
    core_pattern = CORE_SKILL_PATTERNS.get(_normalize_key(skill.name))
    if core_pattern:
        return core_pattern
    return _infer_custom_skill_pattern(skill)


def _character_skill_progress(character_id: int, skill: SkillDefinition) -> tuple[int, int]:
    row = CharacterSkill.query.filter_by(character_id=character_id, skill_id=skill.id).first()
    if not row:
        return 0, 0
    return int(row.skill_level or 0), int(row.skill_xp or 0)


def _character_attribute_level(character_id: int, attribute_key: str) -> int:
    attributes = CharacterAttribute.query.filter_by(character_id=character_id).first()
    if not attributes:
        return 0
    return int(getattr(attributes, attribute_key, 0) or 0)


def _skill_training_allowed(profile: dict, skill: SkillDefinition) -> bool:
    skill_name = str(skill.name or "").strip()
    pattern = _skill_pattern(skill)
    return skill_name in profile.get("specialties", set()) or pattern in profile.get("patterns", set())


def _attribute_training_allowed(profile: dict, attribute_key: str) -> bool:
    return attribute_key in profile.get("attributes", set())


def _lesson_minutes(minutes: Any) -> int:
    try:
        resolved = int(minutes or 60)
    except (TypeError, ValueError):
        resolved = 60
    resolved = max(30, min(120, resolved))
    return max(30, min(120, int(round(resolved / 30.0) * 30)))


def _skill_xp_for_lesson(current_level: int, trainer_tier: int, max_trainable_level: int, is_specialty: bool, minutes: int) -> int:
    tier_base = 22 + (trainer_tier * 16)
    if is_specialty:
        tier_base = int(round(tier_base * 1.15))
    room_factor = max(0.18, ((max_trainable_level - current_level + 8) / (max_trainable_level + 8)) ** 1.35)
    xp = tier_base * (minutes / 60.0) * room_factor
    return max(8, int(round(xp)))


def _attribute_xp_for_lesson(current_level: int, trainer_tier: int, max_trainable_level: int, minutes: int) -> int:
    tier_base = 16 + (trainer_tier * 11)
    room_factor = max(0.2, ((max_trainable_level - current_level + 10) / (max_trainable_level + 10)) ** 1.25)
    xp = tier_base * (minutes / 60.0) * room_factor
    return max(6, int(round(xp)))


def _lesson_price_copper(current_level: int, trainer_tier: int, minutes: int, is_specialty: bool) -> int:
    base_price = 18 + (trainer_tier * 22)
    level_factor = 1.0 + (max(0, current_level) / 18.0)
    specialty_factor = 1.15 if is_specialty else 1.0
    total = base_price * (minutes / 60.0) * level_factor * specialty_factor
    return max(12, int(round(total)))


def get_trainers_at_location(campaign_id: int, location_id: int | None = None) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}

    location = db.session.get(CampaignLocation, location_id) if location_id else _current_campaign_location(campaign)
    if not location:
        return {"success": False, "message": "Current location not found."}

    # Ensure fixed professional NPCs such as blacksmiths and apothecaries exist first.
    get_merchants_at_location(campaign_id=campaign.id, location_id=location.id)

    trainer_payloads = []
    npcs = (
        CampaignNPC.query
        .filter_by(campaign_id=campaign.id, current_location_id=location.id)
        .order_by(CampaignNPC.name.asc())
        .all()
    )
    for npc in npcs:
        profile = _trainer_profile_for_npc(npc, location)
        if not profile:
            continue
        trainer_payloads.append(_serialize_trainer_profile(npc, profile))

    return {
        "success": True,
        "tool": "get_trainers_at_location",
        "location_id": location.id,
        "location_name": location.name,
        "trainers": trainer_payloads,
    }


def serialize_location_trainers(campaign_id: int, location_id: int | None = None) -> list[dict]:
    payload = get_trainers_at_location(campaign_id=campaign_id, location_id=location_id)
    return list(payload.get("trainers", [])) if payload.get("success") else []


def train_with_teacher(
    campaign_id: int,
    trainer_npc_id: int,
    training_type: str,
    target_name: str,
    minutes: int | None = None,
    allow_create_skill: bool = False,
    linked_attribute: str | None = None,
    secondary_attributes: list[str] | None = None,
    aliases: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    charge_price: bool = True,
    reward_context: dict | None = None,
) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "message": "Character not found."}

    location = _current_campaign_location(campaign)
    trainer_npc = CampaignNPC.query.filter_by(campaign_id=campaign.id, id=trainer_npc_id).first()
    if not trainer_npc:
        return {"success": False, "message": "Trainer not found."}
    if not location or int(trainer_npc.current_location_id or -1) != int(location.id):
        return {"success": False, "message": "Trainer is not at the current location."}

    trainer_profile = _trainer_profile_for_npc(trainer_npc, location)
    if not trainer_profile:
        return {"success": False, "message": "This NPC cannot teach right now."}

    lesson_minutes = _lesson_minutes(minutes)
    normalized_type = str(training_type or "").strip().lower()

    xp_amount = 0
    current_level = 0
    training_payload = {}

    if normalized_type == "skill":
        skill = _skill_definition_by_name(target_name)
        if not skill and allow_create_skill:
            skill_result = add_skill_xp(
                character_id=character.id,
                skill_name=target_name,
                amount=0,
                allow_create=True,
                linked_attribute=linked_attribute or "intelligence",
                secondary_attributes=secondary_attributes,
                aliases=aliases,
                allowed_domains=allowed_domains,
            )
            if not skill_result.get("success"):
                return skill_result
            skill = _skill_definition_by_name(target_name)
        if not skill:
            return {"success": False, "message": f"Skill not found: {target_name}"}
        if not _skill_training_allowed(trainer_profile, skill):
            return {"success": False, "message": f"{trainer_npc.name} cannot teach {skill.name}."}

        current_level, old_xp = _character_skill_progress(character.id, skill)
        max_trainable_level = int(trainer_profile.get("max_trainable_level", 20) or 20)
        if current_level > max_trainable_level:
            return {
                "success": False,
                "message": (
                    f"{trainer_npc.name} cannot meaningfully train {skill.name} above level {max_trainable_level}."
                ),
            }

        is_specialty = skill.name in trainer_profile.get("specialties", set())
        xp_amount = _skill_xp_for_lesson(
            current_level=current_level,
            trainer_tier=int(trainer_profile["trainer_tier"]),
            max_trainable_level=max_trainable_level,
            is_specialty=is_specialty,
            minutes=lesson_minutes,
        )
        price_copper = _lesson_price_copper(current_level, int(trainer_profile["trainer_tier"]), lesson_minutes, is_specialty)
        training_payload = {
            "training_type": "skill",
            "target_name": skill.name,
            "skill_pattern": _skill_pattern(skill),
            "skill_pattern_label": TRAINER_PATTERN_LABELS.get(_skill_pattern(skill), _skill_pattern(skill).replace("_", " ")),
            "old_level": current_level,
            "old_xp": old_xp,
            "is_specialty": is_specialty,
        }
    elif normalized_type == "attribute":
        attribute_key = _normalize_attribute_key(target_name)
        if not attribute_key:
            return {"success": False, "message": f"Unknown attribute: {target_name}"}
        if not _attribute_training_allowed(trainer_profile, attribute_key):
            return {"success": False, "message": f"{trainer_npc.name} cannot teach {ATTRIBUTE_NAME_LABELS.get(attribute_key, attribute_key)}."}

        current_level = _character_attribute_level(character.id, attribute_key)
        max_trainable_level = int(trainer_profile.get("max_trainable_level", 20) or 20)
        if current_level > max_trainable_level:
            return {
                "success": False,
                "message": (
                    f"{trainer_npc.name} cannot meaningfully train {ATTRIBUTE_NAME_LABELS.get(attribute_key, attribute_key)} above level {max_trainable_level}."
                ),
            }

        xp_amount = _attribute_xp_for_lesson(
            current_level=current_level,
            trainer_tier=int(trainer_profile["trainer_tier"]),
            max_trainable_level=max_trainable_level,
            minutes=lesson_minutes,
        )
        price_copper = _lesson_price_copper(current_level, int(trainer_profile["trainer_tier"]), lesson_minutes, False)
        training_payload = {
            "training_type": "attribute",
            "target_name": attribute_key,
            "old_level": current_level,
        }
    else:
        return {"success": False, "message": "training_type must be 'skill' or 'attribute'."}

    current_currency = load_currency(character.id)
    if charge_price and _currency_to_copper(current_currency) < price_copper:
        return {
            "success": False,
            "message": "Not enough money.",
            "price": _copper_to_currency(price_copper),
            "currency": current_currency,
        }

    from services.adventure_state.tools import spend_time

    time_result = spend_time(
        campaign_id=campaign.id,
        action_type="teacher_training",
        minutes=lesson_minutes,
        description=f"Lesson with {trainer_npc.name} in {target_name}.",
    )
    if not time_result.get("success"):
        return {
            "success": False,
            "message": time_result.get("error") or time_result.get("message") or "Could not spend training time.",
        }

    if normalized_type == "skill":
        xp_result = add_skill_xp(
            character_id=character.id,
            skill_name=training_payload["target_name"],
            amount=xp_amount,
            reason=f"Lesson with {trainer_npc.name}",
        )
    else:
        xp_result = add_attribute_xp(
            character_id=character.id,
            attribute=training_payload["target_name"],
            amount=xp_amount,
            reason=f"Lesson with {trainer_npc.name}",
        )

    if not xp_result.get("success"):
        return xp_result

    if charge_price:
        save_currency(character.id, _copper_to_currency(_currency_to_copper(current_currency) - price_copper))

    return {
        "success": True,
        "tool": "train_with_teacher",
        "message": f"Completed a lesson with {trainer_npc.name}.",
        "trainer": _serialize_trainer_profile(trainer_npc, trainer_profile),
        "price": _copper_to_currency(price_copper),
        "price_charged": charge_price,
        "currency": load_currency(character.id),
        "time_result": time_result,
        "xp_result": xp_result,
        "reward_context": reward_context,
        "training": {
            **training_payload,
            "xp_awarded": xp_amount,
            "lesson_minutes": lesson_minutes,
            "trainer_max_trainable_level": int(trainer_profile.get("max_trainable_level", 20) or 20),
        },
    }
