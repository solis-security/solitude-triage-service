# ADR 0003 — The analysis engine is a library with two adapters, not an MCP server

- Status: Proposed
- Date: 2026-09-02
- Related: TDD §3.1, §4.4, §4.8; FR-03, FR-06, FR-09

## Context

`ai-analysis-mcp/` is an MCP server over stdio. Its only entry point is
`server.ts`, and an operator drives it by hand from an MCP client.

The TDD never mentions MCP. §3.1 places the AI-Assisted Analysis Engine as a
service inside the pipeline:

    Rule Engine + Findings Store → AI-Assisted Analysis Engine → AI Findings

called by the Orchestration API, with output landing in a review queue (§4.4) that
the Reporting Engine blocks on (§4.8). An Orchestration API cannot call a stdio
MCP server without spawning subprocesses and speaking a protocol designed for
interactive model clients. As built, the engine cannot occupy the position the
architecture requires of it.

This is the decision that was parked pending the design doc. The doc answers it.

The good news is that the code is already shaped correctly. `analysis.ts`,
`validation.ts`, `prompts.ts`, `audit.ts` and `schemas.ts` are pure and
transport-agnostic; `server.ts` is a 93-line adapter that only unpacks arguments
and JSON-encodes results.

## Decision

Treat the analysis capability as a **library** with two thin adapters over the
same core:

1. **HTTP service adapter** — what the Orchestration API calls in the pipeline.
   This is the primary path and the one the TDD's architecture requires.
2. **MCP adapter** — retained, unchanged in spirit, for analyst and operator use.

Neither adapter contains logic. Grounding validation, the circuit breaker and the
audit trail live in the core, so both doors enforce identical rules. An analysis
that would be rejected over HTTP is rejected over MCP.

## Consequences

- The engine becomes callable from the pipeline without abandoning the MCP
  ergonomics that make it useful to an analyst directly.
- `ai-analysis-mcp/` is now misnamed — MCP is one of two adapters, not the
  identity of the component. Rename to `ai-analysis/` with `src/adapters/mcp` and
  `src/adapters/http`.
- The core must stay free of transport concerns. The current split already
  respects this; the risk is future logic drifting into `server.ts` for
  convenience, so a test should assert the adapters remain thin.
- Confirms the repo-local placement decision: the engine is catered to this
  application and ships with it, rather than living in a standalone MCP repo.

## Rejected alternatives

**Keep MCP as the only interface.** Leaves the pipeline unable to call the engine,
and forces the Orchestration API into subprocess management for what should be a
request.

**Rewrite the engine in Python to match the service.** Would discard the grounding
and validation work, which is the direct mitigation for the TDD's highest-rated
risk (§12, AI hallucination, High). The seam between "data processing over
Elasticsearch" and "LLM orchestration" is a real one; see ADR 0007 for how the
contract across it is kept honest.
