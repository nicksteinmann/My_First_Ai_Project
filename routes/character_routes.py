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

from services.serializers import get_character_inventory_data
from services.currency.service import add_currency
from services.inventory.service import add_inventory_item


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
                "inventory": inventory_data["inventory"],
                "inventory_summary": inventory_data["inventory_summary"],
                "inventory_total_weight": inventory_data["total_weight"],
                "inventory_containers": inventory_data["containers"],
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

            starter_items = [
                {
                    "item": {
                        "item_id": "starter_rusty_sword",
                        "name": "Rusty Sword",
                        "description": "A worn but usable sword.",
                        "size": "medium",
                        "volume": 2.0,
                        "weight": 4.0,
                        "stackable": False,
                        "quantity": 1,
                        "hand_usage": "one_handed",
                        "item_type": "weapon",
                    },
                    "quantity": 1,
                    "container_id": "base_inventory",
                },
                {
                    "item": {
                        "item_id": "starter_cloth_armor",
                        "name": "Cloth Armor",
                        "description": "Simple travel clothing with minimal protection.",
                        "size": "medium",
                        "volume": 3.0,
                        "weight": 3.0,
                        "stackable": False,
                        "quantity": 1,
                        "hand_usage": "none",
                        "item_type": "armor",
                    },
                    "quantity": 1,
                    "container_id": "base_inventory",
                },
                {
                    "item": {
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
                    "quantity": 1,
                    "container_id": "base_inventory",
                },
                {
                    "item": {
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
                    "quantity": 1,
                    "container_id": "base_inventory",
                },
            ]

            for starter_item in starter_items:
                result = add_inventory_item(
                    character_id=new_character.id,
                    item=starter_item["item"],
                    quantity=starter_item["quantity"],
                    container_id=starter_item["container_id"],
                )

                if not result.success:
                    raise ValueError(result.message)

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