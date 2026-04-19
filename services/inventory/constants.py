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
    "name": "Base Inventory",
    "source": "base",
    "source_item_id": None,
    "max_volume": 10.0,
    "max_item_size": "medium",
    "items": [],
}

# Fallback-Profil, wenn ein Item keine eigenen Werte bekommt
DEFAULT_ITEM_PROFILE = {
    "description": "",
    "size": "small",
    "volume": 1.0,
    "weight": 1.0,
    "stackable": False,
    "quantity": 1,
    "hand_usage": "none",
}

# Heuristik für spätere Übergangsphase / Legacy-Daten
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