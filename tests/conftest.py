import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radsurvey_mcp.db import SCHEMA


@pytest.fixture
def conn():
    """Tiny hand-built database with known values, so assertions are exact."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.executemany(
        "INSERT INTO areas VALUES (?, ?, ?, ?)",
        [("A1", "Alpha Room", "Test Facility", "Radiation Area"),
         ("B1", "Beta Room", "Test Facility", "Unrestricted")],
    )
    c.executemany(
        "INSERT INTO surveys VALUES (?, ?, ?, ?, ?)",
        [("S1", "A1", "2026-07-01", "robot", "CZT"),
         ("S2", "A1", "2026-08-01", "manual", "Ion chamber"),
         ("S3", "B1", "2026-08-02", "robot", "CZT")],
    )
    c.executemany(
        "INSERT INTO readings (survey_id, x_m, y_m, dose_rate_usv_h) VALUES (?, ?, ?, ?)",
        [
            ("S1", 0.0, 0.0, 1.0), ("S1", 1.0, 0.0, 50.0),
            # S2: two hot points 0.5 m apart (same source) + one separate source
            ("S2", 0.0, 0.0, 2.0), ("S2", 5.0, 5.0, 100.0), ("S2", 5.5, 5.0, 90.0),
            ("S2", 10.0, 0.0, 40.0),
            ("S3", 0.0, 0.0, 0.1), ("S3", 1.0, 1.0, 0.2),
        ],
    )
    yield c
    c.close()
