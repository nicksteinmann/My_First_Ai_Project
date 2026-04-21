SIZE_ORDER = {
    "tiny": 1,
    "small": 2,
    "medium": 3,
    "large": 4,
    "gigantic": 5,
}

VALID_SIZES = tuple(SIZE_ORDER.keys())
VALID_HAND_USAGE = ("none", "one_handed", "two_handed")

DEFAULT_BASE_CONTAINER = {
    "container_id": "base_inventory",
    "name": "No Carried Container",
    "source": "base",
    "source_item_id": None,
    "max_volume": 0.0,
    "max_item_size": "tiny",
    "items": [],
}

HAND_CONTAINERS = {
    "main_hand": {
        "container_id": "hand_main",
        "name": "Holding Items (Main Hand)",
        "source": "hands",
        "source_item_id": "main_hand",
        "max_volume": 1.0,
        "max_item_size": "small",
        "items": [],
    },
    "off_hand": {
        "container_id": "hand_off",
        "name": "Holding Items (Off Hand)",
        "source": "hands",
        "source_item_id": "off_hand",
        "max_volume": 1.0,
        "max_item_size": "small",
        "items": [],
    },
}

HAND_CONTAINER_IDS = {
    slot: profile["container_id"]
    for slot, profile in HAND_CONTAINERS.items()
}

# Fallback item profile when generated items omit values.
DEFAULT_ITEM_PROFILE = {
    "description": "",
    "size": "small",
    "volume": 1.0,
    "weight": 1.0,
    "stackable": False,
    "quantity": 1,
    "hand_usage": "none",
}

# Heuristics for legacy/generated items that omit physical defaults.
ITEM_TYPE_DEFAULTS = {
    "weapon": {
        "size": "medium",
        "volume": 2.0,
        "weight": 3.0,
        "stackable": False,
        "hand_usage": "one_handed",
    },
    "armor": {
        "size": "large",
        "volume": 4.0,
        "weight": 5.0,
        "stackable": False,
        "hand_usage": "none",
    },
    "consumable": {
        "size": "small",
        "volume": 0.5,
        "weight": 0.5,
        "stackable": True,
        "hand_usage": "none",
    },
    "utility": {
        "size": "small",
        "volume": 1.0,
        "weight": 1.0,
        "stackable": False,
        "hand_usage": "none",
    },
    "material": {
        "size": "small",
        "volume": 0.5,
        "weight": 0.5,
        "stackable": True,
        "hand_usage": "none",
    },
    "quest": {
        "size": "small",
        "volume": 0.2,
        "weight": 0.2,
        "stackable": False,
        "hand_usage": "none",
    },
}
