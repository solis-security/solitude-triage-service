# Solitude AI Analysis MCP Server

An MCP server implementing the **AI-Assisted Analysis Engine** from the
Solitude Reloaded TDD (Section 4.4), backed by a **local Ollama model**
rather than a hosted API — so investigation content never leaves the
machine to get an AI-assisted read on it.

TypeScript, matching the convention used by the other Solis MCP servers.

## Design: grounding is enforced, and a failed conclusion is withheld

Every analysis tool follows the same shape:

1. The model is given a finding (or case, or email) **plus the specific
   evidence records that exist for it**, and instructed to cite only those ids.
2. The response is parsed with `safeParse` — model output is untrusted input,
   so an unexpected value degrades to `engine_error` rather than throwing out
   of the tool call.
3. The result is checked in code, not trusted:
   - Firm conclusion citing nothing → **rejected** (`rejected_no_evidence`)
   - An id that was never supplied → **rejected** (`rejected_ungrounded`)
   - Honest "the evidence doesn't support this" → **accepted** (`grounded`,
     `insufficient_evidence: true`)
4. **A rejected conclusion is withheld, not annotated.** The narrative and
   confidence are replaced before returning; the original text goes to the
   audit log only. Clearing `evidence_refs` while still returning the model's
   prose meant a hallucination reached anything that rendered `narrative`
   without also checking `validation`.
5. Every call is appended to an audit log recording the model, digest, the ids
   the model was **offered**, the ids it **cited**, and the verdict — enough to
   re-check any decision after the fact.
6. `get_ai_engine_health` reads that log for a rejection-rate circuit breaker.
   While it is tripped, AI findings must not be auto-included in reports.

`src/validation.ts` holds this logic with no Ollama, MCP or filesystem
dependency, and is unit tested in isolation.

### Content analysis is validated too

`analyze_email_content` was previously exempt from all of the above. It now has
a grounding notion of its own, checkable without a second model: flags must come
from the controlled vocabulary, and the claimed method must match the input the
model was actually given. A model reporting `content_analysis` when no body was
supplied is describing an analysis it could not have performed.

## Tools

| Tool | Purpose |
|---|---|
| `analyze_finding` | Evidence-grounded analysis of one investigation finding |
| `summarize_case` | Evidence-grounded executive summary across a case |
| `analyze_email_content` | Data-exposure assessment of a message; falls back to subject-line-only, explicitly flagged |
| `get_ai_engine_health` | Ollama reachability, local models, circuit-breaker status |

## Setup

Requires [Ollama](https://ollama.com) with a model pulled:

```bash
ollama pull llama3.1
ollama serve
```

```bash
npm install
npm run build
```

### Connect it to Claude Desktop or Claude Code

```json
{
  "mcpServers": {
    "solitude-ai-analysis": {
      "command": "node",
      "args": ["/path/to/solitude-triage-service/ai-analysis-mcp/dist/server.js"],
      "env": { "AI_OLLAMA_MODEL": "llama3.1" }
    }
  }
}
```

## Tests

```bash
npm test    # builds, then runs the suite
```

The suite is runnable with no Ollama installed. `test/mockOllama.ts` emulates
`/api/chat` and `/api/tags` closely enough to exercise the real request path.
Covered: happy path, hallucinated id, no-evidence-cited, honest insufficiency,
malformed output, out-of-vocabulary enum values, unreachable Ollama, withheld
narrative, audit contents, and the content-analysis grounding rules.

### Checking against a real model

The suite runs entirely against the mock, so it cannot tell you how a real
model behaves. `scripts/live-check.ts` exercises all four tools against a live
Ollama:

```bash
npx tsc scripts/live-check.ts --outDir dist-scripts --target ES2023 \
  --module NodeNext --moduleResolution NodeNext --skipLibCheck
node dist-scripts/live-check.js
```

Two things this caught that the mock could not, both now fixed:

- **The model cites finding ids.** `summarize_case` is handed whole findings, so
  `llama3.1` cited `F-1006` alongside the correct evidence ids — and a strict
  evidence-id subset rule rejected an otherwise correct summary. Finding ids are
  now citable; invented ids are still rejected.
- **The model ignored a supplied body**, claiming `subject_line_fallback` when a
  body was present. The content grounding rule caught it; the prompt now states
  the requirement explicitly.

Verified against `llama3.1` (digest `46e0c10c039e`): all four tools grounded,
breaker clean.

## Known limitations

- The audit log is a JSONL file, fine for a single analyst's machine, not for
  concurrent or shared use.
- The sensitivity vocabulary is fixed in `src/validation.ts` and mirrored into
  the prompt; extend both together.
- Nothing wires the triage service to this server yet — findings are passed as
  tool arguments, and `EvidenceItem` needs `{id, source, summary}` while
  findings carry only raw Elasticsearch document ids.
- No content leaves the machine except to your local Ollama instance.
