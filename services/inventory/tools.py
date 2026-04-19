from .service import get_inventory, add_inventory_item, remove_inventory_item


INVENTORY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_inventory",
            "description": "Return the current inventory with all containers and items.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_inventory_item",
            "description": "Add an item into a specific inventory container. If no container_id is given, use the base inventory container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {
                        "type": "object",
                        "description": "Full item payload.",
                        "properties": {
                            "item_id": {"type": "string"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "size": {"type": "string"},
                            "volume": {"type": "number"},
                            "weight": {"type": "number"},
                            "stackable": {"type": "boolean"},
                            "quantity": {"type": "integer"},
                            "hand_usage": {"type": "string"},
                            "item_type": {"type": "string"}
                        },
                        "required": ["name", "description", "size", "volume", "weight", "stackable", "hand_usage"]
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many items should be added."
                    },
                    "container_id": {
                        "type": "string",
                        "description": "Target container id."
                    }
                },
                "required": ["item", "quantity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_inventory_item",
            "description": "Remove an item or part of a stack from a container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The item id to remove."
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many units to remove."
                    },
                    "container_id": {
                        "type": "string",
                        "description": "Optional source container id."
                    }
                },
                "required": ["item_id", "quantity"]
            }
        }
    }
]


def execute_inventory_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_inventory":
        inventory = get_inventory(character_id)
        return {
            "success": True,
            "tool": "get_inventory",
            "inventory": inventory
        }

    if tool_name == "add_inventory_item":
        result = add_inventory_item(
            character_id=character_id,
            item=arguments.get("item", {}),
            quantity=arguments.get("quantity", 1),
            container_id=arguments.get("container_id")
        )
        return result.to_dict()

    if tool_name == "remove_inventory_item":
        result = remove_inventory_item(
            character_id=character_id,
            item_id=arguments.get("item_id", ""),
            quantity=arguments.get("quantity", 1),
            container_id=arguments.get("container_id")
        )
        return result.to_dict()

    return {
        "success": False,
        "error": f"Unknown inventory tool: {tool_name}"
    }