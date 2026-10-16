from sentinel.db import Job, Record, Session


def test_job_names_are_tenant_scoped_and_independent_of_video_pagination(client, headers):
    with Session() as db:
        db.add_all(
            [
                Record(id="own-video", tenant="a", kind="video", body={"name": "people-walking.mp4"}),
                Record(id="other-video", tenant="b", kind="video", body={"name": "private.mp4"}),
                Job(id="own-job", tenant="a", video_id="own-video", config={}),
                Job(id="broken-job", tenant="a", video_id="other-video", config={}),
                Job(id="missing-job", tenant="a", video_id="missing", config={}),
            ]
        )
        db.commit()
    response = client.get("/api/v1/jobs", headers=headers)
    assert response.status_code == 200
    names = {row["id"]: row["video_name"] for row in response.json()}
    assert names == {
        "own-job": "people-walking.mp4",
        "broken-job": "Video unavailable",
        "missing-job": "Video unavailable",
    }
