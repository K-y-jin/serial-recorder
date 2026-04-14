"""Display a CSV recorded by Bliss Recorder.

Usage:
    python cmd/display.py <csv_path> [--rows 64] [--cols 32]
                         [--cmap jet] [--fps 0] [--loop]
                         [--rotate 0]
"""
import argparse
import csv
import os
import sys
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from bliss import config


def build_parser():
    p = argparse.ArgumentParser(prog="display", description="Bliss CSV player")
    p.add_argument("csv_path", help="path to CSV recorded by Bliss Recorder")
    p.add_argument("--rows", type=int, default=config.DEFAULT_ROWS)
    p.add_argument("--cols", type=int, default=config.DEFAULT_COLS)
    p.add_argument("--cmap", default="jet")
    p.add_argument("--fps", type=float, default=0.0,
                   help="playback fps (0 = use recorded timestamps)")
    p.add_argument("--loop", action="store_true", help="loop playback")
    p.add_argument("--rotate", type=int, default=0, choices=[0, 1, 2, 3],
                   help="number of 90° CCW rotations for display")
    return p


def parse_ts(s):
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def load_csv(path, rows, cols):
    expected = rows * cols
    timestamps = []
    frames = []
    with open(path, "r", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError("Empty CSV")
        for i, row in enumerate(reader):
            if len(row) < 1 + expected:
                raise ValueError(
                    f"Row {i}: expected {1 + expected} columns, got {len(row)}. "
                    f"Check --rows/--cols (current: {rows}x{cols})."
                )
            ts = parse_ts(row[0])
            vals = np.array(row[1:1 + expected], dtype=np.float32).astype(np.uint8)
            timestamps.append(ts)
            frames.append(vals.reshape(rows, cols))
    if not frames:
        raise ValueError("No frames in CSV")
    return timestamps, frames


def main(argv=None):
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.csv_path):
        raise FileNotFoundError(args.csv_path)

    timestamps, frames = load_csv(args.csv_path, args.rows, args.cols)
    n = len(frames)
    print(f"[load] {n} frames from {args.csv_path}")

    if args.fps > 0 or any(t is None for t in timestamps):
        fps = args.fps if args.fps > 0 else 1.0
        intervals = [1.0 / fps] * n
    else:
        intervals = [0.0]
        for i in range(1, n):
            intervals.append(max(0.01, timestamps[i] - timestamps[i - 1]))

    first = np.rot90(frames[0], k=args.rotate)
    fig, ax = plt.subplots(figsize=(7, 5))
    fig.canvas.manager.set_window_title(os.path.basename(args.csv_path))
    im = ax.imshow(first, cmap=args.cmap, vmin=0, vmax=255,
                   aspect="equal", interpolation="nearest")
    fig.colorbar(im, ax=ax)
    title = ax.set_title("")
    ax.set_xlabel("col")
    ax.set_ylabel("row")

    def update(i):
        frame = np.rot90(frames[i], k=args.rotate)
        im.set_data(frame)
        ts = timestamps[i]
        ts_str = (datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
                  if ts is not None else "--")
        title.set_text(f"frame {i + 1}/{n}   t={ts_str}   "
                       f"min={int(frame.min())} max={int(frame.max())} "
                       f"mean={frame.mean():.1f}")
        return im, title

    def frame_gen():
        while True:
            for i in range(n):
                yield i
            if not args.loop:
                return

    anim = FuncAnimation(
        fig, update,
        frames=frame_gen,
        interval=max(1, int(intervals[0] * 1000)) if n > 1 else 100,
        blit=False,
        cache_frame_data=False,
        repeat=args.loop,
    )
    _ = anim  # keep reference
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
