"""Fetches the checked site data from the private staging dataset on Hugging Face into a folder, verifying every file against the manifest.

  HF_SITE_READ_TOKEN=... python p6_serving/fetch_site_data.py <repo_id> <out_folder>

Standard library only (the Pages workflow runs it before anything is installed). The token comes from the environment and is never printed. It
downloads `site/release_manifest.json` first, then exactly the files that manifest lists (no directory listing), and refuses when a listed file is
missing, has a path outside the folder, or does not match its sha256. The licence gate runs on the result afterwards (a second, independent check:
the publish job ran it before uploading).
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST = "release_manifest.json"
PREFIX = "site/"


class FetchError(Exception):
    pass


def _get(repo: str, path: str, token: str, opener=urllib.request.urlopen) -> bytes:
    url = f"https://huggingface.co/datasets/{repo}/resolve/main/{urllib.parse.quote(PREFIX + path)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "packsense-site-build"})
    try:
        with opener(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"{path}: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise FetchError(f"{path}: {type(e.reason).__name__}") from None


def fetch(repo: str, out: Path, token: str, opener=urllib.request.urlopen) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    manifest_bytes = _get(repo, MANIFEST, token, opener)
    manifest = json.loads(manifest_bytes)
    (out / MANIFEST).write_bytes(manifest_bytes)
    root = out.resolve()
    for f in manifest.get("files", []):
        name = f.get("path", "")
        target = (out / name).resolve()
        if not name or "/" in name or "\\" in name or root not in target.parents:
            raise FetchError(f"refusing path {name!r}")
        data = _get(repo, name, token, opener)
        if f.get("sha256") and hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise FetchError(f"{name}: sha256 does not match the manifest")
        target.write_bytes(data)
    return manifest


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    token = os.environ.get("HF_SITE_READ_TOKEN", "").strip()
    if not token:
        print("HF_SITE_READ_TOKEN is not set")
        return 2
    try:
        manifest = fetch(argv[0], Path(argv[1]), token)
    except FetchError as e:
        print(f"fetch failed: {e}")
        return 1
    print(f"fetched {len(manifest['files'])} files, built {manifest.get('built_at_utc')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
