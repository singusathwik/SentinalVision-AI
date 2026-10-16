"""Execute API camera registration + real RTSP/YOLO processing against loopback fixture.

Start MediaMTX, FFmpeg fixture publisher and API port 8012 first. Pause general worker.
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
from sentinel.worker import claim, process_job  # noqa: E402

credentials = json.loads(Path("data/local-login.json").read_text())
with httpx.Client(base_url="http://127.0.0.1:8012/api/v1", timeout=60) as c:
    login = c.post("/auth/login", json=credentials)
    login.raise_for_status()
    c.headers["Authorization"] = "Bearer " + login.json()["token"]
    camera = c.post(
        "/cameras",
        json={
            "name": "DEMO loopback RTSP fixture",
            "url": "rtsp://127.0.0.1:8554/fixture",
            "authorized": True,
        },
    )
    camera.raise_for_status()
    rules = c.get("/rules").json()
    job = c.post(
        "/jobs", json={"camera_id": camera.json()["id"], "capture_seconds": 12, "rule_ids": [rules[-1]["id"]]}
    )
    job.raise_for_status()
    identity = job.json()["id"]
    claimed = claim(identity)
    assert claimed
    process_job(claimed)
    result = c.get("/jobs/" + identity).json()
    assert result["state"] == "completed", result
    telemetry = c.get(f"/jobs/{identity}/telemetry").json()
    assert c.get(f"/jobs/{identity}/preview").status_code == 200
    playback = c.get(f"/jobs/{identity}/playback")
    assert playback.status_code == 200 and len(playback.content) > 1000
    report = {
        "job_id": identity,
        "status": result["state"],
        "preview": True,
        "playback_bytes": len(playback.content),
        "telemetry": telemetry,
        "scope": "real localhost RTSP decoder + pretrained model on repeated public image; no physical camera validation",
    }
    Path("docs/results/rtsp-integration.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
