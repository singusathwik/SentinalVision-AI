"""Actor-aware interval matching with maximum-cardinality one-to-one assignments."""

import argparse
import json
from pathlib import Path


def evaluate(predictions, truth, hours, minimum_iou=0.1):
    if hours <= 0 or not 0 < minimum_iou <= 1:
        raise ValueError("Positive duration and IoU in (0,1] required")
    for event in [*predictions, *truth]:
        if not event.get("actor_id") or event["end"] <= event["start"]:
            raise ValueError("Mapped actor identity and positive interval required")
    edges = {}
    for i, prediction in enumerate(predictions):
        candidates = []
        for j, target in enumerate(truth):
            if any(prediction[k] != target[k] for k in ("video_id", "rule_id", "actor_id")):
                continue
            intersection = max(
                0, min(prediction["end"], target["end"]) - max(prediction["start"], target["start"])
            )
            union = max(prediction["end"], target["end"]) - min(prediction["start"], target["start"])
            if intersection / union >= minimum_iou:
                candidates.append((intersection / union, j))
        edges[i] = [j for _, j in sorted(candidates, reverse=True)]
    assigned = {}

    def match(i, visited):
        for j in edges[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in assigned or match(assigned[j], visited):
                assigned[j] = i
                return True
        return False

    for i in sorted(edges, key=lambda i: (predictions[i]["start"], i)):
        match(i, set())
    tp = len(assigned)
    precision, recall = tp / max(len(predictions), 1), tp / max(len(truth), 1)
    return {
        "tp": tp,
        "fp": len(predictions) - tp,
        "fn": len(truth) - tp,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(precision + recall, 1e-12),
        "false_alarms_per_video_hour": (len(predictions) - tp) / hours,
        "matches": [
            {"truth": j, "prediction": i, "onset_error_seconds": predictions[i]["start"] - truth[j]["start"]}
            for j, i in sorted(assigned.items())
        ],
        "protocol": "actor-mapped interval IoU maximum-cardinality matching; signed onset error",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    args.output.write_text(
        json.dumps({"scope": data.pop("scope", "provided annotations"), **evaluate(**data)}, indent=2)
    )
