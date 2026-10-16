"""Execute research CLIs on explicitly synthetic fixtures; not research findings."""

import json
import subprocess
import sys
from pathlib import Path

folder = Path("data/research-fixtures")
folder.mkdir(parents=True, exist_ok=True)
scope = "Synthetic trajectories only; tool verification, not industrial performance or statistical evidence"
track = {"id": 1, "label": "person", "confidence": 0.8, "box": [0.2, 0.1, 0.5, 0.5]}
rule = {
    "id": "r",
    "name": "fixture",
    "kind": "intrusion",
    "zone_id": "z",
    "classes": ["person"],
    "persistence": 0,
    "cooldown": 10,
    "threshold": 1,
    "severity": "warning",
}
frames = [
    {"timestamp": i / 10, "width": 100, "height": 200, "tracks": [track] if i < 15 else []} for i in range(30)
]
(folder / "replay.json").write_text(
    json.dumps(
        {"scope": scope, "rules": [rule], "zones": {"z": [[0, 0], [1, 0], [1, 1], [0, 1]]}, "frames": frames}
    )
)
(folder / "tracks.jsonl").write_text("\n".join(json.dumps(f) for f in frames))
(folder / "events.json").write_text(
    json.dumps(
        {
            "scope": scope,
            "video_hours": {"synthetic-a": 1, "synthetic-b": 1},
            "predictions": [{"video_id": "synthetic-a", "rule_id": "r", "timestamp": 1.5}],
            "truth": [{"video_id": "synthetic-a", "rule_id": "r", "timestamp": 1}],
        }
    )
)
for args in [
    [
        "ml/evaluation/ablation.py",
        str(folder / "replay.json"),
        "--output",
        "docs/results/synthetic-ablations.json",
    ],
    [
        "ml/evaluation/uncertainty.py",
        str(folder / "events.json"),
        "--output",
        "docs/results/synthetic-uncertainty.json",
    ],
    [
        "ml/evaluation/mot_export.py",
        str(folder / "tracks.jsonl"),
        "docs/results/synthetic-mot.txt",
        "--fps",
        "10",
    ],
]:
    subprocess.run([sys.executable, *args], check=True)
assert len(json.loads(Path("docs/results/synthetic-ablations.json").read_text())["ablations"]) == 32
assert len(Path("docs/results/synthetic-mot.txt").read_text().splitlines()) == 15
print("Passed: 32 replay configurations, video bootstrap CLI, 15 MOT rows. Synthetic verification only.")
