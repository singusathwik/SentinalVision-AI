import time

import numpy as np
from sentinel.rules import RuleEngine, Track
from sentinel.schemas import Rule
from sentinel.sources import LiveSource
from test_rules import POLY, track


def test_exit_grace_lifecycle():
    rule = {
        **Rule(name="grace", kind="intrusion", zone_id="z", persistence=0, exit_grace=1).model_dump(),
        "id": "r",
    }
    engine = RuleEngine([rule], {"z": POLY})
    assert engine.step(0, [track()])
    assert not engine.step(0.5, []) and not engine.resolved
    assert not engine.step(1.1, [])
    assert engine.resolved == ["r:1"]


def test_gap_resets_line_and_dwell():
    rule = {**Rule(name="gap", kind="dwell", zone_id="z", threshold=2).model_dump(), "id": "r"}
    engine = RuleEngine([rule], {"z": POLY}, max_gap=1)
    assert not engine.step(0, [track()])
    assert not engine.step(10, [track()])


def test_spatial_exit_margin():
    polygon = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
    rule = {
        **Rule(name="margin", kind="intrusion", zone_id="z", persistence=0, exit_margin=0.05).model_dump(),
        "id": "r",
    }
    engine = RuleEngine([rule], {"z": polygon})

    def subject(x):
        return Track(1, "person", 0.9, (x - 0.01, 0.1, x + 0.01, 0.5))

    assert engine.step(0, [subject(0.49)])
    assert not engine.step(0.1, [subject(0.53)]) and not engine.resolved
    assert not engine.step(0.2, [subject(0.56)])
    assert engine.resolved == ["r:1"]


def test_stream_reconnect_and_bounded_queue():
    class Capture:
        def __init__(self):
            self.index = 0

        def read(self):
            self.index += 1
            return (True, np.zeros((16, 16, 3), np.uint8)) if self.index <= 10 else (False, None)

        def release(self):
            pass

    source = LiveSource("fixture", 2, opener=lambda _: Capture())
    frames = []
    for timestamp, _frame in source:
        frames.append(timestamp)
        time.sleep(0.01)
    source.close()
    assert source.reconnects == 3
    assert source.dropped > 0
    assert len(frames) <= 6
    assert frames == sorted(frames)
