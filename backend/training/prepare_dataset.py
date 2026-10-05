"""Create a deterministic YOLOv8 train/validation/test split from archive/."""

from __future__ import annotations

import argparse
import random
import shutil
from collections import Counter
from pathlib import Path

CLASS_NAMES = ["helmet", "vest"]


def link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.hardlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("../archive"))
    parser.add_argument("--output", type=Path, default=Path("datasets/ppe_yolo"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    source = args.source.resolve()
    images_dir, labels_dir = source / "image" / "image", source / "labels" / "labels"
    images = {path.stem: path for path in images_dir.glob("*.jpg")}
    labels = {path.stem: path for path in labels_dir.glob("*.txt") if path.name != "classes.txt"}
    paired = sorted(images.keys() & labels.keys())
    if not paired:
        raise SystemExit(f"No matching .jpg/.txt pairs found under {source}")

    random.Random(args.seed).shuffle(paired)
    total = len(paired)
    cut_train, cut_val = round(total * 0.70), round(total * 0.90)
    splits = {"train": paired[:cut_train], "val": paired[cut_train:cut_val], "test": paired[cut_val:]}
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    for split, names in splits.items():
        for name in names:
            link_or_copy(images[name], output / "images" / split / images[name].name)
            link_or_copy(labels[name], output / "labels" / split / labels[name].name)

    yaml = "\n".join([
        f"path: {output.as_posix()}", "train: images/train", "val: images/val", "test: images/test",
        "names:", *[f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES)], "",
    ])
    (output / "data.yaml").write_text(yaml, encoding="utf-8")
    print(f"Created {total} paired samples: " + ", ".join(f"{key}={len(value)}" for key, value in splits.items()))
    print(f"Ignored: {len(images) - total} image(s) without labels and {len(labels) - total} label(s) without images.")
    print(f"Dataset configuration: {output / 'data.yaml'}")


if __name__ == "__main__":
    main()
