"""Evaluate a trained local YOLOv8 checkpoint on the held-out test split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=Path("models/best.pt"))
    parser.add_argument("--data", type=Path, default=Path("datasets/ppe_yolo/data.yaml"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=Path("evaluation_results.json"))
    args = parser.parse_args()
    metrics = YOLO(args.weights).val(data=str(args.data.resolve()), split="test", device=args.device)
    result = {
        "status": "measured",
        "weights": str(args.weights),
        "dataset": str(args.data),
        "split": "test",
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
