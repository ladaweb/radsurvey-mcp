"""Pure query functions.

All business logic lives here, separate from MCP, so it can be unit tested
without a server and reused from any other interface (CLI, REST, notebook).
Every query uses bound parameters — the model never supplies raw SQL.
"""

from __future__ import annotations

import sqlite3

from .models import (
    Area,
    Hotspot,
    HotspotReport,
    Reading,
    ReadingQueryResult,
    StayTimeEstimate,
    SurveySummary,
)

MAX_RESULTS = 50  # Hard cap so a tool call can't flood the model's context.


class NotFoundError(ValueError):
    """Raised when an ID doesn't exist. The message is shown to the model."""


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_RESULTS))


def list_areas(conn: sqlite3.Connection) -> list[Area]:
    rows = conn.execute("SELECT * FROM areas ORDER BY area_id").fetchall()
    return [Area(**dict(r)) for r in rows]


def _require_area(conn: sqlite3.Connection, area_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM areas WHERE area_id = ?", (area_id,)).fetchone()
    if row is None:
        valid = ", ".join(a.area_id for a in list_areas(conn))
        raise NotFoundError(f"Unknown area_id '{area_id}'. Valid area_ids: {valid}")
    return row


_SUMMARY_SQL = """
SELECT s.survey_id, s.area_id, a.name AS area_name, s.date, s.method, s.instrument,
       COUNT(r.reading_id) AS reading_count,
       ROUND(MAX(r.dose_rate_usv_h), 3) AS max_dose_rate_usv_h,
       ROUND(AVG(r.dose_rate_usv_h), 3) AS mean_dose_rate_usv_h
FROM surveys s
JOIN areas a ON a.area_id = s.area_id
LEFT JOIN readings r ON r.survey_id = s.survey_id
"""


def list_surveys(
    conn: sqlite3.Connection,
    area_id: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[SurveySummary]:
    clauses, params = [], []
    if area_id:
        _require_area(conn, area_id)
        clauses.append("s.area_id = ?")
        params.append(area_id)
    if since:
        clauses.append("s.date >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"{_SUMMARY_SQL} {where} GROUP BY s.survey_id ORDER BY s.date DESC, s.survey_id LIMIT ?"
    params.append(_clamp_limit(limit))
    return [SurveySummary(**dict(r)) for r in conn.execute(sql, params).fetchall()]


def get_survey(conn: sqlite3.Connection, survey_id: str) -> SurveySummary:
    row = conn.execute(
        f"{_SUMMARY_SQL} WHERE s.survey_id = ? GROUP BY s.survey_id", (survey_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"Unknown survey_id '{survey_id}'. Use list_surveys to find valid IDs."
        )
    return SurveySummary(**dict(row))


def _latest_survey_id(conn: sqlite3.Connection, area_id: str) -> str:
    row = conn.execute(
        "SELECT survey_id FROM surveys WHERE area_id = ? ORDER BY date DESC, survey_id DESC LIMIT 1",
        (area_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"No surveys recorded for area '{area_id}'.")
    return row["survey_id"]


def find_readings_above(
    conn: sqlite3.Connection,
    threshold_usv_h: float,
    survey_id: str | None = None,
    area_id: str | None = None,
    limit: int = 20,
) -> ReadingQueryResult:
    if threshold_usv_h < 0:
        raise ValueError("threshold_usv_h must be >= 0.")
    clauses, params = ["r.dose_rate_usv_h >= ?"], [threshold_usv_h]
    if survey_id:
        get_survey(conn, survey_id)
        clauses.append("r.survey_id = ?")
        params.append(survey_id)
    if area_id:
        _require_area(conn, area_id)
        clauses.append("s.area_id = ?")
        params.append(area_id)
    where = " AND ".join(clauses)
    base = f"FROM readings r JOIN surveys s ON s.survey_id = r.survey_id WHERE {where}"

    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    capped = _clamp_limit(limit)
    rows = conn.execute(
        f"SELECT r.reading_id, r.survey_id, s.area_id, r.x_m, r.y_m, r.dose_rate_usv_h {base} "
        "ORDER BY r.dose_rate_usv_h DESC LIMIT ?",
        [*params, capped],
    ).fetchall()
    readings = [Reading(**dict(r)) for r in rows]
    return ReadingQueryResult(
        threshold_usv_h=threshold_usv_h,
        total_matches=total,
        returned=len(readings),
        truncated=total > len(readings),
        readings=readings,
    )


def area_hotspots(
    conn: sqlite3.Connection,
    area_id: str,
    top_n: int = 5,
    survey_id: str | None = None,
    min_separation_m: float = 1.0,
) -> HotspotReport:
    """Top-N hottest points, skipping points within min_separation_m of a higher one.

    Without the separation rule the "top 5" is often five neighbouring grid
    points around the same source, which is not useful to an inspector.
    """
    area = _require_area(conn, area_id)
    sid = survey_id or _latest_survey_id(conn, area_id)
    survey = get_survey(conn, sid)
    if survey.area_id != area_id:
        raise NotFoundError(f"Survey '{sid}' belongs to area '{survey.area_id}', not '{area_id}'.")

    rows = conn.execute(
        "SELECT x_m, y_m, dose_rate_usv_h FROM readings WHERE survey_id = ? "
        "ORDER BY dose_rate_usv_h DESC",
        (sid,),
    ).fetchall()

    wanted = _clamp_limit(top_n)
    picked: list[sqlite3.Row] = []
    sep2 = min_separation_m**2
    for r in rows:
        if all((r["x_m"] - p["x_m"]) ** 2 + (r["y_m"] - p["y_m"]) ** 2 >= sep2 for p in picked):
            picked.append(r)
            if len(picked) == wanted:
                break

    return HotspotReport(
        area_id=area_id,
        area_name=area["name"],
        survey_id=sid,
        date=survey.date,
        hotspots=[
            Hotspot(
                rank=i + 1,
                x_m=p["x_m"],
                y_m=p["y_m"],
                dose_rate_usv_h=p["dose_rate_usv_h"],
                survey_id=sid,
                date=survey.date,
            )
            for i, p in enumerate(picked)
        ],
    )


def estimate_stay_time(
    conn: sqlite3.Connection,
    area_id: str,
    planned_hours: float,
    dose_budget_usv: float,
    basis: str = "max",
) -> StayTimeEstimate:
    """Planning estimate: dose = dose_rate x time, using the latest survey."""
    if planned_hours <= 0:
        raise ValueError("planned_hours must be > 0.")
    if dose_budget_usv <= 0:
        raise ValueError("dose_budget_usv must be > 0.")
    if basis not in ("max", "mean"):
        raise ValueError("basis must be 'max' or 'mean'.")

    _require_area(conn, area_id)
    survey = get_survey(conn, _latest_survey_id(conn, area_id))
    rate = survey.max_dose_rate_usv_h if basis == "max" else survey.mean_dose_rate_usv_h
    dose = round(rate * planned_hours, 3)
    hours_left = round(dose_budget_usv / rate, 2) if rate > 0 else None

    return StayTimeEstimate(
        area_id=area_id,
        survey_id=survey.survey_id,
        basis=basis,
        dose_rate_usv_h=rate,
        planned_hours=planned_hours,
        estimated_dose_usv=dose,
        dose_budget_usv=dose_budget_usv,
        hours_until_budget=hours_left,
        within_budget=dose <= dose_budget_usv,
        note=(
            "Planning estimate only, from the most recent survey. Not a substitute for "
            "a qualified radiation protection review or real-time dosimetry."
        ),
    )
