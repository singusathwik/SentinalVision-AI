import numpy as np
from sentinel.annotation import draw_tracks, intersection, layout
from sentinel.rules import Track


def test_crowded_labels_do_not_overlap_or_leave_frame():
    tracks = [Track(i, "person", 0.9, (0.4 + i * 0.01, 0.1, 0.47 + i * 0.01, 0.8)) for i in range(9)]
    tracks += [Track(20, "person", 0.8, (0, 0, 0.05, 0.3)), Track(21, "person", 0.8, (0.95, 0.6, 1, 1))]
    placed = layout(tracks, 768, 576)
    assert len(placed) == len(tracks)
    for i, item in enumerate(placed):
        x, y, right, bottom = item["rect"]
        assert 0 <= x < right < 768 and 34 <= y < bottom < 576
        assert item["text"].startswith("Person #")
        assert all(intersection(item["rect"], other["rect"]) == 0 for other in placed[i + 1 :])
    assert placed == layout(list(reversed(tracks)), 768, 576)


def test_annotation_renders_without_changing_track_data():
    tracks = [Track(7, "person", 0.87, (0.2, 0.2, 0.4, 0.8))]
    image = np.zeros((240, 320, 3), np.uint8)
    result = draw_tracks(image, tracks)
    assert result.shape == (240, 320, 3) and result.any()
    assert tracks[0].confidence == 0.87 and tracks[0].box == (0.2, 0.2, 0.4, 0.8)
