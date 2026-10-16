"""Compact track labels with collision-aware placement and connecting lines."""

from typing import Any

import cv2

FONT = cv2.FONT_HERSHEY_SIMPLEX
COLORS = [(180, 155, 45), (90, 175, 75), (60, 155, 220), (200, 125, 155), (190, 160, 95)]


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def layout(tracks, width, height):
    scale = max(0.35, min(0.55, width / 1600))
    boxes = {
        t.id: tuple(
            int(max(0, min(1, v)) * (width - 1 if i % 2 == 0 else height - 1)) for i, v in enumerate(t.box)
        )
        for t in tracks
    }
    placed: list[dict[str, Any]] = []
    for track in sorted(tracks, key=lambda t: (t.label != "person", t.id)):
        text = f"{track.label.replace('_', ' ').capitalize()} #{track.id}"
        (tw, th), baseline = cv2.getTextSize(text, FONT, scale, 1)
        label_w, label_h = min(width - 4, tw + 12), th + baseline + 10
        x1, y1, x2, y2 = boxes[track.id]
        anchor = ((x1 + x2) / 2, y1)

        def rect(x, y, label_w=label_w, label_h=label_h):
            x = max(2, min(width - label_w - 2, int(x)))
            y = max(34, min(height - label_h - 2, int(y)))
            return (x, y, x + label_w, y + label_h)

        candidates = [
            rect(x1, y1 - label_h - 4),
            rect(x1, y2 + 4),
            rect(x2 + 5, y1),
            rect(x1 - label_w - 5, y1),
        ]
        # Search nearby rows and then the frame when people crowd together.
        candidates += [
            rect(x, y)
            for y in range(34, height - label_h, label_h + 5)
            for x in range(2, width - label_w, max(24, label_w // 2))
        ]

        def cost(r, anchor=anchor):
            collisions = sum(
                intersection(r, (p["rect"][0] - 3, p["rect"][1] - 3, p["rect"][2] + 3, p["rect"][3] + 3))
                for p in placed
            )
            cover = sum(intersection(r, b) for b in boxes.values())
            distance = abs((r[0] + r[2]) / 2 - anchor[0]) + abs(r[3] - anchor[1])
            return collisions * 100000 + cover * 4 + distance

        chosen = min(candidates, key=cost)
        placed.append(
            {
                "id": track.id,
                "text": text,
                "rect": chosen,
                "box": boxes[track.id],
                "scale": scale,
                "text_height": th,
                "color": COLORS[track.id % len(COLORS)],
            }
        )
    return placed


def draw_tracks(frame, tracks):
    height, width = frame.shape[:2]
    placements = layout(tracks, width, height)
    for item in placements:
        x1, y1, x2, y2 = item["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), item["color"], 1, cv2.LINE_AA)
    for item in placements:
        x, y, right, bottom = item["rect"]
        bx, by, br, bb = item["box"]
        origin = (int(max(x, min(right, (bx + br) / 2))), int(max(y, min(bottom, by))))
        target = (int(max(bx, min(br, origin[0]))), int(max(by, min(bb, origin[1]))))
        cv2.line(frame, origin, target, item["color"], 1, cv2.LINE_AA)
    for item in placements:
        x, y, right, bottom = item["rect"]
        cv2.rectangle(frame, (x, y), (right, bottom), (28, 34, 39), -1)
        cv2.rectangle(frame, (x, y), (x + 3, bottom), item["color"], -1)
        cv2.putText(
            frame,
            item["text"],
            (x + 7, y + item["text_height"] + 4),
            FONT,
            item["scale"],
            (250, 250, 250),
            1,
            cv2.LINE_AA,
        )
    return frame
