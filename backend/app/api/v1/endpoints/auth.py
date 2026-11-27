from __future__ import annotations

import re
import secrets
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.timeutils import utcnow
from app.integrations import google_oauth
from app.models import Organization, OrganizationSettings, RefreshToken, User
from app.models.enums import Role
from app.schemas.auth import (
    AcceptInviteIn,
    ChangePasswordIn,
    GoogleAuthIn,
    LoginIn,
    LogoutIn,
    MeOut,
    RefreshIn,
    RegisterCompanyIn,
    TokenPair,
)
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_limit(request: Request) -> None:
    """Per-IP ceiling only. Many employees share an office NAT IP, so per-account limits are applied
    inside login (IP + email) and refresh (token family)."""
    rate_limit.check(f"authip:{rate_limit.client_ip(request)}", get_settings().rate_limit_auth_ip)


def _account_limit(request: Request, account: str) -> None:
    rate_limit.check(f"auth:{rate_limit.client_ip(request)}:{account.lower()}", get_settings().rate_limit_auth)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


def issue_tokens(db: Session, user: User, response: Response, family: str | None = None) -> TokenPair:
    s = get_settings()
    jti, fam = secrets.token_hex(16), family or secrets.token_hex(16)
    db.add(RefreshToken(organization_id=user.organization_id, user_id=user.id, jti=jti, family=fam,
                        expires_at=utcnow() + timedelta(days=s.refresh_token_days)))
    refresh = create_refresh_token(user.id, user.organization_id, user.token_version, jti, fam)
    response.set_cookie(s.refresh_cookie_name, refresh, max_age=s.refresh_token_days * 86400, httponly=True, secure=s.cookie_secure,
                        samesite=s.cookie_samesite, path="/api/v1/auth")
    return TokenPair(access_token=create_access_token(user.id, user.organization_id, user.token_version), refresh_token=refresh,
                     expires_in=s.access_token_minutes * 60)


def _revoke_family(db: Session, family: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family == family, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))


def _create_org(db: Session, *, company_name: str, tz: str, company_type, full_name: str, email: str, password: str | None, google_sub: str | None) -> User:
    org = Organization(name=company_name, slug=_slugify(company_name), timezone=tz, company_type=company_type)
    db.add(org)
    db.flush()
    db.add(OrganizationSettings(organization_id=org.id))
    user = User(organization_id=org.id, email=email.lower(), full_name=full_name, role=Role.OWNER,
                password_hash=hash_password(password) if password else None, google_sub=google_sub)
    db.add(user)
    db.flush()
    return user


@router.post("/register/", response_model=TokenPair, status_code=201, dependencies=[Depends(_auth_limit)])
@router.post("/register-company/", response_model=TokenPair, status_code=201, include_in_schema=False, dependencies=[Depends(_auth_limit)])
def register(body: RegisterCompanyIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    _account_limit(request, "register")
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = _create_org(db, company_name=body.company_name, tz=body.timezone, company_type=body.company_type, full_name=body.full_name,
                       email=body.email, password=body.password, google_sub=None)
    audit(db, org_id=user.organization_id, actor_id=user.id, action="organization.registered", entity_type="organization",
          entity_id=user.organization_id, ip=rate_limit.client_ip(request))
    tokens = issue_tokens(db, user, response)
    db.commit()
    return tokens


@router.post("/login/", response_model=TokenPair, dependencies=[Depends(_auth_limit)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    _account_limit(request, body.email)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    org = db.get(Organization, user.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organization disabled")
    user.last_login_at = utcnow()
    audit(db, org_id=user.organization_id, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id, ip=rate_limit.client_ip(request))
    tokens = issue_tokens(db, user, response)
    db.commit()
    return tokens


@router.post("/google/", response_model=TokenPair, dependencies=[Depends(_auth_limit)])
def google(body: GoogleAuthIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    """Sign in (or register a new workspace) with a Google ID token. Invited users are activated on first Google sign-in."""
    try:
        ident = google_oauth.verify_id_token(body.id_token, body.nonce)
    except google_oauth.GoogleAuthError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "not configured" in str(exc) else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(code, str(exc)) from None
    user = db.scalar(select(User).where(User.google_sub == ident.sub)) or db.scalar(select(User).where(User.email == ident.email))
    if user is None:
        if not body.company_name:
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "GOOGLE_ACCOUNT_NOT_FOUND", "email": ident.email,
                                                            "message": "No workspace for this Google account. Provide company details to register."})
        user = _create_org(db, company_name=body.company_name, tz=body.timezone, company_type=body.company_type,
                           full_name=body.full_name or ident.name or ident.email, email=ident.email, password=None, google_sub=ident.sub)
        audit(db, org_id=user.organization_id, actor_id=user.id, action="organization.registered", entity_type="organization", entity_id=user.organization_id,
              changes={"via": "google"}, ip=rate_limit.client_ip(request))
    else:
        if not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
        if user.google_sub and user.google_sub != ident.sub:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google account mismatch")
        user.google_sub = ident.sub
        if user.invite_token_hash:  # invited employee activating via Google
            user.invite_token_hash, user.invite_expires_at = None, None
    user.last_login_at = utcnow()
    audit(db, org_id=user.organization_id, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id,
          changes={"via": "google"}, ip=rate_limit.client_ip(request))
    tokens = issue_tokens(db, user, response)
    db.commit()
    return tokens


@router.post("/refresh/", response_model=TokenPair, dependencies=[Depends(_auth_limit)])
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)) -> TokenPair:
    """Rotate: each refresh token is single-use. Reusing a rotated token revokes the whole token family."""
    raw = (body.refresh_token if body and body.refresh_token else None) or request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        payload = decode_token(raw, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None
    rate_limit.check(f"refresh:{payload.get('fam')}", get_settings().rate_limit_refresh)
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti")))
    user = db.get(User, int(payload["sub"]))
    if stored is None or user is None or not user.is_active or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if stored.revoked_at is not None:
        _revoke_family(db, stored.family)
        audit(db, org_id=user.organization_id, actor_id=user.id, action="auth.refresh_reuse_detected", entity_type="user", entity_id=user.id,
              ip=rate_limit.client_ip(request))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected; please sign in again")
    tokens = issue_tokens(db, user, response, family=stored.family)
    stored.revoked_at = utcnow()
    stored.replaced_by = decode_token(tokens.refresh_token, "refresh")["jti"]
    db.commit()
    return tokens


@router.post("/logout/", status_code=204)
def logout(request: Request, response: Response, body: LogoutIn | None = None, db: Session = Depends(get_db)) -> None:
    s = get_settings()
    raw = (body.refresh_token if body and body.refresh_token else None) or request.cookies.get(s.refresh_cookie_name)
    if raw:
        try:
            payload = decode_token(raw, "refresh")
            stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti")))
            if stored:
                _revoke_family(db, stored.family)
                audit(db, org_id=stored.organization_id, actor_id=stored.user_id, action="auth.logout", entity_type="user", entity_id=stored.user_id)
                db.commit()
        except jwt.PyJWTError:
            pass
    response.delete_cookie(s.refresh_cookie_name, path="/api/v1/auth")


@router.post("/accept-invite/", response_model=TokenPair, dependencies=[Depends(_auth_limit)])
def accept_invite(body: AcceptInviteIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    _account_limit(request, "invite")
    user = db.scalar(select(User).where(User.invite_token_hash == hash_token(body.token)))
    if user is None or user.invite_expires_at is None or user.invite_expires_at < utcnow() or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired")
    user.password_hash = hash_password(body.password)
    user.invite_token_hash = None
    user.invite_expires_at = None
    user.token_version += 1
    audit(db, org_id=user.organization_id, actor_id=user.id, action="auth.invite_accepted", entity_type="user", entity_id=user.id, ip=rate_limit.client_ip(request))
    tokens = issue_tokens(db, user, response)
    db.commit()
    return tokens


@router.post("/change-password/", status_code=204)
def change_password(body: ChangePasswordIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    user = db.get(User, p.user.id)
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # revokes all existing access + refresh tokens
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit(db, org_id=user.organization_id, actor_id=user.id, action="auth.password_changed", entity_type="user", entity_id=user.id)
    db.commit()


@router.get("/me/", response_model=MeOut)
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> MeOut:
    org = db.get(Organization, p.org_id)
    return MeOut(id=p.user.id, email=p.user.email, full_name=p.user.full_name, role=p.user.role, organization_id=p.org_id,
                 organization_name=org.name, organization_timezone=org.timezone, subscription_plan=org.subscription_plan.value,
                 employee_id=p.employee.id if p.employee else None, managed_department_ids=sorted(p.managed_department_ids),
                 last_login_at=p.user.last_login_at, has_password=p.user.password_hash is not None, google_linked=p.user.google_sub is not None)
