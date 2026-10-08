"""Tiny in-memory sliding-window rate limiter for endpoints that create sandbox orders / call the LLM."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int, per_hour: int, global_per_hour: int, clock=time.monotonic) -> None:
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.global_per_hour = global_per_hour
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._global: deque = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _trim(q: deque, now: float, window: float) -> None:
        while q and now - q[0] >= window:
            q.popleft()

    def check(self, key: str) -> str | None:
        """Records a hit and returns None, or returns a human-readable reason if the hit is refused."""
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            self._trim(q, now, 3600)
            self._trim(self._global, now, 3600)
            last_minute = sum(1 for t in q if now - t < 60)
            if last_minute >= self.per_minute:
                return f"Rate limit: at most {self.per_minute} runs per minute. Please wait a moment."
            if len(q) >= self.per_hour:
                return f"Rate limit: at most {self.per_hour} runs per hour from one address."
            if len(self._global) >= self.global_per_hour:
                return "Rate limit: the demo is busy (global hourly cap reached). Please try again later."
            q.append(now)
            self._global.append(now)
            return None


def client_key(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
