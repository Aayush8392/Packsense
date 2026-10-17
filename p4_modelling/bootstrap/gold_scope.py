"""Creates a gold secret scope, lets the gold principal read it, and stores a secret in it (admin, run by the user).

  python p4_modelling/bootstrap/gold_scope.py create --scope packsense_gold_dev --principal <client id> --env-file .env
  python p4_modelling/bootstrap/gold_scope.py put-secret --scope packsense_gold_dev --name oauth_client_secret --env-file .env
  python p4_modelling/bootstrap/gold_scope.py list --scope packsense_gold_dev --env-file .env

A gold scope holds only what the gold job needs: `oauth_client_id`, `oauth_client_secret` (the principal's own credential for dbt) and,
in prod, `healthchecks_gold_ping_url`. The value is typed at a hidden prompt, never echoed or printed. A scope has no per-key
permission, so READ on it covers all of its secrets: that is why the gold scopes are separate from `packsense`.
Environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import re
import sys

ALLOWED_SCOPES = ("packsense_gold_dev", "packsense_gold")
ALLOWED_SECRETS = ("oauth_client_id", "oauth_client_secret", "healthchecks_gold_ping_url")


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def check_scope(scope: str) -> str:
    if scope not in ALLOWED_SCOPES:
        sys.exit(f"scope must be one of {ALLOWED_SCOPES}; the real `packsense` scope is never touched by this script")
    return scope


def check_secret_name(name: str) -> str:
    if name not in ALLOWED_SECRETS:
        sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
    return name


def check_principal(principal: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", principal or ""):
        sys.exit("principal must be the service principal's application (client) id, a UUID")
    return principal


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name, "").strip():
            sys.exit(f"missing environment variable: {name}")
    # A shell that still holds a principal's client id and secret (from a dbt or bundle run) would make the SDK see two auth methods:
    # this script is admin-only, so ignore those and say that the token is the one in use.
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def cmd_create(scope: str, principal: str) -> int:
    from databricks.sdk.service import workspace
    w = client()
    try:
        w.secrets.create_scope(scope=scope)
        print(f"scope '{scope}' created")
    except Exception as e:  # already exists is fine
        print(f"create_scope: {str(e)[:100]}")
    w.secrets.put_acl(scope=scope, principal=principal, permission=workspace.AclPermission.READ)
    print(f"'{principal}' can READ scope '{scope}'")
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=scope)])
    return 0


def cmd_put_secret(scope: str, name: str, replace: bool) -> int:
    w = client()
    exists = any(s.key == name for s in w.secrets.list_secrets(scope=scope))
    if exists and not replace:
        sys.exit(f"'{name}' already exists in scope '{scope}': nothing changed (use --replace to overwrite it)")
    value = getpass.getpass(f"value for '{name}' (hidden, not echoed): ").strip()
    if not value:
        sys.exit("empty value: nothing stored")
    w.secrets.put_secret(scope=scope, key=name, string_value=value)
    del value
    print(f"stored '{name}' in scope '{scope}' ({'replaced' if exists else 'new'}); the value was not printed")
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=scope)))
    return 0


def cmd_list(scope: str) -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=scope)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=scope)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "put-secret", "list"])
    ap.add_argument("--scope", required=True)
    ap.add_argument("--principal", help="create: the gold principal's application (client) id")
    ap.add_argument("--name", help="put-secret: the secret's name in the scope")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    scope = check_scope(args.scope)
    if args.command == "create":
        return cmd_create(scope, check_principal(args.principal))
    if args.command == "put-secret":
        return cmd_put_secret(scope, check_secret_name(args.name), args.replace)
    return cmd_list(scope)


if __name__ == "__main__":
    sys.exit(main())
