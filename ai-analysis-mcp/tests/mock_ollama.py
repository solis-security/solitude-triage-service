"""A minimal local HTTP server that mimics just enough of Ollama's REST API
(/api/chat, /api/tags) to test our client and analysis code end-to-end
without a real Ollama installation. Response content is controlled by
special marker strings in the request's user message, so tests can drive
specific scenarios (happy path, hallucinated evidence, malformed JSON,
server error).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class MockOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default request logging
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            self._respond(200, {
                "models": [{"model": "llama3.1:latest", "digest": "sha256:abc123def456", "name": "llama3.1:latest"}]
            })
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._respond(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        user_msg = next((m["content"] for m in body.get("messages", []) if m["role"] == "user"), "")

        content = self._scripted_content(user_msg)
        self._respond(200, {
            "model": body.get("model", "llama3.1"),
            "created_at": "2026-08-14T00:00:00Z",
            "message": {"role": "assistant", "content": content},
            "done": True,
        })

    def _scripted_content(self, user_msg: str) -> str:
        if "TRIGGER_MALFORMED" in user_msg:
            return "this is not valid json {{{"
        if "TRIGGER_HALLUCINATE" in user_msg:
            return json.dumps({
                "narrative": "The account was compromised via a phished credential.",
                "confidence": "high",
                "evidence_refs": ["EV-DOES-NOT-EXIST"],
                "insufficient_evidence": False,
            })
        if "TRIGGER_NO_EVIDENCE" in user_msg:
            return json.dumps({
                "narrative": "This looks suspicious.",
                "confidence": "medium",
                "evidence_refs": [],
                "insufficient_evidence": False,
            })
        if "TRIGGER_INSUFFICIENT" in user_msg:
            return json.dumps({
                "narrative": "The evidence provided does not clearly indicate compromise.",
                "confidence": "low",
                "evidence_refs": [],
                "insufficient_evidence": True,
            })
        if "TRIGGER_SUBJECT_FALLBACK" in user_msg:
            return json.dumps({
                "method": "subject_line_fallback",
                "sensitivity_flags": ["invoice_or_payment_request"],
                "narrative": "Subject line suggests a payment-related request; body was not available for review.",
                "confidence": "low",
            })
        # default: well-formed, grounded response referencing whatever
        # evidence ids actually appear in the prompt (evidence ids are
        # conventionally prefixed "EV-" in this test suite; this avoids
        # accidentally also capturing a finding's own "id" field)
        import re
        ids = re.findall(r'"id":\s*"(EV-[^"]+)"', user_msg)
        return json.dumps({
            "narrative": "The sign-in pattern and mailbox rule together indicate the account was compromised and used to redirect financial correspondence.",
            "confidence": "high",
            "evidence_refs": ids,
            "insufficient_evidence": False,
        })

    def _respond(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MockOllamaServer:
    """Context manager: starts the mock server on a free local port in a
    background thread, yields its base URL."""

    def __init__(self):
        self._httpd = HTTPServer(("127.0.0.1", 0), MockOllamaHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        port = self._httpd.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
