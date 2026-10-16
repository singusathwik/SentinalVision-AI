"""Validate a licensed manifest and emit group-safe YOLO splits with SHA256 provenance.

Manifest: {names: [...], license: str, source: str, samples: [{image, label, group}]}
Paths are relative to manifest location. Each source video/scene has one group.
"""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import yaml


def prepare(manifest: Path, output: Path):
    data = json.loads(manifest.read_text())
    if not data.get("license") or not data.get("source") or not data.get("names"):
        raise ValueError("Dataset requires explicit license, provenance and classes")
    groups, digests, accepted = {}, {}, []
    perceptual = []
    bands = {}
    for sample in data["samples"]:
        image = (manifest.parent / sample["image"]).resolve()
        label = (manifest.parent / sample["label"]).resolve()
        if (
            image.parent.name != "images"
            or label.parent.name != "labels"
            or image.parent.parent != label.parent.parent
            or image.stem != label.stem
        ):
            raise ValueError("Use paired images/name.jpg and labels/name.txt YOLO layout")
        frame = cv2.imread(str(image))
        if frame is None:
            raise ValueError(f"Corrupt image: {image}")
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        if digest in digests:
            raise ValueError(f"Duplicate decoded image: {image} and {digests[digest]}")
        digests[digest] = str(image)
        # Conservative cross-source near-duplicate gate. Same-source adjacent frames
        # are permitted because the entire group stays in a single split.
        thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 32))
        small = cv2.resize(thumb, (9, 8))
        bits = small[:, 1:] > small[:, :-1]
        code = int.from_bytes(np.packbits(bits).tobytes(), "big")
        candidates = set()
        # Hamming distance <=3 implies at least one identical 16-bit band.
        for band in range(4):
            candidates.update(bands.get((band, (code >> (16 * band)) & 65535), []))
        for candidate in sorted(candidates):
            previous, previous_bits, previous_group, previous_path = perceptual[candidate]
            if str(sample["group"]) != previous_group and np.count_nonzero(bits != previous_bits) <= 3:
                if np.abs(thumb.astype(float) - previous.astype(float)).mean() <= 12:
                    raise ValueError(
                        f"Possible cross-source near duplicate: {image} and {previous_path}; audit grouping"
                    )
        for band in range(4):
            bands.setdefault((band, (code >> (16 * band)) & 65535), []).append(len(perceptual))
        perceptual.append((thumb, bits, str(sample["group"]), str(image)))
        for row in label.read_text().splitlines():
            values = [float(v) for v in row.split()]
            if len(values) != 5 or not values[0].is_integer() or not 0 <= values[0] < len(data["names"]):
                raise ValueError(f"Invalid class/annotation: {label}")
            _, x, y, w, h = values
            if (
                not all(0 <= v <= 1 for v in (x, y, w, h))
                or min(w, h) <= 0
                or x - w / 2 < -1e-6
                or y - h / 2 < -1e-6
                or x + w / 2 > 1 + 1e-6
                or y + h / 2 > 1 + 1e-6
            ):
                raise ValueError(f"Invalid normalized box: {label}")
        group = str(sample["group"])
        if not group:
            raise ValueError("Missing source video group")
        # Stable assignment independent of manifest order; never split individual frames.
        bucket = int(hashlib.sha256(("sentinel-v1:" + group).encode()).hexdigest()[:8], 16) % 100
        split = "train" if bucket < 70 else "val" if bucket < 85 else "test"
        groups[group] = split
        accepted.append(
            {
                "image": str(image),
                "label": str(label),
                "sha256_pixels": digest,
                "label_sha256": hashlib.sha256(label.read_bytes()).hexdigest(),
                "group": group,
                "split": split,
            }
        )
    output.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        images = [s["image"] for s in accepted if s["split"] == split]
        if not images:
            raise ValueError(f"Empty {split} split; acquire more independent source groups")
        (output / f"{split}.txt").write_text("\n".join(images) + "\n")
    config = {
        "path": str(output.resolve()),
        "names": data["names"],
        **{s: str((output / f"{s}.txt").resolve()) for s in ("train", "val", "test")},
    }
    (output / "dataset.yaml").write_text(yaml.safe_dump(config))
    (output / "manifest.lock.json").write_text(
        json.dumps(
            {"source": data["source"], "license": data["license"], "groups": groups, "samples": accepted},
            indent=2,
        )
    )
    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/prepared"))
    args = parser.parse_args()
    prepare(args.manifest, args.output)
