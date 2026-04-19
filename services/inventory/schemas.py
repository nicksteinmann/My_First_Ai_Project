from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class InventoryItem:
    item_id: str
    name: str
    description: str
    size: str
    volume: float
    weight: float
    stackable: bool
    quantity: int
    hand_usage: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InventoryContainer:
    container_id: str
    name: str
    source: str
    source_item_id: Optional[str]
    max_volume: float
    max_item_size: str
    items: List[InventoryItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["items"] = [item.to_dict() for item in self.items]
        return data


@dataclass
class InventoryState:
    containers: List[InventoryContainer] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inventory": {
                "containers": [container.to_dict() for container in self.containers]
            }
        }


@dataclass
class InventoryOperationResult:
    success: bool
    message: str
    inventory: Dict[str, Any]
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "inventory": self.inventory,
            "details": self.details,
        }


def container_from_dict(data: Dict[str, Any]) -> InventoryContainer:
    items = [InventoryItem(**item) for item in data.get("items", [])]
    return InventoryContainer(
        container_id=data["container_id"],
        name=data["name"],
        source=data["source"],
        source_item_id=data.get("source_item_id"),
        max_volume=float(data["max_volume"]),
        max_item_size=data["max_item_size"],
        items=items,
    )


def inventory_from_dict(data: Dict[str, Any]) -> InventoryState:
    inventory_data = data.get("inventory", {})
    containers = [
        container_from_dict(container)
        for container in inventory_data.get("containers", [])
    ]
    return InventoryState(containers=containers)