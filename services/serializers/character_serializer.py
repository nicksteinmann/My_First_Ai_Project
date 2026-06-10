"""Character serializers for templates, prompts, and API responses.

The serializer is the bridge between SQLAlchemy models, JSON-backed inventory
state, and frontend-friendly dictionaries. It should collect existing backend
state, not invent gameplay state.
"""

import json

from models import CampaignLocation
from services.attributes import serialize_attributes
from services.equipment import build_item_bonus_lines, build_item_tooltip, get_defense_profile, get_effective_stats, serialize_equipment
from services.inventory.service import get_inventory
from services.leveling import serialize_level_progression, serialize_level_renown
from services.merchants import serialize_location_merchants
from services.status_effects import serialize_status_effects
from services.skills import serialize_character_skills
from services.timekeeping import calendar_date_for_day
from services.trainers import serialize_location_trainers
from services.world_data import get_coordinate_system, normalize_coordinate

SIZE_ABBREVIATIONS = {
    "tiny": "XS",
    "small": "S",
    "medium": "M",
    "large": "L",
    "gigantic": "XXL",
}

CARRY_CAPACITY_BASE = 15.0
CARRY_CAPACITY_PER_STRENGTH_LEVEL = 2.0


def _round_inventory_value(value):
    """Round inventory measurements for compact UI display."""

    return round(float(value), 2)


def _format_inventory_value(value):
    """Format inventory measurements with one stable decimal place."""

    return f"{float(value):.1f}"


def _format_size_label(value):
    """Return a UI-friendly size label while keeping backend values unchanged."""

    return str(value or "small").strip().title()


def _format_size_abbreviation(value):
    """Return compact size labels for dense inventory rows."""

    normalized = str(value or "small").strip().lower()
    return SIZE_ABBREVIATIONS.get(normalized, normalized.upper())


def _build_item_label(item):
    """Return a compact item name with quantity when needed."""

    quantity = int(item.get("quantity", 1))
    name = item.get("name", "Unknown Item")
    return f"{name} x{quantity}" if quantity > 1 else name


def _get_equipped_weight(inventory_blob):
    """Return unique equipped item weight without double-counting shared slots."""

    slots = inventory_blob.get("equipment", {}).get("slots", {})
    seen_item_ids = set()
    total_weight = 0.0

    for item in slots.values():
        if not isinstance(item, dict):
            continue

        item_id = item.get("item_id")
        unique_key = item_id or id(item)
        if unique_key in seen_item_ids:
            continue

        seen_item_ids.add(unique_key)
        quantity = int(item.get("quantity", 1) or 1)
        total_weight += float(item.get("weight", 0) or 0) * quantity

    return total_weight


def _build_carry_load(serialized_attributes, inventory_data):
    """Calculate current load and comfortable carry capacity."""

    strength = next(
        (
            attribute
            for attribute in serialized_attributes
            if attribute.get("key") == "strength"
        ),
        None,
    )
    strength_level = int(strength.get("level", 0) or 0) if strength else 0
    capacity = CARRY_CAPACITY_BASE + (strength_level * CARRY_CAPACITY_PER_STRENGTH_LEVEL)
    current_weight = float(inventory_data.get("total_weight", 0) or 0)

    return {
        "current": _round_inventory_value(current_weight),
        "current_display": _format_inventory_value(current_weight),
        "capacity": _round_inventory_value(capacity),
        "capacity_display": _format_inventory_value(capacity),
        "is_over_capacity": current_weight > capacity,
    }


def get_character_inventory_data(character_id):
    """Serialize containers, equipment slots, and inventory summaries."""

    if not character_id:
        return {
            "containers": [],
            "equipment": [],
            "equipment_slots": [],
            "equipment_summary": "None",
            "inventory": [],
            "inventory_summary": "Leer",
            "total_weight": 0.0,
            "total_weight_display": _format_inventory_value(0),
            "equipment_weight": 0.0,
            "equipment_weight_display": _format_inventory_value(0),
        }

    inventory_blob = get_inventory(character_id)
    equipment_data = serialize_equipment(character_id)
    raw_containers = inventory_blob.get("inventory", {}).get("containers", [])

    serialized_containers = []
    flat_inventory_items = []
    inventory_content_weight = 0.0

    for container in raw_containers:
        serialized_items = []
        used_volume = 0.0
        container_weight = 0.0
        container_source = container.get("source", "base")
        is_carried_container = container_source in ("equipment", "hands")

        if container_source == "nearby":
            continue

        if container_source in ("base", "hands") and not container.get("items"):
            continue

        for item in container.get("items", []):
            quantity = int(item.get("quantity", 1))
            item_volume = float(item.get("volume", 0))
            item_weight = float(item.get("weight", 0))

            total_item_volume = item_volume * quantity
            total_item_weight = item_weight * quantity

            used_volume += total_item_volume
            container_weight += total_item_weight
            if is_carried_container:
                inventory_content_weight += total_item_weight

            serialized_item = {
                "item_id": item.get("item_id"),
                "name": item.get("name", "Unknown Item"),
                "description": item.get("description", ""),
                "bonus_lines": build_item_bonus_lines(item),
                "tooltip": build_item_tooltip(item),
                "size": item.get("size", "small"),
                "size_display": _format_size_label(item.get("size", "small")),
                "size_abbreviation": _format_size_abbreviation(item.get("size", "small")),
                "volume": _round_inventory_value(item_volume),
                "volume_display": _format_inventory_value(item_volume),
                "weight": _round_inventory_value(item_weight),
                "weight_display": _format_inventory_value(item_weight),
                "quantity": quantity,
                "stackable": bool(item.get("stackable", False)),
                "hand_usage": item.get("hand_usage", "none"),
                "item_type": item.get("item_type"),
                "display_name": _build_item_label(item),
                "total_volume": _round_inventory_value(total_item_volume),
                "total_volume_display": _format_inventory_value(total_item_volume),
                "total_weight": _round_inventory_value(total_item_weight),
                "total_weight_display": _format_inventory_value(total_item_weight),
            }
            serialized_items.append(serialized_item)
            flat_inventory_items.append(serialized_item["display_name"])

        max_volume = float(container.get("max_volume", 0))

        serialized_containers.append({
            "container_id": container.get("container_id"),
            "name": container.get("name", "Unnamed Container"),
            "source": container_source,
            "source_item_id": container.get("source_item_id"),
            "is_carried": is_carried_container,
            "max_volume": _round_inventory_value(max_volume),
            "max_volume_display": _format_inventory_value(max_volume),
            "used_volume": _round_inventory_value(used_volume),
            "used_volume_display": _format_inventory_value(used_volume),
            "available_volume": _round_inventory_value(max_volume - used_volume),
            "max_item_size": container.get("max_item_size", "small"),
            "max_item_size_display": _format_size_label(container.get("max_item_size", "small")),
            "max_item_size_abbreviation": _format_size_abbreviation(container.get("max_item_size", "small")),
            "total_weight": _round_inventory_value(container_weight),
            "total_weight_display": _format_inventory_value(container_weight),
            "items": serialized_items,
        })

    equipment_weight = _get_equipped_weight(inventory_blob)
    total_weight = inventory_content_weight + equipment_weight

    return {
        "containers": serialized_containers,
        "equipment": equipment_data["labels"],
        "equipment_slots": equipment_data["slots"],
        "equipment_by_slot": {
            slot["slot"]: slot
            for slot in equipment_data["slots"]
        },
        "equipment_summary": equipment_data["summary"],
        "inventory": flat_inventory_items,
        "inventory_summary": ", ".join(flat_inventory_items) if flat_inventory_items else "Leer",
        "equipment_weight": _round_inventory_value(equipment_weight),
        "equipment_weight_display": _format_inventory_value(equipment_weight),
        "total_weight": _round_inventory_value(total_weight),
        "total_weight_display": _format_inventory_value(total_weight),
    }


def get_character_status_effects(character_id):
    """Return active status effects or an empty list for missing characters."""

    if not character_id:
        return []
    return serialize_status_effects(character_id)


def _parse_quest_json(value, fallback):
    """Parse stored quest JSON safely for serializer output."""

    if not value:
        return fallback

    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _format_quest_progress_line(objective):
    """Return a compact progress line for one quest objective."""

    objective_type = str(objective.get("objective_type", "")).strip().lower()
    label = objective.get("label")
    if label:
        return str(label)

    if objective_type in {"collect_item", "bring_item"}:
        current_count = int(objective.get("current_count", 0) or 0)
        required_count = int(objective.get("required_count", 0) or 0)
        item_name = objective.get("item_name") or objective.get("item_id") or "Item"
        return f"{current_count} / {required_count} {item_name}"

    if objective_type in {"talk_to_npc", "return_to_npc"}:
        npc_id = objective.get("npc_id")
        return f"Talk to NPC #{npc_id}"

    if objective_type in {"reach_location", "visit_location", "return_to_location"}:
        location_id = objective.get("location_id")
        location_name = objective.get("location_name")
        if location_id is not None:
            return f"Reach location #{location_id}"
        return f"Reach {location_name or 'location'}"

    if objective_type == "kill_enemy_type":
        current_count = int(objective.get("current_count", 0) or 0)
        required_count = int(objective.get("required_count", 0) or 0)
        enemy_type = objective.get("enemy_type") or "target"
        return f"{current_count} / {required_count} defeat {enemy_type}"

    if objective_type == "kill_npc":
        npc_id = objective.get("npc_id")
        return f"Defeat NPC #{npc_id}"

    return objective_type.replace("_", " ").title() if objective_type else "Objective"


def _build_quest_tooltip(quest, objectives, rewards):
    """Build one hover tooltip text for a visible quest."""

    if not quest:
        return "No quest"

    lines = [quest.description or quest.title]

    if quest.target_location_id:
        lines.append(f"Target location #{quest.target_location_id}")

    if objectives:
        lines.append("")
        lines.append("Objectives:")
        for objective in objectives:
            progress_line = _format_quest_progress_line(objective)
            completed_marker = "done" if objective.get("is_completed") else "open"
            lines.append(f"- {progress_line} [{completed_marker}]")

    currency = rewards.get("currency", {}) if isinstance(rewards, dict) else {}
    items = rewards.get("items", []) if isinstance(rewards, dict) else []
    services = rewards.get("services", []) if isinstance(rewards, dict) else []
    reward_bits = []

    xp_value = int(rewards.get("xp", 0) or 0) if isinstance(rewards, dict) else 0
    if xp_value > 0:
        reward_bits.append(f"{xp_value} XP")

    if any(int(currency.get(key, 0) or 0) > 0 for key in ("gold", "silver", "copper")):
        reward_bits.append(
            f"{int(currency.get('gold', 0) or 0)}g / "
            f"{int(currency.get('silver', 0) or 0)}s / "
            f"{int(currency.get('copper', 0) or 0)}c"
        )

    if items:
        reward_bits.append(f"{len(items)} item reward(s)")

    if services:
        reward_bits.append(f"{len(services)} service reward(s)")

    if reward_bits:
        lines.append("")
        lines.append("Rewards:")
        for bit in reward_bits:
            lines.append(f"- {bit}")

    if quest.turn_in_npc_id:
        lines.append("")
        lines.append(f"Turn in at NPC #{quest.turn_in_npc_id}")
    if quest.turn_in_location_id:
        lines.append(f"Turn in at location #{quest.turn_in_location_id}")

    return "\n".join(lines)


def _serialize_location_reference(location_id):
    """Return location details for quest context without duplicating quest truth."""

    if location_id is None:
        return None

    location = CampaignLocation.query.get(location_id)
    if not location:
        return None

    return {
        "id": location.id,
        "name": location.name,
        "location_type": location.location_type,
        "coordinate_x": normalize_coordinate(location.coordinate_x) if location.coordinate_x is not None else None,
        "coordinate_y": normalize_coordinate(location.coordinate_y) if location.coordinate_y is not None else None,
        "region_id": location.region_id,
        "region_name": location.region_name,
        "subregion": location.subregion,
        "world_location_id": location.world_location_id,
        "world_location_name": location.world_location_name,
    }


def _quest_display_status(quest):
    """Return the player-facing quest label for one visible quest."""

    if quest.status == "turned_in" and not quest.reward_claimed_at:
        return "Completed - Collect Reward"

    if quest.status == "completed":
        return "Completed - Turn In"

    return quest.title


def _serialize_visible_quests(campaign):
    """Return all quests that should still be shown in the UI."""

    if not campaign:
        return []

    visible_statuses = {"active", "completed", "turned_in"}
    sort_order = {"active": 0, "completed": 1, "turned_in": 2}
    visible_quests = []

    for quest in campaign.quests:
        if quest.status not in visible_statuses:
            continue
        if quest.reward_claimed_at:
            continue

        objectives = _parse_quest_json(quest.objectives_json, [])
        rewards = _parse_quest_json(quest.rewards_json, {})

        visible_quests.append({
            "id": quest.id,
            "title": quest.title,
            "display": _quest_display_status(quest),
            "description": quest.description or "",
            "status": quest.status,
            "quest_type": quest.quest_type,
            "objectives": objectives,
            "rewards": rewards,
            "quest_giver_npc_id": quest.quest_giver_npc_id,
            "turn_in_npc_id": quest.turn_in_npc_id,
            "start_location_id": quest.start_location_id,
            "turn_in_location_id": quest.turn_in_location_id,
            "target_location_id": quest.target_location_id,
            "location_refs": {
                "start": _serialize_location_reference(quest.start_location_id),
                "target": _serialize_location_reference(quest.target_location_id),
                "turn_in": _serialize_location_reference(quest.turn_in_location_id),
            },
            "reward_claimed_at": quest.reward_claimed_at.isoformat() if quest.reward_claimed_at else None,
            "tooltip": _build_quest_tooltip(quest, objectives, rewards),
            "sort_order": sort_order.get(quest.status, 99),
            "started_at": quest.started_at.isoformat() if quest.started_at else "",
        })

    visible_quests.sort(key=lambda quest: (quest["sort_order"], quest["started_at"], quest["id"]))
    return visible_quests


def get_visible_campaign_quest_summary(campaign):
    """Return a compact summary for pages that only have one quest text slot."""

    visible_quests = _serialize_visible_quests(campaign)
    if not visible_quests:
        return "No quests"

    if len(visible_quests) == 1:
        return visible_quests[0]["display"]

    return f"{len(visible_quests)} quests"


def _serialize_current_location_context(current_location):
    """Return map coordinates and region context for the active location."""

    coordinate_system = get_coordinate_system()

    return {
        "coordinate_x": (
            normalize_coordinate(current_location.coordinate_x)
            if current_location and current_location.coordinate_x is not None
            else None
        ),
        "coordinate_y": (
            normalize_coordinate(current_location.coordinate_y)
            if current_location and current_location.coordinate_y is not None
            else None
        ),
        "coordinate_source": current_location.coordinate_source if current_location else None,
        "region_id": current_location.region_id if current_location else None,
        "region_name": current_location.region_name if current_location else None,
        "subregion": current_location.subregion if current_location else None,
        "world_location_id": current_location.world_location_id if current_location else None,
        "world_location_name": current_location.world_location_name if current_location else None,
        "scale_km_per_unit": coordinate_system.get("scale_km_per_unit"),
    }


def _apply_effective_attribute_overlay(serialized_attributes, effective_stats):
    """Overlay equipment-driven effective values onto serialized attribute rows."""

    effective_attributes = (effective_stats or {}).get("attributes", {}) if isinstance(effective_stats, dict) else {}
    overlaid = []
    for attribute in serialized_attributes:
        key = attribute.get("key")
        payload = effective_attributes.get(key) or {}
        updated = dict(attribute)
        updated["base_level"] = int(attribute.get("level", 0) or 0)
        updated["equipment_bonus"] = int(payload.get("equipment_bonus", 0) or 0)
        updated["effective_level"] = int(payload.get("effective", updated["base_level"]) or updated["base_level"])
        updated["level"] = updated["effective_level"]
        overlaid.append(updated)
    return overlaid


def serialize_character(
    character,
    get_active_campaign_for_character,
    get_current_campaign_location,
):
    """Serialize the complete active character state used by the game UI."""

    attributes = character.attributes
    resources = character.resources
    campaign = get_active_campaign_for_character(character.id)
    current_location = get_current_campaign_location(campaign)
    visible_quests = _serialize_visible_quests(campaign)
    inventory_data = get_character_inventory_data(character.id)
    status_effects = get_character_status_effects(character.id)
    level_progression = serialize_level_progression(character)
    level_renown = serialize_level_renown(character)
    effective_stats = get_effective_stats(character.id)
    defense_profile = get_defense_profile(character.id)
    nearby_merchants = (
        serialize_location_merchants(campaign.id, current_location.id)
        if campaign and current_location
        else []
    )
    nearby_trainers = (
        serialize_location_trainers(campaign.id, current_location.id)
        if campaign and current_location
        else []
    )

    hp_current = resources.hp_current if resources else 0
    hp_max = resources.hp_max if resources else 0
    mana_current = resources.mana_current if resources else 0
    mana_max = resources.mana_max if resources else 0
    energy_current = resources.energy_current if resources else 0
    energy_max = resources.energy_max if resources else 0

    serialized_attributes = serialize_attributes(attributes)
    if effective_stats.get("success"):
        serialized_attributes = _apply_effective_attribute_overlay(serialized_attributes, effective_stats)
    serialized_skills = serialize_character_skills(character)
    carry_load = _build_carry_load(serialized_attributes, inventory_data)
    attribute_summary = ", ".join(
        f"{attribute['label']} {attribute['level']}"
        for attribute in serialized_attributes
    ) if serialized_attributes else "None"

    location_context = _serialize_current_location_context(current_location)
    calendar_date = calendar_date_for_day(campaign.current_ingame_day) if campaign else None

    return {
        "id": character.id,
        "name": character.name,
        "race": character.race,
        "class_name": character.class_name,
        "level": character.level,
        "xp": character.xp,
        "level_progression": level_progression,
        "level_renown": level_renown,
        "renown_label": level_renown["label"],
        "renown_summary": level_renown["prompt_hint"],
        "status": character.status,
        "status_effects": status_effects,
        "status_effect_summary": ", ".join(effect["name"] for effect in status_effects) if status_effects else "None",
        "currency": character.currency_json,
        "portrait": "👤",
        "stats": {
            "hp": hp_current,
            "hp_max": hp_max,
            "mana": mana_current,
            "mana_max": mana_max,
            "energy": energy_current,
            "energy_max": energy_max,
            "currency": character.currency_json,
            "armor_rating": (
                defense_profile.get("armor", {}).get("armor_rating_total", 0)
                if defense_profile.get("success")
                else 0
            ),
        },
        "attributes": serialized_attributes,
        "attribute_summary": attribute_summary,
        "effective_stats": effective_stats if effective_stats.get("success") else None,
        "combat_overview": {
            "armor_rating": defense_profile.get("armor", {}).get("armor_rating_total", 0) if defense_profile.get("success") else 0,
            "dodge_score": defense_profile.get("scores", {}).get("dodge_score", 0) if defense_profile.get("success") else 0,
            "block_score": defense_profile.get("scores", {}).get("block_score", 0) if defense_profile.get("success") else 0,
        },
        "skills": serialized_skills,
        "skill_summary": ", ".join(
            f"{skill['name']} {skill['level']}"
            for skill in serialized_skills[:12]
        ) if serialized_skills else "None",
        "current_state": {
            "location": current_location.name if current_location else "Unknown",
            "current_location_id": current_location.id if current_location else None,
            "location_context": location_context,
            "region_id": location_context["region_id"],
            "region_name": location_context["region_name"],
            "subregion": location_context["subregion"],
            "coordinate_x": location_context["coordinate_x"],
            "coordinate_y": location_context["coordinate_y"],
            "ingame_day": campaign.current_ingame_day if campaign else None,
            "calendar": calendar_date,
            "day_label": calendar_date["date_label"] if calendar_date else "Unknown Day",
            "time_of_day": campaign.current_ingame_time if campaign else "Unknown",
            "quest_summary": get_visible_campaign_quest_summary(campaign),
            "visible_quests": visible_quests,
            "nearby_merchants": nearby_merchants,
            "nearby_trainers": nearby_trainers,
        },
        "equipment": inventory_data["equipment"],
        "equipment_slots": inventory_data["equipment_slots"],
        "equipment_by_slot": inventory_data["equipment_by_slot"],
        "equipment_summary": inventory_data["equipment_summary"],
        "inventory": inventory_data["inventory"],
        "inventory_summary": inventory_data["inventory_summary"],
        "inventory_total_weight": inventory_data["total_weight"],
        "carry_load": carry_load,
        "inventory_containers": inventory_data["containers"],
    }
