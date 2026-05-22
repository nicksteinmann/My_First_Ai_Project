"""Equipment tool definitions and dispatcher."""

from .service import equip_item, get_attack_profile, get_equipment, unequip_item


EQUIPMENT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_equipment",
            "description": "Return all equipment slots and currently equipped items.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "equip_item",
            "description": (
                "Equip one reachable item into an equipment slot. This can equip items from carried "
                "inventory containers or nearby scene containers, for example a Travel Backpack in "
                "nearby_room_gear. Use this instead of add_inventory_item when the player wears or "
                "wields an existing item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The inventory item id or item name to equip.",
                    },
                    "slot": {
                        "type": "string",
                        "description": "Optional equipment slot, for example head, torso_armor, gloves, belt, belt_slot_1, belt_slot_2, backpack, ring_left, main_hand or off_hand. Use backpack for backpacks worn on the back.",
                    },
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unequip_item",
            "description": "Unequip an item from a slot or by item id and return it to an inventory container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {
                        "type": "string",
                        "description": "The equipment slot to clear.",
                    },
                    "item_id": {
                        "type": "string",
                        "description": "Optional equipped item id or name.",
                    },
                    "target_container_id": {
                        "type": "string",
                        "description": "Optional inventory container id for the unequipped item.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_attack_profile",
            "description": (
                "Return backend-calculated weapon attack profile including weapon family, "
                "damage range, attribute scaling and skill contribution for the currently equipped weapon."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def execute_equipment_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_equipment":
        return {
            "success": True,
            "tool": "get_equipment",
            "equipment": get_equipment(character_id),
        }

    if tool_name == "equip_item":
        result = equip_item(
            character_id=character_id,
            item_id=arguments.get("item_id", ""),
            slot=arguments.get("slot"),
        )
        return result.to_dict()

    if tool_name == "unequip_item":
        result = unequip_item(
            character_id=character_id,
            slot=arguments.get("slot"),
            item_id=arguments.get("item_id"),
            target_container_id=arguments.get("target_container_id"),
        )
        return result.to_dict()

    if tool_name == "get_attack_profile":
        response = get_attack_profile(character_id)
        response["tool"] = "get_attack_profile"
        return response

    return {
        "success": False,
        "message": f"Unknown equipment tool: {tool_name}",
    }
