ATTRIBUTE_DEFINITIONS = [
    {
        "key": "strength",
        "label": "Strength",
        "icon": "💪",
    },
    {
        "key": "dexterity",
        "label": "Dexterity",
        "icon": "🤸",
    },
    {
        "key": "constitution",
        "label": "Constitution",
        "icon": "🧱",
    },
    {
        "key": "intelligence",
        "label": "Intelligence",
        "icon": "🧠",
    },
    {
        "key": "perception",
        "label": "Perception",
        "icon": "👁️",
    },
    {
        "key": "charisma",
        "label": "Charisma",
        "icon": "🗣️",
    },
]

ATTRIBUTE_KEYS = [attribute["key"] for attribute in ATTRIBUTE_DEFINITIONS]
MAX_ATTRIBUTE_LEVEL = 100
ATTRIBUTE_XP_BASE_COST = 100
ATTRIBUTE_XP_CURVE_EXPONENT = 1.55

CLASS_ATTRIBUTE_XP_WEIGHTS = {
    "Knight": {
        "strength": 0.25,
        "constitution": 0.20,
        "charisma": 0.10,
        "dexterity": 0.08,
        "perception": 0.05,
        "intelligence": 0.03,
    },
    "Mage": {
        "intelligence": 0.25,
        "charisma": 0.12,
        "perception": 0.10,
        "constitution": 0.06,
        "dexterity": 0.05,
        "strength": 0.03,
    },
    "Rogue": {
        "dexterity": 0.25,
        "perception": 0.18,
        "charisma": 0.12,
        "intelligence": 0.10,
        "strength": 0.06,
        "constitution": 0.05,
    },
    "Priest": {
        "charisma": 0.22,
        "intelligence": 0.18,
        "constitution": 0.12,
        "perception": 0.10,
        "dexterity": 0.05,
        "strength": 0.04,
    },
    "Ranger": {
        "perception": 0.25,
        "dexterity": 0.20,
        "constitution": 0.12,
        "strength": 0.10,
        "intelligence": 0.06,
        "charisma": 0.04,
    },
}

DEFAULT_ATTRIBUTE_XP_WEIGHTS = {
    "strength": 0.10,
    "dexterity": 0.10,
    "constitution": 0.10,
    "intelligence": 0.10,
    "perception": 0.10,
    "charisma": 0.10,
}
