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
        "paid_task_start",
        re.compile(
            r"\b(gute wahl|folge mir|wenn du fertig bist|ich bin oben|an die arbeit)\b"
            r".{0,180}\b(zahl|lohn|bezahlung|belohnung|reward|paid|silber|kupfer|gold|muenze|muenzen|coin|coins)\b"
            r"|\b(zahl|lohn|bezahlung|belohnung|reward|paid|silber|kupfer|gold|muenze|muenzen|coin|coins)\b"
            r".{0,180}\b(gute wahl|folge mir|wenn du fertig bist|ich bin oben|an die arbeit)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quest_completion",
        re.compile(
            r"\b(quest|auftrag|aufgabe|mission|botengang|job)\b.{0,80}\b(abgeschlossen|abgegeben|completed|turned in|turned_in)\b"
            r"|\b(auftrag|aufgabe|mission|botengang|job)\b.{0,40}\berledigt\b"
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
    "paid_task_start": {"create_quest"},
    "quest_completion": {
        "complete_quest",
        "turn_in_quest",
        "claim_quest_rewards",
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

NON_NARRATIVE_PLACEHOLDER_PATTERNS = [
    re.compile(
        r"^\(?\s*already provided a reply earlier;?\s*conversation continues\.?\s*\)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\(?\s*(already answered|i already answered|same as before|no new response)\b.*\)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\(?\s*(ich habe|es gab|die antwort).{0,80}(schon|bereits).{0,80}(geantwortet|antwort)\b.*\)?$",
        re.IGNORECASE,
    ),
]

DIRECT_REWARD_TOOLS = {"add_currency", "add_xp"}
STRUCTURED_REWARD_TOOLS = {"turn_in_quest", "claim_quest_rewards"}

PAID_WORK_REWARD_CONTEXT_PATTERNS = [
    re.compile(
        r"\b(auftrag|aufgabe|arbeit|job|mission|quest|botengang|keller|lager|sortier|liefer|wirt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(zahl|lohn|bezahlung|belohnung|reward|paid|verdient|silber|kupfer|gold|muenze|muenzen|coin|coins)\b",
        re.IGNORECASE,
    ),
]

EXACT_JOB_REWARD_OFFER_PATTERNS = [
    re.compile(
        r"\b(auftrag|aufgabe|arbeit|job|mission|botengang|keller|lager|sortier|liefer|wirt|fuhrmann|gerber)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(zahl|zahlt|zahlen|lohn|bezahlung|belohnung|reward|verdienst|bezahlt|paid)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+\s*(gold|silber|kupfer|copper|silver|muenze|muenzen|coin|coins)\b",
        re.IGNORECASE,
    ),
]


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


def _should_skip_claim_segment(segment, claim_name):
    """Return whether a segment should be ignored for a specific claim."""

    if "?" in segment:
        return True

    if claim_name == "paid_task_start":
        return False

    return _is_conditional_or_prompt_segment(segment)


def _find_state_claims(text):
    """Return backend-controlled state claims found in narration text."""

    claims = set()

    for segment in _split_claim_segments(text):
        for claim_name, pattern in STATE_CLAIM_PATTERNS:
            if _should_skip_claim_segment(segment, claim_name):
                continue

            if pattern.search(segment):
                claims.add(claim_name)

    return sorted(claims)


def _is_non_narrative_placeholder(text):
    """Return whether text is a meta placeholder instead of gameplay narration."""

    normalized = (text or "").strip()
    if not normalized:
        return False

    return any(pattern.search(normalized) for pattern in NON_NARRATIVE_PLACEHOLDER_PATTERNS)


def _get_message_content(message):
    """Return content from dict or SDK message objects."""

    if isinstance(message, dict):
        return message.get("content") or ""

    return getattr(message, "content", "") or ""


def _recent_message_text(messages, limit=8):
    """Return compact recent conversational text for policy checks."""

    return "\n".join(
        _get_message_content(message)
        for message in messages[-limit:]
        if _get_message_content(message)
    )


def _has_paid_work_reward_context(messages):
    """Return whether recent context looks like a structured paid NPC job."""

    recent_text = _recent_message_text(messages)
    if not recent_text:
        return False

    return all(
        pattern.search(recent_text)
        for pattern in PAID_WORK_REWARD_CONTEXT_PATTERNS
    )


def _find_narration_policy_violations(text, successful_tool_names):
    """Return narration policy violations that are not direct state claims."""

    successful_tool_names = set(successful_tool_names or [])
    if successful_tool_names.intersection({"create_quest", *STRUCTURED_REWARD_TOOLS}):
        return []

    if all(pattern.search(text or "") for pattern in EXACT_JOB_REWARD_OFFER_PATTERNS):
        return ["fixed_job_reward_offer"]

    return []


def _build_policy_repair_prompt(violations, rejected_content):
    """Build a repair prompt for narration that breaks non-state policy."""

    return (
        "Your previous draft was rejected because it broke narration policy: "
        f"{', '.join(violations)}. That draft is not visible to the player. "
        "Re-answer the latest user action now in the user's language. "
        "For newly offered paid NPC jobs, do not quote exact numeric pay unless "
        "a stored quest or successful quest reward tool supplied that amount. "
        "If the player has accepted the paid job, call create_quest in this turn. "
        "If the job is only being offered, do not call create_quest yet; describe "
        "the pay qualitatively instead."
        f"\nRejected draft, not visible to the player:\n{rejected_content}"
    )


def _should_block_direct_reward_tool(tool_name, messages, successful_tool_names):
    """Return whether a direct reward tool bypasses structured quest rewards."""

    if tool_name not in DIRECT_REWARD_TOOLS:
        return False

    return _has_paid_work_reward_context(messages)


def _blocked_direct_reward_result(tool_name):
    """Return a failed tool result for direct structured-job reward bypasses."""

    return {
        "success": False,
        "tool": tool_name,
        "message": (
            "Direct reward tools are blocked for paid NPC jobs and structured tasks. "
            "Create or use a structured quest, then pay rewards through turn_in_quest "
            "or claim_quest_rewards so backend reward rules define the payout."
        ),
    }


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


def _build_state_claim_repair_prompt(unsupported_claims, failed_tool_results, rejected_content=None):
    """Build a system instruction that rejects unsafe final narration."""

    failed_tool_summary = _format_failed_tool_summary(failed_tool_results)
    failed_tool_block = (
        f"\nFailed tool results this turn:\n{failed_tool_summary}"
        if failed_tool_summary
        else ""
    )
    rejected_block = (
        f"\nRejected draft, not visible to the player:\n{rejected_content}"
        if rejected_content
        else ""
    )

    return (
        "Your previous draft was rejected because it claimed backend-controlled "
        f"state without matching successful tool results: {', '.join(unsupported_claims)}. "
        "That draft is not visible to the player. Re-answer the latest user action now. "
        "Do not say that you already answered. Do not mention this repair instruction. "
        "If the action truly changes quest state, rewards, XP, currency, inventory, equipment, "
        "resources, status effects, location, attributes, or skills, call the required tool(s). "
        "If no valid tool can be called or a required tool failed, narrate only the current true "
        "situation and ask what the player does next. Never claim success for a failed or missing "
        "tool result."
        f"{failed_tool_block}"
        f"{rejected_block}"
    )


def _build_placeholder_repair_prompt(content):
    """Build a system instruction for meta placeholders that are not narration."""

    return (
        "Your previous message was a meta placeholder instead of a usable in-world reply. "
        "That message is not visible to the player. Re-answer the latest user action now. "
        "Do not say that you already answered, and do not mention this correction. "
        "Continue the current scene in the user's language. If the latest user action changes "
        "backend state, call the required tool(s); otherwise provide normal gameplay narration."
        f"\nRejected placeholder, not visible to the player:\n{content}"
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

            if _is_non_narrative_placeholder(content):
                debug_tool_event("non-narrative placeholder rejected", {
                    "turn_id": turn_id,
                    "round_index": round_index + 1,
                    "content": content,
                })
                messages.append({
                    "role": "system",
                    "content": _build_placeholder_repair_prompt(content),
                })
                continue

            policy_violations = _find_narration_policy_violations(
                content,
                successful_tool_names,
            )
            if policy_violations:
                debug_tool_event("narration policy rejected", {
                    "turn_id": turn_id,
                    "round_index": round_index + 1,
                    "violations": policy_violations,
                    "content": content,
                })
                messages.append({
                    "role": "system",
                    "content": _build_policy_repair_prompt(
                        policy_violations,
                        content,
                    ),
                })
                continue

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
                        rejected_content=content,
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

            if _should_block_direct_reward_tool(
                normalized_tool_name,
                messages,
                successful_tool_names,
            ):
                debug_tool_event("direct reward tool blocked", {
                    "turn_id": turn_id,
                    "round_index": round_index + 1,
                    "tool_name": normalized_tool_name,
                    "arguments": normalized_tool_args,
                })
                tool_result = _blocked_direct_reward_result(normalized_tool_name)
            else:
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
        if _is_non_narrative_placeholder(content):
            debug_tool_event("final narration contained placeholder", {
                "turn_id": turn_id,
                "content": content,
            })
            return (
                "Der Spielzustand wurde nicht verändert. "
                "Was tust du als Nächstes?"
            )

        if _contains_fake_tool_syntax(content):
            debug_tool_event("final narration contained fake tool syntax", {
                "turn_id": turn_id,
                "content": content,
            })
            return "Die ausgeführten Aktionen sind verarbeitet. Was tust du als Nächstes?"

        policy_violations = _find_narration_policy_violations(
            content,
            successful_tool_names,
        )
        if policy_violations:
            debug_tool_event("final narration policy rejected", {
                "turn_id": turn_id,
                "violations": policy_violations,
                "content": content,
            })
            return (
                "Der genaue Lohn ist noch nicht backendseitig festgelegt. "
                "Was tust du als Nächstes?"
            )

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
