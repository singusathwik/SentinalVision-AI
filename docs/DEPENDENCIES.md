# Dependency and license matrix

Resolved on 2026-10-16. `uv.lock` and `apps/web/package-lock.json` pin transitive versions. Native checks used Python 3.12.15 and Node 25.3.0; deployment targets Python 3.12 / Node 22 LTS. Do not assume the unexecuted container profile works merely because native checks pass.

| Component | Installed version | Evidence / terms |
|---|---|---|
| Next.js | 16.4.2 | Build and browser test executed; MIT |
| FastAPI | 0.143.2 | API integration tests and live HTTP executed; MIT |
| SQLAlchemy | 2.1.4 | Local SQLite tested; MIT |
| Pydantic | 2.14.1 | Runtime input validation tested; MIT |
| PyTorch | 2.14.1+cpu | CPU inference and one training epoch executed; BSD-style |
| Ultralytics | 8.4.178 | YOLO11n, ByteTrack and BoT-SORT executed; AGPL-3.0 / Enterprise |
| ONNX / Runtime | 1.23.2 / 1.31.0 | Export and sample agreement executed; Apache-2.0 / MIT |
| MLflow | 3.17.1 | Local SQLite run tracking executed; Apache-2.0 |
| Celery / Redis client | 5.6.3 / 8.1.0 | Adapter only; Redis service not executed |
| Dataset versioning | Local JSON/hash utility | DVC/diskcache removed from environment; compatible local pointer verification only |

Official references checked during implementation:
- https://nextjs.org/docs/app/getting-started/installation (Node minimum 20.9; shipped docs read for environment and Playwright behavior)
- https://fastapi.tiangolo.com/deployment/versions/
- https://docs.ultralytics.com/modes/track/ (explicitly select tracker; defaults can change)
- https://www.ultralytics.com/license (model/software terms require review before closed-source commercial distribution)

YOLO11n is a supported small baseline, not a claim to be the newest model. COCO weights do not provide helmet, vest or forklift classes. Supply validated industrial weights and an explicit capability registry before enabling those rules.

Security audit outcomes are recorded in IMPLEMENTATION_STATUS.md. An audit is a point-in-time dependency check, not a security certification.

The full npm audit and Python installed-environment audit now pass with zero findings. `eslint-config-next` was replaced to remove the unpatched braces dependency chain; TypeScript/React/hooks/accessibility linting remains enabled, but Next-specific preset rules are no longer used. Local dataset pointer verification replaces DVC CLI execution. FFmpeg H264 encoding is supplied through imageio-ffmpeg; review the bundled binary codec/license terms before redistribution. MediaMTX is a local protocol-test tool downloaded separately, not an application dependency.

PyAV 19.0.1 now decodes source timestamps and encodes variable-rate annotated MP4. Review PyAV and its linked FFmpeg codec licenses before distribution. Timing design reference: https://pyav.org/docs/stable/api/time.html and the upstream generate_video_with_pts.py example; installed-package roundtrip tests verify the API used here.
