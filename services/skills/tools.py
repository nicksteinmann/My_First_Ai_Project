"""Skill tool definitions and dispatcher."""

from .service import add_skill_xp, create_custom_skill, serialize_character_skills


SKILL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_skills",
            "description": "Return core and custom character skills with level and XP progress.",
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
            "name": "add_skill_xp",
            "description": "Add XP to a core or custom skill. Can create a custom skill when allow_create is true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "amount": {"type": "integer"},
                    "reason": {"type": "string"},
                    "allow_create": {"type": "boolean"},
                    "linked_attribute": {"type": "string"},
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
                    "category": {"type": "string"},
                    "icon": {"type": "string"},
                    "short_code": {"type": "string"},
                },
                "required": ["skill_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_custom_skill",
            "description": "Create or attach a reusable custom skill for a character when no core skill fits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "linked_attribute": {"type": "string"},
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
                    "description": {"type": "string"},
                    "icon": {"type": "string"},
                    "short_code": {"type": "string"},
                },
                "required": ["name", "linked_attribute"],
            },
        },
    },
]


def execute_skill_tool(character_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "get_skills":
        return {
            "success": True,
            "tool": "get_skills",
            "skills": serialize_character_skills(character_id),
        }

    if tool_name == "add_skill_xp":
        return add_skill_xp(
            character_id=character_id,
            skill_name=arguments.get("skill_name", ""),
            amount=arguments.get("amount", 0),
            reason=arguments.get("reason"),
            allow_create=bool(arguments.get("allow_create", False)),
            linked_attribute=arguments.get("linked_attribute"),
            secondary_attributes=arguments.get("secondary_attributes"),
            aliases=arguments.get("aliases"),
            allowed_domains=arguments.get("allowed_domains"),
            category=arguments.get("category", "Custom"),
            icon=arguments.get("icon"),
            short_code=arguments.get("short_code"),
        )

    if tool_name == "create_custom_skill":
        return create_custom_skill(
            character_id=character_id,
            name=arguments.get("name", ""),
            linked_attribute=arguments.get("linked_attribute", "intelligence"),
            secondary_attributes=arguments.get("secondary_attributes"),
            aliases=arguments.get("aliases"),
            allowed_domains=arguments.get("allowed_domains"),
            description=arguments.get("description"),
            icon=arguments.get("icon"),
            short_code=arguments.get("short_code"),
        )

    return {
        "success": False,
        "message": f"Unknown skill tool: {tool_name}",
    }
