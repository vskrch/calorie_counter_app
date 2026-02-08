from __future__ import annotations

import json
from typing import Any

import pytest


def _register_user(client, name: str = "Lee") -> tuple[int, str]:
    response = client.post("/api/auth/register", json={"name": name})
    assert response.status_code == 200
    payload = response.json()
    return payload["user"]["id"], payload["code"]


def test_register_and_login_flow(client) -> None:
    user_id, code = _register_user(client)

    session = client.post("/api/auth/session", json={"code": code})
    assert session.status_code == 200
    assert session.json()["mode"] == "user"

    profile = client.get("/api/profile", headers={"X-Access-Code": code})
    assert profile.status_code == 200
    assert profile.json()["id"] == user_id


def test_register_invalid_name(client) -> None:
    response = client.post("/api/auth/register", json={"name": "   "})
    assert response.status_code == 400


def test_session_invalid_code(client) -> None:
    response = client.post("/api/auth/session", json={"code": "missing"})
    assert response.status_code == 404


def test_manual_analysis_and_history(client) -> None:
    _, code = _register_user(client)

    analyze = client.post(
        "/api/analyze/manual",
        headers={"X-Access-Code": code},
        json={
            "text": json.dumps(
                {
                    "dish": "Salad",
                    "calories_kcal": 180,
                    "protein_g": 8,
                    "fiber_g": 4,
                    "nutrients": ["folate"],
                    "chemicals": ["chlorophyll"],
                }
            ),
            "save_entry": True,
        },
    )
    assert analyze.status_code == 200
    assert analyze.json()["dish"] == "Salad"

    meals = client.get("/api/meals", headers={"X-Access-Code": code})
    assert meals.status_code == 200
    assert meals.json()["entries"][0]["dish"] == "Salad"

    summary = client.get("/api/summary?days=7", headers={"X-Access-Code": code})
    assert summary.status_code == 200
    assert summary.json()["entries"] == 1


def test_manual_analysis_without_saving(client) -> None:
    _, code = _register_user(client)

    analyze = client.post(
        "/api/analyze/manual",
        headers={"X-Access-Code": code},
        json={"text": "{\"dish\": \"Tea\", \"calories\": 2}", "save_entry": False},
    )
    assert analyze.status_code == 200

    meals = client.get("/api/meals", headers={"X-Access-Code": code})
    assert meals.status_code == 200
    assert meals.json()["entries"] == []


def test_delete_entry_flow(client) -> None:
    _, code = _register_user(client)

    client.post(
        "/api/analyze/manual",
        headers={"X-Access-Code": code},
        json={"text": "{\"dish\":\"Toast\",\"calories\":90}", "save_entry": True},
    )
    meals = client.get("/api/meals", headers={"X-Access-Code": code}).json()["entries"]
    entry_id = meals[0]["id"]

    deleted = client.delete(f"/api/meals/{entry_id}", headers={"X-Access-Code": code})
    assert deleted.status_code == 200

    missing = client.delete(f"/api/meals/{entry_id}", headers={"X-Access-Code": code})
    assert missing.status_code == 404


def test_photo_analysis_flow(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _, code = _register_user(client)

    import backend.app.main as main

    def fake_analyze(image_bytes: bytes, provider: str, **_: Any) -> dict[str, Any]:
        assert image_bytes
        return {
            "dish": "Burger",
            "meal_type": "lunch",
            "calories_kcal": 700,
            "protein_g": 30,
            "fiber_g": 3,
            "confidence_score": 0.9,
            "nutrients": ["B12"],
            "chemicals": ["sodium"],
            "notes": "estimate",
            "source": provider,
            "model": "fake",
            "raw": "{}",
        }

    monkeypatch.setattr(main, "analyze_image", fake_analyze)

    response = client.post(
        "/api/analyze/photo",
        headers={"X-Access-Code": code},
        data={"provider": "perplexity", "save_entry": "true"},
        files={"image": ("meal.jpg", b"123", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["dish"] == "Burger"


def test_photo_analysis_errors(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _, code = _register_user(client)

    import backend.app.main as main

    def bad_provider(image_bytes: bytes, provider: str, **_: Any) -> dict[str, Any]:
        assert image_bytes
        assert provider == "bad"
        raise ValueError("Unsupported provider")

    monkeypatch.setattr(main, "analyze_image", bad_provider)

    response = client.post(
        "/api/analyze/photo",
        headers={"X-Access-Code": code},
        data={"provider": "bad"},
        files={"image": ("meal.jpg", b"123", "image/jpeg")},
    )
    assert response.status_code == 400

    def runtime_fail(image_bytes: bytes, provider: str, **_: Any) -> dict[str, Any]:
        assert image_bytes
        assert provider == "perplexity"
        raise RuntimeError("missing key")

    monkeypatch.setattr(main, "analyze_image", runtime_fail)
    response = client.post(
        "/api/analyze/photo",
        headers={"X-Access-Code": code},
        data={"provider": "perplexity"},
        files={"image": ("meal.jpg", b"123", "image/jpeg")},
    )
    assert response.status_code == 400

    def unknown_fail(image_bytes: bytes, provider: str, **_: Any) -> dict[str, Any]:
        assert image_bytes
        assert provider == "perplexity"
        raise Exception("bad gateway")

    monkeypatch.setattr(main, "analyze_image", unknown_fail)
    response = client.post(
        "/api/analyze/photo",
        headers={"X-Access-Code": code},
        data={"provider": "perplexity"},
        files={"image": ("meal.jpg", b"123", "image/jpeg")},
    )
    assert response.status_code == 502


def test_photo_empty_file(client) -> None:
    _, code = _register_user(client)
    response = client.post(
        "/api/analyze/photo",
        headers={"X-Access-Code": code},
        data={"provider": "perplexity"},
        files={"image": ("meal.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400


def test_user_auth_required(client) -> None:
    missing = client.get("/api/profile", headers={"X-Access-Code": "bad"})
    assert missing.status_code == 401

    meals = client.get("/api/meals", headers={"X-Access-Code": "bad"})
    assert meals.status_code == 401


def test_admin_flow(client) -> None:
    user_id, _ = _register_user(client, "Robin")

    login = client.post("/api/auth/session", json={"code": "admin-secret"})
    assert login.status_code == 200
    assert login.json()["mode"] == "admin"

    overview = client.get("/api/admin/overview", headers={"X-Admin-Code": "admin-secret"})
    assert overview.status_code == 200

    users = client.get("/api/admin/users", headers={"X-Admin-Code": "admin-secret"})
    assert users.status_code == 200
    assert users.json()

    reset = client.post(
        f"/api/admin/users/{user_id}/reset-code",
        headers={"X-Admin-Code": "admin-secret"},
    )
    assert reset.status_code == 200
    assert reset.json()["new_code"]

    deleted = client.delete(
        f"/api/admin/users/{user_id}",
        headers={"X-Admin-Code": "admin-secret"},
    )
    assert deleted.status_code == 200

    missing = client.delete(
        "/api/admin/users/9999",
        headers={"X-Admin-Code": "admin-secret"},
    )
    assert missing.status_code == 404


def test_admin_auth_required(client) -> None:
    overview = client.get("/api/admin/overview", headers={"X-Admin-Code": "bad"})
    assert overview.status_code == 401

    users = client.get("/api/admin/users", headers={"X-Admin-Code": "bad"})
    assert users.status_code == 401

    reset = client.post("/api/admin/users/1/reset-code", headers={"X-Admin-Code": "bad"})
    assert reset.status_code == 401


def test_admin_reset_missing_user(client) -> None:
    response = client.post(
        "/api/admin/users/999/reset-code",
        headers={"X-Admin-Code": "admin-secret"},
    )
    assert response.status_code == 404


def test_health_and_static(client) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in health.headers
    assert "x-ratelimit-limit" not in health.headers

    root = client.get("/")
    assert root.status_code == 200
    assert root.headers["x-content-type-options"] == "nosniff"

    asset = client.get("/asset.txt")
    assert asset.status_code == 200

    next_asset = client.get("/_next/file.js")
    assert next_asset.status_code == 200

    fallback = client.get("/unknown")
    assert fallback.status_code == 200

    missing_api = client.get("/api/missing")
    assert missing_api.status_code == 404

def test_missing_static_dir(client_no_static) -> None:
    missing_root = client_no_static.get("/")
    assert missing_root.status_code == 404

    missing_fallback = client_no_static.get("/not-found")
    assert missing_fallback.status_code == 404


def test_auth_rate_limit(client) -> None:
    from backend.app.main import app
    from backend.app.security import RatePolicy

    rate_limiter = app.state.rate_limiter
    original = rate_limiter.policies["auth"]
    rate_limiter.policies["auth"] = RatePolicy(
        name="auth",
        max_requests=2,
        window_seconds=60,
    )

    try:
        first = client.post("/api/auth/session", json={"code": "missing"})
        assert first.status_code == 404
        assert first.headers["x-ratelimit-limit"] == "2"
        assert first.headers["x-ratelimit-remaining"] == "1"

        second = client.post("/api/auth/session", json={"code": "missing"})
        assert second.status_code == 404
        assert second.headers["x-ratelimit-remaining"] == "0"

        limited = client.post("/api/auth/session", json={"code": "missing"})
        assert limited.status_code == 429
        assert limited.headers["x-ratelimit-limit"] == "2"
        assert limited.headers["x-ratelimit-remaining"] == "0"
        assert limited.headers["x-ratelimit-scope"] == "auth"
    finally:
        rate_limiter.policies["auth"] = original
