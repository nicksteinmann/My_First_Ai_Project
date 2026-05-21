import unittest

from services.world_data import flatten_world_locations, load_world_data


class WorldDataTestCase(unittest.TestCase):
    def test_world_data_contains_fixed_regions_and_locations(self):
        world = load_world_data()
        locations = flatten_world_locations(world)

        self.assertEqual(world["name"], "Avalion")
        self.assertEqual(len(world["regions"]), 5)
        self.assertGreaterEqual(len(locations), 40)

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


if __name__ == "__main__":
    unittest.main()
