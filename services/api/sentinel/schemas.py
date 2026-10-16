import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class Zone(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    points: list[tuple[float, float]] = Field(min_length=3, max_length=32)

    @model_validator(mode="after")
    def geometry(self):
        if any(not math.isfinite(v) or not 0 <= v <= 1 for p in self.points for v in p):
            raise ValueError("Coordinates must be finite and normalized to [0,1]")
        area = sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True)
        )
        if abs(area) < 1e-6:
            raise ValueError("Polygon must have nonzero area")
        if len(set(self.points)) != len(self.points):
            raise ValueError("Polygon vertices must be unique")
        from .rules import side

        edges = list(zip(self.points, self.points[1:] + self.points[:1], strict=True))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i or j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if side(a, b, c) * side(a, b, d) <= 0 and side(c, d, a) * side(c, d, b) <= 0:
                    if max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) and max(
                        min(a[1], b[1]), min(c[1], d[1])
                    ) <= min(max(a[1], b[1]), max(c[1], d[1])):
                        raise ValueError("Polygon edges may not self-intersect")
        return self


class Rule(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    version: int = Field(default=1, ge=1)
    kind: Literal["intrusion", "dwell", "occupancy", "line", "proximity", "ppe"]
    zone_id: str | None = None
    calibration_id: str | None = None
    equipment: Literal["helmet", "vest"] = "helmet"
    classes: list[str] = Field(default_factory=lambda: ["person"], min_length=1)
    persistence: float = Field(default=0.5, ge=0, le=3600)
    cooldown: float = Field(default=10, ge=0, le=86400)
    threshold: float = Field(default=1, gt=0)
    line: list[tuple[float, float]] | None = None
    direction: Literal["both", "positive", "negative"] = "both"
    severity: Literal["info", "warning", "critical"] = "warning"
    exit_grace: float = Field(default=0, ge=0, le=30)
    exit_margin: float = Field(default=0, ge=0, le=0.1)

    @model_validator(mode="after")
    def valid(self):
        if self.kind in ("intrusion", "dwell", "occupancy") and not self.zone_id:
            raise ValueError("This rule requires a zone")
        if self.kind == "line":
            if not self.line or len(self.line) != 2 or self.line[0] == self.line[1]:
                raise ValueError("Line requires two distinct points")
            if any(not math.isfinite(v) or not 0 <= v <= 1 for p in self.line for v in p):
                raise ValueError("Line coordinates must be normalized")
        return self


class JobRequest(BaseModel):
    video_id: str | None = None
    camera_id: str | None = None
    capture_seconds: int = Field(default=30, ge=1, le=300)
    tracker: Literal["bytetrack", "botsort"] = "bytetrack"
    rule_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(default=0.25, ge=0.05, le=0.95)
    sample_every: int = Field(default=1, ge=1, le=30)

    @model_validator(mode="after")
    def source(self):
        if bool(self.video_id) == bool(self.camera_id):
            raise ValueError("Choose exactly one video or authorized camera")
        return self


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["viewer", "operator", "admin"] = "viewer"


class Camera(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2048)
    authorized: Literal[True]


class Review(BaseModel):
    status: Literal["confirmed", "false_alarm", "needs_review"]
    note: str = Field(default="", max_length=1000)
