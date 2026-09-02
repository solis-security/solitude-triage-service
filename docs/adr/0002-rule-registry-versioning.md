# ADR 0002 — Declarative rule *set*, imperative rule *logic*

- Status: Proposed
- Date: 2026-09-02
- Related: TDD §4.3, §7, §10 (Regression), §12; FR-02

## Context

TDD §4.3 requires that rules be "declarative, versioned, and each rule run is
stamped with the rule-set version used, so report outputs are traceable and
reproducible". FR-02's acceptance signal is that the rule set is "documented,
versioned, traceable in reports". §12 rates rule-set drift a Medium risk, and §10
requires that a rule-set version change can be re-run against archived cases.

Today `app/rules.py` has five detection functions invoked by a hardcoded list in
`run_all_rules`. There is no rule id, no version, no scope metadata, and nothing
stamped on the report. `grep -rniE "rule_version|rule_set"` returns nothing.

The word "declarative" needs care. Read literally — rules expressed in YAML or a
DSL — it is the wrong call here, and expensive to discover late. The existing
rules compute haversine distances between country centroids, parse RFC-5322-ish
recipient lists, and pair temporally adjacent sign-ins. Expressing that
declaratively means inventing a language that will need arithmetic, geo
primitives and iteration; that language becomes a second codebase with no tests
and worse ergonomics than Python.

What §4.3 actually needs from "declarative" is delivered by the *set* being data:
enumerable, versioned, traceable, and scope-filterable without editing code.

## Decision

Rule **logic** stays as Python functions. The rule **set** becomes a declarative
registry.

Each rule is registered with metadata:

- `id` — stable identifier, e.g. `impossible_travel`
- `version` — bumped when the rule's logic or thresholds change
- `area` — the TDD §7 rule area
- `severity` — default severity
- `scope` — `full`, `triage`, or `both`, encoding the §7 two-column table
- `fn` — the callable

`run_all_rules` becomes a scope-filtered iteration over the registry rather than a
hardcoded list. Every `Finding` carries `rule_id` and `rule_version`. Every report
carries a `rule_set_version`: a deterministic hash over the sorted
`(id, version)` pairs of the rules that ran.

## Consequences

- FR-02 is satisfiable and testable: a report names the exact rule set that
  produced it, and §10's regression strategy becomes mechanical — re-run an
  archived case, diff findings, and any change is attributable to a specific rule
  version bump.
- §7's triage-vs-full distinction stops being a fork. Triage runs the registry
  filtered to `scope in (triage, both)`; the full investigation runs everything.
  This is what makes ADR 0001 implementable.
- Thresholds currently in `app/config.py` (e.g. `impossible_travel_kmh_threshold`)
  are inputs to a rule's behaviour, so changing one changes results without
  changing any rule version. Either fold thresholds into the rule's version
  computation or record the resolved threshold values alongside the rule-set
  version. Otherwise "reproducible" is untrue in a way that will only surface
  during a dispute.
- Rule ids become part of the report contract and must stay stable. Renaming a
  rule id is a breaking change to archived reports.

## Rejected alternatives

**A YAML/DSL rule language.** Cannot express the existing detections without
growing into a general-purpose language. Large build cost, worse testability, and
it buys nothing FR-02 actually asks for.

**A bare `RULE_SET_VERSION = "1.0"` constant.** Cheap, and satisfies a careless
reading of FR-02. But it is a number a human must remember to bump, so it will
silently go stale and assert reproducibility that does not hold. A hash derived
from the registry cannot drift from what actually ran.
