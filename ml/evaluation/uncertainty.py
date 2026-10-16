"""Bootstrap event metrics by independent source video, never individual frames."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


def bootstrap(data: dict, replicates: int = 2000, seed: int = 42) -> dict:
    spec = importlib.util.spec_from_file_location("event_metrics", Path(__file__).with_name("events.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    durations = data["video_hours"]
    videos = sorted(durations)
    if len(videos) < 2 or any(v <= 0 for v in durations.values()):
        raise ValueError("At least two independent videos with positive durations are required")
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(replicates):
        selected = rng.choice(videos, size=len(videos), replace=True)
        predictions, truth = [], []
        for occurrence, video in enumerate(selected):
            predictions.extend(
                {**p, "video_id": str(occurrence)} for p in data["predictions"] if p["video_id"] == video
            )
            truth.extend({**p, "video_id": str(occurrence)} for p in data["truth"] if p["video_id"] == video)
        samples.append(module.evaluate(predictions, truth, sum(durations[v] for v in selected)))
    return {
        "unit": "source_video",
        "seed": seed,
        "replicates": replicates,
        "videos": len(videos),
        "intervals_95": {
            k: np.percentile([s[k] for s in samples], [2.5, 97.5]).tolist()
            for k in ("precision", "recall", "f1", "false_alarms_per_video_hour")
        },
        "scope": data.get("scope", "supplied annotations; independence must be audited"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(bootstrap(json.loads(args.input.read_text())), indent=2))
