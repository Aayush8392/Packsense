"""One-time setup of the India release job's objects (an admin runs it; the secret values are typed at a hidden prompt and never printed).

  python p6_serving/bootstrap/setup_release.py create-scope --env-file .env                                  makes the scope `packsense_release` (only the admin manages it)
  python p6_serving/bootstrap/setup_release.py put-secret --name hf_release_token --env-file .env             the Hugging Face WRITE token of the public release dataset
  python p6_serving/bootstrap/setup_release.py put-secret --name healthchecks_release_ping_url --env-file .env   the ping URL of the check `packsense-release`
  python p6_serving/bootstrap/setup_release.py list --env-file .env

The job `packsense-release` is admin-owned (no run_as): the exit function needs the plaintext contributor names that only bronze holds. The scope is therefore readable
by the admin only; p5_governance/grants.yml lists it, and the nightly drift check goes red if the scope's ACLs differ from that file.
Environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import sys

SCOPE = "packsense_release"
ALLOWED_SECRETS = ("hf_release_token", "healthchecks_release_ping_url")


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name, "").strip():
            sys.exit(f"missing environment variable: {name}")
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def cmd_create_scope() -> int:
    w = client()
    try:
        w.secrets.create_scope(scope=SCOPE)
        print(f"scope '{SCOPE}' created")
    except Exception as e:
        print(f"create_scope: {str(e)[:100]}")
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def cmd_put_secret(name: str, replace: bool) -> int:
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
    return 0


def cmd_list() -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-scope", "put-secret", "list"])
    ap.add_argument("--name")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "create-scope":
        return cmd_create_scope()
    if args.command == "put-secret":
        if args.name not in ALLOWED_SECRETS:
            sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
        return cmd_put_secret(args.name, args.replace)
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
