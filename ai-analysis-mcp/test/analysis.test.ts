import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  analyzeEmailContent,
  analyzeFinding,
  getEngineHealth,
  summarizeCase,
} from "../dist/analysis.js";
import { settings } from "../dist/config.js";
import { OllamaClient } from "../dist/ollama.js";
import { MockOllamaServer } from "./mockOllama.ts";

const SAMPLE_FINDING = {
  id: "F-1006",
  rule: "impossible_travel",
  severity: "high" as const,
  area: "Authentication and sign-ins",
  text: "Sign-in from US then NG within 25 minutes.",
  evidence: [
    { id: "EV-3381", source: "Sign-in log", summary: "Successful sign-in from US at 10:00 UTC." },
    { id: "EV-3382", source: "Sign-in log", summary: "Successful sign-in from NG at 10:25 UTC." },
  ],
};

let server: MockOllamaServer;
let client: OllamaClient;

beforeEach(async () => {
  server = new MockOllamaServer();
  const url = await server.start();
  client = new OllamaClient({ host: url, model: "llama3.1" });
  const dir = await mkdtemp(join(tmpdir(), "solitude-audit-"));
  settings.auditLogPath = join(dir, "audit.jsonl");
});

afterEach(async () => {
  await server.stop();
});

async function auditRecords(): Promise<Array<Record<string, unknown>>> {
  const raw = await readFile(settings.auditLogPath, "utf8");
  return raw.split("\n").filter(Boolean).map((l) => JSON.parse(l) as Record<string, unknown>);
}

describe("analyzeFinding", () => {
  it("returns a grounded analysis on the happy path", async () => {
    const result = await analyzeFinding(SAMPLE_FINDING, client);
    assert.equal(result.validation, "grounded");
    assert.deepEqual(result.evidence_refs.sort(), ["EV-3381", "EV-3382"]);
    assert.equal(result.model_digest, "sha256:abc12");
    assert.equal(result.error, null);
  });

  it("WITHHOLDS the narrative of a hallucinated conclusion, not just its refs", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_HALLUCINATE this finding" };
    const result = await analyzeFinding(finding, client);

    assert.equal(result.validation, "rejected_ungrounded");
    assert.deepEqual(result.evidence_refs, []);
    // The regression that mattered: the model's claim must not reach the caller.
    assert.doesNotMatch(result.narrative, /phished credential/i);
    assert.match(result.narrative, /withheld/i);
    assert.equal(result.confidence, "low", "a rejected claim must not keep high confidence");
  });

  it("keeps the withheld text in the audit log for debugging", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_HALLUCINATE this finding" };
    await analyzeFinding(finding, client);
    const [record] = await auditRecords();
    assert.match(String(record!.withheld_narrative), /phished credential/i);
  });

  it("rejects a firm conclusion that cites no evidence", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_NO_EVIDENCE this finding" };
    const result = await analyzeFinding(finding, client);
    assert.equal(result.validation, "rejected_no_evidence");
    assert.doesNotMatch(result.narrative, /definitely compromised/i);
  });

  it("accepts an honest insufficient-evidence answer", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_INSUFFICIENT this finding" };
    const result = await analyzeFinding(finding, client);
    assert.equal(result.validation, "grounded");
    assert.equal(result.insufficient_evidence, true);
    assert.match(result.narrative, /does not support a firm conclusion/i);
  });

  it("degrades an out-of-vocabulary confidence to engine_error instead of throwing", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_BAD_CONFIDENCE this finding" };
    const result = await analyzeFinding(finding, client);
    assert.equal(result.validation, "engine_error");
    assert.match(String(result.error), /confidence/);
  });

  it("treats malformed model output as engine_error, not a crash", async () => {
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_MALFORMED this finding" };
    const result = await analyzeFinding(finding, client);
    assert.equal(result.validation, "engine_error");
    assert.notEqual(result.error, null);
  });

  it("treats an unreachable Ollama as engine_error, not a crash", async () => {
    const dead = new OllamaClient({ host: "http://127.0.0.1:1", model: "llama3.1", timeoutSeconds: 1 });
    const result = await analyzeFinding(SAMPLE_FINDING, dead);
    assert.equal(result.validation, "engine_error");
    assert.notEqual(result.error, null);
  });

  it("records the evidence ids the model was offered, so a verdict can be re-checked", async () => {
    await analyzeFinding(SAMPLE_FINDING, client);
    const [record] = await auditRecords();
    assert.deepEqual(record!.provided_evidence_ids, ["EV-3381", "EV-3382"]);
  });
});

describe("summarizeCase", () => {
  it("summarises and carries the finding counts", async () => {
    const result = await summarizeCase([SAMPLE_FINDING], client);
    assert.equal(result.validation, "grounded");
    assert.equal(result.finding_count, 1);
    assert.equal(result.high_severity_count, 1);
  });
});

describe("summarizeCase grounding set", () => {
  it("accepts a finding id as a citation, since the prompt supplies findings", async () => {
    const result = await summarizeCase(
      [{ ...SAMPLE_FINDING, text: "TRIGGER_CITE_FINDING_ID here" }], client,
    );
    assert.equal(result.validation, "grounded");
    // The finding id is citable, but it is a finding reference, not an
    // evidence reference — a renderer resolving evidence_refs against the
    // evidence set must not be handed an id that isn't in it.
    assert.deepEqual(result.finding_refs, ["F-1006"]);
    assert.ok(!result.evidence_refs.includes("F-1006"));
    assert.ok(result.evidence_refs.includes("EV-3381"));
    assert.match(result.narrative, /impossible travel/i);
  });

  it("still rejects an id that was never supplied", async () => {
    const result = await summarizeCase(
      [{ ...SAMPLE_FINDING, text: "TRIGGER_INVENTED_ID here" }], client,
    );
    assert.equal(result.validation, "rejected_ungrounded");
    assert.doesNotMatch(result.narrative, /A confident summary/);
  });
});

describe("analyzeEmailContent", () => {
  it("accepts a subject-line-only assessment when no body was given", async () => {
    const result = await analyzeEmailContent(
      "EV-9001", "TRIGGER_SUBJECT_FALLBACK Updated banking details", null, client,
    );
    assert.equal(result.method, "subject_line_fallback");
    assert.equal(result.validation, "grounded");
    assert.ok(result.sensitivity_flags.includes("invoice_or_payment_request"));
  });

  it("REJECTS a content_analysis claim when no body was ever supplied", async () => {
    // Previously this path hardcoded validation="grounded" and could not
    // reject anything at all.
    const result = await analyzeEmailContent(
      "EV-9002", "TRIGGER_FALSE_CONTENT_CLAIM Invoice", null, client,
    );
    assert.equal(result.validation, "rejected_ungrounded");
    assert.doesNotMatch(result.narrative, /full bank account details/i);
    assert.deepEqual(result.sensitivity_flags, []);
  });

  it("claims no method at all on a rejected assessment", async () => {
    // Either literal would assert something false here: content_analysis
    // claims an analysis whose narrative was withheld, and
    // subject_line_fallback restates the claim that was just rejected.
    const result = await analyzeEmailContent(
      "EV-9005", "TRIGGER_FALSE_CONTENT_CLAIM x", null, client,
    );
    assert.equal(result.validation, "rejected_ungrounded");
    assert.equal(result.method, null);
  });

  it("treats an invented flag as ungrounded, not as an engine outage", async () => {
    // Validating the vocabulary in the schema made safeParse reject first,
    // so a model inventing categories was logged as engine_error and pointed
    // the operator at Ollama instead of at the model.
    const result = await analyzeEmailContent(
      "EV-9003", "TRIGGER_BAD_FLAG Something", null, client,
    );
    assert.equal(result.validation, "rejected_ungrounded");
    assert.deepEqual(result.sensitivity_flags, []);
  });

  it("writes content calls to the audit log so they reach the breaker", async () => {
    await analyzeEmailContent("EV-9004", "TRIGGER_FALSE_CONTENT_CLAIM x", null, client);
    const [record] = await auditRecords();
    assert.equal(record!.kind, "content_sensitivity");
    assert.equal(record!.validation, "rejected_ungrounded");
  });
});

describe("audit log is re-verifiable", () => {
  it("records the full set the verdict was actually judged against", async () => {
    // The audit trail exists so a verdict can be re-checked later. If the
    // recorded 'offered' set is narrower than what validation actually
    // allowed, a reviewer re-running the check reaches the opposite
    // conclusion — which is worse than not logging it at all.
    const finding = { ...SAMPLE_FINDING, text: "TRIGGER_CITE_FINDING_ID here" };
    const result = await summarizeCase([finding], client);
    assert.equal(result.validation, "grounded");

    const [record] = await auditRecords();
    const offered = new Set(record!.provided_evidence_ids as string[]);
    const cited = record!.cited_evidence_refs as string[];
    const reverified = cited.every((id) => offered.has(id));
    assert.equal(
      reverified, true,
      `log says offered=${JSON.stringify([...offered])} cited=${JSON.stringify(cited)}, ` +
      "so re-checking the log rejects what the engine accepted",
    );
  });
});

describe("failures never escape as exceptions", () => {
  it("degrades an unwritable audit log into result.error instead of throwing", async () => {
    // record() is called from inside the catch blocks too, so a throw here
    // propagated straight out of the tool call.
    settings.auditLogPath = "/proc/nonexistent-dir/audit.jsonl";
    const result = await analyzeFinding(SAMPLE_FINDING, client);
    assert.ok(result, "the call must still return a result");
    assert.match(String(result.error), /audit log write failed/i);
  });

  it("reports an HTTP-error Ollama as unreachable rather than healthy", async () => {
    // Must be a real non-2xx response, not a connection failure: a refused
    // connection is caught by the transport handler and never reaches the
    // response.ok guard, so that version of this test stayed green even with
    // the guard deleted.
    const failing = new MockOllamaServer({ status: 502 });
    const url = await failing.start();
    try {
      const broken = new OllamaClient({ host: url, model: "llama3.1", timeoutSeconds: 5 });
      const health = await getEngineHealth(broken);
      assert.equal(health.ollama_reachable, false);
    } finally {
      await failing.stop();
    }
  });
});

describe("getEngineHealth", () => {
  it("reflects real rejection history from the audit log", async () => {
    await analyzeFinding(SAMPLE_FINDING, client);
    await analyzeFinding(SAMPLE_FINDING, client);
    await analyzeFinding(SAMPLE_FINDING, client);
    await analyzeFinding({ ...SAMPLE_FINDING, text: "TRIGGER_NO_EVIDENCE x" }, client);
    await analyzeFinding({ ...SAMPLE_FINDING, text: "TRIGGER_HALLUCINATE x" }, client);

    const health = await getEngineHealth(client);
    assert.equal(health.ollama_reachable, true);
    assert.equal(health.calls_in_window, 5);
    assert.equal(health.rejected_in_window, 2);
  });
});
