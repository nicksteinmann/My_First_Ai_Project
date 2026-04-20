import json


def run_game_turn(
    client,
    model,
    messages,
    campaign_id,
    active_character,

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

    max_tool_rounds=5,
):
    """
    Führt einen kompletten LLM-Turn inkl. Tool-Loop aus.
    """

    all_tool_definitions = (
        state_tool_definitions
        + inventory_tool_definitions
        + currency_tool_definitions
    )

    final_text = None

    for round_index in range(max_tool_rounds):

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

            tool_result = execute_normalized_tool(
                normalized_tool_name=normalized_tool_name,
                normalized_tool_args=normalized_tool_args,
                campaign_id=campaign_id,
                character_id=active_character["id"],
                state_tool_definitions=state_tool_definitions,
                inventory_tool_definitions=inventory_tool_definitions,
                currency_tool_definitions=currency_tool_definitions,
                execute_state_tool=execute_state_tool,
                execute_inventory_tool=execute_inventory_tool,
                execute_currency_tool=execute_currency_tool,
            )

            tool_result_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        # Tool Ergebnisse zurück ins Gespräch geben
        messages.extend(tool_result_messages)

    # -------------------------
    # 4. Falls max Runden erreicht
    # -------------------------
    return "The situation becomes unclear after several actions."