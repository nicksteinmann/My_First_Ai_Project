"""Crop a generated 3x2 portrait sheet into square character portrait assets."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def crop_sheet(input_path: Path, output_dir: Path, keys: list[str]) -> None:
    """Split a 3x2 portrait sheet into square portrait PNG files."""

    if len(keys) > 6:
        raise ValueError("A 3x2 sheet supports at most 6 output keys.")

    output_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as image:
        width, height = image.size
        cols = 3
        rows = 2
        cell_width = width / cols
        cell_height = height / rows

        for index, key in enumerate(keys):
            if not key or key.lower() == "skip":
                continue

            row = index // cols
            col = index % cols
            left = int(round(col * cell_width))
            upper = int(round(row * cell_height))
            right = int(round((col + 1) * cell_width))
            lower = int(round((row + 1) * cell_height))

            cell = image.crop((left, upper, right, lower))
            crop_size = min(cell.width, cell.height)
            crop_left = (cell.width - crop_size) // 2
            crop_upper = (cell.height - crop_size) // 2
            portrait = cell.crop((
                crop_left,
                crop_upper,
                crop_left + crop_size,
                crop_upper + crop_size,
            ))
            portrait.save(output_dir / f"{key}.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--keys",
        required=True,
        help="Comma-separated asset keys in 3x2 reading order. Use 'skip' for empty cells.",
    )
    args = parser.parse_args()

    keys = [part.strip() for part in args.keys.split(",")]
    crop_sheet(args.input_path, args.output_dir, keys)


if __name__ == "__main__":
    main()
