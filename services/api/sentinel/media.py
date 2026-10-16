import subprocess
from pathlib import Path

import imageio_ffmpeg


def encode_playback(source: Path, destination: Path, fps: float) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-r",
            str(fps),
            "-movflags",
            "+faststart",
            str(destination),
        ],
        check=True,
        timeout=120,
        capture_output=True,
    )


def event_clip(source: Path, destination: Path, timestamp: float) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(max(timestamp - 2, 0)),
            "-i",
            str(source),
            "-t",
            "5",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )


class TimestampWriter:
    """H264 MP4 with per-frame PTS, preserving gaps rather than resampling."""

    def __init__(self, destination, width, height):
        from fractions import Fraction

        import av

        self.container = av.open(str(destination), "w", options={"movflags": "+faststart"})
        self.stream = self.container.add_stream("libx264", rate=30)
        self.stream.width, self.stream.height = width + width % 2, height + height % 2
        self.stream.pix_fmt = "yuv420p"
        self.stream.time_base = Fraction(1, 1000000)
        self.stream.codec_context.time_base = Fraction(1, 1000000)
        self.origin = None
        self.closed = False

    def write(self, array, timestamp):
        import av

        if self.origin is None:
            self.origin = timestamp
        frame = av.VideoFrame.from_ndarray(array, format="bgr24").reformat(
            width=self.stream.width, height=self.stream.height, format="yuv420p"
        )
        frame.pts = round((timestamp - self.origin) * 1000000)
        frame.time_base = self.stream.time_base
        for packet in self.stream.encode(frame):
            self.container.mux(packet)

    def close(self):
        if not self.closed:
            for packet in self.stream.encode():
                self.container.mux(packet)
            self.container.close()
            self.closed = True
