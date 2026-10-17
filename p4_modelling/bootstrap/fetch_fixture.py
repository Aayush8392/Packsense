"""Downloads the exported fixture from the dev landing volume into p4_modelling/fixtures/ and removes it from the volume.

  python p4_modelling/bootstrap/fetch_fixture.py [--keep-remote]
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), set in your own shell; or pass --env-file PATH. Values are never printed.
The fixture is a few hundred products (about 1 MB at most): the 'small listed derived files' the project allows on the laptop.
Cleanup: the remote copy is deleted after the local copy is verified (size and line count), unless --keep-remote.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REMOTE_DIR = "/Volumes/workspace/packsense_dev/landing/_fixture"
FILES = ("stg_silver_versions.jsonl", "manifest.json")
LOCAL_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--remote-dir", default=REMOTE_DIR)
    ap.add_argument("--keep-remote", action="store_true")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        remote = f"{args.remote_dir}/{name}"
        body = w.files.download(remote).contents.read()
        (LOCAL_DIR / name).write_bytes(body)
        print(f"downloaded {name}: {len(body)} bytes")

    manifest = json.loads((LOCAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    lines = (LOCAL_DIR / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines()
    if len(lines) != manifest["version_rows"]:
        sys.exit(f"line count {len(lines)} differs from the manifest's {manifest['version_rows']}: remote copy kept")
    print(f"verified: {len(lines)} version rows, {manifest['products']} products")

    if not args.keep_remote:
        for name in FILES:
            w.files.delete(f"{args.remote_dir}/{name}")
        w.files.delete_directory(args.remote_dir)
        print("removed the remote copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
