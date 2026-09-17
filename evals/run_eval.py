"""Evaluate an LLM using this MCP server on a fixed question set.

The script bridges MCP tools to the Claude API tool-use format, runs each
question through an agent loop, and scores:
  * tool selection  - did the model call the expected tool(s)?
  * grounding       - does the answer mention the expected facts?
  * errors / turns / latency

It connects to the server locally over stdio, so no public URL is needed.

    pip install -e ".[llm]"
    export ANTHROPIC_API_KEY=...
    python evals/run_eval.py --model claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from anthropic import Anthropic
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 6


def mcp_tools_to_anthropic(tools) -> list[dict]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in tools
    ]


def result_text(result) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content)
    return "\n".join(getattr(c, "text", "") for c in result.content)


async def run_question(llm: Anthropic, model: str, client: Client, tools, system: str, q: dict):
    messages = [{"role": "user", "content": q["question"]}]
    called, errors, turns = [], 0, 0
    start = time.perf_counter()
    answer = ""

    while turns < MAX_TURNS:
        turns += 1
        resp = llm.messages.create(
            model=model, max_tokens=1024, system=system, tools=tools, messages=messages
        )
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            answer = "".join(b.text for b in resp.content if b.type == "text")
            break
        results = []
        for u in uses:
            called.append(u.name)
            r = await client.call_tool(u.name, u.input)
            errors += int(bool(r.is_error))
            results.append({
                "type": "tool_result", "tool_use_id": u.id,
                "content": result_text(r), "is_error": bool(r.is_error),
            })
        messages.append({"role": "user", "content": results})

    expected = set(q["expected_tools"])
    tool_ok = expected <= set(called) if expected else True
    grounded = any(s.lower() in answer.lower() for s in q["must_mention_any"])
    return {
        "id": q["id"], "tools_called": called, "tool_selection_ok": tool_ok,
        "grounded": grounded, "tool_errors": errors, "turns": turns,
        "latency_s": round(time.perf_counter() - start, 2), "answer": answer,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--out", default=str(ROOT / "evals" / "results.json"))
    args = ap.parse_args()

    questions = json.loads((ROOT / "evals" / "questions.json").read_text())
    llm = Anthropic()
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "radsurvey_mcp.server"],
        env={"PYTHONPATH": str(ROOT / "src")}, cwd=str(ROOT),
    )
    async with Client(params) as client:
        tools = mcp_tools_to_anthropic((await client.list_tools()).tools)
        system = client.instructions or ""
        rows = [await run_question(llm, args.model, client, tools, system, q) for q in questions]

    n = len(rows)
    summary = {
        "model": args.model,
        "questions": n,
        "tool_selection_accuracy": round(sum(r["tool_selection_ok"] for r in rows) / n, 2),
        "grounded_rate": round(sum(r["grounded"] for r in rows) / n, 2),
        "mean_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
        "total_tool_errors": sum(r["tool_errors"] for r in rows),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "results": rows}, indent=2))

    for r in rows:
        mark = "PASS" if r["tool_selection_ok"] and r["grounded"] else "FAIL"
        print(f"[{mark}] {r['id']:<14} tools={r['tools_called']} turns={r['turns']} "
              f"{r['latency_s']}s")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
