from __future__ import annotations

import pytest
from starlette.responses import Response

from backend.app.security import (
    DEFAULT_CSP,
    InMemoryRateLimiter,
    RatePolicy,
    apply_security_headers,
    extract_client_ip,
    load_rate_policies,
    policy_key_for_path,
)


def test_policy_key_for_path() -> None:
    assert policy_key_for_path("/") is None
    assert policy_key_for_path("/api/health") is None
    assert policy_key_for_path("/api/auth/register") == "auth"
    assert policy_key_for_path("/api/auth/session") == "auth"
    assert policy_key_for_path("/api/analyze/photo") == "analyze"
    assert policy_key_for_path("/api/admin/users") == "admin"
    assert policy_key_for_path("/api/meals") == "api"


def test_extract_client_ip() -> None:
    assert extract_client_ip({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, "9.9.9.9") == "1.2.3.4"
    assert extract_client_ip({"x-real-ip": "2.2.2.2"}, "9.9.9.9") == "2.2.2.2"
    assert extract_client_ip({}, "9.9.9.9") == "9.9.9.9"


def test_rate_limiter_allows_then_blocks() -> None:
    policy = RatePolicy(name="auth", max_requests=2, window_seconds=60)
    limiter = InMemoryRateLimiter({"auth": policy})

    first = limiter.check("auth:1.1.1.1", policy)
    second = limiter.check("auth:1.1.1.1", policy)
    third = limiter.check("auth:1.1.1.1", policy)

    assert first == (True, 0, 1)
    assert second == (True, 0, 0)
    assert third[0] is False
    assert third[1] >= 1
    assert third[2] == 0


def test_apply_security_headers() -> None:
    response = Response("ok")
    apply_security_headers(response, is_https=False, csp=DEFAULT_CSP)

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == DEFAULT_CSP
    assert "strict-transport-security" not in response.headers

    secure_response = Response("ok")
    apply_security_headers(secure_response, is_https=True, csp=DEFAULT_CSP)
    assert secure_response.headers["strict-transport-security"].startswith("max-age=")


def test_load_rate_policies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "bad")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_WINDOW", "-1")
    monkeypatch.setenv("RATE_LIMIT_ANALYZE_PER_WINDOW", "999999")

    policies = load_rate_policies()
    assert policies["auth"].window_seconds == 60
    assert policies["auth"].max_requests == 1
    assert policies["analyze"].max_requests == 500
