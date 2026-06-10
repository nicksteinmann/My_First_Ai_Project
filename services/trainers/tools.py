"""Trainer tool definitions and dispatcher."""

from .service import get_trainers_at_location, train_with_teacher


TRAINER_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_trainers_at_location",
            "description": "Return backend-approved trainers at the current or specified location, including trainer tier, specialties, and level limits.",
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
            "name": "train_with_teacher",
            "description": "Buy a backend-priced lesson from a trainer for a skill or attribute. Handles time, money, trainer limits, and XP scaling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trainer_npc_id": {
                        "type": "integer",
                        "description": "Required campaign NPC id of the trainer.",
                    },
                    "training_type": {
                        "type": "string",
                        "description": "Required training type: skill or attribute.",
                    },
                    "target_name": {
                        "type": "string",
                        "description": "Required skill name or attribute name to train.",
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Optional lesson duration in 30-minute steps from 30 to 120. Defaults to 60.",
                    },
                    "allow_create_skill": {
                        "type": "boolean",
                        "description": "For custom skills, allow backend creation before the lesson when metadata is provided.",
                    },
                    "linked_attribute": {
                        "type": "string",
                        "description": "Required for new custom skills when allow_create_skill is true.",
                    },
                    "secondary_attributes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["trainer_npc_id", "training_type", "target_name"],
            },
        },
    },
]


def execute_trainer_tool(campaign_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_trainers_at_location":
        return get_trainers_at_location(
            campaign_id=campaign_id,
            location_id=arguments.get("location_id"),
        )

    if tool_name == "train_with_teacher":
        return train_with_teacher(
            campaign_id=campaign_id,
            trainer_npc_id=int(arguments.get("trainer_npc_id")),
            training_type=arguments.get("training_type", ""),
            target_name=arguments.get("target_name", ""),
            minutes=arguments.get("minutes"),
            allow_create_skill=bool(arguments.get("allow_create_skill", False)),
            linked_attribute=arguments.get("linked_attribute"),
            secondary_attributes=arguments.get("secondary_attributes"),
            aliases=arguments.get("aliases"),
            allowed_domains=arguments.get("allowed_domains"),
            charge_price=bool(arguments.get("charge_price", True)),
        )

    return {
        "success": False,
        "message": f"Unknown trainer tool: {tool_name}",
    }
