"""The monthly egress check (roadmap item M1; the full-automation aim, context file A67).

Databricks' own page says outbound internet is "restricted to a limited set of trusted domains" while a read-only run on 2026-10-18 found it open, so the pipeline depends on
something the vendor says can change. Once a month a small job makes ONE light request to every outside service the pipeline needs, from the same kind of compute the real
jobs use, and goes red with a ping if any of them is not reachable or answers something unexpected. A failure there is a heads-up before a capture, an archive or a lookup fails.

Rules: a connection error, a timeout or an unexpected status is a failure; HTTP 429 counts as reachable (the service answered, it is only busy), noted in the detail; B2's endpoint answers
403 or 400 to an unauthenticated request, which means reachable. No secret is used and nothing is written. Plain Python with the fetch function injected so it can be tested.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = {"User-Agent": "packsense-egress-check/0.1 (portfolio project; github.com/Aayush8392/Packsense)"}
TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Service:
    name: str            # what the pipeline uses it for
    url: str
    method: str = "GET"
    ok_status: tuple = (200,)
    body_contains: str | None = None


SERVICES = (
    Service("OFF delta index (the daily capture)", "https://static.openfoodfacts.org/data/delta/index.txt"),
    Service("OFF taxonomy file (the taxonomy capture)", "https://static.openfoodfacts.org/data/taxonomies/data_quality.json", method="HEAD"),
    Service("OFF product API (the reconciliation lookups)", "https://world.openfoodfacts.org/api/v2/product/3017620422003.json?fields=code,status", ok_status=(200,),
            body_contains='"status":1'),
    Service("Hugging Face dataset API (the snapshot comparison)", "https://huggingface.co/api/datasets/openfoodfacts/product-database"),
    Service("Backblaze B2 endpoint (capture upload, archive read)", "https://s3.eu-central-003.backblazeb2.com", ok_status=(200, 400, 403)),
    Service("PyPI (the notebooks install DuckDB and requests)", "https://pypi.org/simple/duckdb/"),
    Service("healthchecks.io (the pings)", "https://healthchecks.io/"),
)


def fetch(service: Service, timeout: int = TIMEOUT_SECONDS) -> tuple[int | None, str, str | None]:
    """(http status, the first 4 KB of the body as text, error text). Network errors are values, not exceptions."""
    req = urllib.request.Request(service.url, method=service.method, headers=USER_AGENT)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read(4096).decode("utf-8", "replace") if service.method == "GET" else ""
        return r.status, body, None
    except urllib.error.HTTPError as e:
        return e.code, "", None
    except Exception as e:                                         # timeout, DNS, reset, blocked: a failure of the request itself
        return None, "", f"{type(e).__name__}: {str(e)[:100]}"


def judge(service: Service, status: int | None, body: str, error: str | None) -> tuple[bool, str]:
    """(ok, detail). Never includes more than the status and a short reason."""
    if error is not None or status is None:
        return False, f"not reachable: {(error or 'no response')[:120]}"
    if status == 429:
        return True, "reachable (HTTP 429: the service is busy)"
    if status not in service.ok_status:
        return False, f"unexpected HTTP {status} (expected {'/'.join(str(s) for s in service.ok_status)})"
    if service.body_contains and service.body_contains.replace(" ", "") not in body.replace(" ", ""):
        return False, f"HTTP {status} but the answer does not look right (missing {service.body_contains})"
    return True, f"HTTP {status}"


def check_all(services=SERVICES, fetcher=fetch, sleep=time.sleep, pause: float = 2.0, now=time.monotonic) -> list[dict]:
    """One light request per service, `pause` seconds apart (OFF answers HTTP 429 to rapid requests). Returns one dict per service."""
    results = []
    for i, s in enumerate(services):
        t0 = now()
        status, body, error = fetcher(s)
        ok, detail = judge(s, status, body, error)
        results.append({"service": s.name, "ok": ok, "detail": detail, "seconds": round(now() - t0, 2)})
        if i < len(services) - 1:
            sleep(pause)
    return results


def summary(results: list[dict]) -> str:
    failed = [r for r in results if not r["ok"]]
    if not failed:
        return f"all {len(results)} outside services reachable"
    return f"{len(failed)} of {len(results)} outside services failed: " + "; ".join(f"{r['service']}: {r['detail']}" for r in failed)
