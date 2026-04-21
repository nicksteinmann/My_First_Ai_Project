"""Container-based inventory operations.

Inventory data is stored as JSON on the character for the MVP. The service
keeps item normalization, size checks, volume checks, stacking, and persistence
deterministic so the LLM can only request inventory changes through tools.
"""

from copy import deepcopy
from typing import Dict, Any, Optional
from uuid import uuid4

from .constants import (
    DEFAULT_BASE_CONTAINER,
    DEFAULT_ITEM_PROFILE,
    HAND_CONTAINERS,
    ITEM_TYPE_DEFAULTS,
    SIZE_ORDER,
    VALID_HAND_USAGE,
    VALID_SIZES,
)
from .repository import load_inventory_blob, save_inventory_blob
from .schemas import InventoryOperationResult


HAND_USAGE_ALIASES = {
    "one-handed": "one_handed",
    "one handed": "one_handed",
    "onehanded": "one_handed",
    "one-hand": "one_handed",
    "one hand": "one_handed",
    "one_hand": "one_handed",
    "one": "one_handed",
    "two-handed": "two_handed",
    "two handed": "two_handed",
    "twohanded": "two_handed",
    "two-hands": "two_handed",
    "two hands": "two_handed",
    "two hand": "two_handed",
    "two_hand": "two_handed",
    "two_hands": "two_handed",
    "two": "two_handed",
    "none": "none",
    "no": "none",
    "no hands": "none",
    "no hand": "none",
    "free": "none",
}


# ---------------------------------------------------------------------------
# Container helpers
# ---------------------------------------------------------------------------


def _get_containers(inventory_blob: Dict[str, Any]):
    """Return inventory containers, creating the base container if missing."""

    inventory_blob.setdefault("inventory", {})
    inventory_blob["inventory"].setdefault("containers", [deepcopy(DEFAULT_BASE_CONTAINER)])
    return inventory_blob["inventory"]["containers"]


def _get_equipment_slots(inventory_blob: Dict[str, Any]) -> Dict[str, Any]:
    """Return raw equipment slots from the inventory blob."""

    return inventory_blob.get("equipment", {}).get("slots", {})


def _find_container(containers, container_id: str):
    """Find one container by id in a container list."""

    for container in containers:
        if container["container_id"] == container_id:
            return container
    return None


def _find_container_index(containers, container_id: str) -> Optional[int]:
    """Find a container index by id in a container list."""

    for index, container in enumerate(containers):
        if container.get("container_id") == container_id:
            return index
    return None


def _sync_hand_containers(inventory_blob: Dict[str, Any]) -> None:
    """Create hand containers for free hands and remove empty blocked ones."""

    containers = _get_containers(inventory_blob)
    slots = _get_equipment_slots(inventory_blob)

    for hand_slot, profile in HAND_CONTAINERS.items():
        container_id = profile["container_id"]
        container_index = _find_container_index(containers, container_id)

        if not slots.get(hand_slot):
            if container_index is None:
                containers.append(deepcopy(profile))
            continue

        if container_index is not None and not containers[container_index].get("items"):
            containers.pop(container_index)


def _size_fits(item_size: str, container_size: str) -> bool:
    """Return whether an item size is allowed in a container size profile."""

    return SIZE_ORDER[item_size] <= SIZE_ORDER[container_size]


def _used_volume(container: Dict[str, Any]) -> float:
    """Calculate used volume based on item volume and quantity."""

    total = 0.0
    for item in container.get("items", []):
        total += float(item["volume"]) * int(item["quantity"])
    return total


def _available_volume(container: Dict[str, Any]) -> float:
    """Return remaining volume in a container."""

    return float(container["max_volume"]) - _used_volume(container)


def _can_store_item(container: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """Return whether a container can hold the item by size and volume."""

    if container.get("source") == "hands" and item.get("hand_usage") != "none":
        return False

    if not _size_fits(item["size"], container["max_item_size"]):
        return False

    required_volume = item["volume"] * item["quantity"]
    return required_volume <= _available_volume(container)


def _is_carried_container(container: Dict[str, Any]) -> bool:
    """Return whether a container is physically carried by the character."""

    return container.get("source") in ("equipment", "hands")


def _find_first_carried_container_with_space(containers, item: Dict[str, Any]):
    """Find the first carried container that can accept an item."""

    for container in containers:
        if container.get("source") == "equipment" and _can_store_item(container, item):
            return container

    for container in containers:
        if _is_carried_container(container) and _can_store_item(container, item):
            return container

    return None


# ---------------------------------------------------------------------------
# Item normalization and stacking
# ---------------------------------------------------------------------------


def _normalize_item_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and validate an item payload before inserting it."""

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

    raw_hand_usage = (normalized.get("hand_usage") or "none").strip().lower()
    normalized["hand_usage"] = HAND_USAGE_ALIASES.get(raw_hand_usage, raw_hand_usage)

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
    """Return a compatible existing stack for a stackable item."""

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


# ---------------------------------------------------------------------------
# Public inventory operations
# ---------------------------------------------------------------------------


def get_inventory(character_id: int) -> Dict[str, Any]:
    """Return the raw inventory blob for a character."""

    inventory_blob = load_inventory_blob(character_id)
    _sync_hand_containers(inventory_blob)
    save_inventory_blob(character_id, inventory_blob)
    return inventory_blob


def add_inventory_item(
    character_id: int,
    item: Dict[str, Any],
    quantity: int = 1,
    container_id: Optional[str] = None
) -> InventoryOperationResult:
    """Add an item to a specific inventory container after validation."""

    inventory_blob = load_inventory_blob(character_id)
    _sync_hand_containers(inventory_blob)
    containers = _get_containers(inventory_blob)

    normalized_item = _normalize_item_payload(item)
    normalized_item["quantity"] = int(quantity)

    if container_id:
        target_container = _find_container(containers, container_id)
        if not target_container:
            return InventoryOperationResult(
                success=False,
                message=f"Container '{container_id}' not found.",
                inventory=inventory_blob,
            )
    else:
        target_container = _find_first_carried_container_with_space(containers, normalized_item)
        if not target_container:
            return InventoryOperationResult(
                success=False,
                message=(
                    f"No carried container has enough space for '{normalized_item['name']}'."
                ),
                inventory=inventory_blob,
            )

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
    container_id: Optional[str] = None,
) -> InventoryOperationResult:
    """Remove an item by id or fuzzy name from one or all containers."""

    inventory_blob = load_inventory_blob(character_id)
    _sync_hand_containers(inventory_blob)
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

    normalized_item_id = item_id.lower().strip()

    for container in candidate_containers:
        for existing in container.get("items", []):
            existing_id = existing["item_id"].lower()
            existing_name = existing["name"].lower().strip()

            if (
                existing_id == normalized_item_id
                or existing_name == normalized_item_id
                or normalized_item_id in existing_name
            ):
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
                        "item_id": existing["item_id"],
                    }
                )

    print("REMOVE FAILED:", item_id)

    return InventoryOperationResult(
        success=False,
        message=f"Item '{item_id}' not found.",
        inventory=inventory_blob,
    )
