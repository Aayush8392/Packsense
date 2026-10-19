"""Creates the secret scope `packsense_policy` and stores its secrets (an admin runs it; the values are typed at a hidden prompt).

  python p5_governance/bootstrap/policy_scope.py create --env-file .env
  python p5_governance/bootstrap/policy_scope.py put-secret --name pipeline_user_token --env-file .env
  python p5_governance/bootstrap/policy_scope.py put-secret --name analyst_token --env-file .env
  python p5_governance/bootstrap/policy_scope.py put-secret --name healthchecks_policy_ping_url --env-file .env
  python p5_governance/bootstrap/policy_scope.py list --env-file .env

The scope is read only by the admin-owned policy job: it holds the pipeline user's and the analyst's own tokens (low-privilege, expiring)
so the job can sign in as them and prove what they cannot do, plus the ping URL of the `packsense-policy` healthchecks check. No service
principal can read it and it holds no principal secret. A value is never echoed or printed.
Environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import sys

SCOPE = "packsense_policy"
ALLOWED_SECRETS = ("pipeline_user_token", "analyst_token", "healthchecks_policy_ping_url")


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def check_secret_name(name: str) -> str:
    if name not in ALLOWED_SECRETS:
        sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
    return name


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name, "").strip():
            sys.exit(f"missing environment variable: {name}")
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):    # a stray principal login would make the SDK see two auth methods
        os.environ.pop(name, None)
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def cmd_create() -> int:
    w = client()
    try:
        w.secrets.create_scope(scope=SCOPE)
        print(f"scope '{SCOPE}' created")
    except Exception as e:  # already exists is fine
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
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    return 0


def cmd_list() -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "put-secret", "list"])
    ap.add_argument("--name", help="put-secret: the secret's name in the scope")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "create":
        return cmd_create()
    if args.command == "put-secret":
        return cmd_put_secret(check_secret_name(args.name), args.replace)
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
