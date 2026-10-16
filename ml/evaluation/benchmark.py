"""Measured model latency, separate stages, warm-up excluded. No quality claims."""

import argparse
import csv
import json
import platform
import time
from pathlib import Path

import cv2
import numpy as np
import psutil
from ultralytics import YOLO

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="yolo11n.pt")
parser.add_argument("--image", required=True)
parser.add_argument("--runs", type=int, default=30)
parser.add_argument("--warmup", type=int, default=5)
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--output", default="data/benchmarks/cpu")
args = parser.parse_args()
if args.runs < 2 or args.warmup < 1:
    raise SystemExit("Use at least two measured runs and one warm-up")
image = cv2.imread(args.image)
model = YOLO(args.model, task="detect")
samples = []
for i in range(args.runs + args.warmup):
    t = time.perf_counter()
    result = model(image, device="cpu", imgsz=args.imgsz, rect=False, verbose=False)[0]
    latency = (time.perf_counter() - t) * 1000
    if i >= args.warmup:
        samples.append({"end_to_end_ms": latency, **result.speed})
times = [s["end_to_end_ms"] for s in samples]
report = {
    "model": args.model,
    "device": "cpu",
    "hardware": platform.processor(),
    "platform": platform.platform(),
    "logical_cpus": psutil.cpu_count(),
    "rss_mb": psutil.Process().memory_info().rss / 1024**2,
    "batch": 1,
    "imgsz": args.imgsz,
    "warmup": args.warmup,
    "runs": args.runs,
    "p50_ms": float(np.percentile(times, 50)),
    "p95_ms": float(np.percentile(times, 95)),
    "p99_ms": float(np.percentile(times, 99)),
    "fps": 1000 / float(np.mean(times)),
    "stages_ms": {k: float(np.mean([s[k] for s in samples])) for k in result.speed},
    "scope": "decode excluded; model predict call; no tracking, rules or storage",
}
out = Path(args.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.with_suffix(".json").write_text(json.dumps(report, indent=2))
with out.with_suffix(".csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(samples[0]))
    writer.writeheader()
    writer.writerows(samples)
out.with_suffix(".md").write_text(
    "# Executed CPU benchmark\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n"
)
print(json.dumps(report, indent=2))
