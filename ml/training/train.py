"""Real transfer learning; smoke mode is explicitly not evidence of task accuracy."""

import argparse
import json
import re
from pathlib import Path

import mlflow
from ultralytics import YOLO

parser = argparse.ArgumentParser()
parser.add_argument("--data", required=True)
parser.add_argument("--model", default="yolo11n.pt")
parser.add_argument("--epochs", type=int, default=50)
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--batch", type=int, default=8)
parser.add_argument("--device", default="cpu")
parser.add_argument("--resume", action="store_true")
parser.add_argument("--smoke", action="store_true")
parser.add_argument("--output", default="data/training")


def main():
    args = parser.parse_args()
    if not args.smoke and not (Path(args.data).parent / "manifest.lock.json").exists():
        raise SystemExit("Run prepare.py first to establish provenance and grouped splits")
    mlflow.set_tracking_uri("sqlite:///data/mlflow.db")
    mlflow.set_experiment("sentinel-smoke" if args.smoke else "sentinel-detection")
    with mlflow.start_run() as run:
        mlflow.log_params({"requested_" + k: v for k, v in vars(args).items()})
        model = YOLO(args.model)
        model.train(
            data=args.data,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            seed=42,
            deterministic=True,
            workers=0,
            patience=10,
            amp=args.device != "cpu",
            project=args.output,
            name="smoke" if args.smoke else "finetune",
            exist_ok=True,
            resume=args.resume,
            plots=True,
        )
        metrics = model.val(data=args.data, split="val", device=args.device, imgsz=args.imgsz)
        measured = {k: float(v) for k, v in metrics.results_dict.items()}
        mlflow.log_metrics({re.sub(r"[^a-zA-Z0-9_./ -]", "_", k): v for k, v in measured.items()})
        Path(args.output).mkdir(parents=True, exist_ok=True)
        report = Path(args.output) / "validation.json"
        report.write_text(
            json.dumps(
                {"smoke_only": args.smoke, "metrics": measured, "data": args.data, "run_id": run.info.run_id},
                indent=2,
            )
        )
        mlflow.log_artifact(str(report))
        mlflow.log_artifacts(str(model.trainer.save_dir))


if __name__ == "__main__":
    main()
