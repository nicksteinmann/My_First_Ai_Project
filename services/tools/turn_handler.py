import json

from .tool_handler import debug_tool_event, extract_fake_tool_calls


def _contains_fake_tool_syntax(text):
    if not text:
        return False

    if extract_fake_tool_calls(text):
        return True

    lowered = text.lower()
    return (
        "dsml" in lowered
        or "function_call" in lowered
        or "function_calls" in lowered
        or "invoke name=" in lowered
        or "parameter name=" in lowered
    )


def run_game_turn(
    client,
    model,
    messages,
    campaign_id,
    active_character,

    state_tool_definitions,
    inventory_tool_definitions,
    currency_tool_definitions,
    equipment_tool_definitions,
    resource_tool_definitions,
    status_effect_tool_definitions,
    leveling_tool_definitions,
    attribute_tool_definitions,

    execute_state_tool,
    execute_inventory_tool,
    execute_currency_tool,
    execute_equipment_tool,
    execute_resource_tool,
    execute_status_effect_tool,
    execute_leveling_tool,
    execute_attribute_tool,

    resolve_tool_calls,
    parse_tool_call_payload,
    normalize_tool_call,
    execute_normalized_tool,

    max_tool_rounds=5,
    turn_id=None,
):
    """
    Führt einen kompletten LLM-Turn inkl. Tool-Loop aus.
    """

    all_tool_definitions = (
        state_tool_definitions
        + inventory_tool_definitions
        + currency_tool_definitions
        + equipment_tool_definitions
        + resource_tool_definitions
        + status_effect_tool_definitions
        + leveling_tool_definitions
        + attribute_tool_definitions
    )
    debug_tool_event("game turn started", {
        "turn_id": turn_id,
        "campaign_id": campaign_id,
        "character_id": active_character["id"],
        "tool_count": len(all_tool_definitions),
        "max_tool_rounds": max_tool_rounds,
    })

    for round_index in range(max_tool_rounds):
        debug_tool_event("tool round started", {
            "turn_id": turn_id,
            "round_index": round_index + 1,
        })

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=all_tool_definitions,
        )

        message = response.choices[0].message

        # -------------------------
        # 1. Tool Calls erkennen
        # -------------------------
        tool_calls = resolve_tool_calls(
            message,
            state_tool_definitions,
            inventory_tool_definitions,
            currency_tool_definitions,
            equipment_tool_definitions,
            resource_tool_definitions,
            status_effect_tool_definitions,
            leveling_tool_definitions,
            attribute_tool_definitions,
        )

        # -------------------------
        # 2. Kein Toolcall → fertig
        # -------------------------
        if not tool_calls:
            content = message.content or ""

            # 🔴 Fix für leere Antworten
            if not content.strip():
                return "Something happens, but you can't quite make sense of it."

            return content

        # -------------------------
        # 3. Toolcalls verarbeiten
        # -------------------------
        messages.append(message)

        tool_result_messages = []

        for index, tool_call in enumerate(tool_calls):

            tool_name, tool_args, tool_call_id, raw_arguments = parse_tool_call_payload(
                tool_call,
                index=index,
            )

            normalized_tool_name, normalized_tool_args = normalize_tool_call(
                tool_name,
                tool_args,
                active_character,
            )

            debug_tool_event("executing tool", {
                "turn_id": turn_id,
                "round_index": round_index + 1,
                "tool_name": normalized_tool_name,
                "arguments": normalized_tool_args,
            })

            tool_result = execute_normalized_tool(
                normalized_tool_name=normalized_tool_name,
                normalized_tool_args=normalized_tool_args,
                campaign_id=campaign_id,
                character_id=active_character["id"],
                state_tool_definitions=state_tool_definitions,
                inventory_tool_definitions=inventory_tool_definitions,
                currency_tool_definitions=currency_tool_definitions,
                equipment_tool_definitions=equipment_tool_definitions,
                resource_tool_definitions=resource_tool_definitions,
                status_effect_tool_definitions=status_effect_tool_definitions,
                leveling_tool_definitions=leveling_tool_definitions,
                attribute_tool_definitions=attribute_tool_definitions,
                execute_state_tool=execute_state_tool,
                execute_inventory_tool=execute_inventory_tool,
                execute_currency_tool=execute_currency_tool,
                execute_equipment_tool=execute_equipment_tool,
                execute_resource_tool=execute_resource_tool,
                execute_status_effect_tool=execute_status_effect_tool,
                execute_leveling_tool=execute_leveling_tool,
                execute_attribute_tool=execute_attribute_tool,
            )

            if isinstance(tool_result, dict) and turn_id:
                tool_result.setdefault("turn_id", turn_id)

            debug_tool_event("tool result", {
                "turn_id": turn_id,
                "round_index": round_index + 1,
                "tool_name": normalized_tool_name,
                "result": tool_result,
            })

            tool_result_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        # Tool Ergebnisse zurück ins Gespräch geben
        messages.extend(tool_result_messages)

    # -------------------------
    # 4. Falls max Runden erreicht:
    #    Tool-Ausführung ist schon passiert, also erzwinge eine finale
    #    Narrative ohne weitere Tools statt eines sichtbaren Technik-Fallbacks.
    # -------------------------
    messages.append({
        "role": "system",
        "content": (
            "Tool execution has ended for this turn. Do not call any more tools. "
            "Summarize only the actions that were already completed by tool results. "
            "Continue the scene in the user's language using plain narrative text only. "
            "Never output DSML, XML, JSON, tool syntax, function_calls, invoke tags, or parameter tags."
        )
    })

    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )

    content = response.choices[0].message.content or ""
    if content.strip():
        if _contains_fake_tool_syntax(content):
            debug_tool_event("final narration contained fake tool syntax", {
                "turn_id": turn_id,
                "content": content,
            })
            return "Die ausgeführten Aktionen sind verarbeitet. Was tust du als Nächstes?"

        return content

    return "The actions are resolved, but the narration could not be generated."
