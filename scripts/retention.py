"""Preview expiry; --apply uses the same tenant-scoped local/S3 deletion as the worker."""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from sentinel.config import settings  # noqa: E402
from sentinel.db import Job, Record, Session, now  # noqa: E402
from sentinel.lifecycle import retention  # noqa: E402
from sqlalchemy import select  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
if args.apply:
    print("Expired videos deleted:", retention())
else:
    with Session() as db:
        for video in db.scalars(
            select(Record).where(
                Record.kind == "video", Record.created < now() - dt.timedelta(days=settings.retention_days)
            )
        ):
            active = db.scalar(
                select(Job.id).where(
                    Job.video_id == video.id, Job.tenant == video.tenant, Job.state.in_(["queued", "running"])
                )
            )
            if not active:
                print("would delete video and evidence:", video.id)
