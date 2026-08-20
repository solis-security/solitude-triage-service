/**
 * Exercises all four tools against a REAL Ollama instance. The unit suite
 * runs entirely against a mock, so this is the only thing that proves the
 * real model's JSON mode, error shapes and vocabulary adherence.
 *
 *   node --test-force-exit dist-scripts/live-check.js
 */
import { analyzeEmailContent, analyzeFinding, getEngineHealth, summarizeCase } from "../dist/analysis.js";
import { OllamaClient } from "../dist/ollama.js";

const client = new OllamaClient();

const FINDING = {
  id: "F-1006",
  rule: "impossible_travel",
  severity: "high" as const,
  area: "Authentication and sign-ins",
  text: "d.farrow: sign-in from US then NG within 0.4h — implies ~11000 km/h travel.",
  evidence: [
    { id: "EV-3381", source: "Sign-in log", summary: "Successful sign-in from US (Browser) at 10:00 UTC." },
    { id: "EV-3382", source: "Sign-in log", summary: "Successful sign-in from NG (Browser), Entra risk high, at 10:25 UTC." },
  ],
};

function line(label: string, value: unknown) {
  console.log(`  ${label.padEnd(20)} ${typeof value === "string" ? value : JSON.stringify(value)}`);
}

const health = await getEngineHealth(client);
console.log("== get_ai_engine_health ==");
line("reachable", health.ollama_reachable);
line("models", health.available_models);
line("breaker tripped", health.circuit_breaker_tripped);

console.log("\n== analyze_finding (grounded path) ==");
const a = await analyzeFinding(FINDING, client);
line("validation", a.validation);
line("confidence", a.confidence);
line("evidence_refs", a.evidence_refs);
line("model_digest", a.model_digest);
line("narrative", `${a.narrative.slice(0, 150)}...`);

console.log("\n== analyze_finding (hallucination pressure) ==");
// Evidence deliberately too thin to support the claim in the text.
const thin = {
  ...FINDING,
  id: "F-2001",
  text: "d.farrow's mailbox was exfiltrated in full and forwarded to a criminal group.",
  evidence: [{ id: "EV-7001", source: "Sign-in log", summary: "One successful sign-in from US at 09:00 UTC." }],
};
const b = await analyzeFinding(thin, client);
line("validation", b.validation);
line("insufficient", b.insufficient_evidence);
line("evidence_refs", b.evidence_refs);
line("narrative", `${b.narrative.slice(0, 150)}...`);

console.log("\n== summarize_case ==");
const c = await summarizeCase([FINDING], client);
line("validation", c.validation);
line("finding_count", c.finding_count);
line("narrative", `${c.narrative.slice(0, 180)}...`);

console.log("\n== analyze_email_content (no body -> must self-declare fallback) ==");
const d = await analyzeEmailContent("EV-9001", "URGENT: updated bank details for invoice 4471", null, client);
line("method", d.method);
line("validation", d.validation);
line("flags", d.sensitivity_flags);
line("narrative", `${d.narrative.slice(0, 150)}...`);

console.log("\n== analyze_email_content (with body) ==");
const e = await analyzeEmailContent(
  "EV-9002",
  "Invoice 4471",
  "Please remit payment to our new account, sort code 04-00-72, account 11223344.",
  client,
);
line("method", e.method);
line("validation", e.validation);
line("flags", e.sensitivity_flags);

const final = await getEngineHealth(client);
console.log("\n== breaker after run ==");
line("calls", final.calls_in_window);
line("rejected", final.rejected_in_window);
line("rate", final.rejection_rate.toFixed(2));
line("tripped", final.circuit_breaker_tripped);
