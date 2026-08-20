# Solitude AI Analysis MCP Server

An MCP (Model Context Protocol) server implementing the **AI-Assisted
Analysis Engine** from the Solitude Reloaded TDD (Section 4.4), backed by a
**local Ollama model** instead of a hosted API — so investigation content
never has to leave your machine/network to get an AI-assisted read on it.

## Design: evidence grounding is enforced, not requested

Every analysis tool follows the same shape:

1. The model is given a finding (or case, or email) **plus the specific
   evidence records** that exist for it, and instructed to cite only
   those evidence ids.
2. The response is parsed and checked in code — not just trusted:
   - No evidence cited but a firm conclusion drawn → **rejected** (`rejected_no_evidence`)
   - An evidence id cited that wasn't in the input → **rejected** (`rejected_ungrounded`, i.e. hallucination)
   - Model honestly says the evidence doesn't support a conclusion → **accepted** (`grounded`, `insufficient_evidence: true`)
3. Every call is appended to an audit log (model, digest, validation result,
   evidence refs) — this is what `get_ai_engine_health` reads to compute a
   rejection-rate circuit breaker, matching the TDD's requirement that
   auto-inclusion of AI findings in a report should stop if the AI engine
   starts misbehaving.

This validation logic lives in `app/validation.py`, has no Ollama or MCP
dependency, and is fully unit tested.

## Tools exposed

| Tool | Purpose |
|---|---|
| `analyze_finding` | Evidence-grounded analysis of a single investigation finding |
| `summarize_case` | Evidence-grounded executive summary across all findings in a case |
| `analyze_email_content` | Data-exposure/sensitivity analysis of an email; falls back to subject-line-only analysis (explicitly flagged) when no body is available |
| `get_ai_engine_health` | Ollama reachability, available models, and circuit-breaker status |

## Setup

Requires [Ollama](https://ollama.com) running locally with a model pulled:

```bash
ollama pull llama3.1
ollama serve   # if not already running as a service
```

```bash
pip install -r requirements.txt
cp .env.example .env   # adjust AI_OLLAMA_MODEL etc. if needed
```

Run standalone (stdio transport) to sanity-check it starts:

```bash
python -m app.server
```

### Connect it to Claude Desktop or Claude Code

Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "solitude-ai-analysis": {
      "command": "python",
      "args": ["-m", "app.server"],
      "cwd": "/path/to/solitude-ai-analysis-mcp",
      "env": { "AI_OLLAMA_MODEL": "llama3.1" }
    }
  }
}
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

20 tests, all runnable without a real Ollama installation:

- `tests/test_validation.py` — pure logic: grounding checks, circuit breaker math
- `tests/test_analysis_integration.py` — full pipeline (prompts → Ollama → parsing → validation → audit log), run against `tests/mock_ollama.py`, a ~100-line mock HTTP server that emulates Ollama's `/api/chat` and `/api/tags` endpoints closely enough for the real `ollama` Python client to talk to it. Scenarios covered: happy path, hallucinated evidence id, no-evidence-cited, honest "insufficient evidence", malformed model output, and Ollama being unreachable — each checked against the real request/response path, not just mocked-out function calls.

## Known limitations

- **Not verified against a real Ollama instance.** This was built and
  tested in a sandbox with no Ollama installed — the mock server captures
  Ollama's documented response shape, but subtle real-world differences
  (exact error formats, timeout behavior, model-specific JSON-mode quirks)
  haven't been exercised. Run the tools once against your real Ollama
  setup and report anything that doesn't match.
- `analyze_email_content`'s sensitivity vocabulary is a fixed list in the
  prompt (`app/prompts.py`) — extend it there if you need more categories.
- The audit log is a local JSONL file, not a database — fine for a single
  analyst's machine, not for concurrent/shared use.
- No content is sent anywhere except your local Ollama instance — there's
  no telemetry or external call in this server.
