import json

from models import db, Campaign, CampaignLocation, CampaignQuest


TIME_ORDER = ["late night", "early morning", "morning", "noon", "afternoon", "evening", "night", "midnight"]


def _normalize_time_label(value: str) -> str:
    if not value:
        return "morning"

    value = value.strip().lower()
    if value in TIME_ORDER:
        return value

    return "morning"


def _advance_time_label(current_label: str, minutes: int) -> str:
    current_label = _normalize_time_label(current_label)

    if minutes <= 0:
        return current_label

    current_index = TIME_ORDER.index(current_label)

    # Grobe MVP-Zeitlogik:
    # < 180 Minuten = gleiche Tagesphase
    # alle weiteren 180 Minuten = eine Phase weiter
    steps = minutes // 180
    if minutes % 180 != 0:
        steps += 1

    new_index = min(current_index + steps, len(TIME_ORDER) - 1)
    return TIME_ORDER[new_index]


def update_location(campaign_id: int, location_name: str, location_type: str = None, description: str = None):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    if not location_name or not location_name.strip():
        return {
            "success": False,
            "error": "Location name is required."
        }

    location_name = location_name.strip()

    existing_location = (
        CampaignLocation.query
        .filter_by(campaign_id=campaign.id, name=location_name)
        .first()
    )

    if existing_location:
        location = existing_location

        if location_type and not location.location_type:
            location.location_type = location_type

        if description and not location.description:
            location.description = description
    else:
        location = CampaignLocation(
            campaign_id=campaign.id,
            name=location_name,
            location_type=location_type or "custom",
            description=description or "",
            is_discovered=True,
            is_custom=True
        )
        db.session.add(location)
        db.session.flush()

    if hasattr(campaign, "current_location_id"):
        campaign.current_location_id = location.id

    db.session.commit()

    return {
        "success": True,
        "tool": "update_location",
        "location_name": location.name,
        "location_type": location.location_type
    }


def advance_time(campaign_id: int, minutes: int):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "Minutes must be an integer."
        }

    old_time = _normalize_time_label(campaign.current_ingame_time)
    new_time = _advance_time_label(old_time, minutes)

    campaign.current_ingame_time = new_time
    db.session.commit()

    return {
        "success": True,
        "tool": "advance_time",
        "old_time": old_time,
        "new_time": new_time,
        "minutes_advanced": minutes
    }


def set_active_quest(campaign_id: int, title: str, description: str):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    if not title or not title.strip():
        return {
            "success": False,
            "error": "Quest title is required."
        }

    title = title.strip()
    description = (description or "").strip()

    active_quests = CampaignQuest.query.filter_by(campaign_id=campaign.id, status="active").all()
    for quest in active_quests:
        quest.status = "inactive"

    existing_quest = (
        CampaignQuest.query
        .filter_by(campaign_id=campaign.id, title=title)
        .order_by(CampaignQuest.id.desc())
        .first()
    )

    if existing_quest:
        existing_quest.description = description or existing_quest.description
        existing_quest.status = "active"
        quest = existing_quest
    else:
        quest = CampaignQuest(
            campaign_id=campaign.id,
            title=title,
            description=description,
            status="active",
            reward_gold=0,
            reward_xp=0
        )
        db.session.add(quest)

    db.session.commit()

    return {
        "success": True,
        "tool": "set_active_quest",
        "quest_title": quest.title,
        "quest_description": quest.description
    }


def complete_active_quest(campaign_id: int):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {
            "success": False,
            "error": "Campaign not found."
        }

    quest = (
        CampaignQuest.query
        .filter_by(campaign_id=campaign.id, status="active")
        .order_by(CampaignQuest.id.asc())
        .first()
    )

    if not quest:
        return {
            "success": False,
            "error": "No active quest found."
        }

    quest.status = "completed"
    db.session.commit()

    return {
        "success": True,
        "tool": "complete_active_quest",
        "quest_title": quest.title
    }


STATE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "update_location",
            "description": "Update the character's current location when they move to a different place.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "The new location name."
                    },
                    "location_type": {
                        "type": "string",
                        "description": "The type of location, for example inn, shop, street, shrine or room."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional short description of the location."
                    }
                },
                "required": ["location_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "advance_time",
            "description": "Advance in-game time after travel, waiting, conversations or actions that take time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "integer",
                        "description": "How many in-game minutes pass."
                    }
                },
                "required": ["minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_active_quest",
            "description": "Set or replace the currently active quest when a new quest begins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The quest title."
                    },
                    "description": {
                        "type": "string",
                        "description": "The quest description."
                    }
                },
                "required": ["title", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_active_quest",
            "description": "Complete the currently active quest when its objective has clearly been fulfilled.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def execute_state_tool(campaign_id: int, tool_name: str, arguments: dict):
    arguments = arguments or {}

    if tool_name == "update_location":
        return update_location(
            campaign_id=campaign_id,
            location_name=arguments.get("location_name", ""),
            location_type=arguments.get("location_type"),
            description=arguments.get("description")
        )

    if tool_name == "advance_time":
        return advance_time(
            campaign_id=campaign_id,
            minutes=arguments.get("minutes", 0)
        )

    if tool_name == "set_active_quest":
        return set_active_quest(
            campaign_id=campaign_id,
            title=arguments.get("title", ""),
            description=arguments.get("description", "")
        )

    if tool_name == "complete_active_quest":
        return complete_active_quest(
            campaign_id=campaign_id
        )

    return {
        "success": False,
        "error": f"Unknown tool: {tool_name}"
    }