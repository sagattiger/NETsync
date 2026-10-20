"""Minimal async client for the Ollama HTTP API (also works behind Open WebUI-style proxies with a key)."""

import re
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
