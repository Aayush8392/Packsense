"""The LLM gateway (roadmap item 22, design item 17): one place that every model call of the steward and the narrator goes through.

What it does, and nothing more:
  - the model for a role comes from gateway_config.json (never from code);
  - a call whose prompt is over the role's limit is refused BEFORE it is sent;
  - a call that would take the role's rolling 24-hour token total past the share of its daily pool set in the config (0.9 = 180,000 of 200,000 tokens, the
    owner's setting of 2026-11-04, was 0.8) is refused BEFORE it is sent (Groq's daily limit is a rolling window);
  - a rate-limit or quota answer (HTTP 429) raises at once with the server's retry-after and is never retried here; any other server error raises too;
  - every successful call returns a provenance record (role, model, time, prompt hash, tokens) and is added to the usage log.
Standard library only, so nothing enters the hash locks. The key is read by name and never printed or logged. Prompt text is never logged: only its hash.
The transport is injectable, so the tests run with no network.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

CONFIG = Path(__file__).resolve().with_name("gateway_config.json")


class GatewayError(Exception):
    """A refusal or a server error. `kind` is one of: prompt_too_long, budget, rate_limited, server, config."""

    def __init__(self, kind: str, message: str, retry_after: str | None = None):
        super().__init__(f"{kind}: {message}")
        self.kind, self.retry_after = kind, retry_after


def load_config(path: Path = CONFIG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for role, r in cfg["roles"].items():
        for field in ("model", "daily_tokens", "max_prompt_tokens", "max_output_tokens"):
            if field not in r:
                raise GatewayError("config", f"role {role} has no {field}")
    return cfg


def estimate_tokens(messages: list[dict]) -> int:
    """A deliberately high estimate (3 characters a token) used only to refuse an oversized call before it is sent."""
    return sum(len(m.get("content", "")) for m in messages) // 3 + 4 * len(messages)


def prompt_hash(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


class UsageLog:
    """Tokens used per model with their times; the rolling 24-hour total is what the budget guard reads. Optionally kept in a JSON-lines file."""

    def __init__(self, path: str | Path | None = None, clock: Callable[[], float] = time.time):
        self.path, self.clock, self.rows = (Path(path) if path else None), clock, []
        if self.path and self.path.exists():
            self.rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def add(self, model: str, tokens: int) -> None:
        row = {"t": self.clock(), "model": model, "tokens": int(tokens)}
        self.rows.append(row)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")

    def last_24h(self, model: str) -> int:
        cutoff = self.clock() - 86400
        return sum(r["tokens"] for r in self.rows if r["model"] == model and r["t"] >= cutoff)


def http_transport(endpoint: str, key: str, body: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "packsense-gateway/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:200].replace(key, "<key>")
        if e.code == 429:
            raise GatewayError("rate_limited", text, e.headers.get("retry-after")) from None
        raise GatewayError("server", f"HTTP {e.code}: {text}") from None
    except urllib.error.URLError as e:
        raise GatewayError("server", f"no answer: {e.reason}") from None


def read_key(name: str, env_file: str | None = None) -> str:
    key = os.environ.get(name, "")
    if not key and env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise GatewayError("config", f"{name} is empty or missing")
    return key


class Gateway:
    def __init__(self, key: str, config: dict | None = None, usage: UsageLog | None = None,
                 transport: Callable[[str, str, dict], dict] = http_transport, clock: Callable[[], float] = time.time, budget_share: float | None = None):
        """`budget_share` overrides the config's share of the daily pool this gateway may use (a measurement run asks for less than the nightly work would)."""
        self.cfg = config or load_config()
        self.key, self.usage, self.transport, self.clock = key, usage or UsageLog(clock=clock), transport, clock
        self.budget_share = self.cfg.get("budget_share", 0.8) if budget_share is None else budget_share
        if not 0 < self.budget_share <= 1:
            raise GatewayError("config", f"budget_share must be above 0 and at most 1, not {self.budget_share}")

    def tokens_left(self, role: str) -> int:
        """Tokens this gateway may still spend on the role's model in the rolling 24 hours (never below zero)."""
        r = self.cfg["roles"][role]
        return max(int(r["daily_tokens"] * self.budget_share) - self.usage.last_24h(r["model"]), 0)

    def call(self, role: str, messages: list[dict]) -> dict:
        """One call for a role. Returns {'text', 'finish_reason', 'provenance'}; raises GatewayError on refusal or server error."""
        if role not in self.cfg["roles"]:
            raise GatewayError("config", f"unknown role {role!r}")
        r = self.cfg["roles"][role]
        estimate = estimate_tokens(messages)
        if estimate > r["max_prompt_tokens"]:
            raise GatewayError("prompt_too_long", f"estimated {estimate} tokens, the limit for {role} is {r['max_prompt_tokens']}")
        allowed = int(r["daily_tokens"] * self.budget_share)
        used = self.usage.last_24h(r["model"])
        if used + estimate + r["max_output_tokens"] > allowed:
            raise GatewayError("budget", f"{used} tokens used in the last 24 hours of {allowed} allowed for {r['model']}")
        body = {"model": r["model"], "messages": messages, "max_completion_tokens": r["max_output_tokens"], "temperature": r.get("temperature", 0.2)}
        data = self.transport(self.cfg["endpoint"], self.key, body)
        usage = data["usage"]
        self.usage.add(r["model"], usage["total_tokens"])
        choice = data["choices"][0]
        return {"text": choice["message"].get("content") or "", "finish_reason": choice.get("finish_reason"),
                "provenance": {"role": role, "model": r["model"], "at": self.clock(), "prompt_hash": prompt_hash(messages),
                               "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"], "total_tokens": usage["total_tokens"]}}
