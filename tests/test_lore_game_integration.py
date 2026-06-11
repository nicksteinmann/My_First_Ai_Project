import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from services.lore.tools import LORE_TOOL_DEFINITIONS
from services.prompt_builder.game_prompt_builder import build_game_system_prompt
from services.tools.tool_handler import execute_normalized_tool, resolve_tool_calls
from services.tools.turn_handler import run_game_turn


def _fake_response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _make_test_character():
    return {
        "id": 42,
        "name": "Lore Tester",
        "class_name": "Knight",
        "race": "human",
        "level": 7,
        "status": "alive",
        "inventory_summary": "Torch, Bread",
        "equipment_summary": "Training Sword",
        "attribute_summary": "Strength 8, Dexterity 7",
        "skill_summary": "Swordsmanship 5",
        "status_effect_summary": "None",
        "level_progression": {
            "xp_into_level": 12,
            "xp_needed_this_level": 40,
        },
        "currency": {"gold": 1, "silver": 4, "copper": 7},
        "stats": {
            "hp": 30,
            "hp_max": 30,
            "mana": 5,
            "mana_max": 5,
            "energy": 18,
            "energy_max": 18,
        },
        "current_state": {
            "location": "Crownford",
            "current_location_id": 11,
            "day_label": "Day 3",
            "time_of_day": "Morning",
            "location_context": {
                "region_name": "Crownfields",
                "subregion": "Royal Heartland",
                "coordinate_x": 12,
                "coordinate_y": 18,
                "scale_km_per_unit": 10,
            },
            "visible_quests": [],
            "nearby_merchants": [],
            "nearby_trainers": [],
        },
        "currency_summary": "1 gold, 4 silver, 7 copper",
    }


class LoreGameIntegrationTestCase(unittest.TestCase):
    def test_resolve_tool_calls_accepts_fake_lore_calls(self):
        message = SimpleNamespace(
            content=(
                '<|DSML|invoke name="get_lore_context">'
                '<|DSML|parameter name="query_text">Was weiß ich über Willowbrook?</|DSML|parameter>'
                '<|DSML|parameter name="location_id">willowbrook</|DSML|parameter>'
                '</|DSML|invoke>'
            ),
            tool_calls=[],
        )

        tool_calls = resolve_tool_calls(
            message,
            state_tool_definitions=[],
            inventory_tool_definitions=[],
            currency_tool_definitions=[],
            merchant_tool_definitions=[],
            trainer_tool_definitions=[],
            equipment_tool_definitions=[],
            resource_tool_definitions=[],
            status_effect_tool_definitions=[],
            leveling_tool_definitions=[],
            lore_tool_definitions=LORE_TOOL_DEFINITIONS,
            attribute_tool_definitions=[],
            skill_tool_definitions=[],
        )

        self.assertEqual(1, len(tool_calls))
        self.assertEqual("get_lore_context", tool_calls[0]["name"])
        self.assertEqual("willowbrook", tool_calls[0]["arguments"]["location_id"])

    def test_execute_normalized_tool_dispatches_to_lore_executor(self):
        execute_lore_tool = Mock(return_value={"success": True, "tool": "get_lore_context"})

        result = execute_normalized_tool(
            normalized_tool_name="get_lore_context",
            normalized_tool_args={"query_text": "What is Willowbrook?"},
            campaign_id=7,
            character_id=42,
            state_tool_definitions=[],
            inventory_tool_definitions=[],
            currency_tool_definitions=[],
            merchant_tool_definitions=[],
            trainer_tool_definitions=[],
            equipment_tool_definitions=[],
            resource_tool_definitions=[],
            status_effect_tool_definitions=[],
            leveling_tool_definitions=[],
            lore_tool_definitions=LORE_TOOL_DEFINITIONS,
            attribute_tool_definitions=[],
            skill_tool_definitions=[],
            execute_state_tool=None,
            execute_inventory_tool=None,
            execute_currency_tool=None,
            execute_merchant_tool=None,
            execute_trainer_tool=None,
            execute_equipment_tool=None,
            execute_resource_tool=None,
            execute_status_effect_tool=None,
            execute_leveling_tool=None,
            execute_lore_tool=execute_lore_tool,
            execute_attribute_tool=None,
            execute_skill_tool=None,
        )

        self.assertTrue(result["success"])
        execute_lore_tool.assert_called_once_with(
            campaign_id=7,
            tool_name="get_lore_context",
            arguments={"query_text": "What is Willowbrook?"},
        )

    def test_build_game_system_prompt_flags_lore_questions(self):
        prompt = build_game_system_prompt(
            _make_test_character(),
            latest_user_input="Was weiß ich über die Stadt Willowbrook und diese Region?",
        )

        self.assertIn("Lore/world knowledge question detected.", prompt)
        self.assertIn("Use get_lore_context before answering factual questions", prompt)

    def test_build_game_system_prompt_flags_distant_region_history_questions(self):
        prompt = build_game_system_prompt(
            _make_test_character(),
            latest_user_input="Was weiß ich über die Geschichte der Grimscar Wastes?",
        )

        self.assertIn("Lore/world knowledge question detected.", prompt)
        self.assertIn("Do not invent factual world lore when get_lore_context can answer it.", prompt)

    def test_run_game_turn_executes_lore_tool_before_final_narration(self):
        first_message = SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(
                        name="get_lore_context",
                        arguments='{"query_text":"Was weiß ich über Willowbrook?","location_id":"willowbrook"}',
                    ),
                )
            ],
        )
        second_message = SimpleNamespace(
            content="Willowbrook ist eine geschäftige Marktstadt mit viel Flusshandel.",
            tool_calls=[],
        )
        responses = iter([
            _fake_response(first_message),
            _fake_response(second_message),
        ])

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: next(responses))
            )
        )
        execute_lore_tool = Mock(return_value={
            "success": True,
            "tool": "get_lore_context",
            "matches": [
                {
                    "title": "Willowbrook",
                    "text": "A busy market town on the river.",
                }
            ],
        })

        result = run_game_turn(
            client=client,
            model="test-model",
            messages=[{"role": "user", "content": "Was weiß ich über Willowbrook?"}],
            campaign_id=5,
            active_character=_make_test_character(),
            state_tool_definitions=[],
            inventory_tool_definitions=[],
            currency_tool_definitions=[],
            merchant_tool_definitions=[],
            trainer_tool_definitions=[],
            equipment_tool_definitions=[],
            resource_tool_definitions=[],
            status_effect_tool_definitions=[],
            leveling_tool_definitions=[],
            lore_tool_definitions=LORE_TOOL_DEFINITIONS,
            attribute_tool_definitions=[],
            skill_tool_definitions=[],
            execute_state_tool=None,
            execute_inventory_tool=None,
            execute_currency_tool=None,
            execute_merchant_tool=None,
            execute_trainer_tool=None,
            execute_equipment_tool=None,
            execute_resource_tool=None,
            execute_status_effect_tool=None,
            execute_leveling_tool=None,
            execute_lore_tool=execute_lore_tool,
            execute_attribute_tool=None,
            execute_skill_tool=None,
            resolve_tool_calls=resolve_tool_calls,
            parse_tool_call_payload=lambda tool_call, index=0: (
                tool_call.function.name,
                {"query_text": "Was weiß ich über Willowbrook?", "location_id": "willowbrook"},
                tool_call.id,
                tool_call.function.arguments,
            ),
            normalize_tool_call=lambda tool_name, tool_args, active_character: (tool_name, tool_args),
            execute_normalized_tool=execute_normalized_tool,
            max_tool_rounds=2,
            turn_id="turn-lore-1",
        )

        self.assertEqual(
            "Willowbrook ist eine geschäftige Marktstadt mit viel Flusshandel.",
            result,
        )
        execute_lore_tool.assert_called_once_with(
            campaign_id=5,
            tool_name="get_lore_context",
            arguments={
                "query_text": "Was weiß ich über Willowbrook?",
                "location_id": "willowbrook",
            },
        )


if __name__ == "__main__":
    unittest.main()
