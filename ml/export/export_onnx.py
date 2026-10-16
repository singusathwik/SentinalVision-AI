"""Export fixed-shape FP32 ONNX and check predictions against PyTorch on a real image."""

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from ultralytics import YOLO

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="yolo11n.pt")
parser.add_argument("--image", required=True)
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--output", default="data/evaluation/onnx-agreement.json")
args = parser.parse_args()
model = YOLO(args.model)
path = model.export(format="onnx", imgsz=args.imgsz, dynamic=False, simplify=False, opset=17)
session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
tensor = np.random.default_rng(42).random((1, 3, args.imgsz, args.imgsz), dtype=np.float32)
model.model.eval()
with torch.no_grad():
    reference = model.model(torch.from_numpy(tensor))
    if isinstance(reference, (tuple, list)):
        reference = reference[0]
    reference = reference.numpy()
actual = session.run(None, {session.get_inputs()[0].name: tensor})[0]
raw_ok = bool(np.allclose(reference, actual, rtol=1e-3, atol=1e-3))
a = YOLO(args.model)(args.image, imgsz=args.imgsz, rect=False, verbose=False)[0].boxes
b = YOLO(path, task="detect")(args.image, imgsz=args.imgsz, rect=False, verbose=False)[0].boxes


# Sort by class/confidence to avoid relying on backend output ordering.
def rows(boxes):
    rows = boxes.data.cpu().numpy()
    return rows[np.lexsort((-rows[:, 4], rows[:, 5]))] if len(rows) else rows


ra, rb = rows(a), rows(b)
detection_ok = ra.shape == rb.shape and bool(
    np.array_equal(ra[:, 5], rb[:, 5])
    and np.allclose(ra[:, :4], rb[:, :4], atol=0.5, rtol=0.001)
    and np.allclose(ra[:, 4], rb[:, 4], atol=0.001, rtol=0.001)
)
report = {
    "model": args.model,
    "onnx": path,
    "shape": list(tensor.shape),
    "precision": "FP32",
    "raw_max_absolute_error": float(np.max(np.abs(reference - actual))),
    "raw_allclose": raw_ok,
    "detection_counts": [len(ra), len(rb)],
    "detection_agreement": detection_ok,
    "validation_scope": "one image plus one seeded tensor; not dataset-wide equivalence",
}
out = Path(args.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if not raw_ok or not detection_ok:
    raise SystemExit("ONNX agreement failed")
