"""Google Sign-In: verify an OpenID Connect ID token against Google's published JWKS."""
from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.core.config import get_settings

log = logging.getLogger("geoattend.google")
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().google_jwks_url, cache_keys=True, lifespan=3600)


def verify_id_token(token: str, nonce: str | None = None) -> GoogleIdentity:
    s = get_settings()
    if not s.google_client_id:
        raise GoogleAuthError("Google sign-in is not configured")
    try:
        key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=s.google_client_id, options={"require": ["exp", "iat", "iss", "sub", "aud"]})
    except jwt.PyJWTError as exc:
        log.warning("google_token_invalid", extra={"error": str(exc)})
        raise GoogleAuthError("Invalid Google token") from exc
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("Invalid token issuer")
    if not claims.get("email") or not claims.get("email_verified"):
        raise GoogleAuthError("Google account email is not verified")
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("Nonce mismatch")
    return GoogleIdentity(sub=str(claims["sub"]), email=str(claims["email"]).lower(), name=claims.get("name"))
