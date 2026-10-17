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
FILES = ("stg_silver_versions.jsonl", "manifest.json", "taxonomy_tag.jsonl", "taxonomy_manifest.json")
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
    present = {e.name for e in w.files.list_directory_contents(args.remote_dir)}
    got = []
    for name in FILES:
        if name not in present:
            continue
        body = w.files.download(f"{args.remote_dir}/{name}").contents.read()
        (LOCAL_DIR / name).write_bytes(body)
        got.append(name)
        print(f"downloaded {name}: {len(body)} bytes")
    if not got:
        sys.exit(f"nothing to fetch in {args.remote_dir}")

    # each data file comes with a manifest that names its row count
    for data, manifest_name, what in (("stg_silver_versions.jsonl", "manifest.json", "products"),
                                      ("taxonomy_tag.jsonl", "taxonomy_manifest.json", "taxonomy rows")):
        if data in got or manifest_name in got:
            if not (data in got and manifest_name in got):
                sys.exit(f"{data} and {manifest_name} must come together: remote copy kept")
            manifest = json.loads((LOCAL_DIR / manifest_name).read_text(encoding="utf-8"))
            lines = (LOCAL_DIR / data).read_text(encoding="utf-8").splitlines()
            if len(lines) != manifest["version_rows"]:
                sys.exit(f"{data}: line count {len(lines)} differs from the manifest's {manifest['version_rows']}: remote copy kept")
            print(f"verified {what}: {len(lines)} rows")

    if not args.keep_remote:
        for name in got:
            w.files.delete(f"{args.remote_dir}/{name}")
        if not {e.name for e in w.files.list_directory_contents(args.remote_dir)}:
            w.files.delete_directory(args.remote_dir)
        print("removed the remote copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
