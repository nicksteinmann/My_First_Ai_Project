"""Gameplay API routes.

This module owns the /api/game request boundary: it validates the session,
builds prompt context, persists story messages, runs the bounded tool loop, and
returns the refreshed serialized character state to the browser.
"""

from uuid import uuid4

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
    equipment_tool_definitions,
    resource_tool_definitions,
    status_effect_tool_definitions,
    leveling_tool_definitions,
    attribute_tool_definitions,
    skill_tool_definitions,

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
):
    """Register gameplay JSON endpoints on the Flask app."""

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
        turn_id = uuid4().hex

        system_prompt = build_game_system_prompt(active_character)

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "system",
                "content": (
                    f"Current backend turn id: {turn_id}. "
                    "Only call tools for state changes caused by the latest user message in this current turn."
                )
            }
        ]

        if recent_story_messages:
            messages.append({
                "role": "system",
                "content": (
                    "The following story history is context only. "
                    "Do not execute tools for events, rewards, payments, damage, healing, "
                    "inventory changes, equipment changes, status effects, location changes or quest changes "
                    "that already appear in this history unless the latest user message clearly repeats, continues, "
                    "or intentionally redoes a similar action in the present turn. "
                    "If the user says things like 'again', 'continue', 'weiter', 'nochmal', or repeats a training, travel, "
                    "rest, trade, or combat action, treat that as a new action and call tools again for the new turn only. "
                    "Only avoid re-applying the exact same past event just because it appears in history."
                )
            })

        for msg in recent_story_messages:
            if msg.sender_type == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.sender_type in ("assistant", "ai", "gm"):
                messages.append({
                    "role": "assistant",
                    "content": msg.content
                })

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
                equipment_tool_definitions=equipment_tool_definitions,
                resource_tool_definitions=resource_tool_definitions,
                status_effect_tool_definitions=status_effect_tool_definitions,
                leveling_tool_definitions=leveling_tool_definitions,
                attribute_tool_definitions=attribute_tool_definitions,
                skill_tool_definitions=skill_tool_definitions,

                execute_state_tool=execute_state_tool,
                execute_inventory_tool=execute_inventory_tool,
                execute_currency_tool=execute_currency_tool,
                execute_equipment_tool=execute_equipment_tool,
                execute_resource_tool=execute_resource_tool,
                execute_status_effect_tool=execute_status_effect_tool,
                execute_leveling_tool=execute_leveling_tool,
                execute_attribute_tool=execute_attribute_tool,
                execute_skill_tool=execute_skill_tool,

                resolve_tool_calls=resolve_tool_calls,
                parse_tool_call_payload=parse_tool_call_payload,
                normalize_tool_call=normalize_tool_call,
                execute_normalized_tool=execute_normalized_tool,
                turn_id=turn_id,
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
