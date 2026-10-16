"""Exercise actual HTTP S3 requests against a local Moto service (not AWS/MinIO proof)."""

import json
import os
import sys
from pathlib import Path

import httpx

os.environ["AWS_ACCESS_KEY_ID"] = "fixture-only"
os.environ["AWS_SECRET_ACCESS_KEY"] = "fixture-only"
os.environ["SENTINEL_STORAGE"] = "s3"
os.environ["SENTINEL_S3_ENDPOINT"] = "http://127.0.0.1:5005"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from sentinel import storage  # noqa: E402
from sentinel.config import settings  # noqa: E402

storage.client().create_bucket(Bucket=settings.s3_bucket)
path = storage.local_path("storage-fixture/verified.txt")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(b"Sentinel S3 local integration")
key = storage.publish(path)
url = storage.signed_url(key)
response = httpx.get(url)
assert response.status_code == 200 and response.content == path.read_bytes()
path.unlink()
assert storage.materialize(key).read_bytes() == response.content
storage.erase(key)
report = {
    "upload": True,
    "presigned_http_get": True,
    "cache_rehydration": True,
    "delete": True,
    "scope": "local Moto HTTP S3 emulator; not external S3/MinIO",
}
Path("docs/results/storage-integration.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
