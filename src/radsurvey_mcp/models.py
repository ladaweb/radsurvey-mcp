"""Pydantic models returned by the tools.

Returning typed models (instead of raw dicts) gives the MCP client a JSON
schema for every result, which helps the model read the output correctly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Area(BaseModel):
    area_id: str
    name: str
    facility: str
    posted_classification: str = Field(
        description="Posting at the area entrance, e.g. 'Radiation Area' or 'Unrestricted'."
    )


class SurveySummary(BaseModel):
    survey_id: str
    area_id: str
    area_name: str
    date: str = Field(description="ISO date (YYYY-MM-DD).")
    method: str = Field(description="'robot' (autonomous quadruped) or 'manual'.")
    instrument: str
    reading_count: int
    max_dose_rate_usv_h: float
    mean_dose_rate_usv_h: float


class Reading(BaseModel):
    reading_id: int
    survey_id: str
    area_id: str
    x_m: float = Field(description="X position in the area's local frame, meters.")
    y_m: float = Field(description="Y position in the area's local frame, meters.")
    dose_rate_usv_h: float = Field(description="Gamma dose rate in microsieverts per hour.")


class ReadingQueryResult(BaseModel):
    threshold_usv_h: float
    total_matches: int
    returned: int
    truncated: bool = Field(description="True if more matches exist than were returned.")
    readings: list[Reading]


class Hotspot(BaseModel):
    rank: int
    x_m: float
    y_m: float
    dose_rate_usv_h: float
    survey_id: str
    date: str


class HotspotReport(BaseModel):
    area_id: str
    area_name: str
    survey_id: str
    date: str
    hotspots: list[Hotspot]


class StayTimeEstimate(BaseModel):
    area_id: str
    survey_id: str
    basis: str = Field(description="Which dose rate the estimate uses: 'max' or 'mean'.")
    dose_rate_usv_h: float
    planned_hours: float
    estimated_dose_usv: float
    dose_budget_usv: float
    hours_until_budget: float | None = Field(
        description="Hours before the dose budget is reached; null if the dose rate is zero."
    )
    within_budget: bool
    note: str
