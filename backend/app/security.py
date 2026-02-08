from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from math import ceil
from time import monotonic
from typing import Deque, Mapping

from starlette.responses import Response

DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' https://api.perplexity.ai https://openrouter.ai; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@dataclass(frozen=True)
class RatePolicy:
    name: str
    max_requests: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self, policies: dict[str, RatePolicy]) -> None:
        self.policies = policies
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, policy: RatePolicy) -> tuple[bool, int, int]:
        now = monotonic()
        earliest_allowed = now - policy.window_seconds

        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= earliest_allowed:
                bucket.popleft()

            if len(bucket) >= policy.max_requests:
                retry_after = max(1, ceil(policy.window_seconds - (now - bucket[0])))
                return False, retry_after, 0

            bucket.append(now)
            remaining = max(0, policy.max_requests - len(bucket))
            return True, 0, remaining


def load_rate_policies() -> dict[str, RatePolicy]:
    window_seconds = _read_int_env("RATE_LIMIT_WINDOW_SECONDS", default=60, min_value=1, max_value=3600)
    return {
        "auth": RatePolicy(
            name="auth",
            max_requests=_read_int_env("RATE_LIMIT_AUTH_PER_WINDOW", default=20, min_value=1, max_value=500),
            window_seconds=window_seconds,
        ),
        "analyze": RatePolicy(
            name="analyze",
            max_requests=_read_int_env(
                "RATE_LIMIT_ANALYZE_PER_WINDOW",
                default=12,
                min_value=1,
                max_value=500,
            ),
            window_seconds=window_seconds,
        ),
        "admin": RatePolicy(
            name="admin",
            max_requests=_read_int_env("RATE_LIMIT_ADMIN_PER_WINDOW", default=90, min_value=1, max_value=2000),
            window_seconds=window_seconds,
        ),
        "api": RatePolicy(
            name="api",
            max_requests=_read_int_env("RATE_LIMIT_API_PER_WINDOW", default=240, min_value=1, max_value=5000),
            window_seconds=window_seconds,
        ),
    }


def policy_key_for_path(path: str) -> str | None:
    if not path.startswith("/api/"):
        return None
    if path == "/api/health":
        return None
    if path in ("/api/auth/register", "/api/auth/session"):
        return "auth"
    if path.startswith("/api/analyze/"):
        return "analyze"
    if path.startswith("/api/admin/"):
        return "admin"
    return "api"


def extract_client_ip(headers: Mapping[str, str], fallback_ip: str) -> str:
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        leftmost = forwarded.split(",", 1)[0].strip()
        if leftmost:
            return leftmost

    real_ip = headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    return fallback_ip


def apply_security_headers(response: Response, *, is_https: bool, csp: str) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

    if is_https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value
