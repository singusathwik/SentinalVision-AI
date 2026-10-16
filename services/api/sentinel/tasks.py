from celery import Celery
from sqlalchemy import select, update

from .config import settings
from .db import Dispatch, Job, Session, now
from .worker import claim, process_job

celery = Celery("sentinel", broker=settings.redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_reject_on_worker_lost=True)


@celery.task
def process(identity: str):
    claimed = claim(identity)
    if claimed:
        process_job(claimed)


def dispatch_pending() -> int:
    """Transactional outbox: metadata commit never depends on broker availability."""
    sent = 0
    with Session() as db:
        expired = list(
            db.scalars(select(Job.id).where(Job.state == "running", Job.lease < now(), Job.attempts < 3))
        )
        if expired:
            db.execute(
                update(Job)
                .where(Job.id.in_(expired), Job.state == "running", Job.lease < now())
                .values(state="queued")
            )
            db.execute(update(Dispatch).where(Dispatch.id.in_(expired)).values(sent=0))
        db.execute(
            update(Job)
            .where(Job.state == "running", Job.lease < now(), Job.attempts >= 3)
            .values(state="failed", error="Worker lease expired after three attempts")
        )
        for row in db.scalars(select(Dispatch).where(Dispatch.sent == 0).limit(100)):
            job = db.get(Job, row.id)
            if not job or job.state != "queued":
                row.sent = 1
                continue
            row.attempts += 1
            try:
                process.apply_async(args=[row.id], retry=False)
            except Exception:
                db.commit()
                return sent
            row.sent = 1
            sent += 1
        db.commit()
    return sent


if __name__ == "__main__":
    from .maintenance import main

    main()
