"""Compare frozen checkpoints on a specified split. Never select on the test set."""

import argparse
import json
from pathlib import Path

from ultralytics import YOLO

parser = argparse.ArgumentParser()
parser.add_argument("--data", required=True)
parser.add_argument("--models", nargs="+", required=True)
parser.add_argument("--split", choices=["val", "test"], default="val")
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--output", default="data/evaluation/detection.json")
args = parser.parse_args()
results = []
for weights in args.models:
    metrics = YOLO(weights).val(
        data=args.data, split=args.split, device="cpu", imgsz=args.imgsz, batch=1, rect=False, plots=True
    )
    results.append(
        {
            "weights": weights,
            "split": args.split,
            "metrics": metrics.results_dict,
            "imgsz": args.imgsz,
            "batch": 1,
            "per_class_ap": [
                {
                    "class_id": int(cls),
                    "ap50": float(metrics.box.ap50[i]),
                    "ap50_95": float(metrics.box.ap[i]),
                }
                for i, cls in enumerate(metrics.box.ap_class_index)
            ],
            "artifacts": str(metrics.save_dir),
        }
    )
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(results, indent=2))
