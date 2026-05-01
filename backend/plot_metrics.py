"""
Academic-grade visualization script for PPE compliance monitoring evaluation results.
Generates latency distribution and max IoU distribution plots suitable for thesis publication.
"""

import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import seaborn as sns


# ── Configuration ─────────────────────────────────────────────────────────────

DATA_FILE = os.path.join(os.path.dirname(__file__), "evaluation_results.json")
OUTPUT_DIR = os.path.dirname(__file__)
DPI = 300

# Academic color palette (muted, print-friendly)
COLOR_HIST = "#4878CF"   # steel blue
COLOR_KDE  = "#C44E52"   # muted red
COLOR_THRESH = "#2CA02C" # muted green


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_data(filepath: str) -> dict:
    """Load and return the evaluation results JSON."""
    if not os.path.exists(filepath):
        print(f"[ERROR] File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON: {e}", file=sys.stderr)
        sys.exit(1)


def extract_metrics(data: dict) -> tuple[list[float], list[float]]:
    """
    Extract latency_ms and max_iou from per_image_results,
    skipping any entries with api_error == True.
    """
    latencies: list[float] = []
    max_ious:  list[float] = []

    for record in data.get("per_image_results", []):
        if record.get("api_error", False):
            continue
        latencies.append(record["latency_ms"])
        max_ious.append(record["max_iou"])

    return latencies, max_ious


# ── Plot 1: Latency Distribution ──────────────────────────────────────────────

def plot_latency(latencies: list[float], summary: dict, output_path: str) -> None:
    """Render and save the processing latency histogram with KDE overlay."""
    sns.set_theme(style="whitegrid", font_scale=1.15)

    fig, ax = plt.subplots(figsize=(8, 5))

    sns.histplot(
        latencies,
        bins=20,
        kde=True,
        color=COLOR_HIST,
        edgecolor="white",
        linewidth=0.6,
        line_kws={"color": COLOR_KDE, "linewidth": 2.0},
        ax=ax,
    )

    # Annotate summary statistics
    stats = summary.get("latency_stats_ms", {})
    avg_val = stats.get("avg", np.mean(latencies))
    ax.axvline(avg_val, color=COLOR_KDE, linestyle="--", linewidth=1.4,
               label=f"Mean = {avg_val:.1f} ms")

    ax.set_xlabel("Processing Latency (ms)", fontsize=13, labelpad=8)
    ax.set_ylabel("Frequency", fontsize=13, labelpad=8)
    ax.set_title("Distribution of Per-Image Processing Latency", fontsize=14, pad=12)
    ax.legend(frameon=True, fontsize=11)

    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.tick_params(axis="both", which="both", direction="in")

    # Annotation box with key stats
    n = len(latencies)
    min_v = stats.get("min", min(latencies))
    max_v = stats.get("max", max(latencies))
    info = f"n = {n}\nMin = {min_v} ms\nMax = {max_v} ms"
    ax.text(
        0.97, 0.95, info,
        transform=ax.transAxes,
        fontsize=9.5,
        verticalalignment="top",
        horizontalalignment="right",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#cccccc", alpha=0.85),
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Latency distribution saved → {output_path}")


# ── Plot 2: Max IoU Distribution ──────────────────────────────────────────────

def plot_iou(max_ious: list[float], output_path: str) -> None:
    """Render and save the max-IoU histogram with KDE overlay and mAP@0.5 threshold line."""
    sns.set_theme(style="whitegrid", font_scale=1.15)

    fig, ax = plt.subplots(figsize=(8, 5))

    sns.histplot(
        max_ious,
        bins=25,
        kde=True,
        color=COLOR_HIST,
        edgecolor="white",
        linewidth=0.6,
        line_kws={"color": COLOR_KDE, "linewidth": 2.0},
        ax=ax,
    )

    # mAP@0.5 threshold line
    ax.axvline(0.5, color=COLOR_THRESH, linestyle="--", linewidth=1.6,
               label="mAP@0.5 threshold (IoU = 0.5)")

    ax.set_xlabel("Maximum IoU Score", fontsize=13, labelpad=8)
    ax.set_ylabel("Frequency", fontsize=13, labelpad=8)
    ax.set_title("Distribution of Maximum IoU per Image", fontsize=14, pad=12)
    ax.set_xlim(-0.05, 1.05)
    ax.legend(frameon=True, fontsize=11)

    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.tick_params(axis="both", which="both", direction="in")

    # Proportion above threshold
    n = len(max_ious)
    above = sum(v >= 0.5 for v in max_ious)
    pct = above / n * 100 if n > 0 else 0.0
    info = f"n = {n}\nIoU ≥ 0.5: {above} ({pct:.1f}%)"
    ax.text(
        0.97, 0.95, info,
        transform=ax.transAxes,
        fontsize=9.5,
        verticalalignment="top",
        horizontalalignment="right",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#cccccc", alpha=0.85),
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] IoU distribution saved     → {output_path}")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[INFO] Loading data from: {DATA_FILE}")
    data = load_data(DATA_FILE)

    latencies, max_ious = extract_metrics(data)
    print(f"[INFO] Valid samples extracted: {len(latencies)}")

    if not latencies:
        print("[ERROR] No valid (non-api_error) records found.", file=sys.stderr)
        sys.exit(1)

    summary = data.get("summary", {})

    plot_latency(
        latencies,
        summary,
        os.path.join(OUTPUT_DIR, "latency_distribution.png"),
    )

    plot_iou(
        max_ious,
        os.path.join(OUTPUT_DIR, "iou_distribution.png"),
    )

    print("[DONE] All figures exported successfully.")


if __name__ == "__main__":
    main()
