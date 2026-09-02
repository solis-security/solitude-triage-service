# ADR 0009 — The analysis engine stays TypeScript for now, with a named trigger to revisit

- Status: Proposed
- Date: 2026-09-02
- Related: ADR 0003, ADR 0004, ADR 0007

## Context

With the platform settled as Python/FastAPI throughout (ADR 0008), the analysis
engine in `ai-analysis-mcp/` is the only TypeScript component. That is worth
examining rather than inheriting by accident.

The cost of the split is real and concentrated: a second toolchain, a second CI
lane, a Node runtime in production, and a cross-language contract that exists
*solely* because of this one component — ADR 0007 has no other justification.

The case for porting it to Python is therefore stronger than it was. The case
against is that the engine is ~600 lines of pure logic with 38 tests, and it
implements the direct mitigation for the TDD's highest-rated risk (§12, AI
hallucination, High): grounding validation, the rejection circuit breaker, and the
model audit trail. That code has already had several subtle defects found and
fixed — an unconditional subset check, breaker sample-size capping, withholding
rejected narratives from callers while retaining them for audit, recording cited
refs before rejection clears them. A port must preserve every one of those, and a
port that quietly loses one is worse than no port.

The decisive question is reversibility, and it cuts differently here than in
ADR 0004. Evidence identity had to be settled immediately because ids propagate
into delivered reports we cannot migrate. **The engine's language propagates
nowhere** — it sits behind an HTTP boundary, and callers cannot tell what it is
written in. The "cheapest now" argument does not transfer.

## Decision

**Keep the analysis engine in TypeScript for now.** Do not port speculatively
against an Orchestration API that does not yet exist.

**Revisit when the Orchestration API is actually being built**, at which point the
cost of the split is concrete rather than hypothetical. Revisit sooner if any of
these become true:

- The engine grows substantially beyond its current scope, raising the eventual
  port cost past the value of the working code.
- The generated contract of ADR 0007 proves burdensome in practice rather than in
  theory.
- Operational cost bites — a Node runtime in production turns out to be a real
  burden for deployment, patching or on-call.

**If it is ported later**, the MCP adapter stays TypeScript per the standing
preference for MCP servers, and becomes a thin proxy over the Python engine's HTTP
API. There would still be exactly one implementation of the grounding gate, and
ADR 0007's generated contract would shrink to almost nothing, because a proxy
carries very little schema surface.

## Consequences

- The working, tested implementation of the top-risk mitigation is preserved, and
  no effort is spent on a rewrite whose consumer does not exist.
- The polyglot cost is accepted deliberately, with an owner and a trigger, rather
  than drifting into permanence unexamined.
- ADR 0007 stays necessary in the meantime, and its justification is now precisely
  this ADR rather than a general claim about the codebase.
- This ADR should be re-read, not assumed, when the Orchestration API work starts.
  A deferral with no one revisiting it is just a decision made badly.

## Rejected alternatives

**Port to Python now.** Tempting for uniformity, but it is speculative work
against a consumer that does not exist, and it risks losing hard-won correctness
in the one component where correctness is the entire product.

**Commit to TypeScript permanently.** Overcommits on the evidence available. The
balance genuinely may shift once the Orchestration API is real; naming the trigger
is more honest than pretending the question is closed.
