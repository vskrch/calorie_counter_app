from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"


def get_db_path() -> Path:
    return Path(os.getenv("APP_DB_PATH", DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code_hash TEXT NOT NULL UNIQUE,
                code_hint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                dish TEXT NOT NULL,
                calories_kcal REAL,
                protein_g REAL,
                fiber_g REAL,
                nutrients_json TEXT NOT NULL,
                chemicals_json TEXT NOT NULL,
                notes TEXT,
                eaten_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_meal_entries_user_date ON meal_entries(user_id, eaten_at DESC);
            """
        )
        connection.commit()
