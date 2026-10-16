"""Execute both actual trackers and verify isolation on a repeated public image."""

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from sentinel.inference import YOLOSession  # noqa: E402

frame = cv2.imread("data/demo/bus.jpg")
report = {}
for tracker in ("bytetrack", "botsort"):
    sessions = [YOLOSession("yolo11n.pt", tracker, 0.25, "cpu") for _ in range(2)]
    identities = []
    for session in sessions:
        sequence = []
        for _ in range(5):
            tracks, _, _ = session.infer(frame)
            sequence.append(sorted(t.id for t in tracks))
        assert sequence[0] and all(ids == sequence[0] for ids in sequence)
        identities.append(sequence)
    assert identities[0] == identities[1]
    report[tracker] = {
        "isolated_sessions": 2,
        "stable_ids_on_static_fixture": identities[0][0],
        "frames_each": 5,
    }
Path("data/demo/tracker-smoke.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
