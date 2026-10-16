"""Initialize local secret and create an admin. Run from repository root."""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
env = Path(".env")
if not env.exists():
    env.write_text("SENTINEL_SECRET=" + secrets.token_urlsafe(48) + "\n")

from sentinel.auth import hasher  # noqa: E402
from sentinel.db import Session, User, init_db  # noqa: E402
from sqlalchemy import select  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--email", default="admin@sentinel.local")
parser.add_argument("--tenant", default="local")
args = parser.parse_args()
password = getpass.getpass("Admin password (12+ characters): ")
if len(password) < 12:
    raise SystemExit("Use at least 12 characters")
init_db()
with Session() as db:
    if db.scalar(select(User).where(User.email == args.email.lower())):
        raise SystemExit("User already exists")
    db.add(User(email=args.email.lower(), tenant=args.tenant, password=hasher.hash(password), role="admin"))
    db.commit()
print("Local account created. Start API and worker in separate terminals.")
