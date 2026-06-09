"""Adventure state tools for location, time, and quest tracking."""

import json
import math
import random
from datetime import datetime

from models import (
    db,
    Campaign,
    CampaignLocation,
    CampaignQuest,
    Character,
    CharacterAttribute,
    CharacterSkill,
    SkillCheckLog,
    SkillDefinition,
)
from services.equipment.service import get_attack_profile, get_defense_profile
from services.resources.service import get_resources, remove_resource
from services.skills.constants import CORE_SKILLS
from services.currency.constants import GOLD_TO_COPPER, CURRENCY_CONVERSION_RATES
from services.currency.service import add_currency
from services.inventory.service import add_inventory_item, get_inventory, remove_inventory_item
from services.leveling.service import add_xp
from services.status_effects import get_status_effect_modifier_bundle, tick_status_effects
from services.timekeeping import (
    DEFAULT_INGAME_MINUTE,
    MINUTES_PER_DAY,
    TIME_ORDER,
    calendar_date_for_day,
    minute_for_time_label,
    normalize_ingame_minute,
    normalize_time_label,
    time_label_for_minute,
)
from services.world_data import (
    build_location_context_from_world_location,
    distance_km_between_coordinates,
    estimate_travel_between_coordinates,
    estimate_travel_between_world_locations,
    find_world_location,
    normalize_coordinate,
    resolve_coordinate_context,
)
from .enemy_archetypes import build_enemy_from_payload


QUEST_TYPE_REWARD_MULTIPLIERS = {
    "tutorial": 0.4,
    "general": 1.0,
    "delivery": 0.9,
    "travel": 0.9,
    "gathering": 1.0,
    "investigation": 1.1,
    "escort": 1.2,
    "hunt": 1.2,
    "cleanup": 1.15,
    "kill": 1.3,
}

DANGER_REWARD_MULTIPLIERS = {
    "safe": 0.75,
    "low": 0.9,
    "moderate": 1.0,
    "high": 1.25,
    "deadly": 1.6,
}

QUEST_BASE_CURRENCY_VALUE = 20
QUEST_BASE_XP = 25
NEGOTIATION_BONUS_BY_DANGER = {
    "safe": 5,
    "low": 8,
    "moderate": 12,
    "high": 18,
    "deadly": 25,
}

OBJECTIVE_SCHEMA = {
    "reach_location": {"one_of": ["location_id", "location_name"]},
    "talk_to_npc": {"required": ["npc_id"]},
    "return_to_npc": {"required": ["npc_id"]},
    "collect_item": {"required": ["required_count"], "one_of": ["item_id", "item_name"]},
    "bring_item": {"required": ["required_count"], "one_of": ["item_id", "item_name"]},
    "kill_enemy_type": {"required": ["enemy_type", "required_count"]},
    "kill_npc": {"required": ["npc_id"]},
}

SERVICE_SCHEMA = {
    "crafting": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "repair": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "training": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "transport": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "protection": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "access": {"required": ["provider_npc_id", "reward_value", "uses"]},
    "favor": {"required": ["provider_npc_id", "reward_value", "uses"]},
}

LOCATION_CONTEXT_FIELDS = (
    "coordinate_x",
    "coordinate_y",
    "coordinate_source",
    "region_id",
    "region_name",
    "subregion",
    "world_location_id",
    "world_location_name",
)
MAX_LOCAL_TRAVEL_DISTANCE_KM = 80
MAX_DECLARED_LONG_TRAVEL_DISTANCE_KM = 500
ACTION_TIME_RULES = {
    "conversation": {"default": 0, "min": 0, "max": 1},
    "short_exchange": {"default": 0, "min": 0, "max": 1},
    "local_move": {"default": 1, "min": 0, "max": 2},
    "quick_look": {"default": 1, "min": 0, "max": 2},
    "quick_search": {"default": 2, "min": 1, "max": 5},
    "look_around": {"default": 2, "min": 1, "max": 5},
    "thorough_search": {"default": 10, "min": 5, "max": 10},
    "drink": {"default": 1, "min": 0, "max": 2},
    "meal": {"default": 12, "min": 10, "max": 15},
    "inn_meal": {"default": 15, "min": 10, "max": 15},
    "shopping": {"default": 5, "min": 1, "max": 5},
    "trade": {"default": 5, "min": 1, "max": 5},
    "chore": {"default": 60, "min": 30, "max": 120},
    "paid_work": {"default": 60, "min": 30, "max": 120},
    "lesson": {"default": 60, "min": 60, "max": 60},
    "teacher_training": {"default": 60, "min": 60, "max": 60},
    "self_training": {"default": 15, "min": 5, "max": 60},
    "crafting_quick": {"default": 10, "min": 5, "max": 30},
    "repair_quick": {"default": 10, "min": 5, "max": 30},
    "crafting": {"default": 60, "min": 5, "max": 120},
    "repair": {"default": 30, "min": 5, "max": 120},
    "combat": {"default": 3, "min": 1, "max": 5},
    "wait": {"default": 15, "min": 1, "max": 1440},
}

REST_TIME_RULES = {
    "short": 30,
    "short_rest": 30,
    "long": 8 * 60,
    "long_rest": 8 * 60,
}

CHECK_PASS_TARGET = 11
CHECK_ROLL_MIN = 1
CHECK_ROLL_MAX = 20
CHECK_NORM_MAX = 101.0
CHECK_TYPE_DIFFICULTY_OFFSETS = {
    "trivial": -8,
    "easy": -3,
    "normal": 0,
    "hard": 6,
    "expert": 12,
    "master": 20,
    "legendary": 30,
}
CHECK_ATTRIBUTE_ALIASES = {
    "str": "strength",
    "staerke": "strength",
    "starke": "strength",
    "dex": "dexterity",
    "agility": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "per": "perception",
    "cha": "charisma",
}
COMBAT_STATE_KEY = "combat_state"


def _skill_name_key(value: str) -> str:
    normalized = (value or "").strip().lower()
    return "".join(ch for ch in normalized if ch.isalnum())


_CORE_SKILL_META_BY_NAME_KEY = {
    _skill_name_key(skill["name"]): {
        "linked_attribute": skill.get("linked_attribute"),
        "secondary_attributes": list(skill.get("secondary_attributes") or []),
    }
    for skill in CORE_SKILLS
}


def _normalize_check_attribute(attribute_name: str):
    normalized = (attribute_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = CHECK_ATTRIBUTE_ALIASES.get(normalized, normalized)
    valid = {"strength", "dexterity", "constitution", "intelligence", "perception", "charisma"}
    if normalized not in valid:
        return None
    return normalized


def _normalize_challenge_type(challenge_type: str):
    normalized = (challenge_type or "normal").strip().lower().replace("-", "_")
    aliases = {
        "very_easy": "trivial",
        "simple": "easy",
        "medium": "normal",
        "difficult": "hard",
        "very_hard": "expert",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in CHECK_TYPE_DIFFICULTY_OFFSETS:
        return None
    return normalized


def _normalize_secondary_attributes(raw_secondary_attributes):
    if not raw_secondary_attributes:
        return []
    if isinstance(raw_secondary_attributes, str):
        raw_secondary_attributes = [raw_secondary_attributes]
    normalized = []
    seen = set()
    for attribute in raw_secondary_attributes:
        normalized_attribute = _normalize_check_attribute(attribute)
        if not normalized_attribute:
            continue
        if normalized_attribute in seen:
            continue
        seen.add(normalized_attribute)
        normalized.append(normalized_attribute)
    return normalized


def _load_json_string_list(raw_value):
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value]
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
    return []


def _domain_for_action_type(action_type: str) -> str:
    normalized = (action_type or "general").strip().lower().replace("-", "_")
    if normalized in {"combat", "combat_action", "attack", "defense"}:
        return "combat"
    if normalized in {"social", "conversation", "persuasion", "intimidation"}:
        return "social"
    if normalized in {"crafting", "repair", "smithing", "alchemy"}:
        return "crafting"
    if normalized in {"travel", "exploration", "survival", "tracking"}:
        return "exploration"
    if normalized in {"arcane_lore", "knowledge", "research", "history"}:
        return "knowledge"
    if normalized in {"lockpicking", "utility", "thievery"}:
        return "utility"
    return "general"


def _normalized_check_value(value):
    value = max(0.0, float(value or 0.0))
    return 100.0 * math.log1p(value) / math.log(CHECK_NORM_MAX)


def _resolve_skill_and_attribute_context(character_id: int, skill_name: str):
    if not skill_name:
        return None, None

    normalized_skill_name_key = _skill_name_key(skill_name)
    skill_definition = None
    for candidate in SkillDefinition.query.filter_by(is_active=True).all():
        if _skill_name_key(candidate.name) == normalized_skill_name_key:
            skill_definition = candidate
            break
        aliases = _load_json_string_list(getattr(candidate, "aliases_json", None))
        if normalized_skill_name_key in {_skill_name_key(alias) for alias in aliases}:
            skill_definition = candidate
            break

    if not skill_definition:
        return None, None

    character_skill = CharacterSkill.query.filter_by(
        character_id=character_id,
        skill_id=skill_definition.id,
    ).first()

    skill_level = int(character_skill.skill_level or 0) if character_skill else 0

    core_meta = _CORE_SKILL_META_BY_NAME_KEY.get(_skill_name_key(skill_definition.name), {})
    skill_secondary_attributes = _normalize_secondary_attributes(
        _load_json_string_list(getattr(skill_definition, "secondary_attributes_json", None))
    )
    linked_attribute = _normalize_check_attribute(skill_definition.linked_attribute) or _normalize_check_attribute(
        core_meta.get("linked_attribute")
    )
    secondary_attributes = skill_secondary_attributes or _normalize_secondary_attributes(
        core_meta.get("secondary_attributes", [])
    )
    allowed_domains = _load_json_string_list(getattr(skill_definition, "allowed_domains_json", None))
    allowed_domains = [item.strip().lower().replace("-", "_") for item in allowed_domains if str(item).strip()]
    if not allowed_domains:
        allowed_domains = ["general"]

    return {
        "skill_definition": skill_definition,
        "skill_level": max(0, skill_level),
        "allowed_domains": allowed_domains,
    }, {
        "linked_attribute": linked_attribute,
        "secondary_attributes": secondary_attributes,
    }


def _resolve_check_roll(forced_roll=None):
    if forced_roll is None:
        return random.randint(CHECK_ROLL_MIN, CHECK_ROLL_MAX)
    try:
        forced_roll = int(forced_roll)
    except (TypeError, ValueError):
        return None
    if forced_roll < CHECK_ROLL_MIN or forced_roll > CHECK_ROLL_MAX:
        return None
    return forced_roll


def _load_campaign_notes(campaign: Campaign) -> dict:
    state = getattr(campaign, "state", None)
    if not state or not state.notes_json:
        return {}
    try:
        payload = json.loads(state.notes_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_campaign_notes(campaign: Campaign, notes_payload: dict) -> None:
    campaign_state = getattr(campaign, "state", None)
    if campaign_state is None:
        from models import CampaignState
        campaign_state = CampaignState(campaign_id=campaign.id, notes_json="{}")
        db.session.add(campaign_state)
        db.session.flush()
    campaign_state.notes_json = json.dumps(notes_payload, ensure_ascii=False)


def _get_combat_state(campaign: Campaign) -> dict | None:
    notes = _load_campaign_notes(campaign)
    combat = notes.get(COMBAT_STATE_KEY)
    return combat if isinstance(combat, dict) else None


def _set_combat_state(campaign: Campaign, combat_state: dict | None) -> None:
    notes = _load_campaign_notes(campaign)
    if combat_state is None:
        notes.pop(COMBAT_STATE_KEY, None)
    else:
        notes[COMBAT_STATE_KEY] = combat_state
    _save_campaign_notes(campaign, notes)


def _alive_enemies(combat_state: dict) -> list[dict]:
    enemies = combat_state.get("enemies", [])
    if not isinstance(enemies, list):
        return []
    return [enemy for enemy in enemies if isinstance(enemy, dict) and enemy.get("status") == "alive"]


def _combat_payload(combat_state: dict) -> dict:
    payload = dict(combat_state or {})
    payload["enemy_count_alive"] = len(_alive_enemies(payload))
    payload["current_actor"] = (
        payload["turn_order"][payload["current_turn_index"]]
        if payload.get("active") and payload.get("turn_order")
        else None
    )
    payload["combat_ongoing"] = bool(payload.get("active"))
    return payload


def _combat_level_adjusted_attack_score(base_attack_score: float, attacker_level: int, defender_level: int) -> float:
    level_delta = int(attacker_level) - int(defender_level)
    score = float(base_attack_score)
    if level_delta > 0:
        score += (level_delta * 0.90)
    elif level_delta < 0:
        score += (level_delta * 1.30)
    return score


def _resolve_hit_outcome(attack_score: float, dodge_score: float, block_score: float, block_threshold_bonus: float = 0.0) -> dict:
    attack_roll = random.randint(1, 20)
    defense_roll = random.randint(1, 20)
    attack_total = float(attack_score) + attack_roll
    dodge_total = float(dodge_score) + defense_roll
    block_total = float(block_score) + defense_roll
    defense_total = max(dodge_total, block_total)
    defense_type = "dodge" if dodge_total >= block_total else "block"
    margin = attack_total - defense_total

    if dodge_total >= attack_total + 6:
        return {
            "outcome": "clear_dodge",
            "damage_multiplier": 0.0,
            "attack_roll": attack_roll,
            "defense_roll": defense_roll,
            "attack_total": round(attack_total, 3),
            "dodge_total": round(dodge_total, 3),
            "block_total": round(block_total, 3),
            "defense_total": round(defense_total, 3),
            "defense_type": defense_type,
            "margin": round(margin, 3),
        }

    if block_total >= attack_total + 6 + float(block_threshold_bonus):
        return {
            "outcome": "clear_block",
            "damage_multiplier": 0.0,
            "attack_roll": attack_roll,
            "defense_roll": defense_roll,
            "attack_total": round(attack_total, 3),
            "dodge_total": round(dodge_total, 3),
            "block_total": round(block_total, 3),
            "defense_total": round(defense_total, 3),
            "defense_type": defense_type,
            "margin": round(margin, 3),
        }

    if margin >= 8:
        outcome = "full_hit"
        multiplier = 1.0
    elif margin >= 1:
        outcome = "partial_hit"
        multiplier = 0.45 if defense_type == "dodge" else 0.35
    else:
        outcome = "partial_hit"
        multiplier = 0.30 if defense_type == "dodge" else 0.20

    return {
        "outcome": outcome,
        "damage_multiplier": multiplier,
        "attack_roll": attack_roll,
        "defense_roll": defense_roll,
        "attack_total": round(attack_total, 3),
        "dodge_total": round(dodge_total, 3),
        "block_total": round(block_total, 3),
        "defense_total": round(defense_total, 3),
        "defense_type": defense_type,
        "margin": round(margin, 3),
    }


def start_combat(campaign_id: int, enemies_json=None):
    """Start a lightweight combat state with initiative, turn order, and enemy list."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    if _get_combat_state(campaign):
        return {"success": False, "error": "Combat is already active."}

    resources = get_resources(character.id)
    player_hp = int(resources.get("hp", {}).get("current", 0) or 0)
    player_hp_max = int(resources.get("hp", {}).get("max", 0) or 0)
    attributes = character.attributes
    player_initiative_base = int((getattr(attributes, "dexterity", 0) or 0) + (getattr(attributes, "perception", 0) or 0))

    enemies_payload = _load_json_payload(enemies_json, [])
    if not isinstance(enemies_payload, list):
        enemies_payload = []
    if not enemies_payload:
        enemies_payload = [{"name": "Hostile", "hp": 120, "attack_score": 35, "dodge_score": 22, "block_score": 20}]

    enemies = []
    for index, enemy in enumerate(enemies_payload, start=1):
        if not isinstance(enemy, dict):
            continue
        resolved_enemy = build_enemy_from_payload(enemy, index)
        if "initiative" not in enemy:
            resolved_enemy["initiative"] = int(random.randint(1, 20) + int(resolved_enemy.get("initiative", 8)))
        enemies.append(resolved_enemy)

    if not enemies:
        return {"success": False, "error": "No valid enemies provided."}

    player_initiative = random.randint(1, 20) + player_initiative_base
    enemy_best_initiative = max(enemy["initiative"] for enemy in enemies)
    turn_order = ["player", "enemies"] if player_initiative >= enemy_best_initiative else ["enemies", "player"]

    combat_state = {
        "active": True,
        "round": 1,
        "current_turn_index": 0,
        "turn_order": turn_order,
        "player": {
            "character_id": character.id,
            "name": character.name,
            "level": int(character.level or 1),
            "hp_current": player_hp,
            "hp_max": player_hp_max,
            "status": "alive" if player_hp > 0 else "dead",
            "initiative": player_initiative,
        },
        "enemies": enemies,
        "last_event": {
            "type": "combat_started",
            "player_initiative": player_initiative,
            "enemy_best_initiative": enemy_best_initiative,
            "first_actor": turn_order[0],
        },
    }
    _set_combat_state(campaign, combat_state)
    db.session.commit()

    return {
        "success": True,
        "tool": "start_combat",
        "combat": _combat_payload(combat_state),
    }


def grant_combat_loot(campaign_id: int):
    """Grant loot from defeated enemies in the current combat state exactly once."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state:
        return {"success": False, "error": "No combat state found."}

    enemies = combat_state.get("enemies", [])
    if not isinstance(enemies, list):
        return {"success": False, "error": "Combat state is invalid."}

    total_currency = {"gold": 0, "silver": 0, "copper": 0}
    granted_items = []
    granted_enemies = []
    xp_total = 0

    for enemy in enemies:
        if not isinstance(enemy, dict):
            continue
        if enemy.get("status") != "defeated":
            continue
        if bool(enemy.get("loot_granted", False)):
            continue

        reward_profile = _combat_reward_profile_for_enemy(enemy)
        xp_total += int(reward_profile["xp"])

        currency_payload = enemy.get("loot_currency", {})
        static_copper = _currency_value_to_copper(currency_payload if isinstance(currency_payload, dict) else {})
        computed_copper = int(reward_profile["money_copper"])
        total_enemy_copper = max(0, static_copper + computed_copper)
        merged_currency = _copper_to_currency_payload(total_enemy_copper)
        gold = int(merged_currency.get("gold", 0) or 0)
        silver = int(merged_currency.get("silver", 0) or 0)
        copper = int(merged_currency.get("copper", 0) or 0)
        if gold > 0 or silver > 0 or copper > 0:
            currency_result = add_currency(
                character_id=character.id,
                gold=gold,
                silver=silver,
                copper=copper,
            )
            if currency_result.success:
                total_currency["gold"] += gold
                total_currency["silver"] += silver
                total_currency["copper"] += copper

        loot_items = enemy.get("loot_items", [])
        quest_items = enemy.get("quest_items", [])
        for entry in [*loot_items, *quest_items]:
            if not isinstance(entry, dict):
                continue
            quantity = int(entry.get("quantity", 1) or 1)
            item_result = add_inventory_item(
                character_id=character.id,
                item=entry,
                quantity=quantity,
            ).to_dict()
            granted_items.append(item_result)

        enemy["loot_granted"] = True
        granted_enemies.append({
            "combat_id": enemy.get("combat_id"),
            "name": enemy.get("name"),
            "archetype_id": enemy.get("archetype_id"),
            "reward_role": reward_profile["role"],
            "reward_level": reward_profile["level"],
            "reward_xp": reward_profile["xp"],
            "reward_money_copper": total_enemy_copper,
        })

    xp_result = None
    if xp_total > 0:
        xp_result = add_xp(
            character_id=character.id,
            amount=int(xp_total),
            reason="Combat reward",
        ).to_dict()

    _set_combat_state(campaign, combat_state)
    db.session.commit()

    return {
        "success": True,
        "tool": "grant_combat_loot",
        "granted_enemy_count": len(granted_enemies),
        "granted_enemies": granted_enemies,
        "xp_total": int(xp_total),
        "xp_result": xp_result,
        "currency": total_currency,
        "items": granted_items,
        "combat": _combat_payload(combat_state),
    }


def get_combat_state(campaign_id: int):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state:
        return {"success": False, "error": "No active combat."}

    return {
        "success": True,
        "tool": "get_combat_state",
        "combat": _combat_payload(combat_state),
    }


def _advance_combat_turn(combat_state: dict) -> None:
    turn_order = combat_state.get("turn_order", ["player", "enemies"])
    current_index = int(combat_state.get("current_turn_index", 0))
    next_index = current_index + 1
    if next_index >= len(turn_order):
        combat_state["round"] = int(combat_state.get("round", 1)) + 1
        next_index = 0
    combat_state["current_turn_index"] = next_index


def resolve_attack(campaign_id: int, attacker_side: str = None, target_enemy_id: str = None):
    """Resolve one combat attack and update HP/defeat state."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state or not combat_state.get("active"):
        return {"success": False, "error": "No active combat."}

    current_actor = combat_state["turn_order"][combat_state["current_turn_index"]]
    effective_attacker_side = (attacker_side or current_actor).strip().lower()
    if effective_attacker_side != current_actor:
        return {"success": False, "error": f"It is currently {current_actor}'s turn."}

    alive_enemies = _alive_enemies(combat_state)
    if not alive_enemies:
        combat_state["active"] = False
        combat_state["last_event"] = {"type": "combat_finished", "winner": "player"}
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {"success": True, "tool": "resolve_attack", "combat": _combat_payload(combat_state)}

    if effective_attacker_side == "player":
        status_bundle = get_status_effect_modifier_bundle(character.id)
        if bool(status_bundle.get("cannot_act", False)):
            combat_state["last_event"] = {
                "type": "attack_skipped",
                "attacker": character.name,
                "reason": "status_effect_prevents_action",
                "active_statuses": list(status_bundle.get("active_names", [])),
            }
            tick_status_effects(character.id, tick_mode="combat", ticks=1)
            _advance_combat_turn(combat_state)
            _set_combat_state(campaign, combat_state)
            db.session.commit()
            return {"success": True, "tool": "resolve_attack", "combat": _combat_payload(combat_state)}

        target = None
        if target_enemy_id:
            for enemy in alive_enemies:
                if enemy.get("combat_id") == target_enemy_id:
                    target = enemy
                    break
        if target is None:
            target = alive_enemies[0]

        attack_profile = get_attack_profile(character.id)
        if not attack_profile.get("success"):
            return {"success": False, "error": attack_profile.get("message", "Attack profile unavailable.")}

        base_attack_score = (
            12.0
            + (float(attack_profile["scaling"].get("weighted_attribute_score", 0.0)) * 1.20)
            + (float(attack_profile["weapon"].get("skill_level", 0)) * 0.95)
            + (float(attack_profile["weapon"].get("item_level", 1)) * 0.70)
            + (float(character.level or 1) * 0.70)
            + float(attack_profile.get("status_effects", {}).get("attack_score_bonus", 0.0))
        )
        attack_score = _combat_level_adjusted_attack_score(base_attack_score, int(character.level or 1), int(target.get("level", int(character.level or 1))))
        hit_outcome = _resolve_hit_outcome(
            attack_score=attack_score,
            dodge_score=float(target.get("dodge_score", 0)),
            block_score=float(target.get("block_score", 0)),
            block_threshold_bonus=float(target.get("block_threshold_bonus", 0)),
        )
        raw_damage = random.randint(
            int(attack_profile["damage"]["final_min"]),
            int(attack_profile["damage"]["final_max"]),
        )
        dealt_damage = int(round(raw_damage * float(hit_outcome["damage_multiplier"])))
        dealt_damage = max(0, dealt_damage)
        target["hp_current"] = max(0, int(target.get("hp_current", 0)) - dealt_damage)
        if int(target["hp_current"]) <= 0:
            target["status"] = "defeated"

        combat_state["last_event"] = {
            "type": "player_attack",
            "attacker": character.name,
            "target": target.get("name"),
            "target_id": target.get("combat_id"),
            "raw_damage": raw_damage,
            "dealt_damage": dealt_damage,
            "outcome": hit_outcome["outcome"],
            "defense_type_used": hit_outcome["defense_type"],
            "target_hp_after": int(target.get("hp_current", 0)),
            "target_defeated": target.get("status") == "defeated",
            "attack_details": hit_outcome,
        }
        tick_status_effects(character.id, tick_mode="combat", ticks=1)
    else:
        attacker = alive_enemies[0]
        defense_profile = get_defense_profile(character.id)
        if not defense_profile.get("success"):
            return {"success": False, "error": defense_profile.get("message", "Defense profile unavailable.")}

        attack_score = _combat_level_adjusted_attack_score(
            float(attacker.get("attack_score", 30)),
            int(attacker.get("level", int(character.level or 1))),
            int(character.level or 1),
        )
        hit_outcome = _resolve_hit_outcome(
            attack_score=attack_score,
            dodge_score=float(defense_profile["scores"]["dodge_score"]),
            block_score=float(defense_profile["scores"]["block_score"]),
            block_threshold_bonus=float(defense_profile["armor"]["block_threshold_bonus_total"]),
        )
        raw_damage = random.randint(int(attacker.get("damage_min", 8)), int(attacker.get("damage_max", 16)))
        dealt_damage = int(round(raw_damage * float(hit_outcome["damage_multiplier"])))
        dealt_damage = max(0, dealt_damage)

        if dealt_damage > 0:
            hp_change = remove_resource(character.id, "hp", dealt_damage).to_dict()
            player_hp_after = int(hp_change["resources"]["hp"]["current"])
            player_status = hp_change["resources"]["character_status"]
        else:
            player_resources = get_resources(character.id)
            player_hp_after = int(player_resources["hp"]["current"])
            player_status = character.status

        combat_state["player"]["hp_current"] = player_hp_after
        combat_state["player"]["status"] = player_status
        combat_state["last_event"] = {
            "type": "enemy_attack",
            "attacker": attacker.get("name"),
            "target": character.name,
            "raw_damage": raw_damage,
            "dealt_damage": dealt_damage,
            "outcome": hit_outcome["outcome"],
            "defense_type_used": hit_outcome["defense_type"],
            "player_hp_after": player_hp_after,
            "player_defeated": player_status == "dead",
            "attack_details": hit_outcome,
        }

    if combat_state["player"]["status"] == "dead":
        combat_state["active"] = False
        combat_state["last_event"]["combat_result"] = "player_defeated"
    elif not _alive_enemies(combat_state):
        combat_state["active"] = False
        combat_state["last_event"]["combat_result"] = "enemies_defeated"
    else:
        _advance_combat_turn(combat_state)

    _set_combat_state(campaign, combat_state)
    db.session.commit()
    return {
        "success": True,
        "tool": "resolve_attack",
        "combat": _combat_payload(combat_state),
    }


def attempt_escape(campaign_id: int):
    """Attempt to escape from active combat."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state or not combat_state.get("active"):
        return {"success": False, "error": "No active combat."}

    alive_enemies = _alive_enemies(combat_state)
    if not alive_enemies:
        combat_state["active"] = False
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {"success": True, "tool": "attempt_escape", "escaped": True, "combat": _combat_payload(combat_state)}

    attributes = character.attributes
    dexterity = int(getattr(attributes, "dexterity", 0) or 0)
    perception = int(getattr(attributes, "perception", 0) or 0)
    escape_score = 12 + (dexterity * 1.0) + (perception * 0.6) + (int(character.level or 1) * 0.4) + random.randint(1, 20)
    enemy_pursuit = max(
        float(enemy.get("attack_score", 30)) * 0.75 + random.randint(1, 20)
        for enemy in alive_enemies
    )

    escaped = escape_score >= enemy_pursuit + 3
    combat_state["last_event"] = {
        "type": "attempt_escape",
        "escaped": bool(escaped),
        "escape_score": round(float(escape_score), 3),
        "enemy_pursuit_score": round(float(enemy_pursuit), 3),
    }

    if escaped:
        combat_state["active"] = False
        combat_state["last_event"]["combat_result"] = "escaped"
    else:
        _advance_combat_turn(combat_state)

    _set_combat_state(campaign, combat_state)
    db.session.commit()
    return {
        "success": True,
        "tool": "attempt_escape",
        "escaped": bool(escaped),
        "combat": _combat_payload(combat_state),
    }


def attempt_surrender(campaign_id: int):
    """Attempt surrender in an active combat. Only works when enemies allow surrender."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state or not combat_state.get("active"):
        return {"success": False, "error": "No active combat."}

    alive_enemies = _alive_enemies(combat_state)
    if not alive_enemies:
        combat_state["active"] = False
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {"success": True, "tool": "attempt_surrender", "surrendered": True, "combat": _combat_payload(combat_state)}

    willing = [enemy for enemy in alive_enemies if bool(enemy.get("allows_surrender", False))]
    if not willing:
        combat_state["last_event"] = {
            "type": "attempt_surrender",
            "surrendered": False,
            "reason": "enemies_refuse_surrender",
        }
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {
            "success": False,
            "tool": "attempt_surrender",
            "error": "The current enemies refuse surrender.",
            "combat": _combat_payload(combat_state),
        }

    priority = {"spared": 0, "captured": 1, "imprisoned": 2}
    outcome = sorted(
        [str(enemy.get("surrender_outcome", "captured")).strip().lower() or "captured" for enemy in willing],
        key=lambda key: priority.get(key, 1),
    )[0]

    combat_state["active"] = False
    combat_state["last_event"] = {
        "type": "attempt_surrender",
        "surrendered": True,
        "surrender_outcome": outcome,
        "accepted_by_enemy_count": len(willing),
    }
    _set_combat_state(campaign, combat_state)
    db.session.commit()
    return {
        "success": True,
        "tool": "attempt_surrender",
        "surrendered": True,
        "surrender_outcome": outcome,
        "combat": _combat_payload(combat_state),
    }


def attempt_ceasefire(campaign_id: int):
    """Attempt to mutually stop an active combat when opponents are willing."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state or not combat_state.get("active"):
        return {"success": False, "error": "No active combat."}

    current_actor = combat_state["turn_order"][combat_state["current_turn_index"]]
    if current_actor != "player":
        return {"success": False, "error": "It is not the player's turn."}

    alive_enemies = _alive_enemies(combat_state)
    if not alive_enemies:
        combat_state["active"] = False
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {"success": True, "tool": "attempt_ceasefire", "ceasefire": True, "combat": _combat_payload(combat_state)}

    willing = [enemy for enemy in alive_enemies if bool(enemy.get("allows_ceasefire", False))]
    if not willing:
        combat_state["last_event"] = {
            "type": "attempt_ceasefire",
            "ceasefire": False,
            "reason": "enemies_refuse_ceasefire",
        }
        _advance_combat_turn(combat_state)
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {
            "success": False,
            "tool": "attempt_ceasefire",
            "error": "The current enemies refuse to stop fighting.",
            "combat": _combat_payload(combat_state),
        }

    priority = {"truce": 0, "disengaged": 1, "withdrawn": 2}
    outcome = sorted(
        [str(enemy.get("ceasefire_outcome", "disengaged")).strip().lower() or "disengaged" for enemy in willing],
        key=lambda key: priority.get(key, 1),
    )[0]

    combat_state["active"] = False
    combat_state["last_event"] = {
        "type": "attempt_ceasefire",
        "ceasefire": True,
        "ceasefire_outcome": outcome,
        "accepted_by_enemy_count": len(willing),
        "combat_result": "ceasefire",
    }
    _set_combat_state(campaign, combat_state)
    db.session.commit()
    return {
        "success": True,
        "tool": "attempt_ceasefire",
        "ceasefire": True,
        "ceasefire_outcome": outcome,
        "combat": _combat_payload(combat_state),
    }


def attempt_spare(campaign_id: int, target_enemy_id: str = None):
    """Attempt to spare a weakened enemy during the player's turn."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    combat_state = _get_combat_state(campaign)
    if not combat_state or not combat_state.get("active"):
        return {"success": False, "error": "No active combat."}

    current_actor = combat_state["turn_order"][combat_state["current_turn_index"]]
    if current_actor != "player":
        return {"success": False, "error": "It is not the player's turn."}

    alive_enemies = _alive_enemies(combat_state)
    if not alive_enemies:
        combat_state["active"] = False
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {"success": True, "tool": "attempt_spare", "spared": True, "combat": _combat_payload(combat_state)}

    target = None
    if target_enemy_id:
        for enemy in alive_enemies:
            if enemy.get("combat_id") == target_enemy_id:
                target = enemy
                break
        if target is None:
            return {"success": False, "error": "Target enemy not found or already not alive."}
    else:
        target = alive_enemies[0]

    if not bool(target.get("allows_spare", True)):
        combat_state["last_event"] = {
            "type": "attempt_spare",
            "spared": False,
            "target_id": target.get("combat_id"),
            "target": target.get("name"),
            "reason": "enemy_refuses_mercy",
        }
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {
            "success": False,
            "tool": "attempt_spare",
            "error": "This enemy cannot be spared.",
            "combat": _combat_payload(combat_state),
        }

    hp_current = int(target.get("hp_current", 0) or 0)
    hp_max = max(1, int(target.get("hp_max", 1) or 1))
    hp_ratio = float(hp_current) / float(hp_max)
    if hp_ratio > 0.35:
        combat_state["last_event"] = {
            "type": "attempt_spare",
            "spared": False,
            "target_id": target.get("combat_id"),
            "target": target.get("name"),
            "reason": "target_not_weakened_enough",
            "target_hp_ratio": round(hp_ratio, 4),
        }
        _set_combat_state(campaign, combat_state)
        db.session.commit()
        return {
            "success": False,
            "tool": "attempt_spare",
            "error": "Target is not weakened enough to spare safely.",
            "combat": _combat_payload(combat_state),
        }

    target["status"] = "spared"
    target["hp_current"] = max(1, hp_current)
    spare_outcome = str(target.get("spare_outcome", "released")).strip().lower() or "released"
    combat_state["last_event"] = {
        "type": "attempt_spare",
        "spared": True,
        "target_id": target.get("combat_id"),
        "target": target.get("name"),
        "spare_outcome": spare_outcome,
        "target_hp_after": int(target["hp_current"]),
    }

    if not _alive_enemies(combat_state):
        combat_state["active"] = False
        combat_state["last_event"]["combat_result"] = "enemies_spared_or_defeated"
    else:
        _advance_combat_turn(combat_state)

    _set_combat_state(campaign, combat_state)
    db.session.commit()
    return {
        "success": True,
        "tool": "attempt_spare",
        "spared": True,
        "spare_outcome": spare_outcome,
        "combat": _combat_payload(combat_state),
    }


def _normalize_time_label(value: str) -> str:
    """Normalize time labels to the current coarse MVP time scale."""

    return normalize_time_label(value)


def _normalize_ingame_minute(value) -> int:
    """Normalize an exact in-game minute into the current day."""

    return normalize_ingame_minute(value)


def _time_label_for_minute(minute: int) -> str:
    """Return the coarse fantasy time label for an exact minute."""

    return time_label_for_minute(minute)


def _minute_for_time_label(label: str) -> int:
    """Return a stable representative minute for a coarse time label."""

    return minute_for_time_label(label)


def _campaign_current_minute(campaign: Campaign) -> int:
    """Return exact campaign minute, falling back to the old label when needed."""

    minute = getattr(campaign, "current_ingame_minute", None)
    if minute is None:
        return _minute_for_time_label(campaign.current_ingame_time)

    return _normalize_ingame_minute(minute)


def _apply_campaign_time(campaign: Campaign, day: int, minute: int) -> None:
    """Persist exact and display campaign time fields together."""

    campaign.current_ingame_day = max(1, int(day))
    campaign.current_ingame_minute = _normalize_ingame_minute(minute)
    campaign.current_ingame_time = _time_label_for_minute(campaign.current_ingame_minute)


def _advance_campaign_time(campaign: Campaign, minutes: int) -> dict:
    """Advance exact campaign time and return before/after labels."""

    old_day = int(campaign.current_ingame_day or 1)
    old_minute = _campaign_current_minute(campaign)
    old_time = _time_label_for_minute(old_minute)
    total_minutes = old_minute + int(minutes)
    day_delta, new_minute = divmod(total_minutes, MINUTES_PER_DAY)
    new_day = old_day + day_delta

    _apply_campaign_time(campaign, new_day, new_minute)

    return {
        "old_day": old_day,
        "new_day": new_day,
        "old_minute": old_minute,
        "new_minute": new_minute,
        "old_time": old_time,
        "new_time": campaign.current_ingame_time,
        "minutes_advanced": int(minutes),
        "old_calendar": calendar_date_for_day(old_day),
        "new_calendar": calendar_date_for_day(new_day),
    }


def _resolve_action_minutes(action_type: str, minutes=None) -> tuple[str, int, dict]:
    """Resolve or clamp action time according to backend action defaults."""

    normalized_action_type = str(action_type or "").strip().lower()
    if normalized_action_type not in ACTION_TIME_RULES:
        raise ValueError(f"Unsupported action_type: {action_type}")

    rule = ACTION_TIME_RULES[normalized_action_type]
    if minutes in (None, ""):
        resolved_minutes = int(rule["default"])
    else:
        try:
            resolved_minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValueError("Minutes must be an integer.") from exc

        resolved_minutes = max(int(rule["min"]), min(int(rule["max"]), resolved_minutes))

    return normalized_action_type, resolved_minutes, rule


def _minutes_until_morning(campaign: Campaign) -> int:
    """Return minutes until the next morning phase starts."""

    current_minute = _campaign_current_minute(campaign)
    morning_minute = minute_for_time_label("morning")

    if current_minute < morning_minute:
        return morning_minute - current_minute

    return MINUTES_PER_DAY - current_minute + morning_minute


def _coerce_optional_coordinate(value, field_name: str):
    """Return an optional coordinate float or raise a clear validation error."""

    if value in (None, ""):
        return None

    try:
        return normalize_coordinate(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def _get_current_campaign_location(campaign: Campaign):
    """Return the current campaign location row if one is available."""

    if not campaign or not campaign.current_location_id:
        return None

    return db.session.get(CampaignLocation, campaign.current_location_id)


def _copy_location_context_from_current(campaign: Campaign) -> dict:
    """Return inherited coordinate context for generated local sublocations."""

    current_location = _get_current_campaign_location(campaign)
    if not current_location:
        return {}

    if current_location.coordinate_x is None or current_location.coordinate_y is None:
        return {}

    return {
        "coordinate_x": normalize_coordinate(current_location.coordinate_x),
        "coordinate_y": normalize_coordinate(current_location.coordinate_y),
        "coordinate_source": "inherited",
        "region_id": current_location.region_id,
        "region_name": current_location.region_name,
        "subregion": current_location.subregion,
        "world_location_id": None,
        "world_location_name": None,
    }


def _resolve_location_context(
    campaign: Campaign,
    location_name: str,
    coordinate_x=None,
    coordinate_y=None,
    world_location_id: str = None,
) -> dict:
    """Resolve fixed, provided, or inherited coordinate context for a location."""

    if (coordinate_x is None) != (coordinate_y is None):
        raise ValueError("Both coordinate_x and coordinate_y are required when coordinates are provided.")

    fixed_location = None
    if world_location_id:
        fixed_location = find_world_location(world_location_id)

    if fixed_location is None:
        fixed_location = find_world_location(location_name)

    if fixed_location:
        return build_location_context_from_world_location(fixed_location)

    if coordinate_x is not None and coordinate_y is not None:
        context = resolve_coordinate_context(coordinate_x, coordinate_y)
        context["coordinate_source"] = "provided_coordinates"
        return context

    return _copy_location_context_from_current(campaign)


def _apply_location_context(location: CampaignLocation, context: dict, overwrite: bool = False) -> None:
    """Apply coordinate and region context to a campaign location."""

    for field_name in LOCATION_CONTEXT_FIELDS:
        if field_name not in context:
            continue

        value = context.get(field_name)
        current_value = getattr(location, field_name, None)
        if overwrite or current_value in (None, ""):
            if field_name in {"coordinate_x", "coordinate_y"} and value is not None:
                value = normalize_coordinate(value)
            setattr(location, field_name, value)


def _serialize_location_context(location: CampaignLocation) -> dict:
    """Return coordinate and region context for tool responses."""

    return {
        "coordinate_x": normalize_coordinate(location.coordinate_x) if location.coordinate_x is not None else None,
        "coordinate_y": normalize_coordinate(location.coordinate_y) if location.coordinate_y is not None else None,
        "coordinate_source": location.coordinate_source,
        "region_id": location.region_id,
        "region_name": location.region_name,
        "subregion": location.subregion,
        "world_location_id": location.world_location_id,
        "world_location_name": location.world_location_name,
    }


def _serialize_quest_location_reference(location_id: int | None) -> dict | None:
    """Return a quest location reference with coordinate context."""

    if location_id is None:
        return None

    location = db.session.get(CampaignLocation, location_id)
    if not location:
        return None

    return {
        "id": location.id,
        "name": location.name,
        "location_type": location.location_type,
        "location_context": _serialize_location_context(location),
    }


def update_location(
    campaign_id: int,
    location_name: str,
    location_type: str = None,
    description: str = None,
    coordinate_x=None,
    coordinate_y=None,
    world_location_id: str = None,
):
    """Create/find a campaign location and make it current."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    if not location_name or not location_name.strip():
        return {
            "success": False,
            "error": "Location name is required."
        }

    location_name = location_name.strip()

    try:
        coordinate_x = _coerce_optional_coordinate(coordinate_x, "coordinate_x")
        coordinate_y = _coerce_optional_coordinate(coordinate_y, "coordinate_y")
        location_context = _resolve_location_context(
            campaign=campaign,
            location_name=location_name,
            coordinate_x=coordinate_x,
            coordinate_y=coordinate_y,
            world_location_id=world_location_id,
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    existing_location = (
        CampaignLocation.query
        .filter_by(campaign_id=campaign.id, name=location_name)
        .first()
    )

    if existing_location:
        location = existing_location

        if location_type and not location.location_type:
            location.location_type = location_type

        if description and not location.description:
            location.description = description
    else:
        location = CampaignLocation(
            campaign_id=campaign.id,
            name=location_name,
            location_type=location_type or "custom",
            description=description or "",
            is_discovered=True,
            is_custom=True
        )
        db.session.add(location)
        db.session.flush()

    should_overwrite_context = bool(
        location_context
        and (
            coordinate_x is not None
            or coordinate_y is not None
            or find_world_location(world_location_id)
            or find_world_location(location_name)
        )
    )
    _apply_location_context(
        location=location,
        context=location_context,
        overwrite=should_overwrite_context,
    )

    if hasattr(campaign, "current_location_id"):
        campaign.current_location_id = location.id

    open_quests = (
        CampaignQuest.query
        .filter_by(campaign_id=campaign.id, status="active")
        .all()
    )

    for quest in open_quests:
        objectives = _load_json_payload(quest.objectives_json, [])
        if not isinstance(objectives, list):
            continue

        changed = False
        for objective in objectives:
            if not isinstance(objective, dict):
                continue

            if _normalize_text(objective.get("objective_type")) != "reach_location":
                continue

            target_location_id = objective.get("location_id")
            target_location_name = _normalize_text(objective.get("location_name"))
            location_id_matches = target_location_id is not None and str(target_location_id) == str(location.id)
            location_name_matches = target_location_name and target_location_name == _normalize_text(location.name)

            if not location_id_matches and not location_name_matches:
                continue

            objective["current_count"] = 1
            objective["is_completed"] = True
            objective["location_id"] = location.id
            changed = True

        if not changed:
            continue

        quest.objectives_json = json.dumps(objectives)
        if _all_objectives_completed(objectives):
            quest.status = "completed"
            if not quest.completed_at:
                quest.completed_at = datetime.utcnow()

    db.session.commit()

    return {
        "success": True,
        "tool": "update_location",
        "location_id": location.id,
        "location_name": location.name,
        "location_type": location.location_type,
        "location_context": _serialize_location_context(location),
    }


def move_to_coordinates(
    campaign_id: int,
    destination_name: str,
    coordinate_x=None,
    coordinate_y=None,
    world_location_id: str = None,
    location_type: str = None,
    description: str = None,
    travel_mode: str = "walk",
    terrain: str = None,
    allow_long_travel: bool = False,
):
    """Move the current campaign position across the Avalion map with distance validation."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    current_location = _get_current_campaign_location(campaign)
    if not current_location or current_location.coordinate_x is None or current_location.coordinate_y is None:
        return {
            "success": False,
            "error": "Current location has no map coordinates."
        }
    start_location_id = current_location.id
    start_location_name = current_location.name
    start_coordinate_x = normalize_coordinate(current_location.coordinate_x)
    start_coordinate_y = normalize_coordinate(current_location.coordinate_y)
    start_world_location_id = current_location.world_location_id

    if not destination_name or not destination_name.strip():
        return {
            "success": False,
            "error": "Destination name is required."
        }

    destination_name = destination_name.strip()
    fixed_location = None
    if world_location_id:
        fixed_location = find_world_location(world_location_id)

    if fixed_location is None:
        fixed_location = find_world_location(destination_name)

    try:
        if fixed_location:
            destination_x = normalize_coordinate(fixed_location["x"])
            destination_y = normalize_coordinate(fixed_location["y"])
            resolved_world_location_id = fixed_location["id"]
            resolved_destination_name = fixed_location["name"]
        else:
            destination_x = _coerce_optional_coordinate(coordinate_x, "coordinate_x")
            destination_y = _coerce_optional_coordinate(coordinate_y, "coordinate_y")
            resolved_world_location_id = None
            resolved_destination_name = destination_name

            if destination_x is None or destination_y is None:
                raise ValueError(
                    "Generated map travel requires coordinate_x and coordinate_y, "
                    "or a known world_location_id."
                )

        destination_context = resolve_coordinate_context(destination_x, destination_y)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    travel_estimate = None
    if start_world_location_id and resolved_world_location_id:
        travel_estimate = estimate_travel_between_world_locations(
            start_world_location_id,
            resolved_world_location_id,
            travel_mode=travel_mode,
            terrain=terrain,
        )

    if travel_estimate is None:
        travel_estimate = estimate_travel_between_coordinates(
            start_coordinate_x,
            start_coordinate_y,
            destination_x,
            destination_y,
            travel_mode=travel_mode,
            terrain=terrain,
        )

    distance_km = travel_estimate["distance_km"]
    max_distance_km = (
        MAX_DECLARED_LONG_TRAVEL_DISTANCE_KM
        if allow_long_travel
        else MAX_LOCAL_TRAVEL_DISTANCE_KM
    )

    if distance_km > max_distance_km:
        return {
            "success": False,
            "error": (
                f"Destination is too far for this move ({distance_km} km, "
                f"max {max_distance_km} km)."
            ),
            "movement": {
                "from_location_id": start_location_id,
                "from_location_name": start_location_name,
                "from_coordinate_x": start_coordinate_x,
                "from_coordinate_y": start_coordinate_y,
                "to_location_name": resolved_destination_name,
                "to_coordinate_x": destination_x,
                "to_coordinate_y": destination_y,
                "distance_km": distance_km,
                "estimated_minutes": travel_estimate["estimated_minutes"],
                "travel_estimate": travel_estimate,
                "max_distance_km": max_distance_km,
                "travel_mode": travel_mode or "walk",
                "requires_smaller_steps": True,
            },
        }

    moved = update_location(
        campaign_id=campaign_id,
        location_name=resolved_destination_name,
        location_type=location_type or ("fixed_world_location" if fixed_location else "map_area"),
        description=description,
        coordinate_x=destination_x,
        coordinate_y=destination_y,
        world_location_id=resolved_world_location_id,
    )

    if not moved.get("success"):
        return moved

    time_change = _advance_campaign_time(campaign, travel_estimate["estimated_minutes"])
    db.session.commit()

    moved["tool"] = "move_to_coordinates"
    moved["movement"] = {
        "from_location_id": start_location_id,
        "from_location_name": start_location_name,
        "from_coordinate_x": start_coordinate_x,
        "from_coordinate_y": start_coordinate_y,
        "to_location_id": moved["location_id"],
        "to_location_name": moved["location_name"],
        "to_coordinate_x": destination_x,
        "to_coordinate_y": destination_y,
        "distance_km": distance_km,
        "estimated_minutes": travel_estimate["estimated_minutes"],
        "travel_estimate": travel_estimate,
        "max_distance_km": max_distance_km,
        "travel_mode": travel_mode or "walk",
        "allow_long_travel": bool(allow_long_travel),
        "destination_region_id": destination_context.get("region_id"),
        "destination_region_name": destination_context.get("region_name"),
        "destination_subregion": destination_context.get("subregion"),
    }
    moved["time"] = time_change
    return moved


def advance_time(campaign_id: int, minutes: int):
    """Advance the active campaign's exact in-game clock."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "Minutes must be an integer."
        }

    if minutes < 0:
        return {
            "success": False,
            "error": "Minutes must be zero or greater."
        }

    time_change = _advance_campaign_time(campaign, minutes)
    db.session.commit()
    status_tick = tick_status_effects(campaign.character_id, tick_mode="time", ticks=1)

    return {
        "success": True,
        "tool": "advance_time",
        "status_tick": status_tick,
        **time_change,
    }


def spend_time(campaign_id: int, action_type: str, minutes=None, description: str = None):
    """Spend backend-controlled time for a normal non-travel action."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    try:
        action_type, resolved_minutes, rule = _resolve_action_minutes(action_type, minutes)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "supported_action_types": sorted(ACTION_TIME_RULES),
        }

    time_change = _advance_campaign_time(campaign, resolved_minutes)
    db.session.commit()
    status_tick = tick_status_effects(campaign.character_id, tick_mode="time", ticks=1)

    return {
        "success": True,
        "tool": "spend_time",
        "action_type": action_type,
        "description": description,
        "time_rule": {
            "default_minutes": rule["default"],
            "min_minutes": rule["min"],
            "max_minutes": rule["max"],
        },
        "status_tick": status_tick,
        **time_change,
    }


def rest(campaign_id: int, rest_type: str = "short"):
    """Rest or sleep using backend-controlled time costs."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    normalized_rest_type = str(rest_type or "short").strip().lower()
    if normalized_rest_type == "sleep_until_morning":
        minutes = _minutes_until_morning(campaign)
    elif normalized_rest_type in REST_TIME_RULES:
        minutes = REST_TIME_RULES[normalized_rest_type]
    else:
        return {
            "success": False,
            "error": f"Unsupported rest_type: {rest_type}",
            "supported_rest_types": sorted([*REST_TIME_RULES, "sleep_until_morning"]),
        }

    time_change = _advance_campaign_time(campaign, minutes)
    db.session.commit()
    status_tick = tick_status_effects(campaign.character_id, tick_mode="time", ticks=1)

    return {
        "success": True,
        "tool": "rest",
        "rest_type": normalized_rest_type,
        "status_tick": status_tick,
        **time_change,
    }


def perform_check(
    campaign_id: int,
    action_text: str,
    challenge_level: int,
    challenge_type: str = "normal",
    skill_name: str = None,
    primary_attribute: str = None,
    secondary_attributes=None,
    include_character_level: bool = True,
    action_type: str = "general",
    forced_roll=None,
):
    """Resolve an attribute/skill check with backend-owned math and outcome."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "error": "Character not found."}

    attributes = character.attributes
    if not attributes:
        return {"success": False, "error": "Character attributes not found."}

    if not action_text or not str(action_text).strip():
        return {"success": False, "error": "action_text is required."}

    try:
        challenge_level = int(challenge_level)
    except (TypeError, ValueError):
        return {"success": False, "error": "challenge_level must be an integer."}

    if challenge_level < 1 or challenge_level > 100:
        return {"success": False, "error": "challenge_level must be between 1 and 100."}

    normalized_challenge_type = _normalize_challenge_type(challenge_type)
    if not normalized_challenge_type:
        return {"success": False, "error": "Unknown challenge_type."}

    skill_context = None
    resolved_skill_context = None
    if skill_name:
        skill_context, resolved_skill_context = _resolve_skill_and_attribute_context(character.id, skill_name)
        if not skill_context:
            return {"success": False, "error": f"Skill not found: {skill_name}"}
        action_domain = _domain_for_action_type(action_type)
        allowed_domains = list(skill_context.get("allowed_domains") or ["general"])
        if action_domain not in allowed_domains and "general" not in allowed_domains:
            skill_definition = skill_context["skill_definition"]
            return {
                "success": False,
                "error": (
                    f"Skill '{skill_definition.name}' is not allowed for action domain "
                    f"'{action_domain}'. Allowed domains: {', '.join(allowed_domains)}."
                ),
            }

    resolved_primary_attribute = _normalize_check_attribute(primary_attribute)
    if not resolved_primary_attribute and resolved_skill_context:
        resolved_primary_attribute = resolved_skill_context.get("linked_attribute")
    if not resolved_primary_attribute:
        return {"success": False, "error": "A valid primary attribute is required."}

    resolved_secondary_attributes = _normalize_secondary_attributes(secondary_attributes)
    if not resolved_secondary_attributes and resolved_skill_context:
        resolved_secondary_attributes = list(resolved_skill_context.get("secondary_attributes") or [])
    resolved_secondary_attributes = [
        attribute
        for attribute in resolved_secondary_attributes
        if attribute != resolved_primary_attribute
    ]

    roll_value = _resolve_check_roll(forced_roll)
    if roll_value is None:
        return {"success": False, "error": "forced_roll must be an integer between 1 and 20 when provided."}

    primary_attribute_value = int(getattr(attributes, resolved_primary_attribute, 0) or 0)
    primary_effective = _normalized_check_value(primary_attribute_value)

    secondary_effective = 0.0
    secondary_values = []
    if resolved_secondary_attributes:
        secondary_values = [
            int(getattr(attributes, attribute_key, 0) or 0)
            for attribute_key in resolved_secondary_attributes
        ]
        if secondary_values:
            secondary_effective = _normalized_check_value(sum(secondary_values) / len(secondary_values))

    skill_level = int(skill_context["skill_level"]) if skill_context else 0
    skill_effective = _normalized_check_value(skill_level)

    level_effective = _normalized_check_value(character.level if include_character_level else 0)
    status_bundle = get_status_effect_modifier_bundle(character.id)

    player_score = (
        0.50 * primary_effective
        + 0.10 * secondary_effective
        + 0.35 * skill_effective
        + 0.05 * level_effective
        + float(status_bundle.get("check_bonus", 0.0))
    )
    challenge_score = float(challenge_level + CHECK_TYPE_DIFFICULTY_OFFSETS[normalized_challenge_type])
    margin = player_score - challenge_score
    total_value = roll_value + margin
    required_roll = CHECK_PASS_TARGET - margin

    if required_roll <= CHECK_ROLL_MIN:
        success_chance_percent = 100
    elif required_roll > CHECK_ROLL_MAX:
        success_chance_percent = 0
    else:
        success_chance_percent = int(round(((CHECK_ROLL_MAX - required_roll + 1) / CHECK_ROLL_MAX) * 100))

    is_success = total_value >= CHECK_PASS_TARGET
    if total_value <= CHECK_PASS_TARGET - 8:
        outcome = "critical_failure"
    elif total_value < CHECK_PASS_TARGET:
        outcome = "failure"
    elif total_value < CHECK_PASS_TARGET + 4:
        outcome = "partial_success"
    elif total_value < CHECK_PASS_TARGET + 8:
        outcome = "success"
    elif total_value < CHECK_PASS_TARGET + 12:
        outcome = "strong_success"
    else:
        outcome = "critical_success"

    skill_definition = skill_context["skill_definition"] if skill_context else None
    log_row = SkillCheckLog(
        campaign_id=campaign.id,
        character_id=character.id,
        action_text=str(action_text).strip(),
        action_type=(action_type or "general").strip().lower() or "general",
        skill_id=skill_definition.id if skill_definition else None,
        attribute_used=resolved_primary_attribute,
        difficulty_value=int(round(challenge_score)),
        roll_value=int(roll_value),
        total_value=int(round(total_value)),
        outcome=outcome,
    )
    db.session.add(log_row)
    db.session.commit()

    return {
        "success": True,
        "tool": "perform_check",
        "check": {
            "is_success": bool(is_success),
            "outcome": outcome,
            "action_text": str(action_text).strip(),
            "action_type": (action_type or "general").strip().lower() or "general",
            "challenge_level": challenge_level,
            "challenge_type": normalized_challenge_type,
            "challenge_score": round(challenge_score, 2),
            "roll_value": int(roll_value),
            "pass_target": CHECK_PASS_TARGET,
            "required_roll": round(required_roll, 2),
            "success_chance_percent": max(0, min(100, success_chance_percent)),
            "total_value": round(total_value, 2),
            "margin": round(margin, 2),
            "character_level_used": bool(include_character_level),
            "skill_name": skill_definition.name if skill_definition else None,
            "skill_level": skill_level,
            "skill_allowed_domains": list(skill_context.get("allowed_domains") or ["general"]) if skill_context else [],
            "primary_attribute": {
                "key": resolved_primary_attribute,
                "value": primary_attribute_value,
                "effective": round(primary_effective, 2),
            },
            "secondary_attributes": [
                {"key": key, "value": value}
                for key, value in zip(resolved_secondary_attributes, secondary_values)
            ],
            "score_breakdown": {
                "primary_component": round(0.50 * primary_effective, 2),
                "secondary_component": round(0.10 * secondary_effective, 2),
                "skill_component": round(0.35 * skill_effective, 2),
                "level_component": round(0.05 * level_effective, 2),
                "status_component": round(float(status_bundle.get("check_bonus", 0.0)), 2),
            },
            "status_effects": status_bundle,
            "log_id": log_row.id,
        },
    }


def _serialize_json_payload(value, empty_fallback):
    """Serialize flexible JSON-like tool payloads into stored text."""

    if value in (None, ""):
        return json.dumps(empty_fallback)

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return json.dumps(empty_fallback)
        return value

    return json.dumps(value)


def _load_json_payload(value, empty_fallback):
    """Deserialize stored or tool-provided JSON-like payloads."""

    if value in (None, ""):
        return empty_fallback

    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return empty_fallback

    return empty_fallback


def _serialize_quest_record(quest):
    """Return one quest as a backend-friendly response payload."""

    return {
        "id": quest.id,
        "title": quest.title,
        "description": quest.description or "",
        "quest_type": quest.quest_type or "general",
        "status": quest.status,
        "quest_giver_npc_id": quest.quest_giver_npc_id,
        "turn_in_npc_id": quest.turn_in_npc_id,
        "start_location_id": quest.start_location_id,
        "target_location_id": quest.target_location_id,
        "turn_in_location_id": quest.turn_in_location_id,
        "location_refs": {
            "start": _serialize_quest_location_reference(quest.start_location_id),
            "target": _serialize_quest_location_reference(quest.target_location_id),
            "turn_in": _serialize_quest_location_reference(quest.turn_in_location_id),
        },
        "objectives": _load_json_payload(quest.objectives_json, []),
        "rewards": _load_json_payload(quest.rewards_json, {}),
        "reward_rules": _load_json_payload(quest.reward_rules_json, {}),
        "reward_gold": quest.reward_gold,
        "reward_xp": quest.reward_xp,
        "reward_items": _load_json_payload(quest.reward_items_json, []),
        "started_at": quest.started_at.isoformat() if quest.started_at else None,
        "completed_at": quest.completed_at.isoformat() if quest.completed_at else None,
        "turned_in_at": quest.turned_in_at.isoformat() if quest.turned_in_at else None,
        "reward_claimed_at": quest.reward_claimed_at.isoformat() if quest.reward_claimed_at else None,
        "failed_at": quest.failed_at.isoformat() if quest.failed_at else None,
    }


def _normalize_rewards_payload(rewards_payload, reward_rules: dict | None = None):
    """Normalize flexible quest rewards into the backend reward structure."""

    rewards_payload = rewards_payload or {}
    reward_rules = reward_rules or {}
    normalized = {}

    if not isinstance(rewards_payload, dict):
        return normalized

    currency_payload = rewards_payload.get("currency")
    if isinstance(currency_payload, dict):
        normalized["currency"] = {
            "gold": int(currency_payload.get("gold", 0) or 0),
            "silver": int(currency_payload.get("silver", 0) or 0),
            "copper": int(currency_payload.get("copper", 0) or 0),
        }
    else:
        flat_gold = int(rewards_payload.get("gold", 0) or 0)
        flat_silver = int(rewards_payload.get("silver", 0) or 0)
        flat_copper = int(rewards_payload.get("copper", 0) or 0)
        if flat_gold or flat_silver or flat_copper:
            normalized["currency"] = {
                "gold": flat_gold,
                "silver": flat_silver,
                "copper": flat_copper,
            }

    if "xp" in rewards_payload:
        normalized["xp"] = int(rewards_payload.get("xp", 0) or 0)
    elif reward_rules:
        normalized["xp"] = int(
            reward_rules.get("suggested_xp")
            or reward_rules.get("xp_min")
            or 0
        )

    items = rewards_payload.get("items")
    if isinstance(items, list):
        normalized["items"] = items

    services = rewards_payload.get("services")
    if isinstance(services, list):
        normalized["services"] = services

    if reward_rules and "currency" not in normalized and not normalized.get("items") and not normalized.get("services"):
        reward_value = int(
            reward_rules.get("suggested_reward_value")
            or reward_rules.get("reward_value_min")
            or 0
        )
        silver_to_copper = int(CURRENCY_CONVERSION_RATES["silver_to_copper"])
        normalized["currency"] = {
            "gold": reward_value // GOLD_TO_COPPER,
            "silver": (reward_value % GOLD_TO_COPPER) // silver_to_copper,
            "copper": reward_value % silver_to_copper,
        }

    return normalized


def _clamp_rewards_to_rules(rewards_payload, reward_rules: dict):
    """Keep concrete rewards inside the backend rule ranges."""

    if not isinstance(rewards_payload, dict):
        return rewards_payload

    rules = reward_rules or {}
    xp_min = int(rules.get("xp_min", 0) or 0)
    xp_max = int(rules.get("xp_max", xp_min) or xp_min)
    if xp_max < xp_min:
        xp_max = xp_min

    xp_amount = int(rewards_payload.get("xp", rules.get("suggested_xp", xp_min)) or 0)
    if xp_amount < xp_min:
        xp_amount = xp_min
    if xp_amount > xp_max:
        xp_amount = xp_max

    rewards_payload["xp"] = xp_amount

    currency_payload = rewards_payload.get("currency")
    items = rewards_payload.get("items", [])
    services = rewards_payload.get("services", [])
    if isinstance(currency_payload, dict) and not items and not services:
        silver_to_copper = int(CURRENCY_CONVERSION_RATES["silver_to_copper"])
        total_currency_value = (
            int(currency_payload.get("gold", 0) or 0) * GOLD_TO_COPPER
            + int(currency_payload.get("silver", 0) or 0) * silver_to_copper
            + int(currency_payload.get("copper", 0) or 0)
        )
        reward_value_min = int(rules.get("reward_value_min", total_currency_value) or 0)
        reward_value_max = int(rules.get("reward_value_max", reward_value_min) or reward_value_min)
        if reward_value_max < reward_value_min:
            reward_value_max = reward_value_min

        clamped_value = total_currency_value
        if clamped_value < reward_value_min:
            clamped_value = reward_value_min
        if clamped_value > reward_value_max:
            clamped_value = reward_value_max

        gold = clamped_value // GOLD_TO_COPPER
        remainder = clamped_value % GOLD_TO_COPPER
        silver = remainder // silver_to_copper
        copper = remainder % silver_to_copper
        rewards_payload["currency"] = {
            "gold": gold,
            "silver": silver,
            "copper": copper,
        }

    return rewards_payload


def _normalize_reward_rules(
    reward_rules_json=None,
    quest_type: str = "general",
    quest_level: int = 1,
    danger_level: str = "moderate",
):
    """Build or normalize reward rules from quest level, type, and danger."""

    rules = _load_json_payload(reward_rules_json, {})
    if not isinstance(rules, dict):
        rules = {}

    quest_type = _normalize_text(quest_type) or "general"
    danger_level = _normalize_text(danger_level) or "moderate"
    quest_level = max(1, int(quest_level or 1))

    type_multiplier = float(QUEST_TYPE_REWARD_MULTIPLIERS.get(quest_type, 1.0))
    danger_multiplier = float(DANGER_REWARD_MULTIPLIERS.get(danger_level, 1.0))
    combined_multiplier = type_multiplier * danger_multiplier

    suggested_currency_value = int(round(QUEST_BASE_CURRENCY_VALUE * quest_level * combined_multiplier))
    suggested_xp = int(round(QUEST_BASE_XP * quest_level * combined_multiplier))

    xp_min_default = max(0, int(round(suggested_xp * 0.85)))
    xp_max_default = max(xp_min_default, int(round(suggested_xp * 1.15)))
    reward_value_min_default = max(0, int(round(suggested_currency_value * 0.85)))
    reward_value_max_default = max(reward_value_min_default, int(round(suggested_currency_value * 1.15)))

    return {
        "quest_level": quest_level,
        "danger_level": danger_level,
        "quest_type_multiplier": type_multiplier,
        "danger_multiplier": danger_multiplier,
        "combined_multiplier": combined_multiplier,
        "suggested_xp": suggested_xp,
        "suggested_reward_value": suggested_currency_value,
        "xp_min": xp_min_default,
        "xp_max": xp_max_default,
        "reward_value_min": reward_value_min_default,
        "reward_value_max": reward_value_max_default,
        "negotiable_bonus_percent": int(
            rules.get(
                "negotiable_bonus_percent",
                NEGOTIATION_BONUS_BY_DANGER.get(danger_level, 12),
            ) or 0
        ),
    }


def _validate_objective_payload(objectives):
    """Validate structured quest objectives against the supported schema."""

    if not isinstance(objectives, list):
        return False, "Quest objectives must be a JSON array of objective objects."

    if not objectives:
        return False, "Quest objectives must contain at least one objective."

    for index, objective in enumerate(objectives):
        if not isinstance(objective, dict):
            return False, f"Objective #{index} must be an object."

        objective_type = _normalize_text(objective.get("objective_type"))
        if objective_type not in OBJECTIVE_SCHEMA:
            return False, f"Objective #{index} has unsupported type '{objective.get('objective_type')}'."

        schema = OBJECTIVE_SCHEMA[objective_type]
        for field_name in schema.get("required", []):
            value = objective.get(field_name)
            if value in (None, "", []):
                return False, f"Objective #{index} of type '{objective_type}' requires field '{field_name}'."

        one_of_fields = schema.get("one_of", [])
        if one_of_fields and not any(objective.get(field_name) not in (None, "", []) for field_name in one_of_fields):
            joined_fields = "', '".join(one_of_fields)
            return False, f"Objective #{index} of type '{objective_type}' requires one of '{joined_fields}'."

        if "required_count" in schema.get("required", []):
            try:
                required_count = int(objective.get("required_count", 0))
            except (TypeError, ValueError):
                return False, f"Objective #{index} has an invalid required_count."

            if required_count <= 0:
                return False, f"Objective #{index} must have required_count greater than 0."

    return True, None


def _validate_service_payload(services):
    """Validate structured quest service rewards against the supported schema."""

    if services in (None, []):
        return True, None

    if not isinstance(services, list):
        return False, "Quest reward services must be a JSON array."

    for index, service in enumerate(services):
        if not isinstance(service, dict):
            return False, f"Service reward #{index} must be an object."

        service_type = _normalize_text(service.get("service_type"))
        if service_type not in SERVICE_SCHEMA:
            return False, f"Service reward #{index} has unsupported type '{service.get('service_type')}'."

        schema = SERVICE_SCHEMA[service_type]
        for field_name in schema.get("required", []):
            value = service.get(field_name)
            if value in (None, "", []):
                return False, f"Service reward #{index} of type '{service_type}' requires field '{field_name}'."

        try:
            reward_value = int(service.get("reward_value", 0))
        except (TypeError, ValueError):
            return False, f"Service reward #{index} has an invalid reward_value."

        if reward_value < 0:
            return False, f"Service reward #{index} must not have a negative reward_value."

        try:
            uses = int(service.get("uses", 0))
        except (TypeError, ValueError):
            return False, f"Service reward #{index} has an invalid uses value."

        if uses <= 0:
            return False, f"Service reward #{index} must have uses greater than 0."

    return True, None


def _normalize_text(value):
    """Return a normalized text value for loose backend comparisons."""

    return str(value or "").strip().lower()


def _inventory_item_counts(character_id: int):
    """Count carried inventory items by id and by name."""

    inventory_blob = get_inventory(character_id)
    counts_by_id = {}
    counts_by_name = {}

    for container in inventory_blob.get("inventory", {}).get("containers", []):
        if container.get("source") == "nearby":
            continue

        for item in container.get("items", []):
            quantity = int(item.get("quantity", 1) or 1)
            item_id = _normalize_text(item.get("item_id"))
            item_name = _normalize_text(item.get("name"))

            if item_id:
                counts_by_id[item_id] = counts_by_id.get(item_id, 0) + quantity
            if item_name:
                counts_by_name[item_name] = counts_by_name.get(item_name, 0) + quantity

    return counts_by_id, counts_by_name


def _objective_required_count(objective):
    """Return a normalized required count for count-based quest objectives."""

    return int(
        objective.get("required_count")
        or objective.get("item_count")
        or objective.get("count")
        or 1
    )


def _evaluate_objective(
    character_id: int,
    objective: dict,
    current_location_id=None,
    current_location_name=None,
    current_npc_id=None,
):
    """Evaluate one quest objective against current backend state."""

    objective_type = _normalize_text(objective.get("objective_type"))
    counts_by_id, counts_by_name = _inventory_item_counts(character_id)
    objective_copy = dict(objective)

    if objective_type in {"collect_item", "bring_item"}:
        item_id = _normalize_text(objective.get("item_id"))
        item_name = _normalize_text(objective.get("item_name"))
        required_count = _objective_required_count(objective)

        current_count = 0
        if item_id:
            current_count = counts_by_id.get(item_id, 0)
        elif item_name:
            current_count = counts_by_name.get(item_name, 0)

        objective_copy["current_count"] = current_count
        objective_copy["required_count"] = required_count
        objective_copy["is_completed"] = current_count >= required_count
        return objective_copy

    if objective_type in {"return_to_npc", "talk_to_npc"}:
        if objective.get("is_completed"):
            objective_copy["is_completed"] = True
            return objective_copy

        target_npc_id = objective.get("npc_id")
        objective_copy["is_completed"] = (
            current_npc_id is not None and target_npc_id is not None and int(current_npc_id) == int(target_npc_id)
        )
        return objective_copy

    if objective_type in {"reach_location", "visit_location", "return_to_location"}:
        if objective.get("is_completed"):
            objective_copy["is_completed"] = True
            return objective_copy

        target_location_id = objective.get("location_id")
        target_location_name = _normalize_text(objective.get("location_name"))
        current_location_name = _normalize_text(current_location_name)

        id_matches = (
            current_location_id is not None
            and target_location_id is not None
            and int(current_location_id) == int(target_location_id)
        )
        name_matches = bool(target_location_name and current_location_name and target_location_name == current_location_name)

        if id_matches and target_location_id is not None:
            objective_copy["location_id"] = int(target_location_id)

        objective_copy["is_completed"] = (
            id_matches or name_matches
        )
        return objective_copy

    if objective_type in {"kill_enemy_type", "kill_npc", "defeat_target"}:
        # These need dedicated combat systems or explicit progress updates.
        objective_copy["is_completed"] = bool(objective.get("is_completed", False))
        return objective_copy

    if "required_count" in objective_copy or "current_count" in objective_copy:
        required_count = _objective_required_count(objective_copy)
        current_count = int(objective_copy.get("current_count", 0) or 0)
        objective_copy["required_count"] = required_count
        objective_copy["is_completed"] = current_count >= required_count
        return objective_copy

    objective_copy["is_completed"] = bool(objective.get("is_completed", False))
    return objective_copy


def _all_objectives_completed(objectives):
    """Return whether all structured objectives are completed."""

    return bool(objectives) and all(
        isinstance(entry, dict) and entry.get("is_completed")
        for entry in objectives
    )


def _currency_value_to_copper(currency_payload):
    """Convert a reward currency payload into one comparable copper value."""

    gold = int(currency_payload.get("gold", 0) or 0)
    silver = int(currency_payload.get("silver", 0) or 0)
    copper = int(currency_payload.get("copper", 0) or 0)

    silver_to_copper = int(CURRENCY_CONVERSION_RATES["silver_to_copper"])
    return (gold * GOLD_TO_COPPER) + (silver * silver_to_copper) + copper


def _copper_to_currency_payload(copper_value: int) -> dict:
    """Convert copper integer value to gold/silver/copper payload."""

    copper_value = max(0, int(copper_value or 0))
    silver_to_copper = int(CURRENCY_CONVERSION_RATES["silver_to_copper"])
    gold = copper_value // GOLD_TO_COPPER
    remainder = copper_value % GOLD_TO_COPPER
    silver = remainder // silver_to_copper
    copper = remainder % silver_to_copper
    return {
        "gold": int(gold),
        "silver": int(silver),
        "copper": int(copper),
    }


def _combat_enemy_role(enemy: dict) -> str:
    """Classify one combat enemy into reward role tiers."""

    archetype_id = str(enemy.get("archetype_id", "")).strip().lower()
    category = str(enemy.get("category", "")).strip().lower()

    if category == "humanoid":
        if "general" in archetype_id:
            return "humanoid_general"
        if "captain" in archetype_id:
            return "humanoid_captain"
        if "guard" in archetype_id:
            return "humanoid_guard"
        if any(token in archetype_id for token in ("civilian", "worker", "beggar", "old", "child")):
            return "humanoid_civilian"
        if any(token in archetype_id for token in ("champion", "knight", "veteran", "elite", "hero")):
            return "humanoid_elite"
        return "humanoid_raider"

    if category == "undead":
        return "undead"
    if category == "monster":
        return "monster"
    if category == "animal":
        return "animal"

    return "generic"


def _combat_reward_profile_for_enemy(enemy: dict) -> dict:
    """Return backend reward profile (xp and money value) for one defeated enemy."""

    role = _combat_enemy_role(enemy)
    level = max(1, int(enemy.get("level", 1) or 1))

    profile_by_role = {
        "humanoid_civilian": {"xp_base": 3, "xp_scale": 1.05, "money_base_copper": 4, "money_scale": 1.02},
        "humanoid_raider": {"xp_base": 7, "xp_scale": 1.07, "money_base_copper": 16, "money_scale": 1.04},
        "humanoid_guard": {"xp_base": 14, "xp_scale": 1.08, "money_base_copper": 60, "money_scale": 1.05},
        "humanoid_captain": {"xp_base": 24, "xp_scale": 1.09, "money_base_copper": 130, "money_scale": 1.06},
        "humanoid_general": {"xp_base": 40, "xp_scale": 1.10, "money_base_copper": 360, "money_scale": 1.07},
        "humanoid_elite": {"xp_base": 30, "xp_scale": 1.10, "money_base_copper": 220, "money_scale": 1.07},
        "animal": {"xp_base": 5, "xp_scale": 1.06, "money_base_copper": 0, "money_scale": 1.00},
        "undead": {"xp_base": 12, "xp_scale": 1.08, "money_base_copper": 0, "money_scale": 1.00},
        "monster": {"xp_base": 15, "xp_scale": 1.09, "money_base_copper": 0, "money_scale": 1.00},
        "generic": {"xp_base": 8, "xp_scale": 1.07, "money_base_copper": 8, "money_scale": 1.03},
    }
    selected = profile_by_role.get(role, profile_by_role["generic"])

    xp_value = int(round(float(selected["xp_base"]) + (level ** float(selected["xp_scale"]))))
    money_value_copper = int(round(float(selected["money_base_copper"]) + (level ** float(selected["money_scale"]))))
    if selected["money_base_copper"] <= 0:
        money_value_copper = 0

    return {
        "role": role,
        "level": level,
        "xp": max(0, xp_value),
        "money_copper": max(0, money_value_copper),
    }


def _reward_entry_value(item_entry):
    """Return the monetary reward value of one item or service entry in copper."""

    if not isinstance(item_entry, dict):
        return 0

    payload = item_entry.get("item", item_entry)
    quantity = int(item_entry.get("quantity", payload.get("quantity", 1)) or 1)

    for field_name in ("reward_value", "value_final", "value_base", "value"):
        raw_value = payload.get(field_name)
        if raw_value not in (None, ""):
            try:
                return int(raw_value) * quantity
            except (TypeError, ValueError):
                return 0

    return 0


def _total_reward_value(rewards, reward_items):
    """Return the combined value budget of currency, items, and services."""

    total_value = _currency_value_to_copper(rewards.get("currency", {}))

    if isinstance(reward_items, list):
        for item_entry in reward_items:
            total_value += _reward_entry_value(item_entry)

    services = rewards.get("services", [])
    if isinstance(services, list):
        for service_entry in services:
            total_value += _reward_entry_value(service_entry)

    return total_value


def _validate_rewards_payload(quest):
    """Validate concrete quest rewards against the stored reward rule bounds."""

    rewards = _load_json_payload(quest.rewards_json, {})
    rules = _load_json_payload(quest.reward_rules_json, {})
    validation_errors = []

    xp_amount = int(rewards.get("xp", quest.reward_xp or 0) or 0)
    xp_min = int(rules.get("xp_min", xp_amount) or 0)
    xp_max = int(rules.get("xp_max", xp_amount) or 0)
    if xp_amount < xp_min or xp_amount > xp_max:
        validation_errors.append(f"XP reward {xp_amount} is outside allowed range {xp_min}-{xp_max}.")

    reward_items = rewards.get("items")
    if reward_items is None:
        reward_items = _load_json_payload(quest.reward_items_json, [])

    total_reward_value = _total_reward_value(rewards, reward_items)
    reward_value_min = int(
        rules.get("reward_value_min", rules.get("currency_min_value", total_reward_value)) or 0
    )
    reward_value_max = int(
        rules.get("reward_value_max", rules.get("currency_max_value", total_reward_value)) or 0
    )
    if total_reward_value < reward_value_min or total_reward_value > reward_value_max:
        validation_errors.append(
            f"Reward value {total_reward_value} is outside allowed range {reward_value_min}-{reward_value_max}."
        )

    return validation_errors, rewards, reward_items


def _grant_quest_rewards(character_id: int, rewards: dict, reward_items):
    """Apply validated quest rewards through existing backend services."""

    grant_result = {
        "xp": None,
        "currency": None,
        "items": [],
    }

    xp_amount = int(rewards.get("xp", 0) or 0)
    if xp_amount > 0:
        grant_result["xp"] = add_xp(
            character_id=character_id,
            amount=xp_amount,
            reason="Quest reward",
        ).to_dict()

    currency_payload = rewards.get("currency", {})
    if any(int(currency_payload.get(key, 0) or 0) > 0 for key in ("gold", "silver", "copper")):
        grant_result["currency"] = add_currency(
            character_id=character_id,
            gold=int(currency_payload.get("gold", 0) or 0),
            silver=int(currency_payload.get("silver", 0) or 0),
            copper=int(currency_payload.get("copper", 0) or 0),
        ).__dict__

    if isinstance(reward_items, list):
        for item_entry in reward_items:
            if not isinstance(item_entry, dict):
                continue

            item_payload = item_entry.get("item", item_entry)
            quantity = int(item_entry.get("quantity", item_payload.get("quantity", 1)) or 1)
            item_result = add_inventory_item(
                character_id=character_id,
                item=item_payload,
                quantity=quantity,
            ).to_dict()
            grant_result["items"].append(item_result)

    return grant_result


def _has_claimable_service_rewards(rewards: dict) -> bool:
    """Return whether a reward payload contains deferred service rewards."""

    services = rewards.get("services", [])
    return isinstance(services, list) and any(isinstance(entry, dict) for entry in services)


def _consume_turn_in_items(character_id: int, objectives):
    """Remove delivered proof or hand-in items from inventory after quest turn-in."""

    removal_results = []

    for objective in objectives:
        if not isinstance(objective, dict):
            continue

        objective_type = _normalize_text(objective.get("objective_type"))
        if objective_type != "bring_item":
            continue

        item_identifier = objective.get("item_id") or objective.get("item_name")
        required_count = _objective_required_count(objective)
        if not item_identifier:
            continue

        removal_results.append(
            remove_inventory_item(
                character_id=character_id,
                item_id=str(item_identifier),
                quantity=required_count,
            ).to_dict()
        )

    return removal_results


def create_quest(
    campaign_id: int,
    title: str,
    description: str,
    quest_type: str = "general",
    quest_giver_npc_id: int = None,
    turn_in_npc_id: int = None,
    start_location_id: int = None,
    target_location_id: int = None,
    turn_in_location_id: int = None,
    objectives_json=None,
    rewards_json=None,
    reward_rules_json=None,
    quest_level: int = 1,
    danger_level: str = "moderate",
):
    """Create a structured open quest inside the campaign."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    if not title or not title.strip():
        return {"success": False, "error": "Quest title is required."}

    title = title.strip()
    description = (description or "").strip()
    quest_type = (quest_type or "general").strip().lower()
    objectives_payload = _load_json_payload(objectives_json, [])
    is_valid_objectives, objective_error = _validate_objective_payload(objectives_payload)
    if not is_valid_objectives:
        return {"success": False, "error": objective_error}

    objectives_json = _serialize_json_payload(objectives_payload, [])
    normalized_reward_rules = _normalize_reward_rules(
        reward_rules_json=reward_rules_json,
        quest_type=quest_type,
        quest_level=quest_level,
        danger_level=danger_level,
    )

    rewards_payload = _load_json_payload(rewards_json, {})
    if not isinstance(rewards_payload, dict):
        return {"success": False, "error": "Quest rewards must be a JSON object."}

    rewards_payload = _normalize_rewards_payload(
        rewards_payload,
        reward_rules=normalized_reward_rules,
    )
    rewards_payload = _clamp_rewards_to_rules(rewards_payload, normalized_reward_rules)

    is_valid_services, service_error = _validate_service_payload(rewards_payload.get("services", []))
    if not is_valid_services:
        return {"success": False, "error": service_error}

    rewards_json = _serialize_json_payload(rewards_payload, {})
    reward_rules_json = json.dumps(normalized_reward_rules)

    quest = CampaignQuest(
        campaign_id=campaign.id,
        title=title,
        description=description,
        quest_type=quest_type,
        status="active",
        quest_giver_npc_id=quest_giver_npc_id,
        turn_in_npc_id=turn_in_npc_id,
        start_location_id=start_location_id,
        target_location_id=target_location_id,
        turn_in_location_id=turn_in_location_id,
        objectives_json=objectives_json,
        reward_gold=0,
        reward_xp=0,
        reward_items_json="[]",
        rewards_json=rewards_json,
        reward_rules_json=reward_rules_json,
    )
    db.session.add(quest)
    db.session.commit()

    return {
        "success": True,
        "tool": "create_quest",
        "quest": _serialize_quest_record(quest),
    }


def _get_campaign_quest(campaign: Campaign, quest_id):
    """Return one quest by id, scoped to the current campaign."""

    if quest_id is None or str(quest_id).strip() == "":
        return None, "quest_id is required for this quest tool."

    try:
        normalized_quest_id = int(quest_id)
    except (TypeError, ValueError):
        return None, "quest_id must be an integer."

    quest = db.session.get(CampaignQuest, normalized_quest_id)
    if not quest or quest.campaign_id != campaign.id:
        return None, "Quest not found in campaign."

    return quest, None


def validate_quest_progress(campaign_id: int, quest_id: int, current_location_id: int = None, current_npc_id: int = None):
    """Validate one quest's objectives against current backend state."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    quest, error = _get_campaign_quest(campaign, quest_id)
    if error:
        return {"success": False, "error": error}

    effective_location_id = current_location_id
    if effective_location_id is None and campaign.current_location_id:
        effective_location_id = campaign.current_location_id

    current_location_name = None
    if effective_location_id is not None:
        current_location = db.session.get(CampaignLocation, effective_location_id)
        current_location_name = current_location.name if current_location else None

    objectives = _load_json_payload(quest.objectives_json, [])
    if not isinstance(objectives, list):
        return {"success": False, "error": "Quest objectives are not a list."}

    evaluated_objectives = [
        _evaluate_objective(
            character_id=campaign.character_id,
            objective=objective,
            current_location_id=effective_location_id,
            current_location_name=current_location_name,
            current_npc_id=current_npc_id,
        )
        for objective in objectives
    ]

    quest.objectives_json = json.dumps(evaluated_objectives)
    if _all_objectives_completed(evaluated_objectives):
        quest.status = "completed"
        if not quest.completed_at:
            quest.completed_at = datetime.utcnow()

    db.session.commit()

    return {
        "success": True,
        "tool": "validate_quest_progress",
        "quest": _serialize_quest_record(quest),
    }


def get_quest_details(campaign_id: int, quest_id: int):
    """Return one quest with structured fields."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    quest, error = _get_campaign_quest(campaign, quest_id)
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "tool": "get_quest_details",
        "quest": _serialize_quest_record(quest),
    }


def update_quest_objective_progress(campaign_id: int, quest_id: int, objective_index: int = None, current_count: int = None, is_completed: bool = None, notes: str = None):
    """Update one structured objective entry for a quest."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    quest, error = _get_campaign_quest(campaign, quest_id)
    if error:
        return {"success": False, "error": error}

    objectives = _load_json_payload(quest.objectives_json, [])
    if not isinstance(objectives, list):
        return {"success": False, "error": "Quest objectives are not a list."}

    if objective_index is None or objective_index < 0 or objective_index >= len(objectives):
        return {"success": False, "error": "Objective index is out of range."}

    objective = objectives[objective_index]
    if not isinstance(objective, dict):
        return {"success": False, "error": "Quest objective is not structured correctly."}

    if current_count is not None:
        objective["current_count"] = int(current_count)
        required_count = objective.get("required_count")
        if required_count is not None:
            objective["is_completed"] = int(current_count) >= int(required_count)

    if is_completed is not None:
        objective["is_completed"] = bool(is_completed)

    if notes is not None:
        objective["notes"] = notes

    objectives[objective_index] = objective
    quest.objectives_json = json.dumps(objectives)

    if objectives and all(
        isinstance(entry, dict) and entry.get("is_completed")
        for entry in objectives
    ):
        quest.status = "completed"
        if not quest.completed_at:
            quest.completed_at = datetime.utcnow()

    db.session.commit()

    return {
        "success": True,
        "tool": "update_quest_objective_progress",
        "quest": _serialize_quest_record(quest),
    }


def turn_in_quest(campaign_id: int, quest_id: int, current_location_id: int = None, current_npc_id: int = None):
    """Mark a completed quest as turned in after backend validation succeeds."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    quest, error = _get_campaign_quest(campaign, quest_id)
    if error:
        return {"success": False, "error": error}

    if quest.status == "turned_in" or quest.turned_in_at:
        return {"success": False, "error": "Quest has already been turned in."}

    if quest.status not in {"active", "completed"}:
        return {"success": False, "error": "Quest is not open for turn-in."}

    effective_location_id = current_location_id if current_location_id is not None else campaign.current_location_id
    current_location_name = None
    if effective_location_id is not None:
        current_location = db.session.get(CampaignLocation, effective_location_id)
        current_location_name = current_location.name if current_location else None

    if quest.turn_in_npc_id is not None and current_npc_id is not None and int(current_npc_id) != int(quest.turn_in_npc_id):
        return {"success": False, "error": "Quest must be turned in to a different NPC."}

    if quest.turn_in_npc_id is not None and current_npc_id is None:
        return {"success": False, "error": "Turn-in NPC confirmation is required for this quest."}

    if quest.turn_in_location_id is not None and effective_location_id is not None and int(effective_location_id) != int(quest.turn_in_location_id):
        return {"success": False, "error": "Quest must be turned in at a different location."}

    objectives = _load_json_payload(quest.objectives_json, [])
    if objectives:
        objectives = [
            _evaluate_objective(
                character_id=campaign.character_id,
                objective=objective,
                current_location_id=effective_location_id,
                current_location_name=current_location_name,
                current_npc_id=current_npc_id,
            )
            for objective in objectives
        ]
        quest.objectives_json = json.dumps(objectives)

    if objectives and not _all_objectives_completed(objectives):
        db.session.commit()
        return {
            "success": False,
            "error": "Quest objectives are not fully completed.",
            "quest": _serialize_quest_record(quest),
        }

    validation_errors, rewards, reward_items = _validate_rewards_payload(quest)
    if validation_errors:
        return {
            "success": False,
            "error": "Quest rewards failed validation.",
            "details": {"validation_errors": validation_errors},
        }

    consumed_items = _consume_turn_in_items(
        character_id=campaign.character_id,
        objectives=objectives,
    )

    reward_grants = None
    has_claimable_services = _has_claimable_service_rewards(rewards)

    quest.status = "turned_in"
    if not quest.completed_at:
        quest.completed_at = datetime.utcnow()
    quest.turned_in_at = datetime.utcnow()

    if not has_claimable_services:
        reward_grants = _grant_quest_rewards(
            character_id=campaign.character_id,
            rewards=rewards,
            reward_items=reward_items,
        )
        quest.reward_claimed_at = datetime.utcnow()

    db.session.commit()

    return {
        "success": True,
        "tool": "turn_in_quest",
        "quest": _serialize_quest_record(quest),
        "consumed_items": consumed_items,
        "claimable_rewards": rewards,
        "reward_grants": reward_grants,
        "needs_reward_claim": has_claimable_services,
    }


def claim_quest_rewards(campaign_id: int, quest_id: int):
    """Claim stored rewards for a turned-in quest exactly once."""

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found."}

    quest, error = _get_campaign_quest(campaign, quest_id)
    if error:
        return {"success": False, "error": error}

    if quest.reward_claimed_at:
        return {"success": False, "error": "Quest rewards have already been claimed."}

    if quest.status != "turned_in" or not quest.turned_in_at:
        return {"success": False, "error": "Quest must be turned in before rewards can be claimed."}

    validation_errors, rewards, reward_items = _validate_rewards_payload(quest)
    if validation_errors:
        return {
            "success": False,
            "error": "Quest rewards failed validation.",
            "details": {"validation_errors": validation_errors},
        }

    reward_grants = _grant_quest_rewards(
        character_id=campaign.character_id,
        rewards=rewards,
        reward_items=reward_items,
    )

    quest.reward_claimed_at = datetime.utcnow()
    db.session.commit()

    return {
        "success": True,
        "tool": "claim_quest_rewards",
        "quest": _serialize_quest_record(quest),
        "reward_grants": reward_grants,
    }


STATE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "update_location",
            "description": "Update the character's current location for local movement, rooms, shops, cellars, streets or already validated locations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "The new location name."
                    },
                    "location_type": {
                        "type": "string",
                        "description": "The type of location, for example inn, shop, street, shrine or room."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional short description of the location."
                    },
                    "world_location_id": {
                        "type": "string",
                        "description": "Optional fixed Avalion world location id when moving to a known map location."
                    },
                    "coordinate_x": {
                        "type": "number",
                        "description": "Optional Avalion map X coordinate. Use only when the coordinate is known. The backend stores up to 3 decimal places."
                    },
                    "coordinate_y": {
                        "type": "number",
                        "description": "Optional Avalion map Y coordinate. Use only together with coordinate_x when the coordinate is known. The backend stores up to 3 decimal places."
                    }
                },
                "required": ["location_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_to_coordinates",
            "description": (
                "Move the character across the Avalion map to a known world location or explicit "
                "map coordinates. This validates distance from the current coordinate before changing location."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination_name": {
                        "type": "string",
                        "description": "Destination name shown to the player."
                    },
                    "world_location_id": {
                        "type": "string",
                        "description": "Optional fixed Avalion world location id, preferred for known cities and landmarks."
                    },
                    "coordinate_x": {
                        "type": "number",
                        "description": "Optional destination X coordinate for generated map places. The backend stores up to 3 decimal places."
                    },
                    "coordinate_y": {
                        "type": "number",
                        "description": "Optional destination Y coordinate for generated map places. Required with coordinate_x. The backend stores up to 3 decimal places."
                    },
                    "location_type": {
                        "type": "string",
                        "description": "Destination type, for example road, wilderness, city, camp, pass or ruin."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional short description of the destination."
                    },
                    "travel_mode": {
                        "type": "string",
                        "description": "Travel mode such as walk, ride, cart, ship, airship, flight or teleportation."
                    },
                    "terrain": {
                        "type": "string",
                        "description": "Optional terrain hint for generated routes, such as road, plains, forest, swamp, mountain, waste, canyon, coast, sea, urban or wilderness."
                    },
                    "allow_long_travel": {
                        "type": "boolean",
                        "description": "Set true only when the player explicitly commits to a long overland or special transport journey."
                    }
                },
                "required": ["destination_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "advance_time",
            "description": "Advance in-game time after travel, waiting, conversations or actions that take time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "integer",
                        "description": "How many in-game minutes pass."
                    }
                },
                "required": ["minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spend_time",
            "description": (
                "Spend backend-controlled time for normal non-travel actions such as quick search, "
                "thorough search, meal, shopping, chore, lesson, self-training, crafting, combat or waiting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": (
                            "One of: conversation, short_exchange, local_move, quick_look, quick_search, "
                            "look_around, thorough_search, drink, meal, inn_meal, shopping, trade, chore, "
                            "paid_work, lesson, teacher_training, self_training, crafting_quick, repair_quick, "
                            "crafting, repair, combat, wait."
                        )
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Optional requested minutes. Backend clamps this to the allowed range for the action type."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional short description of what consumed time."
                    }
                },
                "required": ["action_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rest",
            "description": "Spend time resting or sleeping. This currently advances time only; resource recovery is a later feature.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rest_type": {
                        "type": "string",
                        "description": "Rest type: short, short_rest, long, long_rest, or sleep_until_morning."
                    }
                },
                "required": ["rest_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_check",
            "description": (
                "Resolve a backend-owned attribute/skill check and return success chance, roll outcome, "
                "and degree of success. Use this when the action outcome should not be decided by narration alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_text": {
                        "type": "string",
                        "description": "Short description of the attempted action."
                    },
                    "action_type": {
                        "type": "string",
                        "description": "Context tag such as lockpicking, social, survival, combat_action, crafting or general."
                    },
                    "challenge_level": {
                        "type": "integer",
                        "description": "Difficulty level from 1 to 100."
                    },
                    "challenge_type": {
                        "type": "string",
                        "description": "Difficulty tier: trivial, easy, normal, hard, expert, master, legendary."
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "Optional known skill name such as Lockpicking, Persuasion or Arcane Lore."
                    },
                    "primary_attribute": {
                        "type": "string",
                        "description": "Optional primary attribute override: strength, dexterity, constitution, intelligence, perception or charisma."
                    },
                    "secondary_attributes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional secondary attributes list. Only small weighting is applied."
                    },
                    "include_character_level": {
                        "type": "boolean",
                        "description": "Whether a small character-level contribution is included in the check."
                    }
                },
                "required": ["action_text", "challenge_level"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_combat",
            "description": "Start backend combat state with initiative, turn order, and one or more enemies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "enemies_json": {
                        "type": "string",
                        "description": "Optional JSON array of enemy entries with fields like name, hp, attack_score, dodge_score, block_score, damage_min, damage_max.",
                    }
                },
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_combat_state",
            "description": "Return active combat state including current actor, alive enemies, and last combat event.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grant_combat_loot",
            "description": "Grant backend-validated loot from defeated enemies exactly once (currency, equipment, quest items).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_attack",
            "description": "Resolve one combat attack turn and return exact backend outcome including damage and defeat flags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attacker_side": {
                        "type": "string",
                        "description": "Optional attacker side: player or enemies. Must match current turn if provided."
                    },
                    "target_enemy_id": {
                        "type": "string",
                        "description": "Optional enemy combat_id target when player attacks. Defaults to first alive enemy."
                    }
                },
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attempt_escape",
            "description": "Attempt to flee an active combat encounter. Backend decides success or failure.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attempt_surrender",
            "description": "Attempt to surrender in active combat. Works only if current enemies allow surrender.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attempt_ceasefire",
            "description": "Attempt to stop combat by mutual de-escalation (duel stop, mercy pause, stand down).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attempt_spare",
            "description": "Attempt to spare a weakened enemy during the player's turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_enemy_id": {
                        "type": "string",
                        "description": "Optional enemy combat_id to spare. Defaults to first alive enemy."
                    }
                },
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_quest",
            "description": "Create a structured quest in the current campaign.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The quest title."},
                    "description": {"type": "string", "description": "The quest description."},
                    "quest_type": {
                        "type": "string",
                        "description": "Quest type such as gathering, hunt, travel, delivery, tutorial or general."
                    },
                    "quest_giver_npc_id": {"type": "integer", "description": "Optional campaign NPC id of the quest giver. Use only known ids."},
                    "turn_in_npc_id": {"type": "integer", "description": "Optional campaign NPC id where the quest should be turned in. Use only known ids."},
                    "start_location_id": {"type": "integer", "description": "Optional campaign location id where the quest begins. Use only known ids."},
                    "target_location_id": {"type": "integer", "description": "Optional campaign location id where the main objective happens. Use only known ids."},
                    "turn_in_location_id": {"type": "integer", "description": "Optional campaign location id where the quest is turned in. Use only known ids."},
                    "objectives_json": {"type": "string", "description": "Structured quest objectives as a JSON string."},
                    "rewards_json": {"type": "string", "description": "Structured concrete rewards for this quest as a JSON string."},
                    "reward_rules_json": {"type": "string", "description": "Optional negotiation hints as a JSON string. Backend normalizes final reward rule ranges."},
                    "quest_level": {
                        "type": "integer",
                        "description": "Suggested quest level used to derive reward rule ranges."
                    },
                    "danger_level": {
                        "type": "string",
                        "description": "Quest danger such as safe, low, moderate, high or deadly."
                    },
                },
                "required": ["title", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_quest_progress",
            "description": "Validate one quest's objectives against backend state such as inventory, location and NPC interaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {
                        "type": "integer",
                        "description": "Required quest id from Visible Quests."
                    },
                    "current_location_id": {
                        "type": "integer",
                        "description": "Optional current campaign location id if the quest progress depends on being at a specific place."
                    },
                    "current_npc_id": {
                        "type": "integer",
                        "description": "Optional current campaign NPC id if the quest progress depends on speaking to or turning in at an NPC."
                    }
                },
                "required": ["quest_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_quest_details",
            "description": "Inspect one quest including objectives, reward structure and turn-in targets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {
                        "type": "integer",
                        "description": "Required quest id from Visible Quests."
                    }
                },
                "required": ["quest_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_quest_objective_progress",
            "description": "Update the progress of a structured quest objective when the player fulfills part of it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {"type": "integer", "description": "Required quest id from Visible Quests."},
                    "objective_index": {"type": "integer", "description": "Zero-based index of the objective to update."},
                    "current_count": {"type": "integer", "description": "Updated current count toward completion."},
                    "is_completed": {"type": "boolean", "description": "Explicitly mark the objective completed or not."},
                    "notes": {"type": "string", "description": "Optional notes about how the objective progressed."},
                },
                "required": ["quest_id", "objective_index"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "claim_quest_rewards",
            "description": "Claim stored rewards from a quest that has already been turned in.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {
                        "type": "integer",
                        "description": "Required quest id from Visible Quests."
                    }
                },
                "required": ["quest_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_in_quest",
            "description": "Turn in a quest after all objectives are complete and the hand-in condition has been met.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {
                        "type": "integer",
                        "description": "Required quest id from Visible Quests."
                    },
                    "current_location_id": {
                        "type": "integer",
                        "description": "Optional current campaign location id used to validate the turn-in location."
                    },
                    "current_npc_id": {
                        "type": "integer",
                        "description": "Optional current campaign NPC id used to validate the quest giver or turn-in NPC."
                    }
                },
                "required": ["quest_id"]
            }
        }
    }
]


def execute_state_tool(campaign_id: int, tool_name: str, arguments: dict):
    """Dispatch one adventure state tool call."""

    arguments = arguments or {}

    if tool_name == "update_location":
        return update_location(
            campaign_id=campaign_id,
            location_name=arguments.get("location_name", ""),
            location_type=arguments.get("location_type"),
            description=arguments.get("description"),
            coordinate_x=arguments.get("coordinate_x"),
            coordinate_y=arguments.get("coordinate_y"),
            world_location_id=arguments.get("world_location_id"),
        )

    if tool_name == "move_to_coordinates":
        return move_to_coordinates(
            campaign_id=campaign_id,
            destination_name=arguments.get("destination_name", ""),
            coordinate_x=arguments.get("coordinate_x"),
            coordinate_y=arguments.get("coordinate_y"),
            world_location_id=arguments.get("world_location_id"),
            location_type=arguments.get("location_type"),
            description=arguments.get("description"),
            travel_mode=arguments.get("travel_mode", "walk"),
            terrain=arguments.get("terrain"),
            allow_long_travel=arguments.get("allow_long_travel", False),
        )

    if tool_name == "advance_time":
        return advance_time(
            campaign_id=campaign_id,
            minutes=arguments.get("minutes", 0)
        )

    if tool_name == "spend_time":
        return spend_time(
            campaign_id=campaign_id,
            action_type=arguments.get("action_type", ""),
            minutes=arguments.get("minutes"),
            description=arguments.get("description"),
        )

    if tool_name == "rest":
        return rest(
            campaign_id=campaign_id,
            rest_type=arguments.get("rest_type", "short"),
        )

    if tool_name == "perform_check":
        return perform_check(
            campaign_id=campaign_id,
            action_text=arguments.get("action_text", ""),
            action_type=arguments.get("action_type", "general"),
            challenge_level=arguments.get("challenge_level", 1),
            challenge_type=arguments.get("challenge_type", "normal"),
            skill_name=arguments.get("skill_name"),
            primary_attribute=arguments.get("primary_attribute"),
            secondary_attributes=arguments.get("secondary_attributes"),
            include_character_level=arguments.get("include_character_level", True),
        )

    if tool_name == "start_combat":
        return start_combat(
            campaign_id=campaign_id,
            enemies_json=arguments.get("enemies_json"),
        )

    if tool_name == "get_combat_state":
        return get_combat_state(campaign_id=campaign_id)

    if tool_name == "grant_combat_loot":
        return grant_combat_loot(campaign_id=campaign_id)

    if tool_name == "resolve_attack":
        return resolve_attack(
            campaign_id=campaign_id,
            attacker_side=arguments.get("attacker_side"),
            target_enemy_id=arguments.get("target_enemy_id"),
        )

    if tool_name == "attempt_escape":
        return attempt_escape(campaign_id=campaign_id)

    if tool_name == "attempt_surrender":
        return attempt_surrender(campaign_id=campaign_id)

    if tool_name == "attempt_ceasefire":
        return attempt_ceasefire(campaign_id=campaign_id)

    if tool_name == "attempt_spare":
        return attempt_spare(
            campaign_id=campaign_id,
            target_enemy_id=arguments.get("target_enemy_id"),
        )

    if tool_name == "create_quest":
        return create_quest(
            campaign_id=campaign_id,
            title=arguments.get("title", ""),
            description=arguments.get("description", ""),
            quest_type=arguments.get("quest_type", "general"),
            quest_giver_npc_id=arguments.get("quest_giver_npc_id"),
            turn_in_npc_id=arguments.get("turn_in_npc_id"),
            start_location_id=arguments.get("start_location_id"),
            target_location_id=arguments.get("target_location_id"),
            turn_in_location_id=arguments.get("turn_in_location_id"),
            objectives_json=arguments.get("objectives_json"),
            rewards_json=arguments.get("rewards_json"),
            reward_rules_json=arguments.get("reward_rules_json"),
            quest_level=arguments.get("quest_level", 1),
            danger_level=arguments.get("danger_level", "moderate"),
        )

    if tool_name == "get_quest_details":
        return get_quest_details(
            campaign_id=campaign_id,
            quest_id=arguments.get("quest_id"),
        )

    if tool_name == "validate_quest_progress":
        return validate_quest_progress(
            campaign_id=campaign_id,
            quest_id=arguments.get("quest_id"),
            current_location_id=arguments.get("current_location_id"),
            current_npc_id=arguments.get("current_npc_id"),
        )

    if tool_name == "update_quest_objective_progress":
        return update_quest_objective_progress(
            campaign_id=campaign_id,
            quest_id=arguments.get("quest_id"),
            objective_index=arguments.get("objective_index"),
            current_count=arguments.get("current_count"),
            is_completed=arguments.get("is_completed"),
            notes=arguments.get("notes"),
        )

    if tool_name == "turn_in_quest":
        return turn_in_quest(
            campaign_id=campaign_id,
            quest_id=arguments.get("quest_id"),
            current_location_id=arguments.get("current_location_id"),
            current_npc_id=arguments.get("current_npc_id"),
        )

    if tool_name == "claim_quest_rewards":
        return claim_quest_rewards(
            campaign_id=campaign_id,
            quest_id=arguments.get("quest_id"),
        )

    return {
        "success": False,
        "error": f"Unknown tool: {tool_name}"
    }
