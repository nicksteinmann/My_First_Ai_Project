from copy import deepcopy
from typing import Dict, Any, Optional
from uuid import uuid4

from .constants import (
    DEFAULT_BASE_CONTAINER,
    DEFAULT_ITEM_PROFILE,
    ITEM_TYPE_DEFAULTS,
    SIZE_ORDER,
    VALID_HAND_USAGE,
    VALID_SIZES,
)
from .repository import load_inventory_blob, save_inventory_blob
from .schemas import InventoryOperationResult


def _get_containers(inventory_blob: Dict[str, Any]):
    inventory_blob.setdefault("inventory", {})
    inventory_blob["inventory"].setdefault("containers", [deepcopy(DEFAULT_BASE_CONTAINER)])
    return inventory_blob["inventory"]["containers"]


def _find_container(containers, container_id: str):
    for container in containers:
        if container["container_id"] == container_id:
            return container
    return None


def _size_fits(item_size: str, container_size: str) -> bool:
    return SIZE_ORDER[item_size] <= SIZE_ORDER[container_size]


def _used_volume(container: Dict[str, Any]) -> float:
    total = 0.0
    for item in container.get("items", []):
        total += float(item["volume"]) * int(item["quantity"])
    return total


def _available_volume(container: Dict[str, Any]) -> float:
    return float(container["max_volume"]) - _used_volume(container)


def _normalize_item_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    if not item:
        raise ValueError("Item payload is required.")

    normalized = dict(DEFAULT_ITEM_PROFILE)
    normalized.update(item)

    item_type = normalized.get("item_type")
    if item_type and item_type in ITEM_TYPE_DEFAULTS:
        defaults = ITEM_TYPE_DEFAULTS[item_type]
        for key, value in defaults.items():
            normalized.setdefault(key, value)

    normalized["item_id"] = normalized.get("item_id") or f"item_{uuid4().hex[:12]}"
    normalized["name"] = (normalized.get("name") or "").strip()
    normalized["description"] = normalized.get("description") or ""
    normalized["size"] = (normalized.get("size") or "small").strip().lower()
    normalized["volume"] = float(normalized.get("volume", 1.0))
    normalized["weight"] = float(normalized.get("weight", 1.0))
    normalized["stackable"] = bool(normalized.get("stackable", False))
    normalized["quantity"] = int(normalized.get("quantity", 1))
    normalized["hand_usage"] = (normalized.get("hand_usage") or "none").strip().lower()

    if not normalized["name"]:
        raise ValueError("Item name is required.")

    if normalized["size"] not in VALID_SIZES:
        raise ValueError(f"Invalid item size: {normalized['size']}")

    if normalized["hand_usage"] not in VALID_HAND_USAGE:
        raise ValueError(f"Invalid hand usage: {normalized['hand_usage']}")

    if normalized["volume"] <= 0:
        raise ValueError("Item volume must be greater than 0.")

    if normalized["weight"] < 0:
        raise ValueError("Item weight cannot be negative.")

    if normalized["quantity"] <= 0:
        raise ValueError("Item quantity must be greater than 0.")

    return normalized


def _find_stack(container: Dict[str, Any], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not item["stackable"]:
        return None

    for existing in container.get("items", []):
        if (
            existing["name"] == item["name"]
            and existing["description"] == item["description"]
            and existing["size"] == item["size"]
            and float(existing["volume"]) == float(item["volume"])
            and float(existing["weight"]) == float(item["weight"])
            and existing["stackable"] is True
            and existing["hand_usage"] == item["hand_usage"]
        ):
            return existing

    return None


def get_inventory(character_id: int) -> Dict[str, Any]:
    inventory_blob = load_inventory_blob(character_id)
    return inventory_blob


def add_inventory_item(
    character_id: int,
    item: Dict[str, Any],
    quantity: int = 1,
    container_id: Optional[str] = None
) -> InventoryOperationResult:
    inventory_blob = load_inventory_blob(character_id)
    containers = _get_containers(inventory_blob)

    target_container_id = container_id or DEFAULT_BASE_CONTAINER["container_id"]
    target_container = _find_container(containers, target_container_id)

    if not target_container:
        return InventoryOperationResult(
            success=False,
            message=f"Container '{target_container_id}' not found.",
            inventory=inventory_blob,
        )

    normalized_item = _normalize_item_payload(item)
    normalized_item["quantity"] = int(quantity)

    if not _size_fits(normalized_item["size"], target_container["max_item_size"]):
        return InventoryOperationResult(
            success=False,
            message=(
                f"Item '{normalized_item['name']}' does not fit into container "
                f"'{target_container['name']}' because of size."
            ),
            inventory=inventory_blob,
        )

    required_volume = normalized_item["volume"] * normalized_item["quantity"]
    if required_volume > _available_volume(target_container):
        return InventoryOperationResult(
            success=False,
            message=(
                f"Not enough space in container '{target_container['name']}'."
            ),
            inventory=inventory_blob,
            details={
                "required_volume": required_volume,
                "available_volume": _available_volume(target_container),
            }
        )

    stack = _find_stack(target_container, normalized_item)
    if stack:
        stack["quantity"] += normalized_item["quantity"]
    else:
        target_container.setdefault("items", []).append(normalized_item)

    save_inventory_blob(character_id, inventory_blob)

    return InventoryOperationResult(
        success=True,
        message=f"Added {normalized_item['quantity']}x {normalized_item['name']} to {target_container['name']}.",
        inventory=inventory_blob,
        details={
            "container_id": target_container["container_id"],
            "item_id": normalized_item["item_id"],
        }
    )

def remove_inventory_item(
        character_id: int,
        item_id: str,
        quantity: int = 1,
        container_id: Optional[str] = None
) -> InventoryOperationResult:
    inventory_blob = load_inventory_blob(character_id)
    containers = _get_containers(inventory_blob)

    if not item_id or not item_id.strip():
        return InventoryOperationResult(
            success=False,
            message="item_id is required.",
            inventory=inventory_blob,
        )

    item_id = item_id.strip()
    quantity = int(quantity)

    if quantity <= 0:
        return InventoryOperationResult(
            success=False,
            message="Quantity must be greater than 0.",
            inventory=inventory_blob,
        )

    candidate_containers = containers
    if container_id:
        target = _find_container(containers, container_id)
        if not target:
            return InventoryOperationResult(
                success=False,
                message=f"Container '{container_id}' not found.",
                inventory=inventory_blob,
            )
        candidate_containers = [target]

    for container in candidate_containers:
        for existing in container.get("items", []):
            if existing["item_id"] == item_id:
                if existing["quantity"] < quantity:
                    return InventoryOperationResult(
                        success=False,
                        message=(
                            f"Cannot remove {quantity}x {existing['name']}. "
                            f"Only {existing['quantity']} available."
                        ),
                        inventory=inventory_blob,
                    )

                existing["quantity"] -= quantity
                if existing["quantity"] == 0:
                    container["items"].remove(existing)

                save_inventory_blob(character_id, inventory_blob)

                return InventoryOperationResult(
                    success=True,
                    message=f"Removed {quantity}x {existing['name']} from {container['name']}.",
                    inventory=inventory_blob,
                    details={
                        "container_id": container["container_id"],
                        "item_id": item_id,
                    }
                )

    return InventoryOperationResult(
        success=False,
        message=f"Item '{item_id}' not found.",
        inventory=inventory_blob,
    )