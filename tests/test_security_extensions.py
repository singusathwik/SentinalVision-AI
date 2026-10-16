import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sentinel.auth import rate_limit
from sentinel.config import settings
from sentinel.db import Job, Record, Session, now
from sentinel.worker import claim, fenced


def test_logout_revokes(client, headers):
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/events", headers=headers).status_code == 401


def test_experiment_report_is_scoped(client, headers):
    import json

    report = settings.data_dir / "training" / "validation.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps({"run_id": "smoke-fixture", "smoke_only": True, "metrics": {"test": 1}}))
    response = client.post("/api/v1/experiments/publish-local", headers=headers)
    assert response.status_code == 200 and "smoke" in response.json()["scope"]
    other = client.post(
        "/api/v1/auth/login", json={"email": "b@test.local", "password": "test-password-long"}
    ).json()["token"]
    assert client.get("/api/v1/experiments", headers={"Authorization": "Bearer " + other}).json() == []


def test_retry_and_outbox_recovery(client, headers, monkeypatch):
    from sentinel.db import Dispatch
    from sentinel.tasks import dispatch_pending, process

    with Session() as db:
        db.add(Job(id="retry", tenant="a", video_id="v", config={}, state="failed", attempts=3))
        db.commit()
    response = client.post("/api/v1/jobs/retry/retry", headers=headers)
    assert response.status_code == 200 and response.json()["attempts"] == 0
    assert client.post("/api/v1/jobs/retry/retry", headers=headers).status_code == 409

    def broken(**kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(process, "apply_async", broken)
    assert dispatch_pending() == 0
    with Session() as db:
        assert db.get(Dispatch, "retry").sent == 0
        assert db.get(Dispatch, "retry").attempts == 1
    sent = []
    monkeypatch.setattr(process, "apply_async", lambda **kw: sent.append(kw))
    assert dispatch_pending() == 1
    claim("retry")
    with Session() as db:
        db.get(Job, "retry").lease = now() - dt.timedelta(seconds=1)
        db.commit()
    assert dispatch_pending() == 1
    assert len(sent) == 2


def test_chunked_limit_never_calls_parser():
    import asyncio

    from sentinel.security import RequestBoundary

    messages = iter([{"type": "http.request", "body": b"x" * 40000, "more_body": True}] * 2)
    output = []

    async def receive():
        return next(messages)

    async def send(message):
        output.append(message)

    async def parser(*args):
        raise AssertionError("Oversize body reached parser")

    asyncio.run(
        RequestBoundary(parser)(
            {"type": "http", "headers": [], "path": "/api/v1/zones", "method": "POST"}, receive, send
        )
    )
    assert output[0]["status"] == 413


def test_body_limit_before_parse(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert client.post("/api/v1/videos/upload", headers=headers, content=b"x" * 70000).status_code == 413
    assert client.post("/api/v1/zones", headers=headers, content=b"x" * 70000).status_code == 413


def test_shared_rate_limit_concurrency(client):
    def request(_):
        try:
            rate_limit("shared", 4)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(request, range(12)))
    assert responses.count(200) == 4
    assert responses.count(429) == 8


def test_lease_fencing(client):
    with Session() as db:
        db.add(Job(id="fenced", tenant="a", video_id="v", config={}))
        db.commit()
    first = claim()
    with Session() as db:
        job = db.get(Job, "fenced")
        job.lease = now() - dt.timedelta(seconds=1)
        db.commit()
    second = claim()
    assert first == second and first.token != second.token
    with Session() as db:
        assert not fenced(db, first, first.token, progress=0.5)
        assert fenced(db, second, second.token, progress=0.2)
        db.commit()


def test_race_safe_job_creation(client, headers):
    with Session() as db:
        db.add(Record(id="v", tenant="a", kind="video", body={"path": "unused"}))
        db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: client.post("/api/v1/jobs", headers=headers, json={"video_id": "v"}), range(8))
        )
    assert all(r.status_code == 201 for r in results)
    assert len({r.json()["id"] for r in results}) == 1


def test_camera_encryption_and_ssrf(client, headers, monkeypatch):
    from sentinel.cameras import open_source

    monkeypatch.setattr(settings, "rtsp_hosts", "127.0.0.1")
    monkeypatch.setattr(settings, "rtsp_allowed_ips", "127.0.0.1")
    url = "rtsp://alice:private-password@127.0.0.1:8554/test"
    body = {"name": "fixture", "url": url, "authorized": True}
    assert client.post("/api/v1/cameras", headers=headers, json=body).status_code == 422
    monkeypatch.setattr(settings, "allow_loopback_camera_fixture", True)
    response = client.post("/api/v1/cameras", headers=headers, json=body)
    assert response.status_code == 201
    assert "private-password" not in response.text and "encrypted_source" not in response.text
    with Session() as db:
        encrypted = db.get(Record, response.json()["id"]).body["encrypted_source"]
    assert "private-password" not in encrypted
    assert open_source(encrypted) == url
    monkeypatch.setattr(settings, "rtsp_allowed_ips", "10.0.0.5")
    with pytest.raises(ValueError):
        open_source(encrypted)


def test_s3_storage_roundtrip(client, monkeypatch, tmp_path):
    from moto import mock_aws
    from sentinel import storage

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(settings, "storage", "s3")
    with mock_aws():
        storage.client().create_bucket(Bucket=settings.s3_bucket)
        path = storage.local_path("evidence/test.jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        key = storage.publish(path)
        path.unlink()
        assert storage.materialize(key).read_bytes() == b"fixture"
        assert "test.jpg" in storage.signed_url(key)
        storage.erase(key)
        assert not path.exists()


def test_storage_traversal():
    from sentinel.storage import local_path

    with pytest.raises(ValueError):
        local_path("../private")


def test_retention_skips_active_jobs(client, headers):
    from sentinel.lifecycle import retention
    from sentinel.storage import local_path

    old = now() - dt.timedelta(days=10)
    with Session() as db:
        for identity in ("old", "active"):
            path = local_path(f"videos/{identity}.avi")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test")
            db.add(Record(id=identity, tenant="a", kind="video", created=old, body={"path": str(path)}))
        db.add(Job(tenant="a", video_id="active", config={}, state="queued"))
        db.commit()
    assert retention() == 1
    assert not local_path("videos/old.avi").exists()
    assert local_path("videos/active.avi").exists()


def test_user_provisioning_role(client, headers):
    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "viewer@local", "password": "a-long-password", "role": "viewer"},
    )
    assert response.status_code == 201
    token = client.post(
        "/api/v1/auth/login", json={"email": "viewer@local", "password": "a-long-password"}
    ).json()["token"]
    assert client.get("/api/v1/users", headers={"Authorization": "Bearer " + token}).status_code == 403
