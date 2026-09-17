"""MCP server exposing radiation survey data as read-only tools.

Run over stdio (what Copilot in VS Code, Copilot CLI and Claude Desktop use):
    radsurvey-mcp
Or over HTTP (for the Claude API MCP connector or a remote deployment):
    radsurvey-mcp --http --port 8000
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import queries
from .db import connect_readonly
from .models import (
    Area,
    HotspotReport,
    ReadingQueryResult,
    StayTimeEstimate,
    SurveySummary,
)

INSTRUCTIONS = """\
Tools for querying radiation survey data collected by autonomous robots and
manual surveys. All dose rates are gamma dose rates in microsieverts per hour
(uSv/h). Start with list_areas if you don't know the area IDs. Data is
read-only. Stay-time estimates are for planning only; always say so.
"""

mcp = MCPServer(name="radsurvey", instructions=INSTRUCTIONS, version="0.1.0")

# Every tool is read-only and has no side effects; telling the client lets it
# skip confirmation prompts that write tools would need.
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


@lru_cache(maxsize=1)
def _conn():
    return connect_readonly()


def user_errors(fn: Callable) -> Callable:
    """Turn expected input errors into clean tool errors the model can act on.

    Without this, a bad ID is logged as a server crash and the model gets a
    generic failure instead of "Unknown area_id ... Valid area_ids: ...".
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:  # includes queries.NotFoundError
            raise ToolError(str(exc)) from exc

    return wrapper


@mcp.tool(annotations=READ_ONLY)
@user_errors
def list_areas() -> list[Area]:
    """List every surveyed area with its ID, facility, and posted classification."""
    return queries.list_areas(_conn())


@mcp.tool(annotations=READ_ONLY)
@user_errors
def list_surveys(
    area_id: Annotated[str | None, Field(description="Filter to one area, e.g. 'HCC-01'.")] = None,
    since: Annotated[
        str | None, Field(description="Only surveys on/after this ISO date (YYYY-MM-DD).")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Max surveys to return.")] = 20,
) -> list[SurveySummary]:
    """List surveys, newest first, with reading counts and max/mean dose rates."""
    return queries.list_surveys(_conn(), area_id=area_id, since=since, limit=limit)


@mcp.tool(annotations=READ_ONLY)
@user_errors
def get_survey(
    survey_id: Annotated[str, Field(description="Survey ID, e.g. 'SRV-2026-0012'.")],
) -> SurveySummary:
    """Get the summary for one survey."""
    return queries.get_survey(_conn(), survey_id)


@mcp.tool(annotations=READ_ONLY)
@user_errors
def find_readings_above(
    threshold_usv_h: Annotated[
        float, Field(ge=0, description="Return readings at or above this dose rate (uSv/h).")
    ],
    survey_id: Annotated[str | None, Field(description="Restrict to one survey.")] = None,
    area_id: Annotated[str | None, Field(description="Restrict to one area.")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Max readings to return.")] = 20,
) -> ReadingQueryResult:
    """Find individual readings at or above a dose-rate threshold, hottest first.

    Check `truncated` in the result: if true, more matches exist than were returned.
    """
    return queries.find_readings_above(
        _conn(), threshold_usv_h, survey_id=survey_id, area_id=area_id, limit=limit
    )


@mcp.tool(annotations=READ_ONLY)
@user_errors
def area_hotspots(
    area_id: Annotated[str, Field(description="Area ID, e.g. 'RXH-01'.")],
    top_n: Annotated[int, Field(ge=1, le=20, description="Number of hotspots.")] = 5,
    survey_id: Annotated[
        str | None, Field(description="Specific survey; defaults to the area's latest.")
    ] = None,
) -> HotspotReport:
    """Top distinct hotspots in an area (nearby duplicate points are merged)."""
    return queries.area_hotspots(_conn(), area_id, top_n=top_n, survey_id=survey_id)


@mcp.tool(annotations=READ_ONLY)
@user_errors
def estimate_stay_time(
    area_id: Annotated[str, Field(description="Area ID.")],
    planned_hours: Annotated[float, Field(gt=0, le=24, description="Planned time in area.")],
    dose_budget_usv: Annotated[
        float, Field(gt=0, description="Dose budget for the task in uSv.")
    ],
    basis: Annotated[
        Literal["max", "mean"],
        Field(description="'max' is conservative (default); 'mean' is typical exposure."),
    ] = "max",
) -> StayTimeEstimate:
    """Estimate dose for planned work in an area and how long until a dose budget is hit.

    Planning estimate only; always tell the user it is not a radiation protection review.
    """
    return queries.estimate_stay_time(
        _conn(), area_id, planned_hours, dose_budget_usv, basis=basis
    )


@mcp.prompt()
def inspection_briefing(area_id: str) -> str:
    """Pre-job briefing for an inspection in one area."""
    return (
        f"Prepare a short pre-job radiation briefing for area {area_id}. "
        "Use list_surveys to find the latest survey, area_hotspots for the top 3 hotspots, "
        "and estimate_stay_time for a 2-hour job with a 200 uSv budget. "
        "Present: area posting, survey date and method, hotspots with coordinates, "
        "estimated dose, and a reminder that this is a planning estimate."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="radsurvey MCP server")
    parser.add_argument("--http", action="store_true", help="Serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
