/** Feeds a finding whose evidence carries injected instructions to the real
 *  model, to see whether the sanitiser and prompt guard actually hold. */
import { readFileSync } from "node:fs";
import { analyzeFinding } from "../dist/analysis.js";
import { FindingInput } from "../dist/schemas.js";
import { OllamaClient } from "../dist/ollama.js";

const path = process.env.FINDING_JSON!;
const f = FindingInput.parse(JSON.parse(readFileSync(path, "utf8")));
const r = await analyzeFinding(f, new OllamaClient());
console.log("  validation           :", r.validation);
console.log("  insufficient_evidence:", r.insufficient_evidence);
console.log("  confidence           :", r.confidence);
console.log("  evidence_refs        :", JSON.stringify(r.evidence_refs));
console.log("  narrative            :", r.narrative);
