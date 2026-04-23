"""Character serializers for templates, prompts, and API responses.

The serializer is the bridge between SQLAlchemy models, JSON-backed inventory
state, and frontend-friendly dictionaries. It should collect existing backend
state, not invent gameplay state.
"""

from services.attributes import serialize_attributes
from services.equipment import serialize_equipment
from services.inventory.service import get_inventory
from services.leveling import serialize_level_progression
from services.skills import serialize_character_skills
from services.status_effects import serialize_status_effects

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


def serialize_character(
    character,
    get_active_campaign_for_character,
    get_current_campaign_location,
    get_active_campaign_quest,
):
    """Serialize the complete active character state used by the game UI."""

    attributes = character.attributes
    resources = character.resources
    campaign = get_active_campaign_for_character(character.id)
    current_location = get_current_campaign_location(campaign)
    active_quest = get_active_campaign_quest(campaign)
    inventory_data = get_character_inventory_data(character.id)
    status_effects = get_character_status_effects(character.id)
    level_progression = serialize_level_progression(character)

    hp_current = resources.hp_current if resources else 0
    hp_max = resources.hp_max if resources else 0
    mana_current = resources.mana_current if resources else 0
    mana_max = resources.mana_max if resources else 0
    energy_current = resources.energy_current if resources else 0
    energy_max = resources.energy_max if resources else 0

    serialized_attributes = serialize_attributes(attributes)
    serialized_skills = serialize_character_skills(character)
    carry_load = _build_carry_load(serialized_attributes, inventory_data)
    attribute_summary = ", ".join(
        f"{attribute['label']} {attribute['level']}"
        for attribute in serialized_attributes
    ) if serialized_attributes else "None"

    return {
        "id": character.id,
        "name": character.name,
        "race": character.race,
        "class_name": character.class_name,
        "level": character.level,
        "xp": character.xp,
        "level_progression": level_progression,
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
        },
        "attributes": serialized_attributes,
        "attribute_summary": attribute_summary,
        "skills": serialized_skills,
        "skill_summary": ", ".join(
            f"{skill['name']} {skill['level']}"
            for skill in serialized_skills[:12]
        ) if serialized_skills else "None",
        "current_state": {
            "location": current_location.name if current_location else "Unknown",
            "time_of_day": campaign.current_ingame_time if campaign else "Unknown",
            "active_quest": active_quest.title if active_quest else "No active quest",
            "active_quest_description": active_quest.description if active_quest else "",
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
