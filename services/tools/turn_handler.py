"""Bounded LLM turn loop for gameplay.

Each user action can trigger a limited number of backend tool calls. Tool
results are appended back into the message list so the model can continue
planning within the same turn, and a final narration is requested when the
tool budget is exhausted.
"""

import json
import re

from .tool_handler import debug_tool_event, extract_fake_tool_calls


STATE_CLAIM_PATTERNS = [
    (
        "quest_acceptance",
        re.compile(
            r"\b(quest|auftrag|aufgabe|mission|botengang|job)\b.{0,60}\b(angenommen|akzeptiert|accepted|created|angelegt)\b"
            r"|\b(angenommen|akzeptiert)\b.{0,30}\b(quest|auftrag|aufgabe|mission|botengang|job)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quest_completion",
        re.compile(
            r"\b(quest|auftrag|aufgabe|mission|botengang|job)\b.{0,80}\b(abgeschlossen|erledigt|abgegeben|completed|turned in|turned_in)\b"
            r"|\b(abgeschlossen|erledigt|abgegeben)\b.{0,30}\b(quest|auftrag|aufgabe|mission|botengang|job)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reward_claim",
        re.compile(
            r"\b(belohnung|reward)\b.{0,80}\b(erhalten|bekommen|ausgezahlt|angenommen|abgeholt|claimed|received|paid)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "xp_gain",
        re.compile(
            r"\+\s*\d+\s*(xp|erfahrung|erfahrungspunkte)"
            r"|\b(erhaeltst|erhältst|bekommst|kriegst|receive|gain|gained)\b.{0,80}\b(xp|erfahrung|erfahrungspunkte)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "currency_gain",
        re.compile(
            r"\+\s*\d+\s*(gold|silber|kupfer|copper|silver)"
            r"|\b(erhaeltst|erhältst|bekommst|kriegst|receive|gain|gained)\b.{0,80}\b(gold|silber|kupfer|muenze|muenzen|münze|münzen|coin|coins|currency)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "item_gain",
        re.compile(
            r"\b(erhaeltst|erhältst|bekommst|kriegst|nimmst|hebst|steckst|receive|gain|take|pick up)\b"
            r".{0,100}\b(inventar|rucksack|tasche|item|gegenstand|brief|paeckchen|päckchen|axt|schwert|weapon|inventory)\b",
            re.IGNORECASE,
        ),
    ),
]

STATE_CLAIM_TOOL_REQUIREMENTS = {
    "quest_acceptance": {"create_quest"},
    "quest_completion": {
        "complete_quest",
        "turn_in_quest",
        "claim_quest_rewards",
        "validate_quest_progress",
        "update_quest_objective_progress",
    },
    "reward_claim": {
        "turn_in_quest",
        "claim_quest_rewards",
        "add_xp",
        "add_currency",
        "add_inventory_item",
    },
    "xp_gain": {"add_xp", "turn_in_quest", "claim_quest_rewards"},
    "currency_gain": {"add_currency", "turn_in_quest", "claim_quest_rewards"},
    "item_gain": {"add_inventory_item", "equip_item", "turn_in_quest", "claim_quest_rewards"},
}

STATE_CLAIM_CONDITIONAL_MARKERS = (
    "wenn ",
    "sobald ",
    "falls ",
    "moechtest ",
    "möchtest ",
    "willst ",
    "soll ich",
    "wuerde ",
    "würde ",
    "if ",
    "would ",
)


def _split_claim_segments(text):
    """Return small text segments for state-claim scanning."""

    return [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if segment.strip()
    ]


def _is_conditional_or_prompt_segment(segment):
    """Return whether a segment asks or previews instead of claiming state."""

    lowered = segment.lower()
    if "?" in segment:
        return True

    return any(marker in lowered for marker in STATE_CLAIM_CONDITIONAL_MARKERS)


def _find_state_claims(text):
    """Return backend-controlled state claims found in narration text."""

    claims = set()

    for segment in _split_claim_segments(text):
        if _is_conditional_or_prompt_segment(segment):
            continue

        for claim_name, pattern in STATE_CLAIM_PATTERNS:
            if pattern.search(segment):
                claims.add(claim_name)

    return sorted(claims)


def _unsupported_state_claims(claims, successful_tool_names):
    """Return claims that have no matching successful tool in this turn."""

    successful_tool_names = set(successful_tool_names or [])
    unsupported = []

    for claim_name in claims:
        required_tools = STATE_CLAIM_TOOL_REQUIREMENTS.get(claim_name, set())
        if required_tools and successful_tool_names.isdisjoint(required_tools):
            unsupported.append(claim_name)

    return unsupported


def _format_failed_tool_summary(failed_tool_results):
    """Return compact failed-tool context for repair prompts."""

    lines = []
    for failure in failed_tool_results[-3:]:
        message = failure.get("message") or failure.get("error") or "Tool failed."
        lines.append(f"- {failure.get('tool_name', 'unknown')}: {message}")

    return "\n".join(lines)


def _build_state_claim_repair_prompt(unsupported_claims, failed_tool_results):
    """Build a system instruction that rejects unsafe final narration."""

    failed_tool_summary = _format_failed_tool_summary(failed_tool_results)
    failed_tool_block = (
        f"\nFailed tool results this turn:\n{failed_tool_summary}"
        if failed_tool_summary
        else ""
    )

    return (
        "Your previous draft was rejected because it claimed backend-controlled "
        f"state without matching successful tool results: {', '.join(unsupported_claims)}. "
        "That draft is not visible to the player. Re-answer the latest user action now. "
        "If the action truly changes quest state, rewards, XP, currency, inventory, equipment, "
        "resources, status effects, location, attributes, or skills, call the required tool(s). "
        "If no valid tool can be called or a required tool failed, narrate only the current true "
        "situation and ask what the player does next. Never claim success for a failed or missing "
        "tool result."
        f"{failed_tool_block}"
    )


def _contains_fake_tool_syntax(text):
    """Return whether final narration still appears to contain tool syntax."""

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

    max_tool_rounds=5,
    turn_id=None,
):
    """Run one gameplay turn with a bounded tool-call loop."""

    all_tool_definitions = (
        state_tool_definitions
        + inventory_tool_definitions
        + currency_tool_definitions
        + equipment_tool_definitions
        + resource_tool_definitions
        + status_effect_tool_definitions
        + leveling_tool_definitions
        + attribute_tool_definitions
        + skill_tool_definitions
    )
    debug_tool_event("game turn started", {
        "turn_id": turn_id,
        "campaign_id": campaign_id,
        "character_id": active_character["id"],
        "tool_count": len(all_tool_definitions),
        "max_tool_rounds": max_tool_rounds,
    })

    successful_tool_names = []
    failed_tool_results = []

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

        # 1. Resolve tool calls from the model message.
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
            skill_tool_definitions,
        )

        # 2. No tools means final narration only when backend state is not
        # being claimed without a matching successful tool in this turn.
        if not tool_calls:
            content = message.content or ""

            if not content.strip():
                return "Something happens, but you can't quite make sense of it."

            state_claims = _find_state_claims(content)
            unsupported_claims = _unsupported_state_claims(
                state_claims,
                successful_tool_names,
            )

            if unsupported_claims:
                debug_tool_event("state claim rejected without tool support", {
                    "turn_id": turn_id,
                    "round_index": round_index + 1,
                    "claims": unsupported_claims,
                    "successful_tools": successful_tool_names,
                    "content": content,
                })
                messages.append({
                    "role": "system",
                    "content": _build_state_claim_repair_prompt(
                        unsupported_claims,
                        failed_tool_results,
                    ),
                })
                continue

            return content

        # 3. Execute tools and feed results back into the conversation.
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
            )

            if isinstance(tool_result, dict) and turn_id:
                tool_result.setdefault("turn_id", turn_id)

            debug_tool_event("tool result", {
                "turn_id": turn_id,
                "round_index": round_index + 1,
                "tool_name": normalized_tool_name,
                "result": tool_result,
            })

            if isinstance(tool_result, dict) and tool_result.get("success") is True:
                successful_tool_names.append(normalized_tool_name)
            else:
                failed_tool_results.append({
                    "tool_name": normalized_tool_name,
                    "message": (
                        tool_result.get("message")
                        if isinstance(tool_result, dict)
                        else "Tool did not return a success payload."
                    ),
                    "result": tool_result,
                })

            tool_result_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        messages.extend(tool_result_messages)

    # 4. The tool budget is exhausted; force a plain narrative summary.
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

        state_claims = _find_state_claims(content)
        unsupported_claims = _unsupported_state_claims(
            state_claims,
            successful_tool_names,
        )

        if unsupported_claims:
            debug_tool_event("final narration rejected without tool support", {
                "turn_id": turn_id,
                "claims": unsupported_claims,
                "successful_tools": successful_tool_names,
                "content": content,
            })
            return (
                "Die Situation ist noch nicht backendseitig abgeschlossen. "
                "Was tust du als Nächstes?"
            )

        return content

    return "The actions are resolved, but the narration could not be generated."
