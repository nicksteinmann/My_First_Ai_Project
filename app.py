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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from models import (
    db,
    User,
    Character,
    Campaign,
    CampaignLocation,
    TemplateLocation,
    WorldTemplate,
)
from routes import (
    register_auth_routes,
    register_page_routes,
    register_character_routes,
    register_game_routes,
)
from services.adventure_state import STATE_TOOL_DEFINITIONS, execute_state_tool
from services.attributes import ATTRIBUTE_TOOL_DEFINITIONS, execute_attribute_tool
from services.currency import CURRENCY_TOOL_DEFINITIONS, execute_currency_tool
from services.equipment import EQUIPMENT_TOOL_DEFINITIONS, execute_equipment_tool
from services.inventory import INVENTORY_TOOL_DEFINITIONS, execute_inventory_tool
from services.leveling import LEVELING_TOOL_DEFINITIONS, execute_leveling_tool
from services.resources import RESOURCE_TOOL_DEFINITIONS, execute_resource_tool
from services.serializers import serialize_character
from services.skills import SKILL_TOOL_DEFINITIONS, ensure_core_skill_definitions, execute_skill_tool
from services.world_data import ensure_world_template_locations, load_world_data
from services.status_effects import STATUS_EFFECT_TOOL_DEFINITIONS, execute_status_effect_tool
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


def ensure_sqlite_schema_compatibility() -> None:
    """
    Apply tiny SQLite-only compatibility upgrades for MVP-era schema changes.

    Flask-SQLAlchemy's create_all creates missing tables, but it does not add
    new columns to existing tables. This keeps local development databases
    usable until a real migration layer is introduced.
    """
    columns = db.session.execute(text("PRAGMA table_info(character_attributes)")).fetchall()
    column_names = {column[1] for column in columns}

    if "attribute_xp_json" not in column_names:
        db.session.execute(text(
            "ALTER TABLE character_attributes "
            "ADD COLUMN attribute_xp_json TEXT NOT NULL DEFAULT '{}'"
        ))
        db.session.commit()

    skill_columns = db.session.execute(text("PRAGMA table_info(skill_definitions)")).fetchall()
    skill_column_names = {column[1] for column in skill_columns}
    skill_column_statements = {
        "icon": "ALTER TABLE skill_definitions ADD COLUMN icon VARCHAR(12)",
        "short_code": "ALTER TABLE skill_definitions ADD COLUMN short_code VARCHAR(8)",
        "is_custom": "ALTER TABLE skill_definitions ADD COLUMN is_custom BOOLEAN NOT NULL DEFAULT 0",
    }

    for column_name, statement in skill_column_statements.items():
        if column_name not in skill_column_names:
            db.session.execute(text(statement))

    quest_columns = db.session.execute(text("PRAGMA table_info(campaign_quests)")).fetchall()
    quest_column_names = {column[1] for column in quest_columns}
    quest_column_statements = {
        "quest_type": (
            "ALTER TABLE campaign_quests "
            "ADD COLUMN quest_type VARCHAR(40) NOT NULL DEFAULT 'general'"
        ),
        "turn_in_npc_id": "ALTER TABLE campaign_quests ADD COLUMN turn_in_npc_id INTEGER",
        "start_location_id": "ALTER TABLE campaign_quests ADD COLUMN start_location_id INTEGER",
        "target_location_id": "ALTER TABLE campaign_quests ADD COLUMN target_location_id INTEGER",
        "turn_in_location_id": "ALTER TABLE campaign_quests ADD COLUMN turn_in_location_id INTEGER",
        "objectives_json": (
            "ALTER TABLE campaign_quests "
            "ADD COLUMN objectives_json TEXT NOT NULL DEFAULT '[]'"
        ),
        "rewards_json": (
            "ALTER TABLE campaign_quests "
            "ADD COLUMN rewards_json TEXT NOT NULL DEFAULT '{}'"
        ),
        "reward_rules_json": (
            "ALTER TABLE campaign_quests "
            "ADD COLUMN reward_rules_json TEXT NOT NULL DEFAULT '{}'"
        ),
        "turned_in_at": "ALTER TABLE campaign_quests ADD COLUMN turned_in_at DATETIME",
        "reward_claimed_at": "ALTER TABLE campaign_quests ADD COLUMN reward_claimed_at DATETIME",
        "failed_at": "ALTER TABLE campaign_quests ADD COLUMN failed_at DATETIME",
    }

    for column_name, statement in quest_column_statements.items():
        if column_name not in quest_column_names:
            db.session.execute(text(statement))

    campaign_columns = db.session.execute(text("PRAGMA table_info(campaigns)")).fetchall()
    campaign_column_names = {column[1] for column in campaign_columns}
    if "current_ingame_minute" not in campaign_column_names:
        db.session.execute(text(
            "ALTER TABLE campaigns "
            "ADD COLUMN current_ingame_minute INTEGER NOT NULL DEFAULT 540"
        ))
        db.session.execute(text(
            """
            UPDATE campaigns
            SET current_ingame_minute = CASE current_ingame_time
                WHEN 'midnight' THEN 0
                WHEN 'late night' THEN 180
                WHEN 'early morning' THEN 360
                WHEN 'morning' THEN 540
                WHEN 'noon' THEN 720
                WHEN 'afternoon' THEN 900
                WHEN 'evening' THEN 1080
                WHEN 'night' THEN 1260
                ELSE 540
            END
            """
        ))

    location_columns = db.session.execute(text("PRAGMA table_info(campaign_locations)")).fetchall()
    location_column_names = {column[1] for column in location_columns}
    location_column_statements = {
        "coordinate_x": "ALTER TABLE campaign_locations ADD COLUMN coordinate_x REAL",
        "coordinate_y": "ALTER TABLE campaign_locations ADD COLUMN coordinate_y REAL",
        "coordinate_source": "ALTER TABLE campaign_locations ADD COLUMN coordinate_source VARCHAR(40)",
        "region_id": "ALTER TABLE campaign_locations ADD COLUMN region_id VARCHAR(80)",
        "region_name": "ALTER TABLE campaign_locations ADD COLUMN region_name VARCHAR(120)",
        "subregion": "ALTER TABLE campaign_locations ADD COLUMN subregion VARCHAR(120)",
        "world_location_id": "ALTER TABLE campaign_locations ADD COLUMN world_location_id VARCHAR(80)",
        "world_location_name": "ALTER TABLE campaign_locations ADD COLUMN world_location_name VARCHAR(120)",
    }

    for column_name, statement in location_column_statements.items():
        if column_name not in location_column_names:
            db.session.execute(text(statement))

    db.session.commit()


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
            ensure_sqlite_schema_compatibility()
            ensure_core_skill_definitions()
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

    def get_or_create_default_world_template() -> WorldTemplate:
        """
        Return the default world template, creating it if necessary.
        """
        world = WorldTemplate.query.filter_by(slug="avalion-default").first()
        if world:
            ensure_world_template_locations(db.session, world, TemplateLocation)
            db.session.commit()
            return world

        world_data = load_world_data()
        world = WorldTemplate(
            name=world_data["name"],
            slug="avalion-default",
            description=world_data["summary"],
            lore_summary=world_data["summary"],
            current_era=world_data["era"],
            world_year=world_data["year"],
            is_active=True,
        )
        db.session.add(world)
        db.session.flush()
        ensure_world_template_locations(db.session, world, TemplateLocation)

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
        )

    register_auth_routes(app)

    register_page_routes(
        app,
        is_logged_in,
        get_current_user,
        get_active_character,
        get_active_campaign_for_character,
        get_current_campaign_location,
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
        RESOURCE_TOOL_DEFINITIONS,
        STATUS_EFFECT_TOOL_DEFINITIONS,
        LEVELING_TOOL_DEFINITIONS,
        ATTRIBUTE_TOOL_DEFINITIONS,
        SKILL_TOOL_DEFINITIONS,
        execute_state_tool,
        execute_inventory_tool,
        execute_currency_tool,
        execute_equipment_tool,
        execute_resource_tool,
        execute_status_effect_tool,
        execute_leveling_tool,
        execute_attribute_tool,
        execute_skill_tool,
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
