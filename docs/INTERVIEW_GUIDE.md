# Engineering interview guide

## Four-minute demonstration
1. **0:00–0:35** Explain the warehouse restricted-zone use case and show the overview. State that the sample is a repeated public image, not an industrial accuracy benchmark.
2. **0:35–1:15** Sign in, select a reference frame in Zone editor, draw a polygon or use the inset rectangle, save its intrusion rule. Show normalized coordinates and explain that track footpoints are used.
3. **1:15–2:00** Upload `data/demo/static-bus-test.avi`, select the rule and ByteTrack, click Analyze. Explain that a separate process handles inference while the API serves requests. Observe queued/running/completed states.
4. **2:00–2:45** Open Safety events, inspect an actual frame with track IDs and polygon overlay. Explain timestamp, confidence, persistence and cooldown. Mark an observation needs review/confirmed; show the audit endpoint.
5. **2:45–3:20** Show `docs/results` and explain CPU benchmark protocol, warm-up, p95, and why ONNX mean speed is not a guarantee of better tail latency. Distinguish the model-only benchmark from cold pipeline timings.
6. **3:20–4:00** Show tests, one real COCO8 training epoch and MLflow artifacts. Close with explicit gaps: real industrial/PPE data, calibrated geometry, live-camera integration and distributed deployment validation.

## Decisions and tradeoffs

**Detector.** YOLO11n provides a maintained small pretrained baseline that runs locally on CPU. It does not detect forklift/PPE merely because these are requested classes. Supported labels and validated domain performance are different claims. Ultralytics terms require AGPL/Enterprise consideration.

**Training and losses.** The detector learns bounding box localization, class probabilities and distributional box regression. The executed YOLO11 recipe reports box, classification and DFL losses; explain these from the configured model implementation, not a claim that every YOLO version uses identical loss terms. Transfer learning starts from pretrained weights, then adapts on labeled domain footage. A single tiny smoke epoch verifies optimizer/checkpoint/logging execution, not useful generalization.

**Leakage.** Neighboring frames are strongly correlated. Group source videos (and ideally site/camera/day identities) before partitioning. Decode/hash duplicate images, audit near-duplicates and freeze validation choices before evaluating a final test set. Do not tune thresholds to this demo or report its detections as mAP.

**Tracking.** ByteTrack associates high-confidence detections first and then uses lower-confidence detections to recover trajectories. BoT-SORT adds motion compensation and optional appearance handling; appearance ReID is disabled here. Kalman filtering predicts state under noisy observations. Assignment uses a cost matrix and gating. IDs are session-local trajectory identifiers, not human identities. The executed isolation test uses static footage; it cannot establish IDF1 or occlusion robustness.

**Rules.** A track's bottom-center point is evaluated against normalized polygons. Persistence requires repeated observed presence across media timestamps. Dwell and occupancy have distinct predicates. Active suppression avoids repeated alerts while a condition remains active; cooldown controls re-entry. Line crossing checks a finite segment and direction. Missing detections reset presence in this version. Variable-frame-rate timestamps, spatial exit hysteresis and lifecycle resolution need further work.

**Asynchrony.** The API saves metadata and a durable job; the worker atomically claims it. Local SQLite makes the project executable without services. Bounded sequential file decoding supplies natural backpressure. Lease expiry can recover process loss, but distributed fencing and transactional broker dispatch require more engineering. Cancellation is cooperative between frames, not immediate interruption of a running model call.

**Evidence.** An event stores why it triggered, rule version, model, timestamp, tracks and annotated frame. Review status is separate from machine output. Reviewer changes append audit records. No unsupported tracking confidence or calibrated event probability is invented.

**ONNX.** Exporting is not proof of equivalence. Compare raw tensors and detection outputs after identical resizing/padding/NMS settings. The initial check exposed different rectangular preprocessing; fixed-square inputs resolved the discrepancy. The executed agreement check covers one image and one seeded tensor. More inputs are needed before promotion.

**Metrics.** Detection AP measures boxes/classes. Tracking MOTA, IDF1 and HOTA need trajectory ground truth and measure different failure modes. Event precision/recall operate on event onsets under a stated matching tolerance. Count false alarms per video-hour and report detection delay. Bootstrap entire videos rather than correlated frames.

**Scaling and security.** Separate ingestion, control and inference capacity. Introduce supervised workers, authenticated object storage, retention automation and least-privilege infrastructure. Test tenant isolation on every path. RTSP URLs are server-side secrets; registration does not imply a connection. A native local test is not evidence of production or cloud deployment.
