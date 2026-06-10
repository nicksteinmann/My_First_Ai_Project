"""Merchant tool definitions and dispatcher."""

from .service import (
    buy_merchant_service,
    buy_item_from_merchant,
    get_merchant_inventory,
    get_merchants_at_location,
    sell_item_to_merchant,
)


MERCHANT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_merchants_at_location",
            "description": "Return fixed backend merchants at the current or specified campaign location, including stable merchant ids and visible service offers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_id": {
                        "type": "integer",
                        "description": "Optional campaign location id. Defaults to the current location.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_merchant_inventory",
            "description": "Inspect one merchant's backend inventory, prices, current stock, and daily rotating goods before buying anything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_npc_id": {
                        "type": "integer",
                        "description": "Required campaign NPC id of the merchant from get_merchants_at_location.",
                    }
                },
                "required": ["merchant_npc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buy_item_from_merchant",
            "description": "Buy one or more items from a merchant using backend-controlled prices, stock, inventory capacity, and currency validation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_npc_id": {
                        "type": "integer",
                        "description": "Required campaign NPC id of the merchant.",
                    },
                    "merchant_inventory_id": {
                        "type": "integer",
                        "description": "Required merchant inventory entry id from get_merchant_inventory.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many units to buy. Defaults to 1.",
                    },
                },
                "required": ["merchant_npc_id", "merchant_inventory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buy_merchant_service",
            "description": "Buy a fixed merchant service such as an inn meal or a cheap bed using backend-controlled price, time, and payment rules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_npc_id": {
                        "type": "integer",
                        "description": "Required campaign NPC id of the merchant.",
                    },
                    "service_id": {
                        "type": "string",
                        "description": "Required service id from get_merchants_at_location or get_merchant_inventory.",
                    },
                },
                "required": ["merchant_npc_id", "service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sell_item_to_merchant",
            "description": "Sell an inventory item to a merchant for backend-controlled payment. Quest items cannot be sold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_npc_id": {
                        "type": "integer",
                        "description": "Required campaign NPC id of the merchant.",
                    },
                    "item_id": {
                        "type": "string",
                        "description": "Inventory item id or item name to sell.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many units to sell. Defaults to 1.",
                    },
                },
                "required": ["merchant_npc_id", "item_id"],
            },
        },
    },
]


def execute_merchant_tool(campaign_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_merchants_at_location":
        return get_merchants_at_location(
            campaign_id=campaign_id,
            location_id=arguments.get("location_id"),
        )

    if tool_name == "get_merchant_inventory":
        return get_merchant_inventory(
            campaign_id=campaign_id,
            merchant_npc_id=int(arguments.get("merchant_npc_id")),
        )

    if tool_name == "buy_item_from_merchant":
        return buy_item_from_merchant(
            campaign_id=campaign_id,
            merchant_npc_id=int(arguments.get("merchant_npc_id")),
            merchant_inventory_id=int(arguments.get("merchant_inventory_id")),
            quantity=arguments.get("quantity", 1),
        )

    if tool_name == "buy_merchant_service":
        return buy_merchant_service(
            campaign_id=campaign_id,
            merchant_npc_id=int(arguments.get("merchant_npc_id")),
            service_id=arguments.get("service_id", ""),
        )

    if tool_name == "sell_item_to_merchant":
        return sell_item_to_merchant(
            campaign_id=campaign_id,
            merchant_npc_id=int(arguments.get("merchant_npc_id")),
            item_id=arguments.get("item_id", ""),
            quantity=arguments.get("quantity", 1),
        )

    return {
        "success": False,
        "message": f"Unknown merchant tool: {tool_name}",
    }
