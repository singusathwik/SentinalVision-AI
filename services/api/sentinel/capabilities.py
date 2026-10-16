"""Ground-plane calibration and explicit PPE association, never absence inference."""

import math

import cv2
import numpy as np
from pydantic import BaseModel, Field, model_validator


class Calibration(BaseModel):
    camera_id: str
    image_points: list[tuple[float, float]] = Field(min_length=4, max_length=100)
    world_points: list[tuple[float, float]] = Field(min_length=4, max_length=100)
    check_image_points: list[tuple[float, float]] = Field(min_length=2, max_length=100)
    check_world_points: list[tuple[float, float]] = Field(min_length=2, max_length=100)
    max_error_meters: float = Field(gt=0, le=1)
    scope: str = Field(min_length=5, max_length=500)
    measured: bool = False

    @model_validator(mode="after")
    def pairs(self):
        if len(self.image_points) != len(self.world_points) or len(self.check_image_points) != len(
            self.check_world_points
        ):
            raise ValueError("Calibration pairs must align")
        for points in (
            self.image_points,
            self.world_points,
            self.check_image_points,
            self.check_world_points,
        ):
            if any(not math.isfinite(v) for p in points for v in p):
                raise ValueError("Coordinates must be finite")
        if any(not 0 <= v <= 1 for p in [*self.image_points, *self.check_image_points] for v in p):
            raise ValueError("Image coordinates must be normalized")
        if len(set(self.image_points)) != len(self.image_points) or set(self.image_points) & set(
            self.check_image_points
        ):
            raise ValueError("Fit points must be unique and check points independent")
        if len(set(self.check_image_points)) != len(self.check_image_points):
            raise ValueError("Check points must be unique")
        return self


def project(matrix, point):
    value = np.asarray(matrix) @ np.array([*point, 1.0])
    if abs(value[2]) < 1e-9:
        raise ValueError("Point projects to infinity")
    return (value[:2] / value[2]).tolist()


def fit(calibration: Calibration):
    matrix, _ = cv2.findHomography(
        np.asarray(calibration.image_points), np.asarray(calibration.world_points), method=0
    )
    if matrix is None or abs(np.linalg.det(matrix)) < 1e-9:
        raise ValueError("Degenerate calibration")
    errors = [
        math.dist(project(matrix, a), b)
        for a, b in zip(calibration.check_image_points, calibration.check_world_points, strict=True)
    ]
    if max(errors) > calibration.max_error_meters:
        raise ValueError("Held-out calibration error exceeds tolerance")
    return {**calibration.model_dump(), "matrix": matrix.tolist(), "maximum_check_error_meters": max(errors)}


def explicit_ppe(person, detections, equipment="helmet"):
    """Associate an explicit no_helmet/no_vest detection to a visible body region."""
    x1, y1, x2, y2 = person.box
    end = y1 + (y2 - y1) * (0.4 if equipment == "helmet" else 0.85)
    matches = []
    for detection in detections:
        if detection.label != "no_" + equipment:
            continue
        a, b, c, d = detection.box
        intersection = max(0, min(x2, c) - max(x1, a)) * max(0, min(end, d) - max(y1, b))
        if intersection / max((c - a) * (d - b), 1e-12) >= 0.5:
            matches.append(detection)
    return matches
