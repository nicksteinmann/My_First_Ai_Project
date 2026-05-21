import unittest

from services.world_data import (
    distance_km_between_coordinates,
    estimate_travel_between_coordinates,
    estimate_travel_between_world_locations,
    find_world_location,
    flatten_world_subregions,
    flatten_world_locations,
    load_world_data,
    normalize_coordinate,
    resolve_coordinate_context,
)


def _bounds_entries(bounds):
    if isinstance(bounds, list):
        return bounds
    return [bounds]


def _point_in_bounds(x, y, bounds):
    for entry in _bounds_entries(bounds):
        x_min = min(entry["x_min"], entry["x_max"])
        x_max = max(entry["x_min"], entry["x_max"])
        y_min = min(entry["y_min"], entry["y_max"])
        y_max = max(entry["y_min"], entry["y_max"])

        if x_min <= x <= x_max and y_min <= y <= y_max:
            return True

    return False


def _bounds_extents(bounds):
    return (
        min(bounds["x_min"], bounds["x_max"]),
        max(bounds["x_min"], bounds["x_max"]),
        min(bounds["y_min"], bounds["y_max"]),
        max(bounds["y_min"], bounds["y_max"]),
    )


def _coverage_cells(region_bounds, subregion_bounds):
    cells = []

    for region_entry in _bounds_entries(region_bounds):
        region_x_min, region_x_max, region_y_min, region_y_max = _bounds_extents(region_entry)
        x_edges = {region_x_min, region_x_max}
        y_edges = {region_y_min, region_y_max}

        for subregion_bound in subregion_bounds:
            for subregion_entry in _bounds_entries(subregion_bound):
                subregion_x_min, subregion_x_max, subregion_y_min, subregion_y_max = _bounds_extents(
                    subregion_entry
                )
                overlap_x_min = max(region_x_min, subregion_x_min)
                overlap_x_max = min(region_x_max, subregion_x_max)
                overlap_y_min = max(region_y_min, subregion_y_min)
                overlap_y_max = min(region_y_max, subregion_y_max)

                if overlap_x_min < overlap_x_max and overlap_y_min < overlap_y_max:
                    x_edges.update([overlap_x_min, overlap_x_max])
                    y_edges.update([overlap_y_min, overlap_y_max])

        sorted_x_edges = sorted(x_edges)
        sorted_y_edges = sorted(y_edges)

        for x_index in range(len(sorted_x_edges) - 1):
            for y_index in range(len(sorted_y_edges) - 1):
                x_min = sorted_x_edges[x_index]
                x_max = sorted_x_edges[x_index + 1]
                y_min = sorted_y_edges[y_index]
                y_max = sorted_y_edges[y_index + 1]

                if x_min < x_max and y_min < y_max:
                    cells.append(((x_min + x_max) / 2, (y_min + y_max) / 2))

    return cells


class WorldDataTestCase(unittest.TestCase):
    def test_world_data_contains_fixed_regions_and_locations(self):
        world = load_world_data()
        locations = flatten_world_locations(world)

        self.assertEqual(world["name"], "Avalion")
        self.assertEqual(len(world["regions"]), 5)
        self.assertGreaterEqual(len(locations), 40)
        self.assertGreaterEqual(len(flatten_world_subregions(world)), 25)

        location_ids = {location["id"] for location in locations}
        self.assertIn("willowbrook", location_ids)
        self.assertIn("stonewatch", location_ids)
        self.assertIn("kragmor", location_ids)
        self.assertIn("jagged_harbor", location_ids)

    def test_world_data_has_coordinates_and_island_travel_rules(self):
        world = load_world_data()
        locations = flatten_world_locations(world)

        for location in locations:
            self.assertIsInstance(location["x"], (int, float))
            self.assertIsInstance(location["y"], (int, float))
            self.assertGreaterEqual(location["x"], 0)
            self.assertLessEqual(location["x"], world["coordinate_system"]["width"])
            self.assertGreaterEqual(location["y"], 0)
            self.assertLessEqual(location["y"], world["coordinate_system"]["height"])

        sea_routes = [
            route for route in world["travel_edges"]
            if route["mode"] in {"sea", "boat"}
        ]
        self.assertTrue(sea_routes)

        shard_isles = next(region for region in world["regions"] if region["id"] == "shard_isles")
        self.assertIn("ship", shard_isles["travel_requirement"])

    def test_world_location_lookup_and_coordinate_context(self):
        willowbrook = find_world_location("Willowbrook")

        self.assertIsNotNone(willowbrook)
        self.assertEqual("willowbrook", willowbrook["id"])
        self.assertEqual("crownfields", willowbrook["region_id"])

        context = resolve_coordinate_context(willowbrook["x"], willowbrook["y"])
        self.assertEqual("crownfields", context["region_id"])
        self.assertEqual("Willow Vale", context["subregion"])
        self.assertEqual("willowbrook", context["world_location_id"])
        self.assertEqual("Willowbrook", context["nearest_world_location_name"])
        self.assertEqual(0.0, context["nearest_distance_km"])

        distance = distance_km_between_coordinates(0, 0, 3, 4)
        self.assertEqual(50.0, distance)

    def test_travel_time_estimates_use_speed_and_route_multipliers(self):
        straight_walk = estimate_travel_between_coordinates(0, 0, 3, 4, travel_mode="walk")
        self.assertEqual(50.0, straight_walk["distance_km"])
        self.assertEqual(600, straight_walk["estimated_minutes"])
        self.assertEqual(5.0, straight_walk["speed_kmh"])

        road_ride = estimate_travel_between_coordinates(
            0,
            0,
            3,
            4,
            travel_mode="ride",
            route_mode="road",
        )
        self.assertEqual(270, road_ride["estimated_minutes"])

        willowbrook_to_crownford = estimate_travel_between_world_locations(
            "willowbrook",
            "crownford",
            travel_mode="walk",
        )
        self.assertEqual("travel_edge", willowbrook_to_crownford["distance_source"])
        self.assertEqual(156.0, willowbrook_to_crownford["distance_km"])
        self.assertEqual("road", willowbrook_to_crownford["route_mode"])

    def test_coordinate_bounds_resolve_region_and_subregion(self):
        monastery_context = resolve_coordinate_context(59.8, 75.0)

        self.assertEqual("crownfields", monastery_context["region_id"])
        self.assertEqual("Southern Hills", monastery_context["subregion"])

    def test_coordinates_are_normalized_to_three_decimal_places(self):
        self.assertEqual(12.346, normalize_coordinate(12.34567))

        context = resolve_coordinate_context(48.40049, 48.10049)
        self.assertEqual(48.4, context["coordinate_x"])
        self.assertEqual(48.1, context["coordinate_y"])

    def test_region_bounds_are_fully_covered_by_named_subregions(self):
        world = load_world_data()

        for region in world["regions"]:
            subregion_bounds = [subregion["bounds"] for subregion in region["subregions"]]

            for coordinate_x, coordinate_y in _coverage_cells(region["bounds"], subregion_bounds):
                is_covered_by_subregion = any(
                    _point_in_bounds(coordinate_x, coordinate_y, subregion["bounds"])
                    for subregion in region["subregions"]
                )

                self.assertTrue(
                    is_covered_by_subregion,
                    f"{region['name']} has no subregion at {coordinate_x}, {coordinate_y}",
                )

    def test_fixed_locations_resolve_to_their_stored_subregions(self):
        world = load_world_data()
        locations = flatten_world_locations(world)

        removed_fallback_ids = {
            "outer_crownlands",
            "deep_silverwood",
            "stoneward_highlands",
            "open_grimscar",
            "shard_waters",
        }
        subregion_ids = {
            subregion["id"]
            for region in world["regions"]
            for subregion in region["subregions"]
        }
        self.assertFalse(removed_fallback_ids & subregion_ids)

        for location in locations:
            context = resolve_coordinate_context(location["x"], location["y"], world)
            self.assertEqual(location["region_id"], context["region_id"])
            self.assertEqual(location["subregion"], context["subregion"])

    def test_coordinate_movement_across_region_boundary_changes_region(self):
        crownfields_context = resolve_coordinate_context(76.0, 61.0)
        grimscar_context = resolve_coordinate_context(86.7, 55.2)

        self.assertEqual("crownfields", crownfields_context["region_id"])
        self.assertEqual("Duskmire Fringe", crownfields_context["subregion"])

        self.assertEqual("grimscar_wastes", grimscar_context["region_id"])
        self.assertEqual("Redrock Border", grimscar_context["subregion"])


if __name__ == "__main__":
    unittest.main()
