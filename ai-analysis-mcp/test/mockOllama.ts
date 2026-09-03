import { createServer, type Server } from "node:http";

/**
 * Emulates just enough of Ollama's REST API (/api/chat, /api/tags) to drive
 * the client and analysis code end-to-end without a real Ollama install.
 * Responses are scripted by marker strings in the user message.
 */
export const MOCK_DIGEST = "sha256:abc123def456";

function scriptedContent(userMessage: string): string {
  if (userMessage.includes("TRIGGER_MALFORMED")) return "this is not valid json {{{";

  if (userMessage.includes("TRIGGER_HALLUCINATE")) {
    return JSON.stringify({
      narrative: "The account was compromised via a phished credential.",
      confidence: "high",
      evidence_refs: ["EV-9999-DOES-NOT-EXIST"],
      insufficient_evidence: false,
    });
  }

  if (userMessage.includes("TRIGGER_NO_EVIDENCE")) {
    return JSON.stringify({
      narrative: "This account is definitely compromised.",
      confidence: "high",
      evidence_refs: [],
      insufficient_evidence: false,
    });
  }

  if (userMessage.includes("TRIGGER_INSUFFICIENT")) {
    return JSON.stringify({
      narrative: "The evidence provided does not support a firm conclusion.",
      confidence: "low",
      evidence_refs: [],
      insufficient_evidence: true,
    });
  }

  if (userMessage.includes("TRIGGER_CITE_FINDING_ID")) {
    // A real model does this: it cites the finding id alongside the evidence,
    // because the case-summary prompt hands it whole findings.
    return JSON.stringify({
      narrative: "One account shows impossible travel and a suspicious mail rule.",
      confidence: "medium",
      evidence_refs: ["F-1006", "EV-3381"],
      insufficient_evidence: false,
    });
  }

  if (userMessage.includes("TRIGGER_INVENTED_ID")) {
    return JSON.stringify({
      narrative: "A confident summary.",
      confidence: "high",
      evidence_refs: ["F-9999-NOT-REAL"],
      insufficient_evidence: false,
    });
  }

  if (userMessage.includes("TRIGGER_BAD_CONFIDENCE")) {
    return JSON.stringify({
      narrative: "A grounded narrative.",
      confidence: "very high",
      evidence_refs: ["EV-3381"],
      insufficient_evidence: false,
    });
  }

  if (userMessage.includes("TRIGGER_FALSE_CONTENT_CLAIM")) {
    return JSON.stringify({
      method: "content_analysis",
      sensitivity_flags: ["financial_banking_details"],
      narrative: "The message body contains full bank account details.",
      confidence: "high",
    });
  }

  if (userMessage.includes("TRIGGER_BAD_FLAG")) {
    return JSON.stringify({
      method: "subject_line_fallback",
      sensitivity_flags: ["nuclear_launch_codes"],
      narrative: "Subject line only.",
      confidence: "low",
    });
  }

  if (userMessage.includes("TRIGGER_SUBJECT_FALLBACK")) {
    return JSON.stringify({
      method: "subject_line_fallback",
      sensitivity_flags: ["invoice_or_payment_request"],
      narrative: "Subject line only; suggests a payment request. Limited assessment.",
      confidence: "low",
    });
  }

  if (userMessage.includes("Subject:")) {
    return JSON.stringify({
      method: "content_analysis",
      sensitivity_flags: ["invoice_or_payment_request"],
      narrative: "The body discusses an invoice payment.",
      confidence: "medium",
    });
  }

  return JSON.stringify({
    narrative: "Two sign-ins minutes apart from different countries indicate session theft.",
    confidence: "high",
    evidence_refs: ["EV-3381", "EV-3382"],
    insufficient_evidence: false,
  });
}

export interface MockOllamaOptions {
  /** Respond to every request with this HTTP status and a JSON error body,
   *  so the client's response.ok handling can be exercised. */
  status?: number;
}

export class MockOllamaServer {
  private server: Server | undefined;
  private readonly options: MockOllamaOptions;
  url = "";

  constructor(options: MockOllamaOptions = {}) {
    this.options = options;
  }

  async start(): Promise<string> {
    this.server = createServer((req, res) => {
      if (this.options.status !== undefined) {
        res.writeHead(this.options.status, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "upstream failure" }));
        return;
      }
      if (req.method === "GET" && req.url === "/api/tags") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({
          models: [{ model: "llama3.1:latest", name: "llama3.1:latest", digest: MOCK_DIGEST }],
        }));
        return;
      }
      if (req.method === "POST" && req.url === "/api/chat") {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", () => {
          const body = JSON.parse(raw || "{}") as { messages?: Array<{ role: string; content: string }> };
          const user = body.messages?.find((m) => m.role === "user")?.content ?? "";
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({
            model: "llama3.1",
            created_at: "2026-08-20T00:00:00Z",
            message: { role: "assistant", content: scriptedContent(user) },
            done: true,
          }));
        });
        return;
      }
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });

    await new Promise<void>((done) => this.server!.listen(0, "127.0.0.1", done));
    const address = this.server!.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    this.url = `http://127.0.0.1:${address.port}`;
    return this.url;
  }

  async stop(): Promise<void> {
    if (this.server) await new Promise<void>((done) => this.server!.close(() => done()));
  }
}
