"""Equipment slot logic built on top of the inventory blob.

Equipped items are removed from normal containers and stored in equipment slots.
Items with a container profile, such as backpacks or pouches, add a dedicated
inventory container while equipped. Slot validation stays here so the LLM cannot
equip items by directly mutating JSON state.
"""

from copy import deepcopy
from typing import Any, Dict, Optional

from services.inventory.constants import DEFAULT_BASE_CONTAINER, HAND_CONTAINER_IDS, SIZE_ORDER
from services.inventory.repository import load_inventory_blob, save_inventory_blob

from .constants import (
    BELT_ATTACHMENT_SLOTS,
    BELT_POUCH_SIZES,
    EQUIPMENT_SLOTS,
    HAND_SLOTS,
    SLOT_ALIASES,
    SLOT_LABELS,
)


class EquipmentOperationResult:
    """Result object shared by equip and unequip operations."""

    def __init__(
        self,
        success: bool,
        message: str,
        equipment: Dict[str, Any],
        inventory: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.equipment = equipment
        self.inventory = inventory
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the operation result for tool responses."""

        return {
            "success": self.success,
            "message": self.message,
            "equipment": self.equipment,
            "inventory": self.inventory,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Inventory/equipment state helpers
# ---------------------------------------------------------------------------


def _get_containers(inventory_blob: Dict[str, Any]):
    """Return inventory containers, creating the base container if missing."""

    inventory_blob.setdefault("inventory", {})
    inventory_blob["inventory"].setdefault("containers", [deepcopy(DEFAULT_BASE_CONTAINER)])
    return inventory_blob["inventory"]["containers"]


def _get_equipment_state(inventory_blob: Dict[str, Any]) -> Dict[str, Any]:
    """Return equipment state and ensure every known slot exists."""

    equipment = inventory_blob.setdefault("equipment", {})
    slots = equipment.setdefault("slots", {})

    for slot in EQUIPMENT_SLOTS:
        slots.setdefault(slot, None)

    return equipment


def _normalize_slot(slot: Optional[str]) -> Optional[str]:
    """Normalize user/model slot names to canonical equipment slot ids."""

    if not slot:
        return None

    normalized = slot.strip().lower().replace("-", "_").replace(" ", "_")
    return SLOT_ALIASES.get(normalized, normalized)


# ---------------------------------------------------------------------------
# Item classification helpers
# ---------------------------------------------------------------------------


def _is_placeholder(item: Optional[Dict[str, Any]]) -> bool:
    """Return whether a slot item only marks a secondary occupied slot."""

    return bool(item and item.get("placeholder"))


def _normalized_item_type(item: Dict[str, Any]) -> str:
    return (item.get("item_type") or "").strip().lower()


def _normalized_item_size(item: Dict[str, Any]) -> str:
    return (item.get("size") or "small").strip().lower()


def _is_weapon(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) in ("weapon", "tool")


def _is_shield(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) == "shield"


def _is_backpack_item(item: Dict[str, Any]) -> bool:
    return _normalized_item_type(item) in ("backpack", "rucksack")


def _is_belt_pouch(item: Dict[str, Any]) -> bool:
    """Return whether an item is small enough and container-like for belt slots."""

    if (
        _normalized_item_type(item) in ("pouch", "belt_pouch", "coin_pouch", "small_pouch")
        and _normalized_item_size(item) in BELT_POUCH_SIZES
    ):
        return True

    if (
        _normalized_item_type(item) in ("bag", "container")
        and _normalized_item_size(item) in BELT_POUCH_SIZES
        and _container_profile_from_item(item)
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Inventory movement helpers
# ---------------------------------------------------------------------------


def _find_inventory_item(inventory_blob: Dict[str, Any], item_id: str):
    """Find an inventory item by id, exact name, or fuzzy name fragment."""

    normalized_item_id = (item_id or "").strip().lower()
    if not normalized_item_id:
        return None, None

    for container in _get_containers(inventory_blob):
        for item in container.get("items", []):
            existing_id = str(item.get("item_id", "")).lower().strip()
            existing_name = str(item.get("name", "")).lower().strip()

            if (
                existing_id == normalized_item_id
                or existing_name == normalized_item_id
                or normalized_item_id in existing_name
            ):
                return container, item

    return None, None


def _remove_one_from_container(container: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Remove one quantity from a container and return the equipped copy."""

    equipped_item = deepcopy(item)
    equipped_item["quantity"] = 1

    quantity = int(item.get("quantity", 1))
    if quantity > 1:
        item["quantity"] = quantity - 1
    else:
        container.get("items", []).remove(item)

    return equipped_item


def _used_volume(container: Dict[str, Any]) -> float:
    total = 0.0
    for item in container.get("items", []):
        total += float(item.get("volume", 0)) * int(item.get("quantity", 1))
    return total


def _size_fits(item_size: str, container_size: str) -> bool:
    return SIZE_ORDER.get(item_size, 0) <= SIZE_ORDER.get(container_size, 0)


def _find_container(inventory_blob: Dict[str, Any], container_id: str) -> Optional[Dict[str, Any]]:
    for container in _get_containers(inventory_blob):
        if container.get("container_id") == container_id:
            return container
    return None


def _remove_empty_hand_container(inventory_blob: Dict[str, Any], hand_slot: str) -> None:
    container = _find_container(inventory_blob, HAND_CONTAINER_IDS.get(hand_slot))
    if container and not container.get("items"):
        _get_containers(inventory_blob).remove(container)


def _hand_container_has_items(inventory_blob: Dict[str, Any], hand_slot: str) -> bool:
    container = _find_container(inventory_blob, HAND_CONTAINER_IDS.get(hand_slot))
    return bool(container and container.get("items"))


def _can_add_item(container: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """Return whether a container can accept an item by size and volume."""

    if container.get("source") == "hands" and item.get("hand_usage") != "none":
        return False

    if not _size_fits(item.get("size", "small"), container.get("max_item_size", "small")):
        return False

    required_volume = float(item.get("volume", 0)) * int(item.get("quantity", 1))
    available_volume = float(container.get("max_volume", 0)) - _used_volume(container)
    return required_volume <= available_volume


def _add_item_to_container(container: Dict[str, Any], item: Dict[str, Any]) -> None:
    """Add an item to a container, merging compatible stacks."""

    if item.get("stackable"):
        for existing in container.get("items", []):
            if (
                existing.get("name") == item.get("name")
                and existing.get("description") == item.get("description")
                and existing.get("size") == item.get("size")
                and float(existing.get("volume", 0)) == float(item.get("volume", 0))
                and float(existing.get("weight", 0)) == float(item.get("weight", 0))
                and existing.get("hand_usage") == item.get("hand_usage")
                and existing.get("stackable") is True
            ):
                existing["quantity"] = int(existing.get("quantity", 1)) + int(item.get("quantity", 1))
                return

    container.setdefault("items", []).append(item)


def _find_first_carried_container_with_space(inventory_blob: Dict[str, Any], item: Dict[str, Any]):
    for container in _get_containers(inventory_blob):
        if container.get("source") == "equipment" and _can_add_item(container, item):
            return container

    for container in _get_containers(inventory_blob):
        if container.get("source") == "hands" and _can_add_item(container, item):
            return container

    return None


# ---------------------------------------------------------------------------
# Slot inference and validation
# ---------------------------------------------------------------------------


def _infer_slot(item: Dict[str, Any], requested_slot: Optional[str], slots: Dict[str, Any]) -> str:
    """Infer the primary equipment slot for an item."""

    slot = _normalize_slot(requested_slot)

    if slot:
        if slot not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown equipment slot: {requested_slot}")
        return slot

    hand_usage = (item.get("hand_usage") or "none").strip().lower()
    item_type = (item.get("item_type") or "").strip().lower()
    slot_type = _normalize_slot(item.get("slot_type"))

    if slot_type:
        if slot_type not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown item slot_type: {item.get('slot_type')}")
        return slot_type

    if item_type == "shield" and not slots.get("backpack"):
        return "backpack"

    if _is_belt_pouch(item):
        for belt_slot in BELT_ATTACHMENT_SLOTS:
            if not slots.get(belt_slot):
                return belt_slot

    if hand_usage in ("one_handed", "two_handed"):
        if hand_usage == "one_handed" and slots.get("main_hand") and not slots.get("off_hand"):
            return "off_hand"
        return "main_hand"

    if item_type in ("weapon", "tool"):
        return "main_hand"
    if item_type in ("helmet", "headgear"):
        return "head"
    if item_type == "armor":
        return "torso_armor"
    if item_type in ("clothing", "shirt"):
        return "torso_clothing"
    if item_type in ("pants", "trousers"):
        return "legs_clothing"
    if item_type in ("boots", "shoes"):
        return "feet"
    if item_type in ("gloves", "glove"):
        return "gloves"
    if item_type == "belt":
        return "belt"
    if item_type in ("backpack", "bag", "container"):
        return "backpack"
    if item_type == "shield":
        return "backpack"
    if item_type == "cloak":
        return "cloak"
    if item_type == "ring":
        return "ring_left" if not slots.get("ring_left") else "ring_right"

    raise ValueError("Cannot infer equipment slot. Please provide a slot.")


def _target_slots_for_item(item: Dict[str, Any], primary_slot: str, slots: Dict[str, Any]):
    """Return all slots occupied by an item, including two-handed placeholders."""

    hand_usage = (item.get("hand_usage") or "none").strip().lower()

    if primary_slot in BELT_ATTACHMENT_SLOTS:
        return [primary_slot]

    if primary_slot == "backpack" and _is_shield(item):
        return [primary_slot]

    if hand_usage == "two_handed":
        return ["main_hand", "off_hand"]

    if hand_usage == "one_handed":
        if primary_slot not in HAND_SLOTS:
            raise ValueError("One-handed items must use main_hand or off_hand.")
        return [primary_slot]

    if primary_slot in HAND_SLOTS and not (_is_weapon(item) or _is_shield(item)):
        raise ValueError("Only hand-held items can use hand slots.")

    return [primary_slot]


def _validate_belt_attachment(item: Dict[str, Any], primary_slot: str, slots: Dict[str, Any]) -> None:
    """Validate weapons and small pouches attached to equipped belts."""

    if primary_slot not in BELT_ATTACHMENT_SLOTS:
        return

    if not slots.get("belt"):
        raise ValueError("A belt must be equipped before using belt attachment slots.")

    if _is_weapon(item):
        return

    if _is_belt_pouch(item) and _normalized_item_size(item) in BELT_POUCH_SIZES:
        return

    raise ValueError("Belt slots can only hold weapons or tiny/small pouches.")


def _validate_backpack_slot(item: Dict[str, Any], primary_slot: str) -> None:
    """Validate the backpack slot, including the shield-without-backpack rule."""

    if primary_slot != "backpack":
        return

    item_type = _normalized_item_type(item)
    if item_type in ("backpack", "rucksack", "bag", "container", "shield"):
        return

    raise ValueError("Backpack slot can only hold a backpack, container item, or shield.")


def _validate_target_slots(slots: Dict[str, Any], target_slots, item: Optional[Dict[str, Any]] = None):
    """Ensure all target slots are empty and item-specific rules pass."""

    for slot in target_slots:
        if slots.get(slot):
            raise ValueError(f"Equipment slot '{slot}' is already occupied.")

    if item:
        primary_slot = target_slots[0]
        _validate_belt_attachment(item, primary_slot, slots)
        _validate_backpack_slot(item, primary_slot)


def _validate_hand_containers_clear(inventory_blob: Dict[str, Any], target_slots) -> None:
    for slot in target_slots:
        if slot in HAND_CONTAINER_IDS and _hand_container_has_items(inventory_blob, slot):
            raise ValueError(f"Cannot equip item in {slot} while that hand is holding items.")


# ---------------------------------------------------------------------------
# Equipment-provided containers
# ---------------------------------------------------------------------------


def _container_profile_from_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Read a container profile from an equipped item, if it provides storage."""

    profile = item.get("container_profile") or item.get("container")
    if not isinstance(profile, dict):
        return None

    try:
        max_volume = float(profile.get("max_volume", 0))
    except (TypeError, ValueError):
        max_volume = 0

    if max_volume <= 0:
        return None

    return {
        "name": profile.get("name") or f"{item.get('name', 'Equipment')} Storage",
        "max_volume": max_volume,
        "max_item_size": profile.get("max_item_size") or "small",
    }


def _equipment_container_id(item: Dict[str, Any]) -> str:
    return f"equipment_{item.get('item_id')}"


def _attach_equipment_container(inventory_blob: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    """Attach an inventory container supplied by an equipped item."""

    profile = _container_profile_from_item(item)
    if not profile:
        return None

    container_id = _equipment_container_id(item)
    if _find_container(inventory_blob, container_id):
        return container_id

    stored_items = item.pop("stored_items", [])
    if not isinstance(stored_items, list):
        stored_items = []

    _get_containers(inventory_blob).append({
        "container_id": container_id,
        "name": profile["name"],
        "source": "equipment",
        "source_item_id": item.get("item_id"),
        "max_volume": profile["max_volume"],
        "max_item_size": profile["max_item_size"],
        "items": deepcopy(stored_items),
    })
    return container_id


# ---------------------------------------------------------------------------
# Equipped item lookup and serialization
# ---------------------------------------------------------------------------


def _find_equipped_item(slots: Dict[str, Any], slot: Optional[str], item_id: Optional[str]):
    """Find an equipped item by slot or by id/name."""

    normalized_slot = _normalize_slot(slot)
    normalized_item_id = (item_id or "").strip().lower()

    if normalized_slot:
        if normalized_slot not in EQUIPMENT_SLOTS:
            raise ValueError(f"Unknown equipment slot: {slot}")

        item = slots.get(normalized_slot)
        if _is_placeholder(item):
            normalized_slot = item.get("primary_slot")
            item = slots.get(normalized_slot)
        return normalized_slot, item

    if normalized_item_id:
        for current_slot, item in slots.items():
            if not item or _is_placeholder(item):
                continue

            existing_id = str(item.get("item_id", "")).lower().strip()
            existing_name = str(item.get("name", "")).lower().strip()
            if (
                existing_id == normalized_item_id
                or existing_name == normalized_item_id
                or normalized_item_id in existing_name
            ):
                return current_slot, item

    return None, None


def _clean_equipment_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    """Strip slot-only metadata before returning an equipped item to inventory."""

    cleaned = deepcopy(item)
    cleaned.pop("equipped_slots", None)
    cleaned.pop("equipped_slot", None)
    cleaned.pop("placeholder", None)
    cleaned.pop("occupied_by", None)
    cleaned.pop("primary_slot", None)
    cleaned.pop("stored_items", None)
    cleaned["quantity"] = 1
    return cleaned


def get_equipment(character_id: int) -> Dict[str, Any]:
    """Return raw equipment state for a character."""

    inventory_blob = load_inventory_blob(character_id)
    return _get_equipment_state(inventory_blob)


def serialize_equipment(character_id: int):
    """Return UI/prompt-friendly equipment slot data."""

    equipment = get_equipment(character_id)
    slots = equipment.get("slots", {})
    serialized_slots = []
    equipped_labels = []

    def build_item_tooltip(item: Dict[str, Any]) -> str:
        details = [item.get("name", "Unknown Item")]
        if item.get("description"):
            details.append(item["description"])
        details.append(f"Size: {str(item.get('size', 'small')).title()}")
        details.append(f"Volume: {float(item.get('volume', 0) or 0):.1f}")
        details.append(f"Weight: {float(item.get('weight', 0) or 0):.1f}")
        return " | ".join(details)

    for slot in EQUIPMENT_SLOTS:
        item = slots.get(slot)

        if _is_placeholder(item):
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": f"{item.get('name', 'Occupied')} (occupied)",
                "title": f"Occupied by {item.get('name', 'Occupied')}",
                "is_empty": False,
                "is_placeholder": True,
            })
            continue

        if item:
            label = item.get("name", "Unknown Item")
            equipped_labels.append(f"{SLOT_LABELS[slot]}: {label}")
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": label,
                "item_id": item.get("item_id"),
                "title": build_item_tooltip(item),
                "is_empty": False,
                "is_placeholder": False,
            })
        else:
            serialized_slots.append({
                "slot": slot,
                "label": SLOT_LABELS[slot],
                "item": None,
                "title": "",
                "is_empty": True,
                "is_placeholder": False,
            })

    return {
        "slots": serialized_slots,
        "labels": equipped_labels,
        "summary": ", ".join(equipped_labels) if equipped_labels else "None",
    }


# ---------------------------------------------------------------------------
# Public equipment operations
# ---------------------------------------------------------------------------


def equip_item(character_id: int, item_id: str, slot: Optional[str] = None) -> EquipmentOperationResult:
    """Equip one inventory item into a validated equipment slot."""

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment["slots"]

    source_container, source_item = _find_inventory_item(inventory_blob, item_id)
    if not source_item:
        return EquipmentOperationResult(False, f"Item '{item_id}' not found in inventory.", equipment, inventory_blob)

    try:
        primary_slot = _infer_slot(source_item, slot, slots)
        target_slots = _target_slots_for_item(source_item, primary_slot, slots)
        _validate_target_slots(slots, target_slots, source_item)
        _validate_hand_containers_clear(inventory_blob, target_slots)
    except ValueError as exc:
        return EquipmentOperationResult(False, str(exc), equipment, inventory_blob)

    equipped_item = _remove_one_from_container(source_container, source_item)
    equipped_item["equipped_slots"] = target_slots

    primary_slot = target_slots[0]
    slots[primary_slot] = equipped_item

    for secondary_slot in target_slots[1:]:
        slots[secondary_slot] = {
            "placeholder": True,
            "occupied_by": equipped_item.get("item_id"),
            "name": equipped_item.get("name"),
            "primary_slot": primary_slot,
        }

    for target_slot in target_slots:
        if target_slot in HAND_CONTAINER_IDS:
            _remove_empty_hand_container(inventory_blob, target_slot)

    equipment_container_id = _attach_equipment_container(inventory_blob, equipped_item)

    save_inventory_blob(character_id, inventory_blob)

    return EquipmentOperationResult(
        True,
        f"Equipped {equipped_item.get('name')} in {', '.join(target_slots)}.",
        equipment,
        inventory_blob,
        {
            "item_id": equipped_item.get("item_id"),
            "slots": target_slots,
            "equipment_container_id": equipment_container_id,
        },
    )


def unequip_item(
    character_id: int,
    slot: Optional[str] = None,
    item_id: Optional[str] = None,
    target_container_id: Optional[str] = None,
) -> EquipmentOperationResult:
    """Unequip one item and return it to an inventory container."""

    inventory_blob = load_inventory_blob(character_id)
    equipment = _get_equipment_state(inventory_blob)
    slots = equipment["slots"]

    try:
        primary_slot, item = _find_equipped_item(slots, slot, item_id)
    except ValueError as exc:
        return EquipmentOperationResult(False, str(exc), equipment, inventory_blob)

    if not primary_slot or not item:
        return EquipmentOperationResult(False, "Equipped item not found.", equipment, inventory_blob)

    if primary_slot == "belt":
        occupied_belt_slots = [
            belt_slot for belt_slot in BELT_ATTACHMENT_SLOTS
            if slots.get(belt_slot)
        ]
        if occupied_belt_slots:
            return EquipmentOperationResult(
                False,
                "Cannot unequip belt while belt attachment slots are occupied.",
                equipment,
                inventory_blob,
                {"occupied_slots": occupied_belt_slots},
            )

    container_id = _equipment_container_id(item)
    equipment_container = _find_container(inventory_blob, container_id)
    if equipment_container and equipment_container.get("items"):
        return EquipmentOperationResult(
            False,
            f"Cannot unequip {item.get('name')} while its container is not empty.",
            equipment,
            inventory_blob,
            {"equipment_container_id": container_id},
        )

    inventory_item = _clean_equipment_metadata(item)
    target_container = (
        _find_container(inventory_blob, target_container_id)
        if target_container_id
        else _find_first_carried_container_with_space(inventory_blob, inventory_item)
    )
    if not target_container:
        return EquipmentOperationResult(False, "No carried container can hold the unequipped item.", equipment, inventory_blob)

    if not _can_add_item(target_container, inventory_item):
        return EquipmentOperationResult(
            False,
            f"Not enough space in container '{target_container.get('name')}'.",
            equipment,
            inventory_blob,
        )

    if equipment_container:
        _get_containers(inventory_blob).remove(equipment_container)

    for equipped_slot in item.get("equipped_slots", [primary_slot]):
        slots[equipped_slot] = None

    _add_item_to_container(target_container, inventory_item)
    save_inventory_blob(character_id, inventory_blob)

    return EquipmentOperationResult(
        True,
        f"Unequipped {inventory_item.get('name')}.",
        equipment,
        inventory_blob,
        {
            "item_id": inventory_item.get("item_id"),
            "target_container_id": target_container.get("container_id"),
        },
    )
