"""Daily snapshot of Open Food Facts' taxonomies, kept only when they change.

For every taxonomy in TAXONOMIES: download it from OFF, hash it, and compare with the last recorded version.
A new or changed taxonomy is stored as a gzipped snapshot in B2 (upload-only key) and in the Databricks landing
volume. Every run also writes a small log of what each taxonomy looked like that day, changed or not, so the
taxonomy version in force on any past day can be looked up (the ML labels need this).

  B2 and landing:  taxonomies/<name>/<last-modified>_<sha12>.json.gz
  daily log:       taxonomies/manifests/<stamp>.json   (in landing, mirrored to B2 under taxonomies/_log/)

Snapshots live under taxonomies/, outside the raw/ lifecycle rule, so they are kept indefinitely (they are small and
change rarely). OFF rate-limits rapid requests (HTTP 429), so downloads are paced and retried with backoff. One failing
taxonomy does not stop the others; the run exits non-zero if any failed.

Configuration comes from environment variables; values are never printed.
  B2_S3_ENDPOINT, B2_BUCKET, B2_UPLOAD_KEY_ID, B2_UPLOAD_APPLICATION_KEY, DATABRICKS_HOST, DATABRICKS_PIPELINE_TOKEN
Exit codes: 0 ok, 1 at least one taxonomy failed.
"""
import argparse
import datetime as dt
import email.utils
import gzip
import hashlib
import json
import os
import sys
import time

import requests

from capture_deltas import USER_AGENT, b2_client, make_landing, need

BASE = "https://static.openfoodfacts.org/data/taxonomies/"
PREFIX = "taxonomies"
PACE_SECONDS = 3  # between downloads, to stay under OFF's rate limit
TAXONOMIES = [
    "additives", "additives_classes", "allergens", "amino_acids", "brands", "categories", "countries", "data_quality",
    "food_groups", "improvements", "ingredients", "ingredients_analysis", "ingredients_processing", "labels", "languages",
    "minerals", "misc", "nova_groups", "nucleotides", "nutrient_levels", "nutrients", "origins", "origins_adjectives",
    "other_nutritional_substances", "packaging_materials", "packaging_recycling", "packaging_shapes",
    "periods_after_opening", "preservation", "sizes", "states", "storage_conditions", "units", "vitamins",
]


def snapshot_key(name: str, last_modified: str | None, sha256: str, now: dt.datetime) -> str:
    """<name>/<OFF Last-Modified as UTC stamp>_<sha12>.json.gz; the capture time if OFF sent no Last-Modified."""
    when = email.utils.parsedate_to_datetime(last_modified) if last_modified else now
    return f"{name}/{when.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{sha256[:12]}.json.gz"


def last_known(logs: list[dict]) -> dict[str, dict]:
    """Latest recorded {sha256, snapshot} per taxonomy from the daily logs, oldest first (the newest entry wins)."""
    known: dict[str, dict] = {}
    for log in logs:
        for entry in log.get("entries", []):
            known[entry["name"]] = {"sha256": entry["sha256"], "snapshot": entry["snapshot"]}
    return known


def fetch(name: str) -> tuple[bytes, str | None]:
    delay = 5
    for _ in range(5):
        r = requests.get(f"{BASE}{name}.json", headers=USER_AGENT, timeout=120)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After", "")
            time.sleep(max(delay, int(retry_after)) if retry_after.isdigit() else delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r.content, r.headers.get("Last-Modified")
    raise RuntimeError(f"{name}: still HTTP 429 after 5 tries")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="download and compare, store nothing")
    ap.add_argument("--only", help="comma-separated taxonomy names (default: all)")
    ap.add_argument("--no-b2", action="store_true", help="do not upload to B2 (the dev target holds no B2 key)")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.only.split(",")] if args.only else TAXONOMIES
    unknown = [n for n in names if n not in TAXONOMIES]
    if unknown:
        sys.exit(f"not in TAXONOMIES: {', '.join(unknown)}")

    landing = make_landing()
    known = last_known([json.loads(landing.get(f"{PREFIX}/manifests/{m}")) for m in sorted(landing.names(f"{PREFIX}/manifests"))])
    s3, bucket = (None, None) if (args.dry_run or args.no_b2) else (b2_client(), need("B2_BUCKET"))
    now = dt.datetime.now(dt.timezone.utc)
    print(f"{len(names)} taxonomies to check; {len(known)} already have a recorded version")

    entries, failed = [], []
    for i, name in enumerate(names):
        if i:
            time.sleep(PACE_SECONDS)
        try:
            raw, modified = fetch(name)
            tags = len(json.loads(raw))  # must parse as JSON
            sha = hashlib.sha256(raw).hexdigest()
            prev = known.get(name)
            changed = prev is None or prev["sha256"] != sha
            if changed:
                key = snapshot_key(name, modified, sha, now)
                if not args.dry_run:
                    gz = gzip.compress(raw, mtime=0)
                    if s3 is not None:
                        etag = s3.put_object(Bucket=bucket, Key=f"{PREFIX}/{key}", Body=gz)["ETag"].strip('"')
                        if len(etag) == 32 and etag != hashlib.md5(gz).hexdigest():
                            raise RuntimeError(f"{name}: B2 checksum differs from the local checksum")
                    landing.put(f"{PREFIX}/{key}", gz)
            else:
                key = prev["snapshot"]
            entries.append({"name": name, "sha256": sha, "last_modified": modified, "tags": tags, "bytes": len(raw), "changed": changed, "snapshot": key})
            print(f"  {'NEW/CHANGED' if changed else 'unchanged  '} {name}: {tags:,} tags, {len(raw) / 1e3:.0f} KB")
        except Exception as exc:  # keep going so one bad taxonomy does not block the others
            failed.append(name)
            print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:200]}")

    changed_n = sum(1 for e in entries if e["changed"])
    print(f"{len(entries)} ok ({changed_n} new or changed), {len(failed)} failed")
    if args.dry_run:
        print("dry run: nothing stored")
    elif entries:
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        body = json.dumps({"log_version": 1, "captured_at": now.isoformat(timespec="seconds"),
                           "github_run_id": os.environ.get("GITHUB_RUN_ID"), "entries": entries, "failed": failed}, indent=1).encode()
        if s3 is not None:
            s3.put_object(Bucket=bucket, Key=f"{PREFIX}/_log/{stamp}.json", Body=body)
        landing.put(f"{PREFIX}/manifests/{stamp}.json", body)
        print(f"log written: {PREFIX}/manifests/{stamp}.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
