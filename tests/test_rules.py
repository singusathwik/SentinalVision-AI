import pytest
from sentinel.rules import RuleEngine, Track, inside
from sentinel.schemas import Rule, Zone

POLY = [(0, 0), (1, 0), (1, 1), (0, 1)]


def track(x=0.5, identity=1, label="person"):
    return Track(identity, label, 0.9, (x - 0.05, 0.2, x + 0.05, 0.7))


def engine(kind="intrusion", **overrides):
    rule = Rule(name="test", kind=kind, zone_id="z", **overrides).model_dump()
    return RuleEngine([{**rule, "id": "r"}], {"z": POLY})


@pytest.mark.parametrize(
    "point,expected",
    [((0.5, 0.5), True), ((0, 0), True), ((1, 0.5), True), ((1.01, 0.5), False), ((-0.1, 0.5), False)],
)
def test_polygon(point, expected):
    assert inside(point, POLY) is expected


def test_persistence_and_dedup():
    e = engine()
    assert not e.step(0, [track()])
    assert len(e.step(0.5, [track()])) == 1
    assert not e.step(10, [track()])


def test_cooldown_and_reentry():
    e = engine(persistence=0, cooldown=3)
    assert e.step(0, [track()])
    assert not e.step(1, [])
    assert not e.step(2, [track()])
    assert e.step(3, [track()])


def test_dwell_requires_contiguous_presence():
    e = engine("dwell", threshold=3)
    assert not e.step(0, [track()])
    assert not e.step(2, [])
    assert not e.step(3, [track()])
    assert not e.step(5, [track()])
    assert e.step(6, [track()])


def test_occupancy():
    e = engine("occupancy", threshold=1, persistence=0)
    assert not e.step(0, [track()])
    event = e.step(1, [track(), track(0.7, 2)])[0]
    assert event["track_ids"] == [1, 2]


def test_line_direction_and_segment():
    e = engine("line", line=[(0.5, 0), (0.5, 1)], direction="negative")
    assert not e.step(0, [track(0.2)])
    assert e.step(1, [track(0.8)])
    assert not e.step(2, [track(0.2)])


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_timestamps(bad):
    e = engine()
    e.step(0, [])
    with pytest.raises(ValueError):
        e.step(bad, [])


def test_isolation():
    a, b = engine(), engine()
    a.step(0, [track()])
    assert a.step(1, [track()])
    assert not b.step(1, [track()])


def test_proximity_labels_units():
    e = engine("proximity", threshold=0.2, persistence=0)
    result = e.step(0, [track(0.5), track(0.6, 2, "forklift")])
    assert "not meters" in result[0]["reason"]
    assert not engine("proximity").step(0, [track()])


@pytest.mark.parametrize("points", [[(0, 0), (0.5, 0.5), (1, 1)], [(0, 0), (2, 0), (0, 1)]])
def test_invalid_polygon(points):
    with pytest.raises(ValueError):
        Zone(name="bad", points=points)


def test_nonzero_area_self_intersection():
    with pytest.raises(ValueError, match="self-intersect"):
        Zone(name="crossing", points=[(0, 0), (1, 0.8), (0, 1), (0.8, 0), (1, 1)])
