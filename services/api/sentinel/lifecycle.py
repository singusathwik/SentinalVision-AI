"""Tenant-scoped deletion, shared by API and automatic retention."""

import datetime as dt
from pathlib import Path

from sqlalchemy import delete, select

from . import storage
from .config import settings
from .db import AuthSession, CleanupTask, Dispatch, Job, Lease, RateBucket, Record, Session, now


def delete_video(identity: str, tenant: str, actor: str) -> bool:
    with Session() as db:
        video = db.get(Record, identity)
        if not video or video.tenant != tenant or video.kind != "video":
            return False
        jobs = list(db.scalars(select(Job).where(Job.video_id == identity, Job.tenant == tenant)))
        if any(j.state in ("queued", "running") for j in jobs):
            raise ValueError("Cancel active jobs before deleting footage")
        events = list(
            db.scalars(
                select(Record).where(
                    Record.kind == "event",
                    Record.tenant == tenant,
                    Record.body["video_id"].as_string() == identity,
                )
            )
        )
        keys = set()
        if video.body.get("storage_key"):
            keys.add(video.body["storage_key"])
        elif video.body.get("path"):
            keys.add(Path(video.body["path"]).resolve().relative_to(settings.data_dir.resolve()).as_posix())
        for event in events:
            for field in ("evidence_path", "clip_path"):
                if event.body.get(field):
                    keys.add(
                        Path(event.body[field]).resolve().relative_to(settings.data_dir.resolve()).as_posix()
                    )
        for job in jobs:
            artifact = db.get(Record, job.id)
            if artifact and artifact.tenant == tenant and artifact.kind == "artifact":
                for field in ("preview", "playback"):
                    if artifact.body.get(field):
                        keys.add(
                            Path(artifact.body[field])
                            .resolve()
                            .relative_to(settings.data_dir.resolve())
                            .as_posix()
                        )
                db.delete(artifact)
            folder = storage.local_path("evidence/" + job.id)
            if folder.exists():
                for file in folder.rglob("*"):
                    if file.is_file():
                        keys.add(file.resolve().relative_to(settings.data_dir.resolve()).as_posix())
        db.add(
            CleanupTask(tenant=tenant, keys=sorted(keys), prefixes=["evidence/" + j.id + "/" for j in jobs])
        )
        for event in events:
            db.delete(event)
        for job in jobs:
            db.execute(delete(Lease).where(Lease.id == job.id))
            db.execute(delete(Dispatch).where(Dispatch.id == job.id))
            db.delete(job)
        db.add(
            Record(
                tenant=tenant,
                kind="audit",
                body={"action": "video_deleted", "video_id": identity, "actor": actor},
            )
        )
        db.delete(video)
        db.commit()
        drain_cleanup()
        return True


def retention() -> int:
    from .control import preferences

    with Session() as db:
        rows = [
            (r.id, r.tenant)
            for r in db.scalars(select(Record).where(Record.kind == "video"))
            if r.created < now() - dt.timedelta(days=preferences(db, r.tenant).retention_days)
        ]
        db.execute(delete(RateBucket).where(RateBucket.expires < now()))
        db.execute(delete(AuthSession).where(AuthSession.expires < now()))
        db.commit()
    count = 0
    for identity, tenant in rows:
        try:
            count += delete_video(identity, tenant, "retention-service")
        except ValueError:
            continue
    return count


def drain_cleanup() -> int:
    """Idempotent storage side effects after metadata commit; failures stay durable."""
    completed = 0
    with Session() as db:
        tasks = list(db.scalars(select(CleanupTask).limit(100)))
        for task in tasks:
            task.attempts += 1
            try:
                for prefix in task.prefixes:
                    for key in storage.list_keys(prefix):
                        storage.erase(key)
                for key in task.keys:
                    storage.erase(key)
            except Exception as exc:
                task.error = type(exc).__name__
            else:
                db.delete(task)
                completed += 1
            db.commit()
    return completed


def sweep_orphans(hours: int = 24):
    """Only application media prefixes, with age grace and active-job exclusion."""
    protected = set()
    with Session() as db:
        jobs = list(db.scalars(select(Job)))
        active_jobs = {j.id for j in jobs if j.state in ("queued", "running")}
        legacy_jobs = {j.id for j in jobs if db.get(Lease, j.id) is None}
        attempts = {"evidence/" + lease.id + "/" + lease.token + "/" for lease in db.scalars(select(Lease))}
        for record in db.scalars(select(Record).where(Record.kind.in_(["event", "artifact"]))):
            for field in ("evidence_path", "clip_path", "preview", "playback"):
                if record.body.get(field):
                    key = (
                        Path(record.body[field]).resolve().relative_to(settings.data_dir.resolve()).as_posix()
                    )
                    attempts.add(key.rsplit("/", 1)[0] + "/")
        video_keys = {
            r.body.get("storage_key")
            or str(Path(r.body["path"]).resolve().relative_to(settings.data_dir.resolve())).replace("\\", "/")
            for r in db.scalars(select(Record).where(Record.kind == "video"))
        }
        protected.update(video_keys)
        removed = 0
        for prefix in ("videos/", "evidence/"):
            for key in storage.aged_keys(prefix, now() - dt.timedelta(hours=hours)):
                if key in protected or (
                    prefix == "evidence/"
                    and (
                        key.split("/")[1] in active_jobs | legacy_jobs
                        or any(key.startswith(a) for a in attempts)
                    )
                ):
                    continue
                db.add(CleanupTask(tenant="__system", keys=[key], prefixes=[]))
                removed += 1
        db.commit()
    drain_cleanup()
    return removed
