from .service import add_xp


LEVELING_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_xp",
            "description": "Add character XP. The backend handles level-ups, max level and resource bonuses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Amount of XP to add.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional short reason for the XP gain.",
                    },
                },
                "required": ["amount"],
            },
        },
    },
]


def execute_leveling_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "add_xp":
        result = add_xp(
            character_id=character_id,
            amount=arguments.get("amount", 0),
            reason=arguments.get("reason"),
        )
        return result.to_dict()

    return {
        "success": False,
        "message": f"Unknown leveling tool: {tool_name}",
    }
