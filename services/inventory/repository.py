import json
from typing import Dict, Any

from models import db, Character
from .constants import DEFAULT_BASE_CONTAINER


def _safe_load_json(raw_value: str) -> Dict[str, Any]:
    if not raw_value:
        return {}

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return {}


def _safe_dump_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_inventory_blob(character_id: int) -> Dict[str, Any]:
    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")

    inventory_blob = _safe_load_json(character.inventory_json)

    if not inventory_blob or "inventory" not in inventory_blob:
        inventory_blob = {
            "inventory": {
                "containers": [DEFAULT_BASE_CONTAINER.copy()]
            }
        }
        character.inventory_json = _safe_dump_json(inventory_blob)
        db.session.add(character)
        db.session.commit()

    return inventory_blob


def save_inventory_blob(character_id: int, inventory_blob: Dict[str, Any]) -> None:
    character = db.session.get(Character, character_id)
    if not character:
        raise ValueError("Character not found.")

    character.inventory_json = _safe_dump_json(inventory_blob)
    db.session.add(character)
    db.session.commit()