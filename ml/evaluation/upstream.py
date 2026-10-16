"""Regenerate tracks for each detector/backend/resolution/tracker ablation.

JSON: {scope, configurations:[{model,tracker,imgsz,confidence,sample_every,tracker_options}]}.
Never use held-out test data for selection. Each configuration owns a new tracker.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import ultralytics
import yaml
from ultralytics import YOLO


def run(video: Path, specification: dict, output: Path, max_frames: int = 300):
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for index, config in enumerate(specification["configurations"]):
        if config["tracker"] not in ("bytetrack", "botsort"):
            raise ValueError("Unsupported tracker")
        model_path = Path(config["model"])
        if not model_path.is_file():
            raise ValueError("Provision local weights before experiments")
        tracker = yaml.safe_load(
            (Path(ultralytics.__file__).parent / "cfg/trackers" / (config["tracker"] + ".yaml")).read_text()
        )
        overrides = config.get("tracker_options", {})
        if not set(overrides).issubset(
            {"track_high_thresh", "track_low_thresh", "new_track_thresh", "match_thresh", "track_buffer"}
        ):
            raise ValueError("Unknown tracker override")
        tracker.update(overrides)
        tracker["with_reid"] = False
        tracker_path = output / f"tracker-{index}.yaml"
        tracker_path.write_text(yaml.safe_dump(tracker))
        model = YOLO(str(model_path), task="detect")
        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not cap.isOpened() or fps <= 0:
            raise ValueError("Invalid source")
        timings, rows = [], []
        try:
            for frame_no in range(max_frames):
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_no % config.get("sample_every", 1):
                    continue
                started = time.perf_counter()
                r = model.track(
                    frame,
                    tracker=str(tracker_path),
                    persist=True,
                    conf=config.get("confidence", 0.25),
                    imgsz=config.get("imgsz", 640),
                    device="cpu",
                    verbose=False,
                )[0]
                timings.append((time.perf_counter() - started) * 1000)
                tracks = []
                if r.boxes.id is not None:
                    for box, identity, cls, confidence in zip(
                        r.boxes.xyxyn.tolist(),
                        r.boxes.id.tolist(),
                        r.boxes.cls.tolist(),
                        r.boxes.conf.tolist(),
                        strict=True,
                    ):
                        tracks.append(
                            {
                                "id": int(identity),
                                "label": r.names[int(cls)],
                                "confidence": confidence,
                                "box": box,
                            }
                        )
                rows.append(
                    {
                        "timestamp": frame_no / fps,
                        "width": frame.shape[1],
                        "height": frame.shape[0],
                        "tracks": tracks,
                    }
                )
        finally:
            cap.release()
        if not rows:
            raise ValueError("No frames decoded")
        (output / f"tracks-{index}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        reports.append(
            {
                "configuration": config,
                "frames": len(rows),
                "mean_ms": sum(timings) / len(timings),
                "cold_start_included": True,
                "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            }
        )
    report = {
        "scope": specification["scope"],
        "source_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "runs": reports,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("specification", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=300)
    args = parser.parse_args()
    run(args.video, json.loads(args.specification.read_text()), args.output, args.max_frames)
