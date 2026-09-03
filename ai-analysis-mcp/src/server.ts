#!/usr/bin/env node
/**
 * Solitude AI Analysis MCP server.
 *
 * Exposes the TDD's AI-Assisted Analysis Engine (Section 4.4) as MCP tools,
 * backed by a local Ollama model rather than a hosted API — investigation
 * content never leaves the machine to get an AI-assisted read on it.
 *
 * Every analysis tool enforces evidence grounding, and a conclusion that
 * fails validation is withheld rather than returned with a caveat attached.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { analyzeEmailContent, analyzeFinding, getEngineHealth, summarizeCase } from "./analysis.js";
import { EvidenceItem, FindingInput, Severity } from "./schemas.js";

const server = new McpServer({ name: "solitude-ai-analysis", version: "0.2.0" });

function asJson(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

server.registerTool(
  "analyze_finding",
  {
    title: "Analyze finding",
    description:
      "Evidence-grounded AI analysis of a single investigation finding. Only the evidence " +
      "ids supplied here may appear in the response's evidence_refs; a conclusion citing " +
      "anything else is rejected and its narrative withheld.",
    inputSchema: {
      finding_id: z.string().describe('The finding id, e.g. "F-1006".'),
      rule: z.string().describe('The rule that produced it, e.g. "impossible_travel".'),
      severity: Severity,
      area: z.string().describe('Investigation area, e.g. "Authentication and sign-ins".'),
      text: z.string().describe("The rule-generated description of the finding."),
      evidence: z.array(EvidenceItem).describe("Evidence records supporting the finding."),
    },
  },
  async ({ finding_id, rule, severity, area, text, evidence }) => {
    const finding = FindingInput.parse({ id: finding_id, rule, severity, area, text, evidence });
    return asJson({ finding_id, ...(await analyzeFinding(finding)) });
  },
);

server.registerTool(
  "summarize_case",
  {
    title: "Summarize case",
    description:
      "Evidence-grounded executive summary across every finding in a case, written for a " +
      "non-technical stakeholder.",
    inputSchema: {
      findings: z.array(FindingInput).describe("All findings in the case."),
    },
  },
  async ({ findings }) => asJson(await summarizeCase(findings)),
);

server.registerTool(
  "analyze_email_content",
  {
    title: "Analyze email content",
    description:
      "Assess whether an email's content indicates sensitive data exposure. Falls back to " +
      "a subject-line-only assessment, explicitly flagged as such, when no body is available.",
    inputSchema: {
      evidence_id: z.string().describe("The evidence id this message corresponds to."),
      subject: z.string().describe("The message subject line."),
      body: z.string().nullish().describe("The message body, if accessible."),
    },
  },
  async ({ evidence_id, subject, body }) =>
    asJson(await analyzeEmailContent(evidence_id, subject, body ?? null)),
);

server.registerTool(
  "get_ai_engine_health",
  {
    title: "Get AI engine health",
    description:
      "Ollama reachability, locally available models, and whether the rejection-rate " +
      "circuit breaker has tripped. While it is tripped, AI findings must not be " +
      "auto-included in reports.",
    inputSchema: {},
  },
  async () => asJson(await getEngineHealth()),
);

const transport = new StdioServerTransport();
await server.connect(transport);
