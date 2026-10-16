import datetime as dt
import hashlib
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from sentinel.capabilities import Calibration, explicit_ppe, fit, project
from sentinel.config import settings
from sentinel.control import active_model
from sentinel.db import CleanupTask, Job, Record, Session, User, now
from sentinel.lifecycle import delete_video, drain_cleanup, retention, sweep_orphans
from sentinel.rules import Track


def module(path):
    spec = importlib.util.spec_from_file_location("subject", Path(__file__).parents[1] / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_preferences_rule_revision_and_retention(client, headers):
    assert (
        client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"retention_days": 2, "confidence": 0.4, "sample_every": 2},
        ).status_code
        == 200
    )
    with Session() as db:
        db.add(
            Record(
                id="old",
                tenant="a",
                kind="video",
                created=now() - dt.timedelta(days=3),
                body={"path": str(settings.data_dir / "videos/old.avi")},
            )
        )
        db.add(
            Record(
                id="new",
                tenant="b",
                kind="video",
                created=now() - dt.timedelta(days=3),
                body={"path": str(settings.data_dir / "videos/new.avi")},
            )
        )
        db.commit()
    assert retention() == 1
    with Session() as db:
        assert db.get(Record, "new") is not None
    zone = client.post(
        "/api/v1/zones", headers=headers, json={"name": "area", "points": [[0, 0], [1, 0], [1, 1]]}
    ).json()
    body = {"name": "dwell", "kind": "dwell", "zone_id": zone["id"], "threshold": 3}
    rule = client.post("/api/v1/rules", headers=headers, json=body).json()
    changed = client.put("/api/v1/rules/" + rule["id"], headers=headers, json={**body, "threshold": 5})
    assert changed.json()["version"] == 2 and changed.json()["threshold"] == 5


def test_account_disable_reset_and_change(client, headers):
    new = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "new@test.local", "password": "long-password-123", "role": "operator"},
    ).json()

    def login(password):
        return client.post("/api/v1/auth/login", json={"email": "new@test.local", "password": password})

    token = login("long-password-123").json()["token"]
    assert (
        client.put(
            "/api/v1/users/" + new["id"] + "/access",
            headers=headers,
            json={"enabled": False, "role": "viewer"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/events", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert login("long-password-123").status_code == 401
    client.put(
        "/api/v1/users/" + new["id"] + "/access", headers=headers, json={"enabled": True, "role": "operator"}
    )
    assert (
        client.post(
            "/api/v1/users/" + new["id"] + "/reset-password",
            headers=headers,
            json={"new_password": "replacement-123456"},
        ).status_code
        == 200
    )
    assert login("long-password-123").status_code == 401
    token = login("replacement-123456").json()["token"]
    h = {"Authorization": "Bearer " + token}
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=h,
            json={"current_password": "replacement-123456", "new_password": "final-password-123"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/events", headers=h).status_code == 401
    assert login("final-password-123").status_code == 200


def test_registry_hash_promotion_and_rollback(client, headers):
    folder = settings.data_dir / "models"
    folder.mkdir(exist_ok=True)
    path = folder / "fixture.onnx"
    path.write_bytes(b"fixture registry bytes, never inference weights")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = client.post(
        "/api/v1/experiments",
        headers=headers,
        json={
            "run_id": "fixture",
            "scope": "operator attested held-out evaluation",
            "model_sha256": digest,
            "dataset_sha256": "a" * 64,
            "held_out": True,
            "metrics": {"fixture": 1},
            "annotation_provenance": "synthetic fixtures for registry test",
        },
    ).json()
    model = client.post(
        "/api/v1/registry",
        headers=headers,
        json={"filename": "fixture.onnx", "name": "registry fixture", "report_id": report["id"]},
    ).json()
    assert (
        client.post(
            "/api/v1/registry/" + model["id"] + "/promote",
            headers=headers,
            json={"reason": "unit test contract only"},
        ).status_code
        == 200
    )
    with Session() as db:
        assert active_model(db, "a") == str(path)
    path.write_bytes(b"changed")
    with Session() as db:
        with pytest.raises(HTTPException):
            active_model(db, "a")
    assert client.post("/api/v1/registry/reset-baseline", headers=headers).status_code == 200
    with Session() as db:
        assert active_model(db, "a") == settings.model


def test_durable_cleanup_retries(client, monkeypatch):
    from sentinel import storage

    path = settings.data_dir / "videos/delete.avi"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"evidence")
    with Session() as db:
        db.add(Record(id="delete", tenant="a", kind="video", body={"path": str(path)}))
        db.commit()
    erase = storage.erase
    monkeypatch.setattr(storage, "erase", lambda _: (_ for _ in ()).throw(OSError("unavailable")))
    assert delete_video("delete", "a", "test")
    with Session() as db:
        assert db.get(Record, "delete") is None
        assert db.query(CleanupTask).one().attempts == 1
    monkeypatch.setattr(storage, "erase", erase)
    assert drain_cleanup() == 1 and not path.exists()


def test_orphan_sweep_preserves_live_artifacts(client):
    import os

    orphan = settings.data_dir / "evidence/orphan/old.jpg"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x")
    kept = settings.data_dir / "evidence/kept/old.jpg"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"x")
    for p in (orphan, kept):
        os.utime(p, (0, 0))
    with Session() as db:
        db.add(Job(id="kept", tenant="a", video_id="v", config={}))
        db.commit()
    assert sweep_orphans() == 1
    assert not orphan.exists() and kept.exists()


def test_camera_scheduler_concurrency_and_stop(client, headers):
    from sentinel.maintenance import schedule_cameras

    with Session() as db:
        user = db.query(User).filter_by(tenant="a").one()
        db.add(
            Record(
                id="cam",
                tenant="a",
                kind="camera",
                body={
                    "name": "fixture",
                    "encrypted_source": "fixture",
                    "operator_id": user.id,
                    "monitor": {"enabled": True, "segment_seconds": 5, "rule_ids": []},
                },
            )
        )
        db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: schedule_cameras(), range(4))) == 1
    with Session() as db:
        job = db.query(Job).one()
        job.state = "completed"
        db.commit()
    assert schedule_cameras() == 1
    assert (
        client.put("/api/v1/cameras/cam/monitor", headers=headers, json={"enabled": False}).status_code == 200
    )
    assert schedule_cameras() == 0
    with Session() as db:
        assert not db.query(Job).filter(Job.state.in_(["queued", "running"])).count()


def test_calibration_and_explicit_ppe():
    body = Calibration(
        camera_id="c",
        image_points=[(0, 0), (1, 0), (1, 1), (0, 1)],
        world_points=[(0, 0), (10, 0), (10, 10), (0, 10)],
        check_image_points=[(0.2, 0.3), (0.6, 0.7)],
        check_world_points=[(2, 3), (6, 7)],
        max_error_meters=0.01,
        scope="synthetic fixture",
    )
    calibrated = fit(body)
    assert project(calibrated["matrix"], (0.5, 0.5)) == pytest.approx([5, 5])
    with pytest.raises(ValueError):
        fit(body.model_copy(update={"check_world_points": [(9, 9), (9, 9)]}))
    person = Track(1, "person", 0.9, (0.1, 0.1, 0.5, 0.9))
    assert explicit_ppe(person, []) == []
    assert explicit_ppe(person, [Track(2, "no_helmet", 0.9, (0.2, 0.15, 0.3, 0.25))])
    assert not explicit_ppe(person, [Track(3, "no_helmet", 0.9, (0.8, 0.8, 0.9, 0.9))])


def test_actor_interval_matching():
    evaluate = module("ml/evaluation/intervals.py").evaluate
    base = {"video_id": "v", "rule_id": "r", "actor_id": "a", "start": 0, "end": 5}
    report = evaluate([base, base, {**base, "actor_id": "b"}], [base, {**base, "actor_id": "b"}], 1)
    assert (report["tp"], report["fp"], report["fn"]) == (2, 1, 0)
    assert evaluate([{**base, "actor_id": "wrong"}], [base], 1)["tp"] == 0


def test_audit_tamper_detection(client, headers, tmp_path):
    from sentinel.audit import export_manifest, verify_manifest

    client.put("/api/v1/preferences", headers=headers, json={"retention_days": 3})
    manifest = tmp_path / "manifest.json"
    export_manifest(manifest)
    assert verify_manifest(manifest) >= 1
    name = next(iter(json.loads(manifest.read_text())["files"]))
    (settings.data_dir / "audit-sealed" / name).write_text("{}")
    with pytest.raises(ValueError):
        verify_manifest(manifest)


def test_paginated_contract_and_cross_tenant(client, headers):
    for i in range(5):
        client.post(
            "/api/v1/zones", headers=headers, json={"name": str(i), "points": [[0, 0], [1, 0], [1, 1]]}
        )
    first = client.get("/api/v1/zones?limit=2", headers=headers).json()
    second = client.get("/api/v1/zones?limit=2&offset=2", headers=headers).json()
    assert len(first) == len(second) == 2 and not {x["id"] for x in first} & {x["id"] for x in second}
    other = client.post(
        "/api/v1/auth/login", json={"email": "b@test.local", "password": "test-password-long"}
    ).json()["token"]
    h = {"Authorization": "Bearer " + other}
    assert client.put("/api/v1/preferences", headers=h, json={"retention_days": 1}).status_code == 403
    assert client.get("/api/v1/zones", headers=h).json() == []


def test_supervisor_restarts_child(tmp_path):
    marker = tmp_path / "starts.txt"
    command = [
        sys.executable,
        "-c",
        f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x')",
    ]
    with (tmp_path / "service.log").open("w") as log:
        assert module("scripts/supervise.py").supervise(command, lambda: False, log, max_restarts=1) == 1
    assert marker.read_text() == "xx"


def test_backup_restore_integrity(client, tmp_path):
    import sqlite3

    backup = module("scripts/backup.py")
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "sentinel.db") as db:
        db.executescript(
            "create table jobs(id text,state text,config text);create table records(id text,body text);create table auth_sessions(revoked integer);"
        )
        db.execute("insert into records values (?,?)", ("v", json.dumps({"path": str(source / "videos/v")})))
    (source / "videos").mkdir()
    (source / "videos/v").write_bytes(b"footage")
    assert backup.snapshot(source, tmp_path / "snapshot") == 2
    assert backup.restore(tmp_path / "snapshot", tmp_path / "restored") == 2
    assert (tmp_path / "restored/videos/v").read_bytes() == b"footage"
    with sqlite3.connect(tmp_path / "restored/sentinel.db") as db:
        assert (
            str(tmp_path / "restored")
            in json.loads(db.execute("select body from records").fetchone()[0])["path"]
        )


def test_source_pts_and_variable_rate_playback(tmp_path):
    import av
    import numpy as np
    from sentinel.media import TimestampWriter
    from sentinel.sources import PTSReader

    path = tmp_path / "variable.mp4"
    writer = TimestampWriter(path, 32, 32)
    for stamp in (10, 10.1, 10.5, 11.2):
        writer.write(np.zeros((32, 32, 3), np.uint8), stamp)
    writer.close()
    reader = PTSReader(str(path))
    stamps = []
    while reader.read()[0]:
        stamps.append(reader.pts)
    reader.release()
    assert stamps == pytest.approx([0, 0.1, 0.5, 1.2], abs=0.002)
    with av.open(str(path)) as container:
        assert len(list(container.decode(video=0))) == 4


def test_metric_and_ppe_rule_integration():
    from sentinel.rules import RuleEngine
    from sentinel.schemas import Rule

    person = Track(1, "person", 0.9, (0.1, 0.1, 0.3, 0.5))
    vehicle = Track(2, "forklift", 0.8, (0.3, 0.2, 0.5, 0.5))
    rule = {
        **Rule(
            name="distance", kind="proximity", calibration_id="c", threshold=1, persistence=0
        ).model_dump(),
        "id": "r",
    }
    engine = RuleEngine([rule], {}, calibrations={"c": {"matrix": [[10, 0, 0], [0, 10, 0], [0, 0, 1]]}})
    # Two meters apart: the old normalized-image threshold would incorrectly trigger.
    assert not engine.step(0, [person, vehicle])
    vehicle.box = (0.15, 0.2, 0.35, 0.5)
    events = engine.step(1, [person, vehicle])
    assert len(events) == 1 and "meters" in events[0]["reason"]
    ppe = {**Rule(name="helmet", kind="ppe", persistence=0).model_dump(), "id": "p"}
    engine = RuleEngine([ppe], {})
    assert not engine.step(0, [person])
    assert len(engine.step(1, [person, Track(3, "no_helmet", 0.7, (0.15, 0.12, 0.25, 0.2))])) == 1


def test_operations_contracts_and_nonproduction_promotion(client, headers):
    from sentinel.control import key

    with Session() as db:
        db.add(CleanupTask(tenant="a", keys=[], prefixes=[], error="OSError"))
        db.add(CleanupTask(tenant="b", keys=[], prefixes=[]))
        for scope in ("smoke", "synthetic", "demo", "fixture"):
            db.add(Record(id=scope, tenant="a", kind="model_version", body={"scope": scope}))
        db.commit()
    assert client.get("/api/v1/system", headers=headers).json()["pending_cleanup"] == 1
    assert len(client.get("/api/v1/cleanup", headers=headers).json()) == 1
    for scope in ("smoke", "synthetic", "demo", "fixture"):
        assert (
            client.post(
                f"/api/v1/registry/{scope}/promote",
                headers=headers,
                json={"reason": "must reject nonproduction evidence"},
            ).status_code
            == 422
        )
    with Session() as db:
        assert db.get(Record, key("active_model", "a")) is None


def test_every_json_operation_has_response_contract(client):
    schema = client.get("/openapi.json").json()
    media = ("/content", "/evidence", "/preview", "/playback", "/clip", "/updates")
    for path, methods in schema["paths"].items():
        if path.endswith(media):
            continue
        for operation in methods.values():
            for status, response in operation["responses"].items():
                if status.startswith("2"):
                    assert response["content"]["application/json"]["schema"], path


def test_monitor_stop_conflicts_with_inflight_scheduler(client, headers):
    from sentinel.maintenance import acquire, release

    token = acquire("camera:locked")
    assert token
    try:
        assert (
            client.put("/api/v1/cameras/locked/monitor", headers=headers, json={"enabled": False}).status_code
            == 409
        )
    finally:
        release("camera:locked", token)


def test_calibration_rejects_reused_check_points():
    with pytest.raises(ValueError, match="independent"):
        Calibration(
            camera_id="c",
            image_points=[(0, 0), (1, 0), (1, 1), (0, 1)],
            world_points=[(0, 0), (10, 0), (10, 10), (0, 10)],
            check_image_points=[(0, 0), (0.5, 0.5)],
            check_world_points=[(0, 0), (5, 5)],
            max_error_meters=0.1,
            scope="reused fixture",
        )
