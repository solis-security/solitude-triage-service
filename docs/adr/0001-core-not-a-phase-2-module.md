# ADR 0001 — This repository is the platform core, not the Phase 2 triage module

- Status: Proposed
- Date: 2026-09-02
- Deciders: Engineering (Jeff Destine), Zane Hill
- Related: TDD §4.3, §4.9, §7, §12

## Context

The TDD delivers in two phases: Phase 1 is the full forensic platform, Phase 2 is
triage plus ETBR. This service was written as §4.9, the Phase 2 Triage Assessment
Module — `app/main.py` says so in its own description.

But it exists now, and the Phase 1 rule engine does not. The TDD's own risk
register anticipates exactly this shape and rates it Medium:

> Phase 2 built as a separate codebase diverges from Phase 1 rule logic.

with the mitigation being that Phase 2 reuses the Phase 1 Ingestion Service and
Rule Engine. That mitigation assumed Phase 1 would be built first. It wasn't, so
the mitigation as written is unavailable, and the default outcome is two rule
engines that drift.

TDD §7 is the decisive evidence for how this was meant to work. It is a single
table of rule areas with two columns — "Full-investigation logic (Rule Engine)"
and "Triage logic (Triage Module)". Both columns describe the *same* rule areas at
different depths. That is one engine with two scopes, not two engines.

## Decision

This repository is the core of the platform. Triage is a **scope profile** over
the shared rule engine and evidence model, not a separate system.

Concretely:

- The rule engine, evidence model and case model here are the ones Phase 1 builds
  on. Phase 1 adds components (consent, ingestion, pivots, reporting, UI); it does
  not add a second engine.
- Triage is expressed as a scope attribute on each rule (see ADR 0002), so the
  §7 two-column table becomes data rather than a fork in the code.
- The repository and service should be renamed to drop "triage" from their
  identity. The name is currently load-bearing in the wrong direction: it invites
  the exact duplication §12 warns about.

## Consequences

- Phase 1 work lands here rather than in a greenfield repo. Anything already
  built — the rule engine, evidence grounding, the ES projection — is Phase 1
  infrastructure that happens to have been exercised by triage first.
- The `solitude-triage-service` name, the FastAPI `description` in `app/main.py`,
  and the README all need updating. Cheap now; steadily more expensive as more
  references accumulate.
- Our internal PR phase numbering (phase0/phase1/phase2 branches) collides
  head-on with the TDD's Phase 1/Phase 2. Rename ours to avoid ambiguity in
  review — they refer to remediation stages, not TDD phases.
- If Engineering decides instead that Phase 1 is greenfield elsewhere, this ADR is
  rejected and §12's divergence risk must be accepted explicitly and owned, with
  a plan for keeping two rule engines in agreement.

## Rejected alternatives

**Keep triage as a narrow module and build Phase 1 separately.** This is the
status quo by inertia. It realises a risk the TDD already identified, and
duplicates detection logic — the one part of the system that is genuinely hard to
get right and most costly to have disagree between two implementations.
