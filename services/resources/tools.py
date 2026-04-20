from .service import add_resource, get_resources, remove_resource, set_resource


RESOURCE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_resources",
            "description": "Return current HP, Mana and Energy values for the character.",
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
            "name": "add_resource",
            "description": "Restore or increase one character resource. Use for healing, mana recovery or energy recovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "Resource name: hp, mana or energy.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Amount to add. The value is capped at the resource maximum.",
                    },
                },
                "required": ["resource", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_resource",
            "description": "Damage, spend or reduce one character resource. HP reaching zero sets character status to dead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "Resource name: hp, mana or energy.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Amount to remove. The value cannot go below zero.",
                    },
                },
                "required": ["resource", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_resource",
            "description": "Set the current and/or maximum value of one resource. Use for backend-controlled stat changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "Resource name: hp, mana or energy.",
                    },
                    "current": {
                        "type": "integer",
                        "description": "Optional new current value.",
                    },
                    "maximum": {
                        "type": "integer",
                        "description": "Optional new maximum value.",
                    },
                },
                "required": ["resource"],
            },
        },
    },
]


def execute_resource_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_resources":
        return {
            "success": True,
            "tool": "get_resources",
            "resources": get_resources(character_id),
        }

    if tool_name == "add_resource":
        result = add_resource(
            character_id=character_id,
            resource=arguments.get("resource", ""),
            amount=arguments.get("amount", 0),
        )
        return result.to_dict()

    if tool_name == "remove_resource":
        result = remove_resource(
            character_id=character_id,
            resource=arguments.get("resource", ""),
            amount=arguments.get("amount", 0),
        )
        return result.to_dict()

    if tool_name == "set_resource":
        result = set_resource(
            character_id=character_id,
            resource=arguments.get("resource", ""),
            current=arguments.get("current"),
            maximum=arguments.get("maximum"),
        )
        return result.to_dict()

    return {
        "success": False,
        "message": f"Unknown resource tool: {tool_name}",
    }
