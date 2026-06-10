"""Backend merchant generation, stock refresh, and trade validation."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from typing import Any

from models import Campaign, CampaignItem, CampaignLocation, CampaignNPC, Character, Merchant, MerchantInventory, db
from services.currency.constants import CURRENCY_CONVERSION_RATES, GOLD_TO_COPPER
from services.currency.repository import load_currency, save_currency
from services.equipment import build_item_bonus_lines, build_item_tooltip
from services.inventory.repository import load_inventory_blob
from services.inventory.service import add_inventory_item, remove_inventory_item
from services.world_data import find_world_location

SILVER_TO_COPPER = CURRENCY_CONVERSION_RATES["silver_to_copper"]

LOCATION_KIND_TIER = {
    "capital_city": 5,
    "capital_fortress": 5,
    "capital_port": 5,
    "city": 4,
    "port_city": 4,
    "mage_tower": 4,
    "forge_hold": 4,
    "town": 3,
    "fortress_town": 3,
    "pass_town": 3,
    "trade_crossing": 3,
    "port_town": 3,
    "village": 2,
    "marsh_village": 2,
    "border_outpost": 2,
    "watch_fort": 2,
    "ranger_lodge": 2,
    "monastery": 2,
    "camp": 2,
    "canyon_hold": 2,
}

LOCATION_KIND_MERCHANT_TYPES = {
    "capital_city": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary", "arcane_vendor"),
    "capital_fortress": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "capital_port": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary", "arcane_vendor"),
    "city": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "port_city": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "mage_tower": ("general_goods", "apothecary", "arcane_vendor"),
    "forge_hold": ("innkeeper", "general_goods", "blacksmith", "tailor"),
    "town": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "fortress_town": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "pass_town": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "trade_crossing": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor"),
    "port_town": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "village": ("innkeeper", "general_goods", "blacksmith", "bowyer", "tailor", "apothecary"),
    "marsh_village": ("innkeeper", "general_goods", "tailor", "apothecary"),
    "border_outpost": ("innkeeper", "general_goods", "blacksmith", "bowyer"),
    "watch_fort": ("innkeeper", "general_goods", "blacksmith"),
    "ranger_lodge": ("innkeeper", "general_goods", "bowyer", "apothecary"),
    "monastery": ("innkeeper", "general_goods", "tailor", "apothecary", "arcane_vendor"),
    "camp": ("innkeeper", "general_goods"),
    "canyon_hold": ("innkeeper", "general_goods", "blacksmith", "bowyer"),
}

MERCHANT_TYPE_ROLE_LABELS = {
    "innkeeper": "Innkeeper",
    "general_goods": "General Goods Merchant",
    "blacksmith": "Blacksmith",
    "apothecary": "Apothecary",
    "bowyer": "Bowyer",
    "tailor": "Tailor",
    "arcane_vendor": "Arcane Vendor",
}

MERCHANT_TYPE_NPC_ROLE = {
    "innkeeper": "innkeeper",
    "general_goods": "merchant",
    "blacksmith": "blacksmith",
    "apothecary": "apothecary",
    "bowyer": "bowyer",
    "tailor": "tailor",
    "arcane_vendor": "wizard",
}

MERCHANT_TYPE_SERVICE_OFFERS = {
    "innkeeper": [
        {
            "service_id": "hot_meal",
            "name": "Hot Meal",
            "description": "A warm meal and drink.",
            "service_type": "meal",
            "base_price_copper": 12,
        },
        {
            "service_id": "cheap_bed",
            "name": "Cheap Bed",
            "description": "A simple shared sleeping place for the night.",
            "service_type": "lodging",
            "base_price_copper": 40,
        },
    ],
    "general_goods": [],
    "blacksmith": [],
    "apothecary": [],
    "bowyer": [],
    "tailor": [],
    "arcane_vendor": [],
}

MERCHANT_TYPE_BASE_ITEMS = {
    "innkeeper": [
        {"template_id": "bread_loaf", "name": "Bread Loaf", "description": "A simple loaf of fresh bread.", "item_type": "food", "size": "small", "volume": 0.3, "weight": 0.4, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 6},
        {"template_id": "cheap_ale", "name": "Cheap Ale", "description": "A mug of ordinary tavern ale in a stoppered flask.", "item_type": "drink", "size": "small", "volume": 0.3, "weight": 0.5, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 8},
        {"template_id": "travel_rations", "name": "Travel Rations", "description": "Dry bread, smoked meat, and hard cheese for the road.", "item_type": "food", "size": "small", "volume": 0.4, "weight": 0.6, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 2, "value_copper": 14},
    ],
    "general_goods": [
        {"template_id": "torch", "name": "Torch", "description": "A basic travel torch.", "item_type": "utility", "size": "small", "volume": 0.2, "weight": 0.3, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 5},
        {"template_id": "rope", "name": "Rope (10m)", "description": "Simple but reliable travel rope.", "item_type": "utility", "size": "small", "volume": 0.8, "weight": 1.2, "stackable": False, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 30},
        {"template_id": "waterskin", "name": "Waterskin", "description": "A leather waterskin for the road.", "item_type": "utility", "size": "small", "volume": 0.4, "weight": 0.5, "stackable": False, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 18},
        {"template_id": "bandage", "name": "Bandage Roll", "description": "A clean roll of cloth for field treatment.", "item_type": "medical", "size": "tiny", "volume": 0.1, "weight": 0.1, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 1, "value_copper": 10},
    ],
    "blacksmith": [
        {"template_id": "work_knife", "name": "Work Knife", "description": "A plain but durable utility knife.", "item_type": "weapon", "size": "small", "volume": 0.5, "weight": 0.4, "stackable": False, "hand_usage": "one_handed", "weapon_family": "dagger", "rarity": "common", "item_level": 4, "value_copper": 70},
        {"template_id": "wooden_club", "name": "Wooden Club", "description": "A rough club favored by laborers and poor militias.", "item_type": "weapon", "size": "medium", "volume": 2.0, "weight": 2.5, "stackable": False, "hand_usage": "one_handed", "weapon_family": "mace_club", "rarity": "common", "item_level": 3, "value_copper": 55},
        {"template_id": "buckler", "name": "Buckler", "description": "A basic small shield for travelers and town guards.", "item_type": "shield", "size": "medium", "volume": 1.5, "weight": 2.0, "stackable": False, "hand_usage": "one_handed", "rarity": "common", "item_level": 6, "value_copper": 90, "combat_profile": {"armor_rating": 6, "block_bonus": 6, "block_threshold_bonus": 1, "armor_class": "medium"}},
    ],
    "apothecary": [
        {"template_id": "healing_herbs", "name": "Healing Herbs", "description": "A pouch of dried herbs for basic treatment.", "item_type": "medical", "size": "tiny", "volume": 0.1, "weight": 0.1, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 2, "value_copper": 18},
        {"template_id": "antidote_vial", "name": "Antidote Vial", "description": "A bitter emergency antidote against common poisons.", "item_type": "medical", "size": "tiny", "volume": 0.05, "weight": 0.05, "stackable": True, "hand_usage": "none", "rarity": "uncommon", "item_level": 8, "value_copper": 80},
        {"template_id": "clean_bandage_kit", "name": "Clean Bandage Kit", "description": "A better wrapped treatment kit than common field bandages.", "item_type": "medical", "size": "small", "volume": 0.15, "weight": 0.2, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 4, "value_copper": 26},
    ],
    "bowyer": [
        {"template_id": "training_bow", "name": "Training Bow", "description": "A simple bow for hunting practice and short-range work.", "item_type": "weapon", "size": "medium", "volume": 2.0, "weight": 1.1, "stackable": False, "hand_usage": "two_handed", "weapon_family": "bow", "rarity": "common", "item_level": 5, "value_copper": 85},
        {"template_id": "arrow_bundle", "name": "Arrow Bundle", "description": "A wrapped bundle of serviceable arrows.", "item_type": "ammo", "size": "small", "volume": 0.3, "weight": 0.4, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 4, "value_copper": 22},
        {"template_id": "bowstring_spool", "name": "Bowstring Spool", "description": "Replacement string and wax for keeping bows field-ready.", "item_type": "utility", "size": "tiny", "volume": 0.08, "weight": 0.05, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 3, "value_copper": 14},
    ],
    "tailor": [
        {"template_id": "padded_vest", "name": "Padded Vest", "description": "A layered vest offering modest protection without much weight.", "item_type": "armor", "slot_type": "torso_armor", "size": "medium", "volume": 1.6, "weight": 1.8, "stackable": False, "hand_usage": "none", "rarity": "common", "item_level": 4, "value_copper": 70, "combat_profile": {"armor_rating": 4, "dodge_bonus": 1, "armor_class": "light"}},
        {"template_id": "travel_cloak", "name": "Travel Cloak", "description": "A common weather cloak useful on the road.", "item_type": "cloak", "size": "small", "volume": 0.9, "weight": 0.8, "stackable": False, "hand_usage": "none", "rarity": "common", "item_level": 3, "value_copper": 28},
        {"template_id": "stitched_gloves", "name": "Stitched Gloves", "description": "Well-made gloves for travel, work, and rough weather.", "item_type": "gloves", "slot_type": "gloves", "size": "tiny", "volume": 0.2, "weight": 0.15, "stackable": False, "hand_usage": "none", "rarity": "common", "item_level": 3, "value_copper": 18},
    ],
    "arcane_vendor": [
        {"template_id": "focus_rod", "name": "Focus Rod", "description": "A simple channeling rod for novice spellwork.", "item_type": "weapon", "size": "small", "volume": 0.5, "weight": 0.4, "stackable": False, "hand_usage": "one_handed", "weapon_family": "wand", "rarity": "common", "item_level": 6, "value_copper": 120},
        {"template_id": "reagent_pouch", "name": "Reagent Pouch", "description": "Common powders, ash, and salts for ritual or spell utility.", "item_type": "utility", "size": "tiny", "volume": 0.15, "weight": 0.12, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 5, "value_copper": 34},
        {"template_id": "scribe_chalk", "name": "Rune Chalk", "description": "Marked chalk used for circles, sigils, and study marks.", "item_type": "utility", "size": "tiny", "volume": 0.05, "weight": 0.04, "stackable": True, "hand_usage": "none", "rarity": "common", "item_level": 4, "value_copper": 16},
    ],
}

MERCHANT_TYPE_ROTATION_RULES = {
    "innkeeper": [
        {"pattern": "food_rations"},
        {"pattern": "food_hearty"},
    ],
    "general_goods": [
        {"pattern": "travel_cloak"},
        {"pattern": "belt_utility"},
        {"pattern": "backpack_utility"},
    ],
    "blacksmith": [
        {"pattern": "weapon_sword"},
        {"pattern": "weapon_axe"},
        {"pattern": "shield_guard"},
        {"pattern": "armor_heavy"},
    ],
    "apothecary": [
        {"pattern": "medical_tonic"},
        {"pattern": "medical_salve"},
        {"pattern": "medical_elixir"},
    ],
    "bowyer": [
        {"pattern": "weapon_bow"},
        {"pattern": "ammo_arrows"},
        {"pattern": "quiver_utility"},
        {"pattern": "cloak_hunter"},
    ],
    "tailor": [
        {"pattern": "armor_light"},
        {"pattern": "cloak_travel"},
        {"pattern": "gloves_fine"},
        {"pattern": "boots_scout"},
    ],
    "arcane_vendor": [
        {"pattern": "weapon_staff"},
        {"pattern": "weapon_wand"},
        {"pattern": "focus_trinket"},
        {"pattern": "arcane_reagent"},
    ],
}

MERCHANT_PATTERN_RULES = {
    "food_lodging": ["food_rations", "food_hearty"],
    "trade_utility": ["travel_cloak", "belt_utility", "backpack_utility"],
    "weapon_melee": ["weapon_sword", "weapon_axe", "shield_guard"],
    "weapon_ranged": ["weapon_bow", "ammo_arrows", "quiver_utility"],
    "armor_light": ["armor_light", "cloak_travel", "gloves_fine", "boots_scout"],
    "magic_arcane": ["weapon_staff", "weapon_wand", "focus_trinket", "arcane_reagent"],
    "medical": ["medical_tonic", "medical_salve", "medical_elixir"],
}

RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary")
RARITY_PRICE_MULTIPLIERS = {
    "common": 1.0,
    "uncommon": 1.45,
    "rare": 2.2,
    "epic": 3.4,
    "legendary": 5.1,
}

ROTATION_PATTERN_DEFINITIONS = {
    "food_rations": {
        "item_type": "food",
        "stackable": True,
        "size": "small",
        "volume": 0.42,
        "weight": 0.55,
        "name_prefixes": ["Travel", "Hunter", "Camp", "Road", "Wayfarer"],
        "name_bases": ["Rations", "Meal Pack", "Trail Bread", "Field Pack"],
        "description_templates": ["Packed food for the road, salted and wrapped for travel."],
        "rarity_weights": {"common": 70, "uncommon": 25, "rare": 5},
        "base_value": 12,
        "stack_range": (2, 6),
    },
    "food_hearty": {
        "item_type": "food",
        "stackable": True,
        "size": "small",
        "volume": 0.38,
        "weight": 0.5,
        "name_prefixes": ["Spiced", "Smoked", "Herb", "Golden", "Hearty"],
        "name_bases": ["Stew Pack", "Meat Pie", "Cookpot Meal", "Inn Wrap"],
        "description_templates": ["A warm or well-packed meal better than common road fare."],
        "rarity_weights": {"common": 55, "uncommon": 35, "rare": 10},
        "base_value": 16,
        "stack_range": (2, 5),
    },
    "travel_cloak": {
        "item_type": "cloak",
        "stackable": False,
        "size": "small",
        "volume": 1.0,
        "weight": 1.0,
        "name_prefixes": ["Traveler", "Dustroad", "Storm", "Roadwarden", "Trail"],
        "name_bases": ["Cloak", "Mantle", "Wrap"],
        "description_templates": ["A practical outer layer for roads, weather, and rough camps."],
        "rarity_weights": {"common": 65, "uncommon": 25, "rare": 10},
        "base_value": 72,
        "combat_profile_builder": "light_cloak",
    },
    "belt_utility": {
        "item_type": "belt",
        "stackable": False,
        "size": "small",
        "volume": 0.45,
        "weight": 0.45,
        "name_prefixes": ["Scout", "Ranger", "Road", "Tracker", "Field"],
        "name_bases": ["Belt", "Warbelt", "Utility Belt"],
        "description_templates": ["A reinforced belt with loops, rings, and travel fittings."],
        "rarity_weights": {"common": 55, "uncommon": 30, "rare": 15},
        "base_value": 90,
    },
    "backpack_utility": {
        "item_type": "backpack",
        "stackable": False,
        "size": "medium",
        "volume": 2.0,
        "weight": 1.5,
        "name_prefixes": ["Roadwarden", "Trail", "Field", "Packrunner", "Marcher"],
        "name_bases": ["Pack", "Rucksack", "Backpack"],
        "description_templates": ["A sturdier pack built for regular travel and better carrying."],
        "rarity_weights": {"common": 40, "uncommon": 35, "rare": 20, "epic": 5},
        "base_value": 150,
        "container_builder": "backpack",
    },
    "weapon_sword": {
        "item_type": "weapon",
        "stackable": False,
        "size": "medium",
        "volume": 2.2,
        "weight": 2.2,
        "name_prefixes": ["Militia", "Border", "March", "Ward", "Captain"],
        "name_bases": ["Sword", "Blade", "Longsword"],
        "description_templates": ["A forged melee weapon suited to drills, watch duty, or war."],
        "rarity_weights": {"common": 50, "uncommon": 28, "rare": 16, "epic": 6},
        "base_value": 135,
        "weapon_family": "sword",
    },
    "weapon_axe": {
        "item_type": "weapon",
        "stackable": False,
        "size": "medium",
        "volume": 2.35,
        "weight": 2.8,
        "name_prefixes": ["Border", "Forge", "Ridge", "War", "Anvil"],
        "name_bases": ["Axe", "Hatchet", "Cleaver"],
        "description_templates": ["A weapon balanced somewhere between field work and battle."],
        "rarity_weights": {"common": 48, "uncommon": 30, "rare": 16, "epic": 6},
        "base_value": 145,
        "weapon_family": "axe_hammer",
    },
    "shield_guard": {
        "item_type": "shield",
        "stackable": False,
        "size": "medium",
        "volume": 2.0,
        "weight": 3.0,
        "name_prefixes": ["Guard", "Bulwark", "Ward", "Gate", "Sentinel"],
        "name_bases": ["Shield", "Buckler", "Wall Shield"],
        "description_templates": ["A defensive shield built for patrols, guards, and bruising fights."],
        "rarity_weights": {"common": 45, "uncommon": 32, "rare": 17, "epic": 6},
        "base_value": 120,
        "combat_profile_builder": "shield",
    },
    "armor_heavy": {
        "item_type": "armor",
        "slot_type": "torso_armor",
        "stackable": False,
        "size": "medium",
        "volume": 4.4,
        "weight": 6.6,
        "name_prefixes": ["Vanguard", "Ward", "Iron", "Bastion", "Forge"],
        "name_bases": ["Plate", "Cuirass", "Harness"],
        "description_templates": ["Heavy armor built to stop force rather than dance around it."],
        "rarity_weights": {"common": 35, "uncommon": 32, "rare": 22, "epic": 9, "legendary": 2},
        "base_value": 260,
        "combat_profile_builder": "armor_heavy",
    },
    "medical_tonic": {
        "item_type": "medical",
        "stackable": True,
        "size": "tiny",
        "volume": 0.08,
        "weight": 0.08,
        "name_prefixes": ["Restorative", "Field", "Bitter", "Herbal", "Warden"],
        "name_bases": ["Draught", "Tonic", "Infusion"],
        "description_templates": ["A brewed tonic for wounds, strain, and rough conditions."],
        "rarity_weights": {"common": 45, "uncommon": 35, "rare": 15, "epic": 5},
        "base_value": 65,
        "stack_range": (1, 4),
    },
    "medical_salve": {
        "item_type": "medical",
        "stackable": True,
        "size": "tiny",
        "volume": 0.07,
        "weight": 0.06,
        "name_prefixes": ["Blessed", "Calming", "Wound", "Silverleaf", "Nightbloom"],
        "name_bases": ["Salve", "Paste", "Balm"],
        "description_templates": ["A prepared salve for cuts, fever, and lingering aches."],
        "rarity_weights": {"common": 35, "uncommon": 35, "rare": 22, "epic": 8},
        "base_value": 82,
        "stack_range": (1, 3),
    },
    "medical_elixir": {
        "item_type": "medical",
        "stackable": True,
        "size": "tiny",
        "volume": 0.06,
        "weight": 0.05,
        "name_prefixes": ["Moonroot", "Frostbloom", "Dawnfire", "Starpetal", "Glassleaf"],
        "name_bases": ["Elixir", "Philter", "Serum"],
        "description_templates": ["A rarer alchemical blend reserved for wealthy or prepared buyers."],
        "rarity_weights": {"uncommon": 35, "rare": 35, "epic": 22, "legendary": 8},
        "base_value": 110,
        "stack_range": (1, 2),
    },
    "weapon_bow": {
        "item_type": "weapon",
        "stackable": False,
        "size": "medium",
        "volume": 2.0,
        "weight": 1.2,
        "name_prefixes": ["Hunter", "Ashwood", "Longrange", "Falcon", "Stag"],
        "name_bases": ["Bow", "Longbow", "Recurve"],
        "description_templates": ["A bow made for hunts, patrols, or steady ranged fighting."],
        "rarity_weights": {"common": 44, "uncommon": 32, "rare": 17, "epic": 7},
        "base_value": 150,
        "weapon_family": "bow",
    },
    "ammo_arrows": {
        "item_type": "ammo",
        "stackable": True,
        "size": "small",
        "volume": 0.32,
        "weight": 0.38,
        "name_prefixes": ["Hunting", "War", "Flight", "Broadhead", "Tracker"],
        "name_bases": ["Arrows", "Arrow Bundle", "Shaft Pack"],
        "description_templates": ["A tied bundle of arrows for bow use and repeated shots."],
        "rarity_weights": {"common": 55, "uncommon": 30, "rare": 12, "epic": 3},
        "base_value": 28,
        "stack_range": (3, 8),
    },
    "quiver_utility": {
        "item_type": "belt_pouch",
        "stackable": False,
        "size": "small",
        "volume": 0.7,
        "weight": 0.45,
        "name_prefixes": ["Scout", "Hunter", "Ranger", "Fletcher", "Ash"],
        "name_bases": ["Quiver", "Arrow Case", "Shot Carrier"],
        "description_templates": ["A carrying piece built to keep shafts handy and protected."],
        "rarity_weights": {"common": 45, "uncommon": 32, "rare": 18, "epic": 5},
        "base_value": 65,
        "container_builder": "quiver",
    },
    "cloak_hunter": {
        "item_type": "cloak",
        "stackable": False,
        "size": "small",
        "volume": 0.95,
        "weight": 0.85,
        "name_prefixes": ["Moss", "Hunter", "Briar", "Stag", "Shade"],
        "name_bases": ["Cloak", "Mantle", "Cape"],
        "description_templates": ["A cloak colored for brush, trail, and field cover."],
        "rarity_weights": {"common": 38, "uncommon": 35, "rare": 20, "epic": 7},
        "base_value": 78,
        "combat_profile_builder": "light_cloak",
    },
    "armor_light": {
        "item_type": "armor",
        "slot_type": "torso_armor",
        "stackable": False,
        "size": "medium",
        "volume": 1.8,
        "weight": 2.0,
        "name_prefixes": ["Scout", "Duskwalker", "Leather", "Stitched", "Shade"],
        "name_bases": ["Jerkin", "Vest", "Harness", "Leathercoat"],
        "description_templates": ["Light armor favoring motion, travel, and quick reactions."],
        "rarity_weights": {"common": 42, "uncommon": 33, "rare": 18, "epic": 7},
        "base_value": 120,
        "combat_profile_builder": "armor_light",
    },
    "cloak_travel": {
        "item_type": "cloak",
        "stackable": False,
        "size": "small",
        "volume": 0.9,
        "weight": 0.8,
        "name_prefixes": ["Tailored", "Road", "Rain", "Fine", "Dust"],
        "name_bases": ["Cloak", "Mantle", "Cape"],
        "description_templates": ["A layered cloth outer piece stitched for wear and weather."],
        "rarity_weights": {"common": 40, "uncommon": 35, "rare": 18, "epic": 7},
        "base_value": 72,
        "combat_profile_builder": "light_cloak",
    },
    "gloves_fine": {
        "item_type": "gloves",
        "slot_type": "gloves",
        "stackable": False,
        "size": "tiny",
        "volume": 0.18,
        "weight": 0.14,
        "name_prefixes": ["Fine", "Stitched", "Soft", "Rider", "Scout"],
        "name_bases": ["Gloves", "Handwraps", "Gauntlets"],
        "description_templates": ["Well-made hand covering for travel, work, or quiet field use."],
        "rarity_weights": {"common": 45, "uncommon": 33, "rare": 17, "epic": 5},
        "base_value": 44,
    },
    "boots_scout": {
        "item_type": "boots",
        "slot_type": "feet",
        "stackable": False,
        "size": "small",
        "volume": 0.8,
        "weight": 0.9,
        "name_prefixes": ["Scout", "Trail", "Ash", "Quickstep", "Ranger"],
        "name_bases": ["Boots", "Shoes", "Treads"],
        "description_templates": ["Bootwear made to move quietly and hold up over long paths."],
        "rarity_weights": {"common": 40, "uncommon": 34, "rare": 19, "epic": 7},
        "base_value": 68,
    },
    "weapon_staff": {
        "item_type": "weapon",
        "stackable": False,
        "size": "medium",
        "volume": 2.1,
        "weight": 1.5,
        "name_prefixes": ["Apprentice", "Rune", "Star", "Glass", "Moon"],
        "name_bases": ["Staff", "Channeling Staff", "Focus Staff"],
        "description_templates": ["A focus staff for ritual work, spell direction, and arcane shaping."],
        "rarity_weights": {"common": 35, "uncommon": 32, "rare": 22, "epic": 9, "legendary": 2},
        "base_value": 170,
        "weapon_family": "staff",
    },
    "weapon_wand": {
        "item_type": "weapon",
        "stackable": False,
        "size": "small",
        "volume": 0.45,
        "weight": 0.28,
        "name_prefixes": ["Carved", "Rune", "Whisper", "Amber", "Silver"],
        "name_bases": ["Wand", "Focus Rod", "Spell Wand"],
        "description_templates": ["A lighter arcane focus for quick casting and practiced handwork."],
        "rarity_weights": {"common": 32, "uncommon": 32, "rare": 24, "epic": 10, "legendary": 2},
        "base_value": 150,
        "weapon_family": "wand",
    },
    "focus_trinket": {
        "item_type": "ring",
        "stackable": False,
        "size": "tiny",
        "volume": 0.08,
        "weight": 0.08,
        "name_prefixes": ["Focus", "Astral", "Rune", "Moon", "Sigil"],
        "name_bases": ["Band", "Charm", "Seal", "Loop"],
        "description_templates": ["A small focus piece favored by mages, scholars, and ritualists."],
        "rarity_weights": {"uncommon": 40, "rare": 32, "epic": 20, "legendary": 8},
        "base_value": 145,
        "attribute_builder": "arcane_focus",
    },
    "arcane_reagent": {
        "item_type": "utility",
        "stackable": True,
        "size": "tiny",
        "volume": 0.09,
        "weight": 0.06,
        "name_prefixes": ["Rune", "Starlit", "Ashglass", "Moonsalt", "Spell"],
        "name_bases": ["Powder", "Dust", "Reagent Pouch", "Salt"],
        "description_templates": ["Arcane residue, salts, or prepared powder for study and spellwork."],
        "rarity_weights": {"common": 35, "uncommon": 35, "rare": 20, "epic": 8, "legendary": 2},
        "base_value": 58,
        "stack_range": (1, 4),
    },
}

MERCHANT_ROLE_TYPE_ALIASES = {
    "innkeeper": "innkeeper",
    "barkeep": "innkeeper",
    "tavernkeeper": "innkeeper",
    "merchant": "general_goods",
    "trader": "general_goods",
    "shopkeeper": "general_goods",
    "general_goods": "general_goods",
    "general_goods_merchant": "general_goods",
    "blacksmith": "blacksmith",
    "smith": "blacksmith",
    "weaponsmith": "blacksmith",
    "armorer": "blacksmith",
    "armourer": "blacksmith",
    "apothecary": "apothecary",
    "alchemist": "apothecary",
    "herbalist": "apothecary",
    "healer": "apothecary",
    "bowyer": "bowyer",
    "fletcher": "bowyer",
    "tailor": "tailor",
    "clothier": "tailor",
    "leatherworker": "tailor",
    "seamstress": "tailor",
    "wizard": "arcane_vendor",
    "mage": "arcane_vendor",
    "arcanist": "arcane_vendor",
    "enchanter": "arcane_vendor",
    "arcane_vendor": "arcane_vendor",
}

MERCHANT_PATTERN_DEFAULT_TYPES = {
    "food_lodging": "innkeeper",
    "trade_utility": "general_goods",
    "weapon_melee": "blacksmith",
    "weapon_ranged": "bowyer",
    "armor_light": "tailor",
    "magic_arcane": "arcane_vendor",
    "medical": "apothecary",
}


def _normalize_world_kind(value: Any) -> str:
    return str(value or "town").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_merchant_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in MERCHANT_TYPE_ROLE_LABELS else None


def _normalize_role(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _load_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return decoded
    return fallback


def _npc_state_payload(npc: CampaignNPC | None) -> dict:
    payload = _load_json(getattr(npc, "state_json", None), {})
    return payload if isinstance(payload, dict) else {}


def _location_tier_from_kind(location_kind: str) -> int:
    return int(LOCATION_KIND_TIER.get(_normalize_world_kind(location_kind), 3))


def _merchant_price_modifier_for_tier(location_tier: int) -> int:
    return {2: 110, 3: 105, 4: 100, 5: 95}.get(int(location_tier or 3), 100)


def _merchant_types_for_location_kind(location_kind: str) -> tuple[str, ...]:
    return LOCATION_KIND_MERCHANT_TYPES.get(_normalize_world_kind(location_kind), ("innkeeper", "general_goods"))


def _merchant_display_name(world_location_name: str, merchant_type: str) -> str:
    return f"{world_location_name} {MERCHANT_TYPE_ROLE_LABELS.get(merchant_type, merchant_type.replace('_', ' ').title())}"


def _copy_item_payload(template: dict) -> dict:
    payload = deepcopy(template)
    payload.pop("template_id", None)
    payload.pop("value_copper", None)
    payload.pop("min_tier", None)
    payload.setdefault("rarity", "common")
    payload.setdefault("item_level", 1)
    payload.setdefault("item_id", f"merchant_{template.get('template_id')}")
    return payload


def _pattern_rule_names_for_merchant(merchant: Merchant) -> list[str]:
    profile = _load_merchant_profile(merchant)
    if merchant.merchant_type in MERCHANT_TYPE_ROTATION_RULES:
        return list(MERCHANT_TYPE_ROTATION_RULES.get(merchant.merchant_type, []))

    pattern_name = str(profile.get("merchant_pattern", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if pattern_name:
        return [{"pattern": pattern} for pattern in MERCHANT_PATTERN_RULES.get(pattern_name, [])]
    return []


def _roll_rarity(rng: random.Random, rule: dict, location_tier: int) -> str:
    weights = dict(rule.get("rarity_weights", {"common": 100}))
    if location_tier >= 4:
        weights["rare"] = weights.get("rare", 0) + 6
    if location_tier >= 5:
        weights["epic"] = weights.get("epic", 0) + 5
        weights["legendary"] = weights.get("legendary", 0) + 1
    filtered = [(rarity, max(0, int(weight))) for rarity, weight in weights.items() if rarity in RARITY_ORDER and int(weight) > 0]
    if not filtered:
        return "common"
    total = sum(weight for _rarity, weight in filtered)
    roll = rng.randint(1, total)
    running = 0
    for rarity, weight in filtered:
        running += weight
        if roll <= running:
            return rarity
    return filtered[-1][0]


def _level_bounds_for_tier(location_tier: int) -> tuple[int, int]:
    return {
        2: (4, 18),
        3: (10, 35),
        4: (22, 60),
        5: (40, 90),
    }.get(int(location_tier or 3), (8, 28))


def _item_level_for_rule(rng: random.Random, location_tier: int, rarity: str) -> int:
    min_level, max_level = _level_bounds_for_tier(location_tier)
    rarity_bonus = {"common": 0, "uncommon": 2, "rare": 6, "epic": 10, "legendary": 14}.get(rarity, 0)
    adjusted_min = min(100, max(1, min_level + max(0, rarity_bonus // 2)))
    adjusted_max = min(100, max(adjusted_min, max_level + rarity_bonus))
    return rng.randint(adjusted_min, adjusted_max)


def _base_value_from_level_and_rarity(base_value: int, item_level: int, rarity: str) -> int:
    level_factor = 0.65 + ((max(1, min(100, int(item_level or 1))) / 100.0) ** 1.15) * 2.1
    rarity_factor = RARITY_PRICE_MULTIPLIERS.get(rarity, 1.0)
    return max(1, int(round(float(base_value) * level_factor * rarity_factor)))


def _build_combat_profile(builder: str, item_level: int, rarity: str, weapon_family: str | None = None) -> dict | None:
    rarity_step = {"common": 0, "uncommon": 1, "rare": 2, "epic": 4, "legendary": 6}.get(rarity, 0)
    if builder == "light_cloak":
        return {"armor_class": "light", "armor_rating": max(1, 1 + (item_level // 18) + rarity_step), "dodge_bonus": max(1, 1 + (item_level // 28) + (rarity_step // 2))}
    if builder == "shield":
        return {"armor_class": "heavy", "armor_rating": 6 + (item_level // 10) + rarity_step, "block_bonus": 6 + (item_level // 9) + rarity_step, "block_threshold_bonus": max(1, 1 + (item_level // 25) + (rarity_step // 2))}
    if builder == "armor_heavy":
        return {"armor_class": "heavy", "armor_rating": 10 + (item_level // 5) + rarity_step, "block_bonus": 4 + (item_level // 12) + rarity_step, "dodge_bonus": -(1 + (item_level // 30) + (rarity_step // 2))}
    if builder == "armor_light":
        return {"armor_class": "light", "armor_rating": 4 + (item_level // 10) + rarity_step, "dodge_bonus": 1 + (item_level // 18) + (rarity_step // 2)}
    if weapon_family:
        return {"weapon_family": weapon_family, "item_level": item_level}
    return None


def _build_container_profile(builder: str, item_level: int, rarity: str, name: str) -> dict | None:
    rarity_step = {"common": 0, "uncommon": 2, "rare": 4, "epic": 6, "legendary": 8}.get(rarity, 0)
    if builder == "backpack":
        return {"name": name, "max_volume": round(14.0 + (item_level * 0.18) + rarity_step, 1), "max_item_size": "medium"}
    if builder == "quiver":
        return {"name": name, "max_volume": round(4.0 + (item_level * 0.05) + (rarity_step * 0.2), 1), "max_item_size": "small"}
    return None


def _build_attribute_modifiers(builder: str, item_level: int, rarity: str) -> dict | None:
    rarity_step = {"uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}.get(rarity, 0)
    if builder == "arcane_focus":
        bonus = max(1, (item_level // 22) + rarity_step)
        return {"intelligence": bonus}
    return None


def _build_generated_template(rule_name: str, location_tier: int, merchant: Merchant, rng: random.Random, existing_names: set[str], attempt_index: int) -> dict | None:
    rule = ROTATION_PATTERN_DEFINITIONS.get(rule_name)
    if not rule:
        return None

    rarity = _roll_rarity(rng, rule, location_tier)
    item_level = _item_level_for_rule(rng, location_tier, rarity)
    prefix = rng.choice(rule.get("name_prefixes", ["Merchant"]))
    base = rng.choice(rule.get("name_bases", ["Item"]))
    suffixes = ["", "", " Mk II", " of the Road", " of the Watch", " of the Vale"]
    suffix = rng.choice(suffixes)
    name = f"{prefix} {base}{suffix}".strip()
    if name in existing_names:
        name = f"{name} {attempt_index + 1}"
    description = rng.choice(rule.get("description_templates", ["A merchant-made item."]))
    value_copper = _base_value_from_level_and_rarity(int(rule.get("base_value", 20) or 20), item_level, rarity)

    template = {
        "template_id": f"{merchant.merchant_type}_{rule_name}_{item_level}_{attempt_index}",
        "name": name,
        "description": description,
        "item_type": rule["item_type"],
        "size": rule.get("size", "small"),
        "volume": float(rule.get("volume", 0.2) or 0.2),
        "weight": float(rule.get("weight", 0.2) or 0.2),
        "stackable": bool(rule.get("stackable", False)),
        "hand_usage": rule.get("hand_usage", "none"),
        "rarity": rarity,
        "item_level": item_level,
        "value_copper": value_copper,
    }
    if rule.get("slot_type"):
        template["slot_type"] = rule.get("slot_type")
    if rule.get("weapon_family"):
        template["weapon_family"] = rule.get("weapon_family")
    combat_profile = _build_combat_profile(rule.get("combat_profile_builder", ""), item_level, rarity, weapon_family=rule.get("weapon_family"))
    if combat_profile:
        template["combat_profile"] = combat_profile
    container_profile = _build_container_profile(rule.get("container_builder", ""), item_level, rarity, name)
    if container_profile:
        template["container_profile"] = container_profile
    attribute_modifiers = _build_attribute_modifiers(rule.get("attribute_builder", ""), item_level, rarity)
    if attribute_modifiers:
        template["attribute_modifiers"] = attribute_modifiers
    return template


def _campaign_item_from_template(campaign_id: int, template: dict, is_generated: bool) -> CampaignItem:
    inventory_item = _copy_item_payload(template)
    modifier_payload = {
        key: inventory_item[key]
        for key in ("attribute_modifiers", "resource_modifiers", "skill_modifiers", "stat_modifiers")
        if key in inventory_item
    }
    campaign_item = CampaignItem(
        campaign_id=campaign_id,
        name=inventory_item["name"],
        item_type=inventory_item["item_type"],
        rarity=inventory_item.get("rarity", "common"),
        description=inventory_item.get("description"),
        value_final=int(template.get("value_copper", 0) or 0),
        weight=max(0, int(round(float(inventory_item.get("weight", 0) or 0) * 100))),
        slot_type=inventory_item.get("slot_type"),
        stat_modifiers_json=json.dumps(modifier_payload, ensure_ascii=False) if modifier_payload else None,
        special_effects_json=json.dumps({"inventory_item": inventory_item}, ensure_ascii=False),
        is_generated=bool(is_generated),
    )
    db.session.add(campaign_item)
    db.session.flush()
    return campaign_item


def _inventory_item_from_campaign_item(campaign_item: CampaignItem) -> dict:
    try:
        payload = json.loads(campaign_item.special_effects_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    inventory_item = payload.get("inventory_item") if isinstance(payload, dict) else None
    if isinstance(inventory_item, dict):
        resolved = deepcopy(inventory_item)
        resolved.setdefault("item_id", f"merchant_item_{campaign_item.id}")
        resolved.setdefault("name", campaign_item.name)
        resolved.setdefault("description", campaign_item.description or "")
        resolved.setdefault("item_type", campaign_item.item_type)
        resolved.setdefault("rarity", campaign_item.rarity)
        return resolved
    return {
        "item_id": f"merchant_item_{campaign_item.id}",
        "name": campaign_item.name,
        "description": campaign_item.description or "",
        "size": "small",
        "volume": 0.2,
        "weight": max(0.0, float(campaign_item.weight or 0) / 100.0),
        "stackable": False,
        "hand_usage": "none",
        "item_type": campaign_item.item_type,
        "rarity": campaign_item.rarity,
    }


def _currency_to_copper(currency: dict) -> int:
    if not isinstance(currency, dict):
        return 0
    return int(currency.get("gold", 0) or 0) * GOLD_TO_COPPER + int(currency.get("silver", 0) or 0) * SILVER_TO_COPPER + int(currency.get("copper", 0) or 0)


def _copper_to_currency(total_copper: int) -> dict[str, int]:
    remaining = max(0, int(total_copper or 0))
    gold = remaining // GOLD_TO_COPPER
    remaining -= gold * GOLD_TO_COPPER
    silver = remaining // SILVER_TO_COPPER
    remaining -= silver * SILVER_TO_COPPER
    return {"gold": gold, "silver": silver, "copper": remaining}


def _merchant_services_for_profile(merchant_type: str, location_tier: int) -> list[dict]:
    services = []
    for service in MERCHANT_TYPE_SERVICE_OFFERS.get(merchant_type, []):
        service_entry = dict(service)
        service_entry["price_copper"] = max(1, int(round(int(service_entry.get("base_price_copper", 0) or 0) * (_merchant_price_modifier_for_tier(location_tier) / 100.0))))
        services.append(service_entry)
    return services


def _find_service_offer(merchant: Merchant, service_id: str) -> dict | None:
    normalized_service_id = str(service_id or "").strip().lower()
    for service in _load_merchant_profile(merchant).get("service_offers", []):
        if not isinstance(service, dict):
            continue
        if str(service.get("service_id", "")).strip().lower() == normalized_service_id:
            return dict(service)
    return None


def _merchant_profile_payload(world_location: dict, merchant_type: str, location_tier: int) -> dict:
    return {
        "world_location_id": world_location.get("id"),
        "world_location_name": world_location.get("name"),
        "world_location_kind": world_location.get("kind"),
        "location_tier": int(location_tier),
        "merchant_type": merchant_type,
        "service_offers": _merchant_services_for_profile(merchant_type, location_tier),
    }


def _current_campaign_location(campaign: Campaign) -> CampaignLocation | None:
    if not campaign or not campaign.current_location_id:
        return None
    return db.session.get(CampaignLocation, campaign.current_location_id)


def _fixed_world_location_for_campaign_location(location: CampaignLocation | None) -> dict | None:
    if not location or not location.world_location_id:
        return None
    return find_world_location(location.world_location_id)


def _load_merchant_profile(merchant: Merchant) -> dict:
    try:
        payload = json.loads(merchant.inventory_profile_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _merchant_type_from_role(role: Any) -> str | None:
    return MERCHANT_ROLE_TYPE_ALIASES.get(_normalize_role(role))


def _merchant_type_from_pattern(pattern_name: Any) -> str | None:
    normalized = str(pattern_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return MERCHANT_PATTERN_DEFAULT_TYPES.get(normalized)


def _merchant_context_for_location(location: CampaignLocation | None) -> tuple[dict, int]:
    world_location = _fixed_world_location_for_campaign_location(location)
    if world_location:
        return world_location, _location_tier_from_kind(world_location.get("kind"))

    fallback_world_location = {
        "id": getattr(location, "world_location_id", None),
        "name": getattr(location, "name", "Unknown Location"),
        "kind": getattr(location, "location_type", "town"),
    }
    return fallback_world_location, _location_tier_from_kind(fallback_world_location.get("kind"))


def _resolve_merchant_setup_for_npc(location: CampaignLocation | None, npc: CampaignNPC | None) -> dict | None:
    if not location or not npc:
        return None

    state = _npc_state_payload(npc)
    merchant_profile = state.get("merchant_profile") if isinstance(state.get("merchant_profile"), dict) else {}
    merchant_pattern = str(
        merchant_profile.get("merchant_pattern")
        or state.get("merchant_pattern")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    merchant_type = (
        _normalize_merchant_type(merchant_profile.get("merchant_type"))
        or _normalize_merchant_type(state.get("merchant_type"))
        or _merchant_type_from_role(npc.role)
        or _merchant_type_from_pattern(merchant_pattern)
    )
    if not merchant_type:
        return None

    world_location, location_tier = _merchant_context_for_location(location)
    profile_payload = _merchant_profile_payload(world_location, merchant_type, location_tier)
    if merchant_pattern:
        profile_payload["merchant_pattern"] = merchant_pattern

    custom_service_offers = merchant_profile.get("service_offers")
    if isinstance(custom_service_offers, list):
        profile_payload["service_offers"] = list(custom_service_offers)

    return {
        "merchant_type": merchant_type,
        "location_tier": location_tier,
        "inventory_profile": profile_payload,
        "price_modifier": _merchant_price_modifier_for_tier(location_tier),
    }


def _ensure_dynamic_merchant_for_npc(campaign: Campaign, location: CampaignLocation | None, npc: CampaignNPC | None) -> CampaignNPC | None:
    if not campaign or not location or not npc:
        return None
    if int(npc.campaign_id or 0) != int(campaign.id or 0) or int(npc.current_location_id or 0) != int(location.id or 0):
        return None
    if npc.merchant:
        return npc

    merchant_setup = _resolve_merchant_setup_for_npc(location, npc)
    if not merchant_setup:
        return None

    merchant = Merchant(
        campaign_npc_id=npc.id,
        merchant_type=str(merchant_setup["merchant_type"]),
        refresh_rule="daily",
        last_refresh_ingame_day=0,
        price_modifier=int(merchant_setup["price_modifier"] or 100),
        inventory_profile_json=json.dumps(merchant_setup["inventory_profile"], ensure_ascii=False),
    )
    db.session.add(merchant)
    db.session.flush()
    npc.merchant = merchant
    return npc


def _merchant_npc_from_id(campaign_id: int, merchant_npc_id: int) -> CampaignNPC | None:
    return CampaignNPC.query.filter_by(campaign_id=campaign_id, id=merchant_npc_id).first()


def _merchant_from_npc(npc: CampaignNPC | None) -> Merchant | None:
    if not npc:
        return None
    return npc.merchant or Merchant.query.filter_by(campaign_npc_id=npc.id).first()


def _current_location_matches_merchant(campaign: Campaign, merchant_npc: CampaignNPC) -> bool:
    return bool(campaign and merchant_npc and int(campaign.current_location_id or 0) == int(merchant_npc.current_location_id or -1))


def _existing_merchant_npc(campaign_id: int, location_id: int, merchant_type: str) -> CampaignNPC | None:
    return (
        CampaignNPC.query
        .join(Merchant, Merchant.campaign_npc_id == CampaignNPC.id)
        .filter(
            CampaignNPC.campaign_id == campaign_id,
            CampaignNPC.current_location_id == location_id,
            Merchant.merchant_type == merchant_type,
        )
        .first()
    )


def _ensure_fixed_merchants_for_location(campaign: Campaign, location: CampaignLocation | None) -> list[CampaignNPC]:
    if not campaign or not location:
        return []
    world_location = _fixed_world_location_for_campaign_location(location)
    if not world_location:
        return []

    location_tier = _location_tier_from_kind(world_location.get("kind"))
    merchants = []
    for merchant_type in _merchant_types_for_location_kind(world_location.get("kind")):
        existing = _existing_merchant_npc(campaign.id, location.id, merchant_type)
        if existing:
            merchants.append(existing)
            continue

        npc = CampaignNPC(
            campaign_id=campaign.id,
            current_location_id=location.id,
            name=_merchant_display_name(world_location.get("name", location.name), merchant_type),
            role=MERCHANT_TYPE_NPC_ROLE.get(merchant_type, "merchant"),
            description=f"A fixed {merchant_type.replace('_', ' ')} attached to {world_location.get('name', location.name)}.",
            status="alive",
            attitude_label="neutral",
            relationship_score=0,
            is_custom=False,
            state_json=json.dumps({"merchant_type": merchant_type, "world_location_id": world_location.get("id")}, ensure_ascii=False),
        )
        db.session.add(npc)
        db.session.flush()
        db.session.add(Merchant(
            campaign_npc_id=npc.id,
            merchant_type=merchant_type,
            refresh_rule="daily",
            last_refresh_ingame_day=0,
            price_modifier=_merchant_price_modifier_for_tier(location_tier),
            inventory_profile_json=json.dumps(_merchant_profile_payload(world_location, merchant_type, location_tier), ensure_ascii=False),
        ))
        db.session.flush()
        merchants.append(npc)

    db.session.commit()
    return merchants


def _ensure_dynamic_merchants_for_location(campaign: Campaign, location: CampaignLocation | None) -> list[CampaignNPC]:
    if not campaign or not location:
        return []

    created_merchants: list[CampaignNPC] = []
    npcs = (
        CampaignNPC.query
        .filter(
            CampaignNPC.campaign_id == campaign.id,
            CampaignNPC.current_location_id == location.id,
        )
        .order_by(CampaignNPC.name.asc())
        .all()
    )
    for npc in npcs:
        created = _ensure_dynamic_merchant_for_npc(campaign, location, npc)
        if created and created.merchant:
            created_merchants.append(created)

    if created_merchants:
        db.session.commit()
    return created_merchants


def _base_stock_templates(merchant: Merchant) -> list[dict]:
    return deepcopy(MERCHANT_TYPE_BASE_ITEMS.get(merchant.merchant_type, []))


def _ensure_base_stock(merchant: Merchant, campaign_id: int) -> None:
    existing_names = set()
    for entry in merchant.inventory:
        if int(entry.generated_ingame_day or 0) != 0:
            continue
        campaign_item = db.session.get(CampaignItem, entry.campaign_item_id)
        if campaign_item:
            existing_names.add(campaign_item.name)

    for template in _base_stock_templates(merchant):
        if template["name"] in existing_names:
            continue
        campaign_item = _campaign_item_from_template(campaign_id, template, is_generated=False)
        db.session.add(MerchantInventory(
            merchant_id=merchant.id,
            campaign_item_id=campaign_item.id,
            stock_quantity=-1,
            price_override=int(template.get("value_copper", 0) or 0),
            generated_ingame_day=0,
            is_sold_out=False,
        ))


def _refresh_rotating_stock(merchant: Merchant, campaign: Campaign) -> None:
    current_day = int(campaign.current_ingame_day or 1)
    if int(merchant.last_refresh_ingame_day or 0) == current_day:
        return

    for entry in list(merchant.inventory):
        if int(entry.generated_ingame_day or 0) > 0:
            db.session.delete(entry)

    rule_entries = _pattern_rule_names_for_merchant(merchant)
    if rule_entries:
        location_tier = int(_load_merchant_profile(merchant).get("location_tier", 3) or 3)
        desired_count = min(len(rule_entries) + max(0, location_tier - 3), max(1, location_tier + 1))
        rng = random.Random(f"merchant:{merchant.id}:day:{current_day}")
        existing_names: set[str] = set()
        for attempt_index in range(desired_count):
            rule_entry = rng.choice(rule_entries)
            rule_name = str(rule_entry.get("pattern", "")).strip()
            template = _build_generated_template(rule_name, location_tier, merchant, rng, existing_names, attempt_index)
            if not template:
                continue
            existing_names.add(template["name"])
            stack_range = ROTATION_PATTERN_DEFINITIONS.get(rule_name, {}).get("stack_range")
            stock_quantity = rng.randint(*stack_range) if isinstance(stack_range, tuple) and len(stack_range) == 2 else (rng.randint(2, 6) if bool(template.get("stackable")) else 1)
            campaign_item = _campaign_item_from_template(campaign.id, template, is_generated=True)
            db.session.add(MerchantInventory(
                merchant_id=merchant.id,
                campaign_item_id=campaign_item.id,
                stock_quantity=stock_quantity,
                price_override=int(template.get("value_copper", 0) or 0),
                generated_ingame_day=current_day,
                is_sold_out=False,
            ))
    merchant.last_refresh_ingame_day = current_day


def _entry_price_copper(merchant: Merchant, entry: MerchantInventory) -> int:
    campaign_item = db.session.get(CampaignItem, entry.campaign_item_id)
    base_price = int(entry.price_override if entry.price_override is not None else (campaign_item.value_final if campaign_item else 0))
    return max(1, int(round(base_price * (float(merchant.price_modifier or 100) / 100.0))))


def _serialize_merchant(merchant_npc: CampaignNPC) -> dict:
    merchant = _merchant_from_npc(merchant_npc)
    profile = _load_merchant_profile(merchant) if merchant else {}
    return {
        "merchant_id": merchant.id if merchant else None,
        "merchant_npc_id": merchant_npc.id,
        "name": merchant_npc.name,
        "role": merchant_npc.role,
        "merchant_type": merchant.merchant_type if merchant else None,
        "price_modifier": int(merchant.price_modifier or 100) if merchant else 100,
        "location_tier": int(profile.get("location_tier", 3) or 3),
        "world_location_id": profile.get("world_location_id"),
        "service_offers": list(profile.get("service_offers", [])) if isinstance(profile.get("service_offers"), list) else [],
    }


def _serialize_inventory_entry(merchant: Merchant, entry: MerchantInventory) -> dict:
    campaign_item = db.session.get(CampaignItem, entry.campaign_item_id)
    inventory_item = _inventory_item_from_campaign_item(campaign_item)
    price_copper = _entry_price_copper(merchant, entry)
    return {
        "merchant_inventory_id": entry.id,
        "campaign_item_id": campaign_item.id if campaign_item else None,
        "name": inventory_item.get("name", campaign_item.name if campaign_item else "Unknown Item"),
        "description": inventory_item.get("description", campaign_item.description if campaign_item else ""),
        "item_type": inventory_item.get("item_type", campaign_item.item_type if campaign_item else None),
        "rarity": inventory_item.get("rarity", campaign_item.rarity if campaign_item else "common"),
        "item_level": int(inventory_item.get("item_level", 1) or 1),
        "stock_quantity": int(entry.stock_quantity or 0),
        "is_infinite_stock": int(entry.stock_quantity or 0) < 0,
        "generated_ingame_day": int(entry.generated_ingame_day or 0),
        "price_copper": price_copper,
        "price": _copper_to_currency(price_copper),
        "tooltip": build_item_tooltip(inventory_item),
        "bonus_lines": build_item_bonus_lines(inventory_item),
        "item": inventory_item,
    }


def get_merchants_at_location(campaign_id: int, location_id: int | None = None) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    location = db.session.get(CampaignLocation, location_id) if location_id else _current_campaign_location(campaign)
    if not location:
        return {"success": False, "message": "Current location not found."}

    _ensure_fixed_merchants_for_location(campaign, location)
    _ensure_dynamic_merchants_for_location(campaign, location)
    merchant_npcs = (
        CampaignNPC.query
        .join(Merchant, Merchant.campaign_npc_id == CampaignNPC.id)
        .filter(CampaignNPC.campaign_id == campaign.id, CampaignNPC.current_location_id == location.id)
        .order_by(CampaignNPC.name.asc())
        .all()
    )
    return {
        "success": True,
        "tool": "get_merchants_at_location",
        "location_id": location.id,
        "location_name": location.name,
        "merchants": [_serialize_merchant(npc) for npc in merchant_npcs],
    }


def serialize_location_merchants(campaign_id: int, location_id: int | None = None) -> list[dict]:
    payload = get_merchants_at_location(campaign_id=campaign_id, location_id=location_id)
    return list(payload.get("merchants", [])) if payload.get("success") else []


def get_merchant_inventory(campaign_id: int, merchant_npc_id: int) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    merchant_npc = _merchant_npc_from_id(campaign_id, merchant_npc_id)
    current_location = _current_campaign_location(campaign)
    if merchant_npc and current_location:
        _ensure_dynamic_merchant_for_npc(campaign, current_location, merchant_npc)
    merchant = _merchant_from_npc(merchant_npc)
    if not merchant_npc or not merchant:
        return {"success": False, "message": "Merchant not found."}
    if not _current_location_matches_merchant(campaign, merchant_npc):
        return {"success": False, "message": "Merchant is not at the current location."}

    _ensure_base_stock(merchant, campaign.id)
    _refresh_rotating_stock(merchant, campaign)
    db.session.commit()
    db.session.refresh(merchant)
    stock_entries = [_serialize_inventory_entry(merchant, entry) for entry in merchant.inventory if not bool(entry.is_sold_out)]
    stock_entries.sort(key=lambda entry: (entry["generated_ingame_day"], entry["price_copper"], entry["name"]))

    merchant_payload = _serialize_merchant(merchant_npc)
    return {
        "success": True,
        "tool": "get_merchant_inventory",
        "merchant": merchant_payload,
        "inventory": stock_entries,
        "service_offers": merchant_payload.get("service_offers", []),
    }


def buy_item_from_merchant(campaign_id: int, merchant_npc_id: int, merchant_inventory_id: int, quantity: int = 1) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "message": "Character not found."}
    merchant_npc = _merchant_npc_from_id(campaign_id, merchant_npc_id)
    merchant = _merchant_from_npc(merchant_npc)
    if not merchant_npc or not merchant:
        return {"success": False, "message": "Merchant not found."}
    if not _current_location_matches_merchant(campaign, merchant_npc):
        return {"success": False, "message": "Merchant is not at the current location."}

    entry = MerchantInventory.query.filter_by(id=merchant_inventory_id, merchant_id=merchant.id).first()
    if not entry or bool(entry.is_sold_out):
        return {"success": False, "message": "Merchant stock entry not found."}
    quantity = max(1, int(quantity or 1))
    if int(entry.stock_quantity or 0) >= 0 and quantity > int(entry.stock_quantity or 0):
        return {"success": False, "message": "Merchant does not have that many in stock."}

    campaign_item = db.session.get(CampaignItem, entry.campaign_item_id)
    inventory_item = _inventory_item_from_campaign_item(campaign_item)
    total_price_copper = _entry_price_copper(merchant, entry) * quantity
    current_currency = load_currency(character.id)
    if _currency_to_copper(current_currency) < total_price_copper:
        return {"success": False, "message": "Not enough money.", "price": _copper_to_currency(total_price_copper), "currency": current_currency}

    inventory_result = add_inventory_item(character_id=character.id, item=inventory_item, quantity=quantity).to_dict()
    if not inventory_result.get("success"):
        return {"success": False, "message": inventory_result.get("message", "Could not add item to inventory.")}

    save_currency(character.id, _copper_to_currency(_currency_to_copper(current_currency) - total_price_copper))
    if int(entry.stock_quantity or 0) >= 0:
        entry.stock_quantity = max(0, int(entry.stock_quantity or 0) - quantity)
        if int(entry.stock_quantity or 0) <= 0:
            entry.is_sold_out = True
    db.session.commit()
    return {
        "success": True,
        "tool": "buy_item_from_merchant",
        "message": f"Bought {quantity}x {inventory_item.get('name', campaign_item.name)}.",
        "merchant": _serialize_merchant(merchant_npc),
        "item": inventory_item,
        "quantity": quantity,
        "price": _copper_to_currency(total_price_copper),
        "currency": load_currency(character.id),
        "inventory": inventory_result.get("inventory"),
        "details": {
            "merchant_inventory_id": entry.id,
            "remaining_stock_quantity": int(entry.stock_quantity or 0),
            "is_infinite_stock": int(entry.stock_quantity or 0) < 0,
        },
    }


def buy_merchant_service(
    campaign_id: int,
    merchant_npc_id: int,
    service_id: str,
    charge_price: bool = True,
    reward_context: dict | None = None,
) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "message": "Character not found."}
    merchant_npc = _merchant_npc_from_id(campaign_id, merchant_npc_id)
    merchant = _merchant_from_npc(merchant_npc)
    if not merchant_npc or not merchant:
        return {"success": False, "message": "Merchant not found."}
    if not _current_location_matches_merchant(campaign, merchant_npc):
        return {"success": False, "message": "Merchant is not at the current location."}

    service_offer = _find_service_offer(merchant, service_id)
    if not service_offer:
        return {"success": False, "message": "Merchant service not found."}

    price_copper = int(service_offer.get("price_copper", 0) or 0)
    current_currency = load_currency(character.id)
    if charge_price and _currency_to_copper(current_currency) < price_copper:
        return {
            "success": False,
            "message": "Not enough money.",
            "price": _copper_to_currency(price_copper),
            "currency": current_currency,
        }

    from services.adventure_state.tools import rest, spend_time

    service_type = str(service_offer.get("service_type", "")).strip().lower()
    if service_type == "meal":
        service_result = spend_time(
            campaign_id=campaign.id,
            action_type="inn_meal",
            description=f"Bought {service_offer.get('name', 'a meal')} from {merchant_npc.name}.",
        )
    elif service_type == "lodging":
        service_result = rest(
            campaign_id=campaign.id,
            rest_type="sleep_until_morning",
        )
    else:
        return {"success": False, "message": "Unsupported merchant service type."}

    if not service_result.get("success"):
        return {
            "success": False,
            "message": service_result.get("error") or service_result.get("message") or "Service could not be completed.",
            "service": service_offer,
        }

    if charge_price:
        save_currency(character.id, _copper_to_currency(_currency_to_copper(current_currency) - price_copper))

    return {
        "success": True,
        "tool": "buy_merchant_service",
        "message": f"Bought service '{service_offer.get('name', 'service')}'.",
        "merchant": _serialize_merchant(merchant_npc),
        "service": service_offer,
        "price": _copper_to_currency(price_copper),
        "price_charged": charge_price,
        "currency": load_currency(character.id),
        "time_result": service_result,
        "reward_context": reward_context,
    }


def sell_item_to_merchant(campaign_id: int, merchant_npc_id: int, item_id: str, quantity: int = 1) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    character = db.session.get(Character, campaign.character_id)
    if not character:
        return {"success": False, "message": "Character not found."}
    merchant_npc = _merchant_npc_from_id(campaign_id, merchant_npc_id)
    merchant = _merchant_from_npc(merchant_npc)
    if not merchant_npc or not merchant:
        return {"success": False, "message": "Merchant not found."}
    if not _current_location_matches_merchant(campaign, merchant_npc):
        return {"success": False, "message": "Merchant is not at the current location."}

    inventory_blob = load_inventory_blob(character.id)
    normalized_lookup = str(item_id or "").strip().lower()
    found_item = None
    found_container_id = None
    for container in inventory_blob.get("inventory", {}).get("containers", []):
        for item in container.get("items", []):
            existing_id = str(item.get("item_id", "")).strip().lower()
            existing_name = str(item.get("name", "")).strip().lower()
            if existing_id == normalized_lookup or existing_name == normalized_lookup or normalized_lookup in existing_name:
                found_item = deepcopy(item)
                found_container_id = container.get("container_id")
                break
        if found_item:
            break

    if not found_item:
        return {"success": False, "message": "Item not found in inventory."}
    if str(found_item.get("item_type", "")).strip().lower() == "quest":
        return {"success": False, "message": "Quest items cannot be sold."}

    quantity = max(1, int(quantity or 1))
    available_quantity = int(found_item.get("quantity", 1) or 1)
    if quantity > available_quantity:
        return {"success": False, "message": "Not enough quantity to sell."}

    unit_value_copper = int(found_item.get("value_copper", 0) or 0)
    if unit_value_copper <= 0:
        unit_value_copper = max(4, min(250, len(str(found_item.get("name", ""))) * 6))
    total_sell_price = max(1, int(round(unit_value_copper * 0.4))) * quantity

    removal_result = remove_inventory_item(
        character_id=character.id,
        item_id=str(found_item.get("item_id") or found_item.get("name") or item_id),
        quantity=quantity,
        container_id=found_container_id,
    ).to_dict()
    if not removal_result.get("success"):
        return {"success": False, "message": removal_result.get("message", "Could not remove item from inventory.")}

    current_currency = load_currency(character.id)
    save_currency(character.id, _copper_to_currency(_currency_to_copper(current_currency) + total_sell_price))

    sold_template = deepcopy(found_item)
    sold_template["quantity"] = 1
    sold_template.setdefault("rarity", "common")
    sold_template.setdefault("item_level", 1)
    sold_template["value_copper"] = unit_value_copper
    sold_template["template_id"] = f"sold_{sold_template.get('item_id', 'item')}"
    campaign_item = _campaign_item_from_template(campaign.id, sold_template, is_generated=True)
    db.session.add(MerchantInventory(
        merchant_id=merchant.id,
        campaign_item_id=campaign_item.id,
        stock_quantity=quantity,
        price_override=max(1, int(round(unit_value_copper * 1.15))),
        generated_ingame_day=int(campaign.current_ingame_day or 1),
        is_sold_out=False,
    ))
    db.session.commit()
    return {
        "success": True,
        "tool": "sell_item_to_merchant",
        "message": f"Sold {quantity}x {found_item.get('name', 'Item')}.",
        "merchant": _serialize_merchant(merchant_npc),
        "item_name": found_item.get("name", "Item"),
        "quantity": quantity,
        "price": _copper_to_currency(total_sell_price),
        "currency": load_currency(character.id),
        "inventory": removal_result.get("inventory"),
    }
