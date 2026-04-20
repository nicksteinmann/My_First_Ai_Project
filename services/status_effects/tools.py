from .service import apply_status_effect, get_status_effects, remove_status_effect


STATUS_EFFECT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_status_effects",
            "description": "Return active status effects on the character.",
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
            "name": "apply_status_effect",
            "description": "Apply or refresh a status effect such as poisoned, bleeding, stunned or blessed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Status effect name.",
                    },
                    "effect_type": {
                        "type": "string",
                        "description": "Effect category, for example condition, buff, debuff, poison, injury or blessing.",
                    },
                    "duration_turns": {
                        "type": "integer",
                        "description": "How many turns the effect remains active.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of the effect.",
                    },
                    "source_text": {
                        "type": "string",
                        "description": "Optional short note about the source of the effect.",
                    },
                },
                "required": ["name", "duration_turns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_status_effect",
            "description": "Remove an active status effect from the character.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Status effect name.",
                    },
                    "status_effect_id": {
                        "type": "integer",
                        "description": "Optional concrete active status effect id.",
                    },
                },
                "required": [],
            },
        },
    },
]


def execute_status_effect_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_status_effects":
        return {
            "success": True,
            "tool": "get_status_effects",
            "status_effects": get_status_effects(character_id),
        }

    if tool_name == "apply_status_effect":
        result = apply_status_effect(
            character_id=character_id,
            name=arguments.get("name", ""),
            effect_type=arguments.get("effect_type", "condition"),
            duration_turns=arguments.get("duration_turns", 1),
            description=arguments.get("description"),
            source_text=arguments.get("source_text"),
        )
        return result.to_dict()

    if tool_name == "remove_status_effect":
        result = remove_status_effect(
            character_id=character_id,
            name=arguments.get("name"),
            status_effect_id=arguments.get("status_effect_id"),
        )
        return result.to_dict()

    return {
        "success": False,
        "message": f"Unknown status effect tool: {tool_name}",
    }
