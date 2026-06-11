import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

from services.lore.service import (
    FILTERABLE_LORE_FIELDS,
    LoreDocument,
    _ensure_payload_indexes,
    chunk_lore_document,
    load_lore_documents,
    parse_frontmatter,
    query_lore,
)
from services.lore.tools import _build_capital_matches, execute_lore_tool
from services.prompt_builder.game_prompt_builder import build_game_system_prompt


class LoreServiceTestCase(unittest.TestCase):
    def test_parse_frontmatter_returns_metadata_and_body(self):
        text = """---
doc_id: location_willowbrook
scope_type: location
region_id: crownfields
---

# Willowbrook

## Overview
Busy roads and markets.
"""
        metadata, body = parse_frontmatter(text)
        self.assertEqual("location_willowbrook", metadata["doc_id"])
        self.assertEqual("location", metadata["scope_type"])
        self.assertIn("Willowbrook", body)

    def test_chunk_lore_document_prefers_heading_sections(self):
        document = LoreDocument(
            path=Path("lore/locations/willowbrook.md"),
            metadata={"doc_id": "location_willowbrook", "title": "Willowbrook", "scope_type": "location"},
            body="# Willowbrook\n\n## Overview\nA market city.\n\n## Economy\nTrade, carts, and mills.\n",
        )
        chunks = chunk_lore_document(document, max_section_chars=1200)
        self.assertEqual(2, len(chunks))
        self.assertEqual("Overview", chunks[0]["title"])
        self.assertEqual("Economy", chunks[1]["title"])

    def test_load_lore_documents_reads_markdown_tree(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            file_path = temp_dir / "regions" / "crownfields.md"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                """---
doc_id: region_crownfields
scope_type: region
title: Crownfields
---

## Overview
The human heartland.
""",
                encoding="utf-8",
            )
            documents = load_lore_documents(root=temp_dir)
            self.assertEqual(1, len(documents))
            self.assertEqual("region_crownfields", documents[0].metadata["doc_id"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("services.lore.tools.query_lore")
    def test_execute_lore_tool_returns_summarized_matches(self, mock_query_lore):
        mock_query_lore.return_value = {
            "success": True,
            "matches": [
                {
                    "score": 0.91,
                    "payload": {
                        "doc_id": "location_willowbrook",
                        "scope_type": "location",
                        "title": "Willowbrook",
                        "title_path": "Willowbrook > Overview",
                        "region_id": "crownfields",
                        "subregion_id": "willow_vale",
                        "location_id": "willowbrook",
                        "knowledge_level": "public",
                        "text": "A busy starter city.",
                        "source_path": "locations/willowbrook.md",
                    },
                }
            ],
        }

        result = execute_lore_tool(
            campaign_id=999,
            tool_name="get_lore_context",
            arguments={"query_text": "What is known about Willowbrook?", "location_id": "willowbrook"},
        )

        self.assertTrue(result["success"], result)
        self.assertEqual("get_lore_context", result["tool"])
        self.assertEqual("location_willowbrook", result["matches"][0]["doc_id"])
        self.assertEqual("Willowbrook", result["matches"][0]["title"])

    def test_build_capital_matches_uses_known_capital_locations(self):
        matches = _build_capital_matches(
            "Was weiß ich über die Hauptstädte der spielbaren Rassen?",
            limit=8,
        )
        doc_ids = [match["payload"]["doc_id"] for match in matches]

        self.assertIn("location_crownford", doc_ids)
        self.assertIn("location_lythariel", doc_ids)
        self.assertIn("location_stonewatch", doc_ids)
        self.assertIn("location_kragmor", doc_ids)
        self.assertIn("location_jagged_harbor", doc_ids)

    def test_build_capital_matches_can_focus_on_one_requested_race(self):
        matches = _build_capital_matches(
            "Welche Hauptstadt haben die Orks?",
            limit=8,
        )
        doc_ids = [match["payload"]["doc_id"] for match in matches]

        self.assertEqual(["location_kragmor"], doc_ids)

    @patch("services.lore.tools.query_lore")
    def test_execute_lore_tool_capital_query_supplements_generic_region_matches(self, mock_query_lore):
        mock_query_lore.return_value = {
            "success": True,
            "matches": [
                {
                    "score": 0.44,
                    "payload": {
                        "doc_id": "region_crownfields",
                        "scope_type": "region",
                        "title": "Geography",
                        "title_path": "Crownfields > Geography",
                        "region_id": "crownfields",
                        "subregion_id": None,
                        "location_id": None,
                        "knowledge_level": "public",
                        "text": "Dominant people: Humans.",
                        "source_path": "regions/crownfields.md",
                    },
                }
            ],
        }

        result = execute_lore_tool(
            campaign_id=999,
            tool_name="get_lore_context",
            arguments={
                "query_text": "Was weiß ich über die Hauptstädte der spielbaren Rassen?",
                "limit": 5,
            },
        )

        self.assertTrue(result["success"], result)
        doc_ids = [match["doc_id"] for match in result["matches"]]
        self.assertIn("location_crownford", doc_ids)
        self.assertIn("location_kragmor", doc_ids)
        self.assertIn("location_jagged_harbor", doc_ids)
        self.assertIn("location_lythariel", doc_ids)
        self.assertIn("location_stonewatch", doc_ids)

    def test_build_game_system_prompt_lists_official_playable_races(self):
        active_character = {
            "id": 1,
            "name": "Prompt Test",
            "class_name": "Knight",
            "race": "Human",
            "level": 5,
            "status": "alive",
            "inventory_summary": "Torch",
            "equipment_summary": "Sword",
            "attribute_summary": "Strength 8",
            "skill_summary": "Swordsmanship 3",
            "status_effect_summary": "None",
            "level_progression": {"xp_into_level": 10, "xp_needed_this_level": 50},
            "renown_label": "Unknown",
            "renown_summary": "Nobody knows you yet.",
            "currency": {"gold": 0, "silver": 0, "copper": 0},
            "stats": {
                "hp": 20,
                "hp_max": 20,
                "mana": 5,
                "mana_max": 5,
                "energy": 10,
                "energy_max": 10,
            },
            "current_state": {
                "location": "Crownford",
                "current_location_id": 1,
                "day_label": "Day 1",
                "time_of_day": "Morning",
                "location_context": {
                    "region_name": "Crownfields",
                    "subregion": "Royal Heartland",
                    "coordinate_x": 10,
                    "coordinate_y": 10,
                    "scale_km_per_unit": 10,
                },
                "visible_quests": [],
                "nearby_merchants": [],
                "nearby_trainers": [],
            },
        }

        prompt = build_game_system_prompt(
            active_character,
            latest_user_input="Was weiß ich über die Hauptstädte der Rassen?",
        )

        self.assertIn("Official Playable Races In This Campaign Ruleset: Human, Orc, Goblin, Elf, Dwarf", prompt)
        self.assertIn("Do not mention races, peoples, capitals, kingdoms, cities, or factions that are not established", prompt)

    def test_ensure_payload_indexes_creates_keyword_indexes_for_filter_fields(self):
        qdrant = Mock()

        _ensure_payload_indexes(qdrant, "avalion_lore")

        self.assertEqual(len(FILTERABLE_LORE_FIELDS), qdrant.create_payload_index.call_count)
        created_fields = [call.kwargs["field_name"] for call in qdrant.create_payload_index.call_args_list]
        self.assertEqual(list(FILTERABLE_LORE_FIELDS), created_fields)

    @patch("services.lore.service._embed_texts", return_value=[[0.1, 0.2, 0.3]])
    @patch("services.lore.service._build_qdrant_client")
    def test_query_lore_retries_without_filter_when_payload_index_is_missing(self, mock_build_qdrant_client, mock_embed_texts):
        class FakeQdrant:
            def __init__(self):
                self.calls = 0

            def query_points(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError(
                        'Bad request: Index required but not found for "scope_type" of one of the following types: [keyword].'
                    )
                return SimpleNamespace(points=[
                    SimpleNamespace(
                        score=0.88,
                        payload={"doc_id": "location_crownford", "title": "Overview"},
                    )
                ])

        fake_qdrant = FakeQdrant()
        mock_build_qdrant_client.return_value = fake_qdrant

        result = query_lore(
            query_text="Hauptstädte der Rassen",
            limit=4,
            filters={"scope_type": "location"},
        )

        self.assertTrue(result["success"], result)
        self.assertTrue(result["filter_fallback_used"], result)
        self.assertEqual({"scope_type": "location"}, result["applied_filters"])
        self.assertEqual("location_crownford", result["matches"][0]["payload"]["doc_id"])
        self.assertEqual(2, fake_qdrant.calls)


if __name__ == "__main__":
    unittest.main()
