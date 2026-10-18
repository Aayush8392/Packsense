"""Secret-expiry tripwire: is any credential within N days of expiring?

The list of secrets and their expiry dates is NOT in this repository (it is public). It lives in the repository variable
SECRET_EXPIRY_LIST, a JSON list: [{"name": "...", "expires": "YYYY-MM-DD" or null}, ...]. `null` means no known expiry and is
never reported. Update the variable whenever a secret is rotated.

This repository's Actions logs are public too, so the log carries COUNTS only. The names and days left go only to the
healthchecks.io ping body (private): a success ping when nothing is due, a /fail ping listing what is due or expired.

Configuration comes from environment variables; values are never printed.
  SECRET_EXPIRY_LIST, HEALTHCHECKS_PING_URL, SECRET_EXPIRY_THRESHOLD_DAYS (default 10)
Exit codes: 0 nothing due, 1 something due or expired (or the list is missing or malformed).
"""
import datetime as dt
import json
import os
import sys
import urllib.request

DEFAULT_THRESHOLD_DAYS = 10


def parse_list(text: str) -> list[dict]:
    """Validate the JSON list. Raises ValueError with a message that names the position, never the content."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("the secret list is not valid JSON") from None
    if not isinstance(data, list) or not data:
        raise ValueError("the secret list must be a non-empty JSON list")
    seen, out = set(), []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError(f"entry {i}: 'name' must be a non-empty string")
        name = item["name"].strip()
        if name in seen:
            raise ValueError(f"entry {i}: duplicate name")
        seen.add(name)
        raw = item.get("expires")
        if raw is None:
            out.append({"name": name, "expires": None})
            continue
        try:
            out.append({"name": name, "expires": dt.date.fromisoformat(raw)})
        except (TypeError, ValueError):
            raise ValueError(f"entry {i}: 'expires' must be YYYY-MM-DD or null") from None
    return out


def due(entries: list[dict], today: dt.date, threshold_days: int) -> list[tuple[str, int, dt.date]]:
    """(name, days left, expiry date) for every entry that expires within threshold_days (negative = already expired),
    soonest first. An entry with no expiry is never due; exactly threshold_days left IS due."""
    hits = []
    for e in entries:
        if e["expires"] is None:
            continue
        left = (e["expires"] - today).days
        if left <= threshold_days:
            hits.append((e["name"], left, e["expires"]))
    return sorted(hits, key=lambda h: (h[1], h[0]))


def report_lines(hits: list[tuple[str, int, dt.date]]) -> list[str]:
    return [
        f"{name}: EXPIRED {-left} day(s) ago ({when})" if left < 0 else f"{name}: {left} day(s) left ({when})"
        for name, left, when in hits
    ]


def ping(url: str, body: str, fail: bool) -> None:
    target = url.rstrip("/") + ("/fail" if fail else "")
    req = urllib.request.Request(target, data=body.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (the URL is our own healthchecks ping URL)
        resp.read()


def main() -> int:
    url = os.environ.get("HEALTHCHECKS_PING_URL", "")
    threshold = int(os.environ.get("SECRET_EXPIRY_THRESHOLD_DAYS") or DEFAULT_THRESHOLD_DAYS)
    today = dt.datetime.now(dt.timezone.utc).date()
    try:
        entries = parse_list(os.environ.get("SECRET_EXPIRY_LIST", ""))
    except ValueError as e:
        print(f"FAIL: {e}")
        if url:
            ping(url, f"secret expiry check could not read its list: {e}", fail=True)
        return 1
    hits = due(entries, today, threshold)
    tracked = sum(1 for e in entries if e["expires"] is not None)
    if hits:
        print(f"FAIL: {len(hits)} of {tracked} dated secret(s) expire within {threshold} days or already have (names are in the healthchecks ping, not here)")
        if url:
            ping(url, f"{len(hits)} secret(s) within {threshold} days:\n" + "\n".join(report_lines(hits)), fail=True)
        return 1
    print(f"ok: {tracked} dated secret(s) tracked, none within {threshold} days")
    if url:
        ping(url, f"ok: {tracked} dated secret(s), none within {threshold} days", fail=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
