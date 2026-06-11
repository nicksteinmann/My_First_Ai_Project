# Avalion Lore

This folder is the canonical lore source for retrieval.

Use markdown plus YAML frontmatter.
Write lore here first, then ingest it into Qdrant.

Structure:
- `regions/` for the five large race regions and other large zones
- `subregions/` for regional subdivisions and travel-scale areas
- `locations/` for cities, towns, villages, towers, forts, ports, shrines, and other fixed places

Chunking rule:
- prefer semantic sections via headings
- only split by size when a heading section becomes too large
