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
from services.serializers.character_serializer import (
    get_character_inventory_data,
    get_character_status_effects,
    get_visible_campaign_quest_summary,
)
from services.currency.service import add_currency
from services.leveling import serialize_level_progression
from services.skills import serialize_character_skills
from services.world_data import build_location_context_from_world_location, find_world_location


RACE_START_LOCATIONS = {
    "Human": {
        "world_location_id": "crownford",
        "location_name": "Crownford - Rented Room",
        "location_type": "inn_room",
        "description": "A tiny rented room in Crownford, close to the busy roads of the human heartland.",
        "main_objective": "Begin your journey in Crownford.",
        "scene_summary": (
            "You wake up in a cheap rented room in Crownford after arriving late the night before. "
            "You are dressed in simple travel clothes with two belt pouches, a backpack, "
            "and a wooden club in hand."
        ),
        "world_summary": (
            "Crownford is the human capital and a strong starting point for roads, markets, "
            "simple work, and safer early quests."
        ),
    },
    "Elf": {
        "world_location_id": "lythariel",
        "location_name": "Lythariel - Guest Bower",
        "location_type": "guest_room",
        "description": "A quiet guest bower woven into the living branches of Lythariel.",
        "main_objective": "Begin your journey in Lythariel.",
        "scene_summary": (
            "You wake in a quiet guest bower in Lythariel, surrounded by silver leaves, "
            "soft morning light, and the sound of hidden forest paths beyond the city."
        ),
        "world_summary": (
            "Lythariel is the elven capital in Silverwood, where forest paths, old magic, "
            "and guarded glades shape early travel."
        ),
    },
    "Dwarf": {
        "world_location_id": "stonewatch",
        "location_name": "Stonewatch - Travelers' Bunk",
        "location_type": "bunk_room",
        "description": "A sturdy stone bunk room inside Stonewatch, warm with forge heat and mountain air.",
        "main_objective": "Begin your journey in Stonewatch.",
        "scene_summary": (
            "You wake in a travelers' bunk in Stonewatch, where stone corridors echo with boots, "
            "hammers, and the low rumble of the mountain roads."
        ),
        "world_summary": (
            "Stonewatch is the dwarven capital in the Stoneward Peaks, built around fortress roads, "
            "craft halls, and slower mountain travel."
        ),
    },
    "Orc": {
        "world_location_id": "kragmor",
        "location_name": "Kragmor - Clan Rest Hall",
        "location_type": "rest_hall",
        "description": "A rough rest hall in Kragmor, with hides, smoke, and heavy wooden beams.",
        "main_objective": "Begin your journey in Kragmor.",
        "scene_summary": (
            "You wake in a rough rest hall in Kragmor, the air thick with smoke, iron, "
            "and the distant noise of clan life in the Grimscar Wastes."
        ),
        "world_summary": (
            "Kragmor is the orc capital in the Grimscar Wastes, surrounded by hard country, "
            "strongholds, clan politics, and dangerous open routes."
        ),
    },
    "Goblin": {
        "world_location_id": "jagged_harbor",
        "location_name": "Jagged Harbor - Dockside Loft",
        "location_type": "dockside_room",
        "description": "A cramped dockside loft above cranes, ropes, scrap stalls, and crooked piers.",
        "main_objective": "Begin your journey in Jagged Harbor.",
        "scene_summary": (
            "You wake in a cramped dockside loft in Jagged Harbor, with gull cries, creaking cranes, "
            "and the smell of salt and machine oil below."
        ),
        "world_summary": (
            "Jagged Harbor is the goblin capital port of the Shard Isles. Leaving the islands "
            "requires a valid crossing method such as ship, airship, flight, or teleportation."
        ),
    },
}


def _get_race_start_location(race: str) -> dict:
    return RACE_START_LOCATIONS.get(race, RACE_START_LOCATIONS["Human"])


def register_character_routes(
    app,
    is_logged_in,
    get_user_characters,
    get_character_by_id_for_user,
    get_active_campaign_for_character,
    get_current_campaign_location,
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
                "quest": get_visible_campaign_quest_summary(campaign),
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

            race_start = _get_race_start_location(race)
            race_start_world_location = find_world_location(race_start["world_location_id"])
            race_start_context = build_location_context_from_world_location(
                race_start_world_location,
                source="starter_location",
            )
            start_location = CampaignLocation(
                campaign_id=new_campaign.id,
                name=race_start["location_name"],
                location_type=race_start["location_type"],
                description=race_start["description"],
                is_discovered=True,
                is_custom=False,
                **race_start_context,
            )
            db.session.add(start_location)
            db.session.flush()

            if hasattr(new_campaign, "current_location_id"):
                new_campaign.current_location_id = start_location.id

            start_state = CampaignState(
                campaign_id=new_campaign.id,
                main_objective=race_start["main_objective"],
                current_scene_summary=race_start["scene_summary"],
                world_state_summary=race_start["world_summary"],
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
