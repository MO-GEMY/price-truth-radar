"""Lightweight anti-spam for public forms — process memory only, zero DB.

- ``RateLimiter``: bounded sliding-window counters per key (per-IP and global).
- ``client_ip``: best-effort client IP behind Cloudflare / Railway edge proxies.
- ``verify_turnstile``: optional Cloudflare Turnstile check, active only when
  ``TURNSTILE_SECRET_KEY`` is set.

Counters live per worker process, so limits are per replica and reset on every
deploy. That is deliberate: enough to brake abuse without touching Neon.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import secrets
import threading
import time
from collections import OrderedDict, deque

import httpx
from fastapi import Request

from app.notify import env_int, env_str

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Per-process salt so the limiter never retains a raw client IP.
_IP_KEY_SALT = secrets.token_hex(16)


class RateLimiter:
    """Sliding-window counter with a bounded key set (oldest keys are evicted)."""

    def __init__(
        self,
        *,
        limit_env: str,
        default_limit: int,
        window_env: str,
        default_window: int,
        max_keys: int = 10_000,
    ) -> None:
        self._limit_env = limit_env
        self._default_limit = default_limit
        self._window_env = window_env
        self._default_window = default_window
        self._max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return env_int(self._limit_env, self._default_limit, lo=1, hi=10_000)

    @property
    def window(self) -> float:
        return float(env_int(self._window_env, self._default_window, lo=1, hi=86_400))

    def allow(self, key: str) -> tuple[bool, int]:
        """Record one hit; return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        window = self.window
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
                while len(self._hits) > self._max_keys:
                    self._hits.popitem(last=False)
            self._hits.move_to_end(key)
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, math.ceil(hits[0] + window - now))
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    Prefers Cloudflare's ``CF-Connecting-IP``, then the *last* ``X-Forwarded-For``
    hop (the one appended by the trusted Railway edge, which a client cannot
    forge), then the socket peer. A client that reaches the origin directly while
    spoofing these headers can still rotate the per-IP key, which is why every
    form also carries a global budget.
    """
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header, "").strip()
        if value:
            hops = [hop.strip() for hop in value.split(",") if hop.strip()]
            if hops:
                return hops[-1][:64]
    return (request.client.host if request.client else "unknown")[:64]


def enforce_rate_limit(ip_limiter: RateLimiter, global_limiter: RateLimiter, ip: str) -> tuple[bool, int]:
    """Per-IP brake first, then the process-wide outbound budget."""
    allowed, retry_after = ip_limiter.allow("ip:" + hashlib.sha256((_IP_KEY_SALT + ip).encode("utf-8")).hexdigest())
    if not allowed:
        return False, retry_after
    return global_limiter.allow("all")


def turnstile_site_key() -> str:
    """Public widget key served to the frontend; empty when Turnstile is off."""
    return env_str("TURNSTILE_SITE_KEY")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def verify_turnstile(token: str, remote_ip: str) -> tuple[bool, str]:
    """Validate a widget token; passes automatically while the feature is off.

    Fails closed once enabled: an unreachable or erroring siteverify rejects the
    submission rather than letting automation through.
    """
    secret = env_str("TURNSTILE_SECRET_KEY")
    if not secret:
        return True, "disabled"
    if not token:
        return False, "missing token"

    form = {"secret": secret, "response": token}
    if _is_ip(remote_ip):
        form["remoteip"] = remote_ip
    try:
        resp = httpx.post(TURNSTILE_VERIFY_URL, data=form, timeout=8.0)
    except httpx.HTTPError:
        return False, "siteverify unreachable"
    if resp.status_code != 200:
        return False, f"siteverify HTTP {resp.status_code}"
    try:
        payload = resp.json()
    except ValueError:
        return False, "siteverify returned a non-JSON body"
    if not isinstance(payload, dict):
        return False, "siteverify returned an unexpected body"
    if not payload.get("success"):
        codes = payload.get("error-codes") or ["no detail"]
        return False, f"rejected: {','.join(map(str, codes))}"[:200]
    return True, "ok"
