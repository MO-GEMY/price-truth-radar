"""Thread-safe bounded in-memory TTL cache and HTTP Cache-Control helpers.

Protects Render FastAPI workers and Neon PostgreSQL during viral traffic spikes
with zero external dependencies.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from fastapi import Response


class TTLCache:
    """Bounded LRU + TTL in-memory cache safe across FastAPI threadpool workers."""

    def __init__(self, maxsize: int = 512, default_ttl: float = 300.0) -> None:
        self._maxsize = max(1, maxsize)
        self._default_ttl = float(default_ttl)
        self._lock = threading.RLock()
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        ttl_s = self._default_ttl if ttl is None else float(ttl)
        expires_at = time.monotonic() + max(1.0, ttl_s)
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Shared process-level read caches
api_cache = TTLCache(maxsize=1024, default_ttl=300.0)
sitemap_cache = TTLCache(maxsize=16, default_ttl=3600.0)


def set_cache_headers(
    response: Response,
    *,
    s_maxage: int = 600,
    stale_while_revalidate: int = 300,
) -> None:
    """Attach Cloudflare/CDN-friendly public Cache-Control headers for read endpoints."""
    response.headers["Cache-Control"] = (
        f"public, s-maxage={s_maxage}, stale-while-revalidate={stale_while_revalidate}"
    )
