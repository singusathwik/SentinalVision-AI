import datetime as dt
import hashlib
import json
import logging
import os
import socket
import time
import uuid
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from . import storage
from .annotation import draw_tracks
from .cameras import open_source
from .config import settings
from .db import Job, Lease, Record, Session, init_db, now, uid
from .inference import YOLOSession
from .media import TimestampWriter, encode_playback, event_clip
from .rules import RuleEngine
from .sources import LiveSource

log = logging.getLogger("sentinel.worker")


class Claim(str):
    token: str


def claim(identity: str | None = None) -> Claim | None:
    with Session() as db:
        db.execute(
            update(Job)
            .where(Job.state == "running", Job.lease < now(), Job.attempts < 3)
            .values(state="queued")
        )
        db.execute(
            update(Job)
            .where(Job.state == "running", Job.lease < now(), Job.attempts >= 3)
            .values(state="failed", error="Worker lease expired after three attempts")
        )
        query = select(Job).where(Job.state == "queued").order_by(Job.created)
        if identity:
            query = query.where(Job.id == identity)
        j = db.scalar(query.limit(1))
        if not j:
            db.commit()
            return None
        result = db.execute(
            update(Job)
            .where(Job.id == j.id, Job.state == "queued")
            .values(
                state="running",
                attempts=Job.attempts + 1,
                lease=now() + dt.timedelta(seconds=settings.lease_seconds),
            )
        )
        if not cast(CursorResult, result).rowcount:
            db.rollback()
            return None
        token = uid()
        db.merge(Lease(id=j.id, token=token))
        db.commit()
        result_id = Claim(j.id)
        result_id.token = token
        return result_id


def fenced(db, identity: str, token: str, **values) -> bool:
    owns = select(Lease.id).where(Lease.id == identity, Lease.token == token).exists()
    result = db.execute(
        update(Job)
        .where(Job.id == identity, Job.state == "running", Job.lease > now(), owns)
        .values(**values)
    )
    return bool(cast(CursorResult, result).rowcount)


def heartbeat(state: str, job_id: str | None = None):
    with Session() as db:
        db.merge(
            Record(
                id="worker-"
                + uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname() + str(os.getpid())).hex[:24],
                tenant="__system",
                kind="worker",
                body={"state": state, "job_id": job_id, "heartbeat": now().isoformat()},
            )
        )
        db.commit()


def process_job(identity: str) -> None:
    cap = None
    live = None
    writer = None
    raw_writer = None
    pts_writer = None
    token = getattr(identity, "token", "")
    try:
        with Session() as db:
            j = db.get(Job, identity)
            if not j or j.state != "running":
                return
            # Legacy direct invocation is allowed only for a job without a lease (unit failure path).
            lease = db.get(Lease, identity)
            if lease and lease.token != token:
                return
            video = db.get(Record, j.video_id)
            if not video:
                raise ValueError("Source video missing")
            path, tenant, config = video.body["path"], j.tenant, j.config
            encrypted = None
            if config.get("camera_id"):
                camera = db.get(Record, config["camera_id"])
                if not camera or camera.tenant != tenant:
                    raise ValueError("Camera missing")
                encrypted = camera.body["encrypted_source"]
            elif video.body.get("storage_key"):
                path = str(storage.materialize(video.body["storage_key"]))
        if (
            config.get("model_sha256")
            and hashlib.sha256(Path(config["model"]).read_bytes()).hexdigest() != config["model_sha256"]
        ):
            raise ValueError("Model artifact changed after submission")
        detector = YOLOSession(config["model"], config["tracker"], config["confidence"], settings.device)
        rules = RuleEngine(
            config["rules"],
            config["zones"],
            max_gap=2 if encrypted else None,
            calibrations=config.get("calibrations", {}),
        )
        output = storage.local_path(f"evidence/{identity}/{token or 'legacy'}")
        output.mkdir(parents=True, exist_ok=True)
        if encrypted:
            live = LiveSource(open_source(encrypted), config["capture_seconds"])
            frames = iter(live)
            fps, total = 10.0, 0
        else:
            cap = cv2.VideoCapture(path)
            fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if not cap.isOpened() or fps <= 0:
                raise ValueError("Video decoder failed")

            def file_frames():
                frame_no = 0
                previous = -1.0
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        return
                    pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                    timestamp = pts if pts > previous else frame_no / fps
                    if timestamp <= previous:
                        timestamp = previous + 1 / fps
                    previous = timestamp
                    yield timestamp, frame
                    frame_no += 1

            frames = file_frames()
        latencies, speeds, timestamps = [], [], []
        n, processed = 0, 0
        event_ids = []
        playback = output / "annotated.mp4"
        with (output / "trajectories.jsonl").open("w") as trajectory:
            for timestamp, frame in frames:
                n += 1
                with Session() as db:
                    if not fenced(
                        db, identity, token, lease=now() + dt.timedelta(seconds=settings.lease_seconds)
                    ):
                        return
                    db.commit()
                if (n - 1) % config["sample_every"]:
                    continue
                if max(frame.shape[:2]) > 4096:
                    raise ValueError("Source dimensions exceed limit")
                start = time.perf_counter()
                tracks, annotated, speed = detector.infer(frame)
                events = rules.step(timestamp, tracks)
                h, w = frame.shape[:2]
                if writer is None:
                    writer = cv2.VideoWriter(
                        str(output / "annotated.avi"),
                        cv2.VideoWriter.fourcc(*"MJPG"),
                        fps / config["sample_every"],
                        (w, h),
                    )
                    if not writer.isOpened():
                        raise ValueError("Annotated video encoder unavailable")
                for polygon in config["zones"].values():
                    cv2.polylines(
                        annotated,
                        [np.array([(int(x * w), int(y * h)) for x, y in polygon])],
                        True,
                        (40, 180, 255),
                        2,
                    )
                annotated = draw_tracks(annotated, tracks)
                cv2.rectangle(annotated, (6, 5), (min(w - 1, 325), 29), (28, 34, 39), -1)
                cv2.putText(
                    annotated,
                    f"{timestamp:.2f}s | {config['tracker']} | machine-generated",
                    (12, 22),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (255, 255, 255),
                    1,
                )
                writer.write(annotated)
                if encrypted:
                    if pts_writer is None:
                        pts_writer = TimestampWriter(playback, w, h)
                    pts_writer.write(annotated, timestamp)
                if encrypted:
                    if raw_writer is None:
                        Path(path).parent.mkdir(parents=True, exist_ok=True)
                        raw_writer = cv2.VideoWriter(path, cv2.VideoWriter.fourcc(*"MJPG"), fps, (w, h))
                    raw_writer.write(frame)
                trajectory.write(
                    json.dumps(
                        {
                            "timestamp": timestamp,
                            "source_timing": live.last_metadata if live else {"basis": "decoder_pts"},
                            "width": w,
                            "height": h,
                            "tracks": [t.__dict__ for t in tracks],
                        }
                    )
                    + "\n"
                )
                preview = output / "preview.jpg"
                temporary = output / "preview.tmp.jpg"
                cv2.imwrite(str(temporary), annotated)
                temporary.replace(preview)
                with Session() as db:
                    progress = (
                        min(timestamp / config["capture_seconds"], 0.99)
                        if encrypted
                        else min(n / max(total, 1), 0.99)
                    )
                    if not fenced(
                        db,
                        identity,
                        token,
                        progress=progress,
                        lease=now() + dt.timedelta(seconds=settings.lease_seconds),
                    ):
                        return
                    for event in events:
                        eid = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"{identity}:{event['rule_id']}:{event['track_ids']}:{timestamp:.4f}",
                            )
                        )
                        if db.get(Record, eid):
                            continue
                        image_path = output / (eid + ".jpg")
                        if not cv2.imwrite(str(image_path), annotated):
                            raise OSError("Evidence encoding failed")
                        storage.publish(image_path)
                        db.add(
                            Record(
                                id=eid,
                                tenant=tenant,
                                kind="event",
                                body={
                                    **event,
                                    "job_id": str(identity),
                                    "video_id": config["video_id"],
                                    "camera_id": config.get("camera_id"),
                                    "model": config["model"],
                                    "tracker": config["tracker"],
                                    "evidence_path": str(image_path),
                                    "lifecycle": "active",
                                },
                            )
                        )
                        event_ids.append((eid, timestamp))
                    for resolved in rules.resolved:
                        for item in db.scalars(
                            select(Record).where(
                                Record.kind == "event",
                                Record.tenant == tenant,
                                Record.body["job_id"].as_string() == str(identity),
                            )
                        ):
                            if item.body.get("condition_key") == resolved:
                                item.body = {**item.body, "lifecycle": "resolved", "resolved_at": timestamp}
                    db.merge(
                        Record(
                            id=str(identity),
                            tenant=tenant,
                            kind="artifact",
                            body={
                                "preview": str(preview),
                                "playback": str(playback),
                                "timestamp": timestamp,
                                "dropped_frames": live.dropped if live else 0,
                                "reconnects": live.reconnects if live else 0,
                                "timing": live.last_metadata.get("basis", "receive_monotonic")
                                if live
                                else "decoder_pts",
                            },
                        )
                    )
                    db.commit()
                processed += 1
                timestamps.append(timestamp)
                latencies.append((time.perf_counter() - start) * 1000)
                speeds.append(speed)
                heartbeat("processing", str(identity))
        if not processed or (not encrypted and n < total - 1):
            raise ValueError("Empty or truncated video decode")
        assert writer is not None
        writer.release()
        writer = None
        if raw_writer:
            raw_writer.release()
            raw_writer = None
        if pts_writer:
            pts_writer.close()
        else:
            encode_playback(output / "annotated.avi", playback, fps / config["sample_every"])
        storage.publish(playback)
        for eid, timestamp in event_ids:
            clip = output / (eid + ".mp4")
            clip_time = timestamp if not encrypted else (timestamp - timestamps[0])
            event_clip(playback, clip, clip_time)
            storage.publish(clip)
            with Session() as db:
                if not fenced(
                    db, identity, token, lease=now() + dt.timedelta(seconds=settings.lease_seconds)
                ):
                    return
                event_record = db.get(Record, eid)
                if event_record:
                    event_record.body = {**event_record.body, "clip_path": str(clip)}
                db.commit()
        report = {
            "frames": processed,
            "sampled_out": n - processed,
            "dropped_frames": live.dropped if live else 0,
            "reconnects": live.reconnects if live else 0,
            "p50_ms": float(np.percentile(latencies, 50)),
            "p95_ms": float(np.percentile(latencies, 95)),
            "p99_ms": float(np.percentile(latencies, 99)),
            "fps": 1000 / float(np.mean(latencies)),
            "device": settings.device,
            "model": config["model"],
            "warmup": "none; cold start included",
            "batch": 1,
            "stages_ms": {key: float(np.mean([s[key] for s in speeds])) for key in speeds[0]},
        }
        (output / "benchmark.json").write_text(json.dumps(report, indent=2))
        with Session() as db:
            if not fenced(db, identity, token, state="completed", progress=1, lease=None):
                return
            artifact = db.get(Record, str(identity))
            if artifact:
                artifact.body = {**artifact.body, "benchmark": report}
            if encrypted:
                video = db.get(Record, config["video_id"])
                assert video is not None
                video.body = {
                    **video.body,
                    "storage_key": storage.publish(Path(path)),
                    "frames": processed,
                    "fps": fps,
                    "duration": timestamps[-1],
                    "timing": "source_pts with receive fallback; annotated playback preserves gaps; raw AVI constant-rate",
                }
            for item in db.scalars(
                select(Record).where(
                    Record.kind == "event",
                    Record.tenant == tenant,
                    Record.body["job_id"].as_string() == str(identity),
                )
            ):
                if item.body.get("lifecycle") == "active":
                    item.body = {**item.body, "lifecycle": "session_ended", "ended_at": timestamps[-1]}
            db.commit()
        log.info(json.dumps({"job": str(identity), "state": "completed", **report}))
    except Exception as exc:
        # Stream credentials and decoder exceptions are deliberately not logged.
        log.error("Job %s failed (%s)", identity, type(exc).__name__)
        with Session() as db:
            if token:
                fenced(
                    db,
                    identity,
                    token,
                    state="failed",
                    error=f"{type(exc).__name__}: processing failed; inspect source or model configuration",
                )
            else:
                db.execute(
                    update(Job)
                    .where(Job.id == identity, Job.state == "running")
                    .values(state="failed", error=type(exc).__name__)
                )
            db.commit()
    finally:
        if pts_writer:
            try:
                pts_writer.close()
            except Exception as close_error:
                log.error("Playback finalization failed (%s)", type(close_error).__name__)
        for resource in (cap, writer, raw_writer):
            if resource is not None:
                resource.release()
        if live:
            live.close()


def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    while True:
        heartbeat("idle")
        from .maintenance import maintenance

        try:
            maintenance()
        except Exception as exc:
            log.error("Maintenance failed (%s); inference remains available", type(exc).__name__)
        identity = claim()
        if identity:
            process_job(identity)
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
