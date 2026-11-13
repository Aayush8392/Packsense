"""The retry queue of the nightly job (A121 settled 2026-11-13): pure state logic, no network, no files.

State (a plain dict, saved by the caller): {"version": 1, "items": {code: {...}}, "done": {code: {...}}}.
  items  products still to read: first_seen, attempts, last_attempt, record_hash, new, last_reason
  done   products that need no further call until their stored record changes: outcome 'line', 'silence' (a content reason: no photo, readers disagree, ...) or 'gave_up'
Order each night: new flags first, then products that missed an earlier night (a transient error), then the backlog; inside a tier by sha256 of the code (fixed, content-blind).
A transient error costs an attempt; after MAX_ATTEMPTS the product is done as 'gave_up'. A content silence is final for that record: it is read again only when the record hash changes.
A product that is no longer a candidate (its flag closed) leaves the state entirely.
"""
from __future__ import annotations

import hashlib

MAX_ATTEMPTS = 3
CALLS_PER_PRODUCT = 2       # text reader + photo reader


def new_state() -> dict:
    return {"version": 1, "items": {}, "done": {}}


def order_key(code: str) -> str:
    return hashlib.sha256(("night-order:" + code).encode()).hexdigest()


def _fresh(candidate: dict, today: str, new: bool) -> dict:
    return {"first_seen": today, "attempts": 0, "last_attempt": None, "record_hash": candidate["record_hash"], "new": new, "last_reason": None}


def merge_candidates(state: dict, candidates: list[dict], today: str) -> dict:
    """candidates: [{'code', 'record_hash', 'new': bool}] = every product whose flag is open today. Returns counts of what changed."""
    cand = {c["code"]: c for c in candidates}
    items, done = state["items"], state["done"]
    removed = sorted(c for c in set(items) | set(done) if c not in cand)
    for c in removed:
        items.pop(c, None)
        done.pop(c, None)
    added = requeued = 0
    for code, c in cand.items():
        h = c["record_hash"]
        if code in done:
            if done[code]["record_hash"] == h:
                continue
            del done[code]
            items[code] = _fresh(c, today, True)           # the record changed: read afresh, as a new item
            requeued += 1
        elif code in items:
            if items[code]["record_hash"] != h:
                items[code] = _fresh(c, today, True)
                requeued += 1
        else:
            items[code] = _fresh(c, today, bool(c.get("new")))
            added += 1
    return {"added": added, "requeued": requeued, "removed": len(removed)}


def tier(item: dict) -> int:
    if item["attempts"] > 0:
        return 1
    return 0 if item["new"] else 2


def take(state: dict, today: str, max_products: int) -> list[str]:
    """The codes to read tonight, in order; a product already tried tonight is skipped."""
    ready = [(tier(i), order_key(c), c) for c, i in state["items"].items() if i["last_attempt"] != today]
    return [c for _, _, c in sorted(ready)][:max_products]


def settle(state: dict, code: str, outcome: str, today: str, reason: str | None = None) -> None:
    """outcome: 'line' | 'silence' (final, with a reason) | 'error' (transient: one more attempt used)."""
    item = state["items"][code]
    if outcome in ("line", "silence"):
        state["done"][code] = {"record_hash": item["record_hash"], "outcome": outcome, "reason": reason, "night": today}
        del state["items"][code]
    elif outcome == "error":
        item["attempts"] += 1
        item["last_attempt"] = today
        item["last_reason"] = reason
        if item["attempts"] >= MAX_ATTEMPTS:
            state["done"][code] = {"record_hash": item["record_hash"], "outcome": "gave_up", "reason": reason, "night": today}
            del state["items"][code]
    else:
        raise ValueError(f"unknown outcome {outcome!r}")


def counts(state: dict) -> dict:
    out = {"queued": len(state["items"]), "queued_new": 0, "queued_missed": 0, "queued_backlog": 0, "line": 0, "silence": 0, "gave_up": 0}
    for i in state["items"].values():
        out[("queued_new", "queued_missed", "queued_backlog")[tier(i)]] += 1
    for d in state["done"].values():
        out[d["outcome"]] += 1
    return out
