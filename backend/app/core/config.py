"""Application settings (12-factor, environment driven)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GEOATTEND_", extra="ignore")

    app_name: str = "GeoAttend Workforce Attendance"
    environment: str = "development"
    debug: bool = False

    database_url: str = "sqlite:///./geoattend.db"
    redis_url: str | None = None
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str | None = None

    secret_key: str = Field(default="change-me-in-production-please-32+chars", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    invite_token_hours: int = 72
    bcrypt_rounds: int = 12

    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"

    # Rate limits: "<count>/<seconds>"
    rate_limit_enabled: bool = True
    rate_limit_auth: str = "10/60"           # per IP + account (credential guessing)
    rate_limit_auth_ip: str = "300/60"       # per IP ceiling; offices share one NAT IP
    rate_limit_refresh: str = "30/60"        # per refresh-token family
    rate_limit_locations: str = "120/60"
    rate_limit_default: str = "600/60"

    # Clock skew tolerated on client timestamps (seconds).
    max_clock_skew_seconds: int = 120

    # Outbound notifications
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@geoattend.local"
    smtp_tls: bool = True

    # Google OAuth (Sign in with Google, ID-token flow; no Google Maps or paid APIs)
    google_client_id: str | None = None
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"

    # Refresh token cookie (httpOnly). Set cookie_secure=true behind HTTPS in production.
    refresh_cookie_name: str = "ga_refresh"
    cookie_secure: bool = False
    cookie_samesite: str = "strict"

    log_level: str = "INFO"
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
