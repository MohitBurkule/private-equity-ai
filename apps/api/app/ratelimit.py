"""Per-tenant token bucket. In-memory: limits one process; use a shared store (Redis) when scaled out."""
from __future__ import annotations

import os
import threading
import time


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


limiter = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MIN", "600")))
