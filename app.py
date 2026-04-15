from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from models import db
from services.llm_service import ask_llm, check_provider_availability


def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///AI_Pen_and_Paper.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "dev-secret-key-change-later"

    db.init_app(app)

    with app.app_context():
        db.create_all()

    def is_logged_in():
        return "user_id" in session

    def get_active_character():
        """
        Platzhalterdaten.
        Später durch echte DB-Abfrage ersetzen.
        """
        if not is_logged_in():
            return None

        return {
            "id": 1,
            "name": "Wolfram der Türbrecher",
            "race": "Mensch",
            "class_name": "Ritter",
            "level": 7,
            "status": "alive",
            "portrait": "👤",
            "stats": {
                "hp": 120,
                "hp_max": 140,
                "mana": 30,
                "mana_max": 50,
                "energy": 80,
                "energy_max": 100,
                "gold": 245
            },
            "skills": [
                {"icon": "⚔️", "name": "Sword", "level": 7},
                {"icon": "🛡️", "name": "Shield", "level": 6},
                {"icon": "🎯", "name": "Bow", "level": 2},
                {"icon": "🗝️", "name": "Lockpick", "level": 1},
            ],
            "current_state": {
                "location": "Ravenhold",
                "time_of_day": "Evening",
                "active_quest": "Find the missing blacksmith"
            },
            "equipment": [
                "Iron Sword",
                "Knight Shield",
                "Steel Chestplate"
            ],
            "inventory": [
                "Health Potion",
                "Torch",
                "Rope",
                "Old Key"
            ]
        }

    @app.route("/")
    def index():
        if not is_logged_in():
            return render_template("index.html", page_title="Home", logged_in=False)

        active_character = get_active_character()
        return render_template(
            "index.html",
            page_title="Home",
            logged_in=True,
            active_character=active_character,
            username=session.get("username")
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()

            if username:
                session["user_id"] = 1
                session["username"] = username
                return redirect(url_for("index"))

        return render_template("login.html", page_title="Login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            return redirect(url_for("login"))

        return render_template("register.html", page_title="Register")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/characters")
    def characters():
        if not is_logged_in():
            return redirect(url_for("login"))

        character_list = [
            {
                "id": 1,
                "name": "Wolfram der Türbrecher",
                "race": "Mensch",
                "class_name": "Ritter",
                "level": 7,
                "status": "alive",
                "hp": 120,
                "energy": 80
            },
            {
                "id": 2,
                "name": "Theodor von Sturmbart",
                "race": "Zwerg",
                "class_name": "Krieger",
                "level": 4,
                "status": "retired",
                "hp": 95,
                "energy": 60
            }
        ]

        return render_template(
            "characters.html",
            page_title="My Characters",
            characters=character_list
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
        users = [
            {
                "username": "Nick",
                "characters": [
                    {"name": "Wolfram der Türbrecher", "level": 7, "status": "alive"},
                    {"name": "Theodor von Sturmbart", "level": 4, "status": "retired"},
                ]
            },
            {
                "username": "TestUser",
                "characters": [
                    {"name": "Elaena", "level": 5, "status": "alive"},
                ]
            }
        ]

        return render_template(
            "community.html",
            page_title="Community",
            users=users
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