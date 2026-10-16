# Operations

## Native profile (executed)

Install Python 3.12, Node 22+ and uv. Native verification used Python 3.12.15 and Node 25.3.0.

```powershell
uv sync --frozen --group ml
npm ci --prefix apps/web
.venv/Scripts/python.exe scripts/bootstrap.py
```

Bootstrap creates an application secret only if `.env` is absent and asks for an administrator password. This authored checkout already has ignored local credentials in `data/local-login.json`; do not publish that file.

Start three terminals from the root:

```powershell
./scripts/start-local.ps1 api
./scripts/start-local.ps1 worker
./scripts/start-local.ps1 web
```

Browser: http://127.0.0.1:3000. API/OpenAPI: http://127.0.0.1:8010/docs. On Linux use `PYTHONPATH=services/api .venv/bin/python -m uvicorn sentinel.api:app --port 8010`, a separate `python -m sentinel.worker` with that Python path, and `npm run dev --prefix apps/web`. Tokens are kept in browser memory; reload requires login, and Sign out revokes the server session.

For a self-contained integration run, stop services on 8010/3000 and run `python scripts/e2e_stack.py`. It creates an isolated SQLite database and credentials under ignored `data/e2e-stack`, starts services, runs the real model demo plus four Playwright tests and stops its children. On Windows install Edge; on Linux run `npx playwright install --with-deps chromium` in apps/web and set `CI=1`. First model/sample acquisition requires Internet. Logs are retained under the isolated data directory. This exact launcher passed locally; hosted CI has not run.

## Migrations

With `PYTHONPATH=services/api`, fresh schemas use `alembic -c infra/alembic.ini upgrade head`. Head is 003. Revision 001 creates initial records/users/jobs; 002 adds auth sessions, rate buckets, outbox and lease tokens. Revision 003 adds service leases and durable cleanup tasks. Fresh SQLite upgrade to 003 and `alembic check` passed.

Bootstrap/API `create_all` only creates missing tables; it does not upgrade existing columns. For a database already created that way, back it up and compare its schema before stamping the corresponding revision. Never blindly run initial create-table migration over populated tables. PostgreSQL migrations remain unexecuted.

## Capture and replay

Set `SENTINEL_RTSP_HOSTS` and `SENTINEL_RTSP_ALLOWED_IPS` to comma-separated, exact authorized hosts/IPs. Register a source in Live monitoring with operator authorization, select desired rules under Video analysis, then Capture 30 seconds. Previews poll every 1.5s. Captures can be canceled; the API permits 1â€“300 seconds. For local fixtures only, explicitly enable `SENTINEL_ALLOW_LOOPBACK_CAMERA_FIXTURE=true` in the fixture API/worker process, never as a production default.

Camera credentials are encrypted at rest using the application secret. Secret rotation requires camera credential migration/re-registration. Decoder has a 10s open timeout, 3s read timeout, two-frame queue, three reconnect attempts and bounded backoff. Dropped frames/reconnect counts are exposed by job telemetry. PyAV decodes source PTS with receive-time fallback; reconnect/discontinuity epochs are mapped monotonically. Annotated MP4 stores per-frame PTS and preserves dropped-frame gaps. Source clocks are not synchronized to UTC or other cameras. The raw source AVI remains constant-rate and is not the timestamp-authoritative evidence. Native stderr is restricted operational data; credential-free RTSP proxy URLs are preferable for exposed environments.

Local integration used MediaMTX 1.21.2 (official release, provenance under ignored data/tools) bound only to 127.0.0.1:8554 and bundled imageio-ffmpeg. See `configs/mediamtx-fixture.yml`. Start a short-GOP H264 publisher at path `fixture` and a fixture API on 8012, pause the ordinary worker, then run `python scripts/verify_live.py`. The script documents its loopback-only environment. `python scripts/verify_rtsp_restart.py` owns a second publisher and verifies interruption/recovery without contacting a remote camera. These tools require the separately downloaded MediaMTX binary; it is not vendored. The ordinary application does not need MediaMTX for uploaded videos.

## Storage and retention

Default is private local storage. To use S3, provision a private bucket and SDK credentials, set `SENTINEL_STORAGE=s3`, bucket/region and optionally `SENTINEL_S3_ENDPOINT`, consistently for API and workers. Never expose SDK credentials in browser configuration. Presigned URLs expire after 60s and the endpoint must be reachable by their authorized consumers. `scripts/verify_storage.py` passed against a Moto server on loopback port 5005; real AWS/MinIO policy, TLS and durability are unverified.

Native workers run retention at startup and each `SENTINEL_RETENTION_INTERVAL` (default 3600s). Default `SENTINEL_RETENTION_DAYS=7`. `python scripts/retention.py` previews eligible IDs; `--apply` runs the shared local/S3 deletion. Active jobs are excluded. The dashboard requires confirmation before deletion. Audit records persist. Run the shared maintenance service in both profiles. Deletion commits a durable cleanup task with metadata deletion; failed storage work retries every maintenance poll. Age-gated orphan scanning removes unreferenced media after 24 hours, protecting active jobs and referenced attempts. Configure bucket lifecycle expiration as defense in depth. Maintain restricted backups and a separate audit policy.

## Queue recovery

Database mode is the exercised profile. Claims are atomic, leased, randomly fenced and limited to three automatic attempts. Cancellation is cooperative between frames. Failed/canceled jobs expose Retry; completed identical submissions remain idempotent. Retried event IDs preserve prior reviews. Worker heartbeat appears in System health.

For a separately provisioned Redis/Celery profile set `SENTINEL_QUEUE=celery`, run `celery -A sentinel.tasks:celery worker --pool=solo` and `python -m sentinel.tasks` (outbox dispatcher), which now includes the shared maintenance scheduler. API transactions never depend on broker availability. Failure and expired-lease redelivery have unit tests; real-broker restart/load/failover have not been exercised. Native workers and broker workers should not be deployed together accidentally. `scripts/supervise.py` restarts owned native services with bounded backoff. Compose services have restart policies and a maintenance service; boot-time OS service installation and distributed failover still require deployment testing.

## Containers and GPU (unexecuted)

Docker is absent locally. Set required secrets and use `docker compose -f infra/compose.yaml up --build`; bootstrap an account via `docker compose -f infra/compose.yaml exec api python scripts/bootstrap.py`. Core profile uses PostgreSQL with database polling and shared files; Redis is provisioned, MinIO is optional. To use MinIO, create a private bucket and explicitly configure the S3 settings/credentials for API and workers. Optional service presence alone is not storage validation. Docker builds, PostgreSQL and actual Redis/MinIO integration require another host or Docker installation.

For GPU use a compatible CUDA PyTorch/driver stack, verify `torch.cuda.is_available()`, then set `SENTINEL_DEVICE=0` or train with `--device 0`. Validate memory, cancellation, numerical agreement and warmed latency. GPU, TensorRT, Kubernetes and cloud deployment have not been executed.

## Reproduce optional loopback service checks

Run only the fixtures needed, then stop them. These servers bind to loopback.

```powershell
# Terminal A: S3 emulator (dev dependency); then run verify_storage.py in another terminal
.venv/Scripts/python.exe -m moto.server -H 127.0.0.1 -p 5005
.venv/Scripts/python.exe scripts/verify_storage.py

# RTSP server: download the official MediaMTX release first
./data/tools/mediamtx/mediamtx.exe configs/mediamtx-fixture.yml
# A separate terminal can then run the self-owned interruption fixture
.venv/Scripts/python.exe scripts/verify_rtsp_restart.py
```

For `verify_live.py`, first run the demo to create an authorized rule and local fixture. Start a publisher in another terminal:

```powershell
$fixtureFfmpeg = & .venv/Scripts/python.exe -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'
& $fixtureFfmpeg -re -stream_loop -1 -i data/demo/static-bus-test.avi -an -c:v libx264 -preset ultrafast -tune zerolatency -g 10 -pix_fmt yuv420p -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/fixture
```

Pause the ordinary worker so it cannot claim the fixture job without fixture permissions. Start the fixture API with these process-local settings:

```powershell
$env:PYTHONPATH='services/api'
$env:SENTINEL_RTSP_HOSTS='127.0.0.1'
$env:SENTINEL_RTSP_ALLOWED_IPS='127.0.0.1'
$env:SENTINEL_ALLOW_LOOPBACK_CAMERA_FIXTURE='true'
.venv/Scripts/python.exe -m uvicorn sentinel.api:app --host 127.0.0.1 --port 8012
```

Run `python scripts/verify_live.py` from another terminal. It uses ignored local credentials, registers a labeled fixture camera, directly claims its bounded job, executes the real model and verifies preview/playback/telemetry. Stop fixture processes afterwards, close the fixture environment terminal and restart the ordinary worker. Credentials and recorded fixture outputs stay under ignored data directories.

## Continuous segmented monitoring and supervision

Run `.venv/Scripts/python.exe scripts/supervise.py api worker maintenance web` from the repository root. It supervises these local processes until stopped; logs are under `data/service-logs`. Do not simultaneously run duplicate API/web listeners. For Celery use the broker worker plus `python -m sentinel.tasks`; that process runs dispatch and maintenance. The native supervisor intentionally starts the native database worker, not a Celery worker.

Start/stop monitoring in Live monitoring, or PUT `/api/v1/cameras/{id}/monitor` with `enabled`, `segment_seconds` (5–300), `rule_ids`, and `tracker`. Shared camera leases prevent duplicate scheduling and fence stop operations. One active job per camera, a failed-segment cooldown and persisted configuration provide restart recovery. Independent tracking sessions reset at segment boundaries; processing/encoding creates capture gaps. This is continuous scheduling, not a gapless recorder or cross-segment tracker. `scripts/verify_monitoring.py` exercised two real localhost segments and stop. Maintenance should run separately so a busy worker does not delay scheduling/cleanup.

## Tenant controls and model promotion

Settings edits retention and default confidence/sampling; jobs snapshot those defaults and versioned rules. Account disable/role changes, admin password reset and self password changes revoke sessions. Own role/access changes require another administrator. Lists have stable offset/limit pagination (maximum 200). `/failures` lists failed jobs; existing retry/cancel actions are the recovery operations. `/cleanup` shows tenant cleanup attempts/errors; System health exposes pending cleanup and failed jobs. Cluster worker health uses host-qualified identifiers, without a remote alert service.

Provision trusted model files under `data/models` on every worker host. POST `/experiments` with `run_id`, `scope`, exact `model_sha256`, `dataset_sha256`, `held_out: true`, numeric `metrics`, `validated_capabilities` and `annotation_provenance`. This is an administrator's attestation, not automatic proof of annotation quality. Register filename/name/report ID in Model laboratory, then promote with a reason. Smoke/synthetic/demo/fixture reports cannot be promoted. Artifact hashes are verified at promotion, job submission and worker load; baseline rollback is available. Never place untrusted pickle-based weights in the provisioned directory.

POST `/calibrations` accepts camera ID, four or more distinct normalized image/world-meter pairs, two or more independent check pairs, error tolerance, scope and measured flag. Degenerate fits and check-error violations fail. Synthetic calibrations cannot activate metric proximity. Proximity requires the matching camera and validated person/forklift capabilities; PPE requires explicit negative classes, not missing generic detections. Calibration/validation import uses documented typed API inputs; no visual calibration editor is supplied.

## Signed audit and offline restore

With `$env:PYTHONPATH='services/api'`, run `python scripts/audit_manifest.py export <new-manifest-path>` and `python scripts/audit_manifest.py verify <manifest-path>`. Preserve manifest and secret separately. Maintenance seals audit rows; changes to existing sealed rows fail verification. Local administrators can remove or rewrite local files and secrets, so this is tamper evidence with an external anchor, not WORM storage.

Stop all API, workers and maintenance writers before `python scripts/backup.py snapshot data <new-backup-directory>`. Then `python scripts/backup.py restore <backup-directory> <new-data-directory>` verifies hashes, remaps local paths, checks SQLite integrity and revokes sessions. Restore requires the original secret for camera encryption. Configure both database URL and data directory to the restored location. Fixture snapshot/restore was tested; cloud objects, PostgreSQL backup and live point-in-time recovery are not implemented by this offline SQLite tool.
