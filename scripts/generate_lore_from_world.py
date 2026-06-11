"""Generate starter lore markdown files from data/world.json."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.lore.service import export_world_lore_markdown


def main() -> None:
    result = export_world_lore_markdown(overwrite=False)
    print(
        "Generated starter lore files: "
        f"{result['regions']} regions, "
        f"{result['subregions']} subregions, "
        f"{result['locations']} locations."
    )


if __name__ == "__main__":
    main()
