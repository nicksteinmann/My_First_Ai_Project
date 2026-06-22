"""Character portrait metadata, asset lookup, and generation prompts."""

from __future__ import annotations

from pathlib import Path


CHARACTER_GENDERS = {
    "male": {
        "label": "Male",
        "prompt_hint": (
            "masculine facial structure, slightly broader jawline, grounded fantasy realism"
        ),
    },
    "female": {
        "label": "Female",
        "prompt_hint": (
            "feminine facial structure, softer lines, grounded fantasy realism, not sexualized"
        ),
    },
}

RACE_PROMPT_HINTS = {
    "Human": "medieval European-inspired human, grounded and believable",
    "Elf": "elegant fantasy elf, fine features, refined presence",
    "Dwarf": "compact dwarf, broad face, heavy brow, sturdy nose, robust build",
    "Orc": "red-skinned orc, strong bone structure, fierce but intelligent",
    "Goblin": "wiry goblin, sharp clever face, narrow features, serious not goofy",
}

CLASS_PROMPT_HINTS = {
    "Knight": "knight, steel gorget and shoulder armor, hint of weapon hilt, martial role instantly readable",
    "Mage": "mage, arcane robes, magical focus or wand near shoulder, mystical role instantly readable",
    "Rogue": "rogue, dark leather, shoulder strap, dagger handle visible, stealth role instantly readable",
    "Priest": "priest, sacred robe, holy symbol, spiritual authority instantly readable",
    "Ranger": "ranger, travel leathers or mantle, bow visible near shoulder, scout role instantly readable",
}

STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "character_portraits"

BASE_STYLE_PROMPT = (
    "semi-realistic fantasy portrait, painted realism, consistent RPG character-select portrait, "
    "head-and-shoulders framing, subtle shoulder and gear visibility, premium fantasy game art, "
    "not cartoony, believable costume materials, readable silhouette, soft dramatic lighting"
)


def normalize_character_gender(value: str | None) -> str:
    """Return a supported gender key with a stable fallback."""

    normalized = str(value or "").strip().lower()
    if normalized in CHARACTER_GENDERS:
        return normalized
    return "male"


def build_character_portrait_key(race: str, class_name: str, gender: str) -> str:
    """Return the stable portrait asset key for one playable combination."""

    normalized_gender = normalize_character_gender(gender)
    race_key = str(race or "").strip().lower().replace(" ", "_")
    class_key = str(class_name or "").strip().lower().replace(" ", "_")
    return f"{race_key}_{class_key}_{normalized_gender}"


def get_character_portrait_filename(race: str, class_name: str, gender: str) -> str:
    """Return the portrait filename for one playable combination."""

    return f"{build_character_portrait_key(race, class_name, gender)}.png"


def get_character_portrait_asset_path(race: str, class_name: str, gender: str) -> Path:
    """Return the absolute portrait asset path for one playable combination."""

    return STATIC_DIR / get_character_portrait_filename(race, class_name, gender)


def get_character_portrait_url(race: str, class_name: str, gender: str) -> str | None:
    """Return the static URL when an asset exists, otherwise None."""

    path = get_character_portrait_asset_path(race, class_name, gender)
    if not path.exists():
        return None
    return f"/static/character_portraits/{path.name}"


def build_character_portrait_prompt(race: str, class_name: str, gender: str) -> str:
    """Return the image-generation prompt for one playable combination."""

    race_hint = RACE_PROMPT_HINTS.get(race, "fantasy adventurer")
    class_hint = CLASS_PROMPT_HINTS.get(class_name, "fantasy role clearly visible")
    gender_key = normalize_character_gender(gender)
    gender_hint = CHARACTER_GENDERS[gender_key]["prompt_hint"]

    return (
        f"{BASE_STYLE_PROMPT}, {race_hint}, {class_hint}, {gender_hint}, "
        "single character portrait, centered, plain atmospheric background, no text, no watermark"
    )
