# ADR 0006 — Case isolation is enforced at a trust boundary, not by string interpolation

- Status: Proposed
- Date: 2026-09-02
- Related: TDD §9 (Security and Compliance), §8 (Security); RD tenant isolation
- Severity: contains a demonstrated cross-case data leak — see below

## Context

TDD §9 states: "Tenant data isolation: all storage and processing scoped by
case_id / tenant_id; **no cross-tenant querying**."

The service currently has no authentication of any kind, `allow_origins=["*"]`
CORS in `app/main.py`, and — the immediate problem — `case_id` is taken from the
URL path and interpolated straight into an Elasticsearch index name with no
validation:

```python
def signin_index(case_id: str) -> str:
    return f"{settings.signin_index_prefix}-{case_id}".lower()
```

Elasticsearch index expressions accept wildcards. A `case_id` of `*` therefore
resolves to `m365-signin-logs-*`, which matches every case index in the cluster.

**This was verified end-to-end against a live Elasticsearch on 2026-09-02**, not
inferred. Two synthetic case indices were created alongside the existing demo
case, and `GET /triage/*` returned a single triage report spanning all three
cases — 45 sign-in records belonging to three different customers, including
their user principal names. The test indices were removed afterwards.

Every endpoint is affected: `/triage/{case_id}`, `/triage/{case_id}/findings`,
`/triage/{case_id}/analysis-input`, and both `/logs/{case_id}` routes. It is a
single unauthenticated GET, with no special tooling.

## Decision

Case isolation is enforced at an explicit trust boundary. Three layers, in order
of how load-bearing they are:

1. **Validate `case_id` at the edge.** A strict pattern (`^[A-Za-z0-9_-]{1,64}$`),
   applied as a FastAPI path parameter constraint so it is enforced on every route
   by construction rather than remembered per handler. Wildcards, commas, and
   index-expression metacharacters are rejected before reaching storage.
2. **Resolve indices explicitly.** Storage calls pass
   `expand_wildcards="none"` / `allow_no_indices=False` so that even a validation
   bypass cannot silently widen a query across cases. Defence in depth: layer 1
   is the fix, layer 2 makes the failure mode a loud error rather than a quiet
   leak.
3. **Authenticate and authorise at the boundary.** No unauthenticated access to
   case data, and an authenticated principal is authorised for a *specific* case
   rather than for the service. Replace wildcard CORS with an explicit allowlist.

Index-per-case is retained as the storage layout. It gives real physical
isolation and makes case deletion a single operation; the cost is ES cluster-state
overhead at high case counts, which is manageable with lifecycle policies that
close or archive completed cases.

## Consequences

- §9's isolation claim becomes enforceable rather than aspirational.
- Layer 1 is small and self-contained and should not wait for the rest of this
  architecture to land. The leak is live in code currently under review.
- Authentication is a prerequisite for anything holding real customer M365 data.
  Until it exists, this service must not be deployed anywhere reachable, and must
  not be pointed at a real tenant's logs.
- Where authentication lives is settled by ADR 0008: Entra ID is the identity
  provider, with every service verifying tokens against JWKS at its own edge.
  Layer 1 does not depend on that and must not wait for it — a wildcard `case_id`
  is an input-validation bug, and would still be one behind a login.

## Rejected alternatives

**Rely on the Orchestration API to sanitise input.** The service would remain
exploitable by anything that reaches it directly, and a component holding forensic
evidence should not depend on a caller that does not exist yet for its isolation.

**Escape or strip metacharacters instead of rejecting them.** Silently rewriting
an identifier means a request for one case can be answered with another. Rejecting
malformed input is the only behaviour that cannot mislead.
