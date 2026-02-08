from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any

import httpx

from .db import get_connection

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PERPLEXITY_MODEL = "sonar-pro"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.2-11b-vision-instruct:free"
VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack", "other"}
MEAL_TYPE_ALIASES = {
    "brunch": "lunch",
    "supper": "dinner",
}

PROVIDER_PERPLEXITY_WEB = "perplexity_web"


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        return float(raw)
    except ValueError:
        return default


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


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


DEFAULT_GOALS = {
    "calories_kcal": _read_float_env("DEFAULT_DAILY_CALORIES", 2200.0),
    "protein_g": _read_float_env("DEFAULT_DAILY_PROTEIN", 120.0),
    "fiber_g": _read_float_env("DEFAULT_DAILY_FIBER", 30.0),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name: str) -> str:
    cleaned = " ".join(name.split()).strip()
    if not cleaned:
        raise ValueError("Name is required")
    return cleaned[:80]


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def hash_code(code: str) -> str:
    pepper = os.getenv("CODE_PEPPER", "local-dev-pepper")
    payload = f"{pepper}:{normalize_code(code)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_access_code() -> str:
    chunks = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(chunks)


def create_user(name: str) -> dict[str, Any]:
    clean_name = normalize_name(name)
    created_at = now_iso()
    with get_connection() as connection:
        for _ in range(20):
            code = generate_access_code()
            code_hash = hash_code(code)
            code_hint = code[-4:]
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users (name, code_hash, code_hint, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (clean_name, code_hash, code_hint, created_at, created_at),
                )
                connection.commit()
                user_id = cursor.lastrowid
                return {
                    "id": user_id,
                    "name": clean_name,
                    "code_hint": code_hint,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "code": code,
                }
            except sqlite3.IntegrityError:  # pragma: no cover - uniqueness collisions are rare
                continue
    raise RuntimeError("Unable to generate a unique access code")


def get_user_by_code(code: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, name, code_hint, created_at, updated_at FROM users WHERE code_hash = ?",
            (hash_code(code),),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, name, code_hint, created_at, updated_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def list_admin_users(query: str | None = None) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if query and query.strip():
        conditions.append("LOWER(u.name) LIKE ?")
        params.append(f"%{query.strip().lower()}%")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                u.id,
                u.name,
                u.code_hint,
                u.created_at,
                COUNT(m.id) AS entries,
                COALESCE(SUM(m.calories_kcal), 0) AS calories_kcal
            FROM users u
            LEFT JOIN meal_entries m ON m.user_id = u.id
            {where_clause}
            GROUP BY u.id
            ORDER BY u.created_at DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def reset_user_code(user_id: int) -> dict[str, Any] | None:
    user = get_user_by_id(user_id)
    if not user:
        return None

    updated_at = now_iso()
    with get_connection() as connection:
        for _ in range(20):
            code = generate_access_code()
            code_hash = hash_code(code)
            code_hint = code[-4:]
            try:
                connection.execute(
                    "UPDATE users SET code_hash = ?, code_hint = ?, updated_at = ? WHERE id = ?",
                    (code_hash, code_hint, updated_at, user_id),
                )
                connection.commit()
                return {
                    "id": user["id"],
                    "name": user["name"],
                    "code_hint": code_hint,
                    "created_at": user["created_at"],
                    "updated_at": updated_at,
                    "code": code,
                }
            except sqlite3.IntegrityError:  # pragma: no cover - uniqueness collisions are rare
                continue
    raise RuntimeError("Unable to reset code")


def delete_user(user_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()
    return cursor.rowcount > 0


def get_user_goals(user_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT calories_kcal, protein_g, fiber_g, updated_at
            FROM user_goals
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if not row:
        return {
            "calories_kcal": DEFAULT_GOALS["calories_kcal"],
            "protein_g": DEFAULT_GOALS["protein_g"],
            "fiber_g": DEFAULT_GOALS["fiber_g"],
            "updated_at": None,
        }

    return {
        "calories_kcal": float(row["calories_kcal"]),
        "protein_g": float(row["protein_g"]),
        "fiber_g": float(row["fiber_g"]),
        "updated_at": row["updated_at"],
    }


def upsert_user_goals(
    user_id: int,
    calories_kcal: float,
    protein_g: float,
    fiber_g: float,
) -> dict[str, Any]:
    updated_at = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_goals (user_id, calories_kcal, protein_g, fiber_g, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                calories_kcal = excluded.calories_kcal,
                protein_g = excluded.protein_g,
                fiber_g = excluded.fiber_g,
                updated_at = excluded.updated_at
            """,
            (user_id, calories_kcal, protein_g, fiber_g, updated_at),
        )
        connection.commit()

    return get_user_goals(user_id)


def create_entry(
    user_id: int,
    source: str,
    dish: str,
    calories_kcal: float | None,
    protein_g: float | None,
    fiber_g: float | None,
    nutrients: list[str],
    chemicals: list[str],
    notes: str | None,
    meal_type: str = "other",
    confidence_score: float | None = None,
    eaten_at: datetime | str | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    eaten_timestamp = _normalize_datetime(eaten_at) if eaten_at else timestamp
    clean_source = str(source).strip().lower()[:30] or "manual"
    clean_meal_type = normalize_meal_type(meal_type)

    clean_dish = str(dish).strip()[:120]
    if not clean_dish:
        raise ValueError("Dish name is required")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO meal_entries (
                user_id, source, dish, meal_type, calories_kcal, protein_g, fiber_g,
                confidence_score, nutrients_json, chemicals_json, notes, eaten_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                clean_source,
                clean_dish,
                clean_meal_type,
                _coerce_measurement(calories_kcal),
                _coerce_measurement(protein_g),
                _coerce_measurement(fiber_g),
                _coerce_confidence(confidence_score),
                json.dumps(_to_string_list(nutrients)),
                json.dumps(_to_string_list(chemicals)),
                _to_optional_text(notes),
                eaten_timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        entry_id = cursor.lastrowid

    entry = get_entry_for_user(user_id, entry_id)
    if not entry:  # pragma: no cover
        raise RuntimeError("Entry could not be loaded after insert")
    return entry


def list_entries(
    user_id: int,
    limit: int = 30,
    offset: int = 0,
    query: str | None = None,
    source: str | None = None,
    meal_type: str | None = None,
) -> list[dict[str, Any]]:
    conditions: list[str] = ["user_id = ?"]
    params: list[Any] = [user_id]

    if query and query.strip():
        search = f"%{query.strip().lower()}%"
        conditions.append("(LOWER(dish) LIKE ? OR LOWER(COALESCE(notes, '')) LIKE ?)")
        params.extend([search, search])

    if source and source.strip().lower() != "all":
        conditions.append("source = ?")
        params.append(source.strip().lower())

    if meal_type and meal_type.strip().lower() != "all":
        conditions.append("meal_type = ?")
        params.append(normalize_meal_type(meal_type))

    where_clause = " AND ".join(conditions)
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM meal_entries
            WHERE {where_clause}
            ORDER BY datetime(eaten_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_limit, safe_offset],
        ).fetchall()

    return [_meal_row_to_dict(row) for row in rows]


def count_entries(
    user_id: int,
    query: str | None = None,
    source: str | None = None,
    meal_type: str | None = None,
) -> int:
    conditions: list[str] = ["user_id = ?"]
    params: list[Any] = [user_id]

    if query and query.strip():
        search = f"%{query.strip().lower()}%"
        conditions.append("(LOWER(dish) LIKE ? OR LOWER(COALESCE(notes, '')) LIKE ?)")
        params.extend([search, search])

    if source and source.strip().lower() != "all":
        conditions.append("source = ?")
        params.append(source.strip().lower())

    if meal_type and meal_type.strip().lower() != "all":
        conditions.append("meal_type = ?")
        params.append(normalize_meal_type(meal_type))

    where_clause = " AND ".join(conditions)

    with get_connection() as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS total FROM meal_entries WHERE {where_clause}",
            params,
        ).fetchone()
    return int(row["total"] if row else 0)


def get_entry_for_user(user_id: int, entry_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM meal_entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        ).fetchone()
    return _meal_row_to_dict(row) if row else None


def update_entry(user_id: int, entry_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_entry_for_user(user_id, entry_id)
    if not existing:
        return None

    dish = existing["dish"]
    if "dish" in updates and updates["dish"] is not None:
        dish = str(updates["dish"]).strip()[:120]
        if not dish:
            raise ValueError("Dish name is required")

    meal_type = existing["meal_type"]
    if "meal_type" in updates and updates["meal_type"] is not None:
        meal_type = normalize_meal_type(str(updates["meal_type"]))

    calories_kcal = existing["calories_kcal"]
    if "calories_kcal" in updates:
        calories_kcal = _coerce_measurement(updates["calories_kcal"])

    protein_g = existing["protein_g"]
    if "protein_g" in updates:
        protein_g = _coerce_measurement(updates["protein_g"])

    fiber_g = existing["fiber_g"]
    if "fiber_g" in updates:
        fiber_g = _coerce_measurement(updates["fiber_g"])

    nutrients = existing["nutrients"]
    if "nutrients" in updates and updates["nutrients"] is not None:
        nutrients = _to_string_list(updates["nutrients"])

    chemicals = existing["chemicals"]
    if "chemicals" in updates and updates["chemicals"] is not None:
        chemicals = _to_string_list(updates["chemicals"])

    notes = existing["notes"]
    if "notes" in updates:
        notes = _to_optional_text(updates["notes"])

    eaten_at = existing["eaten_at"]
    if "eaten_at" in updates and updates["eaten_at"] is not None:
        eaten_at = _normalize_datetime(updates["eaten_at"])

    updated_at = now_iso()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE meal_entries
            SET
                dish = ?,
                meal_type = ?,
                calories_kcal = ?,
                protein_g = ?,
                fiber_g = ?,
                nutrients_json = ?,
                chemicals_json = ?,
                notes = ?,
                eaten_at = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                dish,
                meal_type,
                calories_kcal,
                protein_g,
                fiber_g,
                json.dumps(nutrients),
                json.dumps(chemicals),
                notes,
                eaten_at,
                updated_at,
                entry_id,
                user_id,
            ),
        )
        connection.commit()

    return get_entry_for_user(user_id, entry_id)


def delete_entry(user_id: int, entry_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM meal_entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def summary_for_user(user_id: int, days: int) -> dict[str, Any]:
    safe_days = max(1, min(days, 90))
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(id) AS entries,
                COALESCE(SUM(calories_kcal), 0) AS calories_kcal,
                COALESCE(SUM(protein_g), 0) AS protein_g,
                COALESCE(SUM(fiber_g), 0) AS fiber_g
            FROM meal_entries
            WHERE user_id = ?
              AND datetime(eaten_at) >= datetime('now', ?)
            """,
            (user_id, f"-{safe_days} days"),
        ).fetchone()

    return {
        "days": safe_days,
        "entries": int(row["entries"] if row else 0),
        "calories_kcal": float(row["calories_kcal"] if row else 0),
        "protein_g": float(row["protein_g"] if row else 0),
        "fiber_g": float(row["fiber_g"] if row else 0),
    }


def daily_analytics_for_user(user_id: int, days: int) -> list[dict[str, Any]]:
    safe_days = max(1, min(days, 120))
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                date(datetime(eaten_at)) AS date_key,
                COUNT(id) AS entries,
                COALESCE(SUM(calories_kcal), 0) AS calories_kcal,
                COALESCE(SUM(protein_g), 0) AS protein_g,
                COALESCE(SUM(fiber_g), 0) AS fiber_g
            FROM meal_entries
            WHERE user_id = ?
              AND datetime(eaten_at) >= datetime('now', ?)
            GROUP BY date_key
            ORDER BY date_key ASC
            """,
            (user_id, f"-{safe_days} days"),
        ).fetchall()

    by_date = {
        row["date_key"]: {
            "entries": int(row["entries"]),
            "calories_kcal": float(row["calories_kcal"]),
            "protein_g": float(row["protein_g"]),
            "fiber_g": float(row["fiber_g"]),
        }
        for row in rows
    }

    start_date = datetime.now(timezone.utc).date() - timedelta(days=safe_days - 1)
    points: list[dict[str, Any]] = []

    for index in range(safe_days):
        day = start_date + timedelta(days=index)
        key = day.isoformat()
        values = by_date.get(
            key,
            {
                "entries": 0,
                "calories_kcal": 0.0,
                "protein_g": 0.0,
                "fiber_g": 0.0,
            },
        )
        points.append({"date": key, **values})

    return points


def list_meals_for_export(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM meal_entries
            WHERE user_id = ?
            ORDER BY datetime(eaten_at) DESC, id DESC
            LIMIT 5000
            """,
            (user_id,),
        ).fetchall()
    return [_meal_row_to_dict(row) for row in rows]


def admin_overview() -> dict[str, Any]:
    with get_connection() as connection:
        user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        row = connection.execute(
            "SELECT COUNT(*) AS entries, COALESCE(SUM(calories_kcal), 0) AS calories_kcal FROM meal_entries"
        ).fetchone()
    return {
        "users": int(user_count),
        "entries": int(row["entries"] if row else 0),
        "calories_kcal": float(row["calories_kcal"] if row else 0),
    }


def admin_top_dishes(days: int, limit: int) -> list[dict[str, Any]]:
    safe_days = max(1, min(days, 180))
    safe_limit = max(1, min(limit, 100))

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                dish,
                meal_type,
                COUNT(*) AS entries,
                COALESCE(SUM(calories_kcal), 0) AS calories_kcal
            FROM meal_entries
            WHERE datetime(eaten_at) >= datetime('now', ?)
            GROUP BY dish, meal_type
            ORDER BY entries DESC, calories_kcal DESC
            LIMIT ?
            """,
            (f"-{safe_days} days", safe_limit),
        ).fetchall()

    return [
        {
            "dish": row["dish"],
            "meal_type": row["meal_type"],
            "entries": int(row["entries"]),
            "calories_kcal": float(row["calories_kcal"]),
        }
        for row in rows
    ]


def get_provider_session(provider: str) -> dict[str, Any] | None:
    clean_provider = (provider or "").strip().lower()
    if not clean_provider:
        return None
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT provider, storage_state_json, updated_at
            FROM provider_sessions
            WHERE provider = ?
            """,
            (clean_provider,),
        ).fetchone()
    return dict(row) if row else None


def upsert_provider_session(provider: str, storage_state: dict[str, Any]) -> dict[str, Any]:
    clean_provider = (provider or "").strip().lower()
    if not clean_provider:
        raise ValueError("Provider is required")
    updated_at = now_iso()
    payload = json.dumps(storage_state, separators=(",", ":"), ensure_ascii=True)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO provider_sessions (provider, storage_state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                storage_state_json = excluded.storage_state_json,
                updated_at = excluded.updated_at
            """,
            (clean_provider, payload, updated_at),
        )
        connection.commit()
    return {"provider": clean_provider, "updated_at": updated_at}


def delete_provider_session(provider: str) -> bool:
    clean_provider = (provider or "").strip().lower()
    if not clean_provider:
        return False
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM provider_sessions WHERE provider = ?",
            (clean_provider,),
        )
        connection.commit()
    return cursor.rowcount > 0


def _load_provider_storage_state(provider: str) -> dict[str, Any] | None:
    session = get_provider_session(provider)
    if not session:
        return None
    raw = (session.get("storage_state_json") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def connect_perplexity_web_session(email: str, password: str) -> dict[str, Any]:
    clean_email = " ".join((email or "").split()).strip()
    clean_password = (password or "").strip()
    if not clean_email:
        raise ValueError("Email is required")
    if not clean_password:
        raise ValueError("Password is required")

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "Playwright is not installed. Install backend dependency and run "
            "`python -m playwright install chromium`."
        ) from exc

    timeout_ms = _read_int_env("PERPLEXITY_WEB_TIMEOUT_MS", 120_000, 5_000, 300_000)
    base_url = (os.getenv("PERPLEXITY_WEB_BASE_URL") or "https://www.perplexity.ai").strip()
    headless = _read_bool_env("PERPLEXITY_WEB_HEADLESS", default=True)

    storage_path = Path(
        os.getenv(
            "PERPLEXITY_WEB_STORAGE_STATE_PATH",
            str(Path(__file__).resolve().parents[1] / "data" / "perplexity_storage_state.json"),
        )
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    db_storage_state = _load_provider_storage_state(PROVIDER_PERPLEXITY_WEB)
    file_storage_state: dict[str, Any] | None = None
    if db_storage_state is None and storage_path.exists():
        try:
            file_storage_state = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception:
            file_storage_state = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context_kwargs: dict[str, Any] = {}
            if db_storage_state is not None:
                context_kwargs["storage_state"] = db_storage_state
            elif file_storage_state is not None:
                context_kwargs["storage_state"] = file_storage_state

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_modals(page)
            _ensure_perplexity_authenticated(
                page,
                email=clean_email,
                password=clean_password,
                timeout_ms=timeout_ms,
            )
            page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_modals(page)

            storage_state = context.storage_state()
            result = upsert_provider_session(PROVIDER_PERPLEXITY_WEB, storage_state)
            try:
                storage_path.write_text(
                    json.dumps(storage_state, separators=(",", ":"), ensure_ascii=True),
                    encoding="utf-8",
                )
            except Exception:
                pass

            context.close()
            browser.close()
            return result
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("Perplexity web automation timed out.") from exc


def analyze_image(
    image_bytes: bytes,
    provider: str,
    *,
    perplexity_api_key: str | None = None,
    openrouter_api_key: str | None = None,
) -> dict[str, Any]:
    clean_provider = provider.strip().lower() if provider else "perplexity"
    if clean_provider == "perplexity":
        return _analyze_with_perplexity(image_bytes, api_key_override=perplexity_api_key)
    if clean_provider == "openrouter":
        return _analyze_with_openrouter(image_bytes, api_key_override=openrouter_api_key)
    if clean_provider == PROVIDER_PERPLEXITY_WEB:
        return _analyze_with_perplexity_web(image_bytes)
    raise ValueError("Unsupported provider")


def analyze_manual(text: str) -> dict[str, Any]:
    parsed = _parse_json(text)
    structured = _normalize_nutrition_payload(parsed)
    structured["source"] = "manual"
    structured["model"] = "manual"
    structured["raw"] = text
    return structured


def _analyze_with_perplexity(
    image_bytes: bytes,
    *,
    api_key_override: str | None = None,
) -> dict[str, Any]:
    api_key = (api_key_override or os.getenv("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "Perplexity API key missing. Set PERPLEXITY_API_KEY or provide X-Perplexity-Api-Key."
        )

    model = os.getenv("PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL)
    api_url = os.getenv("PERPLEXITY_API_URL", "https://api.perplexity.ai/chat/completions")
    payload = {
        "model": model,
        "messages": _build_message(image_bytes),
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=90) as client:
        response = client.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    raw = _extract_message_content(data)
    structured = _normalize_nutrition_payload(_parse_json(raw))
    structured["source"] = "perplexity"
    structured["model"] = model
    structured["raw"] = raw
    return structured


def _analyze_with_openrouter(
    image_bytes: bytes,
    *,
    api_key_override: str | None = None,
) -> dict[str, Any]:
    api_key = (api_key_override or os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "OpenRouter API key missing. Set OPENROUTER_API_KEY or provide X-Openrouter-Api-Key."
        )

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    payload = {
        "model": model,
        "messages": _build_message(image_bytes),
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    app_url = os.getenv("OPENROUTER_APP_URL")
    app_title = os.getenv("OPENROUTER_APP_NAME")
    if app_url:
        headers["HTTP-Referer"] = app_url
    if app_title:
        headers["X-Title"] = app_title

    with httpx.Client(timeout=90) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    raw = _extract_message_content(data)
    structured = _normalize_nutrition_payload(_parse_json(raw))
    structured["source"] = "openrouter"
    structured["model"] = model
    structured["raw"] = raw
    return structured


def _analyze_with_perplexity_web(
    image_bytes: bytes,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "Playwright is not installed. Install backend dependency and run "
            "`python -m playwright install chromium`."
        ) from exc

    timeout_ms = _read_int_env("PERPLEXITY_WEB_TIMEOUT_MS", 120_000, 5_000, 300_000)
    base_url = (os.getenv("PERPLEXITY_WEB_BASE_URL") or "https://www.perplexity.ai").strip()
    prompt = (
        os.getenv("PERPLEXITY_WEB_PROMPT")
        or "Analyze this food image and return strict JSON only with keys: "
        "dish, meal_type, calories_kcal, protein_g, fiber_g, nutrients, chemicals, "
        "confidence_score, notes."
    )
    headless = _read_bool_env("PERPLEXITY_WEB_HEADLESS", default=True)

    storage_path = Path(
        os.getenv(
            "PERPLEXITY_WEB_STORAGE_STATE_PATH",
            str(Path(__file__).resolve().parents[1] / "data" / "perplexity_storage_state.json"),
        )
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    email = (os.getenv("PERPLEXITY_WEB_EMAIL") or "").strip()
    password = (os.getenv("PERPLEXITY_WEB_PASSWORD") or "").strip()

    db_storage_state = _load_provider_storage_state(PROVIDER_PERPLEXITY_WEB)
    file_storage_state: dict[str, Any] | None = None
    if db_storage_state is None and storage_path.exists():
        try:
            file_storage_state = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception:
            file_storage_state = None

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
        tmp_file.write(image_bytes)
        image_path = tmp_file.name

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context_kwargs: dict[str, Any] = {}
            if db_storage_state is not None:
                context_kwargs["storage_state"] = db_storage_state
            elif file_storage_state is not None:
                context_kwargs["storage_state"] = file_storage_state

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_modals(page)
            _ensure_perplexity_authenticated(
                page,
                email=email,
                password=password,
                timeout_ms=timeout_ms,
            )
            page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_modals(page)

            _upload_image_and_submit_prompt(
                page,
                image_path=image_path,
                prompt=prompt,
                timeout_ms=timeout_ms,
            )
            raw = _extract_perplexity_response_text(page, timeout_ms=timeout_ms)

            storage_state = context.storage_state()
            upsert_provider_session(PROVIDER_PERPLEXITY_WEB, storage_state)
            try:
                storage_path.write_text(
                    json.dumps(storage_state, separators=(",", ":"), ensure_ascii=True),
                    encoding="utf-8",
                )
            except Exception:
                pass
            context.close()
            browser.close()

    except PlaywrightTimeoutError as exc:
        raise RuntimeError("Perplexity web automation timed out.") from exc
    finally:
        try:
            Path(image_path).unlink(missing_ok=True)
        except Exception:
            pass

    structured = _normalize_nutrition_payload(_parse_json(raw))
    structured["source"] = "perplexity_web"
    structured["model"] = "perplexity-web"
    structured["raw"] = raw
    return structured


def _ensure_perplexity_authenticated(
    page: Any,
    *,
    email: str,
    password: str,
    timeout_ms: int,
) -> None:
    if not _is_perplexity_login_required(page):
        return

    if not email or not password:
        raise RuntimeError(
            "Perplexity web session is not connected or has expired. Ask an admin to "
            "connect it in the Admin Console, or set PERPLEXITY_WEB_EMAIL and "
            "PERPLEXITY_WEB_PASSWORD on the server to allow automatic re-login."
        )

    _click_first(
        page,
        selectors=[
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
            "a:has-text('Log in')",
            "a:has-text('Sign in')",
            "text=/log in|sign in/i",
        ],
        timeout_ms=2_500,
    )

    _fill_first(
        page,
        selectors=["input[type='email']", "input[name='email']", "input[autocomplete='username']"],
        value=email,
    )
    _fill_first(
        page,
        selectors=[
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ],
        value=password,
    )

    clicked_submit = _click_first(
        page,
        selectors=[
            "button[type='submit']",
            "button:has-text('Continue')",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
        ],
        timeout_ms=2_500,
    )

    if not clicked_submit:
        page.keyboard.press("Enter")

    deadline = monotonic() + (timeout_ms / 1000)
    while monotonic() < deadline:
        page.wait_for_timeout(800)
        if not _is_perplexity_login_required(page):
            return

    raise RuntimeError("Perplexity web login did not complete. Check credentials or captcha.")


def _upload_image_and_submit_prompt(
    page: Any,
    *,
    image_path: str,
    prompt: str,
    timeout_ms: int,
) -> None:
    _click_first(
        page,
        selectors=[
            "button:has-text('Attach')",
            "button:has-text('Upload')",
            "button[aria-label*='Attach']",
            "button[aria-label*='Upload']",
        ],
        timeout_ms=1_200,
    )

    file_input = _first_existing_locator(
        page,
        selectors=["input[type='file']"],
    )
    if file_input is None:
        raise RuntimeError("Could not find file upload input on Perplexity web page.")
    file_input.set_input_files(image_path)

    prompt_locator = _first_existing_locator(
        page,
        selectors=[
            "textarea[placeholder*='Ask']",
            "textarea[placeholder*='question']",
            "textarea",
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
        ],
    )
    if prompt_locator is None:
        raise RuntimeError("Could not find prompt input on Perplexity web page.")

    try:
        prompt_locator.fill(prompt)
    except Exception:
        prompt_locator.click()
        page.keyboard.type(prompt)

    sent = _click_first(
        page,
        selectors=[
            "button:has-text('Submit')",
            "button:has-text('Send')",
            "button[aria-label*='Send']",
        ],
        timeout_ms=1_000,
    )
    if not sent:
        page.keyboard.press("Enter")

    page.wait_for_timeout(min(2_500, timeout_ms // 8))


def _extract_perplexity_response_text(page: Any, *, timeout_ms: int) -> str:
    candidate_selectors = [
        "main article",
        "[data-testid='answer']",
        "[class*='answer']",
        "[class*='prose']",
        "main",
    ]

    deadline = monotonic() + (timeout_ms / 1000)
    best_text = ""

    while monotonic() < deadline:
        for selector in candidate_selectors:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 8)
            except Exception:
                count = 0

            for index in range(count):
                try:
                    text = locator.nth(index).inner_text(timeout=500).strip()
                except Exception:
                    continue
                if len(text) > len(best_text):
                    best_text = text

        if best_text and ("{" in best_text and "}" in best_text):
            return best_text
        if len(best_text) > 600:
            return best_text
        page.wait_for_timeout(1200)

    if best_text:
        return best_text
    raise RuntimeError("Could not extract Perplexity web response text.")


def _is_perplexity_login_required(page: Any) -> bool:
    selectors = [
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "a:has-text('Log in')",
        "a:has-text('Sign in')",
        "text=/log in|sign in/i",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible():
                return True
        except Exception:
            continue
    return False


def _dismiss_optional_modals(page: Any) -> None:
    _click_first(
        page,
        selectors=[
            "button:has-text('Close')",
            "button:has-text('Got it')",
            "button[aria-label='Close']",
        ],
        timeout_ms=500,
    )


def _click_first(page: Any, *, selectors: list[str], timeout_ms: int) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            locator.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _fill_first(page: Any, *, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            locator.fill(value)
            return True
        except Exception:
            continue
    return False


def _first_existing_locator(page: Any, *, selectors: list[str]) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return None


def _build_message(image_bytes: bytes) -> list[dict[str, Any]]:
    prompt = (
        "You are a nutrition analyst. Inspect this food image and return strict JSON only. "
        "Use keys exactly: dish, meal_type, calories_kcal, protein_g, fiber_g, nutrients, "
        "chemicals, confidence_score, notes. Rules: calories_kcal/protein_g/fiber_g must be "
        "numbers when possible; nutrients and chemicals must be arrays of short strings. "
        "meal_type must be one of breakfast/lunch/dinner/snack/other."
    )
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                },
            ],
        }
    ]


def _extract_message_content(data: dict[str, Any]) -> str:
    try:
        message = data["choices"][0]["message"]["content"]
        if isinstance(message, list):
            fragments: list[str] = []
            for part in message:
                if isinstance(part, dict) and part.get("type") == "text":
                    fragments.append(part.get("text", ""))
                elif isinstance(part, str):
                    fragments.append(part)
            return "\n".join(fragment for fragment in fragments if fragment)
        return str(message)
    except Exception:
        return json.dumps(data)


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return {}

    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _normalize_nutrition_payload(payload: dict[str, Any]) -> dict[str, Any]:
    dish = str(payload.get("dish") or "Unknown dish").strip()[:120] or "Unknown dish"
    meal_type_value = payload.get("meal_type")
    meal_type = normalize_meal_type(str(meal_type_value)) if meal_type_value else "other"

    return {
        "dish": dish,
        "meal_type": meal_type,
        "calories_kcal": _coerce_measurement(payload.get("calories_kcal") or payload.get("calories")),
        "protein_g": _coerce_measurement(payload.get("protein_g") or payload.get("protein")),
        "fiber_g": _coerce_measurement(payload.get("fiber_g") or payload.get("fiber")),
        "confidence_score": _coerce_confidence(payload.get("confidence_score")),
        "nutrients": _to_string_list(payload.get("nutrients")),
        "chemicals": _to_string_list(payload.get("chemicals")),
        "notes": _to_optional_text(payload.get("notes")),
    }


def normalize_meal_type(value: str | None) -> str:
    if value is None:
        return "other"

    cleaned = re.sub(r"[^a-z]", "", value.lower())
    if not cleaned:
        return "other"

    cleaned = MEAL_TYPE_ALIASES.get(cleaned, cleaned)
    if cleaned not in VALID_MEAL_TYPES:
        raise ValueError("Invalid meal type")
    return cleaned


def _coerce_measurement(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric < 0:
            return None
        return round(numeric, 2)

    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None

    try:
        numeric = float(match.group(0))
    except ValueError:
        return None

    if numeric < 0:
        return None
    return round(numeric, 2)


def _to_float(value: Any) -> float | None:
    # Backward-compat helper kept for existing tests/callers.
    return _coerce_measurement(value)


def _coerce_confidence(value: Any) -> float | None:
    numeric = _coerce_measurement(value)
    if numeric is None:
        return None
    if numeric > 1:
        numeric = numeric / 100 if numeric <= 100 else 1
    return max(0.0, min(1.0, round(numeric, 3)))


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [part.strip() for part in str(value).split(",")]

    cleaned = [item[:80] for item in items if item]
    return cleaned[:20]


def _to_optional_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text[:400] if text else None


def _normalize_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _meal_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "source": row["source"],
        "dish": row["dish"],
        "meal_type": row["meal_type"] or "other",
        "calories_kcal": row["calories_kcal"],
        "protein_g": row["protein_g"],
        "fiber_g": row["fiber_g"],
        "confidence_score": row["confidence_score"],
        "nutrients": json.loads(row["nutrients_json"] or "[]"),
        "chemicals": json.loads(row["chemicals_json"] or "[]"),
        "notes": row["notes"],
        "eaten_at": row["eaten_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] or row["created_at"] or row["eaten_at"],
    }
