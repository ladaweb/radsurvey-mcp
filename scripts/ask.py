"""Ask Claude questions about the radiation survey data, interactively.

Claude gets the MCP server's tools, decides which to call, and answers
from the data. Uses the Anthropic Python SDK and the MCP Python SDK.

    set ANTHROPIC_API_KEY=your-key        (Command Prompt)
    python scripts/ask.py
    python scripts/ask.py --model claude-sonnet-5 --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from anthropic import Anthropic
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 8


def to_anthropic_tools(tools) -> list[dict]:
    """Convert MCP tool definitions into the Claude API tool format."""
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in tools
    ]


def result_text(result) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content)
    return "\n".join(getattr(c, "text", "") for c in result.content)


async def answer(llm, model, client, tools, system, messages, verbose) -> str:
    """Agent loop: let Claude call tools until it gives a final text answer."""
    for _ in range(MAX_TURNS):
        resp = llm.messages.create(
            model=model, max_tokens=1024, system=system, tools=tools, messages=messages
        )
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            return "".join(b.text for b in resp.content if b.type == "text")

        results = []
        for u in uses:
            if verbose:
                print(f"  -> calling {u.name}({json.dumps(u.input)})")
            r = await client.call_tool(u.name, u.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": u.id,
                "content": result_text(r),
                "is_error": bool(r.is_error),
            })
        messages.append({"role": "user", "content": results})
    return "(Stopped: too many tool calls.)"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--verbose", action="store_true", help="Show which tools Claude calls")
    args = ap.parse_args()

    llm = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "radsurvey_mcp.server"],
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=str(ROOT),
    )

    async with Client(params) as client:
        tools = to_anthropic_tools((await client.list_tools()).tools)
        system = client.instructions or ""
        messages: list[dict] = []  # keeps the conversation, so follow-ups work

        print("Ask about the survey data. Type 'exit' to quit, 'new' to start over.\n")
        while True:
            q = input("You: ").strip()
            if q.lower() in {"exit", "quit"}:
                break
            if q.lower() == "new":
                messages = []
                print("(new conversation)\n")
                continue
            if not q:
                continue
            messages.append({"role": "user", "content": q})
            text = await answer(llm, args.model, client, tools, system, messages, args.verbose)
            print(f"\nClaude: {text}\n")


if __name__ == "__main__":
    asyncio.run(main())
