"""Fetches the checked site data from the private staging dataset on Hugging Face into a folder, verifying every file against the manifest.

  HF_SITE_READ_TOKEN=... python p6_serving/fetch_site_data.py <repo_id> <out_folder>

The question-bot bundle lives in the same private dataset under `bot/` (made by bot/port/make_bot_bundle.mjs, uploaded by bootstrap/upload_bot_bundle.py); its
own manifest `bot/bot_files.json` lists every chunk with its sha256, and the fetch refuses a bundle that lacks a required file, a chunk or a hash.

Standard library only (the Pages workflow runs it before anything is installed). The token comes from the environment and is never printed. It
downloads `site/release_manifest.json` first, then exactly the files that manifest lists (no directory listing), and refuses when a listed file is
missing, has a path outside the folder, or does not match its sha256. The licence gate runs on the result afterwards (a second, independent check:
the publish job ran it before uploading).
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MANIFEST = "release_manifest.json"
PREFIX = "site/"
BOT_PREFIX = "bot/"
BOT_MANIFEST = "bot_files.json"
# The files the browser bot needs: the same names as FILES in bot/port/make_bot_bundle.mjs (a test keeps the two lists equal).
BOT_REQUIRED = ("bot_data.json", "vocab.txt", "config.json", "manifest_int8.json", "learned_pairs.json", "wording_scales.f32", "wording_vectors_int8.bin", "shrunk_int8.bin")
BOT_CHUNK = re.compile(r"^[A-Za-z0-9_.-]+\.\d{3}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?$")      # a file in the folder, or in one sub-folder (cards/); never `..`
WORKERS = 8                                                          # about a thousand small card files: fetched in parallel


class FetchError(Exception):
    pass


def _get(repo: str, path: str, token: str, opener=urllib.request.urlopen, prefix: str = PREFIX) -> bytes:
    url = f"https://huggingface.co/datasets/{repo}/resolve/main/{urllib.parse.quote(prefix + path)}"
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
    jobs = []
    for f in manifest.get("files", []):
        name = f.get("path", "")
        target = (out / name).resolve()
        if not name or not SAFE_PATH.match(name) or ".." in name.split("/") or root not in target.parents:
            raise FetchError(f"refusing path {name!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        jobs.append((name, f.get("sha256"), target))

    def one(job):
        name, sha, target = job
        data = _get(repo, name, token, opener)
        if sha and hashlib.sha256(data).hexdigest() != sha:
            raise FetchError(f"{name}: sha256 does not match the manifest")
        target.write_bytes(data)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for _ in pool.map(one, jobs):          # the first failure is raised here; nothing is published after it
            pass
    return manifest


def fetch_bot(repo: str, out: Path, token: str, opener=urllib.request.urlopen) -> dict:
    """Fetch the bot bundle into <out>/bot/, refusing anything the manifest does not fully and correctly list."""
    bot = out / "bot"
    bot.mkdir(parents=True, exist_ok=True)
    manifest_bytes = _get(repo, BOT_MANIFEST, token, opener, BOT_PREFIX)
    try:
        manifest = json.loads(manifest_bytes)
        files = manifest["files"]
        assert isinstance(files, dict)
    except (ValueError, KeyError, AssertionError):
        raise FetchError("bot/bot_files.json is not a bot manifest") from None
    missing = [n for n in BOT_REQUIRED if n not in files or not files[n].get("chunks")]
    if missing:
        raise FetchError(f"the bot bundle lacks required files: {', '.join(missing)}")
    root = bot.resolve()
    jobs = []
    for name in BOT_REQUIRED:
        total = 0
        for c in files[name]["chunks"]:
            path, sha = c.get("path", ""), c.get("sha256", "")
            if not BOT_CHUNK.match(path) or not path.startswith(name + ".") or root not in (bot / path).resolve().parents:
                raise FetchError(f"refusing bot path {path!r}")
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise FetchError(f"bot/{path}: the manifest has no sha256")
            total += int(c.get("bytes", -1))
            jobs.append((path, sha, int(c["bytes"])))
        if total != files[name].get("bytes"):
            raise FetchError(f"{name}: the chunk sizes do not add up to the size in the manifest")

    def one(job):
        path, sha, size = job
        data = _get(repo, path, token, opener, BOT_PREFIX)
        if hashlib.sha256(data).hexdigest() != sha or len(data) != size:
            raise FetchError(f"bot/{path}: sha256 does not match the manifest")
        (bot / path).write_bytes(data)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for _ in pool.map(one, jobs):
            pass
    (bot / BOT_MANIFEST).write_bytes(manifest_bytes)           # written last: a folder with the manifest is a complete bundle
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
        bot = fetch_bot(argv[0], Path(argv[1]), token)
    except FetchError as e:
        print(f"fetch failed: {e}")
        return 1
    print(f"fetched {len(manifest['files'])} files, built {manifest.get('built_at_utc')}; bot bundle {bot.get('version')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
