"""Bounded, explicitly authorized RTSP acquisition for subsequent upload.

Camera URLs come from a local environment variable, never browser parameters.
This CLI is not a continuous live dashboard or a tested camera integration.
"""

import argparse
import ipaddress
import os
import socket
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import cv2

parser = argparse.ArgumentParser()
parser.add_argument("--authorized", action="store_true", required=True)
parser.add_argument("--allowed-ip", required=True, help="Exact provisioned camera IP")
parser.add_argument("--seconds", type=int, default=30)
parser.add_argument("--output", type=Path, default=Path("data/capture.avi"))
args = parser.parse_args()
if not 1 <= args.seconds <= 300:
    raise SystemExit("Capture must be bounded to 1–300 seconds")
allowed = ipaddress.ip_address(args.allowed_ip)
if allowed.is_loopback or allowed.is_link_local or allowed.is_multicast or allowed.is_unspecified:
    raise SystemExit("Loopback, metadata/link-local and multicast addresses are disallowed")
parsed = urlparse(os.environ.get("SENTINEL_CAPTURE_URL", ""))
if parsed.scheme != "rtsp" or not parsed.hostname or parsed.fragment:
    raise SystemExit("Set SENTINEL_CAPTURE_URL to your authorized RTSP URL")
addresses = {
    ipaddress.ip_address(row[4][0])
    for row in socket.getaddrinfo(parsed.hostname, parsed.port or 554, type=socket.SOCK_STREAM)
}
if addresses != {allowed}:
    raise SystemExit("Camera DNS must resolve only to the explicitly provisioned IP")
# Pin the connection to the approved IP so a second DNS lookup cannot rebind it.
host = f"[{allowed}]" if allowed.version == 6 else str(allowed)
credentials = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
url = urlunparse(parsed._replace(netloc=f"{credentials}{host}:{parsed.port or 554}"))
deadline = time.monotonic() + args.seconds
writer = None
frames, reconnects = 0, 0
args.output.parent.mkdir(parents=True, exist_ok=True)
try:
    while time.monotonic() < deadline and reconnects < 3:
        cap = cv2.VideoCapture(
            url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000]
        )
        try:
            while time.monotonic() < deadline:
                ok, frame = cap.read()
                if not ok:
                    reconnects += 1
                    break
                if max(frame.shape[:2]) > 4096:
                    raise SystemExit("Camera dimensions exceed configured bound")
                if writer is None:
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    fps = fps if 1 <= fps <= 120 else 25
                    writer = cv2.VideoWriter(
                        str(args.output),
                        cv2.VideoWriter_fourcc(*"MJPG"),
                        fps,
                        (frame.shape[1], frame.shape[0]),
                    )
                    if not writer.isOpened():
                        raise SystemExit("Video writer unavailable")
                writer.write(frame)
                frames += 1
        finally:
            cap.release()
finally:
    if writer:
        writer.release()
if not frames:
    raise SystemExit("No frames captured; inspect camera connectivity locally (do not share credentials)")
print(f"Captured {frames} frames; reconnect attempts {reconnects}. Upload {args.output} for analysis.")
