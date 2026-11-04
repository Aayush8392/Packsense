"""A tiny Neon client over Neon's SQL-over-HTTP endpoint (item 22): standard library only, so no Postgres driver enters the hash locks.

The connection string is read by name from the environment or from a .env file and is never printed; an error message has it removed.
One call is one transaction: `run` sends a list of statements and Neon runs them together, all or nothing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_NAME = "NEON_DATABASE_URL"


class NeonError(RuntimeError):
    """The server refused a statement; `.message` is the server's text (the URL is never in it)."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


def read_url(env_file: str | None = None) -> str:
    """The connection string from the environment, else from the .env file; raises when it is missing or not a Postgres URL."""
    value = os.environ.get(ENV_NAME, "")
    if not value and env_file:
        for raw in Path(env_file).read_text(encoding="utf-8").splitlines():
            if raw.startswith(ENV_NAME + "="):
                value = raw.split("=", 1)[1].strip().strip('"')
    if not value.startswith(("postgres://", "postgresql://")):
        raise ValueError(f"{ENV_NAME} is missing or is not a Postgres URL")
    return value


def run(url: str, statements: list[str], timeout: float = 90.0) -> list[list[dict]]:
    """Run the statements as one transaction; returns the rows of each statement as a list of dicts."""
    host = urllib.parse.urlparse(url).hostname
    body = json.dumps({"queries": [{"query": s, "params": []} for s in statements]}).encode()
    request = urllib.request.Request(f"https://{host}/sql", data=body, headers={"Neon-Connection-String": url, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace").replace(url, "<url>")
        try:
            info = json.loads(text)
        except ValueError:
            raise NeonError(f"HTTP {e.code}: {text[:300]}") from None
        raise NeonError(str(info.get("message", text))[:400], info.get("code")) from None
    results = payload["results"] if "results" in payload else [payload]
    return [[dict(r) if isinstance(r, dict) else r for r in (res.get("rows") or [])] for res in results]
