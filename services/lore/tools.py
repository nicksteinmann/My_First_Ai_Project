"""Tool definitions and dispatcher for lore retrieval."""

from __future__ import annotations

import re

from data.character_presets import RACES
from models import Campaign, CampaignLocation, db
from services.lore.service import chunk_lore_document, load_lore_documents, query_lore

CAPITAL_QUERY_TERMS = (
    "capital",
    "capitals",
    "hauptstadt",
    "hauptstädte",
    "hauptstaedte",
)

RACE_QUERY_ALIASES = {
    "human": {"human", "humans", "mensch", "menschen"},
    "orc": {"orc", "orcs", "ork", "orks"},
    "goblin": {"goblin", "goblins"},
    "elf": {"elf", "elves", "elfen"},
    "dwarf": {"dwarf", "dwarves", "zwerg", "zwerge"},
}


def _normalize_query_text(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_people_key(value: str | None) -> str:
    normalized = _normalize_query_text(value)
    for race_key, aliases in RACE_QUERY_ALIASES.items():
        if normalized in aliases:
            return race_key
    return normalized


def _is_capital_query(query_text: str) -> bool:
    normalized = _normalize_query_text(query_text)
    return any(term in normalized for term in CAPITAL_QUERY_TERMS)


def _extract_requested_races(query_text: str) -> list[str]:
    normalized = _normalize_query_text(query_text)
    requested = []
    for race_key, aliases in RACE_QUERY_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            requested.append(race_key)
    if requested:
        return requested
    return [race_name.strip().lower() for race_name in RACES.keys()]


def _dominant_people_by_region() -> dict[str, str]:
    region_lookup = {}
    for document in load_lore_documents():
        metadata = document.metadata or {}
        if metadata.get("scope_type") != "region":
            continue
        region_id = str(metadata.get("region_id") or "").strip().lower()
        dominant_people = str(metadata.get("dominant_people") or "").strip().lower()
        if region_id and dominant_people:
            region_lookup[region_id] = dominant_people
    return region_lookup


def _build_capital_matches(query_text: str, limit: int) -> list[dict]:
    if not _is_capital_query(query_text):
        return []

    requested_races = set(_extract_requested_races(query_text))
    region_people = _dominant_people_by_region()
    matches = []

    for document in load_lore_documents():
        metadata = document.metadata or {}
        if metadata.get("scope_type") != "location":
            continue

        kind = str(metadata.get("kind") or "").strip().lower()
        if not kind.startswith("capital"):
            continue

        region_id = str(metadata.get("region_id") or "").strip().lower()
        dominant_people = region_people.get(region_id, "")
        normalized_people = _normalize_people_key(dominant_people)
        if requested_races and normalized_people not in requested_races:
            continue

        chunks = chunk_lore_document(document)
        overview_chunk = next((chunk for chunk in chunks if str(chunk.get("title")).strip().lower() == "overview"), None)
        selected_chunk = overview_chunk or (chunks[0] if chunks else None)
        if not selected_chunk:
            continue

        matches.append({
            "score": 1.0,
            "payload": {
                **dict(metadata),
                "doc_id": selected_chunk.get("doc_id"),
                "chunk_id": selected_chunk.get("chunk_id"),
                "title": selected_chunk.get("title"),
                "title_path": selected_chunk.get("title_path"),
                "text": selected_chunk.get("text"),
                "source_path": selected_chunk.get("source_path"),
                "dominant_people": dominant_people,
            },
        })

    desired_order = {race.lower(): index for index, race in enumerate(RACES.keys())}

    def _sort_key(match: dict) -> tuple[int, str]:
        payload = match.get("payload", {}) or {}
        region_id = str(payload.get("region_id") or "").strip().lower()
        people = _normalize_people_key(region_people.get(region_id, ""))
        return (desired_order.get(people, 999), str(payload.get("location_id") or ""))

    matches.sort(key=_sort_key)
    return matches[: max(1, int(limit or 4))]


def _merge_lore_matches(query_text: str, matches: list[dict], limit: int) -> list[dict]:
    supplemental = _build_capital_matches(query_text, limit=limit)
    if not supplemental:
        return matches[: max(1, int(limit or 4))]

    merged = []
    seen_doc_ids = set()
    for match in supplemental + list(matches or []):
        payload = match.get("payload", {}) or {}
        doc_id = payload.get("doc_id")
        if doc_id and doc_id in seen_doc_ids:
            continue
        if doc_id:
            seen_doc_ids.add(doc_id)
        merged.append(match)
        if len(merged) >= max(1, int(limit or 4)):
            break
    return merged


LORE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_lore_context",
            "description": (
                "Retrieve world lore and factual background from the lore retrieval index. "
                "Use this before answering questions about regions, subregions, cities, villages, "
                "cultures, peoples, history, or distant places. Do not invent world facts when this tool can answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "The lore question or retrieval query.",
                    },
                    "scope_type": {
                        "type": "string",
                        "enum": ["region", "subregion", "location", "faction", "history", "religion", "person"],
                        "description": "Optional lore scope to narrow retrieval.",
                    },
                    "region_id": {
                        "type": "string",
                        "description": "Optional region id filter, for example 'crownfields'.",
                    },
                    "subregion_id": {
                        "type": "string",
                        "description": "Optional subregion id filter, for example 'willow_vale'.",
                    },
                    "location_id": {
                        "type": "string",
                        "description": "Optional location id filter, for example 'willowbrook'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of lore matches to return. Usually 3 to 6.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["query_text"],
            },
        },
    }
]


def _current_campaign_context(campaign_id: int) -> dict:
    try:
        campaign = db.session.get(Campaign, campaign_id)
    except RuntimeError:
        return {}
    if not campaign or not campaign.current_location_id:
        return {}
    location = db.session.get(CampaignLocation, campaign.current_location_id)
    if not location:
        return {}
    return {
        "region_id": getattr(location, "region_id", None),
        "subregion_id": (getattr(location, "subregion", None) or "").strip().lower().replace("-", "_").replace(" ", "_") or None,
        "location_id": getattr(location, "world_location_id", None),
    }


def get_lore_context(
    campaign_id: int,
    query_text: str,
    scope_type: str | None = None,
    region_id: str | None = None,
    subregion_id: str | None = None,
    location_id: str | None = None,
    limit: int = 4,
) -> dict:
    """Retrieve lore matches with optional metadata filters."""

    if not query_text or not str(query_text).strip():
        return {"success": False, "message": "query_text is required."}

    filters = {}
    current_context = _current_campaign_context(campaign_id)

    if scope_type:
        filters["scope_type"] = str(scope_type).strip().lower()
    if region_id:
        filters["region_id"] = str(region_id).strip().lower()
    if subregion_id:
        filters["subregion_id"] = str(subregion_id).strip().lower().replace("-", "_").replace(" ", "_")
    if location_id:
        filters["location_id"] = str(location_id).strip().lower()

    result = query_lore(
        query_text=str(query_text).strip(),
        limit=max(1, min(int(limit or 4), 8)),
        filters=filters or None,
        provider="openai",
    )
    if not result.get("success"):
        return result

    matches = _merge_lore_matches(
        query_text=str(query_text).strip(),
        matches=result.get("matches", []),
        limit=max(1, min(int(limit or 4), 8)),
    )
    summarized_matches = []
    for match in matches:
        payload = match.get("payload", {}) or {}
        summarized_matches.append({
            "score": match.get("score"),
            "doc_id": payload.get("doc_id"),
            "scope_type": payload.get("scope_type"),
            "title": payload.get("title"),
            "title_path": payload.get("title_path"),
            "region_id": payload.get("region_id"),
            "subregion_id": payload.get("subregion_id"),
            "location_id": payload.get("location_id"),
            "knowledge_level": payload.get("knowledge_level"),
            "text": payload.get("text"),
            "source_path": payload.get("source_path"),
        })

    return {
        "success": True,
        "tool": "get_lore_context",
        "query_text": str(query_text).strip(),
        "filters": filters,
        "current_context": current_context,
        "matches": summarized_matches,
    }


def execute_lore_tool(campaign_id: int, tool_name: str, arguments: dict) -> dict:
    """Dispatch lore tool calls."""

    if tool_name != "get_lore_context":
        return {"success": False, "message": f"Unknown lore tool: {tool_name}"}

    return get_lore_context(
        campaign_id=campaign_id,
        query_text=arguments.get("query_text"),
        scope_type=arguments.get("scope_type"),
        region_id=arguments.get("region_id"),
        subregion_id=arguments.get("subregion_id"),
        location_id=arguments.get("location_id"),
        limit=arguments.get("limit", 4),
    )
