import datetime as dt
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import cv2
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from . import storage
from .auth import admin, current_user, hasher, issue_token, operator, rate_limit, revoke
from .cameras import encrypt_source
from .config import settings
from .contracts import (
    CameraView,
    DeletedView,
    EventView,
    ExperimentView,
    JobView,
    LoginView,
    RuleView,
    StatusView,
    SummaryView,
    SystemView,
    UserView,
    VideoView,
    ZoneView,
)
from .db import Dispatch, Job, Record, Session, User, init_db, now, uid
from .schemas import Camera, JobRequest, Login, Review, Rule, UserCreate, Zone
from .security import RequestBoundary


@asynccontextmanager
async def lifespan(app):
    if len(settings.secret) < 32:
        raise RuntimeError("SENTINEL_SECRET must contain at least 32 characters; run scripts/bootstrap.py")
    init_db()
    yield


app = FastAPI(title="SentinelVision AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestBoundary)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def record_dict(r: Record) -> dict:
    return {
        **{k: v for k, v in r.body.items() if k not in ("encrypted_source", "evidence_path", "clip_path")},
        "id": r.id,
        "created": r.created.isoformat(),
    }


def get_record(db, identity: str, user: User, kind: str) -> Record:
    r = db.get(Record, identity)
    if not r or r.tenant != user.tenant or r.kind != kind:
        raise HTTPException(404, "Not found")
    return r


def add_record(user: User, kind: str, body: dict) -> dict:
    with Session() as db:
        r = Record(tenant=user.tenant, kind=kind, body=body)
        db.add(r)
        db.commit()
        return record_dict(r)


def records(user: User, kind: str, offset: int = 0, limit: int = 100) -> list:
    with Session() as db:
        return [
            record_dict(r)
            for r in db.scalars(
                select(Record)
                .where(Record.tenant == user.tenant, Record.kind == kind)
                .order_by(Record.created.desc(), Record.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 200))
            )
        ]


@app.post("/api/v1/auth/login", response_model=LoginView)
def login(body: Login, request: Request):
    rate_limit(request.client.host if request.client else "unknown")
    from .control import enabled

    with Session() as db:
        user = db.scalar(select(User).where(User.email == body.email.lower()))
        try:
            if not user or not enabled(db, user.id) or not hasher.verify(user.password, body.password):
                raise HTTPException(401, "Invalid credentials")
        except VerificationError:
            raise HTTPException(401, "Invalid credentials") from None
        token = issue_token(user)
        return {"token": token, "role": user.role, "tenant": user.tenant}


@app.get("/api/v1/health", response_model=dict[str, JsonValue])
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/v1/ready", response_model=dict[str, JsonValue])
def ready():
    with Session() as db:
        db.execute(select(1))
    return {"database": "ready"}


@app.post("/api/v1/videos/upload", status_code=201, response_model=VideoView)
def upload(file: UploadFile, user: User = Depends(operator)):
    rate_limit("upload:" + user.id, 20)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp4", ".avi", ".mov", ".mkv"):
        raise HTTPException(415, "Supported video extensions: mp4, avi, mov, mkv")
    identity = uid()
    path = settings.data_dir / "videos" / (identity + suffix)
    path.parent.mkdir(exist_ok=True)
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "Video exceeds upload limit")
                out.write(chunk)
        cap = cv2.VideoCapture(str(path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            ok, frame = cap.read()
            if not ok or not 0 < fps <= 240 or frames <= 0:
                raise HTTPException(422, "Video cannot be decoded or has invalid timing")
            if frames / fps > settings.max_duration_seconds or max(frame.shape[:2]) > 4096:
                raise HTTPException(422, "Video exceeds duration or dimension limits")
        finally:
            cap.release()
        with Session() as db:
            r = Record(
                id=identity,
                tenant=user.tenant,
                kind="video",
                body={
                    "name": Path(file.filename or "video").name,
                    "path": str(path),
                    "storage_key": storage.publish(path),
                    "size": size,
                    "fps": fps,
                    "frames": int(frames),
                    "duration": frames / fps,
                },
            )
            db.add(r)
            db.commit()
            return {k: v for k, v in record_dict(r).items() if k != "path"}
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.get("/api/v1/videos", response_model=list[VideoView])
def videos(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return [{k: v for k, v in r.items() if k != "path"} for r in records(user, "video", offset, limit)]


@app.get("/api/v1/videos/{identity}", response_model=VideoView)
def video(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        return {k: v for k, v in record_dict(get_record(db, identity, user, "video")).items() if k != "path"}


@app.get("/api/v1/videos/{identity}/content")
def video_content(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        r = get_record(db, identity, user, "video")
        return FileResponse(
            storage.materialize(r.body["storage_key"]) if r.body.get("storage_key") else r.body["path"]
        )


def job_dict(j: Job, db) -> dict:
    video = db.get(Record, j.video_id)
    name = video.body.get("name") if video and video.tenant == j.tenant and video.kind == "video" else None
    return {
        "video_name": name or "Video unavailable",
        "id": j.id,
        "video_id": j.video_id,
        "state": j.state,
        "progress": j.progress,
        "error": j.error,
        "attempts": j.attempts,
        "created": j.created.isoformat(),
        "config": j.config,
    }


@app.post("/api/v1/jobs", status_code=201, response_model=JobView)
def create_job(body: JobRequest, user: User = Depends(operator)):
    with Session() as db:
        if body.camera_id:
            camera = get_record(db, body.camera_id, user, "camera")
            if not camera.body.get("encrypted_source"):
                raise HTTPException(422, "Re-register this camera with approved IP configuration")
        else:
            get_record(db, body.video_id or "", user, "video")
        rules = [record_dict(get_record(db, rid, user, "rule")) for rid in body.rule_ids]
        zones = {
            r["zone_id"]: get_record(db, r["zone_id"], user, "zone").body["points"]
            for r in rules
            if r.get("zone_id")
        }
        from .control import active_model, preferences, validate_capabilities

        for rule in rules:
            validate_capabilities(db, Rule.model_validate(rule), user)
        defaults = preferences(db, user.tenant)
        config = {**body.model_dump(), "rules": rules, "zones": zones, "model": active_model(db, user.tenant)}
        for field in ("confidence", "sample_every"):
            if field not in body.model_fields_set:
                config[field] = getattr(defaults, field)
        model_path = Path(config["model"])
        config["model_sha256"] = (
            hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path.is_file() else None
        )
        config["calibrations"] = {}
        for rule in rules:
            if rule.get("calibration_id"):
                calibration = get_record(db, rule["calibration_id"], user, "calibration")
                if calibration.body["camera_id"] != body.camera_id:
                    raise HTTPException(422, "Calibration belongs to a different camera")
                config["calibrations"][rule["calibration_id"]] = calibration.body
        # Same source and immutable config is idempotent while queued/running/completed.
        for old in db.scalars(
            select(Job).where(
                Job.tenant == user.tenant,
                Job.video_id == body.video_id,
                Job.state.in_(["queued", "running", "completed"]),
            )
        ):
            if old.config == config:
                return job_dict(old, db)
        identity = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, user.tenant + json.dumps(config, sort_keys=True)))
            if body.video_id
            else uid()
        )
        video_id = body.video_id or uid()
        if body.camera_id:
            db.add(
                Record(
                    id=video_id,
                    tenant=user.tenant,
                    kind="video",
                    body={
                        "name": camera.body["name"] + " capture",
                        "camera_id": body.camera_id,
                        "path": str(settings.data_dir / "videos" / (video_id + ".avi")),
                    },
                )
            )
            config["video_id"] = video_id
        j = Job(id=identity, tenant=user.tenant, video_id=video_id, config=config)
        db.add(j)
        db.add(Dispatch(id=identity))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.get(Job, identity)
            if not existing or existing.tenant != user.tenant:
                raise
            return job_dict(existing, db)
        return job_dict(j, db)


@app.get("/api/v1/jobs", response_model=list[JobView])
def jobs(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    with Session() as db:
        return [
            job_dict(j, db)
            for j in db.scalars(
                select(Job)
                .where(Job.tenant == user.tenant)
                .order_by(Job.created.desc(), Job.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 200))
            )
        ]


@app.get("/api/v1/jobs/{identity}", response_model=JobView)
def job(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        j = db.get(Job, identity)
        if not j or j.tenant != user.tenant:
            raise HTTPException(404, "Not found")
        return job_dict(j, db)


@app.post("/api/v1/jobs/{identity}/cancel", response_model=JobView)
def cancel(identity: str, user: User = Depends(operator)):
    with Session() as db:
        j = db.get(Job, identity)
        if not j or j.tenant != user.tenant:
            raise HTTPException(404, "Not found")
        if j.state in ("queued", "running"):
            j.state = "canceled"
            db.commit()
        return job_dict(j, db)


@app.post("/api/v1/jobs/{identity}/retry", response_model=JobView)
def retry_job(identity: str, user: User = Depends(operator)):
    with Session() as db:
        j = db.get(Job, identity)
        if not j or j.tenant != user.tenant:
            raise HTTPException(404, "Not found")
        if j.state not in ("failed", "canceled"):
            raise HTTPException(409, "Only failed or canceled jobs can be retried")
        db.execute(
            update(Job)
            .where(Job.id == identity, Job.state.in_(["failed", "canceled"]))
            .values(state="queued", progress=0, error=None, attempts=0, lease=None)
        )
        db.merge(Dispatch(id=identity, sent=0, attempts=0))
        db.add(
            Record(
                tenant=user.tenant,
                kind="audit",
                body={"action": "retry", "job_id": identity, "actor": user.id},
            )
        )
        db.commit()
        db.refresh(j)
        return job_dict(j, db)


@app.post("/api/v1/zones", status_code=201, response_model=ZoneView)
def create_zone(body: Zone, user: User = Depends(operator)):
    return add_record(user, "zone", body.model_dump())


@app.get("/api/v1/zones", response_model=list[ZoneView])
def zones(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return records(user, "zone", offset, limit)


@app.post("/api/v1/rules", status_code=201, response_model=RuleView)
def create_rule(body: Rule, user: User = Depends(operator)):
    with Session() as db:
        if body.zone_id:
            get_record(db, body.zone_id, user, "zone")
        from .control import validate_capabilities

        validate_capabilities(db, body, user)
    return add_record(user, "rule", body.model_dump())


@app.get("/api/v1/rules", response_model=list[RuleView])
def rules(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return records(user, "rule", offset, limit)


@app.get("/api/v1/events", response_model=list[EventView])
def events(user: User = Depends(current_user), offset: int = 0, limit: int = 100, status: str | None = None):
    with Session() as db:
        query = select(Record).where(Record.tenant == user.tenant, Record.kind == "event")
        if status:
            query = query.where(Record.body["status"].as_string() == status)
        rows = db.scalars(
            query.order_by(Record.created.desc(), Record.id)
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 200))
        )
        return [{k: v for k, v in record_dict(r).items() if k != "evidence_path"} for r in rows]


@app.get("/api/v1/events/{identity}", response_model=EventView)
def event(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        return {
            k: v
            for k, v in record_dict(get_record(db, identity, user, "event")).items()
            if k != "evidence_path"
        }


@app.post("/api/v1/events/{identity}/review", response_model=StatusView)
def review(identity: str, body: Review, user: User = Depends(operator)):
    with Session() as db:
        r = get_record(db, identity, user, "event")
        db.add(
            Record(
                tenant=user.tenant,
                kind="audit",
                body={
                    "event_id": identity,
                    "actor": user.id,
                    "previous": r.body["status"],
                    **body.model_dump(),
                },
            )
        )
        r.body = {**r.body, "status": body.status}
        db.commit()
        return {"status": body.status}


@app.get("/api/v1/events/{identity}/evidence")
def evidence(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        r = get_record(db, identity, user, "event")
        key = Path(r.body["evidence_path"]).resolve().relative_to(settings.data_dir.resolve()).as_posix()
        path = storage.materialize(key)
        if not path.is_file():
            raise HTTPException(410, "Evidence expired")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/audit", response_model=list[dict[str, JsonValue]])
def audit(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return records(user, "audit", offset, limit)


@app.post("/api/v1/cameras", status_code=201, response_model=CameraView)
def create_camera(body: Camera, user: User = Depends(operator)):
    try:
        encrypted = encrypt_source(body.url)
    except (ValueError, OSError):
        raise HTTPException(422, "Camera requires an approved RTSP host and resolved IP") from None
    return add_record(
        user,
        "camera",
        {
            "name": body.name,
            "host": urlparse(body.url).hostname,
            "encrypted_source": encrypted,
            "authorized_by": user.id,
            "status": "registered",
        },
    )


@app.get("/api/v1/cameras", response_model=list[CameraView])
def cameras(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return records(user, "camera", offset, limit)


@app.get("/api/v1/models", response_model=list[dict[str, JsonValue]])
def models(user: User = Depends(current_user)):
    from .control import active_model

    with Session() as db:
        selected = active_model(db, user.tenant)
    return [
        {
            "id": selected,
            "backend": "onnxruntime" if selected.endswith(".onnx") else "pytorch",
            "license": "AGPL-3.0 or Ultralytics Enterprise",
            "status": "pretrained" if selected == settings.model else "registered",
            "supported": "COCO 80 classes"
            if selected == settings.model
            else "See registered capability evidence",
            "unavailable": ["forklift", "helmet", "vest"],
            "validation": "No industrial held-out evaluation performed",
        }
    ]


@app.get("/api/v1/analytics/summary", response_model=SummaryView)
def summary(user: User = Depends(current_user)):
    with Session() as db:
        all_events = list(
            db.scalars(select(Record).where(Record.tenant == user.tenant, Record.kind == "event"))
        )
        all_jobs = list(db.scalars(select(Job).where(Job.tenant == user.tenant)))
        categories: dict[str, int] = {}
        for e in all_events:
            categories[e.body["kind"]] = categories.get(e.body["kind"], 0) + 1
        return {
            "events": len(all_events),
            "needs_review": sum(e.body["status"] == "needs_review" for e in all_events),
            "jobs": len(all_jobs),
            "completed": sum(j.state == "completed" for j in all_jobs),
            "queue_depth": sum(j.state == "queued" for j in all_jobs),
            "failed": sum(j.state == "failed" for j in all_jobs),
            "categories": categories,
        }


@app.get("/api/v1/metrics", response_model=SummaryView)
def metrics(user: User = Depends(current_user)):
    return summary(user)


@app.get("/api/v1/updates")
def updates(user: User = Depends(current_user)):
    def stream():
        for _ in range(30):
            yield f"data: {json.dumps(summary(user))}\n\n"
            time.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/v1/auth/logout", response_model=StatusView)
def logout(request: Request, user: User = Depends(current_user)):
    revoke(request.headers["authorization"].split(" ", 1)[1])
    return {"status": "signed_out"}


@app.get("/api/v1/users", response_model=list[UserView])
def users(user: User = Depends(admin), offset: int = 0, limit: int = 100):
    from .control import enabled

    with Session() as db:
        return [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "enabled": enabled(db, u.id),
            }
            for u in db.scalars(
                select(User)
                .where(User.tenant == user.tenant)
                .order_by(User.email)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 200))
            )
        ]


@app.post("/api/v1/users", status_code=201, response_model=UserView)
def create_user(body: UserCreate, user: User = Depends(admin)):
    with Session() as db:
        item = User(
            email=body.email.lower(), tenant=user.tenant, password=hasher.hash(body.password), role=body.role
        )
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Account cannot be created") from None
        return {"id": item.id, "email": item.email, "role": item.role}


@app.delete("/api/v1/videos/{identity}", response_model=DeletedView)
def remove_video(identity: str, user: User = Depends(operator)):
    from .lifecycle import delete_video

    try:
        if not delete_video(identity, user.tenant, user.id):
            raise HTTPException(404, "Not found")
    except ValueError:
        raise HTTPException(409, "Cancel active jobs before deleting footage") from None
    return {"deleted": identity}


@app.delete("/api/v1/cameras/{identity}", response_model=DeletedView)
def remove_camera(identity: str, user: User = Depends(operator)):
    with Session() as db:
        item = get_record(db, identity, user, "camera")
        if item.body.get("monitor", {}).get("enabled"):
            raise HTTPException(409, "Stop monitoring before deleting the camera")
        running = db.scalar(
            select(Job).where(
                Job.tenant == user.tenant,
                Job.state.in_(["queued", "running"]),
                Job.config["camera_id"].as_string() == identity,
            )
        )
        if running:
            raise HTTPException(409, "Cancel camera jobs before deletion")
        db.delete(item)
        db.add(
            Record(
                tenant=user.tenant,
                kind="audit",
                body={"action": "camera_deleted", "camera_id": identity, "actor": user.id},
            )
        )
        db.commit()
    return {"deleted": identity}


def artifact_file(identity: str, field: str, user: User):
    with Session() as db:
        item = get_record(db, identity, user, "artifact")
        value = item.body.get(field)
        if not value:
            raise HTTPException(404, "Artifact not available yet")
        key = Path(value).resolve().relative_to(settings.data_dir.resolve()).as_posix()
        path = storage.materialize(key)
        if not path.is_file():
            raise HTTPException(404, "Artifact not available yet")
        return FileResponse(path, media_type="image/jpeg" if field == "preview" else "video/mp4")


@app.get("/api/v1/jobs/{identity}/preview")
def preview(identity: str, user: User = Depends(current_user)):
    return artifact_file(identity, "preview", user)


@app.get("/api/v1/jobs/{identity}/playback")
def playback(identity: str, user: User = Depends(current_user)):
    return artifact_file(identity, "playback", user)


@app.get("/api/v1/jobs/{identity}/telemetry", response_model=dict[str, JsonValue])
def job_telemetry(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        item = get_record(db, identity, user, "artifact")
        return {k: v for k, v in item.body.items() if k not in ("preview", "playback")}


@app.get("/api/v1/events/{identity}/clip")
def clip(identity: str, user: User = Depends(current_user)):
    with Session() as db:
        item = get_record(db, identity, user, "event")
        value = item.body.get("clip_path")
        if not value:
            raise HTTPException(404, "Clip not available yet")
        path = storage.materialize(Path(value).resolve().relative_to(settings.data_dir.resolve()).as_posix())
        return FileResponse(path, media_type="video/mp4")


@app.get("/api/v1/events/{identity}/signed-url", response_model=dict[str, JsonValue])
def signed_evidence(identity: str, user: User = Depends(current_user)):
    if settings.storage != "s3":
        raise HTTPException(409, "Local storage uses authenticated evidence endpoints")
    with Session() as db:
        item = get_record(db, identity, user, "event")
        key = Path(item.body["evidence_path"]).resolve().relative_to(settings.data_dir.resolve()).as_posix()
        return {"url": storage.signed_url(key), "expires_seconds": 60}


@app.get("/api/v1/system", response_model=SystemView)
def system_status(user: User = Depends(current_user)):
    from .control import preferences
    from .db import CleanupTask

    with Session() as db:
        workers = []
        for worker in db.scalars(select(Record).where(Record.kind == "worker")):
            age = (now() - dt.datetime.fromisoformat(worker.body["heartbeat"])).total_seconds()
            if age < 300:
                workers.append(
                    {
                        "id": worker.id,
                        "state": worker.body["state"],
                        "age_seconds": round(age, 1),
                        "healthy": age < 30,
                    }
                )
        return {
            "workers": workers,
            "queue": settings.queue,
            "storage": settings.storage,
            "retention_days": preferences(db, user.tenant).retention_days,
            "database": settings.database_url.split(":")[0],
            "pending_cleanup": db.query(CleanupTask).filter_by(tenant=user.tenant).count(),
            "failed_jobs": db.query(Job).filter_by(tenant=user.tenant, state="failed").count(),
        }


@app.get("/api/v1/analytics/trends", response_model=dict[str, JsonValue])
def trends(user: User = Depends(current_user)):
    with Session() as db:
        days: dict[str, int] = {}
        cameras: dict[str, int] = {}
        for event in db.scalars(select(Record).where(Record.tenant == user.tenant, Record.kind == "event")):
            day = event.created.date().isoformat()
            days[day] = days.get(day, 0) + 1
            camera = event.body.get("camera_id") or "uploaded-video"
            cameras[camera] = cameras.get(camera, 0) + 1
        return {
            "daily": [{"date": k, "events": v} for k, v in sorted(days.items())],
            "cameras": [{"camera": k, "events": v} for k, v in cameras.items()],
        }


@app.get("/api/v1/experiments", response_model=list[ExperimentView])
def experiments(user: User = Depends(current_user), offset: int = 0, limit: int = 100):
    return records(user, "experiment", offset, limit)


@app.post("/api/v1/experiments/publish-local", response_model=ExperimentView)
def publish_experiment(user: User = Depends(admin)):
    path = settings.data_dir / "training" / "validation.json"
    if not path.is_file():
        raise HTTPException(404, "No local training report")
    report = json.loads(path.read_text())
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, user.tenant + report["run_id"]))
    with Session() as db:
        item = Record(
            id=identity,
            tenant=user.tenant,
            kind="experiment",
            body={
                "scope": "COCO8 smoke only; not domain accuracy"
                if report.get("smoke_only")
                else "local validation report; review provenance",
                "run_id": report["run_id"],
                "metrics": report["metrics"],
            },
        )
        item = db.merge(item)
        db.commit()
        return record_dict(item)


from .control import router as control_router  # noqa: E402

app.include_router(control_router)
