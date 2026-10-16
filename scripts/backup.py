"""Offline SQLite/media snapshot and restore to a NEW directory; never overwrites.
Stop writers first. Secrets are intentionally excluded; restore requires the original secret.
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def snapshot(source: Path, destination: Path):
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Destination must be new and outside source")
    with sqlite3.connect(source / "sentinel.db") as db:
        if db.execute("select count(*) from jobs where state in ('queued','running')").fetchone()[0]:
            raise ValueError("Stop or finish active jobs before snapshot")
        destination.mkdir(parents=True)
        with sqlite3.connect(destination / "sentinel.db") as backup:
            db.backup(backup)
    for name in ("videos", "evidence", "models", "audit-sealed"):
        if (source / name).exists():
            shutil.copytree(source / name, destination / name)
    files = {
        p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in destination.rglob("*")
        if p.is_file()
    }
    (destination / "snapshot.json").write_text(json.dumps({"source": str(source), "files": files}, indent=2))
    return len(files)


def restore(snapshot_dir: Path, destination: Path):
    if destination.exists():
        raise ValueError("Restore target must not exist")
    manifest = json.loads((snapshot_dir / "snapshot.json").read_text())
    for key, digest in manifest["files"].items():
        path = (snapshot_dir / key).resolve()
        if (
            not path.is_relative_to(snapshot_dir.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Snapshot integrity failure")
    shutil.copytree(snapshot_dir, destination)

    def remap(value):
        if isinstance(value, str):
            if value == manifest["source"] or any(
                value.startswith(manifest["source"] + sep) for sep in ("/", "\\")
            ):
                return str(destination.resolve()) + value[len(manifest["source"]) :]
            return value
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value

    with sqlite3.connect(destination / "sentinel.db") as db:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        for table, column in [("records", "body"), ("jobs", "config")]:
            for identity, body in db.execute(f"select id,{column} from {table}").fetchall():
                db.execute(
                    f"update {table} set {column}=? where id=?",
                    (json.dumps(remap(json.loads(body))), identity),
                )
        db.execute("update auth_sessions set revoked=1")
    return len(manifest["files"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "restore"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(globals()[args.action](args.source, args.destination), "files verified")
