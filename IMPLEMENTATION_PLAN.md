# Implementation plan

Build a genuine CPU-first vertical slice, then extend it with reproducible ML and operations tooling. This checkout began empty on 2026-10-16. Docker is absent on the authoring host; Compose validation must be reported separately.

## Architecture and acceptance
API owns authentication, tenant-scoped metadata and job submission. A separate worker claims durable database jobs (local alternative to Redis), runs a fresh YOLO tracking session per job, evaluates versioned rules, and saves annotated evidence. Browser uses authenticated API calls. PostgreSQL/Redis/S3 deployment adapters are separate from local SQLite/filesystem operation.

Acceptance: sign in; upload a valid bounded video; configure polygon; queue a real pretrained detector; observe persisted tracks/events/evidence; review an event with audit history; cancel jobs; reject cross-tenant access. Measure actual CPU inference, never claim synthetic fixture accuracy as real performance.

## Ordered checklist
- [x] Phase 0: dependency matrix, architecture, baseline
- [x] Phase 1: persistence, authentication, API and local startup
- [x] Phase 2: asynchronous uploaded video inference
- [x] Phase 3: isolated ByteTrack/BoT-SORT sessions and trajectories
- [x] Phase 4: polygon, dwell, occupancy and temporal tests
- [x] Phase 5: evidence and Next.js workflow
- [x] Phase 6: source-group dataset validation and training scripts
- [ ] Phase 7: line/proximity rules; gate unsupported PPE
- [x] Phase 8: MLflow/export/benchmark tooling
- [x] Phase 9: local analytics, playback, camera/account controls and operational views
- [x] Phase 10: local security tests, clean audits, browser CI launcher and documentation
- [x] Phase 11: run end-to-end and record exact evidence

Each subsystem is verified with pytest or frontend build/type checks. Live model execution is additionally exercised through HTTP with a public sample image transformed into an explicitly labeled test video. Training quality, held-out tracking metrics, GPU and cloud execution require external resources and must not be inferred.

## Final scope note
Checked phases indicate the native/local milestone, not every enterprise requirement. See IMPLEMENTATION_STATUS.md for external blockers and unfinished engineering.

Continuation completed live-fixture ingestion, restart recovery, clips, S3 emulator integration, session revocation, request limits, outbox/fencing, retention and research-tool checks. Domain PPE/calibration and production service validation remain gated as detailed in IMPLEMENTATION_STATUS.md.
