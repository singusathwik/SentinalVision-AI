from pathlib import Path
from typing import Any

from .rules import Track


class YOLOSession:
    """A model and tracker instance owned by exactly one processing session."""

    def __init__(self, weights: str, tracker: str, confidence: float, device: str):
        from ultralytics import YOLO

        if weights not in ("yolo11n.pt", "yolo26n.pt") and not Path(weights).is_file():
            raise FileNotFoundError("Configured model weights are missing")
        self.model = YOLO(weights, task="detect")
        self.tracker = tracker + ".yaml"
        self.confidence = confidence
        self.device = device

    def infer(self, frame):
        results: Any = self.model.track(
            frame, persist=True, tracker=self.tracker, conf=self.confidence, device=self.device, verbose=False
        )
        result = results[0]
        tracks = []
        height, width = frame.shape[:2]
        if result.boxes.id is not None:
            for box, identity, cls, conf in zip(
                result.boxes.xyxy.cpu().tolist(),
                result.boxes.id.cpu().tolist(),
                result.boxes.cls.cpu().tolist(),
                result.boxes.conf.cpu().tolist(),
                strict=True,
            ):
                tracks.append(
                    Track(
                        int(identity),
                        result.names[int(cls)],
                        float(conf),
                        (box[0] / width, box[1] / height, box[2] / width, box[3] / height),
                    )
                )
        return tracks, frame.copy(), result.speed
