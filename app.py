import json
import re

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from services.llm_service import build_client, get_provider_config, check_provider_availability
from services.tools.state_tools import STATE_TOOL_DEFINITIONS, execute_state_tool
from data.character_presets import RACES, CLASSES
from models import (
    db,
    User,
    UserProfile,
    Character,
    CharacterAttribute,
    CharacterResource,
    Campaign,
    CampaignState,
    CampaignLocation,
    CampaignQuest,
    CharacterInventory,
    ItemDefinition,
    CampaignItem,
    WorldTemplate,
    StoryMessage,
)


def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///AI_Pen_and_Paper.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "dev-secret-key-change-later"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {
            "timeout": 15
        }
    }

    db.init_app(app)

    with app.app_context():
        db.create_all()

    def is_logged_in():
        return "user_id" in session

    def get_current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        return db.session.get(User, user_id)

    def get_user_characters(user_id):
        return Character.query.filter_by(user_id=user_id).order_by(Character.created_at.asc()).all()

    def get_character_by_id_for_user(character_id, user_id):
        return Character.query.filter_by(id=character_id, user_id=user_id).first()

    def get_active_campaign_for_character(character_id):
        return (
            Campaign.query
            .filter_by(character_id=character_id, status="active")
            .order_by(Campaign.created_at.asc())
            .first()
        )

    def get_current_campaign_location(campaign):
        if not campaign:
            return None

        if hasattr(campaign, "current_location_id") and campaign.current_location_id:
            return db.session.get(CampaignLocation, campaign.current_location_id)

        return (
            CampaignLocation.query
            .filter_by(campaign_id=campaign.id)
            .order_by(CampaignLocation.created_at.asc())
            .first()
        )

    def get_active_campaign_quest(campaign):
        if not campaign:
            return None

        return (
            CampaignQuest.query
            .filter_by(campaign_id=campaign.id, status="active")
            .order_by(CampaignQuest.started_at.asc())
            .first()
        )

    def get_or_create_default_world_template():
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
        db.session.commit()
        return world

    def get_or_create_item_definition(name, item_type, rarity, description, value_base, weight, slot_type=None):
        item = ItemDefinition.query.filter_by(name=name).first()
        if item:
            return item

        item = ItemDefinition(
            name=name,
            item_type=item_type,
            rarity=rarity,
            description=description,
            value_base=value_base,
            weight=weight,
            slot_type=slot_type,
            is_template_item=True,
        )
        db.session.add(item)
        db.session.commit()
        return item

    def get_character_inventory_lists(character_id):
        inventory_rows = (
            CharacterInventory.query
            .filter_by(character_id=character_id)
            .order_by(CharacterInventory.id.asc())
            .all()
        )

        item_definition_ids = [row.item_definition_id for row in inventory_rows if row.item_definition_id]
        campaign_item_ids = [row.campaign_item_id for row in inventory_rows if row.campaign_item_id]

        item_definitions = {}
        if item_definition_ids:
            defs = ItemDefinition.query.filter(ItemDefinition.id.in_(item_definition_ids)).all()
            item_definitions = {item.id: item for item in defs}

        campaign_items = {}
        if campaign_item_ids:
            items = CampaignItem.query.filter(CampaignItem.id.in_(campaign_item_ids)).all()
            campaign_items = {item.id: item for item in items}

        equipment = []
        inventory = []

        for row in inventory_rows:
            item_name = "Unknown Item"

            if row.item_definition_id and row.item_definition_id in item_definitions:
                item_name = item_definitions[row.item_definition_id].name
            elif row.campaign_item_id and row.campaign_item_id in campaign_items:
                item_name = campaign_items[row.campaign_item_id].name

            if row.quantity and row.quantity > 1:
                item_name = f"{item_name} x{row.quantity}"

            if row.is_equipped:
                equipment.append(item_name)
            else:
                inventory.append(item_name)

        return equipment, inventory

    def get_recent_story_messages(campaign_id, limit=12):
        messages = (
            StoryMessage.query
            .filter_by(campaign_id=campaign_id)
            .order_by(StoryMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(messages))

    def serialize_story_messages_for_template(messages):
        serialized = []

        for msg in messages:
            if msg.sender_type == "user":
                css_class = "user"
                sender_label = "You"
            elif msg.sender_type in ("assistant", "ai", "gm"):
                css_class = "ai"
                sender_label = "Game Master"
            else:
                css_class = "system"
                sender_label = "System"

            serialized.append({
                "sender_label": sender_label,
                "css_class": css_class,
                "content": msg.content
            })

        return serialized

    def build_story_history_text(messages):
        if not messages:
            return ""

        lines = []
        for msg in messages:
            if msg.sender_type == "user":
                speaker = "Player"
            elif msg.sender_type in ("assistant", "ai", "gm"):
                speaker = "Game Master"
            else:
                speaker = "System"

            lines.append(f"{speaker}: {msg.content}")

        return "\n".join(lines)

    def serialize_character(character):
        attributes = character.attributes
        resources = character.resources
        campaign = get_active_campaign_for_character(character.id)
        current_location = get_current_campaign_location(campaign)
        active_quest = get_active_campaign_quest(campaign)
        equipment_items, inventory_items = get_character_inventory_lists(character.id)

        hp_current = resources.hp_current if resources else 0
        hp_max = resources.hp_max if resources else 0
        mana_current = resources.mana_current if resources else 0
        mana_max = resources.mana_max if resources else 0
        energy_current = resources.energy_current if resources else 0
        energy_max = resources.energy_max if resources else 0

        strength = attributes.strength if attributes else 0
        dexterity = attributes.dexterity if attributes else 0
        intelligence = attributes.intelligence if attributes else 0
        perception = attributes.perception if attributes else 0

        return {
            "id": character.id,
            "name": character.name,
            "race": character.race,
            "class_name": character.class_name,
            "level": character.level,
            "status": character.status,
            "gold": character.gold,
            "portrait": "👤",
            "stats": {
                "hp": hp_current,
                "hp_max": hp_max,
                "mana": mana_current,
                "mana_max": mana_max,
                "energy": energy_current,
                "energy_max": energy_max,
                "gold": character.gold
            },
            "skills": [
                {"icon": "⚔️", "name": "Strength", "level": strength},
                {"icon": "🎯", "name": "Dexterity", "level": dexterity},
                {"icon": "🧠", "name": "Intelligence", "level": intelligence},
                {"icon": "👁️", "name": "Perception", "level": perception},
            ],
            "current_state": {
                "location": current_location.name if current_location else "Unknown",
                "time_of_day": campaign.current_ingame_time if campaign else "Unknown",
                "active_quest": active_quest.title if active_quest else "No active quest",
                "active_quest_description": active_quest.description if active_quest else ""
            },
            "equipment": equipment_items,
            "inventory": inventory_items
        }

    def get_active_character():
        if not is_logged_in():
            return None

        user_id = session.get("user_id")
        active_character_id = session.get("active_character_id")

        if active_character_id:
            selected_character = get_character_by_id_for_user(active_character_id, user_id)
            if selected_character:
                return serialize_character(selected_character)

        characters = get_user_characters(user_id)

        if not characters:
            return None

        first_character = characters[0]
        session["active_character_id"] = first_character.id
        return serialize_character(first_character)

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

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()

            if not username or not password:
                flash("Please enter username and password.", "error")
                return render_template("login.html", page_title="Login")

            try:
                user = User.query.filter_by(username=username).first()

                if not user:
                    flash("User not found.", "error")
                    return render_template("login.html", page_title="Login")

                if not check_password_hash(user.password_hash, password):
                    flash("Incorrect password.", "error")
                    return render_template("login.html", page_title="Login")

                session["user_id"] = user.id
                session["username"] = user.username
                session.pop("active_character_id", None)

                return redirect(url_for("index"))

            except Exception as e:
                db.session.rollback()
                flash(f"Database error: {str(e)}", "error")
                return render_template("login.html", page_title="Login")

        return render_template("login.html", page_title="Login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()

            if not username or not email or not password:
                flash("Please fill in all fields.", "error")
                return render_template("register.html", page_title="Register")

            existing_username = User.query.filter_by(username=username).first()
            if existing_username:
                flash("This username is already taken.", "error")
                return render_template("register.html", page_title="Register")

            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                flash("This email is already in use.", "error")
                return render_template("register.html", page_title="Register")

            try:
                password_hash = generate_password_hash(password)

                new_user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    is_active=True
                )
                db.session.add(new_user)
                db.session.commit()

                new_profile = UserProfile(
                    user_id=new_user.id,
                    display_name=username,
                    bio="New adventurer"
                )
                db.session.add(new_profile)
                db.session.commit()

                flash("Registration successful. You can now log in.", "success")
                return redirect(url_for("login"))

            except Exception as e:
                db.session.rollback()
                flash(f"Database error: {str(e)}", "error")
                return render_template("register.html", page_title="Register")

        return render_template("register.html", page_title="Register")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/characters")
    def characters():
        if not is_logged_in():
            return redirect(url_for("login"))

        user_id = session.get("user_id")
        active_character_id = session.get("active_character_id")
        db_characters = get_user_characters(user_id)

        characters = []
        for character in db_characters:
            resources = character.resources
            attributes = character.attributes
            campaign = get_active_campaign_for_character(character.id)
            current_location = get_current_campaign_location(campaign)
            active_quest = get_active_campaign_quest(campaign)
            equipment_items, inventory_items = get_character_inventory_lists(character.id)

            completed_quests_count = 0
            campaigns_count = Campaign.query.filter_by(character_id=character.id).count()

            if campaign:
                completed_quests_count = CampaignQuest.query.filter_by(
                    campaign_id=campaign.id,
                    status="completed"
                ).count()

            characters.append({
                "id": character.id,
                "name": character.name,
                "race": character.race,
                "class_name": character.class_name,
                "level": character.level,
                "status": character.status,
                "gold": character.gold,
                "is_active": character.id == active_character_id,
                "hp": resources.hp_current if resources else 0,
                "max_hp": resources.hp_max if resources else 0,
                "mana": resources.mana_current if resources else 0,
                "max_mana": resources.mana_max if resources else 0,
                "energy": resources.energy_current if resources else 0,
                "max_energy": resources.energy_max if resources else 0,
                "location": current_location.name if current_location else "Unknown",
                "time": campaign.current_ingame_time if campaign else "Unknown",
                "quest": active_quest.title if active_quest else "No active quest",
                "completed_quests": completed_quests_count,
                "campaigns": campaigns_count,
                "equipment": equipment_items,
                "inventory": inventory_items,
                "skill_1": attributes.strength if attributes else 0,
                "skill_2": attributes.dexterity if attributes else 0,
                "skill_3": attributes.intelligence if attributes else 0,
                "skill_4": attributes.perception if attributes else 0
            })

        return render_template(
            "characters.html",
            page_title="My Characters",
            characters=characters,
            races=RACES,
            classes=CLASSES
        )

    @app.route("/characters/create", methods=["POST"])
    def create_character():
        if not is_logged_in():
            return redirect(url_for("login"))

        user_id = session.get("user_id")

        name = request.form.get("name", "").strip()
        race = request.form.get("race", "").strip()
        class_name = request.form.get("class_name", "").strip()

        if not name or not race or not class_name:
            flash("Please fill in all character fields.", "error")
            return redirect(url_for("characters"))

        if race not in RACES:
            flash("Invalid race selected.", "error")
            return redirect(url_for("characters"))

        if class_name not in CLASSES:
            flash("Invalid class selected.", "error")
            return redirect(url_for("characters"))

        base_attributes = {
            "strength": 5,
            "dexterity": 5,
            "constitution": 5,
            "intelligence": 5,
            "perception": 5,
            "charisma": 5
        }

        race_bonus = RACES[race]["bonuses"]
        class_bonus = CLASSES[class_name]["bonuses"]

        final_strength = base_attributes["strength"] + race_bonus["strength"] + class_bonus["strength"]
        final_dexterity = base_attributes["dexterity"] + race_bonus["dexterity"] + class_bonus["dexterity"]
        final_constitution = base_attributes["constitution"] + race_bonus["constitution"] + class_bonus["constitution"]
        final_intelligence = base_attributes["intelligence"] + race_bonus["intelligence"] + class_bonus["intelligence"]
        final_perception = base_attributes["perception"] + race_bonus["perception"] + class_bonus["perception"]
        final_charisma = base_attributes["charisma"] + race_bonus["charisma"] + class_bonus["charisma"]

        base_hp = 100
        base_mana = 25
        base_energy = 100

        final_hp = base_hp + race_bonus["hp_bonus"] + class_bonus["hp_bonus"]
        final_mana = base_mana + race_bonus["mana_bonus"] + class_bonus["mana_bonus"]
        final_energy = base_energy + race_bonus["energy_bonus"] + class_bonus["energy_bonus"]

        try:
            new_character = Character(
                user_id=user_id,
                name=name,
                race=race,
                class_name=class_name,
                background="New adventurer",
                description="A newly created hero",
                level=1,
                xp=0,
                gold=100,
                status="alive"
            )
            db.session.add(new_character)
            db.session.commit()

            new_attributes = CharacterAttribute(
                character_id=new_character.id,
                strength=final_strength,
                dexterity=final_dexterity,
                constitution=final_constitution,
                intelligence=final_intelligence,
                perception=final_perception,
                charisma=final_charisma
            )
            db.session.add(new_attributes)

            new_resources = CharacterResource(
                character_id=new_character.id,
                hp_current=final_hp,
                hp_max=final_hp,
                energy_current=final_energy,
                energy_max=final_energy,
                mana_current=final_mana,
                mana_max=final_mana,
                stamina_current=100,
                stamina_max=100
            )
            db.session.add(new_resources)
            db.session.commit()

            default_world = get_or_create_default_world_template()

            new_campaign = Campaign(
                character_id=new_character.id,
                world_template_id=default_world.id,
                title=f"{new_character.name}'s First Journey",
                status="active",
                current_ingame_day=1,
                current_ingame_time="morning"
            )
            db.session.add(new_campaign)
            db.session.commit()

            start_location = CampaignLocation(
                campaign_id=new_campaign.id,
                name="The Screeching Rat - Rented Room",
                location_type="inn_room",
                description="A tiny, cheap rented room with a straw bed and a wooden chest.",
                is_discovered=True,
                is_custom=False
            )
            db.session.add(start_location)
            db.session.flush()

            if hasattr(new_campaign, "current_location_id"):
                new_campaign.current_location_id = start_location.id

            start_quest = CampaignQuest(
                campaign_id=new_campaign.id,
                title="Get Ready for the Day",
                description="Equip your gear and leave your room.",
                status="active",
                reward_gold=0,
                reward_xp=0
            )
            db.session.add(start_quest)

            start_state = CampaignState(
                campaign_id=new_campaign.id,
                main_objective="Begin your journey in the capital.",
                current_scene_summary=(
                    "You wake up in a cheap rented room at the tavern called "
                    "'The Screeching Rat' after arriving late in the capital."
                ),
                world_state_summary=(
                    "The capital is a magically protected neutral city where open violence is impossible."
                ),
                last_session_summary=(
                    "You arrived late at night, rented the cheapest bed available, and fell asleep exhausted."
                ),
                notes_json="{}"
            )
            db.session.add(start_state)
            db.session.commit()

            rusty_sword = get_or_create_item_definition(
                name="Rusty Sword",
                item_type="weapon",
                rarity="common",
                description="A worn but usable sword.",
                value_base=15,
                weight=4,
                slot_type="weapon_main"
            )

            cloth_armor = get_or_create_item_definition(
                name="Cloth Armor",
                item_type="armor",
                rarity="common",
                description="Simple travel clothing with minimal protection.",
                value_base=10,
                weight=3,
                slot_type="armor_body"
            )

            torch_item = get_or_create_item_definition(
                name="Torch",
                item_type="utility",
                rarity="common",
                description="A simple torch for dark places.",
                value_base=2,
                weight=1,
                slot_type=None
            )

            bread_item = get_or_create_item_definition(
                name="Bread",
                item_type="consumable",
                rarity="common",
                description="A stale but edible loaf of bread.",
                value_base=1,
                weight=1,
                slot_type=None
            )

            db.session.add(CharacterInventory(
                character_id=new_character.id,
                item_definition_id=rusty_sword.id,
                quantity=1,
                is_equipped=True,
                equipped_slot="weapon_main"
            ))

            db.session.add(CharacterInventory(
                character_id=new_character.id,
                item_definition_id=cloth_armor.id,
                quantity=1,
                is_equipped=True,
                equipped_slot="armor_body"
            ))

            db.session.add(CharacterInventory(
                character_id=new_character.id,
                item_definition_id=torch_item.id,
                quantity=1,
                is_equipped=False
            ))

            db.session.add(CharacterInventory(
                character_id=new_character.id,
                item_definition_id=bread_item.id,
                quantity=1,
                is_equipped=False
            ))

            db.session.commit()

            session["active_character_id"] = new_character.id
            flash("Character created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Database error: {str(e)}", "error")

        return redirect(url_for("characters"))

    @app.route("/characters/select/<int:character_id>", methods=["POST"])
    def select_character(character_id):
        if not is_logged_in():
            return redirect(url_for("login"))

        user_id = session.get("user_id")
        character = get_character_by_id_for_user(character_id, user_id)

        if not character:
            flash("Character not found.", "error")
            return redirect(url_for("characters"))

        session["active_character_id"] = character.id
        flash(f"{character.name} is now your active character.", "success")
        return redirect(url_for("index"))

    @app.route("/characters/delete/<int:character_id>", methods=["POST"])
    def delete_character(character_id):
        if not is_logged_in():
            return redirect(url_for("login"))

        user_id = session.get("user_id")
        character = get_character_by_id_for_user(character_id, user_id)

        if not character:
            flash("Character not found.", "error")
            return redirect(url_for("characters"))

        try:
            if session.get("active_character_id") == character.id:
                session.pop("active_character_id", None)

            db.session.delete(character)
            db.session.commit()

            remaining_characters = get_user_characters(user_id)
            if remaining_characters:
                session["active_character_id"] = remaining_characters[0].id

            flash(f"{character.name} has been deleted.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Database error: {str(e)}", "error")

        return redirect(url_for("characters"))

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
                equipment_items, inventory_items = get_character_inventory_lists(character.id)

                serialized_characters.append({
                    "id": character.id,
                    "name": character.name,
                    "race": character.race,
                    "class_name": character.class_name,
                    "level": character.level,
                    "status": character.status,
                    "gold": character.gold,
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
                    "equipment": equipment_items,
                    "inventory": inventory_items
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

    @app.route("/api/game", methods=["POST"])
    def game():
        if not is_logged_in():
            return jsonify({"error": "Bitte zuerst einloggen."}), 401

        data = request.get_json() or {}
        user_input = (data.get("message") or "").strip()
        provider = (data.get("provider") or "deepseek").strip().lower()

        if not user_input:
            return jsonify({"error": "Keine Nachricht übergeben."}), 400

        availability = check_provider_availability(provider)
        if not availability["available"]:
            return jsonify({
                "error": f"Provider '{provider}' nicht verfügbar.",
                "details": availability["reason"]
            }), 503

        active_character = get_active_character()
        if not active_character:
            return jsonify({
                "error": "No active character found."
            }), 400

        campaign = get_active_campaign_for_character(active_character["id"])
        if not campaign:
            return jsonify({
                "error": "No active campaign found."
            }), 400

        recent_story_messages = get_recent_story_messages(campaign.id, limit=12)

        system_prompt = f"""
Du bist ein Spielleiter für ein Fantasy-Textabenteuer.

Aktiver Charakter:
- Name: {active_character['name']}
- Klasse: {active_character['class_name']}
- Rasse: {active_character['race']}
- Level: {active_character['level']}
- Aktueller Ort: {active_character['current_state']['location']}
- Aktuelle Tageszeit: {active_character['current_state']['time_of_day']}
- Aktive Quest: {active_character['current_state']['active_quest']}
- Questbeschreibung: {active_character['current_state']['active_quest_description']}
- Ausrüstung: {', '.join(active_character['equipment']) if active_character['equipment'] else 'Keine'}
- Inventar: {', '.join(active_character['inventory']) if active_character['inventory'] else 'Leer'}

Wichtige Regeln:
- Bleibe in der bestehenden Szene und setze die Geschichte fort.
- Starte NICHT erneut am Kampagnenanfang, wenn bereits Verlauf vorhanden ist.
- Wenn sich Ort, Zeit oder Quest ändern, benutze die verfügbaren Tools.
- Erfinde KEINE bereits ausgeführten Backend-Ergebnisse.
- Nutze Tools nur dann, wenn wirklich ein Zustandswechsel stattfindet.
- Antworte als Spielleiter.
- Gewalt nur moderat beschreiben.
WICHTIG:
- Nutze NUR die definierten Tools.
- Nutze KEINE XML, KEINE Tags, KEINE eigenen Formate.
- Verwende ausschließlich echtes Tool Calling.
- Erfinde keine Toolnamen.
- Wenn du ein Tool nutzt, dann IMMER über tool_calls.
-Wenn sich der Ort ändert, MUSST du update_location aufrufen.
If you generate tool calls:
- DO NOT write any text explanation before or after
- DO NOT use XML or DSML tags
- ONLY return valid tool_calls
"""

        messages = [{"role": "system", "content": system_prompt}]

        for msg in recent_story_messages:
            if msg.sender_type == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.sender_type in ("assistant", "ai", "gm"):
                messages.append({"role": "assistant", "content": msg.content})

        messages.append({"role": "user", "content": user_input})

        client = build_client(provider)
        cfg = get_provider_config(provider)

        try:
            user_message = StoryMessage(
                campaign_id=campaign.id,
                message_type="story",
                sender_type="user",
                content=user_input
            )
            db.session.add(user_message)
            db.session.commit()

            first_response = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                tools=STATE_TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=500,
            )

            first_message = first_response.choices[0].message
            final_response_text = first_message.content or ""

            def extract_fake_tool_calls(text):
                pattern = r'<\｜DSML\｜invoke name="(.*?)">(.*?)<\｜DSML\｜/invoke>'
                matches = re.findall(pattern, text, re.DOTALL)

                parsed_tool_calls = []

                for name, inner in matches:
                    params = {}

                    param_pattern = r'<\｜DSML\｜parameter name="(.*?)"(?: string="true")?>(.*?)</\｜DSML\｜parameter>'
                    param_matches = re.findall(param_pattern, inner, re.DOTALL)

                    for key, value in param_matches:
                        params[key] = value.strip()

                    parsed_tool_calls.append({
                        "name": name.strip(),
                        "arguments": params
                    })

                return parsed_tool_calls

            tool_calls = first_message.tool_calls or []

            if not tool_calls and first_message.content:
                fake_calls = extract_fake_tool_calls(first_message.content)
                if fake_calls:
                    tool_calls = fake_calls

            if tool_calls:
                assistant_tool_message = {
                    "role": "assistant",
                    "content": first_message.content or "",
                    "tool_calls": []
                }

                tool_result_messages = []

                for index, tool_call in enumerate(tool_calls):
                    if hasattr(tool_call, "function"):
                        tool_name = tool_call.function.name
                        tool_call_id = tool_call.id

                        try:
                            tool_args = json.loads(tool_call.function.arguments or "{}")
                        except json.JSONDecodeError:
                            tool_args = {}

                        raw_arguments = tool_call.function.arguments or "{}"
                    else:
                        tool_name = tool_call["name"]
                        tool_args = tool_call["arguments"]
                        tool_call_id = f"fake_tool_call_{index}"
                        raw_arguments = json.dumps(tool_args, ensure_ascii=False)

                    normalized_tool_name = tool_name
                    normalized_tool_args = dict(tool_args)

                    if normalized_tool_name == "change_location":
                        normalized_tool_name = "update_location"

                    if normalized_tool_name == "update_active_quest":
                        normalized_tool_name = "set_active_quest"

                    if normalized_tool_name == "update_location":
                        if "location" in normalized_tool_args and "location_name" not in normalized_tool_args:
                            normalized_tool_args["location_name"] = normalized_tool_args["location"]

                    if normalized_tool_name == "set_active_quest":
                        if "quest_title" in normalized_tool_args and "title" not in normalized_tool_args:
                            normalized_tool_args["title"] = normalized_tool_args["quest_title"]

                        if "quest_description" in normalized_tool_args and "description" not in normalized_tool_args:
                            normalized_tool_args["description"] = normalized_tool_args["quest_description"]

                    tool_result = execute_state_tool(
                        campaign_id=campaign.id,
                        tool_name=normalized_tool_name,
                        arguments=normalized_tool_args
                    )

                    assistant_tool_message["tool_calls"].append({
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": raw_arguments
                        }
                    })

                    tool_result_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(tool_result, ensure_ascii=False)
                    })

                second_messages = messages + [assistant_tool_message] + tool_result_messages

                second_response = client.chat.completions.create(
                    model=cfg["model"],
                    messages=second_messages,
                    temperature=0.7,
                    max_tokens=500,
                )

                final_response_text = second_response.choices[0].message.content or final_response_text

            assistant_message = StoryMessage(
                campaign_id=campaign.id,
                message_type="story",
                sender_type="assistant",
                content=final_response_text
            )
            db.session.add(assistant_message)
            db.session.commit()

            updated_character = get_active_character()

            return jsonify({
                "provider": provider,
                "response": final_response_text,
                "character": updated_character
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                "error": "API-Fehler",
                "details": str(e)
            }), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)