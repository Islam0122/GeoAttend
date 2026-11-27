"""Request id, structured access log, security headers, last-resort error handler."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import request_id_var

log = logging.getLogger("geoattend.http")

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "geolocation=(self), camera=(), microphone=()",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled_error", extra={"path": request.url.path, "method": request.method})
            response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        response.headers["x-request-id"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                   "ms": round((time.perf_counter() - start) * 1000, 1), "user_id": getattr(request.state, "user_id", None),
                                   "org_id": getattr(request.state, "org_id", None)})
        request_id_var.reset(token)
        return response
