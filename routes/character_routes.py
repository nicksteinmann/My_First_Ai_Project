"""Character creation, selection, and character overview routes."""

import json

from flask import render_template, redirect, url_for, session, request, flash

from data.character_presets import RACES, CLASSES
from models import (
    db,
    Character,
    CharacterAttribute,
    CharacterResource,
    Campaign,
    CampaignState,
    CampaignLocation,
    CampaignQuest,
)

from services.attributes import serialize_attributes
from services.serializers.character_serializer import get_character_inventory_data, get_character_status_effects
from services.currency.service import add_currency
from services.leveling import serialize_level_progression
from services.skills import serialize_character_skills


def register_character_routes(
    app,
    is_logged_in,
    get_user_characters,
    get_character_by_id_for_user,
    get_active_campaign_for_character,
    get_current_campaign_location,
    get_active_campaign_quest,
    get_or_create_default_world_template,
):
    """Register character management routes on the Flask app."""

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
            inventory_data = get_character_inventory_data(character.id)
            status_effects = get_character_status_effects(character.id)
            level_progression = serialize_level_progression(character)
            serialized_attributes = serialize_attributes(attributes)
            serialized_skills = serialize_character_skills(character)

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
                "xp": character.xp,
                "level_progression": level_progression,
                "status": character.status,
                "status_effects": status_effects,
                "currency": character.currency_json,
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
                "equipment": inventory_data["equipment"],
                "equipment_slots": inventory_data["equipment_slots"],
                "equipment_summary": inventory_data["equipment_summary"],
                "inventory": inventory_data["inventory"],
                "inventory_summary": inventory_data["inventory_summary"],
                "inventory_total_weight": inventory_data["total_weight"],
                "inventory_containers": inventory_data["containers"],
                "attributes": serialized_attributes,
                "skills": serialized_skills,
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
                status="alive"
            )
            db.session.add(new_character)
            db.session.commit()

            add_currency(
                character_id=new_character.id,
                gold=0,
                silver=1,
                copper=20
            )

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
                description=(
                    "A tiny, cheap rented room with a straw bed, a chair, and your few belongings."
                ),
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
                description="Check your gear and prepare to leave your rented room.",
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
                    "'The Screeching Rat' after arriving late in the capital. "
                    "You are dressed in simple travel clothes with two belt pouches, a backpack, "
                    "and a wooden club in hand."
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

            starter_jacket = {
                "item_id": "starter_simple_jacket",
                "name": "Simple Jacket",
                "description": "A plain travel jacket with one small pocket.",
                "size": "small",
                "volume": 1.5,
                "weight": 0.8,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "clothing",
                "container_profile": {
                    "name": "Jacket",
                    "max_volume": 2.0,
                    "max_item_size": "small",
                },
                "equipped_slots": ["torso_clothing"],
            }
            starter_trousers = {
                "item_id": "starter_travel_trousers",
                "name": "Travel Trousers",
                "description": "Simple trousers with small pockets.",
                "size": "small",
                "volume": 1.0,
                "weight": 0.8,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "pants",
                "container_profile": {
                    "name": "Trousers",
                    "max_volume": 1.0,
                    "max_item_size": "small",
                },
                "equipped_slots": ["legs_clothing"],
            }
            starter_shoes = {
                "item_id": "starter_simple_shoes",
                "name": "Simple Shoes",
                "description": "Worn but serviceable shoes.",
                "size": "small",
                "volume": 1.0,
                "weight": 1.0,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "shoes",
                "equipped_slots": ["feet"],
            }
            starter_belt = {
                "item_id": "starter_simple_belt",
                "name": "Simple Belt",
                "description": "A simple belt that can hold two attachments.",
                "size": "small",
                "volume": 0.5,
                "weight": 0.4,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "belt",
                "equipped_slots": ["belt"],
            }
            starter_belt_pouch = {
                "item_id": "starter_belt_pouch",
                "name": "Small Belt Pouch",
                "description": "A small pouch tied to your belt.",
                "size": "small",
                "volume": 0.5,
                "weight": 0.3,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "pouch",
                "container_profile": {
                    "name": "Belt 1",
                    "max_volume": 5.0,
                    "max_item_size": "small",
                },
                "equipped_slots": ["belt_slot_1"],
            }
            starter_second_belt_pouch = {
                "item_id": "starter_second_belt_pouch",
                "name": "Small Belt Pouch",
                "description": "A second small pouch tied to your belt.",
                "size": "small",
                "volume": 0.5,
                "weight": 0.3,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "pouch",
                "container_profile": {
                    "name": "Belt 2",
                    "max_volume": 5.0,
                    "max_item_size": "small",
                },
                "equipped_slots": ["belt_slot_2"],
            }
            starter_club = {
                "item_id": "starter_wooden_club",
                "name": "Wooden Club",
                "description": "A rough wooden club, simple but useful.",
                "size": "medium",
                "volume": 2.0,
                "weight": 3.0,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "one_handed",
                "item_type": "weapon",
                "equipped_slots": ["main_hand"],
            }
            starter_backpack = {
                "item_id": "starter_travel_backpack",
                "name": "Backpack",
                "description": "A worn backpack with a few supplies packed inside.",
                "size": "medium",
                "volume": 3.0,
                "weight": 1.5,
                "stackable": False,
                "quantity": 1,
                "hand_usage": "none",
                "item_type": "backpack",
                "container_profile": {
                    "name": "Backpack",
                    "max_volume": 10.0,
                    "max_item_size": "medium",
                },
                "equipped_slots": ["backpack"],
                "stored_items": [
                    {
                        "item_id": "starter_torch",
                        "name": "Torch",
                        "description": "A simple torch for dark places.",
                        "size": "small",
                        "volume": 1.0,
                        "weight": 1.0,
                        "stackable": False,
                        "quantity": 1,
                        "hand_usage": "one_handed",
                        "item_type": "utility",
                    },
                    {
                        "item_id": "starter_bread",
                        "name": "Bread",
                        "description": "A stale but edible loaf of bread.",
                        "size": "small",
                        "volume": 0.5,
                        "weight": 0.5,
                        "stackable": True,
                        "quantity": 1,
                        "hand_usage": "none",
                        "item_type": "consumable",
                    },
                    {
                        "item_id": "starter_full_waterskin",
                        "name": "Full Waterskin",
                        "description": "A simple waterskin filled with clean water.",
                        "size": "small",
                        "volume": 1.0,
                        "weight": 1.0,
                        "stackable": False,
                        "quantity": 1,
                        "hand_usage": "none",
                        "item_type": "consumable",
                    },
                ],
            }

            new_character.inventory_json = json.dumps({
                "inventory": {
                    "containers": [
                        {
                            "container_id": "base_inventory",
                            "name": "No Carried Container",
                            "source": "base",
                            "source_item_id": None,
                            "max_volume": 0.0,
                            "max_item_size": "tiny",
                            "items": [],
                        },
                        {
                            "container_id": "equipment_starter_simple_jacket",
                            "name": "Jacket",
                            "source": "equipment",
                            "source_item_id": "starter_simple_jacket",
                            "max_volume": 2.0,
                            "max_item_size": "small",
                            "items": [],
                        },
                        {
                            "container_id": "equipment_starter_travel_trousers",
                            "name": "Trousers",
                            "source": "equipment",
                            "source_item_id": "starter_travel_trousers",
                            "max_volume": 1.0,
                            "max_item_size": "small",
                            "items": [],
                        },
                        {
                            "container_id": "equipment_starter_belt_pouch",
                            "name": "Belt 1",
                            "source": "equipment",
                            "source_item_id": "starter_belt_pouch",
                            "max_volume": 5.0,
                            "max_item_size": "small",
                            "items": [],
                        },
                        {
                            "container_id": "equipment_starter_second_belt_pouch",
                            "name": "Belt 2",
                            "source": "equipment",
                            "source_item_id": "starter_second_belt_pouch",
                            "max_volume": 5.0,
                            "max_item_size": "small",
                            "items": [],
                        },
                        {
                            "container_id": "equipment_starter_travel_backpack",
                            "name": "Backpack",
                            "source": "equipment",
                            "source_item_id": "starter_travel_backpack",
                            "max_volume": 10.0,
                            "max_item_size": "medium",
                            "items": starter_backpack["stored_items"],
                        },
                    ]
                },
                "equipment": {
                    "slots": {
                        "head": None,
                        "torso_clothing": starter_jacket,
                        "torso_armor": None,
                        "legs_clothing": starter_trousers,
                        "legs_armor": None,
                        "feet": starter_shoes,
                        "gloves": None,
                        "belt": starter_belt,
                        "belt_slot_1": starter_belt_pouch,
                        "belt_slot_2": starter_second_belt_pouch,
                        "backpack": starter_backpack,
                        "cloak": None,
                        "ring_left": None,
                        "ring_right": None,
                        "main_hand": starter_club,
                        "off_hand": None,
                    }
                },
            }, ensure_ascii=False)
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
