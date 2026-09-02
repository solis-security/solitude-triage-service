# ADR 0007 — The Python/TypeScript contract is generated, not maintained by hand

- Status: Proposed
- Date: 2026-09-02
- Related: ADR 0003; TDD §4.4, §5

## Context

ADR 0003 keeps the analysis engine in TypeScript and the detection service in
Python. That is a defensible seam — detection is data processing over
Elasticsearch, analysis is LLM orchestration — but it creates a contract across a
language boundary, and that contract is currently maintained by hand and by
comment.

`app/models.py`:

```python
class EvidenceItem(BaseModel):
    """... Mirrors EvidenceItem in ai-analysis-mcp/src/schemas.ts — the two
    must stay in step, since that server validates against exactly this shape."""
```

A docstring asking two files in two languages to stay in step is not a contract.
It holds until someone changes one side, and the failure is silent on the Python
side and a validation rejection on the TypeScript side — which surfaces as an
`engine_error`, pointing an operator at the model when the real fault is a schema
drift.

`FindingAnalysisInput` / `FindingInput` have the same problem, and the coupling is
load-bearing: `/analysis-input` exists specifically to produce what the engine
consumes.

## Decision

Generate the TypeScript types from the Python schema.

FastAPI already emits an OpenAPI document derived from the Pydantic models. The
build generates the shared TS types from that document, and CI fails if the
committed types differ from the generated ones. Python remains the source of
truth, because that is where the evidence and finding model originates.

The generated types cover the wire contract only — `EvidenceItem`,
`FindingAnalysisInput`, `AnalysisInput`. The engine's internal schemas
(`ModelAnalysisOutput`, `ModelContentOutput`) describe untrusted *model* output,
not the service contract, and stay hand-written and strict where they are.

## Consequences

- Schema drift becomes a build failure instead of a runtime `engine_error`.
- The "must stay in step" docstrings can be deleted, because the invariant is
  enforced.
- Adds a codegen step to the build and a CI check.
- Keeps the boundary honest enough that the polyglot split stays a considered
  choice rather than accumulating quiet coupling costs.

## Rejected alternatives

**Collapse to one language.** Either direction discards working, well-tested code.
Rewriting the engine in Python would throw away the grounding and validation work
that mitigates the TDD's highest-rated risk.

**Keep hand-maintained mirrors.** The current state. It has not broken yet because
one person wrote both sides within a short window; it will not survive a second
contributor or a gap in time.
