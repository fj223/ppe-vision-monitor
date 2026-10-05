"""Train and evaluate the PPE detector; no metric values are hard-coded."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("datasets/ppe_yolo/data.yaml"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2, help="Use 1 or 2 on an MX350 with 2 GB VRAM.")
    parser.add_argument("--device", default="cpu", help="Use '0' only if CUDA is available.")
    parser.add_argument(
        "--amp",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable automatic mixed precision. Leave off for CPU training.",
    )
    args = parser.parse_args()

    data_file = args.data.resolve()
    data_config = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    # ``prepare_dataset.py`` may run on Windows while training runs in Linux
    # Docker.  Rebase the dataset root at runtime so its YAML is portable.
    data_config["path"] = str(data_file.parent)
    runtime_data_file = data_file.parent / ".runtime_data.yaml"
    runtime_data_file.write_text(yaml.safe_dump(data_config, sort_keys=False), encoding="utf-8")

    model = YOLO("yolov8n.pt")
    model.train(
        data=str(runtime_data_file),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        amp=args.amp,
        project="runs",
        name="ppe_yolov8n",
    )
    best = Path(model.trainer.best)
    metrics = YOLO(best).val(data=str(runtime_data_file), split="test", device=args.device)
    print(f"Best checkpoint: {best}")
    print(f"mAP50: {metrics.box.map50:.4f}; mAP50-95: {metrics.box.map:.4f}")
    print("Copy best.pt to backend/models/best.pt before starting the monitoring service.")


if __name__ == "__main__":
    main()
