import json
import unittest

from flask import Flask

from models import (
    Campaign,
    CampaignLocation,
    CampaignNPC,
    Character,
    User,
    WorldTemplate,
    db,
)
from services.adventure_state.tools import (
    advance_time,
    claim_quest_rewards,
    create_quest,
    get_quest_details,
    turn_in_quest,
    update_location,
    update_quest_objective_progress,
    validate_quest_progress,
)
from services.currency.service import get_currency
from services.inventory.service import add_inventory_item, get_inventory


class QuestBackendTestCase(unittest.TestCase):
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

        self.user = User(
            username="tester",
            email="tester@example.com",
            password_hash="test",
        )
        self.character = Character(
            user=self.user,
            name="Nick",
            race="human",
            class_name="fighter",
            inventory_json="{}",
            currency_json={"gold": 0, "silver": 0, "copper": 0},
        )
        self.world = WorldTemplate(
            name="Test World",
            slug="test-world",
            description="World used for backend regression tests.",
            is_active=True,
        )
        db.session.add_all([self.user, self.character, self.world])
        db.session.flush()

        self.campaign = Campaign(
            character_id=self.character.id,
            world_template_id=self.world.id,
            title="Test Campaign",
            status="active",
        )
        db.session.add(self.campaign)
        db.session.flush()

        self.tavern = CampaignLocation(
            campaign_id=self.campaign.id,
            name="Screeching Rat Taproom",
            location_type="inn",
            description="A small inn taproom.",
            is_discovered=True,
            is_custom=True,
        )
        self.cellar = CampaignLocation(
            campaign_id=self.campaign.id,
            name="Screeching Rat Cellar",
            location_type="cellar",
            description="The inn cellar.",
            is_discovered=True,
            is_custom=True,
        )
        self.market = CampaignLocation(
            campaign_id=self.campaign.id,
            name="Market Square",
            location_type="market",
            description="A local market.",
            is_discovered=True,
            is_custom=True,
        )
        db.session.add_all([self.tavern, self.cellar, self.market])
        db.session.flush()

        self.innkeeper = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.tavern.id,
            name="Innkeeper Hagen",
            role="innkeeper",
            is_custom=True,
        )
        self.merchant = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.market.id,
            name="Merchant Torbin",
            role="merchant",
            is_custom=True,
        )
        db.session.add_all([self.innkeeper, self.merchant])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()

    def test_missing_currency_reward_is_filled_from_backend_rules(self):
        result = create_quest(
            campaign_id=self.campaign.id,
            title="Clear the Cellar",
            description="Remove the rats from the inn cellar.",
            quest_type="hunt",
            quest_giver_npc_id=self.innkeeper.id,
            start_location_id=self.tavern.id,
            target_location_id=self.cellar.id,
            turn_in_location_id=self.tavern.id,
            objectives_json=json.dumps([
                {
                    "objective_type": "kill_enemy_type",
                    "enemy_type": "rat",
                    "required_count": 6,
                }
            ]),
            quest_level=1,
            danger_level="low",
        )

        self.assertTrue(result["success"], result)
        quest = result["quest"]

        self.assertEqual(27, quest["rewards"]["xp"])
        self.assertEqual(
            {"gold": 0, "silver": 0, "copper": 22},
            quest["rewards"]["currency"],
        )
        self.assertEqual(22, quest["reward_rules"]["suggested_reward_value"])
        self.assertEqual(19, quest["reward_rules"]["reward_value_min"])
        self.assertEqual(25, quest["reward_rules"]["reward_value_max"])

    def test_location_time_and_quest_detail_tools(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Training Yard",
            location_type="yard",
            description="A small training yard behind the inn.",
        )
        self.assertTrue(moved["success"], moved)
        self.assertEqual("Training Yard", moved["location_name"])
        self.assertIsNotNone(moved["location_id"])

        reused = update_location(
            campaign_id=self.campaign.id,
            location_name="Training Yard",
            location_type="yard",
        )
        self.assertTrue(reused["success"], reused)
        self.assertEqual(moved["location_id"], reused["location_id"])

        advanced = advance_time(campaign_id=self.campaign.id, minutes=180)
        self.assertTrue(advanced["success"], advanced)
        self.assertEqual("morning", advanced["old_time"])
        self.assertEqual("noon", advanced["new_time"])

        quest_result = create_quest(
            campaign_id=self.campaign.id,
            title="Practice Swings",
            description="Complete three practice swings.",
            quest_type="tutorial",
            objectives_json=json.dumps([
                {
                    "objective_type": "kill_enemy_type",
                    "enemy_type": "training_dummy",
                    "required_count": 3,
                    "current_count": 0,
                }
            ]),
            rewards_json=json.dumps({
                "xp": 10,
                "currency": {"gold": 0, "silver": 0, "copper": 6},
            }),
            reward_rules_json=json.dumps({
                "xp_min": 1,
                "xp_max": 20,
                "reward_value_min": 1,
                "reward_value_max": 10,
            }),
        )
        self.assertTrue(quest_result["success"], quest_result)
        quest_id = quest_result["quest"]["id"]

        details = get_quest_details(campaign_id=self.campaign.id, quest_id=quest_id)
        self.assertTrue(details["success"], details)
        self.assertEqual("Practice Swings", details["quest"]["title"])

        progress = update_quest_objective_progress(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            objective_index=0,
            current_count=3,
            notes="All practice swings completed.",
        )
        self.assertTrue(progress["success"], progress)
        self.assertEqual("completed", progress["quest"]["status"])
        self.assertTrue(progress["quest"]["objectives"][0]["is_completed"])

    def test_overquoted_currency_reward_is_clamped_to_backend_range(self):
        result = create_quest(
            campaign_id=self.campaign.id,
            title="Sort the Storage Room",
            description="The innkeeper offers too much silver in narration.",
            quest_type="hunt",
            objectives_json=json.dumps([
                {
                    "objective_type": "kill_enemy_type",
                    "enemy_type": "rat",
                    "required_count": 1,
                }
            ]),
            rewards_json=json.dumps({
                "xp": 999,
                "currency": {"gold": 0, "silver": 5, "copper": 0},
            }),
            quest_level=1,
            danger_level="low",
        )

        self.assertTrue(result["success"], result)
        quest = result["quest"]

        self.assertEqual(31, quest["rewards"]["xp"])
        self.assertEqual(
            {"gold": 0, "silver": 0, "copper": 25},
            quest["rewards"]["currency"],
        )

    def test_cellar_objective_must_turn_in_at_tavern_not_target_location(self):
        result = create_quest(
            campaign_id=self.campaign.id,
            title="Rats in the Cellar",
            description="Kill six rats in the cellar and report back.",
            quest_type="hunt",
            quest_giver_npc_id=self.innkeeper.id,
            turn_in_npc_id=self.innkeeper.id,
            start_location_id=self.tavern.id,
            target_location_id=self.cellar.id,
            turn_in_location_id=self.tavern.id,
            objectives_json=json.dumps([
                {
                    "objective_type": "kill_enemy_type",
                    "enemy_type": "rat",
                    "required_count": 6,
                    "current_count": 6,
                    "is_completed": True,
                }
            ]),
            quest_level=1,
            danger_level="low",
        )
        quest_id = result["quest"]["id"]

        wrong_location = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.cellar.id,
            current_npc_id=self.innkeeper.id,
        )
        self.assertFalse(wrong_location["success"], wrong_location)
        self.assertEqual(
            "Quest must be turned in at a different location.",
            wrong_location["error"],
        )

        correct_location = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.tavern.id,
            current_npc_id=self.innkeeper.id,
        )
        self.assertTrue(correct_location["success"], correct_location)
        self.assertEqual("turned_in", correct_location["quest"]["status"])
        self.assertEqual({"gold": 0, "silver": 0, "copper": 22}, get_currency(self.character.id))
        self.assertEqual(27, self.character.xp)

    def test_delivery_turn_in_requires_recipient_and_consumes_item(self):
        item_result = add_inventory_item(
            character_id=self.character.id,
            item={
                "item_id": "sealed_letter",
                "name": "Sealed Letter",
                "description": "A sealed letter for Torbin.",
                "size": "tiny",
                "volume": 0.01,
                "weight": 0.01,
                "stackable": False,
                "hand_usage": "none",
                "item_type": "quest",
            },
            quantity=1,
        )
        self.assertTrue(item_result.success, item_result.message)

        result = create_quest(
            campaign_id=self.campaign.id,
            title="Letter to Torbin",
            description="Deliver a sealed letter to the merchant.",
            quest_type="delivery",
            quest_giver_npc_id=self.innkeeper.id,
            turn_in_npc_id=self.merchant.id,
            start_location_id=self.tavern.id,
            target_location_id=self.market.id,
            turn_in_location_id=self.market.id,
            objectives_json=json.dumps([
                {
                    "objective_type": "bring_item",
                    "item_name": "Sealed Letter",
                    "required_count": 1,
                },
                {
                    "objective_type": "talk_to_npc",
                    "npc_id": self.merchant.id,
                },
            ]),
            quest_level=1,
            danger_level="safe",
        )
        quest_id = result["quest"]["id"]

        wrong_npc = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.market.id,
            current_npc_id=self.innkeeper.id,
        )
        self.assertFalse(wrong_npc["success"], wrong_npc)
        self.assertEqual(
            "Quest must be turned in to a different NPC.",
            wrong_npc["error"],
        )

        progress = validate_quest_progress(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.market.id,
            current_npc_id=self.merchant.id,
        )
        self.assertTrue(progress["success"], progress)
        self.assertEqual("completed", progress["quest"]["status"])

        turn_in = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.market.id,
            current_npc_id=self.merchant.id,
        )
        self.assertTrue(turn_in["success"], turn_in)
        self.assertEqual({"gold": 0, "silver": 0, "copper": 14}, get_currency(self.character.id))
        self.assertEqual(17, self.character.xp)
        self.assertEqual(1, len(turn_in["consumed_items"]))
        self.assertTrue(turn_in["consumed_items"][0]["success"])

        inventory = get_inventory(self.character.id)
        carried_names = [
            item["name"]
            for container in inventory["inventory"]["containers"]
            for item in container.get("items", [])
        ]
        self.assertNotIn("Sealed Letter", carried_names)

    def test_service_reward_turn_in_can_be_claimed_later(self):
        result = create_quest(
            campaign_id=self.campaign.id,
            title="Earn Training Favor",
            description="Help the innkeeper in exchange for later training.",
            quest_type="tutorial",
            turn_in_location_id=self.tavern.id,
            objectives_json=json.dumps([
                {
                    "objective_type": "kill_enemy_type",
                    "enemy_type": "rat",
                    "required_count": 1,
                    "current_count": 1,
                    "is_completed": True,
                }
            ]),
            rewards_json=json.dumps({
                "xp": 10,
                "services": [
                    {
                        "service_type": "training",
                        "provider_npc_id": self.innkeeper.id,
                        "reward_value": 8,
                        "uses": 1,
                    }
                ],
            }),
            reward_rules_json=json.dumps({
                "xp_min": 1,
                "xp_max": 20,
                "reward_value_min": 1,
                "reward_value_max": 10,
            }),
        )
        self.assertTrue(result["success"], result)
        quest_id = result["quest"]["id"]

        turn_in = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.tavern.id,
        )
        self.assertTrue(turn_in["success"], turn_in)
        self.assertTrue(turn_in["needs_reward_claim"])
        self.assertIsNone(turn_in["reward_grants"])
        self.assertIsNone(turn_in["quest"]["reward_claimed_at"])

        claim = claim_quest_rewards(campaign_id=self.campaign.id, quest_id=quest_id)
        self.assertTrue(claim["success"], claim)
        self.assertIsNotNone(claim["quest"]["reward_claimed_at"])
        self.assertEqual(10, self.character.xp)


if __name__ == "__main__":
    unittest.main()
