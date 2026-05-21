"""Static world data loading for the Avalion map and world overview."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path


WORLD_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "world.json"
COORDINATE_PRECISION = 3
DEFAULT_TRAVEL_SPEED_KMH = 5.0

TRAVEL_MODE_SPEED_KMH = {
    "walk": 5.0,
    "on_foot": 5.0,
    "cart": 6.0,
    "wagon": 6.0,
    "carriage": 8.0,
    "ride": 10.0,
    "horse": 10.0,
    "mount": 10.0,
    "ship": 12.0,
    "sea": 12.0,
    "boat": 8.0,
    "airship": 20.0,
    "flight": 24.0,
    "teleportation": 9999.0,
    "teleport": 9999.0,
}

ROUTE_MODE_TIME_MULTIPLIERS = {
    "road": 0.9,
    "border_road": 1.0,
    "waste_road": 1.15,
    "mountain_road": 1.25,
    "deep_road": 1.2,
    "forest_path": 1.25,
    "canyon_path": 1.35,
    "sea": 0.85,
    "boat": 1.0,
}

TERRAIN_TIME_MULTIPLIERS = {
    "road": 0.9,
    "plains": 1.0,
    "fields": 1.0,
    "forest": 1.25,
    "swamp": 1.4,
    "marsh": 1.45,
    "mountain": 1.5,
    "hills": 1.2,
    "waste": 1.3,
    "desert": 1.35,
    "canyon": 1.4,
    "coast": 1.1,
    "sea": 0.85,
    "urban": 0.8,
    "city": 0.8,
    "wilderness": 1.2,
}


def normalize_coordinate(value) -> float:
    """Return a map coordinate rounded to the shared Avalion coordinate precision."""

    return round(float(value), COORDINATE_PRECISION)


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


def flatten_world_subregions(world_data: dict | None = None) -> list[dict]:
    """Return every fixed subregion with inherited region metadata."""

    data = world_data or load_world_data()
    subregions = []

    for region in data.get("regions", []):
        for subregion in region.get("subregions", []):
            subregion_data = dict(subregion)
            subregion_data["region_id"] = region.get("id")
            subregion_data["region_name"] = region.get("name")
            subregions.append(subregion_data)

    return subregions


def normalize_world_lookup(value) -> str:
    """Normalize names and ids for loose world-location matching."""

    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def get_coordinate_system(world_data: dict | None = None) -> dict:
    """Return the configured world coordinate system."""

    data = world_data or load_world_data()
    return data.get("coordinate_system", {})


def find_world_location(value, world_data: dict | None = None) -> dict | None:
    """Find a fixed world location by id or display name."""

    lookup_key = normalize_world_lookup(value)
    if not lookup_key:
        return None

    for location in flatten_world_locations(world_data):
        if lookup_key in {
            normalize_world_lookup(location.get("id")),
            normalize_world_lookup(location.get("name")),
        }:
            return dict(location)

    return None


def find_travel_edge(from_location_id, to_location_id, world_data: dict | None = None) -> dict | None:
    """Find a direct fixed travel edge between two world locations."""

    from_key = normalize_world_lookup(from_location_id)
    to_key = normalize_world_lookup(to_location_id)
    if not from_key or not to_key:
        return None

    data = world_data or load_world_data()
    for edge in data.get("travel_edges", []):
        edge_from = normalize_world_lookup(edge.get("from"))
        edge_to = normalize_world_lookup(edge.get("to"))

        if {from_key, to_key} == {edge_from, edge_to}:
            return dict(edge)

    return None


def _iter_bounds(bounds) -> list[dict]:
    """Return one or many rectangular bounds entries."""

    if not bounds:
        return []

    if isinstance(bounds, dict):
        return [bounds]

    if isinstance(bounds, list):
        return [entry for entry in bounds if isinstance(entry, dict)]

    return []


def _bounds_area(bounds: dict) -> float:
    """Return rectangle area for tie-breaking overlapping bounds."""

    width = abs(float(bounds.get("x_max", 0) or 0) - float(bounds.get("x_min", 0) or 0))
    height = abs(float(bounds.get("y_max", 0) or 0) - float(bounds.get("y_min", 0) or 0))
    return width * height


def _point_in_bounds(x: float, y: float, bounds) -> bool:
    """Return whether a coordinate is inside one of the provided rectangles."""

    for entry in _iter_bounds(bounds):
        x_min = float(entry.get("x_min", 0) or 0)
        x_max = float(entry.get("x_max", 0) or 0)
        y_min = float(entry.get("y_min", 0) or 0)
        y_max = float(entry.get("y_max", 0) or 0)

        if min(x_min, x_max) <= x <= max(x_min, x_max) and min(y_min, y_max) <= y <= max(y_min, y_max):
            return True

    return False


def _smallest_bounds_area(bounds) -> float:
    """Return the smallest rectangle area for a bounds definition."""

    areas = [_bounds_area(entry) for entry in _iter_bounds(bounds)]
    return min(areas) if areas else float("inf")


def _nearest_location_for_region(region: dict, x: float, y: float) -> dict | None:
    """Return the nearest fixed location inside one region."""

    locations = region.get("locations", [])
    if not locations:
        return None

    return min(
        locations,
        key=lambda location: math.hypot(
            float(location["x"]) - x,
            float(location["y"]) - y,
        ),
    )


def _nearest_world_location(x: float, y: float, world_data: dict | None = None) -> dict:
    """Return the nearest fixed world location for arbitrary coordinates."""

    fixed_locations = flatten_world_locations(world_data)
    return min(
        fixed_locations,
        key=lambda location: math.hypot(
            float(location["x"]) - x,
            float(location["y"]) - y,
        ),
    )


def _resolve_region_from_bounds(x: float, y: float, world_data: dict) -> dict | None:
    """Resolve the containing region from rectangular MVP bounds."""

    regions = world_data.get("regions", [])
    matching_regions = [
        region
        for region in regions
        if _point_in_bounds(x, y, region.get("bounds"))
    ]

    if not matching_regions:
        return None

    if len(matching_regions) == 1:
        return matching_regions[0]

    return min(
        matching_regions,
        key=lambda region: math.hypot(
            float((_nearest_location_for_region(region, x, y) or {"x": x})["x"]) - x,
            float((_nearest_location_for_region(region, x, y) or {"y": y})["y"]) - y,
        ),
    )


def _resolve_subregion_from_bounds(region: dict, x: float, y: float) -> dict | None:
    """Resolve the containing subregion from rectangular MVP bounds."""

    matching_subregions = [
        subregion
        for subregion in region.get("subregions", [])
        if _point_in_bounds(x, y, subregion.get("bounds"))
    ]

    if not matching_subregions:
        return None

    return min(
        matching_subregions,
        key=lambda subregion: _smallest_bounds_area(subregion.get("bounds")),
    )


def _location_radius_units(location: dict) -> float:
    """Return a rough coordinate-radius for recognizing fixed settlements."""

    kind = normalize_world_lookup(location.get("kind"))
    radii = {
        "capitalcity": 2.5,
        "capitalfortress": 2.5,
        "capitalport": 2.2,
        "city": 1.8,
        "portcity": 1.8,
        "fortresstown": 1.4,
        "town": 1.2,
        "porttown": 1.2,
        "village": 0.8,
        "marshvillage": 0.8,
    }
    return radii.get(kind, 1.0)


def _world_location_at_coordinate(x: float, y: float, world_data: dict | None = None) -> dict | None:
    """Return a fixed map location when coordinates are within its rough radius."""

    nearest_location = _nearest_world_location(x, y, world_data)
    distance_units = math.hypot(float(nearest_location["x"]) - x, float(nearest_location["y"]) - y)

    if distance_units <= _location_radius_units(nearest_location):
        return nearest_location

    return None


def distance_km_between_coordinates(
    x1,
    y1,
    x2,
    y2,
    world_data: dict | None = None,
) -> float:
    """Return straight-line distance in kilometers between two map coordinates."""

    coordinate_system = get_coordinate_system(world_data)
    scale_km_per_unit = float(coordinate_system.get("scale_km_per_unit", 10) or 10)
    distance_units = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
    return round(distance_units * scale_km_per_unit, 2)


def estimate_travel_minutes(
    distance_km,
    travel_mode: str = "walk",
    route_mode: str | None = None,
    terrain: str | None = None,
):
    """Estimate travel duration in minutes from distance, travel mode, route, and terrain."""

    normalized_travel_mode = normalize_world_lookup(travel_mode) or "walk"
    normalized_route_mode = normalize_world_lookup(route_mode)
    normalized_terrain = normalize_world_lookup(terrain)

    speed_kmh = TRAVEL_MODE_SPEED_KMH.get(normalized_travel_mode, DEFAULT_TRAVEL_SPEED_KMH)
    if speed_kmh <= 0:
        speed_kmh = DEFAULT_TRAVEL_SPEED_KMH

    route_multiplier = ROUTE_MODE_TIME_MULTIPLIERS.get(normalized_route_mode, 1.0)
    terrain_multiplier = TERRAIN_TIME_MULTIPLIERS.get(normalized_terrain, 1.0)

    if normalized_travel_mode in {"teleportation", "teleport"}:
        estimated_minutes = 1
    else:
        estimated_hours = (float(distance_km) / speed_kmh) * route_multiplier * terrain_multiplier
        estimated_minutes = max(1, int(round(estimated_hours * 60)))

    return {
        "distance_km": round(float(distance_km), 2),
        "estimated_minutes": estimated_minutes,
        "speed_kmh": speed_kmh,
        "travel_mode": normalized_travel_mode,
        "route_mode": normalized_route_mode or None,
        "terrain": normalized_terrain or None,
        "route_multiplier": route_multiplier,
        "terrain_multiplier": terrain_multiplier,
    }


def estimate_travel_between_coordinates(
    x1,
    y1,
    x2,
    y2,
    travel_mode: str = "walk",
    route_mode: str | None = None,
    terrain: str | None = None,
    world_data: dict | None = None,
) -> dict:
    """Estimate travel duration between two arbitrary map coordinates."""

    distance_km = distance_km_between_coordinates(x1, y1, x2, y2, world_data)
    return estimate_travel_minutes(
        distance_km=distance_km,
        travel_mode=travel_mode,
        route_mode=route_mode,
        terrain=terrain,
    )


def estimate_travel_between_world_locations(
    from_location_id,
    to_location_id,
    travel_mode: str = "walk",
    terrain: str | None = None,
    world_data: dict | None = None,
) -> dict | None:
    """Estimate travel duration between fixed world locations, preferring stored route edges."""

    data = world_data or load_world_data()
    from_location = find_world_location(from_location_id, data)
    to_location = find_world_location(to_location_id, data)

    if not from_location or not to_location:
        return None

    route_edge = find_travel_edge(from_location["id"], to_location["id"], data)
    if route_edge:
        distance_km = float(route_edge["distance_km"])
        route_mode = route_edge.get("mode")
        distance_source = "travel_edge"
    else:
        distance_km = distance_km_between_coordinates(
            from_location["x"],
            from_location["y"],
            to_location["x"],
            to_location["y"],
            data,
        )
        route_mode = None
        distance_source = "straight_line"

    estimate = estimate_travel_minutes(
        distance_km=distance_km,
        travel_mode=travel_mode,
        route_mode=route_mode,
        terrain=terrain,
    )
    estimate["distance_source"] = distance_source
    estimate["from_world_location_id"] = from_location["id"]
    estimate["to_world_location_id"] = to_location["id"]
    return estimate


def is_coordinate_inside_world(x, y, world_data: dict | None = None) -> bool:
    """Return whether a coordinate is inside the configured world bounds."""

    coordinate_system = get_coordinate_system(world_data)
    width = float(coordinate_system.get("width", 0) or 0)
    height = float(coordinate_system.get("height", 0) or 0)
    coordinate_x = normalize_coordinate(x)
    coordinate_y = normalize_coordinate(y)

    return 0 <= coordinate_x <= width and 0 <= coordinate_y <= height


def build_location_context_from_world_location(location: dict, source: str = "world_location") -> dict:
    """Return database-ready coordinate context for a fixed world location."""

    return {
        "coordinate_x": normalize_coordinate(location["x"]),
        "coordinate_y": normalize_coordinate(location["y"]),
        "coordinate_source": source,
        "region_id": location.get("region_id"),
        "region_name": location.get("region_name"),
        "subregion": location.get("subregion"),
        "world_location_id": location.get("id"),
        "world_location_name": location.get("name"),
    }


def resolve_coordinate_context(x, y, world_data: dict | None = None) -> dict:
    """
    Infer region context for arbitrary coordinates from the nearest fixed anchor.

    This is an MVP approximation until real region polygons/bounds exist.
    """

    data = world_data or load_world_data()
    if not is_coordinate_inside_world(x, y, data):
        raise ValueError("Coordinates are outside the Avalion map bounds.")

    coordinate_x = normalize_coordinate(x)
    coordinate_y = normalize_coordinate(y)
    nearest_location = _nearest_world_location(coordinate_x, coordinate_y, data)
    matched_region = _resolve_region_from_bounds(coordinate_x, coordinate_y, data)
    matched_world_location = _world_location_at_coordinate(coordinate_x, coordinate_y, data)

    if matched_region is None:
        matched_region = {
            "id": nearest_location.get("region_id"),
            "name": nearest_location.get("region_name"),
            "subregions": [],
        }

    matched_subregion = _resolve_subregion_from_bounds(matched_region, coordinate_x, coordinate_y)
    subregion_name = (
        matched_subregion.get("name")
        if matched_subregion
        else nearest_location.get("subregion")
    )

    context = {
        "coordinate_x": coordinate_x,
        "coordinate_y": coordinate_y,
        "coordinate_source": "inferred_coordinates",
        "region_id": matched_region.get("id"),
        "region_name": matched_region.get("name"),
        "subregion": subregion_name,
        "world_location_id": matched_world_location.get("id") if matched_world_location else None,
        "world_location_name": matched_world_location.get("name") if matched_world_location else None,
    }
    context["nearest_world_location_id"] = nearest_location.get("id")
    context["nearest_world_location_name"] = nearest_location.get("name")
    context["nearest_distance_km"] = distance_km_between_coordinates(
        coordinate_x,
        coordinate_y,
        nearest_location["x"],
        nearest_location["y"],
        data,
    )
    return context


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
