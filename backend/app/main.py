from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import configure_logging
from app.middleware.request_context import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

app = FastAPI(title=settings.app_name, version="2.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url="/api/redoc",
              description="Multi-tenant GPS geofencing attendance API. All distances and attendance decisions are computed server-side.")
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict:
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}
