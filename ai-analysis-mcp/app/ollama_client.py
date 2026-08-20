from __future__ import annotations

import json

import ollama

from app.config import settings


class OllamaUnavailableError(Exception):
    """Raised for any failure talking to Ollama, or a response that isn't
    parseable JSON. Callers must treat this as a safe-failure trigger, not
    let it propagate as a crash."""


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None, timeout: float | None = None):
        self.host = host or settings.ollama_host
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout_seconds
        self._client = ollama.Client(host=self.host, timeout=self.timeout)

    def generate_json(self, system: str, user: str) -> dict:
        """Call the model with a system+user prompt, forcing JSON output,
        and parse the result. Raises OllamaUnavailableError on any
        connection failure or non-JSON response — never lets a raw
        exception type from the ollama/http layer leak to callers."""
        try:
            resp = self._client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                format="json",
                options={"temperature": 0.1},
                stream=False,
            )
        except Exception as e:  # noqa: BLE001 — deliberately broad: any transport/client error becomes OllamaUnavailableError
            raise OllamaUnavailableError(f"Ollama request failed: {e}") from e

        content = resp.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise OllamaUnavailableError(f"Model did not return valid JSON: {e}. Raw: {content[:300]}") from e

    def model_digest(self) -> str | None:
        try:
            tags = self._client.list()
        except Exception:  # noqa: BLE001
            return None
        for m in tags.get("models", []):
            name = m.get("model") or m.get("name") or ""
            if name.split(":")[0] == self.model.split(":")[0]:
                digest = m.get("digest", "")
                return digest[:12] if digest else None
        return None

    def is_reachable(self) -> tuple[bool, list[str]]:
        try:
            tags = self._client.list()
            names = [m.get("model") or m.get("name") or "" for m in tags.get("models", [])]
            return True, names
        except Exception:  # noqa: BLE001
            return False, []
