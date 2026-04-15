from flask import Flask, request, jsonify, render_template
from models import db
from services.llm_service import ask_llm, check_provider_availability


def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///AI_Pen_and_Paper.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.route("/")
    def index():
        return render_template("index.html")

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

        try:
            response = ask_llm(
                prompt=user_input,
                provider=provider,
                system_prompt="Du bist ein Spielleiter für ein Fantasy-Textabenteuer."
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
