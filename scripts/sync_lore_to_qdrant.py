"""Sync local lore markdown files into the configured Qdrant collection."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.lore.service import sync_lore_to_qdrant


def main() -> None:
    result = sync_lore_to_qdrant(provider="openai")
    print(
        "Synced lore to Qdrant: "
        f"{result['documents']} documents, "
        f"{result['chunks']} chunks, "
        f"collection={result['collection']}"
    )


if __name__ == "__main__":
    main()
