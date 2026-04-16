from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, UserProfile, Character, CharacterAttribute, CharacterResource
from services.llm_service import ask_llm, check_provider_availability
from data.character_presets import RACES, CLASSES


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

    def serialize_character(character):
        attributes = character.attributes
        resources = character.resources

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
                "location": "Ravenhold",
                "time_of_day": "Evening",
                "active_quest": "No active quest"
            },
            "equipment": [
                "Starter Weapon",
                "Basic Armor"
            ],
            "inventory": [
                "Torch",
                "Bread"
            ]
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

        return render_template(
        "index.html",
            page_title="Home",
            logged_in=True,
            active_character=active_character,
            username=current_user.username
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
                "location": "Ravenhold",
                "time": "Evening",
                "quest": "No active quest",
                "completed_quests": 0,
                "campaigns": 0,
                "equipment": ["Starter Weapon", "Basic Armor"],
                "inventory": ["Torch", "Bread"],
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

        system_prompt = f"""
Du bist ein Spielleiter für ein Fantasy-Textabenteuer.

Aktiver Charakter:
- Name: {active_character['name']}
- Klasse: {active_character['class_name']}
- Rasse: {active_character['race']}
- Level: {active_character['level']}
- Aktueller Ort: {active_character['current_state']['location']}
- Aktive Quest: {active_character['current_state']['active_quest']}

Antworte als Spielleiter.
Bleibe in der Spielwelt.
Führe die Szene sinnvoll weiter.
Gewalt nur moderat beschreiben.
"""

        try:
            response = ask_llm(
                prompt=user_input,
                provider=provider,
                system_prompt=system_prompt
            )
            return jsonify({
                "provider": provider,
                "response": response
            })
        except Exception as e:
            return jsonify({
                "error": "API-Fehler",
                "details": str(e)
            }), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)