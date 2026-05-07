MAX_CHARACTER_LEVEL = 100
XP_BASE_COST = 100
XP_CURVE_EXPONENT = 1.55

LEVEL_RENOWN_TIERS = [
    {
        "key": "unknown",
        "label": "Unknown",
        "min_level": 1,
        "max_level": 4,
        "recognition_scope": "none",
        "prompt_hint": "Most people have never heard of this character.",
    },
    {
        "key": "familiar_face",
        "label": "Familiar Face",
        "min_level": 5,
        "max_level": 9,
        "recognition_scope": "small local",
        "prompt_hint": "A few locals may recognize the character from recent deeds.",
    },
    {
        "key": "local_name",
        "label": "Local Name",
        "min_level": 10,
        "max_level": 19,
        "recognition_scope": "local",
        "prompt_hint": "People in nearby settlements may have heard the character's name.",
    },
    {
        "key": "regional_reputation",
        "label": "Regional Reputation",
        "min_level": 20,
        "max_level": 34,
        "recognition_scope": "regional",
        "prompt_hint": "The character has a real regional reputation, especially among travelers and officials.",
    },
    {
        "key": "well_known",
        "label": "Well Known",
        "min_level": 35,
        "max_level": 49,
        "recognition_scope": "wide regional",
        "prompt_hint": "Many people in the region recognize the character or know stories about them.",
    },
    {
        "key": "famous_hero",
        "label": "Famous Hero",
        "min_level": 50,
        "max_level": 74,
        "recognition_scope": "national",
        "prompt_hint": "The character is famous enough that important NPCs may know their deeds.",
    },
    {
        "key": "legendary_figure",
        "label": "Legendary Figure",
        "min_level": 75,
        "max_level": 99,
        "recognition_scope": "continental",
        "prompt_hint": "The character is treated as a legendary figure by many who know current events.",
    },
    {
        "key": "living_legend",
        "label": "Living Legend",
        "min_level": 100,
        "max_level": 100,
        "recognition_scope": "worldwide",
        "prompt_hint": "Almost everyone knows this character by name or by unmistakable stories.",
    },
]

BASE_RESOURCE_GAIN_PER_LEVEL = {
    "hp": 5,
    "mana": 2,
    "energy": 1,
}

CLASS_RESOURCE_MULTIPLIERS = {
    "Knight": {
        "hp": 1.4,
        "mana": 0.6,
        "energy": 1.1,
    },
    "Mage": {
        "hp": 0.7,
        "mana": 1.8,
        "energy": 0.9,
    },
    "Rogue": {
        "hp": 0.9,
        "mana": 0.8,
        "energy": 1.5,
    },
    "Priest": {
        "hp": 0.9,
        "mana": 1.5,
        "energy": 1.0,
    },
    "Ranger": {
        "hp": 1.0,
        "mana": 0.9,
        "energy": 1.4,
    },
}
