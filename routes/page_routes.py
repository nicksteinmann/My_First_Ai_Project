from flask import render_template, redirect, url_for, session, flash, jsonify

from models import User, Character, Campaign, CampaignQuest
from data.character_presets import RACES, CLASSES

from services.llm_service import check_provider_availability
from services.serializers.character_serializer import get_character_inventory_data, get_character_status_effects


def register_page_routes(
    app,
    is_logged_in,
    get_current_user,
    get_active_character,
    get_active_campaign_for_character,
    get_current_campaign_location,
    get_active_campaign_quest,
    get_recent_story_messages,
    serialize_story_messages_for_template,
):
    @app.route("/")
    def index():
        if not is_logged_in():
            return render_template("index.html", page_title="Home", logged_in=False)

        current_user = get_current_user()

        if not current_user:
            session.clear()
            flash("Your session has expired. Please log in again.", "error")
            return redirect(url_for("login"))

        active_character = get_active_character()
        story_messages = []

        if active_character:
            campaign = get_active_campaign_for_character(active_character["id"])
            if campaign:
                recent_messages = get_recent_story_messages(campaign.id, limit=20)
                story_messages = serialize_story_messages_for_template(recent_messages)

        return render_template(
            "index.html",
            page_title="Home",
            logged_in=True,
            active_character=active_character,
            username=current_user.username,
            story_messages=story_messages
        )

    @app.route("/world")
    def world():
        world_data = {
            "name": "Avalion",
            "era": "Fantasy Middle Ages",
            "year": 1000,
            "summary": (
                "Avalion is a placeholder fantasy world used for development and testing. "
                "This page will later contain lore, kingdoms, factions, important NPCs, and world history."
            ),
            "locations": [
                "Ravenhold",
                "Greywood",
                "Ironhill",
                "The Old King's Road"
            ]
        }

        return render_template(
            "world.html",
            page_title="World",
            world=world_data
        )

    @app.route("/community")
    def community():
        users = User.query.order_by(User.username.asc()).all()

        community_users = []

        for user in users:
            user_characters = Character.query.filter_by(user_id=user.id).order_by(Character.created_at.asc()).all()

            serialized_characters = []
            for character in user_characters:
                resources = character.resources
                attributes = character.attributes
                campaign = get_active_campaign_for_character(character.id)
                current_location = get_current_campaign_location(campaign)
                active_quest = get_active_campaign_quest(campaign)
                inventory_data = get_character_inventory_data(character.id)
                status_effects = get_character_status_effects(character.id)

                serialized_characters.append({
                    "id": character.id,
                    "name": character.name,
                    "race": character.race,
                    "class_name": character.class_name,
                    "level": character.level,
                    "status": character.status,
                    "status_effects": status_effects,
                    "currency": character.currency_json,
                    "hp": resources.hp_current if resources else 0,
                    "max_hp": resources.hp_max if resources else 0,
                    "mana": resources.mana_current if resources else 0,
                    "max_mana": resources.mana_max if resources else 0,
                    "energy": resources.energy_current if resources else 0,
                    "max_energy": resources.energy_max if resources else 0,
                    "strength": attributes.strength if attributes else 0,
                    "dexterity": attributes.dexterity if attributes else 0,
                    "intelligence": attributes.intelligence if attributes else 0,
                    "location": current_location.name if current_location else "Unknown",
                    "time": campaign.current_ingame_time if campaign else "Unknown",
                    "quest": active_quest.title if active_quest else "No active quest",
                    "equipment": inventory_data["equipment"],
                    "equipment_slots": inventory_data["equipment_slots"],
                    "equipment_summary": inventory_data["equipment_summary"],
                    "inventory": inventory_data["inventory"],
                    "inventory_summary": inventory_data["inventory_summary"],
                    "inventory_total_weight": inventory_data["total_weight"],
                    "inventory_containers": inventory_data["containers"]
                })

            community_users.append({
                "username": user.username,
                "characters": serialized_characters
            })

        return render_template(
            "community.html",
            page_title="Community",
            community_users=community_users
        )

    @app.route("/support")
    def support():
        faq_items = [
            {
                "question": "What is this project?",
                "answer": "A text-based AI Pen & Paper prototype using Flask, SQLAlchemy, and LLM APIs."
            },
            {
                "question": "Which models are supported?",
                "answer": "Currently OpenAI and DeepSeek are planned and can be switched dynamically."
            },
            {
                "question": "Is this a finished game?",
                "answer": "No. This is an active prototype under development."
            }
        ]

        return render_template(
            "support.html",
            page_title="Support & FAQ",
            faq_items=faq_items
        )

    @app.route("/api/providers", methods=["GET"])
    def providers():
        openai_status = check_provider_availability("openai")
        deepseek_status = check_provider_availability("deepseek")

        return jsonify({
            "providers": [
                openai_status,
                deepseek_status
            ]
        })
