import pytest

from radsurvey_mcp import queries
from radsurvey_mcp.queries import MAX_RESULTS, NotFoundError


def test_list_areas(conn):
    assert [a.area_id for a in queries.list_areas(conn)] == ["A1", "B1"]


def test_list_surveys_newest_first_and_filters(conn):
    assert [s.survey_id for s in queries.list_surveys(conn)] == ["S3", "S2", "S1"]
    assert [s.survey_id for s in queries.list_surveys(conn, area_id="A1")] == ["S2", "S1"]
    assert [s.survey_id for s in queries.list_surveys(conn, since="2026-08-01")] == ["S3", "S2"]


def test_unknown_area_lists_valid_ids(conn):
    with pytest.raises(NotFoundError, match="Valid area_ids: A1, B1"):
        queries.list_surveys(conn, area_id="ZZ")


def test_get_survey_stats(conn):
    s = queries.get_survey(conn, "S2")
    assert s.reading_count == 4
    assert s.max_dose_rate_usv_h == 100.0
    assert s.mean_dose_rate_usv_h == 58.0


def test_get_survey_unknown(conn):
    with pytest.raises(NotFoundError):
        queries.get_survey(conn, "nope")


def test_find_readings_above_sorted_and_counted(conn):
    r = queries.find_readings_above(conn, 45.0)
    assert r.total_matches == 3
    assert [x.dose_rate_usv_h for x in r.readings] == [100.0, 90.0, 50.0]
    assert r.truncated is False


def test_find_readings_above_truncates(conn):
    r = queries.find_readings_above(conn, 0.0, limit=2)
    assert r.returned == 2 and r.total_matches == 8 and r.truncated


def test_limit_is_clamped(conn):
    r = queries.find_readings_above(conn, 0.0, limit=10_000)
    assert r.returned <= MAX_RESULTS


def test_negative_threshold_rejected(conn):
    with pytest.raises(ValueError):
        queries.find_readings_above(conn, -1)


def test_hotspots_merge_neighbours_and_default_to_latest(conn):
    rep = queries.area_hotspots(conn, "A1", top_n=3)
    assert rep.survey_id == "S2"  # latest survey for A1
    # 90.0 at (5.5, 5) is 0.5 m from the 100.0 peak, so it is merged away
    assert [h.dose_rate_usv_h for h in rep.hotspots] == [100.0, 40.0, 2.0]
    assert [h.rank for h in rep.hotspots] == [1, 2, 3]


def test_hotspots_rejects_survey_from_other_area(conn):
    with pytest.raises(NotFoundError, match="belongs to area"):
        queries.area_hotspots(conn, "A1", survey_id="S3")


def test_stay_time_max_basis(conn):
    est = queries.estimate_stay_time(conn, "A1", planned_hours=2, dose_budget_usv=150)
    assert est.dose_rate_usv_h == 100.0
    assert est.estimated_dose_usv == 200.0
    assert est.hours_until_budget == 1.5
    assert est.within_budget is False
    assert "Planning estimate" in est.note


def test_stay_time_mean_basis(conn):
    est = queries.estimate_stay_time(conn, "A1", 1, 100, basis="mean")
    assert est.dose_rate_usv_h == 58.0 and est.within_budget


@pytest.mark.parametrize("hours,budget,basis", [(0, 10, "max"), (1, 0, "max"), (1, 10, "p95")])
def test_stay_time_validation(conn, hours, budget, basis):
    with pytest.raises(ValueError):
        queries.estimate_stay_time(conn, "A1", hours, budget, basis=basis)


def test_sql_injection_is_inert(conn):
    with pytest.raises(NotFoundError):
        queries.get_survey(conn, "S1' OR '1'='1")
