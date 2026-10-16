import datetime as dt
import hashlib
import time

import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import settings
from .db import AuthSession, RateBucket, Session, User, engine, now, uid

hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def rate_limit(key: str, limit: int = 10) -> None:
    bucket = hashlib.sha256(f"{key}:{int(time.time()) // 60}".encode()).hexdigest()
    insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
    with Session() as db:
        statement = insert(RateBucket).values(id=bucket, count=1, expires=now() + dt.timedelta(minutes=2))
        query = statement.on_conflict_do_update(
            index_elements=[RateBucket.id], set_={"count": RateBucket.count + 1}
        ).returning(RateBucket.count)
        count = db.scalar(query)
        db.commit()
    if count is not None and count > limit:
        raise HTTPException(429, "Rate limit exceeded; retry in one minute", headers={"Retry-After": "60"})


def issue_token(user: User) -> str:
    identity, expires = uid(), now() + dt.timedelta(hours=8)
    with Session() as db:
        db.add(AuthSession(id=identity, user_id=user.id, expires=expires))
        db.commit()
    return jwt.encode(
        {
            "sub": user.id,
            "jti": identity,
            "exp": expires,
            "iat": now(),
            "iss": "sentinel",
            "aud": "sentinel-api",
        },
        settings.secret,
        algorithm="HS256",
    )


def token_payload(token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret,
        algorithms=["HS256"],
        issuer="sentinel",
        audience="sentinel-api",
        options={"require": ["sub", "jti", "exp", "iat"]},
    )


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    try:
        payload = token_payload(credentials.credentials if credentials else "")
        with Session() as db:
            session = db.get(AuthSession, payload["jti"])
            user = db.get(User, payload["sub"])
            from .control import enabled

            if (
                not session
                or session.revoked
                or session.expires <= now()
                or session.user_id != payload["sub"]
                or not user
                or not enabled(db, user.id)
            ):
                raise ValueError("Invalid session")
        return user
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Authentication required") from None


def revoke(token: str) -> None:
    payload = token_payload(token)
    with Session() as db:
        db.execute(update(AuthSession).where(AuthSession.id == payload["jti"]).values(revoked=1))
        db.commit()


def operator(user: User = Depends(current_user)) -> User:
    if user.role not in ("operator", "admin"):
        raise HTTPException(403, "Operator role required")
    return user


def admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator role required")
    return user
