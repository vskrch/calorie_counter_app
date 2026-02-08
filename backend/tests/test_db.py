from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import db


def test_get_db_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    assert db.get_db_path() == db.DEFAULT_DB_PATH


def test_get_db_path_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom.db"
    monkeypatch.setenv("APP_DB_PATH", str(custom))
    assert db.get_db_path() == custom


def test_connection_enables_foreign_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "fk.db"))
    with db.get_connection() as connection:
        value = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert value == 1
