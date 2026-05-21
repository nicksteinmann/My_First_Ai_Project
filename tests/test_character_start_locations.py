import unittest

from data.character_presets import RACES
from routes.character_routes import RACE_START_LOCATIONS
from services.world_data import find_world_location


class CharacterStartLocationTestCase(unittest.TestCase):
    def test_every_race_has_a_fixed_world_start_location(self):
        expected_regions = {
            "Human": "crownfields",
            "Elf": "silverwood",
            "Dwarf": "stoneward_peaks",
            "Orc": "grimscar_wastes",
            "Goblin": "shard_isles",
        }

        self.assertEqual(set(RACES), set(RACE_START_LOCATIONS))

        for race, expected_region_id in expected_regions.items():
            start_config = RACE_START_LOCATIONS[race]
            world_location = find_world_location(start_config["world_location_id"])

            self.assertIsNotNone(world_location)
            self.assertEqual(expected_region_id, world_location["region_id"])
            self.assertIn(world_location["name"], start_config["location_name"])


if __name__ == "__main__":
    unittest.main()
