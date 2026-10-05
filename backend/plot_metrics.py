"""Plot selected metrics from a local Ultralytics results.csv file."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_csv", type=Path, help="Ultralytics runs/.../results.csv")
    parser.add_argument("--output", type=Path, default=Path("training_metrics.png"))
    args = parser.parse_args()
    frame = pd.read_csv(args.results_csv)
    frame.columns = [column.strip() for column in frame.columns]
    columns = [column for column in ("metrics/mAP50(B)", "metrics/mAP50-95(B)") if column in frame]
    if not columns:
        raise SystemExit("results.csv does not contain YOLOv8 mAP columns")
    frame.plot(x="epoch", y=columns, ylabel="score", ylim=(0, 1), grid=True)
    plt.tight_layout()
    plt.savefig(args.output, dpi=160)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
