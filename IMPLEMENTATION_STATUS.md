# Implementation status — 2026-10-16

**Locally verified CPU application. Industrial accuracy, gapless camera recording and production deployment are not established.** The previous six engineering-boundary bullets are reconciled below. Code completion and external validation are separate claims.

## Executed verification

| Check | Outcome and scope |
|---|---|
| Python | **68 passed**, 76.76% statement coverage. Auth/tenant boundaries, concurrency/fencing, cleanup retries, scheduling/stop, calibration/PPE rules, registry/hash/rollback, audit tampering, backup/restore, pagination and variable-rate PTS roundtrip are covered. Integration runs are separate from coverage. |
| Quality | Ruff, mypy (21 API modules), frontend ESLint, TypeScript and Next production build passed. |
| Clean dependencies | `npm ci` passed in original C checkout and independent D validation copy after repairing the lockfile. Full npm and installed Python dependency audits: **0 known findings**. |
| Browser | **4 Edge tests passed**: login/review/mobile; upload/polygon/real BoT-SORT inference/annotated playback/clips; operations/delete/logout; tenant defaults/account disable-enable/password reset/rule revision. API pagination has separate tests. |
| Full workflow | Isolated SQLite/API/worker/web launcher passed in both checkouts. Real YOLO11n + ByteTrack demo produced 4 observations from a repeated public image. This is workflow evidence, not ground truth. |
| RTSP | PyAV source-PTS → real YOLO inference → preview/H264 playback: 48 processed frames and 65 dropped frames reported. Restart fixture received 185 frames, recovered twice and maintained increasing timestamps. |
| Continuous scheduling | Two real localhost RTSP segments completed and produced playable evidence; stop prevented another job. Concurrent scheduler and stop-conflict tests passed. Not a gapless recording test. |
| Storage | Previously executed Moto HTTP S3 upload/presign/rehydration/deletion evidence retained. New durable cleanup failure/retry and orphan protection tests passed. Not AWS or MinIO validation. |
| Migrations | Fresh SQLite upgrade through **003** and Alembic schema check passed with no drift. |
| Research | Three real upstream configurations regenerated tracks: PyTorch 320 ByteTrack, PyTorch 640 BoT-SORT/sampling, ONNX 640 ByteTrack. Five-frame execution smoke only. Actor-aware interval matching and indexed duplicate screening tested; prior 32-config rule replay/bootstrap/MOT export retained. |
| Operational recovery | Owned-process restart, offline SQLite/media snapshot/restore, session invalidation on restore, signed-audit export/tamper detection and storage retry tests passed. |
| Earlier ML evidence | COCO8 one-epoch CPU training, MLflow, baseline/checkpoint validation, ONNX sample agreement and warmed CPU benchmarks retained. Smoke weights remain unpromoted. |

Raw evidence is under `docs/results/`; `test-summary.json` describes the final run. Current audit files supersede historical `dependency-findings.json`. C: disk exhaustion interrupted an earlier run; after space was freed, clean installation, build, full tests and workflow were rerun successfully. A validation copy remains at `D:\SentinelVision-validation-20261016`; source of truth and final tests are in this checkout. No credentials are included in published reports.

## Disposition of the previous remaining engineering items

| Previously pending item | Implemented locally | Exact boundary |
|---|---|---|
| Camera supervision, PTS and variable-rate playback | Persisted start/stop settings; shared per-camera lease; successive jobs; cooldown/recovery; decoder PTS with monotonic reconnect epochs and receive fallback; timestamped annotated MP4. | Independent bounded segments reset tracks and may have capture gaps. Raw source AVI remains constant-rate. Camera clock synchronization is not implemented. |
| Contracts, pagination, tenant defaults, identities, registry | JSON response schemas on every JSON operation; named core entity models, JSON-valued extensible audit/telemetry payloads; stable paginated API/UI lists; retention/confidence/sampling forms; versioned rule edits; disable/enable/roles/password reset/change with session revocation; hashed candidate registry/promotion/baseline rollback. | Internal metadata deliberately remains a JSON record store. Calibration and evaluation imports use the API, not visual editors. Imported validation is administrator-attested; software cannot establish its scientific validity. |
| Calibration and PPE integration | Homography fit and independent check-error validation; matching-camera calibration snapshots; metric rule engine; explicit negative-PPE detection/person association; model capability gates. | Generic COCO weights cannot activate these capabilities. Physical calibration and held-out industrial/PPE evaluation still need real measurements/labels. No inference from an absent helmet detection. |
| Upstream ablations, actor intervals, duplicate screening | Fresh detector/backend/resolution/tracker/sampling runs and hashed output; actor-mapped interval-IoU maximum-cardinality matching; exact radius-3 hash-band candidate indexing plus grayscale screen. | No benchmark accuracy results. Actor mapping must be provided. Duplicate-index collisions retain a quadratic worst case; screening does not prove source independence. |
| Durable storage deletion, orphans and audit | Metadata deletion and cleanup task commit together; idempotent retry; aged orphan sweep protecting active/referenced artifacts; visible cleanup backlog; signed audit files and separately protectable manifests. | Eventual deletion, not a distributed transaction. Local privileged users can alter local data/secrets; true WORM storage needs an external anchor. |
| Celery maintenance, supervision, dead letters and observability | Shared maintenance runs in native and Celery outbox profiles; restart/backoff supervisor; Compose maintenance/restart definitions; failed-job listing/retry; host-qualified heartbeats and cleanup/failure health counts. | Real broker/PostgreSQL failover and fleet load not executed. External alert transport and deployment-time service installation are not supplied. |

## Genuine external validation blockers

| Resource unavailable here | What it unlocks | Existing executable path |
|---|---|---|
| Docker/Linux service host or provisioned PostgreSQL/Redis/MinIO | Container builds, dialect/concurrency, real broker delivery/failover, storage policy and multi-host load verification | Compose definitions, Celery outbox/maintenance, storage adapter; native SQLite and emulator coverage already executed. Docker/redis-server/psql commands were not available on this host. |
| Authorized physical cameras and network | Device codecs/authentication/redirects, long-running VFR behavior, outage recovery and measured clock alignment | PTS decoder, scheduler and restart fixtures are implemented; physical validation is not replaceable by localhost tests. |
| Licensed independent industrial/PPE footage and actor/interval labels | Domain training, confidence calibration, per-class mAP, event metrics, tracking benchmark results | Preparation, training, upstream/replay/interval tools and capability registry. No invented RQ result or accuracy improvement. |
| Measured camera ground-plane correspondences and check points | Scene-specific metric proximity validation and error bounds | Calibration API and metric engine; synthetic unit fixtures are not field measurements. |
| CUDA hardware/driver stack | GPU throughput, numerical agreement and large training validation | Device-selectable training/inference; CPU is verified. TensorRT-specific integration is separate unfinished work below. |
| Production infrastructure/credentials and operational decisions | TLS, restricted egress, remote immutable audit anchoring, cloud object policy, alert destinations, production recovery exercises | Local audit/backup/supervision and private S3 adapters exist. No deployment or independent penetration test occurred. |

## Unfinished product extensions — not external-resource excuses

The locally implementable work in the six prior engineering items is delivered within the boundaries above. These broader enterprise extensions remain actual implementation work and are **not** described as features waiting only for credentials:

- Gapless persistent camera sessions, continuity of tracking across segments, and cross-device clock synchronization.
- Provider-specific SSO/MFA, remote alert delivery, automated secret rotation, OS boot-service packaging and decoder process sandboxing.
- Visual calibration/annotation editors, a fully normalized relational metadata redesign, and generated end-to-end frontend clients. Public contracts intentionally retain typed JSON maps for extensible payloads.
- Automated TrackEval HOTA/IDF1 orchestration, TensorRT serving/export integration, Kubernetes deployment, online/PostgreSQL/S3 backup orchestration and true remote WORM enforcement.

These extensions are outside the tested native acceptance profile; they are not covered by the passing tests or represented as complete. Production service validation additionally requires the resources above.

## Acceptance A–L

A–F pass locally: startup, sign-in/upload, separate inference worker, rendered tracks/timestamps, polygon observations and reviewed evidence. G includes trusted model registration/promotion and per-job tracker snapshots. H–I have executed training/evaluation/export/benchmark paths with fixture limits. J includes local tests and clean point-in-time dependency audits. K has the reproducible demo/interview guide. L is the explicit disposition and blocker record above. No industrial safety certification or production-readiness claim is made.


## Plain-language video workflow and local cleanup � 2026-10-16

Video results and camera captures now display the source video name, including when the video library is on a different page. Names are resolved with tenant checks; missing or cross-tenant references show �Video unavailable�. Optional alerts explain area-entry detection without showing internal rule IDs. Playback, retry and stop buttons use plain language; diagnostic failures remain available under Technical details. Missing durations show Not available.

At the user's request, the regular local workspace was cleaned: 13 duplicate or failed demo uploads and their associated results were removed through the audited video lifecycle; 7 browser-test rules and 1 duplicate bus-demo rule were removed. Three sample videos remain, including the latest moving-people video with clean labels, plus two clearly named sample alerts. Source files in sample videos remain intact. The scoped cleanup manifest is in ignored data/cleanup-review.json. Historical inference configurations retain their original snapshots.

Validation: 71 Python tests passed, including video-name tenant isolation and missing-reference coverage; Ruff and mypy passed. Frontend lint, typecheck and production build passed. Four isolated browser workflow tests passed (upload, real inference, playback, evidence review, accounts/settings and deletion); they did not repopulate the regular workspace. After cleanup, all nine pages at 1440, 768, 390 and 320 pixels passed overflow and browser-error checks. The retained walking sample played successfully in the regular app, with three named results, two alerts and no browser-test rules or short rule IDs. Layout evidence: data/layout-audit/clarity-cleanup/. No external resources were required for this change.
