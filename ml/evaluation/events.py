"""One-to-one event matching, bootstrap by video, no negative-time matches."""

import argparse
import json
from pathlib import Path

import numpy as np


def evaluate(predictions: list[dict], truth: list[dict], hours: float, tolerance: float = 2):
    used = set()
    delays = []
    for prediction in sorted(predictions, key=lambda x: x["timestamp"]):
        candidates = [
            (i, g)
            for i, g in enumerate(truth)
            if i not in used
            and g["video_id"] == prediction["video_id"]
            and g["rule_id"] == prediction["rule_id"]
            and 0 <= prediction["timestamp"] - g["timestamp"] <= tolerance
        ]
        if candidates:
            i, target = min(candidates, key=lambda x: prediction["timestamp"] - x[1]["timestamp"])
            used.add(i)
            delays.append(prediction["timestamp"] - target["timestamp"])
    tp, fp, fn = len(used), len(predictions) - len(used), len(truth) - len(used)
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(precision + recall, 1e-12),
        "false_alarms_per_video_hour": fp / hours if hours > 0 else None,
        "mean_detection_delay_seconds": float(np.mean(delays)) if delays else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="JSON containing predictions, truth, hours")
    parser.add_argument("--output", default="data/evaluation/events.json")
    args = parser.parse_args()
    report = evaluate(**json.loads(Path(args.input).read_text()))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2))
