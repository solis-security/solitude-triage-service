/**
 * Pure functions — no Ollama, no MCP, no filesystem. This is where evidence
 * grounding is actually enforced before any AI output can reach a report.
 */

export type ValidationStatus =
  | "grounded"
  | "rejected_no_evidence"
  | "rejected_ungrounded"
  | "engine_error";

/**
 * A model may legitimately report insufficient evidence with no references —
 * that is an honest, grounded answer. What is rejected is a firm conclusion
 * that cites nothing, or that cites an evidence id it was never given.
 */
export function validateGrounding(
  evidenceRefs: readonly string[],
  providedEvidenceIds: readonly string[],
  insufficientEvidence: boolean,
): ValidationStatus {
  // The subset check runs unconditionally. Returning early on
  // insufficientEvidence let an invented id through whenever the model also
  // set that flag — the id was then handed to whatever renders citations and
  // recorded in the audit log as grounded.
  const provided = new Set(providedEvidenceIds);
  if (!evidenceRefs.every((ref) => provided.has(ref))) return "rejected_ungrounded";
  // Only the empty-refs case is excused by the flag: an honest "the evidence
  // does not support a conclusion" legitimately cites nothing.
  if (insufficientEvidence) return "grounded";
  if (evidenceRefs.length === 0) return "rejected_no_evidence";
  return "grounded";
}

export const SENSITIVITY_VOCABULARY = [
  "financial_banking_details",
  "credentials",
  "pii",
  "invoice_or_payment_request",
  "contract_or_legal",
  "health_information",
  "none_detected",
] as const;

/**
 * Grounding for content analysis, which previously had none at all.
 *
 * Two things are checkable without a second model: the flags must come from
 * the controlled vocabulary, and the claimed method must match the input the
 * model was actually given. A model that reports "content_analysis" when no
 * body was supplied is describing an analysis it could not have performed.
 */
export function validateContentGrounding(
  flags: readonly string[],
  method: string,
  bodyWasProvided: boolean,
): ValidationStatus {
  const vocabulary = new Set<string>(SENSITIVITY_VOCABULARY);
  if (!flags.every((f) => vocabulary.has(f))) return "rejected_ungrounded";
  if (method === "content_analysis" && !bodyWasProvided) return "rejected_ungrounded";
  if (method === "subject_line_fallback" && bodyWasProvided) return "rejected_ungrounded";
  return "grounded";
}

export function isRejection(status: ValidationStatus): boolean {
  return status === "rejected_no_evidence" || status === "rejected_ungrounded";
}

export interface EngineHealthCounts {
  windowSize: number;
  callsInWindow: number;
  rejectedInWindow: number;
  rejectionRate: number;
  circuitBreakerTripped: boolean;
}

/** Below this many calls the rejection rate is too noisy to act on. Capped
 *  by the window, so configuring a window smaller than this tightens the
 *  breaker rather than silently disabling it — with a hardcoded 5, setting
 *  AI_CIRCUIT_BREAKER_WINDOW=3 meant the breaker could never trip at all. */
export const MIN_BREAKER_SAMPLE = 5;

export function computeEngineHealth(
  recentValidations: readonly ValidationStatus[],
  windowSize: number,
  threshold: number,
): EngineHealthCounts {
  const recent = recentValidations.slice(-windowSize);
  const rejected = recent.filter((v) => isRejection(v) || v === "engine_error").length;
  const rate = recent.length === 0 ? 0 : rejected / recent.length;
  return {
    windowSize,
    callsInWindow: recent.length,
    rejectedInWindow: rejected,
    rejectionRate: rate,
    circuitBreakerTripped:
      recent.length >= Math.min(MIN_BREAKER_SAMPLE, windowSize) && rate > threshold,
  };
}
