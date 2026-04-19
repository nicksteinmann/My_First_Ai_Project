from typing import Dict, Any

from services.currency.service import (
    add_currency,
    remove_currency,
    get_currency,
)


# ===== TOOL DEFINITIONS =====

CURRENCY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_currency",
            "description": "Add currency to the character.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gold": {
                        "type": "integer",
                        "description": "Amount of gold to add",
                    },
                    "silver": {
                        "type": "integer",
                        "description": "Amount of silver to add",
                    },
                    "copper": {
                        "type": "integer",
                        "description": "Amount of copper to add",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_currency",
            "description": "Remove currency from the character.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gold": {
                        "type": "integer",
                        "description": "Amount of gold to remove",
                    },
                    "silver": {
                        "type": "integer",
                        "description": "Amount of silver to remove",
                    },
                    "copper": {
                        "type": "integer",
                        "description": "Amount of copper to remove",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_currency",
            "description": "Get the current currency of the character.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ===== TOOL EXECUTION =====

def execute_currency_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    character_id: int,
):
    try:
        if tool_name == "add_currency":
            result = add_currency(
                character_id=character_id,
                gold=arguments.get("gold", 0),
                silver=arguments.get("silver", 0),
                copper=arguments.get("copper", 0),
            )

        elif tool_name == "remove_currency":
            result = remove_currency(
                character_id=character_id,
                gold=arguments.get("gold", 0),
                silver=arguments.get("silver", 0),
                copper=arguments.get("copper", 0),
            )

        elif tool_name == "get_currency":
            currency = get_currency(character_id)

            return {
                "success": True,
                "message": "Currency fetched successfully.",
                "currency": currency,
            }

        else:
            return {
                "success": False,
                "message": f"Unknown currency tool: {tool_name}",
            }

        return {
            "success": result.success,
            "message": result.message,
            "currency": result.currency,
            "details": result.details,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Currency tool error: {str(e)}",
        }