"""Generate a synthetic radiation survey dataset.

Everything here is fictional: a made-up facility, made-up areas, simulated
readings. Each area has a background level plus a few Gaussian point sources.
Robot surveys sample a dense grid; manual surveys sample fewer points with
more noise. Deterministic (seeded) so tests are stable.

    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radsurvey_mcp.db import DEFAULT_DB, DEFAULT_JSON, build_database

SEED = 42
FACILITY = "Demo Research Reactor (fictional)"

# (area_id, name, posting, width_m, height_m, background uSv/h, sources[(x, y, peak, sigma)])
AREAS = [
    ("CTL-01", "Control Room", "Unrestricted", 10, 8, 0.12, []),
    ("RXH-01", "Reactor Hall", "Radiation Area", 20, 15, 0.8,
     [(6.0, 4.0, 45.0, 1.2), (14.5, 10.0, 18.0, 1.8)]),
    ("HCC-01", "Hot Cell Corridor", "High Radiation Area", 24, 4, 1.5,
     [(5.0, 2.0, 180.0, 0.9), (18.0, 1.5, 95.0, 1.1)]),
    ("WST-01", "Waste Storage", "Radiation Area", 12, 12, 2.0,
     [(3.0, 9.0, 60.0, 1.5), (9.0, 3.0, 35.0, 1.0), (9.5, 9.5, 22.0, 2.0)]),
    ("PMP-01", "Pump Room", "Controlled Area", 8, 10, 0.4, [(4.0, 7.0, 6.5, 1.0)]),
]


def dose_at(x, y, bg, sources, rng, noise):
    val = bg + sum(p * math.exp(-((x - sx) ** 2 + (y - sy) ** 2) / (2 * s**2))
                   for sx, sy, p, s in sources)
    return round(max(0.0, val * rng.gauss(1.0, noise)), 3)


def main() -> None:
    rng = random.Random(SEED)
    areas_out, surveys_out = [], []
    start = date(2026, 6, 1)
    counter = 1

    for area_id, name, posting, w, h, bg, sources in AREAS:
        areas_out.append({"area_id": area_id, "name": name, "facility": FACILITY,
                          "posted_classification": posting})
        for week in range(0, 14, 2):  # a survey every two weeks
            method = "robot" if week % 4 == 0 else "manual"
            step = 0.5 if method == "robot" else 2.0
            noise = 0.05 if method == "robot" else 0.12
            # sources slowly decay, so trends exist in the data
            decay = 0.985 ** week
            decayed = [(sx, sy, p * decay, s) for sx, sy, p, s in sources]
            readings = []
            y = 0.0
            while y <= h:
                x = 0.0
                while x <= w:
                    readings.append({"x_m": x, "y_m": y,
                                     "dose_rate_usv_h": dose_at(x, y, bg, decayed, rng, noise)})
                    x += step
                y += step
            surveys_out.append({
                "survey_id": f"SRV-2026-{counter:04d}",
                "area_id": area_id,
                "date": (start + timedelta(weeks=week, days=AREAS.index(
                    (area_id, name, posting, w, h, bg, sources)))).isoformat(),
                "method": method,
                "instrument": "CZT spectrometer (robot-mounted)" if method == "robot"
                else "Handheld ion chamber",
                "readings": readings,
            })
            counter += 1

    DEFAULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_JSON.write_text(json.dumps({"areas": areas_out, "surveys": surveys_out}))
    build_database(DEFAULT_JSON, DEFAULT_DB)
    n = sum(len(s["readings"]) for s in surveys_out)
    print(f"Wrote {len(areas_out)} areas, {len(surveys_out)} surveys, {n} readings")
    print(f"  JSON: {DEFAULT_JSON}\n  DB:   {DEFAULT_DB}")


if __name__ == "__main__":
    main()
