# Solitude Reloaded — Architecture

Engineering counterpart to the **Solitude Reloaded TDD v0.1** (6 Aug 2026). The
TDD is the design of record; this document records how the code relates to it,
and the decisions taken where the TDD leaves a choice open or where the code has
diverged.

Decisions live in [`docs/adr/`](adr/). Each is `Proposed` until Engineering signs
off.

## Where the code stands against the TDD

Assessed against `main` **plus the four open PRs (#1–#4)**, since those carry the
evidence-hydration and grounding work described below. Anything marked Partial may
not be visible on `main` alone.


| TDD component | Status | Notes |
|---|---|---|
| §4.1 Consent & Auth | **Not built** | No Entra app registration, no OAuth2 consent flow |
| §4.2 Ingestion Service | **Partial** | JSONL/HTTP ingest only (`routes_ingest.py`). No Graph API collection, no manifest, no raw tier — see ADR 0004 |
| §4.3 Rule Engine | **Partial** | Five detections over sign-in and audit records. Not versioned, no rule registry — see ADR 0002. No FR-08 clearing — see ADR 0005 |
| §4.4 AI Analysis Engine | **Partial** | Grounding validation, circuit breaker and model audit trail built. No review gate — see ADR 0005. MCP-only transport — see ADR 0003 |
| §4.5 Pivot & Recursion Controller | **Not built** | |
| §4.6 Evidence Store & Linking | **Partial** | Findings carry evidence ids; `/analysis-input` hydrates them. No immutable raw store, no hashing — see ADR 0004 |
| §4.7 Enrichment Service | **Not built** | No internal KB, no ipinfo |
| §4.8 Reporting Engine | **Partial** | Triage report only. No full forensic report, no executive summary, no render-time blocking |
| §4.9 Triage Module | **Built** | All four §4.9 questions answered with an evidence basis, explicitly labelled per FR-14 |
| §4.10 ETBR Module | **Not built** | |
| §4.11 Unified UI | **Not built** | API only |
| §4.12 Export Service | **Not built** | JSONL is an *input* format here; FR-12 requires it as an output |

Non-functional posture: **§9 tenant isolation is currently violated** by a
demonstrated cross-case leak (ADR 0006). §8/§9 chain of custody is unmet
(ADR 0004). There is no authentication on any endpoint.

## The eight decisions

1. **[0001](adr/0001-core-not-a-phase-2-module.md)** — this repo is the platform
   core; triage is a scope profile, not a separate system.
2. **[0002](adr/0002-rule-registry-versioning.md)** — rule *logic* stays
   imperative; the rule *set* becomes a declarative, versioned registry.
3. **[0003](adr/0003-analysis-engine-library-with-adapters.md)** — the analysis
   engine is a library with HTTP and MCP adapters, not an MCP server.
4. **[0004](adr/0004-evidence-identity-and-raw-store.md)** — evidence identity is
   a content hash; Elasticsearch is a rebuildable projection.
5. **[0005](adr/0005-case-state-owns-review-and-clearing.md)** — the case service
   owns review state and clearing; the analysis engine stays stateless.
6. **[0006](adr/0006-case-isolation-trust-boundary.md)** — case isolation is
   enforced at a trust boundary, not by string interpolation.
7. **[0007](adr/0007-cross-language-contract.md)** — the Python/TypeScript
   contract is generated, not hand-maintained.
8. **[0008](adr/0008-authentication-better-auth.md)** — Better Auth owns staff
   authentication in the TypeScript layer; this service verifies JWTs via JWKS.

## Why this order

ADR 0006 first, because it is a live data leak in code already under review, and
layer 1 of the fix is small and independent of everything else.

ADR 0004 next, despite being the largest, because evidence ids propagate into
findings, grounding checks, audit records and reports. Nothing has shipped in a
delivered report yet, so this is the cheapest the change will ever be. Deferring
it past the first real case makes it a migration across artefacts we do not
control.

ADRs 0001 and 0002 are then a pair: 0001 says there is one engine, and 0002's
`scope` attribute is the mechanism that lets one engine serve both triage and full
investigation. Neither is much use without the other.

ADR 0003 unblocks the pipeline position the TDD requires of the analysis engine,
and 0005 adds the human gate that is the missing third mitigation for the TDD's
highest-rated risk. 0007 is build hygiene and can land whenever.

ADR 0008 tracks whenever the Orchestration API is stood up — there is no token
issuer before then. It is deliberately not a prerequisite for 0006 layer 1.

## Open questions for Engineering

- **Does Phase 1 build here or greenfield?** ADR 0001 assumes here. If not, the
  §12 divergence risk needs an explicit owner and a plan for keeping two rule
  engines in agreement.
- **Is the Orchestration API TypeScript?** ADR 0008 assumes so and picks Better
  Auth accordingly. If it is not, that ADR is void, though its JWKS verification
  seam survives any OIDC-shaped issuer.
- **What is the case store?** ADR 0005 requires durable per-finding state.
  The TDD's §5 data model implies one; nothing here implements it.
- **The RD is authoritative for acceptance criteria (TDD §1.3) and we do not have
  it.** The Investigation Rule Coverage table, ETBR controls and Mandatory Report
  Outputs are referenced but not reproduced, so our five rules cannot be checked
  against the real coverage table.
- **TDD cross-references are ambiguous.** §4.10 and the §10 testing table both
  cite "Section 10" meaning *RD* Section 10, while this TDD's own Section 10 is
  Testing Strategy. Same collision on "Section 9". Worth fixing in v0.2.
