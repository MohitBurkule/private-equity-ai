"""Per-tenant rate limit. In-memory token bucket by default (one process). With REDIS_URL set, a shared
fixed-window counter (INCR + EXPIRE) limits across all API replicas; if Redis is unreachable the
request falls back to the local bucket instead of failing."""
from __future__ import annotations

import os
import threading
import time

from sqlalchemy import text


class RateLimiter:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.cap = float(per_minute)
        self.state: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.cap <= 0:
            return True
        now = time.monotonic() if now is None else now
        with self.lock:
            tokens, last = self.state.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.state[key] = (tokens, now)
                return False
            self.state[key] = (tokens - 1, now)
            return True


class RedisRateLimiter:
    """Fixed window of one minute per tenant, shared through Redis. Burst at a window edge can reach
    2x the limit; accepted for a coarse abuse guard."""

    def __init__(self, per_minute: int, client, fallback: RateLimiter | None = None):
        self.cap = per_minute
        self.client = client
        self.fallback = fallback or RateLimiter(per_minute)

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.cap <= 0:
            return True
        window = int((time.time() if now is None else now) // 60)
        rkey = f"pe:rl:{key}:{window}"
        try:
            n = self.client.incr(rkey)
            if n == 1:
                self.client.expire(rkey, 120)
            return n <= self.cap
        except Exception:  # noqa: BLE001  any Redis failure: degrade to the per-process bucket
            return self.fallback.allow(key)


class PostgresRateLimiter:
    """Fixed window of one minute per tenant, counted in the database, so every API replica shares it without
    Redis. Each count runs in its own transaction with the tenant set, so row-level security applies to it.
    Same burst caveat as the Redis limiter: up to 2x the limit at a window edge."""

    def __init__(self, per_minute: int, engine):
        self.cap = per_minute
        self.engine = engine

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.cap <= 0:
            return True
        minute = int((time.time() if now is None else now) // 60)
        with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": key})
            n = conn.execute(text(
                "INSERT INTO rate_window (tenant_id, minute, n) VALUES (:t, :m, 1) "
                "ON CONFLICT (tenant_id, minute) DO UPDATE SET n = rate_window.n + 1 RETURNING n"),
                {"t": key, "m": minute}).scalar_one()
        return n <= self.cap


def make_limiter(per_minute: int, redis_url: str | None, engine=None):
    """Per-process bucket by default. RATE_LIMIT_BACKEND=postgres shares the count through the database;
    REDIS_URL shares it through Redis (the project runs PostgreSQL only, so prefer the database)."""
    backend = os.environ.get("RATE_LIMIT_BACKEND", "")
    if backend == "postgres" and engine is not None:
        return PostgresRateLimiter(per_minute, engine)
    if not redis_url:
        return RateLimiter(per_minute)
    import redis
    return RedisRateLimiter(per_minute, redis.Redis.from_url(redis_url, socket_timeout=0.25,
                                                             socket_connect_timeout=0.25))
