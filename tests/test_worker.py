from sentinel.db import Job, Session
from sentinel.worker import process_job


def test_missing_weights_fail_explicitly():
    import pytest
    from sentinel.inference import YOLOSession

    with pytest.raises(FileNotFoundError):
        YOLOSession("missing-model.pt", "bytetrack", 0.25, "cpu")


def test_worker_marks_missing_video_failed(client):
    with Session() as db:
        db.add(Job(id="missing", tenant="a", video_id="missing", state="running", config={}))
        db.commit()
    process_job("missing")
    with Session() as db:
        assert db.get(Job, "missing").state == "failed"


def test_worker_does_not_restart_canceled_job(client):
    with Session() as db:
        db.add(Job(id="canceled", tenant="a", video_id="missing", state="canceled", config={}))
        db.commit()
    process_job("canceled")
    with Session() as db:
        assert db.get(Job, "canceled").state == "canceled"
