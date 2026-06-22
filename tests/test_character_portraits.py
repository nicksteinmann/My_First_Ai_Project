import unittest

from data.character_portraits import (
    build_character_portrait_key,
    build_character_portrait_prompt,
    normalize_character_gender,
)


class CharacterPortraitMetadataTestCase(unittest.TestCase):
    def test_normalize_character_gender_defaults_to_male(self):
        self.assertEqual("male", normalize_character_gender(None))
        self.assertEqual("male", normalize_character_gender("unknown"))
        self.assertEqual("female", normalize_character_gender("female"))

    def test_build_character_portrait_key_uses_race_class_and_gender(self):
        self.assertEqual(
            "elf_mage_female",
            build_character_portrait_key("Elf", "Mage", "female"),
        )

    def test_build_character_portrait_prompt_contains_core_identity_traits(self):
        prompt = build_character_portrait_prompt("Orc", "Ranger", "male")
        self.assertIn("red-skinned orc", prompt)
        self.assertIn("bow visible", prompt)
        self.assertIn("masculine facial structure", prompt)


if __name__ == "__main__":
    unittest.main()
