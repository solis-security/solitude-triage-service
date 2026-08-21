import { homedir } from "node:os";
import { join, resolve } from "node:path";

/** Treats an empty or whitespace-only variable as absent. `??` does not:
 *  an empty value is not nullish, so `AI_AUDIT_LOG_PATH=` (which
 *  .env.example ships) resolved to the process working directory, and an
 *  empty timeout became Number("") === 0 — aborting every request. */
function str(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

/** For quantities where zero is meaningless (a timeout, a window size). */
function positive(value: string | undefined, fallback: number): number {
  const trimmed = value?.trim();
  if (!trimmed) return fallback;
  const n = Number(trimmed);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/** For a fraction, where 0 is a legitimate setting — "trip on any
 *  rejection". Rejecting it silently replaced the strictest configuration
 *  available with the laxer default. */
function fraction(value: string | undefined, fallback: number): number {
  const trimmed = value?.trim();
  if (!trimmed) return fallback;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : fallback;
}

export const settings = {
  ollamaHost: str(process.env.AI_OLLAMA_HOST, "http://localhost:11434"),
  ollamaModel: str(process.env.AI_OLLAMA_MODEL, "llama3.1"),
  ollamaTimeoutSeconds: positive(process.env.AI_OLLAMA_TIMEOUT_SECONDS, 60),

  // If the rejection rate over the last N calls exceeds this fraction, the
  // engine reports its breaker as tripped and callers must stop
  // auto-including AI findings in reports until it clears.
  circuitBreakerWindow: positive(process.env.AI_CIRCUIT_BREAKER_WINDOW, 20),
  circuitBreakerRejectionThreshold: fraction(process.env.AI_CIRCUIT_BREAKER_REJECTION_THRESHOLD, 0.3),

  // Resolved absolutely. MCP clients choose the working directory, so a
  // relative path meant the audit trail landed wherever the client happened
  // to be started from — which is not an audit trail.
  auditLogPath: resolve(
    str(process.env.AI_AUDIT_LOG_PATH, join(homedir(), ".solitude", "ai-audit.jsonl")),
  ),
};

export type Settings = typeof settings;
