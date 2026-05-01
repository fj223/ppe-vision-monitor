"""
Converts a directory of JPG images into a low-FPS MP4 video for frontend playback.
Usage: python images_to_video.py
"""

import glob
import os
import sys

import cv2
import numpy as np

# ── Configuration ──────────────────────────────────────────────────────────────

INPUT_DIR  = r"C:\Users\随风1\Desktop\Protection Search\ppe_video\construction-ppe\images\test"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "dataset_test.mp4")
FPS = 3.0

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Collect and sort all jpg images
    pattern = os.path.join(INPUT_DIR, "*.jpg")
    image_paths = sorted(glob.glob(pattern))

    if not image_paths:
        print(f"[ERROR] No .jpg images found in: {INPUT_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Found {len(image_paths)} images in: {INPUT_DIR}")

    # Read first frame to get reference resolution
    first_frame = cv2.imread(image_paths[0])
    if first_frame is None:
        print(f"[ERROR] Cannot read first image: {image_paths[0]}", file=sys.stderr)
        sys.exit(1)

    height, width = first_frame.shape[:2]
    print(f"[INFO] Reference resolution: {width}x{height}")
    print(f"[INFO] Output FPS: {FPS}  |  Codec: mp4v")

    # Initialize VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(OUTPUT_PATH, fourcc, FPS, (width, height))

    if not writer.isOpened():
        print(f"[ERROR] Failed to open VideoWriter for: {OUTPUT_PATH}", file=sys.stderr)
        sys.exit(1)

    # Write frames
    for idx, path in enumerate(image_paths, start=1):
        frame = cv2.imread(path)
        if frame is None:
            print(f"[WARN]  Skipping unreadable image ({idx}/{len(image_paths)}): {path}")
            continue

        # Letterbox: scale proportionally and pad with black borders
        if frame.shape[:2] != (height, width):
            h, w = frame.shape[:2]
            scale = min(width / w, height / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            y_off = (height - new_h) // 2
            x_off = (width  - new_w) // 2
            frame[y_off:y_off + new_h, x_off:x_off + new_w] = resized

        writer.write(frame)

        if idx % 20 == 0 or idx == len(image_paths):
            print(f"[INFO] Progress: {idx}/{len(image_paths)} frames written")

    writer.release()
    print(f"\n[DONE] Video saved successfully → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
