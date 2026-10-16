import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest


def module(path):
    spec = importlib.util.spec_from_file_location("research", Path(__file__).parents[1] / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_near_duplicate_cross_group(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    frame = np.tile(np.arange(100, dtype=np.uint8), (100, 1))
    for name, pixels in (("a", frame), ("b", frame + 2)):
        cv2.imwrite(str(tmp_path / "images" / f"{name}.png"), pixels)
        (tmp_path / "labels" / f"{name}.txt").write_text("0 0.5 0.5 0.4 0.4")
    manifest = {
        "source": "synthetic unit test",
        "license": "test",
        "names": ["person"],
        "samples": [{"image": f"images/{n}.png", "label": f"labels/{n}.txt", "group": n} for n in ("a", "b")],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="near duplicate"):
        module("ml/training/prepare.py").prepare(path, tmp_path / "out")


def test_video_bootstrap_and_mot_export(tmp_path):
    bootstrap = module("ml/evaluation/uncertainty.py").bootstrap
    data = {"video_hours": {"a": 1, "b": 1}, "predictions": [], "truth": []}
    assert bootstrap(data, replicates=30)["intervals_95"]["false_alarms_per_video_hour"] == [0, 0]
    with pytest.raises(ValueError):
        bootstrap({**data, "video_hours": {"a": 1}})
    source, target = tmp_path / "tracks.jsonl", tmp_path / "mot.txt"
    source.write_text(
        json.dumps(
            {
                "timestamp": 0.1,
                "width": 100,
                "height": 200,
                "tracks": [{"id": 7, "box": [0.1, 0.2, 0.4, 0.6], "confidence": 0.8}],
            }
        )
    )
    module("ml/evaluation/mot_export.py").export(source, target, fps=10)
    assert target.read_text().startswith("2,7,10.000,40.000,30.000,80.000,0.80000")
