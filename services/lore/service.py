"""Lore markdown loading, chunking, and vector-retrieval helpers."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.llm_service import build_client
from services.world_data import load_world_data, normalize_coordinate

LORE_ROOT = Path(__file__).resolve().parent.parent.parent / "lore"
REGIONS_DIR = LORE_ROOT / "regions"
SUBREGIONS_DIR = LORE_ROOT / "subregions"
LOCATIONS_DIR = LORE_ROOT / "locations"
LORE_INDEX_PATH = LORE_ROOT / "README.md"

DEFAULT_COLLECTION_NAME = "avalion_lore"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536
DEFAULT_QDRANT_TIMEOUT_SECONDS = 60
DEFAULT_QDRANT_BATCH_SIZE = 32
MAX_SECTION_CHARS = 2200
SOFT_SECTION_SPLIT_CHARS = 1200
FILTERABLE_LORE_FIELDS = (
    "scope_type",
    "region_id",
    "subregion_id",
    "location_id",
    "kind",
    "knowledge_level",
)

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class LoreDocument:
    """One markdown lore file with parsed metadata."""

    path: Path
    metadata: dict[str, Any]
    body: str


def ensure_lore_directories() -> None:
    """Create the canonical lore directory structure if it does not exist."""

    for path in (LORE_ROOT, REGIONS_DIR, SUBREGIONS_DIR, LOCATIONS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def slugify(value: Any) -> str:
    """Return a filesystem-safe slug."""

    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "entry"


def parse_frontmatter(markdown_text: str) -> tuple[dict[str, Any], str]:
    """Parse simple YAML frontmatter from a markdown document."""

    match = FRONTMATTER_PATTERN.match(markdown_text or "")
    if not match:
        return {}, str(markdown_text or "").strip()

    raw_yaml, body = match.groups()
    try:
        metadata = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, body.strip()


def load_lore_documents(root: Path | None = None) -> list[LoreDocument]:
    """Load every markdown lore file below the lore root."""

    base_dir = root or LORE_ROOT
    if not base_dir.exists():
        return []

    documents: list[LoreDocument] = []
    for path in sorted(base_dir.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        raw_text = path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(raw_text)
        documents.append(LoreDocument(path=path, metadata=metadata, body=body))
    return documents


def _source_path_for_document(path: Path) -> str:
    """Return a stable relative display path for a lore document."""

    try:
        return str(path.resolve().relative_to(LORE_ROOT.resolve()))
    except ValueError:
        return str(path)


def _estimate_token_count(text: str) -> int:
    """Return a lightweight token estimate without requiring a remote call."""

    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text or ""))
    except Exception:
        return max(1, len(str(text or "")) // 4)


def _split_large_section(text: str, max_chars: int = MAX_SECTION_CHARS) -> list[str]:
    """Split an oversized section on paragraphs, then sentences if needed."""

    normalized = str(text or "").strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        sentence_chunk = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate_sentence = sentence if not sentence_chunk else f"{sentence_chunk} {sentence}"
            if len(candidate_sentence) <= max_chars:
                sentence_chunk = candidate_sentence
            else:
                if sentence_chunk:
                    chunks.append(sentence_chunk)
                sentence_chunk = sentence
        current = sentence_chunk
    if current:
        chunks.append(current)
    return chunks


def chunk_lore_document(document: LoreDocument, max_section_chars: int = MAX_SECTION_CHARS) -> list[dict[str, Any]]:
    """Chunk one lore markdown document by semantic headings first."""

    lines = document.body.splitlines()
    top_heading = document.metadata.get("title") or document.metadata.get("name")
    current_heading = str(top_heading or document.path.stem).strip()
    current_level = 1
    current_lines: list[str] = []
    sections: list[tuple[str, int, str]] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_heading, current_level, text))

    for raw_line in lines:
        match = HEADING_PATTERN.match(raw_line)
        if match:
            new_level = len(match.group(1))
            new_heading = match.group(2).strip()
            if new_level <= 2 or (len("\n".join(current_lines)) >= SOFT_SECTION_SPLIT_CHARS and new_level <= 3):
                flush()
                current_lines.clear()
                current_heading = new_heading
                current_level = new_level
                continue
        current_lines.append(raw_line)
    flush()

    chunks: list[dict[str, Any]] = []
    chunk_index = 0
    for heading, level, section_text in sections:
        split_sections = _split_large_section(section_text, max_chars=max_section_chars)
        for part_index, split_text in enumerate(split_sections, start=1):
            chunk_index += 1
            title_path = [str(document.metadata.get("title") or document.metadata.get("name") or document.path.stem), heading]
            if heading == title_path[0]:
                title_path = [heading]
            chunks.append({
                "chunk_id": f"{document.metadata.get('doc_id', document.path.stem)}__{chunk_index}",
                "doc_id": document.metadata.get("doc_id", document.path.stem),
                "title": heading,
                "title_path": " > ".join([part for part in title_path if part]),
                "heading_level": level,
                "text": split_text,
                "token_estimate": _estimate_token_count(split_text),
                "part_index": part_index,
                "metadata": dict(document.metadata),
                "source_path": _source_path_for_document(document.path),
            })
    return chunks


def _qdrant_settings() -> dict[str, Any]:
    """Return Qdrant connection settings from env."""

    return {
        "url": os.getenv("QDRANT_URL", "").strip(),
        "api_key": os.getenv("QDRANT_API_KEY", "").strip(),
        "collection": os.getenv("QDRANT_LORE_COLLECTION", DEFAULT_COLLECTION_NAME).strip() or DEFAULT_COLLECTION_NAME,
        "embedding_model": os.getenv("LORE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL,
        "embedding_dimensions": int(os.getenv("LORE_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS)) or DEFAULT_EMBEDDING_DIMENSIONS),
        "timeout_seconds": int(os.getenv("QDRANT_TIMEOUT_SECONDS", str(DEFAULT_QDRANT_TIMEOUT_SECONDS)) or DEFAULT_QDRANT_TIMEOUT_SECONDS),
        "batch_size": int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", str(DEFAULT_QDRANT_BATCH_SIZE)) or DEFAULT_QDRANT_BATCH_SIZE),
    }


def _build_qdrant_client():
    """Build the Qdrant client lazily so the app still imports without the package."""

    from qdrant_client import QdrantClient

    settings = _qdrant_settings()
    if not settings["url"]:
        raise RuntimeError("QDRANT_URL is not configured.")
    return QdrantClient(
        url=settings["url"],
        api_key=settings["api_key"] or None,
        timeout=settings["timeout_seconds"],
    )


def _ensure_payload_indexes(qdrant, collection_name: str) -> None:
    """Ensure common filter fields are indexed in Qdrant."""

    from qdrant_client.models import PayloadSchemaType

    for field_name in FILTERABLE_LORE_FIELDS:
        qdrant.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=PayloadSchemaType.KEYWORD,
            wait=True,
        )


def _embed_texts(texts: list[str], provider: str = "openai") -> list[list[float]]:
    """Create embeddings for lore chunks."""

    if not texts:
        return []
    settings = _qdrant_settings()
    client = build_client(provider)
    response = client.embeddings.create(
        model=settings["embedding_model"],
        input=texts,
        dimensions=settings["embedding_dimensions"],
    )
    return [list(item.embedding) for item in response.data]


def sync_lore_to_qdrant(root: Path | None = None, provider: str = "openai") -> dict[str, Any]:
    """Load lore markdown, chunk it, embed it, and upsert it into Qdrant."""

    from qdrant_client.models import Distance, PointStruct, VectorParams

    settings = _qdrant_settings()
    qdrant = _build_qdrant_client()
    documents = load_lore_documents(root=root)
    chunks = [chunk for document in documents for chunk in chunk_lore_document(document)]
    texts = [chunk["text"] for chunk in chunks]
    embeddings = _embed_texts(texts, provider=provider)

    existing_collections = {collection.name for collection in qdrant.get_collections().collections}
    if settings["collection"] not in existing_collections:
        qdrant.create_collection(
            collection_name=settings["collection"],
            vectors_config=VectorParams(
                size=settings["embedding_dimensions"],
                distance=Distance.COSINE,
            ),
        )
    _ensure_payload_indexes(qdrant, settings["collection"])

    points: list[PointStruct] = []
    for chunk, vector in zip(chunks, embeddings, strict=False):
        payload = {
            **chunk["metadata"],
            "doc_id": chunk["doc_id"],
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "title_path": chunk["title_path"],
            "text": chunk["text"],
            "source_path": chunk["source_path"],
            "token_estimate": chunk["token_estimate"],
        }
        points.append(
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"])),
                vector=vector,
                payload=payload,
            )
        )

    if points:
        batch_size = max(1, int(settings["batch_size"] or DEFAULT_QDRANT_BATCH_SIZE))
        for batch_start in range(0, len(points), batch_size):
            batch = points[batch_start:batch_start + batch_size]
            qdrant.upsert(
                collection_name=settings["collection"],
                wait=True,
                points=batch,
            )

    return {
        "success": True,
        "documents": len(documents),
        "chunks": len(chunks),
        "collection": settings["collection"],
    }


def query_lore(query_text: str, limit: int = 5, filters: dict[str, Any] | None = None, provider: str = "openai") -> dict[str, Any]:
    """Query the lore collection with optional payload filters."""

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    settings = _qdrant_settings()
    qdrant = _build_qdrant_client()
    embedding = _embed_texts([query_text], provider=provider)[0]

    conditions = []
    for key, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
    query_filter = Filter(must=conditions) if conditions else None

    try:
        results = qdrant.query_points(
            collection_name=settings["collection"],
            query=embedding,
            query_filter=query_filter,
            limit=max(1, int(limit or 5)),
        )
        filter_fallback_used = False
    except Exception as exc:
        error_text = str(exc)
        missing_index = "Index required but not found" in error_text
        if not (query_filter and missing_index):
            raise
        results = qdrant.query_points(
            collection_name=settings["collection"],
            query=embedding,
            query_filter=None,
            limit=max(1, int(limit or 5)),
        )
        filter_fallback_used = True

    matches = []
    for point in getattr(results, "points", []):
        matches.append({
            "score": getattr(point, "score", None),
            "payload": dict(getattr(point, "payload", {}) or {}),
        })

    return {
        "success": True,
        "collection": settings["collection"],
        "filter_fallback_used": filter_fallback_used,
        "applied_filters": dict(filters or {}),
        "matches": matches,
    }


def _frontmatter_block(metadata: dict[str, Any]) -> str:
    """Render YAML frontmatter text."""

    return yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()


def _write_markdown_file(path: Path, metadata: dict[str, Any], sections: list[tuple[str, str]]) -> None:
    """Write one lore markdown file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", _frontmatter_block(metadata), "---", ""]
    for heading, text in sections:
        lines.append(f"## {heading}")
        lines.append(text.strip())
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def export_world_lore_markdown(overwrite: bool = False) -> dict[str, int]:
    """Create starter lore markdown files from world.json."""

    ensure_lore_directories()
    world_data = load_world_data()
    region_count = 0
    subregion_count = 0
    location_count = 0

    intro_lines = [
        "# Avalion Lore",
        "",
        "This folder is the canonical lore source for retrieval.",
        "",
        "Use markdown plus YAML frontmatter.",
        "Write lore here first, then ingest it into Qdrant.",
        "",
        "Structure:",
        "- `regions/` for the five large race regions and other large zones",
        "- `subregions/` for regional subdivisions and travel-scale areas",
        "- `locations/` for cities, towns, villages, towers, forts, ports, shrines, and other fixed places",
        "",
        "Chunking rule:",
        "- prefer semantic sections via headings",
        "- only split by size when a heading section becomes too large",
        "",
    ]
    if overwrite or not LORE_INDEX_PATH.exists():
        LORE_INDEX_PATH.write_text("\n".join(intro_lines), encoding="utf-8")

    for region in world_data.get("regions", []):
        region_id = region.get("id")
        region_name = region.get("name")
        region_path = REGIONS_DIR / f"{slugify(region_id)}.md"
        region_metadata = {
            "doc_id": f"region_{region_id}",
            "scope_type": "region",
            "region_id": region_id,
            "title": region_name,
            "dominant_people": region.get("dominant_people"),
            "terrain": region.get("terrain"),
            "tags": ["region", slugify(region.get("dominant_people"))],
            "knowledge_level": "public",
        }
        region_sections = [
            ("Overview", region.get("description", "TODO: Add region overview lore.")),
            ("Geography", f"Terrain: {region.get('terrain', 'Unknown')}. Dominant people: {region.get('dominant_people', 'Unknown')}."),
            ("Adventure Use", "TODO: Add travel tone, politics, dangers, trade, culture, and adventure hooks."),
        ]
        if overwrite or not region_path.exists():
            _write_markdown_file(region_path, region_metadata, region_sections)
        region_count += 1

        for subregion in region.get("subregions", []):
            subregion_id = subregion.get("id")
            subregion_name = subregion.get("name")
            bounds = subregion.get("bounds", {})
            subregion_path = SUBREGIONS_DIR / f"{slugify(subregion_id)}.md"
            subregion_metadata = {
                "doc_id": f"subregion_{subregion_id}",
                "scope_type": "subregion",
                "region_id": region_id,
                "subregion_id": subregion_id,
                "title": subregion_name,
                "tags": ["subregion", slugify(region_id)],
                "knowledge_level": "public",
            }
            subregion_sections = [
                ("Overview", f"{subregion_name} is a subregion of {region_name}. TODO: Expand local lore, landmarks, and travel identity."),
                ("Map Bounds", f"Bounds: `{bounds}`"),
                ("Adventure Use", "TODO: Add local roads, dangers, rumor tone, economy, and notable recurring scene types."),
            ]
            if overwrite or not subregion_path.exists():
                _write_markdown_file(subregion_path, subregion_metadata, subregion_sections)
            subregion_count += 1

        for location in region.get("locations", []):
            location_id = location.get("id")
            location_name = location.get("name")
            location_path = LOCATIONS_DIR / f"{slugify(location_id)}.md"
            location_metadata = {
                "doc_id": f"location_{location_id}",
                "scope_type": "location",
                "region_id": region_id,
                "subregion_id": slugify(location.get("subregion")),
                "location_id": location_id,
                "title": location_name,
                "kind": location.get("kind"),
                "x": normalize_coordinate(location.get("x")),
                "y": normalize_coordinate(location.get("y")),
                "tags": ["location", slugify(location.get("kind")), slugify(region_id)],
                "knowledge_level": "public",
            }
            location_sections = [
                ("Overview", location.get("description", "TODO: Add location overview lore.")),
                ("Map Context", f"Region: {region_name}. Subregion: {location.get('subregion')}. Coordinates: {location.get('x')}, {location.get('y')}. Kind: {location.get('kind')}."),
                ("Culture and Daily Life", "TODO: Add people, routines, class feel, atmosphere, and player-facing first impression."),
                ("Adventure Use", "TODO: Add merchants, trainers, factions, hooks, conflicts, rumors, and services."),
            ]
            if overwrite or not location_path.exists():
                _write_markdown_file(location_path, location_metadata, location_sections)
            location_count += 1

    return {
        "regions": region_count,
        "subregions": subregion_count,
        "locations": location_count,
    }
