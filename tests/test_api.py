import cv2
import numpy as np
from sentinel.db import Job, Record, Session
from sentinel.worker import claim


def test_auth_required(client):
    assert client.get("/api/v1/events").status_code == 401
    assert client.get("/api/v1/health").status_code == 200


def test_upload_rejects_corruption_and_traversal(client, headers):
    assert (
        client.post(
            "/api/v1/videos/upload", headers=headers, files={"file": ("../../bad.py", b"bad")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/videos/upload", headers=headers, files={"file": ("../../bad.mp4", b"bad")}
        ).status_code
        == 422
    )


def test_tenant_and_role(client, headers):
    z = client.post(
        "/api/v1/zones", headers=headers, json={"name": "z", "points": [[0, 0], [1, 0], [1, 1]]}
    ).json()
    other = client.post(
        "/api/v1/auth/login", json={"email": "b@test.local", "password": "test-password-long"}
    ).json()["token"]
    h = {"Authorization": "Bearer " + other}
    assert client.get("/api/v1/zones", headers=h).json() == []
    assert (
        client.post(
            "/api/v1/rules", headers=h, json={"name": "x", "kind": "intrusion", "zone_id": z["id"]}
        ).status_code
        == 403
    )
    with Session() as db:
        db.add(
            Record(
                id="private",
                tenant="a",
                kind="event",
                body={"status": "needs_review", "evidence_path": "secret"},
            )
        )
        db.commit()
    assert client.get("/api/v1/events/private/evidence", headers=h).status_code == 404


def test_ssrf_and_ppe(client, headers):
    assert (
        client.post(
            "/api/v1/cameras",
            headers=headers,
            json={"name": "bad", "url": "http://169.254.169.254/", "authorized": True},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/cameras",
            headers=headers,
            json={"name": "bad", "url": "rtsp://localhost/", "authorized": True},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/rules", headers=headers, json={"name": "bad", "kind": "proximity"}).status_code
        == 422
    )


def test_upload_queue_cancel_and_idempotence(client, headers, tmp_path):
    path = tmp_path / "fixture.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
    for _ in range(10):
        writer.write(np.zeros((64, 64, 3), np.uint8))
    writer.release()
    r = client.post(
        "/api/v1/videos/upload", headers=headers, files={"file": ("fixture.avi", path.read_bytes())}
    )
    assert r.status_code == 201
    body = {"video_id": r.json()["id"]}
    j = client.post("/api/v1/jobs", headers=headers, json=body).json()
    assert client.post("/api/v1/jobs", headers=headers, json=body).json()["id"] == j["id"]
    assert claim() == j["id"]
    assert claim() is None
    assert client.post(f"/api/v1/jobs/{j['id']}/cancel", headers=headers).json()["state"] == "canceled"


def test_review_audit(client, headers):
    with Session() as db:
        db.add(Record(id="event", tenant="a", kind="event", body={"status": "needs_review"}))
        db.commit()
    assert (
        client.post("/api/v1/events/event/review", headers=headers, json={"status": "confirmed"}).status_code
        == 200
    )
    assert client.get("/api/v1/audit", headers=headers).json()[0]["previous"] == "needs_review"


def test_expired_lease_recovery(client):
    import datetime as dt

    from sentinel.db import now

    with Session() as db:
        db.add(
            Job(
                id="retry",
                tenant="a",
                video_id="v",
                state="running",
                config={},
                attempts=1,
                lease=now() - dt.timedelta(seconds=1),
            )
        )
        db.commit()
    assert claim() == "retry"
