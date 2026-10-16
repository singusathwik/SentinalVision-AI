"""Own a local test publisher, interrupt/restart it, and verify decoder recovery.

Requires the loopback-only MediaMTX fixture config with paths: all_others: source: publisher.
No remote stream is used. Run from the repository root.
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import imageio_ffmpeg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from sentinel.sources import LiveSource  # noqa: E402

command = [
    imageio_ffmpeg.get_ffmpeg_exe(),
    "-hide_banner",
    "-loglevel",
    "error",
    "-re",
    "-stream_loop",
    "-1",
    "-i",
    "data/demo/static-bus-test.avi",
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-tune",
    "zerolatency",
    "-g",
    "10",
    "-pix_fmt",
    "yuv420p",
    "-rtsp_transport",
    "tcp",
    "-f",
    "rtsp",
    "rtsp://127.0.0.1:8554/restart",
]
publisher = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
source = LiveSource("rtsp://127.0.0.1:8554/restart", 20)
times = []
thread = threading.Thread(target=lambda: times.extend(t for t, _ in source))
try:
    time.sleep(1)
    thread.start()
    time.sleep(6)
    publisher.terminate()
    publisher.wait(timeout=5)
    time.sleep(0.5)
    publisher = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert times and min(times) < 6 and max(times) > 12, times
    assert source.reconnects >= 1
    report = {
        "scope": "localhost RTSP restart fixture, no physical camera",
        "frames": len(times),
        "reconnects": source.reconnects,
        "first_timestamp": min(times),
        "last_timestamp": max(times),
        "strictly_monotonic": all(b > a for a, b in zip(times, times[1:], strict=False)),
    }
    assert report["strictly_monotonic"]
    Path("docs/results/rtsp-restart.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
finally:
    publisher.terminate()
    publisher.wait(timeout=5)
    source.close()
