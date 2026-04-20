from flask import request, jsonify

from models import db, StoryMessage
from services.llm_service import build_client, get_provider_config, check_provider_availability
from services.prompt_builder import build_game_system_prompt


def register_game_routes(
    app,
    is_logged_in,
    get_active_character,
    get_active_campaign_for_character,
    get_recent_story_messages,

    state_tool_definitions,
    inventory_tool_definitions,
    currency_tool_definitions,

    execute_state_tool,
    execute_inventory_tool,
    execute_currency_tool,

    resolve_tool_calls,
    parse_tool_call_payload,
    normalize_tool_call,
    execute_normalized_tool,
    run_game_turn,
):
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

        system_prompt = build_game_system_prompt(active_character)

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

            final_text = run_game_turn(
                client=client,
                model=cfg["model"],
                messages=messages,
                campaign_id=campaign.id,
                active_character=active_character,

                state_tool_definitions=state_tool_definitions,
                inventory_tool_definitions=inventory_tool_definitions,
                currency_tool_definitions=currency_tool_definitions,

                execute_state_tool=execute_state_tool,
                execute_inventory_tool=execute_inventory_tool,
                execute_currency_tool=execute_currency_tool,

                resolve_tool_calls=resolve_tool_calls,
                parse_tool_call_payload=parse_tool_call_payload,
                normalize_tool_call=normalize_tool_call,
                execute_normalized_tool=execute_normalized_tool,
            )

            assistant_message = StoryMessage(
                campaign_id=campaign.id,
                message_type="story",
                sender_type="assistant",
                content=final_text
            )
            db.session.add(assistant_message)
            db.session.commit()

            updated_character = get_active_character()

            return jsonify({
                "provider": provider,
                "response": final_text,
                "character": updated_character
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                "error": "API-Fehler",
                "details": str(e)
            }), 500