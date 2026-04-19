from typing import Dict, Optional

from services.currency.repository import load_currency, save_currency
from services.currency.constants import VALID_CURRENCY_TYPES


# ===== RESULT OBJECT =====

class CurrencyOperationResult:
    def __init__(
        self,
        success: bool,
        message: str,
        currency: Dict[str, int],
        details: Optional[Dict] = None,
    ):
        self.success = success
        self.message = message
        self.currency = currency
        self.details = details or {}


# ===== GET =====

def get_currency(character_id: int) -> Dict[str, int]:
    return load_currency(character_id)


# ===== ADD =====

def add_currency(
    character_id: int,
    gold: int = 0,
    silver: int = 0,
    copper: int = 0,
) -> CurrencyOperationResult:

    currency = load_currency(character_id)

    for key, value in {
        "gold": gold,
        "silver": silver,
        "copper": copper,
    }.items():

        if key not in VALID_CURRENCY_TYPES:
            return CurrencyOperationResult(
                success=False,
                message=f"Invalid currency type: {key}",
                currency=currency,
            )

        if not isinstance(value, int):
            return CurrencyOperationResult(
                success=False,
                message=f"{key} must be an integer.",
                currency=currency,
            )

        if value < 0:
            return CurrencyOperationResult(
                success=False,
                message=f"{key} must not be negative.",
                currency=currency,
            )

        currency[key] += value

    save_currency(character_id, currency)

    return CurrencyOperationResult(
        success=True,
        message=f"Added currency (gold={gold}, silver={silver}, copper={copper}).",
        currency=currency,
        details={
            "gold": gold,
            "silver": silver,
            "copper": copper,
        }
    )


# ===== REMOVE =====

def remove_currency(
    character_id: int,
    gold: int = 0,
    silver: int = 0,
    copper: int = 0,
) -> CurrencyOperationResult:

    currency = load_currency(character_id)

    for key, value in {
        "gold": gold,
        "silver": silver,
        "copper": copper,
    }.items():

        if key not in VALID_CURRENCY_TYPES:
            return CurrencyOperationResult(
                success=False,
                message=f"Invalid currency type: {key}",
                currency=currency,
            )

        if not isinstance(value, int):
            return CurrencyOperationResult(
                success=False,
                message=f"{key} must be an integer.",
                currency=currency,
            )

        if value < 0:
            return CurrencyOperationResult(
                success=False,
                message=f"{key} must not be negative.",
                currency=currency,
            )

        if currency[key] < value:
            return CurrencyOperationResult(
                success=False,
                message=f"Not enough {key}.",
                currency=currency,
            )

        currency[key] -= value

    save_currency(character_id, currency)

    return CurrencyOperationResult(
        success=True,
        message=f"Removed currency (gold={gold}, silver={silver}, copper={copper}).",
        currency=currency,
        details={
            "gold": gold,
            "silver": silver,
            "copper": copper,
        }
    )