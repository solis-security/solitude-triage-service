# ADR 0008 — Better Auth in the TypeScript layer; this service verifies JWTs

- Status: Proposed
- Date: 2026-09-02
- Related: ADR 0003, ADR 0006; TDD §4.1, §4.11, §9

## Context

ADR 0006 left open where authentication lives. The working direction is
**Better Auth**, consistent with the TypeScript Orchestration API and Unified UI
(TDD §4.11) and with the analysis engine (ADR 0003).

One constraint shapes the whole design: **Better Auth is a TypeScript library and
this service is Python/FastAPI.** It cannot run here. Whatever we choose, this
service's job is to *verify* a credential issued elsewhere, not to own identity.

There is a second, easier-to-miss point. "Auth" means two unrelated things in this
system and conflating them would be a significant design error:

- **Staff authentication** — proving a Solis analyst is who they say they are, and
  what they may see. This is what Better Auth does.
- **Customer tenant consent (TDD §4.1)** — OAuth2 admin consent granting our Entra
  app scoped, app-only access to a *customer's* M365 tenant, per incident.

These have different credentials, lifecycles, threat models and audit
requirements. Better Auth has no role in §4.1.

## Decision

**Better Auth owns staff authentication, and runs in the TypeScript layer** —
the Orchestration API and Unified UI. It is the single sign-in surface for
analysts, CIM and onboarding users.

**This service verifies JWTs and holds no session state.** Better Auth's JWT
plugin publishes a JWKS endpoint (`/api/auth/jwks`, remappable to
`/.well-known/jwks.json`). FastAPI middleware fetches and caches the JWKS, selects
the key by the token's `kid`, verifies the signature, and validates issuer and
audience. No shared database, no callback to the auth server per request.

Supporting decisions:

- **Pin the signing algorithm explicitly.** Better Auth defaults to EdDSA
  (Ed25519) and also supports ES256/ES512 and RS256/PS256. Choose one, assert it
  during verification, and confirm the Python JWT library supports it before
  committing — never accept the algorithm the token asserts about itself.
- **Sessions for the browser, JWTs for the service hop.** Better Auth's own docs
  are explicit that the JWT plugin "is not meant as a replacement for the
  session". The UI keeps its session cookie; JWTs exist to carry identity across
  the boundary into this service.
- **Short token lifetimes.** JWT verification is stateless, so revocation is not
  immediate — a revoked analyst keeps access until their token expires. For a
  system holding customer forensic evidence that window should be minutes, not
  hours.
- **Organisation plugin for the tenant layer.** Better Auth's organization plugin
  models customers as isolated organisations with roles and optional teams, which
  maps cleanly onto the role model TDD §9 requires (forensic analyst / CIM /
  non-technical).
- **Case-level authorisation stays ours.** The organization plugin scopes to
  organisations and teams, not to individual cases. "May this principal read case
  X" is an application-level decision the case service owns. Better Auth supplies
  authenticated identity and org role; it does not answer the case question, and
  assuming otherwise would leave ADR 0006's isolation requirement unmet.

## Consequences

- ADR 0006's open question is answered: identity lives in the TypeScript layer,
  enforcement happens at this service's edge.
- This service gains a JWT verification dependency and a JWKS cache, but no user
  table, no password handling and no session store.
- Until the Orchestration API exists there is no issuer. In the interim this
  service must not be exposed or pointed at real tenant data, and the ADR 0006
  `case_id` validation fix stands on its own — it is an input-validation bug, not
  an authentication one, and must not wait for this.
- Adds a runtime dependency on the auth service being reachable for JWKS refresh.
  Cache keys with a sane TTL and fail closed on an unverifiable token.
- If the Orchestration API turns out not to be TypeScript, this ADR is void and
  the choice reopens. The JWKS verification design here survives that change —
  any OIDC-shaped issuer fits the same seam.

## Rejected alternatives

**Run authentication in this service.** Would mean a Python auth stack, a second
user store, and two sign-in surfaces for one product.

**Shared session database between the TS layer and this service.** Couples two
services to one schema and puts a database round trip in every request, for
something a signature check answers locally.

**Verify by calling the auth server per request.** Adds a network hop and a hard
availability dependency to every case read; JWKS verification gets the same
answer offline.
