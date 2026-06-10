import json
import unittest

from flask import Flask

from models import (
    Campaign,
    CampaignLocation,
    CampaignNPC,
    Character,
    CharacterAttribute,
    CharacterSkill,
    Merchant,
    SkillDefinition,
    User,
    WorldTemplate,
    db,
)
from services.skills.service import create_custom_skill
from services.status_effects import apply_status_effect
from services.equipment.service import equip_item
from services.adventure_state.tools import (
    attempt_surrender,
    attempt_ceasefire,
    attempt_spare,
    attempt_escape,
    advance_time,
    claim_quest_rewards,
    create_quest,
    get_combat_state,
    grant_combat_loot,
    get_quest_details,
    move_to_coordinates,
    perform_check,
    resolve_attack,
    rest,
    start_combat,
    spend_time,
    turn_in_quest,
    update_location,
    update_quest_objective_progress,
    validate_quest_progress,
    redeem_service_reward,
)
from services.currency.service import get_currency
from services.equipment import normalize_combat_attribute_value
from services.inventory.service import add_inventory_item, get_inventory
from services.merchants.service import buy_item_from_merchant, buy_merchant_service, get_merchant_inventory, get_merchants_at_location, sell_item_to_merchant
from services.resources.service import get_resources
from services.skills import ensure_core_skill_definitions
from services.trainers.service import get_trainers_at_location, train_with_teacher


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
        ensure_core_skill_definitions()

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

        self.attributes = CharacterAttribute(
            character_id=self.character.id,
            strength=6,
            dexterity=6,
            constitution=6,
            intelligence=6,
            perception=6,
            charisma=6,
        )
        db.session.add(self.attributes)

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

    def _set_skill_level(self, skill_name: str, level: int):
        skill = SkillDefinition.query.filter_by(name=skill_name, is_active=True).first()
        self.assertIsNotNone(skill)
        row = CharacterSkill.query.filter_by(
            character_id=self.character.id,
            skill_id=skill.id,
        ).first()
        if not row:
            row = CharacterSkill(
                character_id=self.character.id,
                skill_id=skill.id,
                skill_level=0,
                skill_xp=0,
                bonus_modifier=0,
            )
            db.session.add(row)
            db.session.flush()
        row.skill_level = int(level)
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
        self.assertEqual(540, advanced["old_minute"])
        self.assertEqual(720, advanced["new_minute"])
        self.assertEqual(1, advanced["old_day"])
        self.assertEqual(1, advanced["new_day"])

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

    def test_advance_time_uses_exact_minutes_and_rolls_days(self):
        self.campaign.current_ingame_day = 1
        self.campaign.current_ingame_minute = 23 * 60
        self.campaign.current_ingame_time = "night"
        db.session.commit()

        advanced = advance_time(campaign_id=self.campaign.id, minutes=180)

        self.assertTrue(advanced["success"], advanced)
        self.assertEqual(1, advanced["old_day"])
        self.assertEqual(2, advanced["new_day"])
        self.assertEqual(1380, advanced["old_minute"])
        self.assertEqual(120, advanced["new_minute"])
        self.assertEqual("night", advanced["old_time"])
        self.assertEqual("midnight", advanced["new_time"])
        self.assertEqual(1143, advanced["old_calendar"]["year"])
        self.assertEqual("Suncrest", advanced["old_calendar"]["month_name"])
        self.assertEqual(12, advanced["old_calendar"]["day_of_month"])
        self.assertEqual(1143, advanced["new_calendar"]["year"])
        self.assertEqual("Suncrest", advanced["new_calendar"]["month_name"])
        self.assertEqual(13, advanced["new_calendar"]["day_of_month"])

    def test_spend_time_uses_backend_action_defaults_and_clamps_minutes(self):
        quick_search = spend_time(
            campaign_id=self.campaign.id,
            action_type="quick_search",
        )
        self.assertTrue(quick_search["success"], quick_search)
        self.assertEqual(2, quick_search["minutes_advanced"])

        shopping = spend_time(
            campaign_id=self.campaign.id,
            action_type="shopping",
            minutes=30,
        )
        self.assertTrue(shopping["success"], shopping)
        self.assertEqual(5, shopping["minutes_advanced"])

        conversation = spend_time(
            campaign_id=self.campaign.id,
            action_type="conversation",
        )
        self.assertTrue(conversation["success"], conversation)
        self.assertEqual(0, conversation["minutes_advanced"])

    def test_rest_advances_short_rest_and_sleep_until_morning(self):
        short_rest = rest(campaign_id=self.campaign.id, rest_type="short")
        self.assertTrue(short_rest["success"], short_rest)
        self.assertEqual(30, short_rest["minutes_advanced"])

        self.campaign.current_ingame_day = 1
        self.campaign.current_ingame_minute = 20 * 60
        self.campaign.current_ingame_time = "night"
        db.session.commit()

        sleep = rest(campaign_id=self.campaign.id, rest_type="sleep_until_morning")
        self.assertTrue(sleep["success"], sleep)
        self.assertEqual(13 * 60, sleep["minutes_advanced"])
        self.assertEqual(2, sleep["new_day"])
        self.assertEqual("morning", sleep["new_time"])

    def test_update_location_resolves_world_coordinates_and_inherits_local_context(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)
        self.assertEqual("Willowbrook", moved["location_name"])
        self.assertEqual("crownfields", moved["location_context"]["region_id"])
        self.assertEqual(48.4, moved["location_context"]["coordinate_x"])
        self.assertEqual(48.1, moved["location_context"]["coordinate_y"])

        cellar = update_location(
            campaign_id=self.campaign.id,
            location_name="The Screeching Rat - Cellar",
            location_type="cellar",
            description="A cellar under the local tavern.",
        )
        self.assertTrue(cellar["success"], cellar)
        self.assertEqual("inherited", cellar["location_context"]["coordinate_source"])
        self.assertEqual(48.4, cellar["location_context"]["coordinate_x"])
        self.assertEqual(48.1, cellar["location_context"]["coordinate_y"])
        self.assertEqual("crownfields", cellar["location_context"]["region_id"])
        self.assertIsNone(cellar["location_context"]["world_location_id"])

    def test_update_location_coordinate_move_changes_region_context(self):
        crownfields_move = update_location(
            campaign_id=self.campaign.id,
            location_name="Road near Duskmire Watch",
            location_type="road",
            coordinate_x=76.0,
            coordinate_y=61.0,
        )
        self.assertTrue(crownfields_move["success"], crownfields_move)
        self.assertEqual("crownfields", crownfields_move["location_context"]["region_id"])
        self.assertEqual("Duskmire Fringe", crownfields_move["location_context"]["subregion"])

        grimscar_move = update_location(
            campaign_id=self.campaign.id,
            location_name="Redrock Border Road",
            location_type="road",
            coordinate_x=86.7,
            coordinate_y=55.2,
        )
        self.assertTrue(grimscar_move["success"], grimscar_move)
        self.assertEqual("grimscar_wastes", grimscar_move["location_context"]["region_id"])
        self.assertEqual("Redrock Border", grimscar_move["location_context"]["subregion"])

    def test_move_to_coordinates_validates_distance_and_updates_current_location(self):
        start = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(start["success"], start)

        nearby_move = move_to_coordinates(
            campaign_id=self.campaign.id,
            destination_name="Greenwatch Road",
            location_type="road",
            coordinate_x=49.80049,
            coordinate_y=41.00049,
            travel_mode="walk",
        )
        self.assertTrue(nearby_move["success"], nearby_move)
        self.assertEqual("move_to_coordinates", nearby_move["tool"])
        self.assertEqual("Greenwatch Edge", nearby_move["location_context"]["subregion"])
        self.assertEqual(49.8, nearby_move["location_context"]["coordinate_x"])
        self.assertEqual(41.0, nearby_move["location_context"]["coordinate_y"])
        self.assertLessEqual(nearby_move["movement"]["distance_km"], 80)
        self.assertEqual(nearby_move["location_id"], self.campaign.current_location_id)

        far_move = move_to_coordinates(
            campaign_id=self.campaign.id,
            destination_name="Redrock Pass",
            world_location_id="redrock_pass",
            travel_mode="walk",
        )
        self.assertFalse(far_move["success"], far_move)
        self.assertIn("too far", far_move["error"])
        self.assertTrue(far_move["movement"]["requires_smaller_steps"])

        long_move = move_to_coordinates(
            campaign_id=self.campaign.id,
            destination_name="Redrock Pass",
            world_location_id="redrock_pass",
            travel_mode="cart",
            allow_long_travel=True,
        )
        self.assertTrue(long_move["success"], long_move)
        self.assertEqual("grimscar_wastes", long_move["location_context"]["region_id"])
        self.assertEqual("redrock_pass", long_move["location_context"]["world_location_id"])

    def test_move_to_coordinates_returns_backend_travel_time_estimate(self):
        start = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(start["success"], start)

        moved = move_to_coordinates(
            campaign_id=self.campaign.id,
            destination_name="Greenwatch",
            world_location_id="greenwatch",
            travel_mode="walk",
        )

        self.assertTrue(moved["success"], moved)
        self.assertEqual(74.0, moved["movement"]["distance_km"])
        self.assertEqual(799, moved["movement"]["estimated_minutes"])
        self.assertEqual(1, moved["time"]["old_day"])
        self.assertEqual(1, moved["time"]["new_day"])
        self.assertEqual("morning", moved["time"]["old_time"])
        self.assertEqual("night", moved["time"]["new_time"])
        self.assertEqual("travel_edge", moved["movement"]["travel_estimate"]["distance_source"])
        self.assertEqual("road", moved["movement"]["travel_estimate"]["route_mode"])

    def test_perform_check_uses_skill_mapping_and_secondary_attributes(self):
        self.character.level = 10
        self.attributes.dexterity = 15
        self.attributes.intelligence = 6
        db.session.commit()
        self._set_skill_level("Lockpicking", 95)

        result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Pick the merchant lockbox",
            action_type="lockpicking",
            skill_name="Lockpicking",
            challenge_level=75,
            challenge_type="master",
            include_character_level=True,
            forced_roll=20,
        )

        self.assertTrue(result["success"], result)
        check = result["check"]
        self.assertEqual("dexterity", check["primary_attribute"]["key"])
        self.assertEqual("Lockpicking", check["skill_name"])
        self.assertTrue(any(item["key"] == "intelligence" for item in check["secondary_attributes"]))
        self.assertGreaterEqual(check["success_chance_percent"], 0)
        self.assertLessEqual(check["success_chance_percent"], 100)
        self.assertIn(
            check["outcome"],
            {
                "critical_failure",
                "failure",
                "partial_success",
                "success",
                "strong_success",
                "critical_success",
            },
        )

    def test_perform_check_arcane_lore_has_no_secondary_attributes(self):
        self.character.level = 10
        self.attributes.intelligence = 15
        db.session.commit()
        self._set_skill_level("Arcane Lore", 95)

        result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Decode an ancient rune circle",
            action_type="arcane_lore",
            skill_name="Arcane Lore",
            challenge_level=90,
            challenge_type="legendary",
            include_character_level=True,
            forced_roll=20,
        )

        self.assertTrue(result["success"], result)
        check = result["check"]
        self.assertEqual("intelligence", check["primary_attribute"]["key"])
        self.assertEqual([], check["secondary_attributes"])
        self.assertEqual("Arcane Lore", check["skill_name"])

    def test_perform_check_custom_skill_respects_allowed_domains(self):
        created = create_custom_skill(
            character_id=self.character.id,
            name="Rune Tinkering",
            linked_attribute="intelligence",
            secondary_attributes=["dexterity"],
            allowed_domains=["crafting"],
        )
        self.assertTrue(created["success"], created)
        self._set_skill_level("Rune Tinkering", 30)

        allowed = perform_check(
            campaign_id=self.campaign.id,
            action_text="Stabilize the rune housing",
            action_type="crafting",
            skill_name="Rune Tinkering",
            challenge_level=40,
            challenge_type="normal",
            include_character_level=True,
            forced_roll=15,
        )
        self.assertTrue(allowed["success"], allowed)
        self.assertEqual(["crafting"], allowed["check"]["skill_allowed_domains"])
        self.assertEqual("intelligence", allowed["check"]["primary_attribute"]["key"])
        self.assertTrue(any(item["key"] == "dexterity" for item in allowed["check"]["secondary_attributes"]))

        blocked = perform_check(
            campaign_id=self.campaign.id,
            action_text="Sweet-talk a city guard",
            action_type="social",
            skill_name="Rune Tinkering",
            challenge_level=20,
            challenge_type="easy",
            include_character_level=True,
            forced_roll=15,
        )
        self.assertFalse(blocked["success"], blocked)
        self.assertIn("not allowed for action domain", blocked["error"])

    def test_combat_start_resolve_and_state_payload(self):
        self.character.level = 20
        self.attributes.strength = 18
        self.attributes.dexterity = 12
        self.attributes.constitution = 16
        db.session.commit()

        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([
                {
                    "name": "Cellar Rat",
                    "hp": 80,
                    "attack_score": 26,
                    "dodge_score": 18,
                    "block_score": 10,
                    "damage_min": 8,
                    "damage_max": 12,
                }
            ]),
        )
        self.assertTrue(started["success"], started)
        self.assertTrue(started["combat"]["active"])
        self.assertTrue(started["combat"]["combat_ongoing"])
        self.assertEqual(1, len(started["combat"]["enemies"]))
        self.assertIn(started["combat"]["turn_order"][0], {"player", "enemies"})

        state_before = get_combat_state(self.campaign.id)
        self.assertTrue(state_before["success"], state_before)
        self.assertTrue(state_before["combat"]["combat_ongoing"])
        self.assertEqual(1, state_before["combat"]["enemy_count_alive"])
        self.assertIn(state_before["combat"]["current_actor"], {"player", "enemies"})

        actor = state_before["combat"]["current_actor"]
        resolved = resolve_attack(
            campaign_id=self.campaign.id,
            attacker_side=actor,
        )
        self.assertTrue(resolved["success"], resolved)
        self.assertEqual(resolved["combat"]["combat_ongoing"], resolved["combat"]["active"])
        self.assertIn(resolved["combat"]["last_event"]["outcome"], {"clear_dodge", "clear_block", "partial_hit", "full_hit"})
        self.assertIn("dealt_damage", resolved["combat"]["last_event"])

    def test_combat_escape_reports_success_or_failure(self):
        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([{"name": "Bandit", "hp": 90, "attack_score": 30}]),
        )
        self.assertTrue(started["success"], started)

        escaped = attempt_escape(self.campaign.id)
        self.assertTrue(escaped["success"], escaped)
        self.assertIn("escaped", escaped)
        if escaped["escaped"]:
            self.assertFalse(escaped["combat"]["active"])
        else:
            self.assertTrue(escaped["combat"]["active"])

    def test_combat_surrender_allowed_and_refused(self):
        refused_start = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([{"name": "Bandit", "hp": 90, "attack_score": 30, "allows_surrender": False}]),
        )
        self.assertTrue(refused_start["success"], refused_start)
        refused = attempt_surrender(self.campaign.id)
        self.assertFalse(refused["success"], refused)
        self.assertTrue(refused["combat"]["combat_ongoing"])
        self.assertIn("refuse surrender", refused["error"].lower())

        # Reset by forcing combat cleanup for next scenario.
        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        notes.pop("combat_state", None)
        if campaign.state:
            campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        allowed_start = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([{"name": "City Guard", "hp": 120, "attack_score": 32, "allows_surrender": True, "surrender_outcome": "captured"}]),
        )
        self.assertTrue(allowed_start["success"], allowed_start)
        accepted = attempt_surrender(self.campaign.id)
        self.assertTrue(accepted["success"], accepted)
        self.assertTrue(accepted["surrendered"])
        self.assertEqual("captured", accepted["surrender_outcome"])
        self.assertFalse(accepted["combat"]["combat_ongoing"])

    def test_combat_spare_requires_weakened_target_and_ends_if_last_enemy(self):
        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([
                {
                    "name": "Highway Bandit",
                    "hp": 100,
                    "attack_score": 28,
                    "dodge_score": 16,
                    "block_score": 10,
                    "allows_spare": True,
                    "spare_outcome": "released",
                }
            ]),
        )
        self.assertTrue(started["success"], started)

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["current_turn_index"] = combat["turn_order"].index("player")
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        too_early = attempt_spare(self.campaign.id, target_enemy_id="enemy_1")
        self.assertFalse(too_early["success"], too_early)
        self.assertIn("not weakened", too_early["error"].lower())
        self.assertTrue(too_early["combat"]["combat_ongoing"])

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["current_turn_index"] = combat["turn_order"].index("player")
        combat["enemies"][0]["hp_current"] = 20  # 20%
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        spared = attempt_spare(self.campaign.id, target_enemy_id="enemy_1")
        self.assertTrue(spared["success"], spared)
        self.assertTrue(spared["spared"])
        self.assertEqual("released", spared["spare_outcome"])
        self.assertFalse(spared["combat"]["combat_ongoing"])
        self.assertEqual("enemies_spared_or_defeated", spared["combat"]["last_event"]["combat_result"])

    def test_combat_ceasefire_allowed_and_refused(self):
        refused_start = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([{"name": "Raider", "hp": 95, "attack_score": 29, "allows_ceasefire": False}]),
        )
        self.assertTrue(refused_start["success"], refused_start)

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["current_turn_index"] = combat["turn_order"].index("player")
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        refused = attempt_ceasefire(self.campaign.id)
        self.assertFalse(refused["success"], refused)
        self.assertTrue(refused["combat"]["combat_ongoing"])
        self.assertIn("refuse", refused["error"].lower())

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        notes.pop("combat_state", None)
        if campaign.state:
            campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        allowed_start = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([
                {"name": "Duelist", "hp": 110, "attack_score": 33, "allows_ceasefire": True, "ceasefire_outcome": "truce"}
            ]),
        )
        self.assertTrue(allowed_start["success"], allowed_start)

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["current_turn_index"] = combat["turn_order"].index("player")
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        accepted = attempt_ceasefire(self.campaign.id)
        self.assertTrue(accepted["success"], accepted)
        self.assertTrue(accepted["ceasefire"])
        self.assertEqual("truce", accepted["ceasefire_outcome"])
        self.assertFalse(accepted["combat"]["combat_ongoing"])
        self.assertEqual("ceasefire", accepted["combat"]["last_event"]["combat_result"])

    def test_archetype_rat_has_fixed_hp_and_defeated_loot_is_granted_once(self):
        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([
                {"name": "Cellar Rat", "archetype_id": "rat", "level": 9},
            ]),
        )
        self.assertTrue(started["success"], started)
        self.assertEqual(5, started["combat"]["enemies"][0]["hp_max"])

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["active"] = False
        combat["enemies"][0]["status"] = "defeated"
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        granted = grant_combat_loot(self.campaign.id)
        self.assertTrue(granted["success"], granted)
        self.assertEqual(1, granted["granted_enemy_count"])

        granted_again = grant_combat_loot(self.campaign.id)
        self.assertTrue(granted_again["success"], granted_again)
        self.assertEqual(0, granted_again["granted_enemy_count"])

    def test_blessed_improves_check_total_value(self):
        base_result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Negotiate calmly with the merchant",
            action_type="social",
            challenge_level=30,
            challenge_type="normal",
            primary_attribute="charisma",
            include_character_level=True,
            forced_roll=10,
        )
        self.assertTrue(base_result["success"], base_result)

        applied = apply_status_effect(
            character_id=self.character.id,
            name="Blessed",
            effect_type="buff",
            duration_turns=2,
        ).to_dict()
        self.assertTrue(applied["success"], applied)

        blessed_result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Negotiate calmly with the merchant",
            action_type="social",
            challenge_level=30,
            challenge_type="normal",
            primary_attribute="charisma",
            include_character_level=True,
            forced_roll=10,
        )
        self.assertTrue(blessed_result["success"], blessed_result)
        self.assertGreater(
            blessed_result["check"]["total_value"],
            base_result["check"]["total_value"],
        )
        self.assertGreater(
            blessed_result["check"]["score_breakdown"]["status_component"],
            0,
        )

    def test_high_quality_ring_improves_social_check_via_effective_attribute(self):
        added = add_inventory_item(
            character_id=self.character.id,
            item={
                "item_id": "silver_tongue_ring",
                "name": "Silver Tongue Ring",
                "description": "A refined ring worn by practiced negotiators.",
                "size": "tiny",
                "volume": 0.1,
                "weight": 0.1,
                "stackable": False,
                "hand_usage": "none",
                "item_type": "ring",
                "item_level": 45,
                "rarity": "epic",
            },
            quantity=1,
        ).to_dict()
        self.assertTrue(added["success"], added)

        equipped = equip_item(
            character_id=self.character.id,
            item_id="silver_tongue_ring",
            slot="ring_left",
        ).to_dict()
        self.assertTrue(equipped["success"], equipped)

        result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Negotiate a better room price",
            action_type="social",
            challenge_level=30,
            challenge_type="normal",
            primary_attribute="charisma",
            include_character_level=True,
            forced_roll=10,
        )
        self.assertTrue(result["success"], result)
        self.assertGreater(
            result["check"]["primary_attribute"]["value"],
            6,
        )

    def test_over_100_effective_attribute_still_improves_checks(self):
        self.attributes.charisma = 100
        db.session.commit()

        added = add_inventory_item(
            character_id=self.character.id,
            item={
                "item_id": "artifact_diplomat_ring",
                "name": "Artifact Diplomat Ring",
                "description": "A ring that pushes social grace past the natural limit.",
                "size": "tiny",
                "volume": 0.1,
                "weight": 0.1,
                "stackable": False,
                "hand_usage": "none",
                "item_type": "ring",
                "item_level": 100,
                "rarity": "artifact",
            },
            quantity=1,
        ).to_dict()
        self.assertTrue(added["success"], added)

        equipped = equip_item(
            character_id=self.character.id,
            item_id="artifact_diplomat_ring",
            slot="ring_left",
        ).to_dict()
        self.assertTrue(equipped["success"], equipped)

        result = perform_check(
            campaign_id=self.campaign.id,
            action_text="Broker peace between two rival merchants",
            action_type="social",
            challenge_level=70,
            challenge_type="hard",
            primary_attribute="charisma",
            include_character_level=True,
            forced_roll=10,
        )
        self.assertTrue(result["success"], result)
        self.assertGreater(result["check"]["primary_attribute"]["value"], 100)
        self.assertGreater(
            result["check"]["primary_attribute"]["effective"],
            normalize_combat_attribute_value(100),
        )

    def test_spend_time_ticks_poison_and_reduces_hp(self):
        applied = apply_status_effect(
            character_id=self.character.id,
            name="Poisoned",
            effect_type="poison",
            duration_turns=2,
        ).to_dict()
        self.assertTrue(applied["success"], applied)

        before = get_resources(self.character.id)
        spent = spend_time(
            campaign_id=self.campaign.id,
            action_type="quick_search",
            minutes=2,
            description="Search the room quickly",
        )
        self.assertTrue(spent["success"], spent)
        self.assertIn("status_tick", spent)
        after = get_resources(self.character.id)
        self.assertLess(after["hp"]["current"], before["hp"]["current"])

    def test_stunned_player_skips_combat_action(self):
        applied = apply_status_effect(
            character_id=self.character.id,
            name="Stunned",
            effect_type="condition",
            duration_turns=1,
        ).to_dict()
        self.assertTrue(applied["success"], applied)

        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([{"name": "Bandit", "archetype_id": "bandit", "level": 6}]),
        )
        self.assertTrue(started["success"], started)

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["current_turn_index"] = combat["turn_order"].index("player")
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        resolved = resolve_attack(campaign_id=self.campaign.id, attacker_side="player")
        self.assertTrue(resolved["success"], resolved)
        self.assertEqual("attack_skipped", resolved["combat"]["last_event"]["type"])
        self.assertIn("status_effect_prevents_action", resolved["combat"]["last_event"]["reason"])

    def test_humanoid_combat_loot_grants_xp_and_money_profile(self):
        started = start_combat(
            campaign_id=self.campaign.id,
            enemies_json=json.dumps([
                {"name": "City Guard", "archetype_id": "guard", "level": 25},
            ]),
        )
        self.assertTrue(started["success"], started)

        campaign = db.session.get(Campaign, self.campaign.id)
        notes = json.loads(campaign.state.notes_json or "{}") if campaign.state and campaign.state.notes_json else {}
        combat = notes.get("combat_state", {})
        combat["active"] = False
        combat["enemies"][0]["status"] = "defeated"
        notes["combat_state"] = combat
        campaign.state.notes_json = json.dumps(notes)
        db.session.commit()

        granted = grant_combat_loot(self.campaign.id)
        self.assertTrue(granted["success"], granted)
        self.assertGreater(granted["xp_total"], 0)
        self.assertIsNotNone(granted["xp_result"])
        self.assertIn(granted["granted_enemies"][0]["reward_role"], {"humanoid_guard", "humanoid_raider", "humanoid_elite"})
        total_money = (
            int(granted["currency"].get("gold", 0)) * 1000
            + int(granted["currency"].get("silver", 0)) * 50
            + int(granted["currency"].get("copper", 0))
        )
        self.assertGreater(total_money, 0)

    def test_quest_location_ids_serialize_coordinate_context(self):
        start = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        target = update_location(
            campaign_id=self.campaign.id,
            location_name="Redrock Pass",
            location_type="border_pass",
            world_location_id="redrock_pass",
        )
        self.assertTrue(start["success"], start)
        self.assertTrue(target["success"], target)

        result = create_quest(
            campaign_id=self.campaign.id,
            title="Scout the Border",
            description="Travel from Willowbrook to Redrock Pass and report back.",
            quest_type="travel",
            start_location_id=start["location_id"],
            target_location_id=target["location_id"],
            turn_in_location_id=start["location_id"],
            objectives_json=json.dumps([
                {
                    "objective_type": "reach_location",
                    "location_id": target["location_id"],
                }
            ]),
            quest_level=1,
            danger_level="moderate",
        )
        self.assertTrue(result["success"], result)

        location_refs = result["quest"]["location_refs"]
        self.assertEqual("Willowbrook", location_refs["start"]["name"])
        self.assertEqual("crownfields", location_refs["start"]["location_context"]["region_id"])
        self.assertEqual("Redrock Pass", location_refs["target"]["name"])
        self.assertEqual("grimscar_wastes", location_refs["target"]["location_context"]["region_id"])
        self.assertEqual("Redrock Border", location_refs["target"]["location_context"]["subregion"])

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
        self.assertIsNone(claim["quest"]["reward_claimed_at"])
        self.assertEqual(10, self.character.xp)
        self.assertTrue(claim["claimable_services"])

    def test_redeem_training_service_reward_uses_trainer_rules(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)

        trainer = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.campaign.current_location_id,
            name="Master Halric",
            role="blacksmith",
            is_custom=True,
            state_json=json.dumps({
                "trainer_profile": {
                    "trainer_tier": 5,
                    "max_trainable_level": 100,
                    "patterns": ["combat_axe", "physical_craft"],
                    "specialties": ["Axes & Hammers"],
                    "attributes": ["strength", "constitution"],
                }
            }),
        )
        db.session.add(trainer)
        db.session.commit()

        result = create_quest(
            campaign_id=self.campaign.id,
            title="Forge Yard Duty",
            description="Help in the forge yard for a lesson instead of coin.",
            quest_type="tutorial",
            turn_in_location_id=self.campaign.current_location_id,
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
                "xp": 6,
                "services": [
                    {
                        "service_type": "training",
                        "service_name": "One Smithing Lesson",
                        "provider_npc_id": trainer.id,
                        "reward_value": 8,
                        "uses": 1,
                        "details": {
                            "skill_name": "Axes & Hammers",
                            "training_type": "skill",
                            "minutes": 60,
                        },
                    }
                ],
            }),
        )
        self.assertTrue(result["success"], result)
        quest_id = result["quest"]["id"]

        turn_in = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.campaign.current_location_id,
        )
        self.assertTrue(turn_in["success"], turn_in)

        claim = claim_quest_rewards(campaign_id=self.campaign.id, quest_id=quest_id)
        self.assertTrue(claim["success"], claim)
        reward_service_id = claim["claimable_services"][0]["reward_service_id"]

        redeemed = redeem_service_reward(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            reward_service_id=reward_service_id,
            current_npc_id=trainer.id,
        )
        self.assertTrue(redeemed["success"], redeemed)
        self.assertFalse(redeemed["redemption_result"]["price_charged"])
        self.assertEqual("train_with_teacher", redeemed["redemption_result"]["tool"])
        self.assertIsNotNone(redeemed["quest"]["reward_claimed_at"])

    def test_redeem_lodging_service_reward_uses_merchant_service_without_charge(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)

        merchants = get_merchants_at_location(self.campaign.id)
        innkeeper = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "innkeeper")

        result = create_quest(
            campaign_id=self.campaign.id,
            title="Late Shift at the Taproom",
            description="Help the innkeeper and sleep here afterward.",
            quest_type="tutorial",
            turn_in_location_id=self.campaign.current_location_id,
            turn_in_npc_id=innkeeper["merchant_npc_id"],
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
                "services": [
                    {
                        "service_type": "lodging",
                        "service_name": "One Night Bed",
                        "provider_npc_id": innkeeper["merchant_npc_id"],
                        "reward_value": 8,
                        "uses": 1,
                        "details": {
                            "service_id": "cheap_bed",
                        },
                    }
                ],
            }),
        )
        self.assertTrue(result["success"], result)
        quest_id = result["quest"]["id"]

        self.campaign.current_ingame_day = 1
        self.campaign.current_ingame_minute = 20 * 60
        self.campaign.current_ingame_time = "night"
        db.session.commit()

        turn_in = turn_in_quest(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            current_location_id=self.campaign.current_location_id,
            current_npc_id=innkeeper["merchant_npc_id"],
        )
        self.assertTrue(turn_in["success"], turn_in)

        claim = claim_quest_rewards(campaign_id=self.campaign.id, quest_id=quest_id)
        self.assertTrue(claim["success"], claim)

        redeemed = redeem_service_reward(
            campaign_id=self.campaign.id,
            quest_id=quest_id,
            reward_service_id=claim["claimable_services"][0]["reward_service_id"],
            current_npc_id=innkeeper["merchant_npc_id"],
        )
        self.assertTrue(redeemed["success"], redeemed)
        self.assertEqual("buy_merchant_service", redeemed["redemption_result"]["tool"])
        self.assertFalse(redeemed["redemption_result"]["price_charged"])
        self.assertEqual("morning", redeemed["redemption_result"]["time_result"]["new_time"])

    def test_fixed_location_merchants_are_created_and_inventory_is_lazy_refreshed(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)

        merchants = get_merchants_at_location(self.campaign.id)
        self.assertTrue(merchants["success"], merchants)
        self.assertTrue(any(entry["merchant_type"] == "blacksmith" for entry in merchants["merchants"]))
        self.assertTrue(any(entry["merchant_type"] == "innkeeper" for entry in merchants["merchants"]))

        blacksmith = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "blacksmith")
        inventory = get_merchant_inventory(self.campaign.id, blacksmith["merchant_npc_id"])
        self.assertTrue(inventory["success"], inventory)
        self.assertTrue(inventory["inventory"])
        self.assertTrue(any(entry["generated_ingame_day"] == 0 for entry in inventory["inventory"]))
        self.assertTrue(any(entry["generated_ingame_day"] == self.campaign.current_ingame_day for entry in inventory["inventory"]))

    def test_generated_blacksmith_npc_is_onboarded_as_merchant(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Dustmarket",
            location_type="market",
            description="A custom market district with locally generated NPCs.",
        )
        self.assertTrue(moved["success"], moved)

        smith = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.campaign.current_location_id,
            name="Rurik Ashhand",
            role="smith",
            description="A soot-covered smith from a dynamically generated bazaar.",
            is_custom=True,
        )
        db.session.add(smith)
        db.session.commit()

        inventory = get_merchant_inventory(self.campaign.id, smith.id)
        self.assertTrue(inventory["success"], inventory)
        self.assertEqual("blacksmith", inventory["merchant"]["merchant_type"])
        self.assertTrue(any(entry["name"] == "Work Knife" for entry in inventory["inventory"]))
        self.assertIsNotNone(Merchant.query.filter_by(campaign_npc_id=smith.id).first())

    def test_generated_pattern_merchant_is_listed_with_backend_inventory_rules(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Moonmarket Court",
            location_type="city",
            description="A custom district known for strange scholars and traders.",
        )
        self.assertTrue(moved["success"], moved)

        occult_merchant = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.campaign.current_location_id,
            name="Sel Veyra",
            role="ritual broker",
            description="A generated merchant dealing in arcane curios.",
            is_custom=True,
            state_json=json.dumps({
                "merchant_profile": {
                    "merchant_pattern": "magic_arcane",
                }
            }),
        )
        db.session.add(occult_merchant)
        db.session.commit()

        merchants = get_merchants_at_location(self.campaign.id)
        self.assertTrue(merchants["success"], merchants)
        listed = next(entry for entry in merchants["merchants"] if entry["merchant_npc_id"] == occult_merchant.id)
        self.assertEqual("arcane_vendor", listed["merchant_type"])

        inventory = get_merchant_inventory(self.campaign.id, occult_merchant.id)
        self.assertTrue(inventory["success"], inventory)
        self.assertTrue(any(entry["item_type"] == "weapon" for entry in inventory["inventory"]))
        self.assertTrue(any(entry["generated_ingame_day"] == self.campaign.current_ingame_day for entry in inventory["inventory"]))

    def test_buy_item_from_merchant_adds_inventory_and_removes_money(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 0, "silver": 1, "copper": 20}
        db.session.commit()

        merchants = get_merchants_at_location(self.campaign.id)
        general_goods = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "general_goods")
        inventory = get_merchant_inventory(self.campaign.id, general_goods["merchant_npc_id"])
        item_entry = next(entry for entry in inventory["inventory"] if entry["name"] == "Torch")

        before_currency = get_currency(self.character.id)
        bought = buy_item_from_merchant(
            self.campaign.id,
            general_goods["merchant_npc_id"],
            item_entry["merchant_inventory_id"],
            quantity=2,
        )
        self.assertTrue(bought["success"], bought)
        after_currency = get_currency(self.character.id)
        self.assertLess(
            (after_currency["gold"] * 1000) + (after_currency["silver"] * 50) + after_currency["copper"],
            (before_currency["gold"] * 1000) + (before_currency["silver"] * 50) + before_currency["copper"],
        )

        inventory_after = get_inventory(self.character.id)
        carried_names = [
            item["name"]
            for container in inventory_after["inventory"]["containers"]
            for item in container.get("items", [])
        ]
        self.assertIn("Torch", carried_names)

    def test_sell_item_to_merchant_pays_currency_and_removes_item(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)

        added = add_inventory_item(
            character_id=self.character.id,
            item={
                "item_id": "spare_rope",
                "name": "Spare Rope",
                "description": "A spare coil of rope to sell.",
                "size": "small",
                "volume": 0.8,
                "weight": 1.2,
                "stackable": False,
                "hand_usage": "none",
                "item_type": "utility",
                "value_copper": 60,
            },
            quantity=1,
        )
        self.assertTrue(added.success, added.message)

        merchants = get_merchants_at_location(self.campaign.id)
        general_goods = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "general_goods")
        before_currency = get_currency(self.character.id)
        sold = sell_item_to_merchant(
            self.campaign.id,
            general_goods["merchant_npc_id"],
            "spare_rope",
            quantity=1,
        )
        self.assertTrue(sold["success"], sold)
        after_currency = get_currency(self.character.id)
        self.assertGreater(
            (after_currency["gold"] * 1000) + (after_currency["silver"] * 50) + after_currency["copper"],
            (before_currency["gold"] * 1000) + (before_currency["silver"] * 50) + before_currency["copper"],
        )

        inventory_after = get_inventory(self.character.id)
        carried_names = [
            item["name"]
            for container in inventory_after["inventory"]["containers"]
            for item in container.get("items", [])
        ]
        self.assertNotIn("Spare Rope", carried_names)

    def test_buy_merchant_service_meal_spends_time_and_money(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 0, "silver": 1, "copper": 20}
        db.session.commit()

        merchants = get_merchants_at_location(self.campaign.id)
        innkeeper = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "innkeeper")
        meal = next(service for service in innkeeper["service_offers"] if service["service_id"] == "hot_meal")

        before_currency = get_currency(self.character.id)
        before_minute = self.campaign.current_ingame_minute
        result = buy_merchant_service(
            self.campaign.id,
            innkeeper["merchant_npc_id"],
            meal["service_id"],
        )
        self.assertTrue(result["success"], result)
        after_currency = get_currency(self.character.id)
        self.assertLess(
            (after_currency["gold"] * 1000) + (after_currency["silver"] * 50) + after_currency["copper"],
            (before_currency["gold"] * 1000) + (before_currency["silver"] * 50) + before_currency["copper"],
        )
        self.assertEqual("spend_time", result["time_result"]["tool"])
        self.assertGreater(result["time_result"]["new_minute"], before_minute)

    def test_buy_merchant_service_bed_advances_to_morning(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 0, "silver": 2, "copper": 0}
        self.campaign.current_ingame_day = 1
        self.campaign.current_ingame_minute = 20 * 60
        self.campaign.current_ingame_time = "night"
        db.session.commit()

        merchants = get_merchants_at_location(self.campaign.id)
        innkeeper = next(entry for entry in merchants["merchants"] if entry["merchant_type"] == "innkeeper")

        result = buy_merchant_service(
            self.campaign.id,
            innkeeper["merchant_npc_id"],
            "cheap_bed",
        )
        self.assertTrue(result["success"], result)
        self.assertEqual("rest", result["time_result"]["tool"])
        self.assertEqual("morning", result["time_result"]["new_time"])
        self.assertEqual(2, result["time_result"]["new_day"])

    def test_get_trainers_at_location_lists_role_based_trainers(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)

        trainers = get_trainers_at_location(self.campaign.id)
        self.assertTrue(trainers["success"], trainers)
        self.assertTrue(any(entry["role"] == "blacksmith" for entry in trainers["trainers"]))
        self.assertTrue(any(entry["role"] == "apothecary" for entry in trainers["trainers"]))

    def test_train_with_teacher_can_create_and_train_custom_skill_from_matching_role(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Appleford",
            location_type="village",
            world_location_id="appleford",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 0, "silver": 3, "copper": 0}
        db.session.commit()

        woodcutter = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.campaign.current_location_id,
            name="Old Bran",
            role="woodcutter",
            is_custom=True,
        )
        db.session.add(woodcutter)
        db.session.commit()

        result = train_with_teacher(
            campaign_id=self.campaign.id,
            trainer_npc_id=woodcutter.id,
            training_type="skill",
            target_name="Woodcutting",
            minutes=60,
            allow_create_skill=True,
            linked_attribute="strength",
            secondary_attributes=["constitution"],
            allowed_domains=["crafting", "exploration"],
        )
        self.assertTrue(result["success"], result)
        self.assertEqual("teacher_training", result["time_result"]["action_type"])
        self.assertEqual("Woodcutting", result["training"]["target_name"])
        self.assertGreater(result["training"]["xp_awarded"], 0)
        self.assertLess(
            (result["currency"]["gold"] * 1000) + (result["currency"]["silver"] * 50) + result["currency"]["copper"],
            150,
        )
        self.assertTrue(any(skill["name"] == "Woodcutting" for skill in result["xp_result"]["skills"]))

    def test_train_with_teacher_blocks_overleveled_student_for_low_tier_trainer(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Appleford",
            location_type="village",
            world_location_id="appleford",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 1, "silver": 0, "copper": 0}
        self._set_skill_level("Axes & Hammers", 80)

        trainers = get_trainers_at_location(self.campaign.id)
        blacksmith = next(entry for entry in trainers["trainers"] if entry["role"] == "blacksmith")
        result = train_with_teacher(
            campaign_id=self.campaign.id,
            trainer_npc_id=blacksmith["trainer_npc_id"],
            training_type="skill",
            target_name="Axes & Hammers",
            minutes=60,
        )
        self.assertFalse(result["success"], result)
        self.assertIn("cannot meaningfully train", result["message"])

    def test_train_with_teacher_scales_down_xp_and_up_price_at_high_levels(self):
        moved = update_location(
            campaign_id=self.campaign.id,
            location_name="Willowbrook",
            location_type="city",
            world_location_id="willowbrook",
        )
        self.assertTrue(moved["success"], moved)
        self.character.currency_json = {"gold": 5, "silver": 0, "copper": 0}
        db.session.commit()

        master_smith = CampaignNPC(
            campaign_id=self.campaign.id,
            current_location_id=self.campaign.current_location_id,
            name="Master Halric",
            role="blacksmith",
            is_custom=True,
            state_json=json.dumps({
                "trainer_profile": {
                    "trainer_tier": 5,
                    "max_trainable_level": 100,
                    "patterns": ["combat_axe", "physical_craft", "trade_craft"],
                    "specialties": ["Axes & Hammers"],
                    "attributes": ["strength", "constitution"],
                }
            }),
        )
        db.session.add(master_smith)
        db.session.commit()

        low_result = train_with_teacher(
            campaign_id=self.campaign.id,
            trainer_npc_id=master_smith.id,
            training_type="skill",
            target_name="Axes & Hammers",
            minutes=60,
        )
        self.assertTrue(low_result["success"], low_result)
        low_xp = low_result["training"]["xp_awarded"]
        low_price = (
            low_result["price"]["gold"] * 1000
            + low_result["price"]["silver"] * 50
            + low_result["price"]["copper"]
        )

        self._set_skill_level("Axes & Hammers", 90)
        self.character.currency_json = {"gold": 5, "silver": 0, "copper": 0}
        db.session.commit()

        high_result = train_with_teacher(
            campaign_id=self.campaign.id,
            trainer_npc_id=master_smith.id,
            training_type="skill",
            target_name="Axes & Hammers",
            minutes=60,
        )
        self.assertTrue(high_result["success"], high_result)
        high_xp = high_result["training"]["xp_awarded"]
        high_price = (
            high_result["price"]["gold"] * 1000
            + high_result["price"]["silver"] * 50
            + high_result["price"]["copper"]
        )

        self.assertLess(high_xp, low_xp)
        self.assertGreater(high_price, low_price)


if __name__ == "__main__":
    unittest.main()
