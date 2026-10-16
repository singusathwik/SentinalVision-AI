"""Typed tenant controls. No browser-provided filesystem paths are accepted."""

import hashlib
from typing import Literal

from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, JsonValue
from sqlalchemy import select, update

from .auth import admin, current_user, hasher, operator
from .capabilities import Calibration
from .config import settings
from .contracts import AccessView, CleanupView, JobView, ModelVersionView, RuleView, StatusView
from .db import AuthSession, Job, Record, Session, User
from .schemas import Rule

router = APIRouter(prefix="/api/v1")


class Preferences(BaseModel):
    retention_days: int = Field(default=7, ge=1, le=365)
    confidence: float = Field(default=0.25, ge=0.05, le=0.95)
    sample_every: int = Field(default=1, ge=1, le=30)


class IdentityChange(BaseModel):
    enabled: bool = True
    role: Literal["admin", "operator", "viewer"]


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


class Monitor(BaseModel):
    enabled: bool
    segment_seconds: int = Field(default=30, ge=5, le=300)
    rule_ids: list[str] = Field(default_factory=list, max_length=50)
    tracker: Literal["bytetrack", "botsort"] = "bytetrack"


class ModelRegistration(BaseModel):
    filename: str = Field(pattern=r"^[a-zA-Z0-9_.-]+\.(pt|onnx)$", max_length=120)
    name: str = Field(min_length=1, max_length=80)
    report_id: str


class Promotion(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def key(kind, tenant):
    return hashlib.sha256(f"{kind}:{tenant}".encode()).hexdigest()[:36]


def audit(db, user, action, **data):
    db.add(Record(tenant=user.tenant, kind="audit", body={"actor": user.id, "action": action, **data}))


def preferences(db, tenant) -> Preferences:
    item = db.get(Record, key("preferences", tenant))
    return (
        Preferences.model_validate(item.body) if item else Preferences(retention_days=settings.retention_days)
    )


def enabled(db, identity):
    item = db.get(Record, key("identity", identity))
    return not item or item.body.get("enabled", True)


def active_model(db, tenant):
    item = db.get(Record, key("active_model", tenant))
    if not item:
        return settings.model
    registered = db.get(Record, item.body["model_id"])
    if not registered or registered.tenant != tenant:
        raise HTTPException(409, "Active model registration missing")
    path = settings.data_dir / "models" / registered.body["filename"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != registered.body["sha256"]:
        raise HTTPException(409, "Model artifact changed or is unavailable; register it again")
    return str(path)


@router.get("/preferences", response_model=Preferences)
def get_preferences(user: User = Depends(current_user)):
    with Session() as db:
        return preferences(db, user.tenant)


@router.put("/preferences", response_model=Preferences)
def save_preferences(body: Preferences, user: User = Depends(admin)):
    with Session() as db:
        db.merge(
            Record(
                id=key("preferences", user.tenant),
                tenant=user.tenant,
                kind="preferences",
                body=body.model_dump(),
            )
        )
        audit(db, user, "preferences_changed", **body.model_dump())
        db.commit()
    return body


@router.put("/users/{identity}/access", response_model=AccessView)
def change_access(identity: str, body: IdentityChange, user: User = Depends(admin)):
    if identity == user.id:
        raise HTTPException(409, "Ask another administrator to change your own access")
    with Session() as db:
        target = db.get(User, identity)
        if not target or target.tenant != user.tenant:
            raise HTTPException(404, "Not found")
        target.role = body.role
        db.merge(
            Record(
                id=key("identity", identity),
                tenant=user.tenant,
                kind="identity",
                body={"enabled": body.enabled},
            )
        )
        db.execute(update(AuthSession).where(AuthSession.user_id == identity).values(revoked=1))
        audit(db, user, "access_changed", user_id=identity, **body.model_dump())
        db.commit()
    return {"id": identity, **body.model_dump()}


@router.post("/users/{identity}/reset-password", response_model=StatusView)
def reset_password(identity: str, body: PasswordReset, user: User = Depends(admin)):
    with Session() as db:
        target = db.get(User, identity)
        if not target or target.tenant != user.tenant:
            raise HTTPException(404, "Not found")
        target.password = hasher.hash(body.new_password)
        db.execute(update(AuthSession).where(AuthSession.user_id == identity).values(revoked=1))
        audit(db, user, "password_reset", user_id=identity)
        db.commit()
    return {"status": "password_reset_sessions_revoked"}


@router.post("/auth/change-password", response_model=StatusView)
def change_password(body: PasswordChange, user: User = Depends(current_user)):
    try:
        if not hasher.verify(user.password, body.current_password):
            raise HTTPException(401, "Incorrect current password")
    except VerificationError:
        raise HTTPException(401, "Incorrect current password") from None
    with Session() as db:
        db.execute(update(User).where(User.id == user.id).values(password=hasher.hash(body.new_password)))
        db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(revoked=1))
        audit(db, user, "password_changed")
        db.commit()
    return {"status": "password_changed_sign_in_again"}


@router.put("/cameras/{identity}/monitor", response_model=Monitor)
def monitor(identity: str, body: Monitor, user: User = Depends(operator)):
    from .maintenance import acquire, release

    token = acquire("camera:" + identity)
    if not token:
        raise HTTPException(409, "Camera scheduler is updating this source; retry shortly")
    try:
        return _monitor(identity, body, user)
    finally:
        release("camera:" + identity, token)


def _monitor(identity: str, body: Monitor, user: User):
    from .api import get_record

    with Session() as db:
        camera = get_record(db, identity, user, "camera")
        for rule in body.rule_ids:
            get_record(db, rule, user, "rule")
        camera.body = {**camera.body, "monitor": body.model_dump(), "operator_id": user.id}
        if not body.enabled:
            for job in db.scalars(
                select(Job).where(
                    Job.tenant == user.tenant,
                    Job.state.in_(["queued", "running"]),
                    Job.config["camera_id"].as_string() == identity,
                )
            ):
                job.state = "canceled"
        audit(db, user, "monitor_changed", camera_id=identity, **body.model_dump())
        db.commit()
    return body


@router.put("/rules/{identity}", response_model=RuleView)
def revise_rule(identity: str, body: Rule, user: User = Depends(operator)):
    from .api import get_record

    with Session() as db:
        old = get_record(db, identity, user, "rule")
        if body.zone_id:
            get_record(db, body.zone_id, user, "zone")
        validate_capabilities(db, body, user)
        old.body = {**body.model_dump(), "version": old.body.get("version", 1) + 1}
        audit(db, user, "rule_revised", rule_id=identity, version=old.body["version"])
        db.commit()
        return {**old.body, "id": identity, "created": old.created.isoformat()}


@router.get("/registry", response_model=list[ModelVersionView])
def registry(offset: int = 0, limit: int = 20, user: User = Depends(current_user)):
    from .api import records

    return records(user, "model_version", offset, limit)


@router.post("/registry", status_code=201, response_model=ModelVersionView)
def register_model(body: ModelRegistration, user: User = Depends(admin)):
    from .api import get_record

    path = settings.data_dir / "models" / body.filename
    if not path.is_file():
        raise HTTPException(422, "Administrator must provision the artifact in data/models first")
    with Session() as db:
        report = get_record(db, body.report_id, user, "experiment")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if report.body.get("model_sha256") != digest and "smoke" not in report.body["scope"].lower():
            raise HTTPException(422, "Validation report must identify the exact model hash")
        item = Record(
            tenant=user.tenant,
            kind="model_version",
            body={
                **body.model_dump(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "scope": report.body["scope"],
                "status": "candidate",
                "validated_capabilities": report.body.get("validated_capabilities", []),
            },
        )
        db.add(item)
        audit(db, user, "model_registered", sha256=item.body["sha256"])
        db.commit()
        return {**item.body, "id": item.id, "created": item.created.isoformat()}


@router.post("/registry/{identity}/promote", response_model=dict[str, str])
def promote(identity: str, body: Promotion, user: User = Depends(admin)):
    from .api import get_record

    with Session() as db:
        item = get_record(db, identity, user, "model_version")
        if any(word in item.body["scope"].lower() for word in ("smoke", "synthetic", "demo", "fixture")):
            raise HTTPException(422, "Smoke, synthetic, demo or fixture evidence cannot justify promotion")
        previous = db.get(Record, key("active_model", user.tenant))
        db.merge(
            Record(
                id=key("active_model", user.tenant),
                tenant=user.tenant,
                kind="active_model",
                body={"model_id": identity},
            )
        )
        db.flush()
        active_model(db, user.tenant)
        audit(
            db,
            user,
            "model_promoted",
            model_id=identity,
            previous=previous.body if previous else None,
            reason=body.reason,
        )
        db.commit()
    return {"active_model_id": identity}


@router.get("/failures", response_model=list[JobView])
def failures(offset: int = 0, limit: int = 20, user: User = Depends(operator)):
    from .api import job_dict

    with Session() as db:
        return [
            job_dict(j, db)
            for j in db.scalars(
                select(Job)
                .where(Job.tenant == user.tenant, Job.state == "failed")
                .order_by(Job.created.desc(), Job.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 200))
            )
        ]


@router.post("/calibrations", status_code=201, response_model=dict[str, JsonValue])
def create_calibration(body: Calibration, user: User = Depends(admin)):
    from .api import get_record
    from .capabilities import fit

    with Session() as db:
        get_record(db, body.camera_id, user, "camera")
        try:
            result = fit(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        item = Record(tenant=user.tenant, kind="calibration", body=result)
        db.add(item)
        audit(db, user, "calibration_registered", camera_id=body.camera_id, measured=body.measured)
        db.commit()
        return {**result, "id": item.id, "created": item.created.isoformat()}


def validate_capabilities(db, body, user):
    from .api import get_record

    industrial = {"forklift", "helmet", "vest", "no_helmet", "no_vest"}
    required = set(body.classes) & industrial
    if body.kind == "proximity":
        required |= {"person", "forklift"}
        if not body.calibration_id:
            raise HTTPException(422, "Metric proximity requires measured calibration")
        calibration = get_record(db, body.calibration_id, user, "calibration")
        if not calibration.body["measured"]:
            raise HTTPException(422, "Synthetic calibration cannot activate metric safety rules")
    if body.kind == "ppe":
        required |= {"person", "no_" + body.equipment}
    if required:
        active = db.get(Record, key("active_model", user.tenant))
        model = db.get(Record, active.body["model_id"]) if active else None
        if not model or not required.issubset(set(model.body.get("validated_capabilities", []))):
            raise HTTPException(422, "Active model lacks validation evidence for the requested capabilities")


class ValidationReport(BaseModel):
    run_id: str = Field(min_length=1, max_length=100)
    scope: str = Field(min_length=10, max_length=1000)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    held_out: Literal[True]
    metrics: dict[str, float]
    validated_capabilities: list[str] = Field(default_factory=list, max_length=100)
    annotation_provenance: str = Field(min_length=10, max_length=2000)


@router.post("/experiments", status_code=201, response_model=dict[str, JsonValue])
def import_report(body: ValidationReport, user: User = Depends(admin)):
    with Session() as db:
        item = Record(tenant=user.tenant, kind="experiment", body=body.model_dump())
        db.add(item)
        audit(
            db,
            user,
            "validation_report_imported",
            model_sha256=body.model_sha256,
            dataset_sha256=body.dataset_sha256,
        )
        db.commit()
        return {**item.body, "id": item.id, "created": item.created.isoformat()}


@router.post("/registry/reset-baseline", response_model=dict[str, str])
def baseline(user: User = Depends(admin)):
    with Session() as db:
        item = db.get(Record, key("active_model", user.tenant))
        if item:
            db.delete(item)
        audit(db, user, "model_rollback_baseline")
        db.commit()
    return {"active_model": settings.model}


@router.get("/cleanup", response_model=list[CleanupView])
def cleanup_status(offset: int = 0, limit: int = 20, user: User = Depends(admin)):
    from .db import CleanupTask

    with Session() as db:
        return [
            {"id": row.id, "created": row.created, "attempts": row.attempts, "error": row.error}
            for row in db.scalars(
                select(CleanupTask)
                .where(CleanupTask.tenant == user.tenant)
                .order_by(CleanupTask.created, CleanupTask.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 200))
            )
        ]
