/**
 * End-to-end: real triage findings -> hydrated evidence -> real Ollama.
 * Proves the Phase 2.1 bridge: the analysis engine can now be driven from a
 * case id rather than hand-assembled tool arguments.
 */
import { analyzeFinding, summarizeCase } from "../dist/analysis.js";
import { FindingInput } from "../dist/schemas.js";
import { OllamaClient } from "../dist/ollama.js";

const API = process.env.TRIAGE_API ?? "http://127.0.0.1:8099";
const CASE = process.env.CASE_ID ?? "SR-2026-0501";

const res = await fetch(`${API}/triage/${CASE}/analysis-input?tenant_domain=contoso.onmicrosoft.com`);
if (!res.ok) {
  // Without this the FastAPI error body ({"detail": ...}) surfaces as
  // "raw.map is not a function" instead of the actual status.
  throw new Error(`${API} returned HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
}
const body = (await res.json()) as { findings: unknown[]; limitations: string[] };

// The service's output must satisfy the MCP's own schema with no massaging.
const findings = body.findings.map((f) => FindingInput.parse(f));
console.log(`Fetched ${findings.length} findings from ${API}; all parsed against FindingInput.`);
for (const l of body.limitations) console.log(`  limitation: ${l}`);
if (findings.length === 0) {
  console.log("No findings for this case — nothing to analyse.");
  process.exit(0);
}
console.log();

const client = new OllamaClient();

const target = findings.find((f) => f.rule === "impossible_travel") ?? findings[0];
if (!target) throw new Error("unreachable: findings is non-empty");
console.log(`== analyze_finding: ${target.id} (${target.rule}) ==`);
const a = await analyzeFinding(target, client);
console.log(`  validation   : ${a.validation}`);
console.log(`  confidence   : ${a.confidence}`);
console.log(`  evidence_refs: ${JSON.stringify(a.evidence_refs)}`);
console.log(`  offered ids  : ${JSON.stringify(target.evidence.map((e) => e.id))}`);
console.log(`  narrative    : ${a.narrative.slice(0, 220)}\n`);

console.log(`== summarize_case: all ${findings.length} findings ==`);
const c = await summarizeCase(findings, client);
console.log(`  validation    : ${c.validation}`);
console.log(`  finding_count : ${c.finding_count} (high: ${c.high_severity_count})`);
console.log(`  evidence_refs : ${JSON.stringify(c.evidence_refs)}`);
console.log(`  finding_refs  : ${JSON.stringify(c.finding_refs)}`);
console.log(`  narrative     : ${c.narrative.slice(0, 400)}`);
