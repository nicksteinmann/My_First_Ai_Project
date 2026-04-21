"""Persistence helpers for JSON-backed character inventory."""

import json
from copy import deepcopy
from typing import Dict, Any

from models import db, Character
from .constants import DEFAULT_BASE_CONTAINER


def _safe_load_json(raw_value: str) -> Dict[str, Any]:
    """Return parsed JSON or an empty dict for invalid legacy data."""

    if not raw_value:
        return {}

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return {}


def _safe_dump_json(value: Dict[str, Any]) -> str:
    """Serialize inventory JSON while preserving non-ASCII item text."""

    return json.dumps(value, ensure_ascii=False)


def load_inventory_blob(character_id: int) -> Dict[str, Any]:
    """Load inventory, creating the empty hands fallback if needed."""

    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")

    inventory_blob = _safe_load_json(character.inventory_json)

    if not inventory_blob or "inventory" not in inventory_blob:
        inventory_blob = {
            "inventory": {
                "containers": [deepcopy(DEFAULT_BASE_CONTAINER)]
            }
        }
        character.inventory_json = _safe_dump_json(inventory_blob)
        db.session.add(character)
        db.session.commit()

    return inventory_blob


def save_inventory_blob(character_id: int, inventory_blob: Dict[str, Any]) -> None:
    """Persist a complete inventory blob for a character."""

    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")

    character.inventory_json = _safe_dump_json(inventory_blob)
    db.session.add(character)
    db.session.commit()
