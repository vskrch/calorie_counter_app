from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from .db import get_connection

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PERPLEXITY_MODEL = "sonar-pro"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.2-11b-vision-instruct:free"


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


def list_admin_users() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                u.id,
                u.name,
                u.code_hint,
                u.created_at,
                COUNT(m.id) AS entries,
                COALESCE(SUM(m.calories_kcal), 0) AS calories_kcal
            FROM users u
            LEFT JOIN meal_entries m ON m.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
            """
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
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO meal_entries (
                user_id, source, dish, calories_kcal, protein_g, fiber_g,
                nutrients_json, chemicals_json, notes, eaten_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source,
                dish,
                calories_kcal,
                protein_g,
                fiber_g,
                json.dumps(nutrients),
                json.dumps(chemicals),
                notes,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        entry_id = cursor.lastrowid

    return {
        "id": entry_id,
        "user_id": user_id,
        "source": source,
        "dish": dish,
        "calories_kcal": calories_kcal,
        "protein_g": protein_g,
        "fiber_g": fiber_g,
        "nutrients": nutrients,
        "chemicals": chemicals,
        "notes": notes,
        "eaten_at": timestamp,
        "created_at": timestamp,
    }


def list_entries(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM meal_entries
            WHERE user_id = ?
            ORDER BY eaten_at DESC
            LIMIT ?
            """,
            (user_id, max(1, min(limit, 200))),
        ).fetchall()
    return [_meal_row_to_dict(row) for row in rows]


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


def analyze_image(image_bytes: bytes, provider: str) -> dict[str, Any]:
    clean_provider = provider.strip().lower() if provider else "perplexity"
    if clean_provider == "perplexity":
        return _analyze_with_perplexity(image_bytes)
    if clean_provider == "openrouter":
        return _analyze_with_openrouter(image_bytes)
    raise ValueError("Unsupported provider")


def analyze_manual(text: str) -> dict[str, Any]:
    parsed = _parse_json(text)
    structured = _normalize_nutrition_payload(parsed)
    structured["source"] = "manual"
    structured["model"] = "manual"
    structured["raw"] = text
    return structured


def _analyze_with_perplexity(image_bytes: bytes) -> dict[str, Any]:
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

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


def _analyze_with_openrouter(image_bytes: bytes) -> dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

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


def _build_message(image_bytes: bytes) -> list[dict[str, Any]]:
    prompt = (
        "You are a nutrition analyst. Inspect this food image and return strict JSON only. "
        "Use keys exactly: dish, calories_kcal, protein_g, fiber_g, nutrients, chemicals, notes. "
        "Rules: calories_kcal/protein_g/fiber_g must be numbers when possible; nutrients and "
        "chemicals must be arrays of short strings."
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
    return {
        "dish": dish,
        "calories_kcal": _to_float(payload.get("calories_kcal") or payload.get("calories")),
        "protein_g": _to_float(payload.get("protein_g") or payload.get("protein")),
        "fiber_g": _to_float(payload.get("fiber_g") or payload.get("fiber")),
        "nutrients": _to_string_list(payload.get("nutrients")),
        "chemicals": _to_string_list(payload.get("chemicals")),
        "notes": _to_optional_text(payload.get("notes")),
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


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


def _meal_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "source": row["source"],
        "dish": row["dish"],
        "calories_kcal": row["calories_kcal"],
        "protein_g": row["protein_g"],
        "fiber_g": row["fiber_g"],
        "nutrients": json.loads(row["nutrients_json"] or "[]"),
        "chemicals": json.loads(row["chemicals_json"] or "[]"),
        "notes": row["notes"],
        "eaten_at": row["eaten_at"],
        "created_at": row["created_at"],
    }
