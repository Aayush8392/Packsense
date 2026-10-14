"""Creates the HMAC key that scrambles contributor usernames in silver, and stores it in a Databricks secret scope.

The key is 32 random bytes (hex-encoded, 64 characters), generated in memory here. It is never printed, never written to a
file and never sent anywhere except the secret scope. There is deliberately no escrow copy: if the key is lost, a new
one is created (hmac_key_v2) and silver is rebuilt from bronze; every contributor then gets a new code.

Safe by construction: if the secret already exists the script stops and changes nothing. Rotation is a separate,
deliberate runbook, not this script.

After storing the key, a one-off serverless run reads it back inside Databricks and returns only its length and a
key-check value (the first 8 hex characters of HMAC-SHA256(key, "packsense-key-check")). The script computes the same
value locally and compares, which proves the scope, the job path and the stored key agree. The temporary notebook
is deleted afterwards. The key-check value is not secret and cannot be used to recover the key.

  python p2_lakehouse/bootstrap/create_hmac_key.py create  [--env-file PATH]   generate, store, verify
  python p2_lakehouse/bootstrap/create_hmac_key.py check   [--env-file PATH]   read the stored key in a job, print length + key-check value
  python p2_lakehouse/bootstrap/create_hmac_key.py dry-run                     generate a key in memory, show the key-check value, touch nothing
  python p2_lakehouse/bootstrap/create_hmac_key.py put-secret --name NAME [--replace] [--env-file PATH]
                                                                               store another secret (e.g. a healthchecks ping URL) in the
                                                                               same scope; the value is typed at a hidden prompt, never echoed

Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed.
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from datetime import timedelta

SCOPE = "packsense"
SECRET = "hmac_key_v1"
CHECK_WORD = b"packsense-key-check"

NOTEBOOK = f'''# Databricks notebook source
import hashlib, hmac, json
k = dbutils.secrets.get("{SCOPE}", "{SECRET}")
dbutils.notebook.exit(json.dumps({{"length": len(k), "check": hmac.new(k.encode(), {CHECK_WORD!r}, hashlib.sha256).hexdigest()[:8]}}))
'''


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def key_check(key: str) -> str:
    return hmac.new(key.encode(), CHECK_WORD, hashlib.sha256).hexdigest()[:8]


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name, "").strip():
            sys.exit(f"missing environment variable: {name}")
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])


def read_back(w) -> dict:
    """Run a one-off serverless notebook that reads the stored key and returns its length and key-check value."""
    from databricks.sdk.service import jobs, workspace
    me = w.current_user.me().user_name
    folder = f"/Users/{me}/packsense_scratch"
    path = f"{folder}/hmac_check"
    w.workspace.mkdirs(folder)
    w.workspace.import_(path=path, format=workspace.ImportFormat.SOURCE, language=workspace.Language.PYTHON,
                        content=base64.b64encode(NOTEBOOK.encode()).decode(), overwrite=True)
    try:
        run = w.jobs.submit(run_name="packsense-hmac-key-check", tasks=[jobs.SubmitTask(
            task_key="check", notebook_task=jobs.NotebookTask(notebook_path=path))]).result(timeout=timedelta(minutes=20))
        out = w.jobs.get_run_output(run_id=run.tasks[0].run_id)
        if not (out.notebook_output and out.notebook_output.result):
            sys.exit("the check run returned no output: " + (run.state.state_message or "")[:300] + (out.error or "")[:300])
        return json.loads(out.notebook_output.result)
    finally:
        w.workspace.delete(folder, recursive=True)
        print("temporary notebook folder deleted")


def cmd_dry_run() -> int:
    key = secrets.token_hex(32)
    print(f"dry run: generated a {len(key)}-character key in memory; key-check value {key_check(key)}; nothing stored")
    return 0


def cmd_create() -> int:
    w = client()
    try:
        w.secrets.create_scope(scope=SCOPE)
        print(f"scope '{SCOPE}' created")
    except Exception as e:  # already exists is fine; anything else shows up at the next call
        print(f"create_scope: {str(e)[:100]}")
    if any(s.key == SECRET for s in w.secrets.list_secrets(scope=SCOPE)):
        sys.exit(f"'{SECRET}' already exists in scope '{SCOPE}': nothing changed (rotation is a separate runbook)")
    key = secrets.token_hex(32)
    expected = key_check(key)
    w.secrets.put_secret(scope=SCOPE, key=SECRET, string_value=key)
    del key
    print(f"stored '{SECRET}' in scope '{SCOPE}'")
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    got = read_back(w)
    ok = got.get("check") == expected and got.get("length") == 64
    print(f"read back inside Databricks: length {got.get('length')}, key-check {got.get('check')} (local {expected}) -> {'OK' if ok else 'MISMATCH'}")
    print(f"record this non-secret key-check value: {expected}")
    return 0 if ok else 1


def check_secret_name(name: str) -> str:
    """A name this command may write: plain characters only, and never the HMAC key itself."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name or ""):
        sys.exit("secret name must be 1-128 characters of letters, digits, underscore, dot or hyphen")
    if name.startswith("hmac_key"):
        sys.exit("refusing to touch an HMAC key with put-secret (rotation is a separate runbook)")
    return name


def cmd_put_secret(name: str, replace: bool) -> int:
    check_secret_name(name)
    w = client()
    exists = any(s.key == name for s in w.secrets.list_secrets(scope=SCOPE))
    if exists and not replace:
        sys.exit(f"'{name}' already exists in scope '{SCOPE}': nothing changed (use --replace to overwrite it)")
    value = getpass.getpass(f"value for '{name}' (hidden, not echoed): ").strip()
    if not value:
        sys.exit("empty value: nothing stored")
    w.secrets.put_secret(scope=SCOPE, key=name, string_value=value)
    del value
    print(f"stored '{name}' in scope '{SCOPE}' ({'replaced' if exists else 'new'}); the value was not printed")
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    return 0


def cmd_check() -> int:
    got = read_back(client())
    print(f"stored key: length {got.get('length')}, key-check {got.get('check')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "check", "dry-run", "put-secret"])
    ap.add_argument("--env-file")
    ap.add_argument("--name", help="put-secret: the secret's name in the scope")
    ap.add_argument("--replace", action="store_true", help="put-secret: overwrite an existing secret")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "put-secret":
        if not args.name:
            sys.exit("put-secret needs --name")
        return cmd_put_secret(args.name, args.replace)
    return {"create": cmd_create, "check": cmd_check, "dry-run": cmd_dry_run}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
