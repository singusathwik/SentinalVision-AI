import os
import tempfile

TEST_DIR = tempfile.mkdtemp(prefix="sentinel-tests-")
os.environ["SENTINEL_DATABASE_URL"] = "sqlite:///" + TEST_DIR.replace("\\", "/") + "/test.db"
os.environ["SENTINEL_DATA_DIR"] = TEST_DIR
os.environ["SENTINEL_SECRET"] = "test-only-secret-" + "x" * 40

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sentinel.api import app  # noqa: E402
from sentinel.auth import hasher  # noqa: E402
from sentinel.db import Base, Session, User, engine  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as db:
        db.add_all(
            [
                User(
                    email="a@test.local", password=hasher.hash("test-password-long"), tenant="a", role="admin"
                ),
                User(
                    email="b@test.local",
                    password=hasher.hash("test-password-long"),
                    tenant="b",
                    role="viewer",
                ),
            ]
        )
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(client):
    r = client.post("/api/v1/auth/login", json={"email": "a@test.local", "password": "test-password-long"})
    return {"Authorization": "Bearer " + r.json()["token"]}
