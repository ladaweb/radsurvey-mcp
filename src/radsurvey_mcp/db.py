"""SQLite storage layer.

The server only ever opens the database in read-only mode. The loader
(`build_database`) is a separate step you run once to import JSON data.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = PACKAGE_ROOT / "data" / "sample_surveys.json"
DEFAULT_DB = PACKAGE_ROOT / "data" / "surveys.db"

SCHEMA = """
CREATE TABLE areas (
    area_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    facility TEXT NOT NULL,
    posted_classification TEXT NOT NULL
);
CREATE TABLE surveys (
    survey_id TEXT PRIMARY KEY,
    area_id TEXT NOT NULL REFERENCES areas(area_id),
    date TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('robot', 'manual')),
    instrument TEXT NOT NULL
);
CREATE TABLE readings (
    reading_id INTEGER PRIMARY KEY,
    survey_id TEXT NOT NULL REFERENCES surveys(survey_id),
    x_m REAL NOT NULL,
    y_m REAL NOT NULL,
    dose_rate_usv_h REAL NOT NULL CHECK (dose_rate_usv_h >= 0)
);
CREATE INDEX idx_readings_survey ON readings(survey_id);
CREATE INDEX idx_readings_dose ON readings(dose_rate_usv_h);
CREATE INDEX idx_surveys_area_date ON surveys(area_id, date);
"""


def build_database(json_path: Path = DEFAULT_JSON, db_path: Path = DEFAULT_DB) -> Path:
    """(Re)create the SQLite database from a JSON export."""
    data = json.loads(Path(json_path).read_text())
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO areas VALUES (:area_id, :name, :facility, :posted_classification)",
            data["areas"],
        )
        for s in data["surveys"]:
            conn.execute(
                "INSERT INTO surveys VALUES (?, ?, ?, ?, ?)",
                (s["survey_id"], s["area_id"], s["date"], s["method"], s["instrument"]),
            )
            conn.executemany(
                "INSERT INTO readings (survey_id, x_m, y_m, dose_rate_usv_h) VALUES (?, ?, ?, ?)",
                [(s["survey_id"], r["x_m"], r["y_m"], r["dose_rate_usv_h"]) for r in s["readings"]],
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def resolve_db_path() -> Path:
    """DB path from the RADSURVEY_DB env var, falling back to the bundled sample."""
    return Path(os.environ.get("RADSURVEY_DB", DEFAULT_DB))


def connect_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the database read-only. Builds the sample DB on first run if missing."""
    path = Path(db_path) if db_path else resolve_db_path()
    if not path.exists():
        if path == DEFAULT_DB:
            build_database()
        else:
            raise FileNotFoundError(f"Survey database not found: {path}")
    # mode=ro enforces read-only at the SQLite level, not just by convention.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
