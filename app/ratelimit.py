"""Tiny in-memory sliding-window rate limiter for endpoints that create sandbox orders / call the LLM."""

from __future__ import annotations

import ipaddress
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


class Cooldown:
    """Per-key minimum interval plus a global minimum interval (e.g. demo reset)."""

    def __init__(self, per_key_s: float, global_s: float, clock=time.monotonic) -> None:
        self.per_key_s, self.global_s, self._clock = per_key_s, global_s, clock
        self._last: dict[str, float] = {}
        self._last_global: float | None = None
        self._lock = threading.Lock()

    def check(self, key: str) -> str | None:
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.per_key_s:
                return f"Reset was used from your address {int(now - last)} s ago; please wait " \
                       f"{int(self.per_key_s - (now - last)) + 1} s."
            if self._last_global is not None and now - self._last_global < self.global_s:
                return f"The demo was just reset by someone else; please wait " \
                       f"{int(self.global_s - (now - self._last_global)) + 1} s."
            self._last[key] = self._last_global = now
            if len(self._last) > 5000:
                for k in [k for k, v in self._last.items() if now - v >= self.per_key_s]:
                    del self._last[k]
            return None


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_key(request, trusted_hops: int = 1, trust_cf_header: bool = True) -> str:
    """Client address for rate limiting, resistant to a spoofed X-Forwarded-For.

    Proxies append to X-Forwarded-For, so the leftmost entries are whatever the client sent. We take
    the entry `trusted_hops` from the right (the address our trusted proxy chain saw), never the
    leftmost. On Render (behind Cloudflare), CF-Connecting-IP is set by Cloudflare's edge and
    overwrites any client value, so it is preferred when present (TRADEOS_TRUST_CF_CONNECTING_IP).
    request.client is not used when headers exist: uvicorn may already have taken the leftmost
    X-Forwarded-For value when FORWARDED_ALLOW_IPS='*'.
    """
    if trust_cf_header:
        cf = _valid_ip(request.headers.get("cf-connecting-ip", ""))
        if cf:
            return cf
    parts = [p.strip() for p in ",".join(request.headers.getlist("x-forwarded-for")).split(",") if p.strip()]
    if parts and trusted_hops > 0:
        chosen = parts[-trusted_hops] if len(parts) >= trusted_hops else parts[0]
        ip = _valid_ip(chosen)
        if ip:
            return ip
    return request.client.host if request.client else "unknown"
