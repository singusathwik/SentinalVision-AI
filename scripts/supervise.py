"""Restart owned local services with bounded backoff and terminate their process trees."""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def supervise(command, stop, log, max_restarts=None):
    restarts = 0
    while not stop():
        started = time.monotonic()
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "services/api")},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            while child.poll() is None and not stop():
                time.sleep(0.1)
        finally:
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
                else:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
        if stop() or (max_restarts is not None and restarts >= max_restarts):
            break
        restarts += 1
        delay = min(2 ** min(restarts, 5), 30) if time.monotonic() - started < 60 else 1
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline and not stop():
            time.sleep(0.1)
    return restarts


if __name__ == "__main__":
    import threading

    parser = argparse.ArgumentParser()
    parser.add_argument("services", nargs="+", choices=["api", "worker", "maintenance", "web"])
    args = parser.parse_args()
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    commands = {
        "api": [sys.executable, "-m", "uvicorn", "sentinel.api:app", "--host", "127.0.0.1", "--port", "8010"],
        "worker": [sys.executable, "-m", "sentinel.worker"],
        "maintenance": [sys.executable, "-m", "sentinel.maintenance"],
        "web": [
            shutil.which("node"),
            str(ROOT / "apps/web/node_modules/next/dist/bin/next"),
            "dev",
            str(ROOT / "apps/web"),
            "--hostname",
            "127.0.0.1",
        ],
    }
    folder = ROOT / "data/service-logs"
    folder.mkdir(parents=True, exist_ok=True)
    handles = [(folder / (name + ".log")).open("a") for name in args.services]
    threads = [
        threading.Thread(target=supervise, args=(commands[name], stopped.is_set, handle))
        for name, handle in zip(args.services, handles, strict=True)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for handle in handles:
        handle.close()
