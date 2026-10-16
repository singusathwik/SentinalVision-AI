"""Deterministic rules. Track footpoints and polygon vertices use normalized coordinates."""

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class Track:
    id: int
    label: str
    confidence: float
    box: tuple[float, float, float, float]

    @property
    def point(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, self.box[3])


def inside(p: tuple[float, float], polygon: list) -> bool:
    x, y = p
    result = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
        if (
            abs(cross) < 1e-9
            and min(a[0], b[0]) - 1e-9 <= x <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= y <= max(a[1], b[1]) + 1e-9
        ):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            result = not result
    return result


def side(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


class RuleEngine:
    def __init__(
        self,
        rules: list[dict],
        zones: dict[str, list],
        max_gap: float | None = None,
        calibrations: dict | None = None,
    ):
        self.calibrations = calibrations or {}
        self.rules = rules
        self.zones = zones
        self.since: dict[tuple, float] = {}
        self.last: dict[tuple, float] = {}
        self.active: set[tuple] = set()
        self.previous: dict[tuple, tuple[float, float]] = {}
        self.timestamp = -1.0
        self.max_gap = max_gap
        self.seen: dict[tuple, float] = {}
        self.resolved: list[str] = []

    def step(self, timestamp: float, tracks: list[Track]) -> list[dict[str, Any]]:
        if not math.isfinite(timestamp) or timestamp <= self.timestamp:
            raise ValueError("Timestamps must be finite and strictly increasing")
        self.resolved = []
        if self.max_gap and self.timestamp >= 0 and timestamp - self.timestamp > self.max_gap:
            self.resolved = [f"{k[0]}:{k[1]}" for k in self.active]
            self.since.clear()
            self.active.clear()
            self.previous.clear()
        self.timestamp = timestamp
        events = []
        observed: set[tuple] = set()
        new_previous = {}
        for rule in self.rules:
            candidates = [t for t in tracks if t.label in rule["classes"]]
            kind = rule["kind"]
            hits: list[tuple[str, list[Track], str]] = []
            if kind in ("intrusion", "dwell", "occupancy"):
                polygon = self.zones[rule["zone_id"]]
                candidates = [
                    t
                    for t in candidates
                    if inside(t.point, polygon)
                    or (
                        (rule["id"], str(t.id)) in self.active
                        and polygon_distance(t.point, polygon) <= rule.get("exit_margin", 0)
                    )
                ]
                if kind == "occupancy":
                    if len(candidates) > rule["threshold"]:
                        hits.append(
                            ("zone", candidates, f"occupancy {len(candidates)} > {rule['threshold']}")
                        )
                else:
                    hits = [(str(t.id), [t], "track footpoint inside restricted polygon") for t in candidates]
            elif kind == "line":
                a, b = rule["line"]
                for t in candidates:
                    key = (rule["id"], str(t.id))
                    old = self.previous.get(key)
                    new_previous[key] = t.point
                    if old:
                        s0, s1 = side(a, b, old), side(a, b, t.point)
                        direction = "positive" if s1 > s0 else "negative"
                        # Require intersection with the finite line segment, not its extension.
                        if (
                            s0 * s1 < 0
                            and side(old, t.point, a) * side(old, t.point, b) <= 0
                            and rule["direction"] in ("both", direction)
                        ):
                            hits.append((str(t.id), [t], f"line crossed {direction}"))
            elif kind == "proximity":
                for person in (t for t in tracks if t.label == "person"):
                    for forklift in (t for t in tracks if t.label == "forklift"):
                        from .capabilities import project

                        calibration = self.calibrations.get(rule.get("calibration_id"))
                        distance = (
                            math.dist(
                                project(calibration["matrix"], person.point),
                                project(calibration["matrix"], forklift.point),
                            )
                            if calibration
                            else math.dist(person.point, forklift.point)
                        )
                        if distance < rule["threshold"]:
                            hits.append(
                                (
                                    f"{person.id}:{forklift.id}",
                                    [person, forklift],
                                    f"distance {distance:.4f} < {rule['threshold']}; "
                                    + (
                                        "meters on calibrated ground plane"
                                        if calibration
                                        else "image-space; not meters"
                                    ),
                                )
                            )
            elif kind == "ppe":
                from .capabilities import explicit_ppe

                for person in (t for t in tracks if t.label == "person"):
                    matches = explicit_ppe(person, tracks, rule.get("equipment", "helmet"))
                    if matches:
                        hits.append(
                            (
                                str(person.id),
                                [person, *matches],
                                "explicit negative PPE detection associated to person; not inferred from absence",
                            )
                        )
            for identity, subjects, reason in hits:
                key = (rule["id"], identity)
                observed.add(key)
                self.seen[key] = timestamp
                start = self.since.setdefault(key, timestamp)
                duration = (
                    0
                    if kind == "line"
                    else max(rule["persistence"], rule["threshold"] if kind == "dwell" else 0)
                )
                if (
                    timestamp - start >= duration
                    and key not in self.active
                    and timestamp - self.last.get(key, -math.inf) >= rule["cooldown"]
                ):
                    self.active.add(key)
                    self.last[key] = timestamp
                    events.append(
                        {
                            "rule_id": rule["id"],
                            "rule_version": rule["version"],
                            "kind": kind,
                            "severity": rule["severity"],
                            "timestamp": timestamp,
                            "started_at": start,
                            "track_ids": [t.id for t in subjects],
                            "classes": [t.label for t in subjects],
                            "confidence": min(t.confidence for t in subjects),
                            "reason": reason,
                            "status": "needs_review",
                            "duration": timestamp - start,
                            "condition_key": f"{key[0]}:{key[1]}",
                        }
                    )
        grace = {r["id"]: r.get("exit_grace", 0) for r in self.rules}
        observed.update(k for k in self.active if timestamp - self.seen.get(k, -math.inf) <= grace[k[0]])
        self.resolved.extend(f"{k[0]}:{k[1]}" for k in self.active - observed)
        self.since = {k: v for k, v in self.since.items() if k in observed}
        self.active.intersection_update(observed)
        self.previous = new_previous
        return events


def polygon_distance(point, polygon) -> float:
    distances = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        fraction = max(
            0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / max(dx * dx + dy * dy, 1e-12))
        )
        distances.append(math.dist(point, (a[0] + fraction * dx, a[1] + fraction * dy)))
    return min(distances)
