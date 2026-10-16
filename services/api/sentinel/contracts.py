"""Public response contracts. Storage secrets/paths never belong to public records."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from .schemas import Rule, Zone


class RecordView(BaseModel):
    id: str
    created: datetime


class ZoneView(Zone, RecordView):
    pass


class RuleView(Rule, RecordView):
    pass


class VideoView(RecordView):
    name: str
    camera_id: str | None = None
    size: int | None = None
    fps: float | None = None
    frames: int | None = None
    duration: float | None = None
    timing: str | None = None


class EventView(RecordView):
    status: Literal["confirmed", "false_alarm", "needs_review"]
    kind: str | None = None
    rule_id: str | None = None
    rule_version: int | None = None
    timestamp: float | None = None
    started_at: float | None = None
    track_ids: list[int] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
    severity: str | None = None
    duration: float | None = None
    condition_key: str | None = None
    job_id: str | None = None
    video_id: str | None = None
    camera_id: str | None = None
    model: str | None = None
    tracker: str | None = None
    lifecycle: str | None = None
    resolved_at: float | None = None
    ended_at: float | None = None


class JobView(BaseModel):
    video_name: str
    id: str
    video_id: str
    state: Literal["queued", "running", "completed", "failed", "canceled"]
    progress: float
    error: str | None
    attempts: int
    created: datetime
    config: dict[str, JsonValue]


class CameraView(RecordView):
    name: str
    host: str | None = None
    authorized_by: str | None = None
    status: str
    monitor: dict[str, JsonValue] | None = None
    operator_id: str | None = None


class UserView(BaseModel):
    id: str
    email: str
    role: Literal["admin", "operator", "viewer"]
    enabled: bool = True


class ExperimentView(RecordView):
    run_id: str
    scope: str
    metrics: dict[str, float]


class LoginView(BaseModel):
    token: str
    role: Literal["admin", "operator", "viewer"]
    tenant: str


class StatusView(BaseModel):
    status: str


class DeletedView(BaseModel):
    deleted: str


class ModelVersionView(RecordView):
    filename: str
    name: str
    report_id: str
    sha256: str
    scope: str
    status: str
    validated_capabilities: list[str]


class AccessView(BaseModel):
    id: str
    enabled: bool
    role: Literal["admin", "operator", "viewer"]


class WorkerView(BaseModel):
    id: str
    state: str
    age_seconds: float
    healthy: bool


class SystemView(BaseModel):
    workers: list[WorkerView]
    queue: str
    storage: str
    database: str
    retention_days: int
    pending_cleanup: int
    failed_jobs: int


class CleanupView(RecordView):
    attempts: int
    error: str | None


class SummaryView(BaseModel):
    events: int
    needs_review: int
    jobs: int
    completed: int
    queue_depth: int
    failed: int
    categories: dict[str, int]
