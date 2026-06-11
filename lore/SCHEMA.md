# Lore Schema

This file defines the authoring format for retrieval lore.

## Canonical Source

- Write lore in markdown files.
- Use YAML frontmatter for metadata.
- The markdown files are the source of truth.
- Qdrant is only the retrieval index built from these files.

## Folder Layout

- `lore/regions/`
- `lore/subregions/`
- `lore/locations/`

Optional later:

- `lore/factions/`
- `lore/history/`
- `lore/religion/`
- `lore/people/`

## Required Frontmatter

```yaml
doc_id: location_willowbrook
scope_type: location
title: Willowbrook
knowledge_level: public
```

## Recommended Frontmatter

```yaml
doc_id: location_willowbrook
scope_type: location
region_id: crownfields
subregion_id: willow_vale
location_id: willowbrook
title: Willowbrook
kind: city
x: 48.4
y: 48.1
tags:
  - location
  - city
  - crownfields
knowledge_level: public
```

## Scope Types

- `region`
- `subregion`
- `location`
- `faction`
- `history`
- `religion`
- `person`

## Knowledge Levels

- `public`
- `regional`
- `restricted`
- `secret`

## Heading Rules

- Use `##` for retrieval-first sections.
- Use `###` only when one `##` section becomes large.
- Keep sections semantic, not arbitrary token cuts.

Suggested sections for places:

- `## Overview`
- `## Map Context`
- `## Culture and Daily Life`
- `## Politics`
- `## Economy`
- `## Factions`
- `## Notable People`
- `## Adventure Use`
- `## Rumors`

Suggested sections for regions:

- `## Overview`
- `## Geography`
- `## Politics`
- `## Culture`
- `## Threats`
- `## Trade and Travel`
- `## Adventure Use`

## Chunking Strategy

- First split by file and headings.
- If one heading section is too large, split by paragraph.
- Only then split more aggressively.

## Metadata Filtering Goals

The retrieval system should later be able to filter by:

- `scope_type`
- `region_id`
- `subregion_id`
- `location_id`
- `kind`
- `knowledge_level`
- `tags`

## Important Rule

- Do not dump giant mixed lore blocks into one file.
- One place or one topic per file is preferred.
- Keep metadata precise so retrieval can filter before similarity search.
