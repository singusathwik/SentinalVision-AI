"""Execute real HTTP upload -> separate worker -> event -> evidence -> review.

Downloads the public Ultralytics bus sample. This is a static-image video test,
not an industrial dataset or an accuracy/tracking benchmark.
"""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

import cv2
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--email", default="admin@sentinel.local")
parser.add_argument("--api", default="http://127.0.0.1:8010/api/v1")
args = parser.parse_args()
password = os.environ.get("SENTINEL_DEMO_PASSWORD")
if not password:
    import getpass

    password = getpass.getpass("Password: ")
root = Path("data/demo")
root.mkdir(parents=True, exist_ok=True)
image = root / "bus.jpg"
if not image.exists():
    urllib.request.urlretrieve("https://ultralytics.com/images/bus.jpg", image)
frame = cv2.imread(str(image))
if frame is None:
    raise SystemExit("Sample download failed")
frame = cv2.resize(frame, (480, 640))
video = root / "static-bus-test.avi"
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (480, 640))
for _ in range(30):
    writer.write(frame)
writer.release()
with httpx.Client(base_url=args.api, timeout=60) as client:

    def post(path, **kwargs):
        r = client.post(path, **kwargs)
        r.raise_for_status()
        return r.json()

    token = post("/auth/login", json={"email": args.email, "password": password})["token"]
    client.headers["Authorization"] = "Bearer " + token
    zone = post("/zones", json={"name": "DEMO full frame", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]})
    rule = post(
        "/rules",
        json={
            "name": "DEMO person intrusion",
            "kind": "intrusion",
            "zone_id": zone["id"],
            "persistence": 0.3,
        },
    )
    with video.open("rb") as stream:
        uploaded = post("/videos/upload", files={"file": (video.name, stream, "video/x-msvideo")})
    job = post("/jobs", json={"video_id": uploaded["id"], "rule_ids": [rule["id"]]})
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = client.get("/jobs/" + job["id"]).json()
        if job["state"] in ("completed", "failed", "canceled"):
            break
        time.sleep(2)
    if job["state"] != "completed":
        raise SystemExit(json.dumps(job))
    events = [e for e in client.get("/events").json() if e["job_id"] == job["id"]]
    if not events:
        raise SystemExit("Real model produced no events; acceptance not established")
    evidence = client.get(f"/events/{events[0]['id']}/evidence")
    evidence.raise_for_status()
    (root / "verified-evidence.jpg").write_bytes(evidence.content)
    post(
        f"/events/{events[0]['id']}/review",
        json={"status": "confirmed", "note": "Synthetic static-image pipeline verification only"},
    )
    report = {
        "job": job,
        "events": len(events),
        "evidence_bytes": len(evidence.content),
        "review": "confirmed",
        "fixture": "static public bus image repeated 30 frames; not benchmark ground truth",
    }
    (root / "verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
