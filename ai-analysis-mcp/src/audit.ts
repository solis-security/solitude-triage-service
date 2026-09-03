import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";

import { settings } from "./config.js";
import type { ValidationStatus } from "./validation.js";

export interface AuditRecord {
  kind: string;
  model: string;
  model_digest: string | null;
  validation: ValidationStatus;
  /** Ids the model was actually offered. Recorded so a grounding verdict can
   *  be re-checked from the log later — without it the audit trail cannot
   *  verify its own decisions. */
  provided_evidence_ids: string[];
  /** What the model actually cited, before any rejection cleared it. Storing
   *  the post-rejection (empty) list instead made the verdict impossible to
   *  re-check from the log — which is the whole point of recording it. */
  cited_evidence_refs: string[];
  /** What was returned to the caller: same as cited on success, empty on a
   *  rejection. */
  evidence_refs: string[];
  /** Set only on a rejection: the text that was withheld from the caller.
   *  Kept locally for debugging, never returned. */
  withheld_narrative?: string;
  at: string;
}

export async function appendAuditRecord(record: Omit<AuditRecord, "at">): Promise<void> {
  const line = JSON.stringify({ ...record, at: new Date().toISOString() });
  await mkdir(dirname(settings.auditLogPath), { recursive: true });
  await appendFile(settings.auditLogPath, `${line}\n`, "utf8");
}

export async function readRecentValidations(limit: number): Promise<ValidationStatus[]> {
  let contents: string;
  try {
    contents = await readFile(settings.auditLogPath, "utf8");
  } catch {
    return [];
  }
  const lines = contents.split("\n").filter((l) => l.trim().length > 0).slice(-limit);
  const out: ValidationStatus[] = [];
  for (const line of lines) {
    try {
      const parsed = JSON.parse(line) as { validation?: ValidationStatus };
      if (parsed.validation) out.push(parsed.validation);
    } catch {
      // A corrupt line must not take down health reporting.
    }
  }
  return out;
}
