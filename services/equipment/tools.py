"""Equipment tool definitions and dispatcher."""

from .service import equip_item, get_equipment, unequip_item


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
            "description": "Equip one inventory item into an equipment slot. Provide slot when the target slot is ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The inventory item id or item name to equip.",
                    },
                    "slot": {
                        "type": "string",
                        "description": "Optional equipment slot, for example head, torso_armor, gloves, belt, belt_slot_1, belt_slot_2, backpack, ring_left, main_hand or off_hand.",
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

    return {
        "success": False,
        "message": f"Unknown equipment tool: {tool_name}",
    }
