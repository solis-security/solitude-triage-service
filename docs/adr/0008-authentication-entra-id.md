# ADR 0008 — Entra ID is the identity provider; services verify tokens against JWKS

- Status: Proposed
- Date: 2026-09-02
- Supersedes: an earlier draft of this ADR that proposed Better Auth
- Related: ADR 0003, ADR 0006, ADR 0009; TDD §4.1, §4.11, §9

## Context

ADR 0006 left open where authentication lives. Two facts settle it:

- **The platform is Python/FastAPI throughout**, including the Orchestration API.
  Better Auth, the initial candidate, is a TypeScript library and cannot run
  there. That earlier draft is superseded rather than amended.
- **Our analysts already exist in Entra ID.** Solis is a Microsoft shop, and this
  is a tool for investigating M365 tenants. A self-hosted identity system would
  create a second credential store for staff who already have corporate
  identities, and would sit outside the conditional-access and MFA controls the
  business already runs.

There is a second point that is easy to miss and expensive to get wrong. "Auth"
means two unrelated things here, and **both are now Entra**, which makes
conflating them more likely rather than less:

- **Staff authentication** — proving a Solis analyst is who they say they are,
  and what they may see. This ADR.
- **Customer tenant consent (TDD §4.1)** — OAuth2 admin consent granting our app
  scoped, app-only access to a *customer's* M365 tenant, per incident.

These must be **separate app registrations**. Different tenants, lifecycles,
consent models and blast radius. A single registration serving both would mean a
staff sign-in and a customer evidence-collection grant share a trust boundary.

## Decision

**Entra ID is the identity provider for staff authentication**, via standard
OIDC. Two app registrations: one for the platform API (the resource) and one for
the Unified UI (the client).

**Every service verifies tokens locally against JWKS and holds no session
state.** FastAPI middleware fetches the OIDC discovery document, selects the
signing key by the token's `kid`, verifies the signature, and validates claims.
No shared database, no per-request callback to the IdP.

Verification rules, which are not optional details:

- **Accept only tokens whose `aud` is our own API.** Microsoft is explicit that
  accepting a token issued for another resource is a confused-deputy
  vulnerability.
- **Never attempt to validate Microsoft Graph tokens.** They are a proprietary
  format and are not validatable by these rules. Graph tokens belong to the §4.1
  collection path and must never be presented to our API as staff credentials.
- **Pin the algorithm.** Entra signs with RS256. Assert it during verification;
  never trust the `alg` the token asserts about itself.
- **Validate `iss` exactly** against the tenant-specific v2.0 metadata document
  (`https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`),
  and read keys from its `jwks_uri`. We are single-tenant for staff, so the
  tenant-independent issuer-templating rules do not apply — and adopting them
  without needing them would weaken the check.
- **Refresh JWKS on a schedule** (Microsoft suggests roughly daily) and on an
  unknown `kid`, so key rollover does not cause an outage.
- **Fail closed.** An unverifiable token is rejected, never downgraded.

**App roles, not group claims, carry the role model.** Roles are declared on the
API's app registration and arrive in the `roles` claim. This maps onto TDD §9's
forensic analyst / CIM / non-technical split, and unlike `groups` it is stable
across tenants and moves with the application.

**Revocation is handled by Continuous Access Evaluation, not by short
lifetimes.** Entra access tokens default to a randomised 60–90 minutes and that
is not something to fight. An earlier draft of this ADR asked for minute-scale
lifetimes; that was wrong for this IdP. CAE is the mechanism that actually
revokes access near-real-time, which matters for a system holding customer
forensic evidence.

**Case-level authorisation stays ours.** The `roles` claim says what kind of user
this is, not which cases they may open. "May this principal read case X" is an
application decision the case service owns (ADR 0005). Assuming the IdP answers
it would leave ADR 0006's isolation requirement unmet.

## Consequences

- Staff get SSO against the directory they already use, and inherit conditional
  access and MFA without us building any of it — which TDD §9 and §10 both care
  about.
- No user table, no password handling, no session store, in any of our services.
- Each service gains a JWT verification dependency and a JWKS cache. The
  verification seam is identical in every service, so it should be one shared
  module rather than reimplemented per service.
- A runtime dependency on Entra being reachable for JWKS refresh. Cache with a
  sane TTL; an unreachable IdP must not fail open.
- Until the Orchestration API exists there is no token issuer. In the interim this
  service must not be exposed or pointed at real tenant data, and the ADR 0006
  `case_id` validation fix stands on its own — it is input validation, not
  authentication, and must not wait for this.
- Because both staff auth and §4.1 customer consent are Entra, the separation
  between them needs to be explicit in the app-registration setup and reviewed,
  not left as an implementation detail.

## Rejected alternatives

**Better Auth.** The initial direction, and a reasonable library — but it is
TypeScript-only, so a Python Orchestration API rules it out. It would also have
meant a second identity store alongside the Entra accounts staff already have.

**Self-hosted IdP (Keycloak or similar).** Standards-compliant and
language-agnostic, but it is infrastructure to run, patch and back up, and it
still leaves staff with two identities unless federated to Entra — at which point
Entra is the source of truth anyway.

**Local accounts in the platform (FastAPI-Users or equivalent).** Cheapest to
start, worst to own: password handling, MFA and offboarding all become ours, for
staff who are already centrally managed.
