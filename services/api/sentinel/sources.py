"""Bounded stream decoder, with receive-time timestamps and explicit drops."""

import queue
import threading
import time

import av

av.logging.set_level(av.logging.PANIC)


class PTSReader:
    """Decode source PTS in its declared time base, retaining receive time separately."""

    def __init__(self, url):
        self.container = av.open(url, timeout=(10, 3), options={"rtsp_transport": "tcp"})
        self.frames = iter(self.container.decode(video=0))
        self.pts = None

    def read(self):
        try:
            frame = next(self.frames)
            self.pts = float(frame.pts * frame.time_base) if frame.pts is not None else None
            return True, frame.to_ndarray(format="bgr24")
        except (StopIteration, av.error.FFmpegError):
            return False, None

    def release(self):
        self.container.close()


class LiveSource:
    def __init__(self, url: str, seconds: int, opener=None):
        self.url, self.seconds = url, seconds
        self.opener = opener or PTSReader
        self.last_metadata: dict = {}
        self.queue: queue.Queue = queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.dropped = 0
        self.reconnects = 0
        self.error: str | None = None
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self):
        started = time.perf_counter()
        previous = -1.0
        try:
            while (
                not self.stop.is_set()
                and time.perf_counter() - started < self.seconds
                and self.reconnects < 3
            ):
                try:
                    cap = self.opener(self.url)
                except Exception:
                    self.reconnects += 1
                    self.stop.wait(min(0.25 * self.reconnects, 1))
                    continue
                first_pts = None
                epoch = time.perf_counter() - started
                try:
                    while not self.stop.is_set() and time.perf_counter() - started < self.seconds:
                        ok, frame = cap.read()
                        if not ok:
                            self.reconnects += 1
                            break
                        received = time.perf_counter() - started
                        pts = getattr(cap, "pts", None)
                        if pts is not None:
                            if first_pts is None:
                                first_pts = pts
                            timestamp = epoch + pts - first_pts
                            if timestamp <= previous:
                                epoch, first_pts = max(received, previous + 0.000001), pts
                                timestamp = epoch
                        else:
                            timestamp = received
                        timestamp = max(timestamp, previous + 0.000001)
                        previous = timestamp
                        item = (
                            timestamp,
                            frame,
                            {
                                "source_pts_seconds": pts,
                                "received_seconds": received,
                                "epoch": self.reconnects,
                                "basis": "source_pts" if pts is not None else "receive_monotonic",
                            },
                        )
                        try:
                            self.queue.put_nowait(item)
                        except queue.Full:
                            try:
                                self.queue.get_nowait()
                            except queue.Empty:
                                pass
                            self.dropped += 1
                            self.queue.put_nowait(item)
                finally:
                    cap.release()
                if self.reconnects and not self.stop.is_set():
                    self.stop.wait(min(0.25 * self.reconnects, 1))
        except Exception:
            self.error = "Stream decoder failed"
        finally:
            self.stop.set()

    def __iter__(self):
        self.thread.start()
        while not self.stop.is_set() or not self.queue.empty():
            try:
                timestamp, frame, self.last_metadata = self.queue.get(timeout=0.2)
                yield timestamp, frame
            except queue.Empty:
                continue

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=14)
