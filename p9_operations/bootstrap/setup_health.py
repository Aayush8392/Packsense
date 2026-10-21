"""One-time setup of the pipeline-health job's objects (an admin runs it; the ping URL is typed at a hidden prompt and never printed).

  python p9_operations/bootstrap/setup_health.py create-schema --env-file .env      makes the schema workspace.packsense_health and the table health_metric_daily (as the admin)
  python p9_operations/bootstrap/setup_health.py create-scope --env-file .env       makes the scope `packsense_health` (only the admin manages it; the admin-owned job reads it)
  python p9_operations/bootstrap/setup_health.py put-secret --name healthchecks_health_ping_url --env-file .env
  python p9_operations/bootstrap/setup_health.py remove-principal --env-file .env   removes the unused service principal `packsense-health` and its scope ACL (see below)
  python p9_operations/bootstrap/setup_health.py list --env-file .env

There is no service principal for this job: Free Edition lets nobody grant the system tables to another identity (GRANT on the `system` catalog needs MANAGE, which not even the
admin holds; measured 2026-10-21), so the job is admin-owned like `packsense-policy`. A principal `packsense-health` was created first and refused the grants; `remove-principal`
cleans it up. The grants on the one table the publish job reads come from p5_governance/grants.yml (`apply_grants.py apply`).
Environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "packsense-health"
SCOPE = "packsense_health"
SCHEMA = ("workspace", "packsense_health")
ALLOWED_SECRETS = ("healthchecks_health_ping_url",)


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


def find_principal(w):
    found = [sp for sp in w.service_principals.list(filter=f'displayName eq "{NAME}"')]
    return found[0] if found else None


def cmd_create_schema() -> int:
    """The schema AND the table are made by the admin, who also owns the job that writes to it."""
    w = client()
    catalog, schema = SCHEMA
    try:
        w.schemas.create(name=schema, catalog_name=catalog)
        print(f"schema {catalog}.{schema} created")
    except Exception as e:
        print(f"create schema: {str(e)[:120]}")
    sys.path.insert(0, str(ROOT / "p9_operations"))
    import health_lib
    warehouse = os.environ.get("DBT_HTTP_PATH", "/sql/1.0/warehouses/c9e35ecf0a03295d").rstrip("/").split("/")[-1]   # the Serverless Starter 2X-Small: an address, not a secret
    r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=health_lib.ddl(), wait_timeout="50s")
    print(f"create table {health_lib.FULL_TABLE}: {r.status.state.value}")
    print("schemas of the catalog:", sorted(s.name for s in w.schemas.list(catalog_name=catalog) if s.name.startswith("packsense")))
    return 0


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


def cmd_remove_principal() -> int:
    """Delete the unused principal and its READ ACL on the scope (a leftover ACL for a deleted id would show as an extra grant in the nightly drift check)."""
    w = client()
    sp = find_principal(w)
    if sp is None:
        print(f"no service principal named {NAME}: nothing to remove")
    else:
        try:
            w.secrets.delete_acl(scope=SCOPE, principal=sp.application_id)
            print("scope ACL of the principal removed")
        except Exception as e:
            print(f"scope ACL: {str(e)[:100]}")
        w.service_principals.delete(id=sp.id)
        print(f"service principal {NAME} deleted")
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def cmd_list() -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-schema", "create-scope", "put-secret", "remove-principal", "list"])
    ap.add_argument("--name")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "create-schema":
        return cmd_create_schema()
    if args.command == "create-scope":
        return cmd_create_scope()
    if args.command == "put-secret":
        if args.name not in ALLOWED_SECRETS:
            sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
        return cmd_put_secret(args.name, args.replace)
    if args.command == "remove-principal":
        return cmd_remove_principal()
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
