"""Static world data loading for the Avalion map and world overview."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


WORLD_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "world.json"


@lru_cache(maxsize=1)
def load_world_data() -> dict:
    """Return the structured world definition used by the World page and seeds."""

    with WORLD_DATA_PATH.open("r", encoding="utf-8") as world_file:
        return json.load(world_file)


def flatten_world_locations(world_data: dict | None = None) -> list[dict]:
    """Return every fixed world location with inherited region metadata."""

    data = world_data or load_world_data()
    locations = []

    for region in data.get("regions", []):
        for location in region.get("locations", []):
            location_data = dict(location)
            location_data["region_id"] = region.get("id")
            location_data["region_name"] = region.get("name")
            location_data["dominant_people"] = region.get("dominant_people")
            locations.append(location_data)

    return locations


def ensure_world_template_locations(db_session, world_template, template_location_model) -> None:
    """Create template region/location rows for fixed world-map anchors."""

    data = load_world_data()

    if template_location_model.query.filter_by(world_template_id=world_template.id).first():
        return

    region_rows = {}

    for region in data.get("regions", []):
        region_row = template_location_model(
            world_template_id=world_template.id,
            name=region["name"],
            location_type="region",
            description=region.get("description"),
            lore_text=(
                f"Dominant people: {region.get('dominant_people')}. "
                f"Terrain: {region.get('terrain')}."
            ),
            is_discoverable=True,
        )
        db_session.add(region_row)
        db_session.flush()
        region_rows[region["id"]] = region_row

        for location in region.get("locations", []):
            location_row = template_location_model(
                world_template_id=world_template.id,
                parent_location_id=region_row.id,
                name=location["name"],
                location_type=location.get("kind", "location"),
                description=location.get("description"),
                lore_text=(
                    f"Region: {region['name']}. "
                    f"Subregion: {location.get('subregion')}. "
                    f"Coordinates: {location.get('x')},{location.get('y')}. "
                    f"Dominant people: {region.get('dominant_people')}."
                ),
                is_discoverable=True,
            )
            db_session.add(location_row)
