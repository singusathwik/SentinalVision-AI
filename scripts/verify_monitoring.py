"""Exercise two real RTSP segments and stop; needs loopback fixture/API on 8012.

Run with the same data directory/database as the fixture API, and no general worker.
"""

import json
import os
import sys
from pathlib import Path

import httpx

os.environ["SENTINEL_RTSP_HOSTS"] = "127.0.0.1"
os.environ["SENTINEL_RTSP_ALLOWED_IPS"] = "127.0.0.1"
os.environ["SENTINEL_ALLOW_LOOPBACK_CAMERA_FIXTURE"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from sentinel.maintenance import schedule_cameras  # noqa: E402
from sentinel.worker import claim, process_job  # noqa: E402

credentials = json.loads(Path("data/local-login.json").read_text())
with httpx.Client(base_url="http://127.0.0.1:8012/api/v1", timeout=60) as client:
    login = client.post("/auth/login", json=credentials)
    login.raise_for_status()
    client.headers["Authorization"] = "Bearer " + login.json()["token"]
    camera = client.post(
        "/cameras",
        json={
            "name": "DEMO monitoring verification",
            "url": "rtsp://127.0.0.1:8554/fixture",
            "authorized": True,
        },
    )
    camera.raise_for_status()
    identity = camera.json()["id"]
    endpoint = f"/cameras/{identity}/monitor"
    client.put(endpoint, json={"enabled": True, "segment_seconds": 5}).raise_for_status()
    segments = []
    try:
        for _ in range(2):
            assert schedule_cameras() >= 1
            job = next(j for j in client.get("/jobs").json() if j["config"].get("camera_id") == identity)
            claimed = claim(job["id"])
            assert claimed
            process_job(claimed)
            result = client.get("/jobs/" + job["id"]).json()
            assert result["state"] == "completed", result["state"]
            playback = client.get(f"/jobs/{job['id']}/playback")
            assert playback.status_code == 200 and len(playback.content) > 1000
            segments.append(
                {"job_id": job["id"], "state": result["state"], "playback_bytes": len(playback.content)}
            )
    finally:
        client.put(endpoint, json={"enabled": False}).raise_for_status()
    schedule_cameras()
    jobs = [j for j in client.get("/jobs").json() if j["config"].get("camera_id") == identity]
    assert len(jobs) == 2 and not any(j["state"] in ("running", "queued") for j in jobs)
    report = {
        "segments": segments,
        "stop_verified": True,
        "scope": "localhost RTSP CPU fixture; segmented monitoring, not gapless capture or cross-segment tracking",
    }
    Path("docs/results/continuous-monitoring.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
