"""Uploads the question-bot bundle to the private site-data dataset under `bot/` (run by the owner, from the laptop, whenever the bundle changes).

  node p6_serving/bot/port/make_bot_bundle.mjs <bundle_folder>            (from p6_serving/bot/port; makes the chunks and bot_files.json)
  HF_SITE_WRITE_TOKEN=... python p6_serving/bootstrap/upload_bot_bundle.py <bundle_folder> [repo_id]      (default repo: Anonymous8392/packsense-site-data)

Before anything leaves the laptop the folder is checked against its own manifest with the same rules the Pages build applies (every required file, every chunk present,
sizes add up, sha256 matches, no stray file). Then ONE commit replaces the whole `bot/` folder (old chunks of a previous version are deleted in the same commit, so the
dataset never holds a half-old bundle). The token comes from the environment, is never printed, and `huggingface_hub` is imported only here (pip install it in a throw-away
environment: the Pages build does not need it). `--dry-run` checks the folder and prints what would be sent.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_site_data as fs  # noqa: E402

DEFAULT_REPO = "Anonymous8392/packsense-site-data"


def check_folder(folder: Path) -> list[str]:
    """The files to upload (names inside the folder), or raises FetchError with the first problem found."""
    manifest_path = folder / fs.BOT_MANIFEST
    if not manifest_path.is_file():
        raise fs.FetchError(f"{manifest_path} is missing: run make_bot_bundle.mjs first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise fs.FetchError("bot_files.json is not a bot manifest")
    missing = [n for n in fs.BOT_REQUIRED if n not in files or not files[n].get("chunks")]
    if missing:
        raise fs.FetchError(f"the bundle lacks required files: {', '.join(missing)}")
    names = [fs.BOT_MANIFEST]
    for name in fs.BOT_REQUIRED:
        total = 0
        for c in files[name]["chunks"]:
            path = c.get("path", "")
            if not fs.BOT_CHUNK.match(path) or not path.startswith(name + "."):
                raise fs.FetchError(f"refusing bot path {path!r}")
            data = (folder / path).read_bytes() if (folder / path).is_file() else None
            if data is None:
                raise fs.FetchError(f"{path}: the chunk is missing from the folder")
            if hashlib.sha256(data).hexdigest() != c.get("sha256") or len(data) != c.get("bytes"):
                raise fs.FetchError(f"{path}: does not match the manifest")
            total += len(data)
            names.append(path)
        if total != files[name].get("bytes"):
            raise fs.FetchError(f"{name}: the chunk sizes do not add up to the size in the manifest")
    stray = sorted(p.name for p in folder.iterdir() if p.name not in set(names))
    if stray:
        raise fs.FetchError(f"files in the folder that the manifest does not list: {', '.join(stray)}")
    return names


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if not argv or len(argv) > 2:
        print(__doc__)
        return 2
    folder, repo = Path(argv[0]), (argv[1] if len(argv) == 2 else DEFAULT_REPO)
    try:
        names = check_folder(folder)
    except fs.FetchError as e:
        print(f"refused: {e}")
        return 1
    size = sum((folder / n).stat().st_size for n in names)
    print(f"bundle ok: {len(names)} files, {size / 1e6:.1f} MB, to {repo} under bot/")
    if dry:
        print("dry run: nothing uploaded")
        return 0
    token = os.environ.get("HF_SITE_WRITE_TOKEN", "").strip()
    if not token:
        print("HF_SITE_WRITE_TOKEN is not set")
        return 2
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api = HfApi(token=token)
    ops = [CommitOperationAdd(path_in_repo=f"bot/{n}", path_or_fileobj=str(folder / n)) for n in names]
    stale = [f for f in api.list_repo_files(repo_id=repo, repo_type="dataset") if f.startswith("bot/") and f[len("bot/"):] not in set(names)]
    ops += [CommitOperationDelete(path_in_repo=f) for f in stale]
    manifest = json.loads((folder / fs.BOT_MANIFEST).read_text(encoding="utf-8"))
    api.create_commit(repo_id=repo, repo_type="dataset", operations=ops, commit_message=f"bot bundle {manifest.get('version')}")
    print(f"uploaded {len(names)} files, deleted {len(stale)} old ones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
