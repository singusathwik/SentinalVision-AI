"""Export saved normalized trajectories to MOTChallenge prediction rows."""

import argparse
import json
from pathlib import Path


def export(source: Path, destination: Path, fps: float):
    if fps <= 0:
        raise ValueError("Positive source FPS required")
    rows = []
    for line in source.read_text().splitlines():
        frame = json.loads(line)
        number = round(frame["timestamp"] * fps) + 1
        for track in frame["tracks"]:
            x1, y1, x2, y2 = track["box"]
            w, h = frame["width"], frame["height"]
            rows.append(
                f"{number},{track['id']},{x1 * w:.3f},{y1 * h:.3f},{(x2 - x1) * w:.3f},{(y2 - y1) * h:.3f},{track['confidence']:.5f},-1,-1,-1"
            )
    destination.write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--fps", type=float, required=True)
    args = parser.parse_args()
    export(args.source, args.destination, args.fps)
