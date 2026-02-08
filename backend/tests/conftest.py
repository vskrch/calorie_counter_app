from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, with_static: bool) -> TestClient:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ADMIN_CODE", "admin-secret")

    if with_static:
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html>OK</html>")
        (static_dir / "asset.txt").write_text("asset")
        next_dir = static_dir / "_next"
        next_dir.mkdir()
        (next_dir / "file.js").write_text("console.log('ok')")
        monkeypatch.setenv("FRONTEND_STATIC_DIR", str(static_dir))
    else:
        monkeypatch.delenv("FRONTEND_STATIC_DIR", raising=False)

    import backend.app.main as main

    importlib.reload(main)
    return TestClient(main.app)


@pytest.fixture()
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    with _load_client(monkeypatch, tmp_path, with_static=True) as test_client:
        yield test_client


@pytest.fixture()
def client_no_static(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    with _load_client(monkeypatch, tmp_path, with_static=False) as test_client:
        yield test_client
