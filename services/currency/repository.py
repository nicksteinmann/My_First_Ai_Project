"""Persistence helpers for character currency JSON."""

from typing import Dict

from sqlalchemy.orm.attributes import flag_modified

from models import db, Character
from services.currency.constants import VALID_CURRENCY_TYPES


def _default_currency() -> Dict[str, int]:
    """Return the canonical empty currency structure."""

    return {
        "gold": 0,
        "silver": 0,
        "copper": 0,
    }


def load_currency(character_id: int) -> Dict[str, int]:
    """Load currency and backfill missing denominations."""

    character: Character = db.session.get(Character, character_id)

    if not character:
        raise ValueError(f"Character with id {character_id} not found.")

    if not character.currency_json:
        currency = _default_currency()
        character.currency_json = currency
        flag_modified(character, "currency_json")
        db.session.commit()
        return currency

    currency = dict(character.currency_json)
    changed = False

    for key in VALID_CURRENCY_TYPES:
        if key not in currency:
            currency[key] = 0
            changed = True

    if changed:
        character.currency_json = dict(currency)
        flag_modified(character, "currency_json")
        db.session.commit()

    return currency


def save_currency(character_id: int, currency: Dict[str, int]) -> None:
    """Persist a complete currency mapping for a character."""

    character: Character = db.session.get(Character, character_id)

    if not character:
        raise ValueError(f"Character with id {character_id} not found.")

    character.currency_json = {
        key: int(currency.get(key, 0) or 0)
        for key in VALID_CURRENCY_TYPES
    }
    flag_modified(character, "currency_json")
    db.session.commit()
