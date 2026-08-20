import { z } from "zod";
import { SENSITIVITY_VOCABULARY } from "./validation.js";

/** Compact, model-facing view of one evidence record. Keep it small: the
 *  model should never see more than what it needs to support — or fail to
 *  support — a conclusion. */
export const EvidenceItem = z.object({
  id: z.string(),
  source: z.string().describe("e.g. 'Unified Audit Log', 'Sign-in log'"),
  summary: z.string().describe("Short factual description of what this record shows"),
});
export type EvidenceItem = z.infer<typeof EvidenceItem>;

export const Severity = z.enum(["low", "medium", "high"]);
export const Confidence = z.enum(["low", "medium", "high"]);

export const FindingInput = z.object({
  id: z.string(),
  rule: z.string(),
  severity: Severity,
  area: z.string(),
  text: z.string(),
  evidence: z.array(EvidenceItem),
});
export type FindingInput = z.infer<typeof FindingInput>;

/**
 * What we require back from the model. Parsed with safeParse, never with a
 * throwing parse: model output is untrusted input, and a model returning
 * confidence "very high" must degrade to engine_error rather than raise out
 * of the tool call.
 */
export const ModelAnalysisOutput = z.object({
  narrative: z.string(),
  confidence: Confidence,
  evidence_refs: z.array(z.string()),
  insufficient_evidence: z.boolean(),
});

export const ModelContentOutput = z.object({
  method: z.enum(["content_analysis", "subject_line_fallback"]),
  // Deliberately z.string(), not z.enum(SENSITIVITY_VOCABULARY). Validating
  // the vocabulary here made safeParse reject an invented flag first, so it
  // was recorded as engine_error — pointing the operator at Ollama when the
  // problem was the model inventing categories. The vocabulary is a
  // grounding rule, so validateContentGrounding owns it.
  sensitivity_flags: z.array(z.string()),
  narrative: z.string(),
  confidence: Confidence,
});

export const ValidationStatusSchema = z.enum([
  "grounded",
  "rejected_no_evidence",
  "rejected_ungrounded",
  "engine_error",
]);

export interface AnalysisResult {
  narrative: string;
  confidence: z.infer<typeof Confidence>;
  evidence_refs: string[];
  insufficient_evidence: boolean;
  model: string;
  model_digest: string | null;
  generated_at: string;
  validation: z.infer<typeof ValidationStatusSchema>;
  error: string | null;
}

export interface CaseSummaryResult extends AnalysisResult {
  /** Cited finding ids, kept out of evidence_refs so a caller resolving
   *  that field against the evidence set does not come up empty. */
  finding_refs: string[];
  finding_count: number;
  high_severity_count: number;
}

export interface ContentSensitivityResult {
  evidence_id: string;
  /** null when no assessment was accepted. Reporting a method for a
   *  rejected result asserts an analysis that did not happen — and forcing
   *  either literal asserts something false in one of the two rejection
   *  cases. */
  method: "content_analysis" | "subject_line_fallback" | null;
  sensitivity_flags: string[];
  narrative: string;
  confidence: z.infer<typeof Confidence>;
  model: string;
  model_digest: string | null;
  generated_at: string;
  validation: z.infer<typeof ValidationStatusSchema>;
  error: string | null;
}

export interface EngineHealth {
  window_size: number;
  calls_in_window: number;
  rejected_in_window: number;
  rejection_rate: number;
  circuit_breaker_tripped: boolean;
  ollama_reachable: boolean;
  available_models: string[];
}
