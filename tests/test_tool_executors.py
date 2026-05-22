import json
import unittest

from flask import Flask

from models import Character, CharacterAttribute, User, db
from services.attributes.tools import execute_attribute_tool
from services.currency.tools import execute_currency_tool
from services.equipment.tools import execute_equipment_tool
from services.inventory.tools import execute_inventory_tool
from services.leveling.tools import execute_leveling_tool
from services.resources.tools import execute_resource_tool
from services.skills import ensure_core_skill_definitions
from services.skills.tools import execute_skill_tool
from services.status_effects.tools import execute_status_effect_tool


def _inventory_with_test_pack():
    return {
        "inventory": {
            "containers": [
                {
                    "container_id": "base_inventory",
                    "name": "No Carried Container",
                    "source": "base",
                    "source_item_id": None,
                    "max_volume": 0.0,
                    "max_item_size": "tiny",
                    "items": [],
                },
                {
                    "container_id": "test_pack",
                    "name": "Test Pack",
                    "source": "equipment",
                    "source_item_id": "test_pack_item",
                    "max_volume": 20.0,
                    "max_item_size": "medium",
                    "items": [],
                },
            ]
        },
        "equipment": {"slots": {}},
    }


class BackendToolExecutorTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        ensure_core_skill_definitions()

        self.user = User(
            username="tooltester",
            email="tooltester@example.com",
            password_hash="test",
        )
        self.character = Character(
            user=self.user,
            name="Tool Nick",
            race="human",
            class_name="Knight",
            inventory_json=json.dumps(_inventory_with_test_pack()),
            currency_json={"gold": 0, "silver": 0, "copper": 0},
        )
        db.session.add_all([self.user, self.character])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()

    def _ensure_attributes(self):
        self.character = db.session.get(Character, self.character.id)
        if self.character.attributes:
            return self.character.attributes
        attributes = CharacterAttribute(character_id=self.character.id)
        db.session.add(attributes)
        db.session.commit()
        self.character = db.session.get(Character, self.character.id)
        return self.character.attributes

    def test_currency_tools_add_get_remove_and_reject_overdraft(self):
        added = execute_currency_tool(
            "add_currency",
            {"silver": 1, "copper": 25},
            self.character.id,
        )
        self.assertTrue(added["success"], added)
        self.assertEqual({"gold": 0, "silver": 1, "copper": 25}, added["currency"])

        current = execute_currency_tool("get_currency", {}, self.character.id)
        self.assertTrue(current["success"], current)
        self.assertEqual({"gold": 0, "silver": 1, "copper": 25}, current["currency"])

        removed = execute_currency_tool(
            "remove_currency",
            {"silver": 1, "copper": 5},
            self.character.id,
        )
        self.assertTrue(removed["success"], removed)
        self.assertEqual({"gold": 0, "silver": 0, "copper": 20}, removed["currency"])

        overdraft = execute_currency_tool(
            "remove_currency",
            {"gold": 1},
            self.character.id,
        )
        self.assertFalse(overdraft["success"], overdraft)
        self.assertEqual("Not enough gold.", overdraft["message"])

    def test_inventory_tools_add_get_and_remove_items(self):
        add_result = execute_inventory_tool(
            self.character.id,
            "add_inventory_item",
            {
                "item": {
                    "item_id": "test_apple",
                    "name": "Apple",
                    "description": "A fresh apple.",
                    "size": "tiny",
                    "volume": 0.1,
                    "weight": 0.1,
                    "stackable": True,
                    "hand_usage": "none",
                    "item_type": "consumable",
                },
                "quantity": 2,
                "container_id": "test_pack",
            },
        )
        self.assertTrue(add_result["success"], add_result)
        self.assertEqual("test_apple", add_result["details"]["item_id"])

        inventory = execute_inventory_tool(self.character.id, "get_inventory", {})
        self.assertTrue(inventory["success"], inventory)
        pack = next(
            container
            for container in inventory["inventory"]["inventory"]["containers"]
            if container["container_id"] == "test_pack"
        )
        self.assertEqual(1, len(pack["items"]))
        self.assertEqual(2, pack["items"][0]["quantity"])

        remove_result = execute_inventory_tool(
            self.character.id,
            "remove_inventory_item",
            {"item_id": "Apple", "quantity": 1},
        )
        self.assertTrue(remove_result["success"], remove_result)

        inventory_after = execute_inventory_tool(self.character.id, "get_inventory", {})
        pack_after = next(
            container
            for container in inventory_after["inventory"]["inventory"]["containers"]
            if container["container_id"] == "test_pack"
        )
        self.assertEqual(1, pack_after["items"][0]["quantity"])

    def test_equipment_tools_equip_and_unequip_weapon(self):
        add_weapon = execute_inventory_tool(
            self.character.id,
            "add_inventory_item",
            {
                "item": {
                    "item_id": "training_club",
                    "name": "Training Club",
                    "description": "A safe practice weapon.",
                    "size": "medium",
                    "volume": 2.0,
                    "weight": 2.0,
                    "stackable": False,
                    "hand_usage": "one_handed",
                    "item_type": "weapon",
                },
                "quantity": 1,
                "container_id": "test_pack",
            },
        )
        self.assertTrue(add_weapon["success"], add_weapon)

        equipped = execute_equipment_tool(
            self.character.id,
            "equip_item",
            {"item_id": "training_club", "slot": "main_hand"},
        )
        self.assertTrue(equipped["success"], equipped)
        self.assertEqual(["main_hand"], equipped["details"]["slots"])
        self.assertEqual(
            "Training Club",
            equipped["equipment"]["slots"]["main_hand"]["name"],
        )

        current = execute_equipment_tool(self.character.id, "get_equipment", {})
        self.assertTrue(current["success"], current)
        self.assertEqual(
            "Training Club",
            current["equipment"]["slots"]["main_hand"]["name"],
        )

        unequipped = execute_equipment_tool(
            self.character.id,
            "unequip_item",
            {"slot": "main_hand", "target_container_id": "test_pack"},
        )
        self.assertTrue(unequipped["success"], unequipped)
        self.assertIsNone(unequipped["equipment"]["slots"]["main_hand"])

    def test_attack_profile_prefers_dexterity_for_rapier_family(self):
        attributes = self._ensure_attributes()
        attributes.strength = 4
        attributes.dexterity = 14
        db.session.commit()

        add_weapon = execute_inventory_tool(
            self.character.id,
            "add_inventory_item",
            {
                "item": {
                    "item_id": "finesse_rapier",
                    "name": "Fine Rapier",
                    "description": "A nimble thrusting blade.",
                    "size": "medium",
                    "volume": 2.0,
                    "weight": 1.5,
                    "stackable": False,
                    "hand_usage": "one_handed",
                    "item_type": "weapon",
                    "weapon_family": "rapier",
                },
                "quantity": 1,
                "container_id": "test_pack",
            },
        )
        self.assertTrue(add_weapon["success"], add_weapon)
        equipped = execute_equipment_tool(
            self.character.id,
            "equip_item",
            {"item_id": "finesse_rapier", "slot": "main_hand"},
        )
        self.assertTrue(equipped["success"], equipped)

        profile = execute_equipment_tool(self.character.id, "get_attack_profile", {})
        self.assertTrue(profile["success"], profile)
        self.assertEqual("rapier", profile["weapon"]["weapon_family"])
        self.assertEqual("Swordsmanship", profile["weapon"]["skill_name"])
        self.assertGreater(
            profile["scaling"]["contributions"]["dexterity"],
            profile["scaling"]["contributions"]["strength"],
        )

    def test_attack_profile_prefers_strength_for_axe_hammer_family(self):
        attributes = self._ensure_attributes()
        attributes.strength = 16
        attributes.dexterity = 5
        db.session.commit()

        add_weapon = execute_inventory_tool(
            self.character.id,
            "add_inventory_item",
            {
                "item": {
                    "item_id": "war_axe",
                    "name": "War Axe",
                    "description": "A heavy axe for brutal strikes.",
                    "size": "medium",
                    "volume": 2.5,
                    "weight": 3.5,
                    "stackable": False,
                    "hand_usage": "one_handed",
                    "item_type": "weapon",
                    "weapon_family": "axe_hammer",
                },
                "quantity": 1,
                "container_id": "test_pack",
            },
        )
        self.assertTrue(add_weapon["success"], add_weapon)
        equipped = execute_equipment_tool(
            self.character.id,
            "equip_item",
            {"item_id": "war_axe", "slot": "main_hand"},
        )
        self.assertTrue(equipped["success"], equipped)

        profile = execute_equipment_tool(self.character.id, "get_attack_profile", {})
        self.assertTrue(profile["success"], profile)
        self.assertEqual("axe_hammer", profile["weapon"]["weapon_family"])
        self.assertEqual("Axes & Hammers", profile["weapon"]["skill_name"])
        self.assertGreater(
            profile["scaling"]["contributions"]["strength"],
            profile["scaling"]["contributions"].get("constitution", 0),
        )

    def test_attack_profile_uses_improvised_fallback_for_unknown_weapon(self):
        self._ensure_attributes()
        add_weapon = execute_inventory_tool(
            self.character.id,
            "add_inventory_item",
            {
                "item": {
                    "item_id": "chair_leg",
                    "name": "Broken Chair Leg",
                    "description": "An improvised weapon from furniture.",
                    "size": "small",
                    "volume": 1.0,
                    "weight": 1.2,
                    "stackable": False,
                    "hand_usage": "one_handed",
                    "item_type": "weapon",
                },
                "quantity": 1,
                "container_id": "test_pack",
            },
        )
        self.assertTrue(add_weapon["success"], add_weapon)
        equipped = execute_equipment_tool(
            self.character.id,
            "equip_item",
            {"item_id": "chair_leg", "slot": "main_hand"},
        )
        self.assertTrue(equipped["success"], equipped)

        profile = execute_equipment_tool(self.character.id, "get_attack_profile", {})
        self.assertTrue(profile["success"], profile)
        self.assertEqual("improvised", profile["weapon"]["weapon_family"])
        self.assertEqual("Athletics", profile["weapon"]["skill_name"])

    def test_resource_tools_set_damage_heal_and_life_status(self):
        lowered = execute_resource_tool(
            self.character.id,
            "set_resource",
            {"resource": "hp", "current": 50, "maximum": 120},
        )
        self.assertTrue(lowered["success"], lowered)
        self.assertEqual(50, lowered["resources"]["hp"]["current"])
        self.assertEqual(120, lowered["resources"]["hp"]["max"])

        dead = execute_resource_tool(
            self.character.id,
            "remove_resource",
            {"resource": "health", "amount": 999},
        )
        self.assertTrue(dead["success"], dead)
        self.assertEqual(0, dead["resources"]["hp"]["current"])
        self.assertEqual("dead", dead["resources"]["character_status"])

        healed = execute_resource_tool(
            self.character.id,
            "add_resource",
            {"resource": "hp", "amount": 5},
        )
        self.assertTrue(healed["success"], healed)
        self.assertEqual(5, healed["resources"]["hp"]["current"])
        self.assertEqual("alive", healed["resources"]["character_status"])

        invalid = execute_resource_tool(
            self.character.id,
            "remove_resource",
            {"resource": "rage", "amount": 1},
        )
        self.assertFalse(invalid["success"], invalid)
        self.assertIn("Unknown resource", invalid["message"])

    def test_leveling_tool_adds_xp_levels_up_and_grants_attribute_xp(self):
        result = execute_leveling_tool(
            self.character.id,
            "add_xp",
            {"amount": 100, "reason": "test reward"},
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(2, result["progression"]["level"])
        self.assertEqual(100, result["progression"]["total_xp"])
        self.assertEqual(1, result["details"]["levels_gained"])
        self.assertIn(2, result["details"]["level_ups"])
        self.assertTrue(result["details"]["attribute_gains"]["attribute_xp_grants"])

    def test_attribute_tool_adds_single_and_batch_xp(self):
        single = execute_attribute_tool(
            self.character.id,
            "add_attribute_xp",
            {"attribute": "strength", "amount": 100, "reason": "training"},
        )
        self.assertTrue(single["success"], single)
        self.assertEqual({"strength": 100}, single["attribute_xp_grants"])

        batch = execute_attribute_tool(
            self.character.id,
            "add_attribute_xp",
            {"grants": {"dexterity": 50, "perception": 25}},
        )
        self.assertTrue(batch["success"], batch)
        self.assertEqual(50, batch["attribute_xp_grants"]["dexterity"])
        self.assertEqual(25, batch["attribute_xp_grants"]["perception"])

        invalid = execute_attribute_tool(
            self.character.id,
            "add_attribute_xp",
            {"attribute": "luck", "amount": 5},
        )
        self.assertFalse(invalid["success"], invalid)
        self.assertIn("Unknown attribute", invalid["message"])

    def test_skill_tools_get_create_and_add_xp(self):
        skills = execute_skill_tool(self.character.id, "get_skills", {})
        self.assertTrue(skills["success"], skills)
        self.assertTrue(any(skill["name"] == "Swordsmanship" for skill in skills["skills"]))

        sword_xp = execute_skill_tool(
            self.character.id,
            "add_skill_xp",
            {"skill_name": "Swordsmanship", "amount": 100, "reason": "practice"},
        )
        self.assertTrue(sword_xp["success"], sword_xp)
        self.assertEqual("Swordsmanship", sword_xp["details"]["skill_name"])
        self.assertEqual(100, sword_xp["details"]["amount"])
        self.assertGreaterEqual(sword_xp["details"]["new_level"], 1)

        custom = execute_skill_tool(
            self.character.id,
            "create_custom_skill",
            {
                "name": "Cartography",
                "linked_attribute": "intelligence",
                "secondary_attributes": ["perception"],
                "aliases": ["Map Reading"],
                "allowed_domains": ["exploration", "knowledge"],
                "description": "Making and reading maps.",
            },
        )
        self.assertTrue(custom["success"], custom)
        self.assertTrue(custom["details"]["created"])
        created_skill = next(skill for skill in custom["skill"] if skill["name"] == "Cartography")
        self.assertEqual(["perception"], created_skill["secondary_attributes"])
        self.assertIn("Map Reading", created_skill["aliases"])
        self.assertEqual(["exploration", "knowledge"], created_skill["allowed_domains"])

        alias_match = execute_skill_tool(
            self.character.id,
            "create_custom_skill",
            {
                "name": "Map Reading",
                "linked_attribute": "intelligence",
            },
        )
        self.assertTrue(alias_match["success"], alias_match)
        self.assertFalse(alias_match["details"]["created"])
        self.assertEqual(created_skill["id"], alias_match["details"]["skill_id"])

        created_xp = execute_skill_tool(
            self.character.id,
            "add_skill_xp",
            {
                "skill_name": "Foraging",
                "amount": 25,
                "allow_create": True,
                "linked_attribute": "perception",
                "secondary_attributes": ["intelligence"],
                "allowed_domains": ["exploration"],
            },
        )
        self.assertTrue(created_xp["success"], created_xp)
        self.assertEqual("Foraging", created_xp["details"]["skill_name"])
        created_foraging = next(skill for skill in created_xp["skills"] if skill["name"] == "Foraging")
        self.assertEqual(["intelligence"], created_foraging["secondary_attributes"])
        self.assertEqual(["exploration"], created_foraging["allowed_domains"])

    def test_status_effect_tools_apply_refresh_get_and_remove(self):
        applied = execute_status_effect_tool(
            self.character.id,
            "apply_status_effect",
            {
                "name": "Poisoned",
                "effect_type": "poison",
                "duration_turns": 3,
                "description": "Taking poison damage over time.",
                "source_text": "test vial",
            },
        )
        self.assertTrue(applied["success"], applied)
        self.assertEqual(1, len(applied["status_effects"]))
        self.assertEqual("Poisoned", applied["status_effects"][0]["name"])
        effect_id = applied["details"]["status_effect_id"]

        refreshed = execute_status_effect_tool(
            self.character.id,
            "apply_status_effect",
            {"name": "Poisoned", "effect_type": "poison", "duration_turns": 5},
        )
        self.assertTrue(refreshed["success"], refreshed)
        self.assertEqual(1, len(refreshed["status_effects"]))
        self.assertEqual(5, refreshed["status_effects"][0]["duration_remaining"])

        current = execute_status_effect_tool(self.character.id, "get_status_effects", {})
        self.assertTrue(current["success"], current)
        self.assertEqual(1, len(current["status_effects"]))

        removed = execute_status_effect_tool(
            self.character.id,
            "remove_status_effect",
            {"status_effect_id": effect_id},
        )
        self.assertTrue(removed["success"], removed)
        self.assertEqual([], removed["status_effects"])


if __name__ == "__main__":
    unittest.main()
