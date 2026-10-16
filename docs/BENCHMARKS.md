# Executed measurements

Measured 2026-10-16 on Windows 11, Intel Core i5-13500H, 16 logical CPUs, CPU-only PyTorch 2.14.1 and ONNX Runtime 1.31.0. These small local measurements are not capacity guarantees or industrial accuracy evidence.

| Backend | p50 ms | p95 ms | p99 ms | Mean-derived FPS |
|---|---:|---:|---:|---:|
| PyTorch YOLO11n | 52.42 | 56.80 | 59.85 | 19.03 |
| ONNX YOLO11n | 44.08 | 64.24 | 77.52 | 21.07 |

Protocol: one public bus image, batch 1, fixed 640×640 input (`rect=False`), five warm-up calls excluded, 30 measured calls. End-to-end here means the model `predict` call including preprocessing and postprocessing; it excludes disk decode, tracking, rules, storage, network and UI. ONNX had lower median but worse measured tails; do not describe it as universally faster. These runs were not isolated from all host activity and have no confidence interval.

JSON/CSV observations and stage timings are in `docs/results/{pytorch,onnx}.*`. Resident process memory was measured, not peak GPU utilization. No GPU benchmark occurred.

ONNX export: static BCHW 1×3×640×640, FP32, opset 17. Raw tensor agreement passed `rtol=1e-3, atol=1e-3`; maximum absolute difference was 0.00494 (relative tolerance matters). Both implementations returned five detections on one sample image with matching classes and the documented box/confidence tolerance. This is a smoke check, not validation across a dataset.

The first pipeline run processed 30 repeated-image frames and stored four person-zone events. Its cold start included tracker/model setup costs and is intentionally not mixed into the warmed model comparison. Four observed events are a pipeline result, not event recall.

Training: a genuine one-epoch COCO8 CPU run completed, with 4 train and 4 validation images and MLflow run `2d5964700e2d467684586cfb6f95ff13`. Its numeric smoke metrics are archived in `docs/results/validation.json`; they are not domain performance or evidence of fine-tuning improvement. No production weights were promoted.
