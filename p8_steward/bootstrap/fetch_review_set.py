"""Downloads the exported review set from the dev landing volume into output/review_set/ (gitignored: it is working material, never committed) and removes
it from the volume.

  python p8_steward/bootstrap/fetch_review_set.py --env-file .env [--keep-remote]
It NEVER writes to p4_modelling/fixtures (the committed fixture has the same file names; the fixture fetcher would overwrite it). The local copy is verified
(line count against the manifest) before the remote copy is deleted.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REMOTE_DIR = "/Volumes/workspace/packsense_dev/landing/_review_set"
FILES = ("stg_silver_versions.jsonl", "manifest.json")
LOCAL_DIR = Path(__file__).resolve().parents[2] / "output" / "review_set"


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--keep-remote", action="store_true")
    ap.add_argument("--name", help="a further part of the review set (for example dev2): fetched into its own folder output/review_set_<name>, never over the first part")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    remote_dir = REMOTE_DIR + (f"_{args.name}" if args.name else "")
    local_dir = LOCAL_DIR.with_name(LOCAL_DIR.name + (f"_{args.name}" if args.name else ""))
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    local_dir.mkdir(parents=True, exist_ok=True)
    present = {e.name for e in w.files.list_directory_contents(remote_dir)}
    if not set(FILES) <= present:
        sys.exit(f"expected {FILES} in {remote_dir}, found {sorted(present)}")
    for name in FILES:
        body = w.files.download(f"{remote_dir}/{name}").contents.read()
        (local_dir / name).write_bytes(body)
        print(f"downloaded {name}: {len(body)} bytes")
    manifest = json.loads((local_dir / "manifest.json").read_text(encoding="utf-8"))
    lines = (local_dir / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines()
    if len(lines) != manifest["version_rows"]:
        sys.exit(f"line count {len(lines)} differs from the manifest's {manifest['version_rows']}: remote copy kept")
    print(f"verified: {manifest['products']} products, {len(lines)} version rows")
    if not args.keep_remote:
        for name in FILES:
            w.files.delete(f"{remote_dir}/{name}")
        if not {e.name for e in w.files.list_directory_contents(remote_dir)}:
            w.files.delete_directory(remote_dir)
        print("removed the remote copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
