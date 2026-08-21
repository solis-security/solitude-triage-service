import { appendAuditRecord, readRecentValidations } from "./audit.js";
import { settings } from "./config.js";
import { OllamaClient, OllamaUnavailableError } from "./ollama.js";
import {
  ModelAnalysisOutput,
  ModelContentOutput,
  type AnalysisResult,
  type CaseSummaryResult,
  type ContentSensitivityResult,
  type EngineHealth,
  type FindingInput,
} from "./schemas.js";
import * as prompts from "./prompts.js";
import {
  computeEngineHealth,
  isRejection,
  validateContentGrounding,
  validateGrounding,
  type ValidationStatus,
} from "./validation.js";

/**
 * What a caller sees instead of a rejected conclusion.
 *
 * Previously only `evidence_refs` was cleared on rejection while the model's
 * narrative and confidence were returned verbatim — so a hallucinated claim
 * still reached anything that rendered `narrative` without also checking
 * `validation`. The rejected text is kept in the audit log, not returned.
 */
const REJECTED_NARRATIVE =
  "Analysis withheld — the model's conclusion failed evidence-grounding validation " +
  "and was not accepted. See the audit log for the withheld text.";

const ENGINE_ERROR_NARRATIVE =
  "Analysis unavailable — the AI engine could not be reached or returned an unusable response.";

function nowIso(): string {
  return new Date().toISOString();
}

export async function analyzeFinding(
  finding: FindingInput,
  client: OllamaClient = new OllamaClient(),
): Promise<AnalysisResult> {
  const providedEvidenceIds = finding.evidence.map((e) => e.id);
  const base = {
    model: client.model,
    generated_at: nowIso(),
    insufficient_evidence: true,
    evidence_refs: [] as string[],
  };

  try {
    const raw = await client.generateJson(
      prompts.FINDING_ANALYSIS_SYSTEM,
      prompts.findingAnalysisUserPrompt(finding),
    );

    // safeParse, never parse: model output is untrusted. An unexpected
    // confidence value degrades to engine_error instead of throwing out of
    // the tool call.
    const parsed = ModelAnalysisOutput.safeParse(raw);
    if (!parsed.success) {
      return await record("finding_analysis", providedEvidenceIds, {
        ...base,
        narrative: ENGINE_ERROR_NARRATIVE,
        confidence: "low",
        model_digest: null,
        validation: "engine_error",
        error: `Model output did not match the required shape: ${parsed.error.issues
          .map((i) => `${i.path.join(".")}: ${i.message}`)
          .join("; ")}`,
      });
    }

    const output = parsed.data;
    const validation = validateGrounding(
      output.evidence_refs,
      providedEvidenceIds,
      output.insufficient_evidence,
    );
    const rejected = isRejection(validation);

    return await record(
      "finding_analysis",
      providedEvidenceIds,
      {
        narrative: rejected ? REJECTED_NARRATIVE : output.narrative,
        confidence: rejected ? "low" : output.confidence,
        evidence_refs: rejected ? [] : output.evidence_refs,
        insufficient_evidence: output.insufficient_evidence,
        model: client.model,
        model_digest: await client.modelDigest(),
        generated_at: nowIso(),
        validation,
        error: null,
      },
      rejected ? output.narrative : undefined,
      output.evidence_refs,
    );
  } catch (error) {
    return await record("finding_analysis", providedEvidenceIds, {
      ...base,
      narrative: ENGINE_ERROR_NARRATIVE,
      confidence: "low",
      model_digest: null,
      validation: "engine_error",
      error: error instanceof OllamaUnavailableError ? error.message : String(error),
    });
  }
}

export async function summarizeCase(
  findings: readonly FindingInput[],
  client: OllamaClient = new OllamaClient(),
): Promise<CaseSummaryResult> {
  const providedEvidenceIds = findings.flatMap((f) => f.evidence.map((e) => e.id));
  // The case-summary prompt serialises whole findings, so their ids are part
  // of what the model was legitimately given. Requiring a strict subset of
  // evidence ids rejected correct summaries purely for citing "F-1006"
  // alongside the right evidence — observed against a real model, never
  // against the mock. A finding id is grounded; an invented id still is not.
  const citableIds = [...providedEvidenceIds, ...findings.map((f) => f.id)];
  let findingRefs: string[] = [];
  const counts = {
    finding_count: findings.length,
    high_severity_count: findings.filter((f) => f.severity === "high").length,
  };

  const result = await (async (): Promise<AnalysisResult> => {
    try {
      const raw = await client.generateJson(
        prompts.CASE_SUMMARY_SYSTEM,
        prompts.caseSummaryUserPrompt(findings),
      );
      const parsed = ModelAnalysisOutput.safeParse(raw);
      if (!parsed.success) {
        return await record("case_summary", citableIds, {
          narrative: ENGINE_ERROR_NARRATIVE,
          confidence: "low",
          evidence_refs: [],
          insufficient_evidence: true,
          model: client.model,
          model_digest: null,
          generated_at: nowIso(),
          validation: "engine_error",
          error: `Model output did not match the required shape: ${parsed.error.issues
            .map((i) => `${i.path.join(".")}: ${i.message}`)
            .join("; ")}`,
        });
      }

      const output = parsed.data;
      const validation = validateGrounding(
        output.evidence_refs,
        citableIds,
        output.insufficient_evidence,
      );
      const rejected = isRejection(validation);
      // Keep the two id namespaces apart in the response: evidence_refs is
      // typed and named for EvidenceItem ids, and a renderer resolving a
      // finding id against the evidence set finds nothing.
      const findingIds = new Set(findings.map((f) => f.id));
      const citedFindingRefs = output.evidence_refs.filter((id) => findingIds.has(id));
      const citedEvidenceRefs = output.evidence_refs.filter((id) => !findingIds.has(id));
      findingRefs = rejected ? [] : citedFindingRefs;

      return await record(
        "case_summary",
        citableIds,
        {
          narrative: rejected ? REJECTED_NARRATIVE : output.narrative,
          confidence: rejected ? "low" : output.confidence,
          evidence_refs: rejected ? [] : citedEvidenceRefs,
          insufficient_evidence: output.insufficient_evidence,
          model: client.model,
          model_digest: await client.modelDigest(),
          generated_at: nowIso(),
          validation,
          error: null,
        },
        rejected ? output.narrative : undefined,
        output.evidence_refs,
      );
    } catch (error) {
      return await record("case_summary", citableIds, {
        narrative: ENGINE_ERROR_NARRATIVE,
        confidence: "low",
        evidence_refs: [],
        insufficient_evidence: true,
        model: client.model,
        model_digest: null,
        generated_at: nowIso(),
        validation: "engine_error",
        error: error instanceof OllamaUnavailableError ? error.message : String(error),
      });
    }
  })();

  return { ...result, ...counts, finding_refs: findingRefs };
}

export async function analyzeEmailContent(
  evidenceId: string,
  subject: string,
  body: string | null = null,
  client: OllamaClient = new OllamaClient(),
): Promise<ContentSensitivityResult> {
  const bodyWasProvided = Boolean(body && body.trim().length > 0);
  const fallbackMethod = bodyWasProvided ? "content_analysis" : "subject_line_fallback";

  try {
    const raw = await client.generateJson(
      prompts.CONTENT_SENSITIVITY_SYSTEM,
      prompts.contentSensitivityUserPrompt(subject, body),
    );

    const parsed = ModelContentOutput.safeParse(raw);
    if (!parsed.success) {
      return await recordContent(evidenceId, [evidenceId], {
        method: null,
        sensitivity_flags: [],
        narrative: ENGINE_ERROR_NARRATIVE,
        confidence: "low",
        model: client.model,
        model_digest: null,
        generated_at: nowIso(),
        validation: "engine_error",
        error: `Model output did not match the required shape: ${parsed.error.issues
          .map((i) => `${i.path.join(".")}: ${i.message}`)
          .join("; ")}`,
        evidence_id: evidenceId,
      });
    }

    const output = parsed.data;
    // This path previously hardcoded "grounded" — the one tool that reads
    // real mailbox content had no validation at all.
    const validation = validateContentGrounding(
      output.sensitivity_flags,
      output.method,
      bodyWasProvided,
    );
    const rejected = isRejection(validation);

    return await recordContent(
      evidenceId,
      [evidenceId],
      {
        evidence_id: evidenceId,
        // No method is claimed for a result that was not accepted. Forcing
        // either literal asserts something false: content_analysis claims an
        // analysis whose narrative was withheld, and subject_line_fallback
        // restates the exact claim that was just rejected.
        method: rejected ? null : output.method,
        sensitivity_flags: rejected ? [] : output.sensitivity_flags,
        narrative: rejected ? REJECTED_NARRATIVE : output.narrative,
        confidence: rejected ? "low" : output.confidence,
        model: client.model,
        model_digest: await client.modelDigest(),
        generated_at: nowIso(),
        validation,
        error: null,
      },
      rejected ? output.narrative : undefined,
      output.method,
    );
  } catch (error) {
    return await recordContent(evidenceId, [evidenceId], {
      evidence_id: evidenceId,
      method: null,
      sensitivity_flags: [],
      narrative: ENGINE_ERROR_NARRATIVE,
      confidence: "low",
      model: client.model,
      model_digest: null,
      generated_at: nowIso(),
      validation: "engine_error",
      error: error instanceof OllamaUnavailableError ? error.message : String(error),
    });
  }
}

export async function getEngineHealth(
  client: OllamaClient = new OllamaClient(),
): Promise<EngineHealth> {
  const { reachable, models } = await client.isReachable();
  const recent = await readRecentValidations(settings.circuitBreakerWindow);
  const health = computeEngineHealth(
    recent,
    settings.circuitBreakerWindow,
    settings.circuitBreakerRejectionThreshold,
  );
  return {
    window_size: health.windowSize,
    calls_in_window: health.callsInWindow,
    rejected_in_window: health.rejectedInWindow,
    rejection_rate: health.rejectionRate,
    circuit_breaker_tripped: health.circuitBreakerTripped,
    ollama_reachable: reachable,
    available_models: models,
  };
}

async function record(
  kind: string,
  providedEvidenceIds: string[],
  result: AnalysisResult,
  withheldNarrative?: string,
  citedRefs?: string[],
): Promise<AnalysisResult> {
  // Never let an audit-write failure escape. record() is called from inside
  // the catch blocks too, so a throw here (unwritable path, full disk)
  // propagated straight out of the tool call — contradicting the contract
  // that every failure degrades to a result, not an exception.
  return safeAudit(result, {
    kind,
    model: result.model,
    model_digest: result.model_digest,
    validation: result.validation as ValidationStatus,
    provided_evidence_ids: providedEvidenceIds,
    cited_evidence_refs: citedRefs ?? result.evidence_refs,
    evidence_refs: result.evidence_refs,
    ...(withheldNarrative === undefined ? {} : { withheld_narrative: withheldNarrative }),
  });
}

async function recordContent(
  evidenceId: string,
  providedEvidenceIds: string[],
  result: ContentSensitivityResult,
  withheldNarrative?: string,
  claimedMethod?: string,
): Promise<ContentSensitivityResult> {
  return safeAudit(result, {
    kind: "content_sensitivity",
    model: result.model,
    model_digest: result.model_digest,
    validation: result.validation as ValidationStatus,
    provided_evidence_ids: providedEvidenceIds,
    cited_evidence_refs: claimedMethod === undefined ? [] : [`method:${claimedMethod}`],
    evidence_refs: [],
    ...(withheldNarrative === undefined ? {} : { withheld_narrative: withheldNarrative }),
  });
}

/** Writes the audit record, and degrades to an annotated result rather than
 *  throwing if the log cannot be written. */
async function safeAudit<T extends { error: string | null }>(
  result: T,
  record: Parameters<typeof appendAuditRecord>[0],
): Promise<T> {
  try {
    await appendAuditRecord(record);
  } catch (cause) {
    const note = `audit log write failed: ${String(cause)}`;
    return { ...result, error: result.error ? `${result.error}; ${note}` : note };
  }
  return result;
}
