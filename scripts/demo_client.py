"""Launch the server as a subprocess over stdio and call each tool.

This is exactly what Copilot or Claude Desktop does under the hood, minus the
LLM. Useful for a live demo and for checking the server starts cleanly.

    python scripts/demo_client.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def show(title: str, result) -> None:
    print(f"\n=== {title} ===")
    if result.is_error:
        print("ERROR:", result.content[0].text)
        return
    data = result.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    text = json.dumps(data, indent=2)
    print(text if len(text) < 1500 else text[:1500] + "\n  ...")


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "radsurvey_mcp.server"],
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=str(ROOT),
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        print("Tools:", ", ".join(t.name for t in tools.tools))

        show("list_areas", await client.call_tool("list_areas", {}))
        show("list_surveys (HCC-01)",
             await client.call_tool("list_surveys", {"area_id": "HCC-01", "limit": 3}))
        show("area_hotspots (HCC-01)",
             await client.call_tool("area_hotspots", {"area_id": "HCC-01", "top_n": 3}))
        show("find_readings_above 100 uSv/h",
             await client.call_tool("find_readings_above", {"threshold_usv_h": 100, "limit": 5}))
        show("estimate_stay_time (RXH-01, 2 h, 100 uSv)",
             await client.call_tool("estimate_stay_time",
                                    {"area_id": "RXH-01", "planned_hours": 2,
                                     "dose_budget_usv": 100}))
        show("bad input is handled",
             await client.call_tool("get_survey", {"survey_id": "SRV-9999"}))


if __name__ == "__main__":
    asyncio.run(main())
