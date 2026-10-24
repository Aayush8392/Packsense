"""A small Groq chat client for the story trials (item 15): standard library only, one call at a time, no retry loop. The key is read by name and never printed."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    def __init__(self, status: int, retry_after: str | None, body: str):
        super().__init__(f"HTTP {status}, retry-after {retry_after}: {body[:200]}")
        self.status, self.retry_after = status, retry_after


def read_key(env_file: str | None = None) -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key and env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("GROQ_API_KEY is empty or missing")
    return key


def chat(key: str, model: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.2, extra: dict | None = None, timeout: int = 180) -> dict:
    body = {"model": model, "messages": messages, "max_completion_tokens": max_tokens, "temperature": temperature, **(extra or {})}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "packsense-story-trial/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise GroqError(e.code, e.headers.get("retry-after"), e.read().decode("utf-8", "replace")) from None
    u = data["usage"]
    return {"text": data["choices"][0]["message"].get("content") or "", "finish_reason": data["choices"][0].get("finish_reason"),
            "prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"], "total_tokens": u["total_tokens"],
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}
