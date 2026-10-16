"""Shared maintenance/scheduling loop for both database and Celery execution."""

import datetime as dt
import logging
import time
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Job, Record, ServiceLease, Session, User, init_db, now, uid

log = logging.getLogger(__name__)


def acquire(identity: str, seconds: int = 30):
    token = uid()
    with Session() as db:
        changed = db.execute(
            update(ServiceLease)
            .where(ServiceLease.id == identity, ServiceLease.expires < now())
            .values(token=token, expires=now() + dt.timedelta(seconds=seconds))
        )
        if not cast(CursorResult, changed).rowcount:
            db.add(ServiceLease(id=identity, token=token, expires=now() + dt.timedelta(seconds=seconds)))
        try:
            db.commit()
        except IntegrityError:
            return None
    return token


def release(identity, token):
    with Session() as db:
        db.execute(
            update(ServiceLease)
            .where(ServiceLease.id == identity, ServiceLease.token == token)
            .values(expires=now())
        )
        db.commit()


def schedule_cameras():
    from .api import create_job
    from .control import Monitor, enabled
    from .schemas import JobRequest

    submitted = 0
    with Session() as db:
        cameras = list(db.scalars(select(Record).where(Record.kind == "camera")))
    for camera in cameras:
        monitor = Monitor.model_validate(camera.body.get("monitor", {"enabled": False}))
        if not monitor.enabled:
            continue
        lock = "camera:" + camera.id
        token = acquire(lock)
        if not token:
            continue
        try:
            with Session() as db:
                current = db.get(Record, camera.id)
                if not current:
                    continue
                monitor = Monitor.model_validate(current.body.get("monitor", {"enabled": False}))
                if not monitor.enabled:
                    continue
                camera = current
                recent = db.scalar(
                    select(Job)
                    .where(Job.tenant == camera.tenant, Job.config["camera_id"].as_string() == camera.id)
                    .order_by(Job.created.desc())
                    .limit(1)
                )
                if recent and (
                    recent.state in ("running", "queued")
                    or (recent.state == "failed" and (now() - recent.created).total_seconds() < 60)
                ):
                    continue
                user = db.get(User, camera.body.get("operator_id"))
                if not user or not enabled(db, user.id) or user.role not in ("admin", "operator"):
                    continue
            create_job(
                JobRequest(
                    camera_id=camera.id,
                    capture_seconds=monitor.segment_seconds,
                    rule_ids=monitor.rule_ids,
                    tracker=monitor.tracker,
                ),
                user,
            )
            submitted += 1
        except Exception as exc:
            log.warning("Camera schedule failed (%s)", type(exc).__name__)
        finally:
            release(lock, token)
    return submitted


def maintenance():
    from .audit import seal_audit
    from .lifecycle import drain_cleanup, retention, sweep_orphans

    token = acquire("maintenance", max(settings.retention_interval, 60))
    if token:
        # Keep the time lease until interval expiry; avoid running retention every poll.
        retention()
        sweep_orphans()
        seal_audit()
    drain_cleanup()
    return schedule_cameras()


def main():
    init_db()
    while True:
        try:
            maintenance()
            if settings.queue == "celery":
                from .tasks import dispatch_pending

                dispatch_pending()
        except Exception as exc:
            log.error("Maintenance failed (%s)", type(exc).__name__)
        time.sleep(2)


if __name__ == "__main__":
    main()
