from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app import services
from backend.app.db import init_db


@pytest.fixture(autouse=True)
def setup_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    init_db()


def test_user_flow_and_code_reset() -> None:
    user = services.create_user("  Ada Lovelace  ")
    assert user["name"] == "Ada Lovelace"

    found = services.get_user_by_code(user["code"])
    assert found and found["id"] == user["id"]

    updated = services.reset_user_code(user["id"])
    assert updated and updated["code"] != user["code"]
    assert services.get_user_by_code(updated["code"])


def test_delete_user_and_entry_cycle() -> None:
    user = services.create_user("Lee")
    entry = services.create_entry(
        user_id=user["id"],
        source="manual",
        dish="Rice bowl",
        calories_kcal=450,
        protein_g=15,
        fiber_g=6,
        nutrients=["vitamin B"],
        chemicals=["starch"],
        notes="test",
    )

    rows = services.list_entries(user["id"])
    assert rows and rows[0]["id"] == entry["id"]

    summary = services.summary_for_user(user["id"], days=7)
    assert summary["entries"] == 1
    assert summary["calories_kcal"] == 450.0

    assert services.delete_entry(user["id"], entry["id"]) is True
    assert services.delete_entry(user["id"], entry["id"]) is False

    assert services.delete_user(user["id"]) is True
    assert services.delete_user(user["id"]) is False


def test_list_admin_users_and_overview() -> None:
    user = services.create_user("Jules")
    services.create_entry(
        user_id=user["id"],
        source="manual",
        dish="Toast",
        calories_kcal=120,
        protein_g=4,
        fiber_g=2,
        nutrients=[],
        chemicals=[],
        notes=None,
    )

    users = services.list_admin_users()
    assert users and users[0]["entries"] >= 1

    overview = services.admin_overview()
    assert overview["users"] >= 1
    assert overview["entries"] >= 1


def test_normalizers_and_helpers() -> None:
    assert services.normalize_name("  A   B ") == "A B"
    assert services.normalize_code("aa-bb 11") == "AABB11"
    assert services.hash_code("x") == services.hash_code("X")
    assert len(services.generate_access_code().split("-")) == 4

    payload = services._normalize_nutrition_payload(
        {
            "dish": "Soup",
            "calories": "200 kcal",
            "protein": "10g",
            "fiber": "3g",
            "nutrients": "vitamin c, potassium",
            "chemicals": ["lycopene"],
            "notes": "warm",
        }
    )
    assert payload["dish"] == "Soup"
    assert payload["calories_kcal"] == 200.0
    assert payload["protein_g"] == 10.0
    assert payload["fiber_g"] == 3.0
    assert payload["nutrients"] == ["vitamin c", "potassium"]

    assert services._to_float(None) is None
    assert services._to_float("abc") is None
    assert services._to_float("42.5g") == 42.5
    assert services._to_string_list(None) == []
    assert services._to_string_list("a, b") == ["a", "b"]
    assert services._to_optional_text("  hi ") == "hi"
    assert services._to_optional_text("   ") is None


def test_parse_and_extract_helpers() -> None:
    assert services._parse_json("") == {}
    assert services._parse_json("{\"dish\": \"Salad\"}")["dish"] == "Salad"
    assert services._parse_json("```json\n{\"dish\": \"Salad\"}\n```")["dish"] == "Salad"
    assert services._parse_json("prefix {\"dish\":\"X\"} suffix")["dish"] == "X"
    assert services._parse_json("not-json") == {}

    list_message = {
        "choices": [{"message": {"content": [{"type": "text", "text": "hello"}]}}]
    }
    assert "hello" in services._extract_message_content(list_message)
    assert services._extract_message_content({"bad": "payload"}).startswith("{")


def test_analyze_manual_sets_source_and_model() -> None:
    raw = json.dumps({"dish": "Taco", "calories_kcal": 220})
    result = services.analyze_manual(raw)
    assert result["source"] == "manual"
    assert result["model"] == "manual"
    assert result["dish"] == "Taco"


def test_analyze_image_provider_errors() -> None:
    with pytest.raises(ValueError):
        services.analyze_image(b"123", provider="unknown")


def test_analyze_perplexity_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        services.analyze_image(b"abc", provider="perplexity")


def test_analyze_openrouter_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        services.analyze_image(b"abc", provider="openrouter")


def test_analyze_perplexity_web_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_web(image_bytes: bytes, **_: Any) -> dict[str, Any]:
        assert image_bytes == b"abc"
        return {
            "dish": "Bowl",
            "meal_type": "lunch",
            "calories_kcal": 410,
            "protein_g": 20,
            "fiber_g": 6,
            "confidence_score": 0.81,
            "nutrients": ["iron"],
            "chemicals": [],
            "notes": None,
            "source": "perplexity_web",
            "model": "perplexity-web",
            "raw": "{}",
        }

    monkeypatch.setattr(services, "_analyze_with_perplexity_web", fake_web)
    result = services.analyze_image(b"abc", provider="perplexity_web")
    assert result["source"] == "perplexity_web"
    assert result["dish"] == "Bowl"


def test_analyze_perplexity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERPLEXITY_API_KEY", "key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "dish": "Pasta",
                                    "calories_kcal": 510,
                                    "protein_g": 18,
                                    "fiber_g": 5,
                                    "nutrients": ["iron"],
                                    "chemicals": ["gluten"],
                                }
                            )
                        }
                    }
                ]
            }

    class DummyClient:
        def __init__(self, *_: Any, **__: Any) -> None:
            return None

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def post(self, *_: Any, **__: Any) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr(services.httpx, "Client", DummyClient)
    result = services.analyze_image(b"img", provider="perplexity")
    assert result["dish"] == "Pasta"
    assert result["source"] == "perplexity"


def test_analyze_openrouter_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"dish\":\"Apple\",\"calories_kcal\":95}\n```"
                        }
                    }
                ]
            }

    class DummyClient:
        def __init__(self, *_: Any, **__: Any) -> None:
            return None

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def post(self, *_: Any, **__: Any) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr(services.httpx, "Client", DummyClient)
    result = services.analyze_image(b"img", provider="openrouter")
    assert result["dish"] == "Apple"
    assert result["source"] == "openrouter"


def test_create_user_retries_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenConnection:
        def __enter__(self) -> "BrokenConnection":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("boom")

        def commit(self) -> None:
            return None

    monkeypatch.setattr(services, "get_connection", lambda: BrokenConnection())
    with pytest.raises(RuntimeError):
        services.create_user("Fail")
