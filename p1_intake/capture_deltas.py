"""Daily capture of Open Food Facts delta files.

For every delta file OFF still lists (it keeps about 14 days) that is not yet in the Databricks landing volume:
download -> checksum and line count -> upload to B2 (upload-only key) -> upload to the landing volume
(pipeline-user token) -> record it in a manifest. Re-runs are harmless: a file already in landing is skipped.

Orphans: a run that dies after a file reached landing but before the manifest was written leaves a landed file no
manifest records. Every run looks for these. An orphan OFF still lists goes through the full path again (a repeat B2
upload makes a second version of the key; the bucket lifecycle removes it after the hidden-file window). An orphan OFF
no longer lists is recorded from the landed file itself (checked to decompress, lines counted), marked as not
re-verified against B2.

Configuration comes from environment variables; values are never printed.
  B2_S3_ENDPOINT, B2_BUCKET, B2_UPLOAD_KEY_ID, B2_UPLOAD_APPLICATION_KEY
  DATABRICKS_HOST, DATABRICKS_PIPELINE_TOKEN
Exit codes: 0 ok, 1 a step failed, 2 OFF's feed looks stale.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time

import boto3
import requests
from botocore.config import Config

OFF_DELTA = "https://static.openfoodfacts.org/data/delta/"
USER_AGENT = {"User-Agent": "packsense-capture/0.1 (+https://github.com/Aayush8392/Packsense)"}
LANDING = "/Volumes/workspace/packsense/landing"
NAME_RE = re.compile(r"^openfoodfacts_products_(\d+)_(\d+)\.json\.gz$")
STALE_AFTER_HOURS = 48


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"missing environment variable: {name}")
    return value


def list_index() -> list[str]:
    text = requests.get(OFF_DELTA + "index.txt", headers=USER_AGENT, timeout=30).text
    names = [n.strip() for n in text.splitlines() if NAME_RE.match(n.strip())]
    return sorted(names, key=lambda n: int(NAME_RE.match(n).group(1)))


class Landing:
    """Databricks Files API on the landing volume (pipeline-user token)."""

    def __init__(self) -> None:
        host = need("DATABRICKS_HOST").rstrip("/")
        self.base = host if host.startswith("http") else "https://" + host
        self.headers = {"Authorization": "Bearer " + need("DATABRICKS_PIPELINE_TOKEN")}

    def names(self, folder: str) -> set[str]:
        found, token = set(), None
        while True:
            params = {"page_token": token} if token else {}
            r = requests.get(f"{self.base}/api/2.0/fs/directories{LANDING}/{folder}", headers=self.headers, params=params, timeout=60)
            if r.status_code == 404:
                return found
            r.raise_for_status()
            body = r.json()
            found |= {c["name"] for c in body.get("contents", []) if not c.get("is_directory")}
            token = body.get("next_page_token")
            if not token:
                return found

    def put(self, path: str, data) -> None:
        r = requests.put(f"{self.base}/api/2.0/fs/files{LANDING}/{path}", headers=self.headers, params={"overwrite": "true"}, data=data, timeout=600)
        r.raise_for_status()

    def size(self, path: str) -> int:
        r = requests.head(f"{self.base}/api/2.0/fs/files{LANDING}/{path}", headers=self.headers, timeout=60)
        r.raise_for_status()
        return int(r.headers["Content-Length"])

    def get(self, path: str) -> bytes:
        r = requests.get(f"{self.base}/api/2.0/fs/files{LANDING}/{path}", headers=self.headers, timeout=600)
        r.raise_for_status()
        return r.content

    def recorded_names(self) -> set[str]:
        """Every file name that any capture manifest in landing records."""
        recorded: set[str] = set()
        for manifest in sorted(self.names("manifests")):
            recorded |= {f["name"] for f in json.loads(self.get(f"manifests/{manifest}")).get("files", [])}
        return recorded


def find_orphans(landed: set[str], recorded: set[str]) -> list[str]:
    """Delta files that are in landing but not in any manifest."""
    return sorted(n for n in landed - recorded if NAME_RE.match(n))


def split_orphans(orphans: list[str], listed_by_off: list[str]) -> tuple[list[str], list[str]]:
    """(orphans OFF still lists, so they can be captured again; orphans OFF no longer lists)."""
    listed = set(listed_by_off)
    return [n for n in orphans if n in listed], [n for n in orphans if n not in listed]


def b2_client():
    endpoint = need("B2_S3_ENDPOINT")
    return boto3.client(
        "s3", endpoint_url=endpoint if endpoint.startswith("http") else "https://" + endpoint,
        aws_access_key_id=need("B2_UPLOAD_KEY_ID"), aws_secret_access_key=need("B2_UPLOAD_APPLICATION_KEY"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def inspect_local(path: str, name: str) -> dict:
    """Checksums, size and line count of a local delta file; the whole file must decompress."""
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    if size == 0:
        raise RuntimeError(f"{name}: empty file")
    lines = 0
    with gzip.open(path, "rb") as g:
        for _ in g:
            lines += 1
    return {"name": name, "path": path, "bytes": size, "sha256": sha.hexdigest(), "md5": md5.hexdigest(), "lines": lines}


def download(name: str, directory: str) -> dict:
    path = os.path.join(directory, name)
    with requests.get(OFF_DELTA + name, headers=USER_AGENT, stream=True, timeout=120) as r, open(path, "wb") as out:
        r.raise_for_status()
        for chunk in r.iter_content(1 << 20):
            out.write(chunk)
    return inspect_local(path, name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list what would be captured, change nothing")
    ap.add_argument("--max-files", type=int, default=0, help="capture at most N files (0 = all)")
    args = ap.parse_args()

    names = list_index()
    if not names:
        print("OFF index lists no delta files")
        return 1
    landing = Landing()
    have = landing.names("deltas")
    orphans = find_orphans(have, landing.recorded_names())
    refetch, from_landing = split_orphans(orphans, names)
    todo = [n for n in names if n not in have or n in refetch]
    if args.max_files:
        todo = todo[: args.max_files]
    print(f"OFF lists {len(names)} delta files; {len(have)} already in landing; {len(todo)} to capture")
    print(f"orphans (in landing, in no manifest): {len(orphans)} ({len(refetch)} still listed by OFF, {len(from_landing)} to record from landing)")
    for n in todo:
        print("  would capture" if args.dry_run else "  capturing", n, "(orphan, capturing again)" if n in refetch else "")
    for n in from_landing:
        print("  would record from landing" if args.dry_run else "  will record from landing", n)
    if args.dry_run:
        return 0

    s3, bucket = b2_client(), need("B2_BUCKET")
    entries, failed = [], False
    with tempfile.TemporaryDirectory() as tmp:
        for name in todo:
            try:
                t0 = time.time()
                info = download(name, tmp)
                key = f"raw/deltas/{name}"
                with open(info["path"], "rb") as fh:
                    etag = s3.put_object(Bucket=bucket, Key=key, Body=fh)["ETag"].strip('"')
                etag_is_md5 = bool(re.fullmatch(r"[0-9a-f]{32}", etag))
                if etag_is_md5 and etag != info["md5"]:
                    raise RuntimeError(f"{name}: B2 checksum differs from the local checksum")
                with open(info["path"], "rb") as fh:
                    landing.put(f"deltas/{name}", fh)
                if landing.size(f"deltas/{name}") != info["bytes"]:
                    raise RuntimeError(f"{name}: landing size differs from the local size")
                os.remove(info["path"])
                entry = {k: info[k] for k in ("name", "bytes", "sha256", "lines")} | {"b2_key": key, "landing": f"deltas/{name}", "b2_etag_matched": etag_is_md5}
                if name in refetch:
                    entry["recovered"] = True
                entries.append(entry)
                print(f"  ok {name}: {info['bytes'] / 1e6:.1f} MB, {info['lines']:,} records, sha256 {info['sha256'][:12]}.. ({time.time() - t0:.0f}s)")
            except Exception as exc:  # keep going so one bad file does not block the others
                failed = True
                print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:200]}")

        for name in from_landing:  # OFF no longer lists these: the landed file is all that is left, so record it as it is
            try:
                path = os.path.join(tmp, name)
                with open(path, "wb") as fh:
                    fh.write(landing.get(f"deltas/{name}"))
                info = inspect_local(path, name)
                os.remove(path)
                entries.append({k: info[k] for k in ("name", "bytes", "sha256", "lines")} | {
                    "b2_key": f"raw/deltas/{name}", "landing": f"deltas/{name}", "b2_etag_matched": False, "recovered": True})
                print(f"  recorded from landing {name}: {info['bytes'] / 1e6:.1f} MB, {info['lines']:,} records (not re-verified against B2)")
            except Exception as exc:
                failed = True
                print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:200]}")

    now = dt.datetime.now(dt.timezone.utc)
    manifest = {
        "manifest_version": 1, "captured_at": now.isoformat(timespec="seconds"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"), "files": entries, "failed": failed,
        "newest_delta_in_index": names[-1],
    }
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    body = json.dumps(manifest, indent=1).encode()
    s3.put_object(Bucket=bucket, Key=f"raw/manifests/{stamp}.json", Body=body)
    landing.put(f"manifests/{stamp}.json", body)
    print(f"manifest written: manifests/{stamp}.json ({len(entries)} new files)")

    newest_end = int(NAME_RE.match(names[-1]).group(2))
    age_h = (now.timestamp() - newest_end) / 3600
    print(f"newest OFF delta ends {age_h:.1f} h ago")
    if failed:
        return 1
    if age_h > STALE_AFTER_HOURS:
        print(f"OFF feed looks stale (> {STALE_AFTER_HOURS} h)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
