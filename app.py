"""
Application entrypoint for the AI Pen & Paper project.

Responsibilities of this module:
- create and configure the Flask app
- initialize the database connection
- provide small app-level helper functions
- register route modules with their required dependencies

Business logic, tool handling, prompt building, serialization, and route
implementations live in dedicated modules/packages.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, session
from sqlalchemy.exc import SQLAlchemyError

from models import (
    db,
    User,
    Character,
    Campaign,
    CampaignLocation,
    CampaignQuest,
    WorldTemplate,
)
from routes import (
    register_auth_routes,
    register_page_routes,
    register_character_routes,
    register_game_routes,
)
from services.adventure_state import STATE_TOOL_DEFINITIONS, execute_state_tool
from services.currency import CURRENCY_TOOL_DEFINITIONS, execute_currency_tool
from services.equipment import EQUIPMENT_TOOL_DEFINITIONS, execute_equipment_tool
from services.inventory import INVENTORY_TOOL_DEFINITIONS, execute_inventory_tool
from services.serializers import serialize_character
from services.story import (
    get_recent_story_messages,
    serialize_story_messages_for_template,
)
from services.tools import (
    resolve_tool_calls,
    parse_tool_call_payload,
    normalize_tool_call,
    execute_normalized_tool,
    run_game_turn,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """
    Create, configure, and return the Flask application instance.
    """
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///AI_Pen_and_Paper.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "dev-secret-key-change-later"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {
            "timeout": 15,
        }
    }

    db.init_app(app)

    try:
        with app.app_context():
            db.create_all()
    except SQLAlchemyError as exc:
        logger.exception("Database initialization failed.")
        raise RuntimeError("Failed to initialize the database.") from exc

    def is_logged_in() -> bool:
        """
        Return whether a user session is currently active.
        """
        return "user_id" in session

    def get_current_user() -> Optional[User]:
        """
        Return the currently logged-in user or None if no valid session exists.
        """
        user_id = session.get("user_id")
        if not user_id:
            return None
        return db.session.get(User, user_id)

    def get_user_characters(user_id: int) -> list[Character]:
        """
        Return all characters belonging to a user ordered by creation time.
        """
        return (
            Character.query
            .filter_by(user_id=user_id)
            .order_by(Character.created_at.asc())
            .all()
        )

    def get_character_by_id_for_user(character_id: int, user_id: int) -> Optional[Character]:
        """
        Return a specific character for a specific user, or None if not found.
        """
        return Character.query.filter_by(id=character_id, user_id=user_id).first()

    def get_active_campaign_for_character(character_id: int) -> Optional[Campaign]:
        """
        Return the active campaign for a character, or None if no active campaign exists.
        """
        return (
            Campaign.query
            .filter_by(character_id=character_id, status="active")
            .order_by(Campaign.created_at.asc())
            .first()
        )

    def get_current_campaign_location(campaign: Optional[Campaign]) -> Optional[CampaignLocation]:
        """
        Return the current location for a campaign.

        Preference:
        1. Explicit current_location_id, if present
        2. Fallback to the first created location in the campaign
        """
        if campaign is None:
            return None

        if hasattr(campaign, "current_location_id") and campaign.current_location_id:
            return db.session.get(CampaignLocation, campaign.current_location_id)

        return (
            CampaignLocation.query
            .filter_by(campaign_id=campaign.id)
            .order_by(CampaignLocation.created_at.asc())
            .first()
        )

    def get_active_campaign_quest(campaign: Optional[Campaign]) -> Optional[CampaignQuest]:
        """
        Return the currently active quest for a campaign, or None if none exists.
        """
        if campaign is None:
            return None

        return (
            CampaignQuest.query
            .filter_by(campaign_id=campaign.id, status="active")
            .order_by(CampaignQuest.started_at.asc())
            .first()
        )

    def get_or_create_default_world_template() -> WorldTemplate:
        """
        Return the default world template, creating it if necessary.
        """
        world = WorldTemplate.query.filter_by(slug="avalion-default").first()
        if world:
            return world

        world = WorldTemplate(
            name="Avalion",
            slug="avalion-default",
            description="Default fantasy world for campaign starts.",
            lore_summary="A fantasy world with a peaceful capital hub for all peoples.",
            current_era="Fantasy Middle Ages",
            world_year=1000,
            is_active=True,
        )
        db.session.add(world)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Failed to create default world template.")
            raise RuntimeError("Failed to create default world template.") from exc

        return world

    def get_active_character():
        """
        Return the currently active serialized character for the logged-in user.

        If no active_character_id is stored in the session, the first available
        character is selected automatically and stored in the session.
        """
        if not is_logged_in():
            return None

        user_id = session.get("user_id")
        if user_id is None:
            return None

        active_character_id = session.get("active_character_id")

        if active_character_id:
            selected_character = get_character_by_id_for_user(active_character_id, user_id)
            if selected_character:
                return serialize_character(
                    selected_character,
                    get_active_campaign_for_character,
                    get_current_campaign_location,
                    get_active_campaign_quest,
                )

        characters = get_user_characters(user_id)
        if not characters:
            return None

        first_character = characters[0]
        session["active_character_id"] = first_character.id

        return serialize_character(
            first_character,
            get_active_campaign_for_character,
            get_current_campaign_location,
            get_active_campaign_quest,
        )

    register_auth_routes(app)

    register_page_routes(
        app,
        is_logged_in,
        get_current_user,
        get_active_character,
        get_active_campaign_for_character,
        get_current_campaign_location,
        get_active_campaign_quest,
        get_recent_story_messages,
        serialize_story_messages_for_template,
    )

    register_character_routes(
        app,
        is_logged_in,
        get_user_characters,
        get_character_by_id_for_user,
        get_active_campaign_for_character,
        get_current_campaign_location,
        get_active_campaign_quest,
        get_or_create_default_world_template,
    )

    register_game_routes(
        app,
        is_logged_in,
        get_active_character,
        get_active_campaign_for_character,
        get_recent_story_messages,
        STATE_TOOL_DEFINITIONS,
        INVENTORY_TOOL_DEFINITIONS,
        CURRENCY_TOOL_DEFINITIONS,
        EQUIPMENT_TOOL_DEFINITIONS,
        execute_state_tool,
        execute_inventory_tool,
        execute_currency_tool,
        execute_equipment_tool,
        resolve_tool_calls,
        parse_tool_call_payload,
        normalize_tool_call,
        execute_normalized_tool,
        run_game_turn,
    )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
