"""Daily capture of Open Food Facts delta files.

For every delta file OFF still lists (it keeps about 14 days) that is not yet in the Databricks landing volume:
download -> checksum and line count -> upload to B2 (upload-only key) -> upload to the landing volume
(pipeline-user token) -> record it in a manifest. Re-runs are harmless: a file already in landing is skipped.

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


def b2_client():
    endpoint = need("B2_S3_ENDPOINT")
    return boto3.client(
        "s3", endpoint_url=endpoint if endpoint.startswith("http") else "https://" + endpoint,
        aws_access_key_id=need("B2_UPLOAD_KEY_ID"), aws_secret_access_key=need("B2_UPLOAD_APPLICATION_KEY"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def download(name: str, directory: str) -> dict:
    path = os.path.join(directory, name)
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with requests.get(OFF_DELTA + name, headers=USER_AGENT, stream=True, timeout=120) as r, open(path, "wb") as out:
        r.raise_for_status()
        for chunk in r.iter_content(1 << 20):
            out.write(chunk)
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    if size == 0:
        raise RuntimeError(f"{name}: empty download")
    lines = 0
    with gzip.open(path, "rb") as g:  # integrity check: the whole file must decompress
        for _ in g:
            lines += 1
    return {"name": name, "path": path, "bytes": size, "sha256": sha.hexdigest(), "md5": md5.hexdigest(), "lines": lines}


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
    todo = [n for n in names if n not in have]
    if args.max_files:
        todo = todo[: args.max_files]
    print(f"OFF lists {len(names)} delta files; {len(have)} already in landing; {len(todo)} to capture")
    for n in todo:
        print("  would capture" if args.dry_run else "  capturing", n)
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
                if re.fullmatch(r"[0-9a-f]{32}", etag) and etag != info["md5"]:
                    raise RuntimeError(f"{name}: B2 checksum differs from the local checksum")
                with open(info["path"], "rb") as fh:
                    landing.put(f"deltas/{name}", fh)
                if landing.size(f"deltas/{name}") != info["bytes"]:
                    raise RuntimeError(f"{name}: landing size differs from the local size")
                os.remove(info["path"])
                entries.append({k: info[k] for k in ("name", "bytes", "sha256", "lines")} | {"b2_key": key, "landing": f"deltas/{name}"})
                print(f"  ok {name}: {info['bytes'] / 1e6:.1f} MB, {info['lines']:,} records, sha256 {info['sha256'][:12]}.. ({time.time() - t0:.0f}s)")
            except Exception as exc:  # keep going so one bad file does not block the others
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
