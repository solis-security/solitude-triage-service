# ADR 0005 — Case state owns the review gate and clearing; the analysis engine stays stateless

- Status: Proposed
- Date: 2026-09-02
- Related: TDD §4.3, §4.4, §4.8, §5, §12; FR-03, FR-08

## Context

Two TDD requirements need durable per-finding state that nothing currently has.

**The review gate (§4.4, §5).** AI output must enter a "proposed finding" state
and be approved, edited or rejected by an analyst before it is eligible for the
report. §4.8 makes report generation *block* on AI findings having been reviewed.
§5 gives `AI Finding` the fields `review_status ∈ {proposed, approved, edited,
rejected}`, `reviewer`, `reviewed_at`.

This matters more than a missing field. §12 rates AI hallucination a **High** risk
and lists three mitigations: evidence-reference validation, an analyst approval
gate, and a confidence circuit breaker. Two are built. The approval gate is the
missing one, and it is the only one with a human in it.

**Clearing (§4.3, FR-08).** An analyst can mark a risky sign-in legitimate;
cleared items must be excluded from subsequent rule and AI passes "and from
prompts sent to the AI engine", without deleting the underlying evidence. §5 gives
`Rule Finding` a `status (active/cleared)`.

Today `Finding` in `app/models.py` has no status field, and
`GET /triage/{case_id}/analysis-input` sends every finding to the model. An
analyst's judgment that something is benign has nowhere to live and no effect.

## Decision

**All per-finding state lives in the case service. The analysis engine remains
stateless.**

- The engine takes findings and evidence and returns a proposed analysis plus a
  validation verdict. It persists nothing about a case and holds no opinion about
  whether a human accepted its output.
- The case service persists AI output as `proposed`, owns the
  `proposed → approved | edited | rejected` transitions, and records reviewer
  identity and timestamp.
- `Finding` gains `status: active | cleared`, plus who cleared it and when.
- `/analysis-input` filters to active findings. This is the FR-08 requirement that
  cleared items never reach a prompt, and it belongs at the boundary that builds
  the prompt input.
- Report generation refuses to render while any AI finding is still `proposed`,
  implementing §4.8's blocking condition in code rather than as a manual QA step.

**The two audit trails are distinct and must not be conflated.** The engine's
`~/.solitude/ai-audit.jsonl` is a *model* audit trail — what was asked, what came
back, how grounding was judged. The case audit trail records *human* decisions —
who approved what, who cleared what, when. Different subjects, different
retention, different legal weight.

## Consequences

- The engine stays swappable and testable offline, and the state that matters for
  defensibility sits with the case rather than in a local file beside a model.
- `/analysis-input`'s contract changes to exclude cleared findings. Better done
  before anything consumes it in anger.
- The engine's audit record should carry a prompt/context reference, which §4.4
  requires and `audit.ts` currently lacks — without it a recorded verdict cannot
  be tied to the input that produced it.
- A case store is now required. It is implied by the TDD's data model (§5) but has
  no implementation here yet.

## Rejected alternatives

**Put review state in the analysis engine.** Would make the engine stateful,
require it to know about analysts and cases, and split case state across two
stores — with the human-decision half living next to the model rather than next
to the evidence.

**Treat the AI audit log as the case audit trail.** It is append-only JSONL on
local disk keyed to a model interaction. It answers "what did the model do", never
"who accepted it".
