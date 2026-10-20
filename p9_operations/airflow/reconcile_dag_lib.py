"""The logic of the reconciliation DAG, as plain Python so it can be tested without Airflow (the DAG file only wires it together).

What the DAG does each week (existence_lib.py explains the statuses): find the newest candidate list Databricks left in the landing volume, ask OFF's
API about every candidate slowly and politely, keep one small result file per code so an interrupted run resumes, and upload the answers as one JSON-lines file
that the Databricks loader reads. Nothing here touches OFF's data beyond `code,status,status_verbose,last_modified_t` of the candidate codes.

Politeness and limits (measured 2026-10-20 on 14 real lookups: 0.8 to 1.2 s each): one request at a time, a pause between requests, a pause that grows when OFF
answers HTTP 429, and a batch that stops (the DAG's retry takes over later) when OFF keeps refusing. A code that still gets no clear answer is recorded as
`unconfirmed` and asked again the next week; nothing is guessed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import existence_lib as rl  # noqa: E402

BATCH_SIZE = 100
USER_AGENT = "packsense-reconcile/0.1 (portfolio project; contact via github.com/Aayush8392/Packsense)"
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 5                       # per code: the first request plus four retries
BACKOFF_SECONDS = (30, 60, 120, 240)   # waited after the 1st, 2nd, 3rd and 4th failed attempt (Retry-After wins when OFF sends one)
MAX_BACKOFF = 300
STOP_AFTER_RATE_LIMITED = 3            # codes in a row that were still rate limited after every retry: the batch stops and Airflow retries it later


class RateLimited(Exception):
    """OFF kept answering HTTP 429: stop this batch now, do not hammer."""


def chunk(items: list, size: int = BATCH_SIZE) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def http_get(url: str):
    """(http status, parsed body or None, error text or None, Retry-After seconds or None) for one GET. Network errors are values, not exceptions."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        r = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        status, raw, hdr = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hdr = e.code, e.read(), e.headers
    except Exception as e:                                       # timeout, DNS, reset: a failure of the request itself
        return None, None, f"{type(e).__name__}: {str(e)[:100]}", None
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        body = None
    retry_after = hdr.get("Retry-After") if hdr else None
    return status, body, None, (int(retry_after) if retry_after and retry_after.isdigit() else None)


def lookup_one(code: str, get=http_get, sleep=time.sleep, now=lambda: dt.datetime.now(dt.timezone.utc)) -> tuple[dict, bool]:
    """Ask OFF about one code, retrying with a growing pause. Returns (result line, still_rate_limited). The result line is the LAST answer, classified."""
    status, body, error, retry_after = None, None, None, None
    for attempt in range(MAX_ATTEMPTS):
        status, body, error, retry_after = get(rl.api_url(code))
        outcome = rl.classify_response(status, body, error)
        if outcome["status"] != rl.STATUS_UNCONFIRMED or not (error or status in rl.RETRYABLE_HTTP):
            return rl.result_line(code, outcome, status, now()), False          # a clear answer, or an answer retrying cannot improve
        if attempt < MAX_ATTEMPTS - 1:
            sleep(min(retry_after if retry_after else BACKOFF_SECONDS[attempt], MAX_BACKOFF))
    return rl.result_line(code, rl.classify_response(status, body, error), status, now()), status == 429


def run_batch(codes: list[str], result_dir: str, get=http_get, sleep=time.sleep, now=lambda: dt.datetime.now(dt.timezone.utc),
              pause: float = rl.API_PAUSE_SECONDS) -> dict:
    """Look up every code that has no result file yet, one at a time. Each answer is written to `<result_dir>/<code>.json` as soon as it is known, so a
    batch that is interrupted, retried or rerun does only the remaining codes. Raises RateLimited after STOP_AFTER_RATE_LIMITED codes in a row that stayed
    rate limited (their files are NOT written: they are asked again)."""
    out = Path(result_dir)
    out.mkdir(parents=True, exist_ok=True)
    done = skipped = limited_in_a_row = 0
    for code in codes:
        target = out / f"{code}.json"
        if target.exists():
            skipped += 1
            continue
        line, limited = lookup_one(code, get=get, sleep=sleep, now=now)
        if limited:
            limited_in_a_row += 1
            if limited_in_a_row >= STOP_AFTER_RATE_LIMITED:
                raise RateLimited(f"{limited_in_a_row} codes in a row were still rate limited after {MAX_ATTEMPTS} attempts; {done} looked up in this batch")
            continue
        limited_in_a_row = 0
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(line), encoding="utf-8")
        os.replace(tmp, target)
        done += 1
        sleep(pause)
    return {"looked_up": done, "already_done": skipped, "codes": len(codes)}


def collect(codes: list[str], result_dir: str, now=lambda: dt.datetime.now(dt.timezone.utc)) -> list[dict]:
    """One result line per candidate, in candidate order. A code with no file (never answered) is `unconfirmed`: it is asked again next week."""
    lines = []
    for code in codes:
        f = Path(result_dir) / f"{code}.json"
        if f.exists():
            lines.append(json.loads(f.read_text(encoding="utf-8")))
        else:
            lines.append(rl.result_line(code, {"status": rl.STATUS_UNCONFIRMED, "detail": "not looked up in this run"}, None, now()))
    return lines


def to_jsonl(lines: list[dict]) -> str:
    return "".join(json.dumps(x) + "\n" for x in lines)


# --- the landing volume through Databricks' Files API (the pipeline user's token: read and write on that volume only) ------------------------------

class Landing:
    def __init__(self, host: str, token: str, base: str = "/Volumes/workspace/packsense/landing", session=None):
        import requests
        self.host = host.rstrip("/") if host.startswith("http") else "https://" + host.rstrip("/")
        self.base = base.rstrip("/")
        self.s = session or requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def _url(self, path: str, kind: str) -> str:
        return f"{self.host}/api/2.0/fs/{kind}{self.base}/{path.lstrip('/')}"

    def list(self, folder: str) -> list[str]:
        r = self.s.get(self._url(folder, "directories"), timeout=60)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return [c["name"] for c in r.json().get("contents", []) if not c.get("is_directory")]

    def read(self, path: str) -> bytes:
        r = self.s.get(self._url(path, "files"), timeout=120)
        r.raise_for_status()
        return r.content

    def write(self, path: str, data: bytes) -> None:
        r = self.s.put(self._url(path, "files") + "?overwrite=true", data=data, timeout=120)
        r.raise_for_status()


def newest_candidates_file(names: list[str]) -> str | None:
    """The candidate list with the latest snapshot date (`<date>.json`), or None."""
    dated = sorted(n for n in names if n.endswith(".json") and n[:10].count("-") == 2)
    return dated[-1] if dated else None
