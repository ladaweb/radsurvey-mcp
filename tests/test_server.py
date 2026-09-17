"""End-to-end tests through a real MCP client connected in-process."""

import json
import sqlite3

import pytest
from mcp import Client

from radsurvey_mcp import db, server

EXPECTED_TOOLS = {
    "list_areas", "list_surveys", "get_survey",
    "find_readings_above", "area_hotspots", "estimate_stay_time",
}


@pytest.fixture(scope="module", autouse=True)
def sample_db():
    db.build_database()  # ensure bundled sample DB exists
    server._conn.cache_clear()
    yield


def _payload(result):
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(result.content[0].text)


async def test_tools_registered_and_read_only():
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == EXPECTED_TOOLS
        for t in tools:
            assert t.annotations and t.annotations.read_only_hint is True
            assert t.description


async def test_list_areas_via_mcp():
    async with Client(server.mcp) as client:
        res = await client.call_tool("list_areas", {})
        assert not res.is_error
        ids = {a["area_id"] for a in _payload(res)}
        assert {"RXH-01", "HCC-01", "WST-01"} <= ids


async def test_hotspots_via_mcp():
    async with Client(server.mcp) as client:
        res = await client.call_tool("area_hotspots", {"area_id": "HCC-01", "top_n": 2})
        data = _payload(res)
        assert len(data["hotspots"]) == 2
        top = data["hotspots"][0]
        # Strongest source in the hot cell corridor is placed at (5.0, 2.0)
        assert abs(top["x_m"] - 5.0) <= 1.0 and abs(top["y_m"] - 2.0) <= 1.0


async def test_bad_input_returns_tool_error_not_crash():
    async with Client(server.mcp) as client:
        res = await client.call_tool("get_survey", {"survey_id": "does-not-exist"})
        assert res.is_error
        assert "list_surveys" in res.content[0].text  # helpful message reaches the model


async def test_schema_validation_rejects_out_of_range():
    async with Client(server.mcp) as client:
        res = await client.call_tool("find_readings_above", {"threshold_usv_h": -5})
        assert res.is_error


def test_server_connection_is_read_only():
    conn = db.connect_readonly()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM readings")
