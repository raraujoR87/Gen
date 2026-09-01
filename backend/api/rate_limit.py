"""Simple in-memory token-bucket rate limiting, keyed by user id.

This is process-local (not shared across Modal workers/replicas) and is
intended as a cheap first line of defense in front of the execution engine's
own risk checks, not as the system of record for quota enforcement.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from backend.api.auth import get_current_user_id

RATE_LIMIT_CAPACITY = float(os.environ.get("RATE_LIMIT_CAPACITY", "10"))
RATE_LIMIT_REFILL_PER_SECOND = float(os.environ.get("RATE_LIMIT_REFILL_PER_SECOND", "1"))


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketRateLimiter:
    """Thread-safe in-memory token bucket, one bucket per key."""

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = max(0.0, now - bucket.last_refill)
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
        bucket.last_refill = now

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, last_refill=now)
                self._buckets[key] = bucket
            else:
                self._refill(bucket, now)

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# Module-level singleton shared by the FastAPI dependency below. Tests can
# call `.reset()` on it (or construct/patch a fresh limiter) between cases.
limiter = TokenBucketRateLimiter(
    capacity=RATE_LIMIT_CAPACITY,
    refill_per_second=RATE_LIMIT_REFILL_PER_SECOND,
)


def rate_limit_dependency(user_id: str = Depends(get_current_user_id)) -> str:
    """FastAPI dependency: enforces a per-user token bucket, then returns user_id."""
    if not limiter.allow(user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    return user_id
