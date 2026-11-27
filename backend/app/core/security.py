from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.timeutils import utcnow


def hash_password(password: str) -> str:
    # bcrypt only uses 72 bytes; pre-hash to support long passphrases safely.
    digest = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    digest = hashlib.sha256(password.encode()).hexdigest().encode()
    try:
        return bcrypt.checkpw(digest, hashed.encode())
    except ValueError:
        return False


def _encode(sub: int, org: int, ver: int, kind: str, ttl: timedelta, extra: dict | None = None) -> str:
    s = get_settings()
    now = utcnow()
    payload = {"sub": str(sub), "org": org, "ver": ver, "typ": kind, "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp()),
               "jti": secrets.token_hex(16), **(extra or {})}
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def create_access_token(user_id: int, org_id: int, token_version: int) -> str:
    return _encode(user_id, org_id, token_version, "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user_id: int, org_id: int, token_version: int, jti: str, family: str) -> str:
    return _encode(user_id, org_id, token_version, "refresh", timedelta(days=get_settings().refresh_token_days), {"jti": jti, "fam": family})


def decode_token(token: str, expected_type: str) -> dict:
    s = get_settings()
    # Expiry is checked against the application clock (single source of time, freezable in tests).
    payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "typ"], "verify_exp": False})
    if int(payload["exp"]) < int(utcnow().timestamp()):
        raise jwt.ExpiredSignatureError("token expired")
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_invite_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
