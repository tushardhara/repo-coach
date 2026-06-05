"""
Ollama client for RepoCoach v2.
Default model: qwen2.5-coder:1.5b (configured via REPO_COACH_MODEL env var)
"""
import json
import os
import urllib.request
import urllib.error
from typing import Iterator, List, Optional


OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("REPO_COACH_MODEL", "qwen2.5-coder:1.5b")


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        top_p: float = 0.8,
    ):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p

    def chat(self, messages: List[dict], stream: bool = False) -> str:
        """
        POST /api/chat with messages=[{role, content}].
        Returns the assistant response content string.
        Non-streaming only (stream=False).
        Raises OllamaError on HTTP error or connection refused.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "num_predict": 2048,
            },
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
                return body["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise OllamaError(f"HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            if "refused" in reason.lower() or "connection" in reason.lower():
                raise OllamaError(f"Ollama not running at {OLLAMA_BASE}") from e
            raise OllamaError(f"URLError: {reason}") from e

    def generate(self, prompt: str) -> str:
        """
        POST /api/generate. Returns response string.
        Wraps prompt as user message and calls chat().
        """
        return self.chat([{"role": "user", "content": prompt}])

    def is_available(self) -> bool:
        """GET /api/tags — returns True if Ollama is running."""
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """GET /api/tags — return list of available model names."""
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                return [m["name"] for m in body.get("models", [])]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise OllamaError(f"HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            if "refused" in reason.lower() or "connection" in reason.lower():
                raise OllamaError(f"Ollama not running at {OLLAMA_BASE}") from e
            raise OllamaError(f"URLError: {reason}") from e
