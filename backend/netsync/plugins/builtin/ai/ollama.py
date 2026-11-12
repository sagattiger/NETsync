"""Minimal async client for the Ollama HTTP API (also works behind Open WebUI-style proxies with a key)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class OllamaError(Exception):
    pass


def _client(cfg: dict[str, Any], timeout: float) -> httpx.AsyncClient:
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise OllamaError("Ollama URL is not configured")
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    return httpx.AsyncClient(base_url=base, headers=headers, timeout=timeout)


async def list_models(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        async with _client(cfg, 10) as c:
            r = await c.get("/api/tags")
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise OllamaError(f"Cannot reach Ollama at {cfg.get('base_url')}: {e}") from e
    return [
        {"name": m["name"], "size": m.get("size"), "family": (m.get("details") or {}).get("family"),
         "parameters": (m.get("details") or {}).get("parameter_size")}
        for m in r.json().get("models", [])
    ]


async def chat(cfg: dict[str, Any], system: str, user: str) -> str:
    if not cfg.get("model"):
        raise OllamaError("No model selected in the AI assistant settings")
    payload = {
        "model": cfg["model"],
        "stream": False,
        "keep_alive": "10m",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": float(cfg.get("temperature", 0.2)), "num_ctx": int(cfg.get("num_ctx", 8192))},
    }
    try:
        async with _client(cfg, float(cfg.get("timeout_seconds", 180))) as c:
            r = await c.post("/api/chat", json=payload)
    except httpx.TimeoutException as e:
        raise OllamaError(f"Ollama did not answer within {cfg.get('timeout_seconds', 180)} s") from e
    except httpx.HTTPError as e:
        raise OllamaError(f"Cannot reach Ollama: {e}") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", r.text)
        except ValueError:
            detail = r.text
        raise OllamaError(f"Ollama error {r.status_code}: {detail[:300]}")
    content = (r.json().get("message") or {}).get("content", "").strip()
    if cfg.get("hide_thinking", True):
        content = THINK.sub("", content).strip()  # reasoning models (deepseek-r1, qwen3...)
    if not content:
        raise OllamaError("The model returned an empty answer")
    return content


async def chat_stream(cfg: dict[str, Any], messages: list[dict], tools: list[dict] | None = None,
                      model: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Stream /api/chat chunks ({"message": {"content", "tool_calls"}, "done": bool}).

    ``think`` is switched off for reasoning models (faster, and their reasoning must not reach the user); models
    that don't know the option are retried without it."""
    model = model or cfg.get("model")
    if not model:
        raise OllamaError("No model selected in the AI assistant settings")
    payload: dict[str, Any] = {
        "model": model, "stream": True, "keep_alive": "10m", "messages": messages,
        "options": {"temperature": float(cfg.get("temperature", 0.2)), "num_ctx": int(cfg.get("num_ctx", 8192))},
    }
    if tools:
        payload["tools"] = tools
    timeout = float(cfg.get("timeout_seconds", 180))
    for think in (False, None):
        body = {**payload, "think": think} if think is not None else payload
        try:
            async with _client(cfg, timeout) as c, c.stream("POST", "/api/chat", json=body) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode(errors="replace")
                    try:
                        detail = json.loads(detail).get("error", detail)
                    except ValueError:
                        pass
                    if think is not None and "think" in detail.lower():
                        continue
                    raise OllamaError(f"Ollama error {r.status_code}: {detail[:300]}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(f"Ollama error: {chunk['error'][:300]}")
                    yield chunk
                return
        except httpx.TimeoutException as e:
            raise OllamaError(f"Ollama did not answer within {timeout:.0f} s") from e
        except httpx.HTTPError as e:
            raise OllamaError(f"Cannot reach Ollama: {e}") from e


class ThinkFilter:
    """Drops <think>…</think> from streamed text (reasoning models that ignore think=false)."""

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False

    def feed(self, text: str) -> str:
        self.buf += text
        out = ""
        while self.buf:
            if self.inside:
                end = self.buf.find("</think>")
                if end < 0:
                    self.buf = self.buf[-8:]
                    return out
                self.buf = self.buf[end + 8:].lstrip()
                self.inside = False
                continue
            start = self.buf.find("<think>")
            if start >= 0:
                out += self.buf[:start]
                self.buf = self.buf[start + 7:]
                self.inside = True
                continue
            # keep a possible partial "<think" at the end
            keep = next((i for i in range(1, 7) if "<think>".startswith(self.buf[-i:])), 0)
            out += self.buf[: len(self.buf) - keep] if keep else self.buf
            self.buf = self.buf[len(self.buf) - keep:] if keep else ""
            return out
        return out

    def flush(self) -> str:
        out, self.buf = ("" if self.inside else self.buf), ""
        return out
