import { settings } from "./config.js";

/** Every failure talking to Ollama, and every unparseable response, becomes
 *  this one error type. Callers treat it as a safe-failure trigger; no raw
 *  transport error is ever allowed to escape as a crash. */
export class OllamaUnavailableError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "OllamaUnavailableError";
  }
}

export interface OllamaClientOptions {
  host?: string;
  model?: string;
  timeoutSeconds?: number;
}

interface TagsResponse {
  models?: Array<{ model?: string; name?: string; digest?: string }>;
}

export class OllamaClient {
  readonly host: string;
  readonly model: string;
  readonly timeoutSeconds: number;
  /** Cached: the digest is a property of the loaded model, so re-fetching it
   *  on every analysis added a second HTTP round trip per call. */
  private digestCache: string | null | undefined;

  constructor(options: OllamaClientOptions = {}) {
    this.host = (options.host ?? settings.ollamaHost).replace(/\/+$/, "");
    this.model = options.model ?? settings.ollamaModel;
    this.timeoutSeconds = options.timeoutSeconds ?? settings.ollamaTimeoutSeconds;
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    const signal = AbortSignal.timeout(this.timeoutSeconds * 1000);
    let response: Response;
    try {
      response = await fetch(`${this.host}${path}`, { ...init, signal });
    } catch (cause) {
      throw new OllamaUnavailableError(`Ollama request failed: ${String(cause)}`, { cause });
    }
    // Checked here rather than only in generateJson: a proxy or a failing
    // Ollama returning 502 with a JSON body parsed cleanly, so isReachable
    // reported a healthy engine while every analysis failed.
    if (!response.ok) {
      throw new OllamaUnavailableError(`Ollama returned HTTP ${response.status}`);
    }
    return response;
  }

  /** Call the model forcing JSON output and return the parsed object. */
  async generateJson(system: string, user: string): Promise<unknown> {
    const response = await this.request("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model: this.model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        format: "json",
        options: { temperature: 0.1 },
        stream: false,
      }),
    });

    let envelope: { message?: { content?: string } };
    try {
      envelope = (await response.json()) as typeof envelope;
    } catch (cause) {
      throw new OllamaUnavailableError("Ollama response was not JSON", { cause });
    }

    const content = envelope.message?.content ?? "";
    try {
      return JSON.parse(content) as unknown;
    } catch (cause) {
      throw new OllamaUnavailableError(
        `Model did not return valid JSON. Raw: ${content.slice(0, 300)}`,
        { cause },
      );
    }
  }

  async modelDigest(): Promise<string | null> {
    if (this.digestCache !== undefined) return this.digestCache;
    try {
      const response = await this.request("/api/tags");
      const tags = (await response.json()) as TagsResponse;
      const base = this.model.split(":")[0];
      for (const entry of tags.models ?? []) {
        const name = entry.model ?? entry.name ?? "";
        if (name.split(":")[0] === base) {
          this.digestCache = entry.digest ? entry.digest.slice(0, 12) : null;
          return this.digestCache;
        }
      }
      this.digestCache = null;
    } catch {
      // Not fatal: a missing digest degrades the audit record, it does not
      // invalidate the analysis. Left uncached so a later call can recover it.
      return null;
    }
    return this.digestCache;
  }

  async isReachable(): Promise<{ reachable: boolean; models: string[] }> {
    try {
      const response = await this.request("/api/tags");
      const tags = (await response.json()) as TagsResponse;
      const models = (tags.models ?? []).map((m) => m.model ?? m.name ?? "").filter(Boolean);
      return { reachable: true, models };
    } catch {
      return { reachable: false, models: [] };
    }
  }
}
