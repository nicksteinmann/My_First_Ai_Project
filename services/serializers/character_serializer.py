from services.attributes import serialize_attributes
from services.equipment import serialize_equipment
from services.inventory.service import get_inventory
from services.leveling import serialize_level_progression
from services.skills import serialize_character_skills
from services.status_effects import serialize_status_effects


def _round_inventory_value(value):
    return round(float(value), 2)


def _build_item_label(item):
    quantity = int(item.get("quantity", 1))
    name = item.get("name", "Unknown Item")
    return f"{name} x{quantity}" if quantity > 1 else name


def get_character_inventory_data(character_id):
    if not character_id:
        return {
            "containers": [],
            "equipment": [],
            "equipment_slots": [],
            "equipment_summary": "None",
            "inventory": [],
            "inventory_summary": "Leer",
            "total_weight": 0.0,
        }

    inventory_blob = get_inventory(character_id)
    equipment_data = serialize_equipment(character_id)
    raw_containers = inventory_blob.get("inventory", {}).get("containers", [])

    serialized_containers = []
    flat_inventory_items = []
    total_weight = 0.0

    for container in raw_containers:
        serialized_items = []
        used_volume = 0.0
        container_weight = 0.0

        for item in container.get("items", []):
            quantity = int(item.get("quantity", 1))
            item_volume = float(item.get("volume", 0))
            item_weight = float(item.get("weight", 0))

            total_item_volume = item_volume * quantity
            total_item_weight = item_weight * quantity

            used_volume += total_item_volume
            container_weight += total_item_weight
            total_weight += total_item_weight

            serialized_item = {
                "item_id": item.get("item_id"),
                "name": item.get("name", "Unknown Item"),
                "description": item.get("description", ""),
                "size": item.get("size", "small"),
                "volume": _round_inventory_value(item_volume),
                "weight": _round_inventory_value(item_weight),
                "quantity": quantity,
                "stackable": bool(item.get("stackable", False)),
                "hand_usage": item.get("hand_usage", "none"),
                "item_type": item.get("item_type"),
                "display_name": _build_item_label(item),
                "total_volume": _round_inventory_value(total_item_volume),
                "total_weight": _round_inventory_value(total_item_weight),
            }
            serialized_items.append(serialized_item)
            flat_inventory_items.append(serialized_item["display_name"])

        max_volume = float(container.get("max_volume", 0))

        serialized_containers.append({
            "container_id": container.get("container_id"),
            "name": container.get("name", "Unnamed Container"),
            "source": container.get("source", "base"),
            "source_item_id": container.get("source_item_id"),
            "max_volume": _round_inventory_value(max_volume),
            "used_volume": _round_inventory_value(used_volume),
            "available_volume": _round_inventory_value(max_volume - used_volume),
            "max_item_size": container.get("max_item_size", "small"),
            "total_weight": _round_inventory_value(container_weight),
            "items": serialized_items,
        })

    return {
        "containers": serialized_containers,
        "equipment": equipment_data["labels"],
        "equipment_slots": equipment_data["slots"],
        "equipment_summary": equipment_data["summary"],
        "inventory": flat_inventory_items,
        "inventory_summary": ", ".join(flat_inventory_items) if flat_inventory_items else "Leer",
        "total_weight": _round_inventory_value(total_weight),
    }


def get_character_status_effects(character_id):
    if not character_id:
        return []
    return serialize_status_effects(character_id)


def serialize_character(
    character,
    get_active_campaign_for_character,
    get_current_campaign_location,
    get_active_campaign_quest,
):
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
        "equipment_summary": inventory_data["equipment_summary"],
        "inventory": inventory_data["inventory"],
        "inventory_summary": inventory_data["inventory_summary"],
        "inventory_total_weight": inventory_data["total_weight"],
        "inventory_containers": inventory_data["containers"],
    }
