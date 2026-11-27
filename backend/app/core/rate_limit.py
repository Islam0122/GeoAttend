"""Fixed-window rate limiter. Uses Redis when configured (multi-worker safe), memory otherwise."""
from __future__ import annotations

import logging
import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

log = logging.getLogger("geoattend.ratelimit")


class _MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, start = self._buckets.get(key, (0, now))
            if now - start >= window:
                count, start = 0, now
            count += 1
            self._buckets[key] = (count, start)
            if len(self._buckets) > 50_000:  # bound memory
                cutoff = now - 3600
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] > cutoff}
            return count

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=0.5)

    def hit(self, key: str, window: int) -> int:
        bucket = f"rl:{key}:{int(time.time() // window)}"
        pipe = self._r.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window + 1)
        return int(pipe.execute()[0])

    def reset(self) -> None:  # pragma: no cover
        pass


_backend: _MemoryBackend | _RedisBackend | None = None


def backend():
    global _backend
    if _backend is None:
        url = get_settings().redis_url
        _backend = _RedisBackend(url) if url else _MemoryBackend()
    return _backend


def _parse(spec: str) -> tuple[int, int]:
    count, seconds = spec.split("/")
    return int(count), int(seconds)


def check(key: str, spec: str) -> None:
    if not get_settings().rate_limit_enabled:
        return
    limit, window = _parse(spec)
    try:
        n = backend().hit(key, window)
    except Exception:  # noqa: BLE001 - limiter outage must not take the API down
        log.exception("rate_limiter_unavailable")
        return
    if n > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers={"Retry-After": str(window)})


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
