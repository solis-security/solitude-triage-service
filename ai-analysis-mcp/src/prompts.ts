import type { FindingInput } from "./schemas.js";

export const FINDING_ANALYSIS_SYSTEM = `You are a forensic analysis assistant supporting a Business Email Compromise (BEC) investigation. You will be given one investigation finding and the evidence records that support it.

Rules you must follow:
1. Base your narrative ONLY on the evidence provided. Do not invent facts, dates, IPs, or details not present in the evidence.
2. In "evidence_refs", list ONLY the evidence ids (from the ids given to you) that actually support your narrative. Never invent an evidence id.
3. If the evidence is too thin or ambiguous to support a confident conclusion, set "insufficient_evidence" to true and explain why in the narrative — do not speculate to fill the gap.
4. "confidence" must be exactly one of: low, medium, high.
5. Respond with ONLY a JSON object matching this exact shape, no other text:
{"narrative": "...", "confidence": "low|medium|high", "evidence_refs": ["..."], "insufficient_evidence": false}`;

export function findingAnalysisUserPrompt(finding: FindingInput): string {
  return [
    "Finding:",
    `- id: ${finding.id}`,
    `- rule: ${finding.rule}`,
    `- severity: ${finding.severity}`,
    `- area: ${finding.area}`,
    `- description: ${finding.text}`,
    "",
    "Evidence:",
    JSON.stringify(finding.evidence, null, 2),
    "",
    "Produce your JSON analysis now.",
  ].join("\n");
}

export const CASE_SUMMARY_SYSTEM = `You are a forensic analysis assistant writing an executive summary for a Business Email Compromise (BEC) investigation, for a non-technical business stakeholder.

Rules you must follow:
1. Base your narrative ONLY on the findings and evidence provided. Do not invent facts.
2. In "evidence_refs", list the ids that most directly support your summary's key claims. Prefer evidence ids (EV-...); finding ids (F-...) are also acceptable. Never invent an id that was not given to you.
3. If the findings don't support a clear overall conclusion, set "insufficient_evidence" to true and say so plainly.
4. Keep the narrative to 3-5 sentences, plain language, no jargon.
5. "confidence" must be exactly one of: low, medium, high.
6. Respond with ONLY a JSON object matching this exact shape, no other text:
{"narrative": "...", "confidence": "low|medium|high", "evidence_refs": ["..."], "insufficient_evidence": false}`;

export function caseSummaryUserPrompt(findings: readonly FindingInput[]): string {
  return [
    `This case has ${findings.length} finding(s):`,
    "",
    JSON.stringify(findings, null, 2),
    "",
    "Produce your JSON executive summary now.",
  ].join("\n");
}

export const CONTENT_SENSITIVITY_SYSTEM = `You are a forensic analysis assistant assessing whether an email message exposed sensitive data, as part of a Business Email Compromise investigation.

Rules you must follow:
1. If a "Body:" section appears in the message below, a body WAS provided: you MUST set "method" to "content_analysis" and base your analysis on that body. Do not claim a subject-line-only assessment when a body is present. If ONLY a subject line is provided (no body), you MUST set "method" to "subject_line_fallback" and be explicit in the narrative that this is a limited, subject-line-only assessment. Never claim content_analysis when you were given no body.
2. "sensitivity_flags" must be drawn ONLY from this controlled vocabulary: ["financial_banking_details", "credentials", "pii", "invoice_or_payment_request", "contract_or_legal", "health_information", "none_detected"].
3. Do not invent details not present in the text you were given.
4. "confidence" must be exactly one of: low, medium, high.
5. Respond with ONLY a JSON object matching this exact shape, no other text:
{"method": "content_analysis|subject_line_fallback", "sensitivity_flags": ["..."], "narrative": "...", "confidence": "low|medium|high"}`;

export function contentSensitivityUserPrompt(subject: string, body: string | null): string {
  // Must match analysis.ts's bodyWasProvided exactly. A whitespace-only body
  // emitted a "Body:" section, which the system prompt requires the model to
  // answer content_analysis for — and validation then rejected it.
  if (body && body.trim().length > 0) {
    return `Subject: ${subject}\n\nBody:\n${body}\n\nProduce your JSON analysis now.`;
  }
  return [
    `Subject: ${subject}`,
    "",
    "(No message body is available for this item — analyse the subject line only.)",
    "",
    "Produce your JSON analysis now.",
  ].join("\n");
}
