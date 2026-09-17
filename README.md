# radsurvey-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that lets AI assistants answer questions about radiation survey data in plain language.

Instead of writing SQL or digging through survey spreadsheets, an inspector can ask GitHub Copilot or Claude:

> "Where is the hottest spot in the Hot Cell Corridor?"
> "I need 3 hours in the Reactor Hall with a 100 µSv budget. Am I OK?"

The assistant calls a small set of well-defined tools, and the server answers from the survey database.

> **Data note:** the bundled dataset is fully synthetic: a fictional facility with simulated point sources. Estimates are for planning only and are not a substitute for radiation protection review or real-time dosimetry.
>
> **Example input and output** 
<img width="562" height="197" alt="image" src="https://github.com/user-attachments/assets/9c8027a4-61da-4931-b9ac-c0d06e7c9712" />

## Why

Survey data from autonomous robots (for example, a quadruped doing a LiDAR-localized grid survey) is dense: hundreds of readings per area per survey. Most people who need answers from it are not going to write queries. MCP puts a safe, narrow interface between a language model and that data.

## Tools

| Tool | What it does |
|---|---|
| `list_areas` | All surveyed areas with posting classification |
| `list_surveys` | Surveys (newest first) with reading count and max/mean dose rate; filter by area and date |
| `get_survey` | Summary for one survey |
| `find_readings_above` | Individual readings above a dose-rate threshold, hottest first, with a `truncated` flag |
| `area_hotspots` | Top-N **distinct** hotspots (nearby points from the same source are merged) |
| `estimate_stay_time` | Estimated dose for planned work and hours until a dose budget is reached |

Plus one prompt, `inspection_briefing`, that chains the tools into a pre-job briefing.

## Design decisions

- **Read-only, enforced twice.** Tools are annotated `readOnlyHint`, and SQLite is opened with `mode=ro`, so writes fail at the database level even if code changes later.
- **No model-supplied SQL.** Every tool has a typed schema (Pydantic + `Field` constraints) and every query uses bound parameters.
- **Result caps.** Results are capped at 50 rows, and queries report `total_matches` and `truncated`, so the model knows when it is seeing a partial answer instead of flooding its context.
- **Errors the model can recover from.** Bad input returns a tool error with a next step, e.g. `Unknown area_id 'X'. Valid area_ids: CTL-01, HCC-01, ...`, rather than a crash.
- **Logic separate from protocol.** `queries.py` has no MCP imports, so it is unit tested directly and could back a CLI or REST API too.
- **Typed outputs.** Tools return Pydantic models, so clients receive a JSON schema for results as well as inputs.
- **Evaluated, not just tested.** `evals/` measures how well an LLM actually uses the tools (see below).

## Architecture

```
Copilot / Claude  ──MCP (stdio or HTTP)──►  server.py   (tool schemas, error mapping)
                                               │
                                           queries.py   (pure logic, bound params, caps)
                                               │
                                             db.py      (read-only SQLite)
                                               │
                                        data/surveys.db  ◄── generate_sample_data.py
```

```
radsurvey-mcp/
├── src/radsurvey_mcp/
│   ├── server.py        # MCP tools, prompt, stdio/HTTP entry point
│   ├── queries.py       # query logic
│   ├── models.py        # Pydantic result models
│   └── db.py            # schema, JSON loader, read-only connection
├── scripts/
│   ├── generate_sample_data.py
│   └── demo_client.py   # calls every tool over real stdio, no LLM needed
├── evals/
│   ├── questions.json   # question set with expected tools and facts
│   └── run_eval.py      # LLM agent loop + scoring
├── tests/               # unit tests + end-to-end tests through an MCP client
├── examples/            # Copilot CLI and Claude Desktop configs
├── .vscode/mcp.json     # Copilot in VS Code
└── .github/workflows/ci.yml
```

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/<you>/radsurvey-mcp.git
cd radsurvey-mcp
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python scripts/generate_sample_data.py   # builds data/surveys.db
pytest -q                                # 23 tests
python scripts/demo_client.py            # calls every tool over stdio
```

To point at your own database: `export RADSURVEY_DB=/path/to/surveys.db`.

## Use it with GitHub Copilot

**VS Code (Copilot Chat, agent mode):** open this folder. `.vscode/mcp.json` already registers the server. Open Copilot Chat, switch to **Agent** mode, and start the `radsurvey` server from the tools picker. Then ask a question.
(On Windows, change the command to `${workspaceFolder}\\.venv\\Scripts\\python.exe`.)

**Copilot CLI:** run `/mcp add` in the CLI, or copy `examples/copilot-cli-mcp-config.json` into your Copilot CLI MCP config and fix the absolute path.

## Use it with Claude

**Claude Desktop:** merge `examples/claude_desktop_config.json` into your `claude_desktop_config.json` and fix the path.

**Claude Code:**
```bash
claude mcp add radsurvey -- /ABSOLUTE/PATH/.venv/bin/python -m radsurvey_mcp.server
```

**Claude API:** `evals/run_eval.py` shows how to bridge MCP tools into the Messages API tool-use loop locally. For a hosted deployment, run the server over HTTP (`radsurvey-mcp --http --port 8000`) behind authentication.

## Evaluation

Unit tests check the code is correct. Evals check whether a **model** uses the tools correctly.

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
python evals/run_eval.py --model claude-sonnet-4-6
```

For each question in `evals/questions.json` it records:

- **Tool selection:** did the model call the expected tool?
- **Grounding:** does the answer contain the expected facts?
- **Tool errors, turns, latency**

It includes a negative case (an area that doesn't exist) to check that the model says "no data" instead of making something up. Results are written to `evals/results.json`. Rerun after changing a tool description to see whether it helped or hurt.

## What the sample data shows

Robot surveys sample a 0.5 m grid and manual surveys a 2 m grid. In the Hot Cell Corridor the latest robot survey records a peak around 157 µSv/h, while the manual survey two weeks earlier peaks around 83 µSv/h. The difference is mostly grid spacing missing the source, which is a useful argument for dense autonomous surveys.

## Testing

- `tests/test_queries.py`: exact-value tests against a small hand-built database (filters, ordering, truncation, limit clamping, hotspot merging, stay-time math, validation, injection attempts)
- `tests/test_server.py`: end-to-end through a real MCP client (tool registration, read-only annotations, schema validation, error messages, read-only DB)
- CI runs lint, tests, and the stdio smoke test on Python 3.10 and 3.12

## Roadmap

- Survey-to-survey trend tool (is an area getting hotter?)
- Import from robot survey logs (ROS bag → JSON)
- Map rendering of hotspots as an MCP resource
- Auth for the HTTP transport

## License

MIT
