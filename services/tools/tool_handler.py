import json
import re


def debug_tool_event(label, payload=None):
    print(f"[TOOL DEBUG] {label}")
    if payload is not None:
        try:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        except TypeError:
            print(payload)


def _normalize_dsml_text(text):
    if not text:
        return ""

    normalized = text
    normalized = normalized.replace("｜", "|")
    normalized = normalized.replace("ï½œ", "|")
    normalized = normalized.replace("<| DSML |", "<|DSML|")
    normalized = normalized.replace("<|DSML |", "<|DSML|")
    normalized = normalized.replace("<| DSML|", "<|DSML|")
    normalized = normalized.replace("| invoke", "|invoke")
    normalized = normalized.replace("| parameter", "|parameter")
    normalized = normalized.replace("| /invoke", "|/invoke")
    normalized = normalized.replace("| /parameter", "|/parameter")
    normalized = normalized.replace("| /function_calls", "|/function_calls")
    return normalized


def extract_fake_tool_calls(text):
    if not text:
        return []

    text = _normalize_dsml_text(text)
    parsed_tool_calls = []

    invoke_pattern = r'<\|DSML\|invoke\s+name="([^"]+)"\s*>(.*?)(?=<\|DSML\|invoke|<\|DSML\|/invoke>|$)'
    invoke_matches = re.findall(invoke_pattern, text, re.DOTALL)

    for name, inner in invoke_matches:
        params = {}

        param_pattern = (
            r'<\|DSML\|parameter\s+name="([^"]+)"'
            r'(?:\s+string="(?:true|false)")?\s*>'
            r'(.*?)(?=<\|DSML\|parameter|<\|DSML\|/invoke>|$)'
        )
        param_matches = re.findall(param_pattern, inner, re.DOTALL)

        for key, value in param_matches:
            cleaned_value = value.strip()

            cleaned_value = re.sub(r'<\|DSML\|/?parameter[^>]*>', '', cleaned_value).strip()
            cleaned_value = re.sub(r'<\|DSML\|/?invoke[^>]*>', '', cleaned_value).strip()
            cleaned_value = re.sub(r'<\|DSML\|/?function_calls[^>]*>', '', cleaned_value).strip()

            if cleaned_value:
                params[key] = cleaned_value

        parsed_tool_calls.append({
            "name": name.strip(),
            "arguments": params
        })

    if parsed_tool_calls:
        debug_tool_event("fake/DSML tool calls parsed", parsed_tool_calls)

    return parsed_tool_calls


def clean_tool_args(tool_args):
    if not isinstance(tool_args, dict):
        return tool_args

    cleaned_tool_args = {}

    for key, value in tool_args.items():
        if isinstance(value, str):
            value = value.strip()

            if value.isdigit():
                value = int(value)
            elif value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False

        cleaned_tool_args[key] = value

    return cleaned_tool_args


def normalize_tool_call(tool_name, tool_args, active_character):
    normalized_tool_name = tool_name
    normalized_tool_args = dict(tool_args)

    if normalized_tool_name == "update_currency":
        gold_value = int(normalized_tool_args.get("gold", 0))
        silver_value = int(normalized_tool_args.get("silver", 0))
        copper_value = int(normalized_tool_args.get("copper", 0))

        current_currency = active_character.get("currency", {}) or {}
        current_gold = int(current_currency.get("gold", 0))
        current_silver = int(current_currency.get("silver", 0))
        current_copper = int(current_currency.get("copper", 0))

        delta_gold = gold_value - current_gold
        delta_silver = silver_value - current_silver
        delta_copper = copper_value - current_copper

        if delta_gold > 0 or delta_silver > 0 or delta_copper > 0:
            normalized_tool_name = "add_currency"
            normalized_tool_args = {
                "gold": max(delta_gold, 0),
                "silver": max(delta_silver, 0),
                "copper": max(delta_copper, 0),
            }
        else:
            normalized_tool_name = "remove_currency"
            normalized_tool_args = {
                "gold": abs(min(delta_gold, 0)),
                "silver": abs(min(delta_silver, 0)),
                "copper": abs(min(delta_copper, 0)),
            }

    if normalized_tool_name == "update_resource":
        normalized_tool_name = "set_resource"

    if normalized_tool_name == "damage_resource":
        normalized_tool_name = "remove_resource"

    if normalized_tool_name == "heal_resource":
        normalized_tool_name = "add_resource"

    if normalized_tool_name in ("grant_xp", "add_experience", "gain_xp", "gain_experience"):
        normalized_tool_name = "add_xp"

    if normalized_tool_name in ("grant_attribute_xp", "add_stat_xp"):
        normalized_tool_name = "add_attribute_xp"

    if normalized_tool_name == "grant_skill_xp":
        normalized_tool_name = "add_skill_xp"

    if normalized_tool_name == "learn_skill":
        normalized_tool_name = "create_custom_skill"

    if normalized_tool_name == "change_location":
        normalized_tool_name = "update_location"

    if normalized_tool_name == "set_location":
        normalized_tool_name = "update_location"

    if normalized_tool_name == "update_active_quest":
        normalized_tool_name = "set_active_quest"

    if normalized_tool_name == "update_location":
        if "location" in normalized_tool_args and "location_name" not in normalized_tool_args:
            normalized_tool_args["location_name"] = normalized_tool_args["location"]

    if normalized_tool_name == "set_active_quest":
        if "quest_title" in normalized_tool_args and "title" not in normalized_tool_args:
            normalized_tool_args["title"] = normalized_tool_args["quest_title"]

        if "quest_description" in normalized_tool_args and "description" not in normalized_tool_args:
            normalized_tool_args["description"] = normalized_tool_args["quest_description"]

    if normalized_tool_name != tool_name or normalized_tool_args != tool_args:
        debug_tool_event("tool call normalized", {
            "original_name": tool_name,
            "original_args": tool_args,
            "normalized_name": normalized_tool_name,
            "normalized_args": normalized_tool_args,
        })

    return normalized_tool_name, normalized_tool_args


def get_valid_tool_names(
    state_tool_definitions,
    inventory_tool_definitions,
    currency_tool_definitions,
    equipment_tool_definitions=None,
    resource_tool_definitions=None,
    status_effect_tool_definitions=None,
    leveling_tool_definitions=None,
    attribute_tool_definitions=None,
    skill_tool_definitions=None,
):
    equipment_tool_definitions = equipment_tool_definitions or []
    resource_tool_definitions = resource_tool_definitions or []
    status_effect_tool_definitions = status_effect_tool_definitions or []
    leveling_tool_definitions = leveling_tool_definitions or []
    attribute_tool_definitions = attribute_tool_definitions or []
    skill_tool_definitions = skill_tool_definitions or []

    return {
        *(t["function"]["name"] for t in state_tool_definitions),
        *(t["function"]["name"] for t in inventory_tool_definitions),
        *(t["function"]["name"] for t in currency_tool_definitions),
        *(t["function"]["name"] for t in equipment_tool_definitions),
        *(t["function"]["name"] for t in resource_tool_definitions),
        *(t["function"]["name"] for t in status_effect_tool_definitions),
        *(t["function"]["name"] for t in leveling_tool_definitions),
        *(t["function"]["name"] for t in attribute_tool_definitions),
        *(t["function"]["name"] for t in skill_tool_definitions),
        "change_location",
        "set_location",
        "update_active_quest",
        "update_currency",
        "update_resource",
        "damage_resource",
        "heal_resource",
        "grant_xp",
        "add_experience",
        "gain_xp",
        "gain_experience",
        "grant_attribute_xp",
        "add_stat_xp",
        "grant_skill_xp",
        "learn_skill",
    }


def resolve_tool_calls(
    first_message,
    state_tool_definitions,
    inventory_tool_definitions,
    currency_tool_definitions,
    equipment_tool_definitions=None,
    resource_tool_definitions=None,
    status_effect_tool_definitions=None,
    leveling_tool_definitions=None,
    attribute_tool_definitions=None,
    skill_tool_definitions=None,
):
    tool_calls = first_message.tool_calls or []

    debug_tool_event("raw model message", {
        "content": first_message.content,
        "native_tool_call_count": len(tool_calls),
        "native_tool_calls": tool_calls,
    })

    if not tool_calls and first_message.content:
        fake_calls = extract_fake_tool_calls(first_message.content)
        if fake_calls:
            valid_tool_names = get_valid_tool_names(
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

            filtered_fake_calls = [
                call for call in fake_calls
                if call.get("name") in valid_tool_names
            ]

            rejected_fake_calls = [
                call for call in fake_calls
                if call.get("name") not in valid_tool_names
            ]

            debug_tool_event("fake/DSML tool call filtering", {
                "valid_tool_names": sorted(valid_tool_names),
                "accepted": filtered_fake_calls,
                "rejected": rejected_fake_calls,
            })

            tool_calls = filtered_fake_calls

    debug_tool_event("resolved tool calls", {
        "count": len(tool_calls),
        "tool_calls": tool_calls,
    })

    return tool_calls


def execute_normalized_tool(
    normalized_tool_name,
    normalized_tool_args,
    campaign_id,
    character_id,
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
):
    state_tool_names = [t["function"]["name"] for t in state_tool_definitions]
    inventory_tool_names = [t["function"]["name"] for t in inventory_tool_definitions]
    currency_tool_names = [t["function"]["name"] for t in currency_tool_definitions]
    equipment_tool_names = [t["function"]["name"] for t in equipment_tool_definitions]
    resource_tool_names = [t["function"]["name"] for t in resource_tool_definitions]
    status_effect_tool_names = [t["function"]["name"] for t in status_effect_tool_definitions]
    leveling_tool_names = [t["function"]["name"] for t in leveling_tool_definitions]
    attribute_tool_names = [t["function"]["name"] for t in attribute_tool_definitions]
    skill_tool_names = [t["function"]["name"] for t in skill_tool_definitions]

    if normalized_tool_name in state_tool_names:
        return execute_state_tool(
            campaign_id=campaign_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in inventory_tool_names:
        return execute_inventory_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in currency_tool_names:
        return execute_currency_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in equipment_tool_names and execute_equipment_tool:
        return execute_equipment_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in resource_tool_names and execute_resource_tool:
        return execute_resource_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in status_effect_tool_names and execute_status_effect_tool:
        return execute_status_effect_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in leveling_tool_names and execute_leveling_tool:
        return execute_leveling_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in attribute_tool_names and execute_attribute_tool:
        return execute_attribute_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    if normalized_tool_name in skill_tool_names and execute_skill_tool:
        return execute_skill_tool(
            character_id=character_id,
            tool_name=normalized_tool_name,
            arguments=normalized_tool_args
        )

    debug_tool_event("unknown normalized tool", {
        "tool_name": normalized_tool_name,
        "arguments": normalized_tool_args,
    })

    return {
        "success": False,
        "message": f"Unknown tool: {normalized_tool_name}"
    }


def parse_tool_call_payload(tool_call, index=0):
    if hasattr(tool_call, "function"):
        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        try:
            tool_args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            tool_args = {}

        raw_arguments = tool_call.function.arguments or "{}"
    else:
        tool_name = tool_call["name"]
        tool_args = tool_call["arguments"]
        tool_call_id = f"fake_tool_call_{index}"
        raw_arguments = json.dumps(tool_args, ensure_ascii=False)

    tool_args = clean_tool_args(tool_args)

    debug_tool_event("tool call payload parsed", {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_call_id": tool_call_id,
        "raw_arguments": raw_arguments,
    })

    return tool_name, tool_args, tool_call_id, raw_arguments
