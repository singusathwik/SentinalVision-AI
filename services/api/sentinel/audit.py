"""Signed append-only audit export. Verify against a separately protected manifest.

Local administrators can remove local files; external WORM/anchoring is deployment validation.
"""

import hashlib
import hmac
import json
from pathlib import Path

from sqlalchemy import select

from .config import settings
from .db import Record, Session


def signature(payload):
    return hmac.new(
        settings.secret.encode(),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def seal_audit():
    folder = settings.data_dir / "audit-sealed"
    folder.mkdir(exist_ok=True)
    with Session() as db:
        for row in db.scalars(select(Record).where(Record.kind == "audit")):
            target = folder / (row.id + ".json")
            payload = {
                "id": row.id,
                "tenant": row.tenant,
                "created": row.created.isoformat(),
                "body": row.body,
            }
            sealed = {"payload": payload, "signature": signature(payload)}
            if target.exists():
                if json.loads(target.read_text()) != sealed:
                    raise ValueError("Audit export differs from database")
            else:
                with target.open("x") as out:
                    json.dump(sealed, out, sort_keys=True)
    return folder


def export_manifest(destination: Path):
    folder = seal_audit()
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.json"))}
    destination.write_text(json.dumps({"files": files, "signature": signature(files)}, indent=2))


def verify_manifest(manifest: Path):
    data = json.loads(manifest.read_text())
    if not hmac.compare_digest(data["signature"], signature(data["files"])):
        raise ValueError("Manifest authentication failed")
    folder = settings.data_dir / "audit-sealed"
    for name, digest in data["files"].items():
        path = folder / Path(name).name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Audit file missing or changed")
    return len(data["files"])
