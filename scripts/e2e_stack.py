"""Start an isolated local API/worker/web stack, execute demo + browsers, then stop.

Requires free ports 8010/3000, installed Python/Node dependencies, browser and model.
Credentials and SQLite are placed under ignored data/e2e-stack, never overwrite local login.
"""

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
for port in (8010, 3000):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Port {port} is in use; stop the local stack first")
folder = ROOT / "data" / "e2e-stack" / secrets.token_hex(4)
folder.mkdir(parents=True)
password = secrets.token_urlsafe(24)
credentials = folder / "login.json"
credentials.write_text(json.dumps({"email": "admin@sentinel.local", "password": password}))
env = {
    **os.environ,
    "PYTHONPATH": str(ROOT / "services/api"),
    "SENTINEL_DATABASE_URL": "sqlite:///" + (folder / "db.sqlite").as_posix(),
    "SENTINEL_DATA_DIR": str(folder),
    "SENTINEL_SECRET": secrets.token_urlsafe(48),
    "SENTINEL_STORAGE": "local",
    "SENTINEL_QUEUE": "database",
    "SENTINEL_DEVICE": "cpu",
    "SENTINEL_DEMO_PASSWORD": password,
    "E2E_LOGIN_PATH": str(credentials),
    "NEXT_PUBLIC_API_URL": "http://127.0.0.1:8010/api/v1",
}
subprocess.run(
    [
        sys.executable,
        "-c",
        "import os; from sentinel.db import init_db,Session,User; from sentinel.auth import hasher; init_db(); s=Session(); s.add(User(email='admin@sentinel.local',tenant='ci',role='admin',password=hasher.hash(os.environ['SENTINEL_DEMO_PASSWORD']))); s.commit()",
    ],
    env=env,
    check=True,
)
processes, logs = [], []


def start(command, cwd=ROOT):
    log = (folder / f"service-{len(processes)}.log").open("w")
    logs.append(log)
    processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))


def wait(url):
    for _ in range(120):
        if any(p.poll() is not None for p in processes):
            raise RuntimeError(f"Service exited; see {folder}")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


try:
    start([sys.executable, "-m", "uvicorn", "sentinel.api:app", "--host", "127.0.0.1", "--port", "8010"])
    start([sys.executable, "-m", "sentinel.worker"])
    start(
        [shutil.which("node"), "node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1"],
        ROOT / "apps/web",
    )
    wait("http://127.0.0.1:8010/api/v1/ready")
    wait("http://127.0.0.1:3000")
    subprocess.run([sys.executable, "scripts/demo.py"], env=env, check=True)
    subprocess.run(
        [shutil.which("node"), "node_modules/@playwright/test/cli.js", "test"],
        cwd=ROOT / "apps/web",
        env=env,
        check=True,
    )
finally:
    for process in reversed(processes):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    for log in logs:
        log.close()
