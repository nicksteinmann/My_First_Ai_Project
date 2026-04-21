from .service import add_attribute_xp


ATTRIBUTE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_attribute_xp",
            "description": (
                "Add XP to one or more character attributes. Use for training, learning, "
                "attribute-focused rewards or attribute XP consumables."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "attribute": {
                        "type": "string",
                        "description": "Single attribute name: strength, dexterity, constitution, intelligence, perception or charisma.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "XP amount for the single attribute.",
                    },
                    "grants": {
                        "type": "object",
                        "description": "Optional batch grants, for example {\"strength\": 10000, \"dexterity\": 10000}.",
                        "additionalProperties": {
                            "type": "integer",
                        },
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional short reason for the XP gain.",
                    },
                },
                "required": [],
            },
        },
    },
]


def execute_attribute_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "add_attribute_xp":
        return add_attribute_xp(
            character_id=character_id,
            attribute=arguments.get("attribute"),
            amount=arguments.get("amount"),
            grants=arguments.get("grants"),
            reason=arguments.get("reason"),
        )

    return {
        "success": False,
        "message": f"Unknown attribute tool: {tool_name}",
    }
