import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest


def module(path):
    spec = importlib.util.spec_from_file_location("subject", Path(__file__).parents[1] / path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def test_event_one_to_one_and_no_early_match():
    evaluate = module("ml/evaluation/events.py").evaluate
    truth = [{"video_id": "v", "rule_id": "r", "timestamp": 5}]
    predictions = [{"video_id": "v", "rule_id": "r", "timestamp": t} for t in (4, 5, 6)]
    r = evaluate(predictions, truth, 1)
    assert r["tp"] == 1 and r["fp"] == 2
    assert r["mean_detection_delay_seconds"] == 0


def test_group_splits_and_duplicate_rejection(tmp_path):
    prepare = module("ml/training/prepare.py").prepare
    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    samples = []
    for i in range(40):
        cv2.imwrite(
            str(tmp_path / f"images/{i}.png"),
            np.random.default_rng(i).integers(0, 256, (64, 64, 3), dtype=np.uint8),
        )
        (tmp_path / f"labels/{i}.txt").write_text("0 0.5 0.5 0.25 0.25\n")
        samples.append({"image": f"images/{i}.png", "label": f"labels/{i}.txt", "group": f"video-{i // 2}"})
    manifest = {
        "license": "synthetic test",
        "source": "independent seeded noise frames",
        "names": ["person"],
        "samples": samples,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    rows = prepare(path, tmp_path / "output")
    for group in {r["group"] for r in rows}:
        assert len({r["split"] for r in rows if r["group"] == group}) == 1
    assert {r["split"] for r in rows} == {"train", "val", "test"}
    (tmp_path / "images/1.png").write_bytes((tmp_path / "images/0.png").read_bytes())
    with pytest.raises(ValueError, match="Duplicate"):
        prepare(path, tmp_path / "bad")
