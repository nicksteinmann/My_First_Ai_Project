import unittest

from services.adventure_state.tools import STATE_TOOL_DEFINITIONS
from services.attributes.tools import ATTRIBUTE_TOOL_DEFINITIONS
from services.currency.tools import CURRENCY_TOOL_DEFINITIONS
from services.equipment.tools import EQUIPMENT_TOOL_DEFINITIONS
from services.inventory.tools import INVENTORY_TOOL_DEFINITIONS
from services.leveling.tools import LEVELING_TOOL_DEFINITIONS
from services.merchants.tools import MERCHANT_TOOL_DEFINITIONS
from services.resources.tools import RESOURCE_TOOL_DEFINITIONS
from services.skills.tools import SKILL_TOOL_DEFINITIONS
from services.status_effects.tools import STATUS_EFFECT_TOOL_DEFINITIONS
from services.trainers.tools import TRAINER_TOOL_DEFINITIONS


def _tool_names(tool_definitions):
    return [tool["function"]["name"] for tool in tool_definitions]


class ToolDefinitionContractTestCase(unittest.TestCase):
    def test_known_tool_definition_names_are_intentional(self):
        expected = {
            "state": [
                "update_location",
                "move_to_coordinates",
                "advance_time",
                "spend_time",
                "rest",
                "perform_check",
                "start_combat",
                "get_combat_state",
                "grant_combat_loot",
                "resolve_attack",
                "attempt_escape",
                "attempt_surrender",
                "attempt_ceasefire",
                "attempt_spare",
                "create_quest",
                "validate_quest_progress",
                "get_quest_details",
                "update_quest_objective_progress",
                "claim_quest_rewards",
                "turn_in_quest",
                "redeem_service_reward",
            ],
            "currency": [
                "add_currency",
                "remove_currency",
                "get_currency",
            ],
            "merchant": [
                "get_merchants_at_location",
                "get_merchant_inventory",
                "buy_item_from_merchant",
                "buy_merchant_service",
                "sell_item_to_merchant",
            ],
            "trainer": [
                "get_trainers_at_location",
                "train_with_teacher",
            ],
            "inventory": [
                "get_inventory",
                "add_inventory_item",
                "remove_inventory_item",
            ],
            "equipment": [
                "get_equipment",
                "equip_item",
                "unequip_item",
                "get_attack_profile",
                "get_defense_profile",
                "preview_attack_outcome",
            ],
            "resources": [
                "get_resources",
                "add_resource",
                "remove_resource",
                "set_resource",
            ],
            "leveling": [
                "add_xp",
            ],
            "attributes": [
                "add_attribute_xp",
            ],
            "skills": [
                "get_skills",
                "add_skill_xp",
                "create_custom_skill",
            ],
            "status_effects": [
                "get_status_effects",
                "apply_status_effect",
                "remove_status_effect",
            ],
        }

        actual = {
            "state": _tool_names(STATE_TOOL_DEFINITIONS),
            "currency": _tool_names(CURRENCY_TOOL_DEFINITIONS),
            "merchant": _tool_names(MERCHANT_TOOL_DEFINITIONS),
            "trainer": _tool_names(TRAINER_TOOL_DEFINITIONS),
            "inventory": _tool_names(INVENTORY_TOOL_DEFINITIONS),
            "equipment": _tool_names(EQUIPMENT_TOOL_DEFINITIONS),
            "resources": _tool_names(RESOURCE_TOOL_DEFINITIONS),
            "leveling": _tool_names(LEVELING_TOOL_DEFINITIONS),
            "attributes": _tool_names(ATTRIBUTE_TOOL_DEFINITIONS),
            "skills": _tool_names(SKILL_TOOL_DEFINITIONS),
            "status_effects": _tool_names(STATUS_EFFECT_TOOL_DEFINITIONS),
        }

        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
