from typing import Dict

from models import db, Character
from services.currency.constants import VALID_CURRENCY_TYPES


# ===== DEFAULT STRUCTURE =====

def _default_currency() -> Dict[str, int]:
    return {
        "gold": 0,
        "silver": 0,
        "copper": 0,
    }


# ===== LOAD =====

def load_currency(character_id: int) -> Dict[str, int]:
    character: Character = Character.query.get(character_id)

    if not character:
        raise ValueError(f"Character with id {character_id} not found.")

    if not character.currency_json:
        currency = _default_currency()
        character.currency_json = currency
        db.session.commit()
        return currency

    currency = character.currency_json

    # ensure structure (future-proofing)
    for key in VALID_CURRENCY_TYPES:
        if key not in currency:
            currency[key] = 0

    return currency


# ===== SAVE =====

def save_currency(character_id: int, currency: Dict[str, int]) -> None:
    character: Character = Character.query.get(character_id)

    if not character:
        raise ValueError(f"Character with id {character_id} not found.")

    character.currency_json = currency
    db.session.commit()